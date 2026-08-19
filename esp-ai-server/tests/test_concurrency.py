"""
concurrency 单元测试

覆盖范围：
- init_concurrency_control：启用 / 禁用全局并发限制
- acquire_global_slot：无信号量 / 有信号量
- release_global_slot：无信号量 / 正常释放 / 超额释放（ValueError）
- run_in_executor：正常执行 / 池未初始化时自动初始化
- get_stats：返回统计字典（启用 / 禁用）
- shutdown：关闭线程池 / 无池时无操作
"""
import asyncio
import concurrent.futures
from unittest.mock import MagicMock, patch

import pytest

from src.infrastructure import concurrency
from src.infrastructure.concurrency import (
    acquire_global_slot,
    get_stats,
    init_concurrency_control,
    release_global_slot,
    run_in_executor,
    shutdown,
)


def _make_perf_config(enable_limit=True, max_sessions=5, pool_workers=4):
    """构造模拟的 settings.performance 配置"""
    cfg = MagicMock()
    cfg.enable_global_concurrency_limit = enable_limit
    cfg.global_max_concurrent_sessions = max_sessions
    cfg.process_pool_max_workers = pool_workers
    return cfg


def _make_settings(enable_limit=True, max_sessions=5, pool_workers=4):
    """构造模拟的 settings 对象"""
    settings = MagicMock()
    settings.performance = _make_perf_config(enable_limit, max_sessions, pool_workers)
    return settings


@pytest.fixture(autouse=True)
def reset_concurrency_globals():
    """每个测试前后重置模块级全局变量，避免相互影响"""
    concurrency._global_semaphore = None
    concurrency._global_semaphore_max = 30
    concurrency._process_pool = None
    yield
    # 清理：关闭可能创建的线程池
    if concurrency._process_pool is not None:
        concurrency._process_pool.shutdown(wait=True)
        concurrency._process_pool = None
    concurrency._global_semaphore = None
    concurrency._global_semaphore_max = 30


# ─── init_concurrency_control 测试 ─────────────────────────

class TestInitConcurrencyControl:
    """init_concurrency_control 测试"""

    def test_init_enabled(self):
        settings = _make_settings(enable_limit=True, max_sessions=5, pool_workers=3)
        with patch("src.infrastructure.concurrency.get_settings", return_value=settings):
            init_concurrency_control()
        assert concurrency._global_semaphore is not None
        assert concurrency._global_semaphore_max == 5
        assert concurrency._process_pool is not None
        assert isinstance(concurrency._process_pool, concurrent.futures.ThreadPoolExecutor)

    def test_init_disabled(self):
        settings = _make_settings(enable_limit=False, max_sessions=5, pool_workers=2)
        with patch("src.infrastructure.concurrency.get_settings", return_value=settings):
            init_concurrency_control()
        assert concurrency._global_semaphore is None
        # 信号量禁用时 max 保持默认
        assert concurrency._global_semaphore_max == 30
        # 线程池仍应初始化
        assert concurrency._process_pool is not None

    def test_init_creates_pool_with_workers(self):
        settings = _make_settings(enable_limit=True, max_sessions=10, pool_workers=8)
        with patch("src.infrastructure.concurrency.get_settings", return_value=settings):
            init_concurrency_control()
        assert concurrency._process_pool is not None
        # 线程池应有 worker 配置（无法直接断言数量，但确保非空）

    def test_init_can_be_called_multiple_times(self):
        settings = _make_settings(enable_limit=True, max_sessions=5, pool_workers=2)
        with patch("src.infrastructure.concurrency.get_settings", return_value=settings):
            init_concurrency_control()
            first_pool = concurrency._process_pool
            init_concurrency_control()
        # 重新初始化后池应被替换
        assert concurrency._process_pool is not None


# ─── acquire_global_slot 测试 ──────────────────────────────

class TestAcquireGlobalSlot:
    """acquire_global_slot 测试"""

    async def test_acquire_no_semaphore_returns_true(self):
        # 未启用限制时直接返回 True
        assert await acquire_global_slot() is True

    async def test_acquire_with_semaphore(self):
        concurrency._global_semaphore = asyncio.Semaphore(2)
        concurrency._global_semaphore_max = 2
        concurrency._available_count = 2
        assert await acquire_global_slot() is True
        # 获取后可用计数应减少
        assert concurrency._available_count == 1

    async def test_acquire_multiple_then_block(self):
        concurrency._global_semaphore = asyncio.Semaphore(1)
        concurrency._global_semaphore_max = 1
        concurrency._available_count = 1
        assert await acquire_global_slot() is True
        # 第二次获取应阻塞（用 wait_for 验证会超时）
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(acquire_global_slot(), timeout=0.1)
        # 释放后计数恢复
        release_global_slot()
        assert concurrency._available_count == 1


# ─── release_global_slot 测试 ──────────────────────────────

class TestReleaseGlobalSlot:
    """release_global_slot 测试"""

    def test_release_no_semaphore_noop(self):
        # 无信号量时释放不报错
        release_global_slot()

    async def test_release_increments_value(self):
        concurrency._global_semaphore = asyncio.Semaphore(2)
        concurrency._global_semaphore_max = 2
        concurrency._available_count = 2
        await acquire_global_slot()
        assert concurrency._available_count == 1
        release_global_slot()
        assert concurrency._available_count == 2

    def test_release_value_error_swallowed(self):
        # 模拟 release 抛出 ValueError（如 BoundedSemaphore 超额释放）
        sem = MagicMock()
        sem.release.side_effect = ValueError("too many releases")
        concurrency._global_semaphore = sem
        # 不应抛出异常
        release_global_slot()

    async def test_acquire_release_cycle(self):
        concurrency._global_semaphore = asyncio.Semaphore(3)
        concurrency._global_semaphore_max = 3
        concurrency._available_count = 3
        await acquire_global_slot()
        await acquire_global_slot()
        assert concurrency._available_count == 1
        release_global_slot()
        release_global_slot()
        assert concurrency._available_count == 3


# ─── run_in_executor 测试 ──────────────────────────────────

class TestRunInExecutor:
    """run_in_executor 测试"""

    async def test_run_in_executor_returns_result(self):
        settings = _make_settings(enable_limit=False, pool_workers=2)
        with patch("src.infrastructure.concurrency.get_settings", return_value=settings):
            init_concurrency_control()
            result = await run_in_executor(lambda x, y: x + y, 3, 4)
        assert result == 7

    async def test_run_in_executor_with_kwargs(self):
        settings = _make_settings(enable_limit=False, pool_workers=2)
        with patch("src.infrastructure.concurrency.get_settings", return_value=settings):
            init_concurrency_control()

            def func(a, b=10):
                return a * b

            result = await run_in_executor(func, 5, b=3)
        assert result == 15

    async def test_run_in_executor_auto_init_when_pool_none(self):
        # 池为 None 时应自动初始化
        assert concurrency._process_pool is None
        settings = _make_settings(enable_limit=False, pool_workers=2)
        with patch("src.infrastructure.concurrency.get_settings", return_value=settings):
            result = await run_in_executor(lambda: 42)
        assert result == 42
        assert concurrency._process_pool is not None

    async def test_run_in_executor_no_args(self):
        settings = _make_settings(enable_limit=False, pool_workers=2)
        with patch("src.infrastructure.concurrency.get_settings", return_value=settings):
            init_concurrency_control()
            result = await run_in_executor(lambda: "hello")
        assert result == "hello"

    async def test_run_in_executor_propagates_exception(self):
        settings = _make_settings(enable_limit=False, pool_workers=2)
        with patch("src.infrastructure.concurrency.get_settings", return_value=settings):
            init_concurrency_control()

            def boom():
                raise RuntimeError("boom")

            with pytest.raises(RuntimeError, match="boom"):
                await run_in_executor(boom)


# ─── get_stats 测试 ────────────────────────────────────────

class TestGetStats:
    """get_stats 测试"""

    def test_stats_disabled(self):
        # 未初始化时（确保 semaphore 为 None，available_count 与 max 一致）
        concurrency._global_semaphore = None
        concurrency._global_semaphore_max = 30
        concurrency._available_count = 30
        stats = get_stats()
        assert stats["global_concurrency_limit_enabled"] is False
        assert stats["global_concurrency_max"] == 30
        assert stats["global_concurrency_available"] == 30
        assert stats["process_pool_initialized"] is False

    def test_stats_enabled(self):
        settings = _make_settings(enable_limit=True, max_sessions=5, pool_workers=2)
        with patch("src.infrastructure.concurrency.get_settings", return_value=settings):
            init_concurrency_control()
        stats = get_stats()
        assert stats["global_concurrency_limit_enabled"] is True
        assert stats["global_concurrency_max"] == 5
        assert stats["global_concurrency_available"] == 5
        assert stats["process_pool_initialized"] is True

    async def test_stats_available_decreases_after_acquire(self):
        concurrency._global_semaphore = asyncio.Semaphore(3)
        concurrency._global_semaphore_max = 3
        concurrency._available_count = 3
        await acquire_global_slot()
        stats = get_stats()
        assert stats["global_concurrency_available"] == 2
        assert stats["global_concurrency_limit_enabled"] is True


# ─── shutdown 测试 ─────────────────────────────────────────

class TestShutdown:
    """shutdown 测试"""

    def test_shutdown_no_pool_noop(self):
        # 无线程池时 shutdown 不报错
        shutdown()
        assert concurrency._process_pool is None

    def test_shutdown_closes_pool(self):
        settings = _make_settings(enable_limit=False, pool_workers=2)
        with patch("src.infrastructure.concurrency.get_settings", return_value=settings):
            init_concurrency_control()
        pool = concurrency._process_pool
        assert pool is not None
        shutdown()
        assert concurrency._process_pool is None

    def test_shutdown_idempotent(self):
        settings = _make_settings(enable_limit=False, pool_workers=2)
        with patch("src.infrastructure.concurrency.get_settings", return_value=settings):
            init_concurrency_control()
        shutdown()
        # 第二次 shutdown 不报错
        shutdown()
        assert concurrency._process_pool is None

    async def test_run_in_executor_after_shutdown_reinits(self):
        # shutdown 后再调用 run_in_executor 应自动重新初始化
        settings = _make_settings(enable_limit=False, pool_workers=2)
        with patch("src.infrastructure.concurrency.get_settings", return_value=settings):
            init_concurrency_control()
            shutdown()
            assert concurrency._process_pool is None
            result = await run_in_executor(lambda: "reborn")
        assert result == "reborn"
        assert concurrency._process_pool is not None
