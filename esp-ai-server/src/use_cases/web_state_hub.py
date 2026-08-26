"""WebStateHub - 面向 Web 前端的设备状态实时推送中心

设备状态变化（连接/断开/FSM 状态/情绪）通过 WebSocket 实时推送到前端，
前端据此实时切换设备屏幕图标（休息中/聆听中/说话中/OFF）。
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


class WebStateHub:
    """维护 Web 前端 WebSocket 连接集合，广播设备状态变更"""

    def __init__(self) -> None:
        self._clients: set = set()
        self._lock = asyncio.Lock()

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def register(self, websocket) -> None:
        async with self._lock:
            self._clients.add(websocket)

    async def unregister(self, websocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)

    async def broadcast(self, payload: dict) -> None:
        if not self._clients:
            return
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)

    async def broadcast_device_state(
        self,
        device_id: str,
        online: bool,
        state: str = "idle",
        emotion: str = "",
    ) -> None:
        if not device_id:
            return
        payload = {
            "type": "device_state",
            "device_id": device_id,
            "online": bool(online),
            "state": state,
            "emotion": emotion,
        }
        await self.broadcast(payload)
