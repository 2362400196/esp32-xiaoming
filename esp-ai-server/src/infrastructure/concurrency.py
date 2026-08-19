"""
并发控制模块 - 全局并发限制和线程池管理

提供:
- 全局会话并发限制 (Semaphore)
- CPU 密集型任务的线程池
- 性能统计
"""
from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any, Callable, Optional, TypeVar

from .logging import get_logger
from .config import get_settings

logger = get_logger("concurrency")

T = TypeVar('T')

# 全局并发控制
_global_semaphore: Optional[asyncio.Semaphore] = None
_global_semaphore_max: int = 30
# 公开计数器（替代 _global_semaphore._value 私有属性访问）
_available_count: int = 30

# CPU 密集型任务线程池
_process_pool: Optional[concurrent.futures.ThreadPoolExecutor] = None


def init_concurrency_control():
    """初始化并发控制模块"""
    global _global_semaphore, _process_pool, _global_semaphore_max, _available_count

    settings = get_settings()
    config = settings.performance

    # 初始化全局并发控制
    if config.enable_global_concurrency_limit:
        _global_semaphore_max = config.global_max_concurrent_sessions
        _global_semaphore = asyncio.Semaphore(_global_semaphore_max)
        _available_count = _global_semaphore_max
        logger.info(f"[Concurrency] 全局会话并发限制: {_global_semaphore_max}")
    else:
        logger.info("[Concurrency] 全局并发限制已禁用")

    # 初始化线程池
    _process_pool = concurrent.futures.ThreadPoolExecutor(
        max_workers=config.process_pool_max_workers,
        thread_name_prefix="espai-cpu"
    )
    logger.info(f"[Concurrency] CPU 线程池初始化: {config.process_pool_max_workers} 个 worker")


async def acquire_global_slot() -> bool:
    """
    获取全局并发插槽（阻塞等待直到有可用插槽）

    Returns:
        bool: 是否成功获取
    """
    global _available_count
    if _global_semaphore is None:
        return True  # 未启用限制

    await _global_semaphore.acquire()
    _available_count = max(0, _available_count - 1)
    logger.debug(f"[Concurrency] 获取插槽成功，剩余: {_available_count}/{_global_semaphore_max}")
    return True


async def try_acquire_global_slot(timeout: float = 0.0) -> bool:
    """尝试获取全局并发插槽

    Args:
        timeout: 超时秒数。0 表示非阻塞（有可用插槽才获取，否则立即返回 False）

    Returns:
        bool: 是否成功获取
    """
    global _available_count
    if _global_semaphore is None:
        return True  # 未启用限制

    if timeout <= 0:
        # 非阻塞：检查信号量是否可用
        if _global_semaphore.locked():
            return False
        # 有可用插槽，尝试获取
        try:
            _global_semaphore.acquire_nowait()
        except Exception:
            return False
    else:
        # 带超时等待
        try:
            await asyncio.wait_for(_global_semaphore.acquire(), timeout=timeout)
        except asyncio.TimeoutError:
            return False

    _available_count = max(0, _available_count - 1)
    logger.debug(f"[Concurrency] 获取插槽成功，剩余: {_available_count}/{_global_semaphore_max}")
    return True


def release_global_slot():
    """释放全局并发插槽"""
    global _available_count
    if _global_semaphore is None:
        return

    try:
        _global_semaphore.release()
        _available_count = min(_global_semaphore_max, _available_count + 1)
        logger.debug(f"[Concurrency] 释放插槽，剩余: {_available_count}/{_global_semaphore_max}")
    except ValueError:
        logger.warning("[Concurrency] 尝试释放过多插槽")


async def run_in_executor(func: Callable[..., T], *args, **kwargs) -> T:
    """
    在 CPU 线程池中执行函数（异步方式）

    Args:
        func: 要执行的函数
        *args: 位置参数
        **kwargs: 关键字参数

    Returns:
        T: 函数返回值
    """
    if _process_pool is None:
        init_concurrency_control()

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _process_pool,
        lambda: func(*args, **kwargs)
    )


def get_stats() -> dict[str, Any]:
    """获取并发控制统计信息"""
    return {
        "global_concurrency_limit_enabled": _global_semaphore is not None,
        "global_concurrency_max": _global_semaphore_max,
        "global_concurrency_available": _available_count,
        "process_pool_initialized": _process_pool is not None,
    }


def shutdown():
    """关闭并发控制模块"""
    global _process_pool
    if _process_pool:
        logger.info("[Concurrency] 正在关闭线程池...")
        _process_pool.shutdown(wait=True)
        _process_pool = None
        logger.info("[Concurrency] 线程池已关闭")
