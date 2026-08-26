"""火山引擎 TTS 服务插件。

使用 WebSocket SDK 连接火山引擎 TTS 服务（V3 双向流式协议），实现流式语音合成。
插件开发者只需关注协议拼装和解析，SDK 封装了 WebSocket 连接管理。

V3 协议帧格式：
  - 4 字节头部（version/header_size/type/flag/serialization/compression）
  - 4 字节 event（WithEvent 标志）
  - 4 字节 session_id 长度 + session_id 数据
  - 4 字节 connect_id 长度 + connect_id 数据（仅 ConnectionStarted 等事件）
  - 4 字节 sequence（PositiveSeq 标志）
  - 4 字节 payload 大小 + payload 数据

实现参考：
  1. tts_start_synthesis: 连接 WS，发送 FullClientRequest 帧，返回 syn_id
  2. tts_get_audio: 从 WS 接收 AudioOnlyServer 帧，返回 base64 编码的音频
  3. tts_end_synthesis: 发送 FinishConnection 帧，关闭 WS
"""

from __future__ import annotations

import io
import json
import struct
import time
import uuid

from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import ws_connect, ws_send, ws_recv, ws_close, json_dumps

import logging
logger = logging.getLogger("plugin.tts_volcengine")

# 火山引擎 TTS V3 协议地址
TTS_URL = "wss://openspeech.bytedance.com/api/v3/tts/unidirectional/stream"

# 会话缓存：syn_id → {"ws_id": str, "done": bool, "buffer": list}
_sessions: dict[str, dict] = {}

# ── 协议常量 ────────────────────────────────────────────────

MSG_TYPE_FULL_CLIENT_REQUEST = 0b1
MSG_TYPE_AUDIO_ONLY_CLIENT = 0b10
MSG_TYPE_FULL_SERVER_RESPONSE = 0b1001
MSG_TYPE_AUDIO_ONLY_SERVER = 0b1011
MSG_TYPE_FRONT_END_SERVER = 0b1100
MSG_TYPE_ERROR = 0b1111

FLAG_NO_SEQ = 0
FLAG_POSITIVE_SEQ = 0b1
FLAG_WITH_EVENT = 0b100

EVENT_FINISH_CONNECTION = 2
EVENT_CONNECTION_FINISHED = 52
EVENT_START_SESSION = 100
EVENT_FINISH_SESSION = 102
EVENT_SESSION_FINISHED = 152
EVENT_SESSION_FAILED = 153
EVENT_TTS_SENTENCE_START = 350
EVENT_TTS_SENTENCE_END = 351
EVENT_TTS_RESPONSE = 352
EVENT_TTS_ENDED = 359


def _build_message(type_: int, flags: int = 0, payload: bytes = b"",
                   event: int | None = None, session_id: str = "",
                   sequence: int = 0) -> bytes:
    """构造 TTS V3 协议帧，与旧版 Message.marshal() 行为一致。"""
    buf = io.BytesIO()

    # 4 字节头部
    version = 0x1 << 4
    header_size = 0x1 << 0
    byte0 = (version | header_size).to_bytes(1, "big")
    byte1 = ((type_ << 4) | flags).to_bytes(1, "big")
    serialization = 0x1 << 4  # JSON
    compression = 0x0 << 0
    byte2 = (serialization | compression).to_bytes(1, "big")
    byte3 = (0).to_bytes(1, "big")
    buf.write(byte0 + byte1 + byte2 + byte3)

    # WithEvent → 4 字节 event + session_id（某些事件省略 session_id）
    if flags & FLAG_WITH_EVENT:
        buf.write(struct.pack(">i", event or 0))
        # FinishConnection / StartConnection / ConnectionStarted / ConnectionFailed 跳过 session_id
        skip_events = {2, 1, 50, 51}
        if event not in skip_events:
            sid_bytes = session_id.encode("utf-8")
            buf.write(struct.pack(">I", len(sid_bytes)))
            if sid_bytes:
                buf.write(sid_bytes)

    # PositiveSeq → 4 字节 sequence
    if flags & FLAG_POSITIVE_SEQ:
        buf.write(struct.pack(">i", sequence))

    # payload
    buf.write(struct.pack(">I", len(payload)))
    if payload:
        buf.write(payload)

    return buf.getvalue()


def _parse_message(data: bytes) -> dict:
    """解析 TTS V3 协议帧，返回结构化字典。"""
    msg = {
        "type": None,
        "flags": 0,
        "event": None,
        "session_id": "",
        "connect_id": "",
        "sequence": 0,
        "payload": b"",
        "error_code": 0,
    }
    if len(data) < 3:
        msg["type"] = MSG_TYPE_ERROR
        return msg

    buf = io.BytesIO(data)
    byte0 = buf.read(1)[0]
    byte1 = buf.read(1)[0]
    byte2 = buf.read(1)[0]
    msg["type"] = byte1 >> 4
    msg["flags"] = byte1 & 0b00001111

    header_size = byte0 & 0b00001111
    read_size = 3
    if padding := (header_size * 4) - read_size:
        buf.read(padding)

    flags = msg["flags"]
    if flags & FLAG_WITH_EVENT:
        ev_bytes = buf.read(4)
        if len(ev_bytes) == 4:
            msg["event"] = struct.unpack(">i", ev_bytes)[0]
        event = msg["event"]
        # 跳过 session_id 的事件：StartConnection(1), FinishConnection(2),
        # ConnectionStarted(50), ConnectionFailed(51)
        if event not in (1, 2, 50, 51):
            sid_len_bytes = buf.read(4)
            if len(sid_len_bytes) == 4:
                sid_len = struct.unpack(">I", sid_len_bytes)[0]
                if sid_len > 0:
                    msg["session_id"] = buf.read(sid_len).decode("utf-8", errors="replace")
        # connect_id 仅 ConnectionStarted(50)/ConnectionFailed(51)/ConnectionFinished(52)
        if event in (50, 51, 52):
            cid_len_bytes = buf.read(4)
            if len(cid_len_bytes) == 4:
                cid_len = struct.unpack(">I", cid_len_bytes)[0]
                if cid_len > 0:
                    msg["connect_id"] = buf.read(cid_len).decode("utf-8", errors="replace")

    if msg["type"] == MSG_TYPE_ERROR:
        ec_bytes = buf.read(4)
        if len(ec_bytes) == 4:
            msg["error_code"] = struct.unpack(">I", ec_bytes)[0]
    elif flags & (FLAG_POSITIVE_SEQ):
        seq_bytes = buf.read(4)
        if len(seq_bytes) == 4:
            msg["sequence"] = struct.unpack(">i", seq_bytes)[0]

    # payload
    plen_bytes = buf.read(4)
    if len(plen_bytes) == 4:
        plen = struct.unpack(">I", plen_bytes)[0]
        if plen > 0:
            msg["payload"] = buf.read(plen)

    return msg


def _build_request_payload(config: dict, text: str) -> bytes:
    """构造 TTS 合成请求 JSON payload。"""
    request = {
        "user": {"uid": str(uuid.uuid4())},
        "req_params": {
            "speaker": config.get("voice_type", "BV001_streaming"),
            "audio_params": {
                "format": "mp3",
                "sample_rate": int(config.get("sample_rate", "24000")),
                "speed_ratio": float(config.get("speed_ratio", "1.0")),
                "volume_ratio": float(config.get("volume_ratio", "1.0")),
                "pitch_ratio": float(config.get("pitch_ratio", "1.0")),
            },
            "text": text,
        },
    }
    return json.dumps(request, ensure_ascii=False).encode("utf-8")


@tool(cache=False)
async def tts_volcengine_start_synthesis(text: str, config: dict | None = None,
                                         tool_manager=None) -> dict:
    """开始 TTS 语音合成，返回 syn_id。

    Args:
        text: 待合成文本
        config: 配置，包含 api_key, resource_id, voice_type 等

    Returns:
        {"syn_id": str, "error": str|null}
    """
    cfg = config or {}
    api_key = cfg.get("api_key", "")
    resource_id = cfg.get("resource_id", "")

    if not api_key:
        return {"syn_id": "", "error": "api_key 未配置"}

    headers = {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": resource_id or "volc.tts.222222222",
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }

    # 从框架连接池取连接（reuse 模式：优先复用，close 时归还）
    try:
        ws_id = await ws_connect(TTS_URL, headers, pool="reuse",
                                 pool_headers=["X-Api-Key", "X-Api-Resource-Id"])
    except Exception as e:
        return {"syn_id": "", "error": f"WebSocket 连接失败: {e}"}

    # 发送合成请求帧（FullClientRequest）
    payload = _build_request_payload(cfg, text)
    request_frame = _build_message(
        type_=MSG_TYPE_FULL_CLIENT_REQUEST,
        flags=FLAG_NO_SEQ,
        payload=payload,
    )
    try:
        await ws_send(ws_id, request_frame)
    except Exception as e:
        # 连接可能已被服务端关闭，重建后重试
        try:
            await ws_close(ws_id)
        except Exception:
            pass
        try:
            ws_id = await ws_connect(TTS_URL, headers, pool="reuse",
                                     pool_headers=["X-Api-Key", "X-Api-Resource-Id"])
        except Exception as e2:
            return {"syn_id": "", "error": f"WebSocket 连接失败: {e2}"}
        try:
            await ws_send(ws_id, request_frame)
        except Exception as e3:
            return {"syn_id": "", "error": f"发送请求失败: {e3}"}

    syn_id = uuid.uuid4().hex[:8]
    _sessions[syn_id] = {"ws_id": ws_id, "done": False, "buffer": []}
    return {"syn_id": syn_id, "error": None}


@tool(cache=False)
async def tts_volcengine_get_audio(syn_id: str, tool_manager=None) -> dict:
    """获取下一段音频数据。

    Args:
        syn_id: start_synthesis 返回的合成 ID

    Returns:
        {"audio_base64": str, "done": bool, "error": str|null}
    """
    import base64

    session = _sessions.get(syn_id)
    if not session:
        return {"audio_base64": "", "done": True, "error": "session not found"}

    # 优先从缓冲区取
    if session["buffer"]:
        return {"audio_base64": session["buffer"].pop(0), "done": False, "error": None}

    if session["done"]:
        return {"audio_base64": "", "done": True, "error": None}

    # 从 WebSocket 接收数据
    try:
        data = await ws_recv(session["ws_id"], timeout=0.5)
    except Exception as e:
        return {"audio_base64": "", "done": True, "error": f"接收失败: {e}"}

    if data is None:
        return {"audio_base64": "", "done": False, "error": None}

    # 解析 V3 协议帧
    logger.info(f"[TTS get_audio] 收到 {len(data)} bytes, 前16字节: {data[:16].hex()}")
    msg = _parse_message(data)
    logger.info(f"[TTS get_audio] 解析结果: type={msg['type']}, event={msg['event']}, "
                f"payload_len={len(msg.get('payload', b''))}")
    msg_type = msg.get("type")
    msg_event = msg.get("event")
    payload = msg.get("payload", b"")

    if msg_type == MSG_TYPE_ERROR:
        ec = msg.get("error_code", 0)
        session["done"] = True
        return {"audio_base64": "", "done": True, "error": f"服务端错误: code={ec}"}

    if msg_type == MSG_TYPE_AUDIO_ONLY_SERVER:
        # 音频数据
        if payload:
            audio_b64 = base64.b64encode(payload).decode("ascii")
            return {"audio_base64": audio_b64, "done": False, "error": None}
        return {"audio_base64": "", "done": False, "error": None}

    if msg_type == MSG_TYPE_FULL_SERVER_RESPONSE:
        if msg_event == EVENT_TTS_SENTENCE_END:
            # 句子结束，payload 可能包含额外音频数据
            if payload:
                audio_b64 = base64.b64encode(payload).decode("ascii")
                return {"audio_base64": audio_b64, "done": False, "error": None}
            return {"audio_base64": "", "done": False, "error": None}
        if msg_event == EVENT_FINISH_SESSION:
            session["done"] = True
            return {"audio_base64": "", "done": True, "error": None}
        if msg_event == EVENT_SESSION_FINISHED:
            # SessionFinished：火山服务端在音频全部下发后发送，标识合成完成
            session["done"] = True
            return {"audio_base64": "", "done": True, "error": None}
        if msg_event == EVENT_SESSION_FAILED:
            session["done"] = True
            payload_str = payload.decode("utf-8", errors="replace")
            return {"audio_base64": "", "done": True, "error": f"合成失败: {payload_str}"}
        if msg_event == EVENT_TTS_RESPONSE:
            # 响应帧，可能包含 MIME 类型信息
            return {"audio_base64": "", "done": False, "error": None}
        if msg_event == EVENT_TTS_ENDED:
            # 合成结束帧：所有音频已发送完毕，标记完成，避免调用方无限轮询
            session["done"] = True
            return {"audio_base64": "", "done": True, "error": None}
        if msg_event == EVENT_CONNECTION_FINISHED:
            # 服务端关闭连接，标记完成；连接归还池时由框架健康检查丢弃
            session["done"] = True
            return {"audio_base64": "", "done": True, "error": None}

    if msg_type == MSG_TYPE_FRONT_END_SERVER:
        # 前端结果帧
        return {"audio_base64": "", "done": False, "error": None}

    return {"audio_base64": "", "done": False, "error": None}


@tool(cache=False)
async def tts_volcengine_end_synthesis(syn_id: str, tool_manager=None) -> dict:
    """清理 TTS 合成会话，将连接归还框架连接池供后续句子复用。"""
    session = _sessions.pop(syn_id, None)
    if session:
        try:
            await ws_close(session["ws_id"])
        except Exception:
            pass
    return {}