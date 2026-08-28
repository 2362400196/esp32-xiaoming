"""
task_manager 单元测试

验证 background_task：
1. 持有任务强引用，完成后自动移除
2. 任务异常被记录（ERROR 日志），不再静默丢失
3. 任务被取消时不记 ERROR
4. 返回值是真正的 asyncio.Task（可 cancel/await）
"""
import asyncio
import logging

import pytest

from src.infrastructure import task_manager
from src.infrastructure.task_manager import background_task, get_active_count


async def _ok_coro():
    await asyncio.sleep(0)
    return "done"


async def _fail_coro():
    await asyncio.sleep(0)
    raise ValueError("boom")


class TestBackgroundTask:
    """background_task 引用持有与异常处理"""

    async def test_returns_real_task(self):
        task = background_task(_ok_coro(), name="t_ok")
        assert isinstance(task, asyncio.Task)
        assert task.get_name() == "t_ok"
        assert await task == "done"

    async def test_holds_reference_until_done(self):
        started = asyncio.Event()

        async def _waiter():
            started.set()
            await asyncio.sleep(0.05)

        before = get_active_count()
        task = background_task(_waiter(), name="t_ref")
        await started.wait()
        # 运行中应被持有强引用（不会被 GC 回收）
        assert get_active_count() >= before + 1
        await task
        # 让 done_callback 有机会执行
        await asyncio.sleep(0)
        assert get_active_count() == before

    async def test_exception_logged_as_error(self, caplog):
        # 应用日志配置关闭了 propagate，直接把 caplog 的 handler 挂到目标 logger
        target_logger = logging.getLogger("task_manager")
        target_logger.addHandler(caplog.handler)
        try:
            task = background_task(_fail_coro(), name="t_fail")
            with pytest.raises(ValueError, match="boom"):
                await task
            # 等待 done_callback 执行
            await asyncio.sleep(0)
        finally:
            target_logger.removeHandler(caplog.handler)
        errors = [r for r in caplog.records if "Task failed" in r.getMessage()]
        assert errors, "任务异常应记录 ERROR 日志"
        assert all(r.levelno >= logging.ERROR for r in errors)

    async def test_cancelled_not_logged_as_error(self, caplog):
        task = background_task(_ok_coro(), name="t_cancel")
        task.cancel()
        with caplog.at_level("ERROR", logger="task_manager"):
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.sleep(0)
        assert not any("Task failed" in r.message for r in caplog.records)

    async def test_on_done_callback_invoked(self):
        results = []
        task = background_task(_ok_coro(), name="t_cb", on_done=lambda t: results.append(t))
        await task
        await asyncio.sleep(0)
        assert len(results) == 1
        assert results[0] is task

    async def test_coro_name_used_when_no_name(self):
        task = background_task(_ok_coro())
        assert task.get_name() == "_ok_coro"
        await task
