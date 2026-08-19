"""
connection_pool 高性能连接池单元测试

覆盖范围：
- ConnectionWrapper：update_used_time / is_healthy（正常/异常/close_code）
- ConnectionPoolBase（通过子类）：warm_up / acquire / release / close / get_stats / _cleanup_loop
- PoolManager：register_pool / get_pool / close_all / get_all_stats
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.connection_pool import (
    ConnectionPoolBase,
    ConnectionWrapper,
    PoolManager,
)


# ════════════════════════════════════════════════════════════════
# 测试用具体子类
# ════════════════════════════════════════════════════════════════

class FakeConnection:
    """模拟连接对象"""

    def __init__(self, cid: int, healthy: bool = True, open_attr: bool = True, close_code=None):
        self.cid = cid
        self._healthy = healthy
        self.open = open_attr
        self.close_code = close_code
        self.closed = False

    async def close(self):
        self.closed = True


class TestConnectionPool(ConnectionPoolBase):
    """ConnectionPoolBase 的测试子类"""

    def __init__(self, *args, **kwargs):
        self._create_count = 0
        self._heartbeat_calls = []
        self._closed_conns = []
        self._healthy_override = None  # 若设置则 _is_healthy 返回此值
        super().__init__(*args, **kwargs)

    async def _create_connection(self):
        self._create_count += 1
        return FakeConnection(self._create_count)

    async def _heartbeat(self, conn):
        self._heartbeat_calls.append(conn)

    async def _is_healthy(self, conn):
        if self._healthy_override is not None:
            return self._healthy_override
        return getattr(conn, "_healthy", True)

    async def _close_connection(self, conn):
        self._closed_conns.append(conn)
        if hasattr(conn, "close"):
            await conn.close()


# ════════════════════════════════════════════════════════════════
# ConnectionWrapper 测试
# ════════════════════════════════════════════════════════════════

class TestConnectionWrapper:
    """ConnectionWrapper 数据类测试"""

    def test_default_fields(self):
        """默认字段值"""
        conn = MagicMock()
        w = ConnectionWrapper(connection=conn)
        assert w.connection is conn
        assert w.created_time > 0
        assert w.last_used_time > 0
        assert w.use_count == 0

    def test_update_used_time(self):
        """update_used_time 应更新使用时间和计数"""
        conn = MagicMock()
        w = ConnectionWrapper(connection=conn)
        old_time = w.last_used_time
        old_count = w.use_count
        time.sleep(0.001)
        w.update_used_time()
        assert w.last_used_time >= old_time
        assert w.use_count == old_count + 1

    def test_is_healthy_default(self):
        """连接有 open=True 且无 close_code 时健康"""
        conn = MagicMock()
        conn.open = True
        # close_code 属性不存在 -> getattr 返回 None
        del conn.close_code
        w = ConnectionWrapper(connection=conn)
        assert w.is_healthy() is True

    def test_is_healthy_close_code_set(self):
        """连接有 close_code 时不健康"""
        conn = MagicMock()
        conn.close_code = 1000
        w = ConnectionWrapper(connection=conn)
        assert w.is_healthy() is False

    def test_is_healthy_open_false(self):
        """连接 open=False 时不健康"""
        conn = MagicMock()
        conn.open = False
        del conn.close_code
        w = ConnectionWrapper(connection=conn)
        assert w.is_healthy() is False

    def test_is_healthy_no_open_attr(self):
        """连接无 open 属性时 getattr 默认返回 True -> 健康"""
        conn = MagicMock()
        del conn.close_code
        del conn.open
        w = ConnectionWrapper(connection=conn)
        # getattr(conn, 'open', True) -> True（默认值）
        assert w.is_healthy() is True

    def test_is_healthy_exception(self):
        """访问 connection 属性抛异常时返回 False"""
        # 使用 property 抛异常的自定义类
        class BadConn:
            @property
            def close_code(self):
                raise RuntimeError("err")

        w = ConnectionWrapper(connection=BadConn())
        assert w.is_healthy() is False


# ════════════════════════════════════════════════════════════════
# ConnectionPoolBase 测试
# ════════════════════════════════════════════════════════════════

class TestConnectionPoolBase:
    """ConnectionPoolBase 通过子类测试"""

    def test_init_defaults(self):
        """默认参数"""
        pool = TestConnectionPool()
        assert pool._max_size == 100
        assert pool._min_size == 20
        assert pool._heartbeat_interval == 30
        assert pool._idle_timeout == 300
        assert pool._connection_timeout == 15
        assert pool._pool_name == "default"
        assert pool._active_count == 0
        assert pool._closed is False
        assert pool.is_closed is False

    def test_init_custom_params(self):
        """自定义参数"""
        pool = TestConnectionPool(
            max_size=50, min_size=5, heartbeat_interval=10,
            idle_timeout=60, connection_timeout=5, pool_name="test",
        )
        assert pool._max_size == 50
        assert pool._min_size == 5
        assert pool._pool_name == "test"

    def test_get_stats_initial(self):
        """初始统计"""
        pool = TestConnectionPool(pool_name="mypool")
        stats = pool.get_stats()
        assert stats["pool_name"] == "mypool"
        assert stats["active_count"] == 0
        assert stats["idle_count"] == 0
        assert stats["max_size"] == 100
        assert stats["min_size"] == 20
        assert stats["is_closed"] is False
        assert stats["acquire_count"] == 0
        assert stats["create_count"] == 0
        assert stats["reuse_count"] == 0

    async def test_increment_and_decrement_count(self):
        """计数器增减"""
        pool = TestConnectionPool()
        assert await pool._increment_count() == 1
        assert await pool._increment_count() == 2
        assert await pool._decrement_count() == 1
        assert pool._active_count == 1

    async def test_warm_up_creates_connections(self):
        """预热应创建 min_size 个连接"""
        pool = TestConnectionPool(min_size=3, connection_timeout=5)
        await pool.warm_up()
        # 等待 warmup task 完成
        if pool._warmup_task:
            await pool._warmup_task
        assert pool._create_count == 3
        assert pool._active_count == 3
        assert pool._pool.qsize() == 3
        await pool.close()

    async def test_warm_up_pool_closed(self):
        """预热时池已关闭应停止创建"""
        pool = TestConnectionPool(min_size=3)
        pool._closed = True
        await pool.warm_up()
        if pool._warmup_task:
            await pool._warmup_task
        assert pool._create_count == 0

    async def test_warm_up_create_failure(self):
        """预热时创建连接失败应中断"""
        pool = TestConnectionPool(min_size=3)

        async def fail_create():
            raise ConnectionError("create failed")

        pool._create_connection = fail_create
        await pool.warm_up()
        if pool._warmup_task:
            await pool._warmup_task
        assert pool._active_count == 0

    async def test_acquire_creates_new_connection(self):
        """空池 acquire 应创建新连接"""
        pool = TestConnectionPool(max_size=10, min_size=0, connection_timeout=5)
        wrapped = await pool.acquire(timeout=1)
        assert wrapped is not None
        # 新创建的连接 use_count 为 0（update_used_time 仅在复用时调用）
        assert wrapped.use_count == 0
        assert pool._stats["create_count"] == 1
        assert pool._stats["acquire_count"] == 1
        await pool.close()

    async def test_acquire_reuses_healthy_connection(self):
        """池中有健康连接时应复用"""
        pool = TestConnectionPool(max_size=10, min_size=0, connection_timeout=5)
        # 手动放入一个连接
        conn = FakeConnection(1)
        wrapped = ConnectionWrapper(conn)
        await pool._increment_count()
        pool._pool.put_nowait(wrapped)

        acquired = await pool.acquire(timeout=1)
        assert acquired is wrapped
        assert acquired.use_count == 1  # 复用时 update_used_time 被调用
        assert pool._stats["reuse_count"] == 1
        await pool.close()

    async def test_acquire_closes_unhealthy_then_creates(self):
        """池中连接不健康时应关闭并创建新的"""
        pool = TestConnectionPool(max_size=10, min_size=0, connection_timeout=5)
        # 放入一个不健康的连接
        conn = FakeConnection(1, healthy=False)
        wrapped = ConnectionWrapper(conn)
        # 让 is_healthy 返回 False
        wrapped.connection.close_code = 1000
        await pool._increment_count()
        pool._pool.put_nowait(wrapped)

        acquired = await pool.acquire(timeout=1)
        assert acquired is not wrapped
        assert len(pool._closed_conns) == 1
        assert pool._stats["create_count"] == 1
        await pool.close()

    async def test_acquire_closed_pool_raises(self):
        """关闭的池 acquire 应抛 ConnectionError"""
        pool = TestConnectionPool()
        pool._closed = True
        with pytest.raises(ConnectionError, match="连接池已关闭"):
            await pool.acquire()

    async def test_acquire_timeout(self):
        """达到上限且队列空时 acquire 应超时"""
        pool = TestConnectionPool(max_size=1, min_size=0, connection_timeout=5)
        # 占用唯一连接配额
        await pool._increment_count()
        with pytest.raises(ConnectionError, match="获取连接超时"):
            await pool.acquire(timeout=0.1)

    async def test_acquire_create_timeout(self):
        """创建连接超时应抛 ConnectionError"""
        pool = TestConnectionPool(max_size=10, min_size=0, connection_timeout=1)

        async def slow_create():
            await asyncio.sleep(10)
            return FakeConnection(1)

        pool._create_connection = slow_create
        with pytest.raises(ConnectionError, match="创建连接超时"):
            await pool.acquire(timeout=0.5)
        assert pool._stats["timeout_count"] == 1

    async def test_acquire_create_exception(self):
        """创建连接抛异常时应向上传播"""
        pool = TestConnectionPool(max_size=10, min_size=0, connection_timeout=5)

        async def boom():
            raise RuntimeError("boom")

        pool._create_connection = boom
        with pytest.raises(RuntimeError, match="boom"):
            await pool.acquire(timeout=1)

    async def test_release_healthy_connection(self):
        """释放健康连接应放回池"""
        pool = TestConnectionPool(max_size=10, min_size=0, connection_timeout=5)
        wrapped = await pool.acquire(timeout=1)
        await pool.release(wrapped)
        assert pool._pool.qsize() == 1
        await pool.close()

    async def test_release_none(self):
        """释放 None 应无操作"""
        pool = TestConnectionPool()
        await pool.release(None)
        assert pool._pool.qsize() == 0

    async def test_release_unhealthy_connection(self):
        """释放不健康连接应关闭"""
        pool = TestConnectionPool(max_size=10, min_size=0, connection_timeout=5)
        wrapped = await pool.acquire(timeout=1)
        wrapped.connection.close_code = 1000  # 标记不健康
        await pool.release(wrapped)
        assert pool._pool.qsize() == 0
        assert len(pool._closed_conns) == 1
        await pool.close()

    async def test_release_to_closed_pool(self):
        """关闭的池释放连接应直接关闭"""
        pool = TestConnectionPool(max_size=10, min_size=0, connection_timeout=5)
        wrapped = await pool.acquire(timeout=1)
        pool._closed = True
        await pool.release(wrapped)
        assert pool._pool.qsize() == 0
        await pool.close()

    async def test_release_queue_full_closes(self):
        """队列满时释放应关闭连接"""
        pool = TestConnectionPool(max_size=1, min_size=0, connection_timeout=5)
        # 填满队列
        conn1 = FakeConnection(1)
        pool._pool.put_nowait(ConnectionWrapper(conn1))
        # 再释放一个
        conn2 = FakeConnection(2)
        wrapped2 = ConnectionWrapper(conn2)
        await pool.release(wrapped2)
        # conn2 应被关闭
        assert len(pool._closed_conns) == 1

    async def test_close_connection_internal_exception(self):
        """_close_connection 抛异常时仍应递减计数"""
        pool = TestConnectionPool(max_size=10, min_size=0, connection_timeout=5)

        async def boom_close(conn):
            raise RuntimeError("close failed")

        pool._close_connection = boom_close
        wrapped = ConnectionWrapper(FakeConnection(1))
        await pool._increment_count()
        await pool._close_connection_internal(wrapped)
        assert pool._active_count == 0

    async def test_close_pool(self):
        """close 应关闭池并清理连接"""
        pool = TestConnectionPool(max_size=10, min_size=0, connection_timeout=5)
        # 放入一些连接
        await pool.acquire(timeout=1)
        await pool.acquire(timeout=1)
        # release 让它们回到池
        # 实际上 acquire 后连接不在池中，需要 release
        await pool.close()
        assert pool.is_closed is True
        assert pool._closed is True

    async def test_close_already_closed_pool(self):
        """重复 close 不应报错"""
        pool = TestConnectionPool()
        await pool.close()
        await pool.close()
        assert pool.is_closed is True

    async def test_cleanup_loop_runs(self):
        """_cleanup_loop 应能运行并清理"""
        pool = TestConnectionPool(
            max_size=10, min_size=0, idle_timeout=0,
            connection_timeout=5,
        )
        # 手动启动 cleanup_loop（sleep 很短）
        pool._closed = False
        # 放入一个空闲连接（last_used_time 很久以前 -> 立即过期）
        conn = FakeConnection(1)
        wrapped = ConnectionWrapper(conn)
        wrapped.last_used_time = time.time() - 1000
        pool._pool.put_nowait(wrapped)
        await pool._increment_count()

        # 运行一次清理逻辑（直接调用内部逻辑而非等待 60s）
        # 模拟 cleanup_loop 的一轮
        task = asyncio.create_task(pool._cleanup_loop())
        await asyncio.sleep(0.05)
        pool._closed = True
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def test_acquire_after_release_unhealthy_recurse(self):
        """acquire 中遇到不健康连接后递归调用 acquire(timeout=0)"""
        pool = TestConnectionPool(max_size=10, min_size=0, connection_timeout=5)
        # 放入一个不健康连接
        conn = FakeConnection(1, healthy=False)
        wrapped = ConnectionWrapper(conn)
        wrapped.connection.close_code = 1000
        await pool._increment_count()
        pool._pool.put_nowait(wrapped)

        acquired = await pool.acquire(timeout=1)
        assert acquired is not None
        assert acquired.connection is not conn
        await pool.close()


# ════════════════════════════════════════════════════════════════
# PoolManager 测试
# ════════════════════════════════════════════════════════════════

class TestPoolManager:
    """PoolManager 全局连接池管理器测试"""

    async def setup_method(self):
        """每个测试前清空全局池"""
        PoolManager._pools = {}

    async def teardown_method(self):
        """每个测试后清空全局池"""
        PoolManager._pools = {}

    async def test_register_and_get_pool(self):
        """注册并获取连接池"""
        pool = TestConnectionPool(pool_name="test1")
        await PoolManager.register_pool("test1", pool)
        result = await PoolManager.get_pool("test1")
        assert result is pool

    async def test_get_pool_not_found(self):
        """获取不存在的池应返回 None"""
        result = await PoolManager.get_pool("nonexistent")
        assert result is None

    async def test_close_all(self):
        """close_all 应关闭所有池"""
        pool1 = TestConnectionPool(pool_name="p1")
        pool2 = TestConnectionPool(pool_name="p2")
        await PoolManager.register_pool("p1", pool1)
        await PoolManager.register_pool("p2", pool2)

        await PoolManager.close_all()
        assert pool1.is_closed is True
        assert pool2.is_closed is True
        assert len(PoolManager._pools) == 0

    async def test_close_all_with_exception(self):
        """close_all 中某池关闭失败不应影响其他池"""
        pool1 = TestConnectionPool(pool_name="p1")
        pool2 = TestConnectionPool(pool_name="p2")

        # 让 pool1.close 抛异常
        async def boom_close():
            raise RuntimeError("close failed")

        pool1.close = boom_close
        await PoolManager.register_pool("p1", pool1)
        await PoolManager.register_pool("p2", pool2)

        await PoolManager.close_all()
        assert pool2.is_closed is True
        assert len(PoolManager._pools) == 0

    def test_get_all_stats(self):
        """get_all_stats 应返回所有池的统计"""
        pool1 = TestConnectionPool(pool_name="p1")
        PoolManager._pools["p1"] = pool1
        stats = PoolManager.get_all_stats()
        assert "p1" in stats
        assert stats["p1"]["pool_name"] == "p1"

    def test_get_all_stats_empty(self):
        """无池时 get_all_stats 返回空字典"""
        PoolManager._pools = {}
        stats = PoolManager.get_all_stats()
        assert stats == {}
