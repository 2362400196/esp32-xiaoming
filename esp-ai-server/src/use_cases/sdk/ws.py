"""WebSocket 操作 SDK

沙箱插件通过 `ws_connect / ws_send / ws_recv / ws_close` 管理 WebSocket 连接。
子进程环境由 sdk_shim.py 中的桩实现替换为主进程 RPC 代理；
主进程环境（如插件加载器工具发现阶段）使用此模块的真实实现。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

import websockets

logger = logging.getLogger(__name__)

# 全局会话缓存: session_id -> websocket.WebSocketClientProtocol
_sessions: dict[str, "websockets.WebSocketClientProtocol"] = {}
_session_counter = 0


async def ws_connect(url: str, headers: dict | None = None) -> str:
    """创建 WebSocket 连接，返回 session_id。"""
    global _session_counter
    try:
        extra_headers = dict(headers or {})
        ws = await websockets.connect(url, additional_headers=extra_headers, ping_interval=None)
        _session_counter += 1
        session_id = f"ws_{_session_counter}"
        _sessions[session_id] = ws
        logger.debug(f"[ws SDK] 已连接: {url} -> {session_id}")
        return session_id
    except Exception as e:
        logger.error(f"[ws SDK] 连接失败 {url}: {e}")
        raise


async def ws_send(session_id: str, data: bytes) -> None:
    """通过 WebSocket 发送二进制数据。"""
    ws = _sessions.get(session_id)
    if ws is None:
        raise RuntimeError(f"WebSocket 会话不存在: {session_id}")
    try:
        await ws.send(data)
    except Exception as e:
        logger.error(f"[ws SDK] send 失败 {session_id}: {e}")
        raise


async def ws_recv(session_id: str, timeout: float = 0.1) -> bytes | None:
    """从 WebSocket 接收数据（带超时），返回 bytes 或 None。"""
    ws = _sessions.get(session_id)
    if ws is None:
        raise RuntimeError(f"WebSocket 会话不存在: {session_id}")
    try:
        data = await asyncio.wait_for(ws.recv(), timeout=timeout)
        if isinstance(data, bytes):
            return data
        if isinstance(data, str):
            return data.encode("utf-8")
        return data
    except asyncio.TimeoutError:
        return None
    except Exception as e:
        logger.debug(f"[ws SDK] recv 异常 {session_id}: {e}")
        return None


async def ws_close(session_id: str) -> None:
    """关闭 WebSocket 连接。"""
    ws = _sessions.pop(session_id, None)
    if ws is None:
        return
    try:
        await ws.close()
    except Exception as e:
        logger.debug(f"[ws SDK] close 异常 {session_id}: {e}")