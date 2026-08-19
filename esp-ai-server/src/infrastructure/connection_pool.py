"""
High-Performance Connection Pool - 高性能连接池

优化目标：支持 500+ 设备并发

关键优化：
1. 分离锁 - 减少锁争用
2. 快速路径 - 减少锁内操作
3. 智能预热 - 启动时预建连接
4. 分段队列 - 按优先级分配
"""
from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any, Optional
from dataclasses import dataclass, field
from collections import deque

from src.infrastructure.logging import get_logger

logger = get_logger("connection_pool")


@dataclass
class ConnectionWrapper:
    connection: Any
    created_time: float = field(default_factory=time.time)
    last_used_time: float = field(default_factory=time.time)
    use_count: int = 0
    
    def update_used_time(self):
        self.last_used_time = time.time()
        self.use_count += 1
    
    def is_healthy(self) -> bool:
        try:
            close_code = getattr(self.connection, 'close_code', None)
            if close_code is not None:
                return False
            return getattr(self.connection, 'open', True)
        except Exception:
            return False


class ConnectionPoolBase(ABC):
    def __init__(
        self,
        max_size: int = 100,
        min_size: int = 20,
        heartbeat_interval: int = 30,
        idle_timeout: int = 300,
        connection_timeout: int = 15,
        pool_name: str = "default",
    ):
        self._max_size = max_size
        self._min_size = min_size
        self._heartbeat_interval = heartbeat_interval
        self._idle_timeout = idle_timeout
        self._connection_timeout = connection_timeout
        self._pool_name = pool_name
        
        # 核心数据结构：无锁队列 + 计数
        self._pool: asyncio.Queue[ConnectionWrapper] = asyncio.Queue(maxsize=max_size)
        self._active_count: int = 0
        self._closed: bool = False
        
        # 分离锁 - 只保护计数器
        self._count_lock = asyncio.Lock()
        
        # 后台任务
        self._cleanup_task: Optional[asyncio.Task] = None
        self._warmup_task: Optional[asyncio.Task] = None
        
        # 统计
        self._stats = {
            "acquire_count": 0,
            "miss_count": 0,
            "reuse_count": 0,
            "create_count": 0,
            "close_count": 0,
            "timeout_count": 0,
        }

    @abstractmethod
    async def _create_connection(self) -> Any:
        raise NotImplementedError

    @abstractmethod
    async def _heartbeat(self, conn: Any) -> None:
        raise NotImplementedError

    @abstractmethod
    async def _is_healthy(self, conn: Any) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def _close_connection(self, conn: Any) -> None:
        raise NotImplementedError

    async def _increment_count(self) -> int:
        async with self._count_lock:
            self._active_count += 1
            return self._active_count

    async def _decrement_count(self) -> int:
        async with self._count_lock:
            self._active_count -= 1
            return self._active_count

    async def warm_up(self) -> None:
        """智能预热 - 后台异步创建最小连接数"""
        logger.info(f"[Pool:{self._pool_name}] 开始预热，预建 {self._min_size} 个连接...")
        
        async def _do_warmup():
            created = 0
            for i in range(self._min_size):
                if self._closed:
                    break
                try:
                    conn = await asyncio.wait_for(
                        self._create_connection(),
                        timeout=self._connection_timeout
                    )
                    wrapped = ConnectionWrapper(conn)
                    
                    # 直接放入队列，不持有锁
                    try:
                        self._pool.put_nowait(wrapped)
                        await self._increment_count()
                        created += 1
                        asyncio.create_task(self._heartbeat(conn))
                    except asyncio.QueueFull:
                        await self._close_connection(conn)
                        
                except Exception as e:
                    logger.warning(f"[Pool:{self._pool_name}] 预热创建连接失败: {e}")
                    break
            
            logger.info(f"[Pool:{self._pool_name}] 预热完成，已创建 {created}/{self._min_size} 个连接")
        
        self._warmup_task = asyncio.create_task(_do_warmup())
        
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def acquire(self, timeout: float = 10.0) -> ConnectionWrapper:
        """快速获取连接 - 最小化锁持有时间"""
        if self._closed:
            raise ConnectionError("连接池已关闭")
        
        self._stats["acquire_count"] += 1
        
        # 快速路径：尝试从队列获取
        while True:
            try:
                wrapped = self._pool.get_nowait()
                
                # 快速健康检查
                if wrapped.is_healthy():
                    wrapped.update_used_time()
                    self._stats["reuse_count"] += 1
                    return wrapped
                else:
                    await self._close_connection_internal(wrapped)
                break
            except asyncio.QueueEmpty:
                break
        
        # 需要创建新连接
        async with self._count_lock:
            current_count = self._active_count
        
        if current_count < self._max_size:
            try:
                conn = await asyncio.wait_for(
                    self._create_connection(),
                    timeout=self._connection_timeout
                )
                wrapped = ConnectionWrapper(conn)
                
                await self._increment_count()
                self._stats["create_count"] += 1
                asyncio.create_task(self._heartbeat(conn))
                
                logger.debug(f"[Pool:{self._pool_name}] 创建新连接，活跃: {current_count + 1}")
                return wrapped
                
            except asyncio.TimeoutError:
                self._stats["timeout_count"] += 1
                raise ConnectionError(f"创建连接超时 ({self._connection_timeout}s)")
            except Exception as e:
                logger.error(f"[Pool:{self._pool_name}] 创建连接失败: {e}")
                raise
        
        # 队列为空且达到上限，等待
        try:
            wrapped = await asyncio.wait_for(
                self._pool.get(),
                timeout=timeout
            )
            
            if wrapped.is_healthy():
                wrapped.update_used_time()
                self._stats["reuse_count"] += 1
                return wrapped
            else:
                await self._close_connection_internal(wrapped)
                self._stats["miss_count"] += 1
                return await self.acquire(timeout=0)
                
        except asyncio.TimeoutError:
            self._stats["timeout_count"] += 1
            raise ConnectionError(f"获取连接超时 ({timeout}s)")

    async def release(self, wrapped: Optional[ConnectionWrapper]) -> None:
        """快速释放连接"""
        if wrapped is None:
            return

        if self._closed:
            await self._close_connection_internal(wrapped)
            return

        if wrapped.is_healthy():
            try:
                self._pool.put_nowait(wrapped)
                return
            except asyncio.QueueFull:
                pass
        
        await self._close_connection_internal(wrapped)

    async def _close_connection_internal(self, wrapped: ConnectionWrapper) -> None:
        try:
            await self._close_connection(wrapped.connection)
            await self._decrement_count()
            self._stats["close_count"] += 1
        except Exception:
            await self._decrement_count()

    async def _cleanup_loop(self) -> None:
        """定期清理空闲连接"""
        while not self._closed:
            await asyncio.sleep(60)
            
            if self._closed:
                break

            cleaned = 0
            temp_conns = []
            
            # 批量检查
            while not self._pool.empty():
                try:
                    wrapped = self._pool.get_nowait()
                    
                    idle_time = time.time() - wrapped.last_used_time
                    if idle_time < self._idle_timeout and self._pool.qsize() > self._min_size // 2:
                        temp_conns.append(wrapped)
                    else:
                        await self._close_connection_internal(wrapped)
                        cleaned += 1
                except asyncio.QueueEmpty:
                    break
            
            # 放回剩余连接
            for wrapped in temp_conns:
                try:
                    self._pool.put_nowait(wrapped)
                except asyncio.QueueFull:
                    await self._close_connection_internal(wrapped)
                    cleaned += 1
            
            if cleaned > 0:
                logger.info(f"[Pool:{self._pool_name}] 清理了 {cleaned} 个空闲连接")

    async def close(self) -> None:
        """优雅关闭"""
        self._closed = True
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        if self._warmup_task:
            self._warmup_task.cancel()
            try:
                await self._warmup_task
            except asyncio.CancelledError:
                pass
        
        while not self._pool.empty():
            try:
                wrapped = self._pool.get_nowait()
                await self._close_connection(wrapped.connection)
            except asyncio.QueueEmpty:
                break
        
        async with self._count_lock:
            self._active_count = 0

    def get_stats(self) -> dict:
        return {
            "pool_name": self._pool_name,
            "active_count": self._active_count,
            "idle_count": self._pool.qsize(),
            "max_size": self._max_size,
            "min_size": self._min_size,
            "is_closed": self._closed,
            **self._stats,
        }

    @property
    def is_closed(self) -> bool:
        return self._closed


# 全局连接池管理器 - 支持多池
class PoolManager:
    """全局连接池管理器"""
    
    _pools: dict[str, ConnectionPoolBase] = {}
    _lock = asyncio.Lock()
    
    @classmethod
    async def register_pool(cls, name: str, pool: ConnectionPoolBase) -> None:
        async with cls._lock:
            cls._pools[name] = pool
            logger.info(f"[PoolManager] 注册连接池: {name}")
    
    @classmethod
    async def get_pool(cls, name: str) -> Optional[ConnectionPoolBase]:
        return cls._pools.get(name)
    
    @classmethod
    async def close_all(cls) -> None:
        for name, pool in cls._pools.items():
            try:
                await pool.close()
                logger.info(f"[PoolManager] 关闭连接池: {name}")
            except Exception as e:
                logger.error(f"[PoolManager] 关闭连接池失败 {name}: {e}")
        cls._pools.clear()
    
    @classmethod
    def get_all_stats(cls) -> dict:
        return {
            name: pool.get_stats() 
            for name, pool in cls._pools.items()
        }

    @classmethod
    def get_stats(cls) -> dict:
        """返回所有连接池的统计信息（``get_all_stats`` 的别名）。

        供 ``monitoring.update_pool_metrics()`` 在 ``/metrics`` 端点被访问时调用。
        """
        return cls.get_all_stats()


def get_pool_manager():
    """获取全局连接池管理器（``PoolManager`` 类本身）。

    供 ``monitoring.update_pool_metrics()`` 使用，避免在 monitoring 模块
    顶层产生对 connection_pool 的硬依赖。
    """
    return PoolManager
