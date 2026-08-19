"""子进程插件沙箱 RPC 协议（JSON-lines over stdin/stdout）。

消息约定：
    主进程 → 子进程（stdin，每行一个 JSON 对象）：
        {"type": "call",      "id": int, "tool": str, "args": dict}
        {"type": "sdk_reply", "id": int, "result": dict, "error": str|null}
        {"type": "ping",      "id": int}

    子进程 → 主进程（stdout，每行一个 JSON 对象）：
        {"type": "ready",       "plugin": str, "tools": [ToolSchema]}
        {"type": "result",      "id": int, "result": dict}      # call 的回复
        {"type": "sdk_request", "id": int, "call": int|null, "op": str, "params": dict}
        {"type": "pong",        "id": int}

    ToolSchema = {"name": str, "description": str, "schema": dict, "cache": bool,
                  "signature": [{"name": str, "kind": str, "default": bool}]}

    call 回复 result 结构：
        {"ok": true, "value": str|null, "stop": bool, "error": null}
        {"ok": false, "error": str}          # 工具抛异常（含 StackTrace）

    sdk_reply 结构：
        {"ok": true, "result": any}          # result 需 JSON 可序列化
        {"ok": false, "error": str}          # 权限拒绝/内部错误（SDK 侧抛异常）

安全：
    - 单条消息最大 MAX_MSG_BYTES 字节，防止内存炸弹。
    - 每条消息都是完整 JSON 行，行内不能有换行。
"""

from __future__ import annotations

import json

MAX_MSG_BYTES = 1024 * 1024  # 单条消息上限 1MB


class ProtocolError(Exception):
    """协议层错误（消息过大/JSON 损坏/字段缺失）。"""


def encode(msg: dict) -> str:
    """将消息编码为单行 JSON 字符串（供写入管道）。"""
    raw = json.dumps(msg, ensure_ascii=False, separators=(",", ":"), default=_json_default)
    if len(raw.encode("utf-8")) > MAX_MSG_BYTES:
        raise ProtocolError(f"消息过大（>{MAX_MSG_BYTES} 字节），已拒绝发送")
    return raw + "\n"


def _json_default(o):
    if isinstance(o, bytes):
        return o.decode("utf-8", "replace")
    return repr(o)


def decode(line: str) -> dict:
    """解析一行消息。行过长/损坏时抛 ProtocolError。"""
    if len(line.encode("utf-8")) > MAX_MSG_BYTES:
        raise ProtocolError(f"消息过大（>{MAX_MSG_BYTES} 字节），已拒绝接收")
    try:
        msg = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ProtocolError(f"消息不是合法 JSON: {e}") from e
    if not isinstance(msg, dict):
        raise ProtocolError("消息必须是 JSON 对象")
    return msg