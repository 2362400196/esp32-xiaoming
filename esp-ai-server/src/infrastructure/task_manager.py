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
import time
from collections import deque
from typing import Any, Callable, Coroutine, Optional, Set

from src.infrastructure.logging import get_logger

logger = get_logger("task_manager")

# 持有所有活跃 task 的强引用
_background_tasks: Set[asyncio.Task] = set()

# task -> 元数据（名称/创建时间），供后台详情展示
_task_meta: dict[asyncio.Task, dict] = {}

# 已完成（含失败/取消）task 的累计计数
_completed_count = 0

# 最近完成的任务（环形缓冲，供管理后台"任务明细"展示）
_recent_completed: deque = deque(maxlen=20)


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
    _task_meta[task] = {"name": task.get_name(), "created_at": time.time()}

    def _on_complete(t: asyncio.Task) -> None:
        global _completed_count
        _completed_count += 1
        _background_tasks.discard(t)
        meta = _task_meta.pop(t, None) or {}
        try:
            exc = t.exception()
        except asyncio.CancelledError:
            exc = None  # 取消不算失败
        _recent_completed.append({
            "name": t.get_name(),
            "elapsed": round(time.time() - (meta.get("created_at") or time.time()), 2),
            "success": exc is None,
            "ended_at": time.time(),
        })
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


def get_completed_count() -> int:
    """获取已完成（含失败/取消）task 的累计数量"""
    return _completed_count


def list_recent_completed() -> list[dict]:
    """最近完成的任务（最新在前，最多 20 条）"""
    return list(reversed(_recent_completed))


def list_active_tasks() -> list[dict]:
    """列出当前活跃的后台任务（名称 + 已运行秒数），按运行时长倒序。

    供管理后台"活跃任务"详情展示；同名任务可能出现多条（如多个会话
    并发的 memory_save），前端负责按名称聚合计数。
    """
    now = time.time()
    out = []
    for t in list(_background_tasks):
        if t.done():
            continue
        meta = _task_meta.get(t, {})
        created = meta.get("created_at") or 0
        out.append({
            "name": t.get_name(),
            "elapsed": round(now - created, 1) if created else 0.0,
        })
    out.sort(key=lambda x: -x["elapsed"])
    return out


def cancel_all() -> None:
    """取消所有后台 task（优雅退出时调用）"""
    for task in list(_background_tasks):
        if not task.done():
            task.cancel()


__all__ = [
    "background_task",
    "get_active_count",
    "get_completed_count",
    "list_active_tasks",
    "list_recent_completed",
    "cancel_all",
]
