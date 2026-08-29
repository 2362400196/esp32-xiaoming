"""进程内事件系统（发布/订阅）— 供插件订阅框架事件。

插件用法（在 plugin.py 中）：

    from src.use_cases.sdk.events import subscribe, unsubscribe, EVENT_DEVICE_ONLINE

    def _on_device_online(device_id: str = "", **_):
        plugin_log(f"设备上线: {device_id}")

    sub_id = subscribe(EVENT_DEVICE_ONLINE, _on_device_online, plugin_name="my_plugin")
    # 不再需要时：unsubscribe(sub_id)

设计要点：
- 纯进程内、无持久化；publish 同步遍历订阅者，任何单个回调异常都被捕获并记日志，
  绝不影响发布方主流程，也不影响其他订阅者。
- 协程函数回调通过 background_task 包装为后台任务执行（不阻塞发布方）。
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass
from typing import Callable

from src.infrastructure.logging import get_logger
from src.infrastructure.task_manager import background_task

logger = get_logger(__name__)

# ════════════════════════════════════════════════════════════
# 预定义事件名常量
# ════════════════════════════════════════════════════════════

EVENT_DEVICE_ONLINE = "device_online"        # 设备上线（payload: device_id）
EVENT_DEVICE_OFFLINE = "device_offline"      # 设备离线（payload: device_id）
EVENT_SESSION_START = "session_start"        # 语音会话开始（payload: device_key）
EVENT_WECHAT_MESSAGE = "wechat_message"      # 微信消息事件（payload: chat_id, text）
EVENT_SESSION_END = "session_end"            # 设备会话结束/断连（payload: device_key）


@dataclass
class _Subscription:
    """单条订阅记录"""
    sub_id: str
    event: str
    plugin_name: str
    callback: Callable


# event 名 → 订阅列表
_subscriptions: dict[str, list[_Subscription]] = {}
# 保护 _subscriptions 的锁（线程安全：回调可能在线程池中执行 unsubscribe）
_lock = threading.Lock()


def subscribe(event: str, callback: Callable, plugin_name: str = "") -> str:
    """订阅框架事件，返回订阅 id（用于 unsubscribe）。

    Args:
        event: 事件名（使用本模块的 EVENT_* 常量）
        callback: 回调函数；payload 以关键字参数传入。
                  协程函数会自动用 background_task 包装为后台任务。
        plugin_name: 订阅方插件名（仅用于日志排查）
    """
    sub_id = uuid.uuid4().hex
    sub = _Subscription(sub_id=sub_id, event=event, plugin_name=plugin_name, callback=callback)
    with _lock:
        _subscriptions.setdefault(event, []).append(sub)
    logger.debug(f"[Events] 订阅: event={event} plugin={plugin_name or 'anonymous'} id={sub_id[:8]}")
    return sub_id


def unsubscribe(sub_id: str) -> bool:
    """取消订阅。返回是否成功移除（已不存在返回 False）。"""
    with _lock:
        for event, subs in _subscriptions.items():
            for i, sub in enumerate(subs):
                if sub.sub_id == sub_id:
                    subs.pop(i)
                    if not subs:
                        _subscriptions.pop(event, None)
                    logger.debug(f"[Events] 取消订阅: event={event} id={sub_id[:8]}")
                    return True
    return False


def publish(event: str, **payload) -> None:
    """发布事件：同步遍历该事件的订阅者并逐个调用回调。

    绝对容错：任何订阅者异常只记日志，不影响发布方主流程和其他订阅者；
    无人订阅时为空操作。协程回调交给 background_task，不阻塞事件循环。
    """
    with _lock:
        subs = list(_subscriptions.get(event, []))
    if not subs:
        return
    for sub in subs:
        try:
            if asyncio.iscoroutinefunction(sub.callback):
                # 协程回调包装为后台任务：持有引用、异常有日志
                background_task(
                    sub.callback(**payload),
                    name=f"event:{event}:{sub.plugin_name or sub.sub_id[:8]}",
                )
            else:
                sub.callback(**payload)
        except Exception as e:
            # 单个订阅者失败不影响其他订阅者，更不影响发布方
            logger.warning(
                f"[Events] 事件回调异常: event={event} plugin={sub.plugin_name or 'anonymous'}: {e}"
            )
