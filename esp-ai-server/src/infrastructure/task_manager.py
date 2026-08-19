"""后台 Task 管理器

解决 fire-and-forget asyncio.create_task 的两个问题：
1. 未持有强引用的 task 可能被 GC 回收
2. task 异常被静默丢弃

使用方式：
    from src.infrastructure.task_manager import background_task

    # 替代 asyncio.create_task(coro)
    background_task(coro, name="mcp_init")

    # 带回调的 task
    background_task(coro, name="tts_play", on_done=cleanup_func)
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Coroutine, Optional, Set

from src.infrastructure.logging import get_logger

logger = get_logger("task_manager")

# 持有所有活跃 task 的强引用
_background_tasks: Set[asyncio.Task] = set()


def background_task(
    coro: Coroutine[Any, Any, Any],
    name: str = "",
    on_done: Optional[Callable[[asyncio.Task], None]] = None,
) -> asyncio.Task:
    """创建后台 task，自动管理引用和异常处理

    Args:
        coro: 要执行的协程
        name: task 名称（用于日志标识）
        on_done: 完成回调（可选）

    Returns:
        asyncio.Task
    """
    task = asyncio.create_task(coro, name=name or coro.__qualname__)
    _background_tasks.add(task)

    def _on_complete(t: asyncio.Task) -> None:
        _background_tasks.discard(t)
        if t.cancelled():
            logger.debug(f"[TaskManager] Task cancelled: {t.get_name()}")
            return
        exc = t.exception()
        if exc:
            logger.error(f"[TaskManager] Task failed: {t.get_name()}: {exc}", exc_info=exc)
        else:
            logger.debug(f"[TaskManager] Task completed: {t.get_name()}")
        if on_done:
            try:
                on_done(t)
            except Exception as e:
                logger.error(f"[TaskManager] on_done callback error: {e}", exc_info=e)

    task.add_done_callback(_on_complete)
    return task


def get_active_count() -> int:
    """获取活跃 task 数量"""
    return len(_background_tasks)


def cancel_all() -> None:
    """取消所有后台 task（优雅退出时调用）"""
    for task in list(_background_tasks):
        if not task.done():
            task.cancel()


__all__ = [
    "background_task",
    "get_active_count",
    "cancel_all",
]
