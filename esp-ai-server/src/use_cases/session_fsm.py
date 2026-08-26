"""
Session FSM - 会话状态机

与旧架构(app/websocket/channel.py)完全对齐：
- SessionFSM: 带transition guard的状态机
- WSChannel: WebSocket唯一收发入口（单写队列化）
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Callable, Optional

from src.domain.entities import SessionState
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


VALID_TRANSITIONS = {
    SessionState.IDLE: [SessionState.ASR, SessionState.TTS],
    SessionState.ASR: [SessionState.LLM, SessionState.IDLE],
    SessionState.LLM: [SessionState.TTS, SessionState.IDLE, SessionState.ASR],
    SessionState.TTS: [SessionState.ASR, SessionState.IDLE],
}


class SessionFSM:
    """会话状态机：带 transition guard"""

    def __init__(self, on_change: Optional[Callable[[SessionState], None]] = None):
        self.state = SessionState.IDLE
        self.lock = asyncio.Lock()
        self._on_change = on_change

    async def set(self, new_state: SessionState):
        async with self.lock:
            if self.state == new_state:
                return
            if new_state not in VALID_TRANSITIONS.get(self.state, []):
                logger.error(f"[FSM] 非法状态转换: {self.state.value} -> {new_state.value}，已忽略")
                return
            self.state = new_state
            if self._on_change:
                try:
                    self._on_change(new_state)
                except Exception as e:
                    logger.debug(f"[FSM] 状态变化回调异常: {e}")

    def get(self) -> SessionState:
        return self.state

    def is_busy(self) -> bool:
        return self.state != SessionState.IDLE


class WSChannel:
    """WebSocket 唯一收发入口 — 双队列优先级（控制帧优先于音频帧）"""

    def __init__(self):
        self.websocket = None
        self._hi = asyncio.Queue(maxsize=64)   # 控制帧（高优先级）：JSON/Text
        self._lo = asyncio.Queue(maxsize=500)  # 音频帧（低优先级）：bytes
        self._send_task = None
        self._send_gen = 0
        self.connected = False
        self._volume = 1.0  # 设备音量缓存（0.0-1.0），供 HTTP API 读写
        self._brightness = 100  # 设备亮度缓存（0-100），供 HTTP API 读写

    @property
    def send_queue(self):
        """向后兼容：旧代码通过 send_queue.put_nowait 注入控制帧，现映射到高优先级队列 _hi。"""
        return self._hi

    def bind(self, websocket):
        self.websocket = websocket
        self.connected = True
        self._send_gen += 1
        self._send_task = asyncio.create_task(self._send_loop(self._send_gen))

    async def _send_loop(self, gen: int):
        try:
            while self.connected:
                # 优先消费高优先级控制帧；_hi 为空时等待低优先级音频帧
                # 使用 timeout 定期检查 _hi，避免控制帧（如 iat_start）被无限阻塞
                try:
                    msg = self._hi.get_nowait()
                    self._hi.task_done()
                except asyncio.QueueEmpty:
                    try:
                        msg = await asyncio.wait_for(self._lo.get(), timeout=0.1)
                        self._lo.task_done()
                    except asyncio.TimeoutError:
                        continue  # 超时后重新检查 _hi
                if gen != self._send_gen:
                    break
                data = msg["data"]
                try:
                    if msg["kind"] == "json":
                        await self.websocket.send_json(data)
                    elif msg["kind"] == "bytes":
                        await self.websocket.send_bytes(data)
                    elif msg["kind"] == "text":
                        await self.websocket.send_text(data)
                    if msg["kind"] != "bytes" and (msg["kind"] == "text" or (isinstance(data, dict) and data.get("type") not in ("keepalive", "pong", "session_status"))):
                        logger.info(f"[WSChannel] 已发送 {msg['kind']}: {str(data)[:200]}")
                except Exception as e:
                    kind = msg.get("kind", "?")
                    preview = f"{len(data)}B" if kind == "bytes" else str(data)[:120]
                    logger.warning(f"[WSChannel] 发送失败: {e} (kind={kind}, msg={preview})")
                    self.connected = False
                    # 连接已死：主动关闭 WebSocket，让 run() 中阻塞的 receive() 立即返回并走 cleanup()，
                    # 释放全局并发 slot / 注销设备。否则半开连接下旧会话任务永久卡死，
                    # 设备重连后仍会被旧会话残留拖住，只能靠重启服务端恢复。
                    try:
                        if self.websocket is not None:
                            await asyncio.wait_for(self.websocket.close(), timeout=2.0)
                    except Exception:
                        pass
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[WSChannel] 发送循环异常: {e}")
            self.connected = False
            try:
                if self.websocket is not None:
                    await asyncio.wait_for(self.websocket.close(), timeout=2.0)
            except Exception:
                pass

    async def send_json(self, data: dict):
        if self.connected:
            await self._hi.put({"kind": "json", "data": data})

    async def send_bytes(self, data: bytes):
        if self.connected:
            await self._lo.put({"kind": "bytes", "data": data})

    async def send_text(self, data: str):
        if self.connected:
            await self._hi.put({"kind": "text", "data": data})

    def send_json_nowait(self, data: dict):
        if not self.connected:
            if data.get("type") == "keepalive":
                logger.warning("[WSChannel] keepalive 丢弃: 连接已断开")
            return
        try:
            self._hi.put_nowait({"kind": "json", "data": data})
        except asyncio.QueueFull:
            if data.get("type") == "keepalive":
                logger.warning("[WSChannel] keepalive 丢弃: 高优先级队列已满，丢弃最旧一条")
                try:
                    self._hi.get_nowait()
                    self._hi.task_done()
                    self._hi.put_nowait({"kind": "json", "data": data})
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    async def close(self):
        self.connected = False
        if self._send_task and not self._send_task.done():
            self._send_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._send_task

    def clear_queue(self) -> int:
        cleared = 0
        for q in (self._hi, self._lo):
            while not q.empty():
                try:
                    q.get_nowait()
                    q.task_done()
                    cleared += 1
                except asyncio.QueueEmpty:
                    break
        return cleared

    async def interrupt_send_loop(self) -> int:
        self._send_gen += 1
        if self._send_task and not self._send_task.done():
            self._send_task.cancel()

        cleared = self.clear_queue()

        if self.connected and self.websocket:
            self._send_task = asyncio.create_task(self._send_loop(self._send_gen))

        return cleared


__all__ = ["SessionFSM", "WSChannel", "VALID_TRANSITIONS"]
