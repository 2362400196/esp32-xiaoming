"""WebSocket 会话处理器兼容入口。

实现已按职责拆分到 ``src.interfaces.ws_session`` 子包，本模块仅保留
``WebSocketSessionHandler`` 的导入路径，避免调用方改动。
"""
from __future__ import annotations

from src.interfaces.ws_session import WebSocketSessionHandler

__all__ = ["WebSocketSessionHandler"]
