"""子进程侧 RPC 客户端：处理 stdin 消息、发送 stdout 消息。

子进程内有两条线程：
    - 主线程：运行 asyncio 事件循环（执行插件工具函数 / SDK 异步请求）
    - stdin 读取线程：读取主进程下发的 call / sdk_reply / ping

写 stdout 全部由事件循环线程完成（避免跨线程写竞争）：
    - 工具结果：工具任务完成时写
    - SDK 请求：工具任务内 await send_async() 时写；同步 SDK 函数在事件循环
      线程内阻塞等待时写（线程安全由 GIL + 单写者保证）
    - pong：通过 call_soon_threadsafe 调度到事件循环写

同步/异步两套 RPC 通道共存：
    - 同步 SDK 函数（如 resolve_device_key）在事件循环线程内阻塞等待 stdin 线程
      直接 set event（不经过事件循环，避免死锁）
    - 异步 SDK 函数（如 http_request）用 asyncio.Future，stdin 线程通过
      call_soon_threadsafe 唤醒
"""

from __future__ import annotations

import asyncio
import contextvars
import sys
import threading
from typing import Any, Callable

from .protocol import MAX_MSG_BYTES, ProtocolError, decode, encode

# 当前正在执行的 tool call 的 id（contextvars，asyncio 任务自动隔离）
call_id_ctx: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "plugin_call_id", default=None
)

_pending: dict[int, threading.Event | asyncio.Future] = {}
_pending_lock = threading.Lock()
_msg_counter = 0
_msg_counter_lock = threading.Lock()
_write_lock = threading.Lock()

_on_call: Callable[[dict], Any] | None = None  # 由 runner 注入

# stdin 读到 EOF 时置位（唯一 stdin 读取者，避免多线程争抢丢消息）
_eof_event = threading.Event()


def get_eof_event() -> threading.Event:
    return _eof_event


def set_call_handler(handler: Callable[[dict], Any]) -> None:
    global _on_call
    _on_call = handler

def _next_id() -> int:
    global _msg_counter
    with _msg_counter_lock:
        _msg_counter += 1
        return _msg_counter


def _write(msg: dict) -> None:
    payload = encode(msg)
    with _write_lock:
        sys.stdout.write(payload)
        sys.stdout.flush()


# ════════════════════════════════════════════════════════════
# 发送请求（供 SDK 桩调用）
# ════════════════════════════════════════════════════════════


def send_sync(op: str, params: dict) -> dict:
    """同步 SDK 请求：阻塞直到主进程回复（仅可在事件循环线程内调用）。"""
    msg_id = _next_id()
    ev = threading.Event()
    ev._holder = {}
    with _pending_lock:
        _pending[msg_id] = ev
    try:
        _write({"type": "sdk_request", "id": msg_id, "call": call_id_ctx.get(),
                "op": op, "params": params})
        if not ev.wait(timeout=60.0):
            raise TimeoutError(f"SDK 请求超时: {op}")
        reply = ev._holder["reply"]
    finally:
        with _pending_lock:
            _pending.pop(msg_id, None)
    if not reply.get("ok"):
        _raise_sdk_error(reply)
    return reply.get("result")


async def send_async(op: str, params: dict) -> dict:
    """异步 SDK 请求：协程等待主进程回复。"""
    msg_id = _next_id()
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    with _pending_lock:
        _pending[msg_id] = fut
    try:
        _write({"type": "sdk_request", "id": msg_id, "call": call_id_ctx.get(),
                "op": op, "params": params})
        reply = await asyncio.wait_for(fut, timeout=60.0)
    finally:
        with _pending_lock:
            _pending.pop(msg_id, None)
    if not reply.get("ok"):
        _raise_sdk_error(reply)
    return reply.get("result")


def _raise_sdk_error(reply: dict) -> None:
    err = reply.get("error") or "SDK 请求失败"
    if err.startswith("PermissionError"):
        raise PermissionError(err)
    raise RuntimeError(err)


# ════════════════════════════════════════════════════════════
# stdin 消息分发（stdin 读取线程调用）
# ════════════════════════════════════════════════════════════


def _dbg(msg: str) -> None:
    import os
    import sys as _sys
    try:
        with open(os.environ.get("PLUGIN_DEBUG_FILE", ""), "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        try:
            _sys.stderr.write(msg + "\n")
        except Exception:
            pass


def handle_message(msg: dict, loop: asyncio.AbstractEventLoop) -> None:
    mtype = msg.get("type")
    if mtype == "sdk_reply":
        rid = msg.get("id")
        with _pending_lock:
            waiter = _pending.get(rid)
        if waiter is None:
            return
        if isinstance(waiter, threading.Event):
            # 同步通道：直接把结果放进内存，再 set event（不依赖事件循环）
            holder = getattr(waiter, "_holder", None)
            if holder is None:
                holder = {}
                waiter._holder = holder
            holder["reply"] = msg
            waiter.set()
        else:
            loop.call_soon_threadsafe(waiter.set_result, msg)
    elif mtype == "call":
        if _on_call is not None:
            loop.call_soon_threadsafe(_schedule_call, msg, loop)
    elif mtype == "ping":
        loop.call_soon_threadsafe(_write, {"type": "pong", "id": msg.get("id")})


def _schedule_call(msg: dict, loop: asyncio.AbstractEventLoop) -> None:
    _on_call(msg)


def start_reader(loop: asyncio.AbstractEventLoop) -> None:
    """启动 stdin 读取线程（守护线程）。"""
    def _reader() -> None:
        buf = ""
        while True:
            try:
                line = sys.stdin.readline()
            except (OSError, ValueError):
                break
            if not line:
                break
            if len(line.encode("utf-8", "replace")) > MAX_MSG_BYTES:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                msg = decode(line)
            except ProtocolError:
                continue
            try:
                handle_message(msg, loop)
            except Exception:
                continue
        _eof_event.set()

    t = threading.Thread(target=_reader, name="plugin-stdin-reader", daemon=True)
    t.start()