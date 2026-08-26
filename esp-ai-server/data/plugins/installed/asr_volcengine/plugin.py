"""火山引擎 ASR 服务插件。

使用 WebSocket SDK 连接火山引擎 ASR 服务（SAUC 协议），实现流式语音识别。
插件开发者只需关注协议拼装和解析，SDK 封装了 WebSocket 连接管理。

SAUC 协议帧格式：
  - 4 字节头部（version/header_size/message_type/flags/serialization/compression）
  - 4 字节 payload 大小（大端序）
  - payload（JSON 编码）

实现参考：
  1. asr_start_session: 连接 WS，发送初始化配置，返回 session_id
  2. asr_send_audio: 发送音频分片，返回当前识别结果
  3. asr_get_result: 获取当前识别结果
  4. asr_end_session: 发送结束信号，关闭 WS，返回最终结果
"""

from __future__ import annotations

import asyncio
import json
import struct
import uuid

from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import ws_connect, ws_send, ws_recv, ws_close, ws_prewarm

# 火山引擎 ASR SAUC 地址
ASR_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"

# 会话缓存：session_id → {"ws_id": str, "current_text": str, "is_final": bool}
_sessions: dict[str, dict] = {}

# 互斥锁：防止多个协程并发 ws_recv 导致 "cannot call recv while another coroutine is running"
# 火山引擎 ASR 会话只会同时接收一个结果，所以用全局锁即可
import asyncio
_ws_recv_lock = asyncio.Lock()


def _make_header(message_type: int, flags: int = 0) -> bytes:
    """构造 SAUC 协议 4 字节头部。"""
    version = 0x1 << 4
    header_size = 0x1 << 0
    byte0 = (version | header_size).to_bytes(1, "big")
    byte1 = ((message_type << 4) | flags).to_bytes(1, "big")
    serialization = 0x1 << 4  # JSON
    compression = 0x0 << 0
    byte2 = (serialization | compression).to_bytes(1, "big")
    byte3 = (0).to_bytes(1, "big")
    return byte0 + byte1 + byte2 + byte3


def _make_payload(data: dict) -> bytes:
    """构造 SAUC 协议 payload：4 字节长度 + JSON 数据。"""
    json_bytes = json.dumps(data).encode("utf-8")
    return struct.pack(">I", len(json_bytes)) + json_bytes


def _parse_response(data: bytes) -> dict | None:
    """解析 SAUC 协议响应帧。"""
    if len(data) < 12:
        return None
    payload_size = struct.unpack(">I", data[8:12])[0]
    if len(data) < 12 + payload_size:
        return None
    payload = data[12:12 + payload_size]
    try:
        return json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _extract_text(result: dict) -> str:
    """从 ASR 结果中提取文本。"""
    result_data = result.get("result", {})
    texts = result_data.get("texts", [])
    if texts:
        return texts[0].get("text", "")
    return result_data.get("text", "")


def _is_final(result: dict) -> bool:
    """判断 ASR 结果是否为最终结果。"""
    if result.get("is_final"):
        return True
    result_data = result.get("result", {})
    additions = result_data.get("additions", {})
    if additions.get("definite"):
        return True
    utterances = result_data.get("utterances", [])
    for utt in utterances:
        if utt.get("definite") and utt.get("text"):
            return True
    return False


@tool(cache=False)
async def asr_volcengine_prewarm(config: dict | None = None,
                                 tool_manager=None) -> dict:
    """预热 ASR WebSocket 连接池（设备连接时调用，确保首次语音输入免建连）。

    Args:
        config: 配置，包含 api_key, resource_id

    Returns:
        {"created": int, "error": str|null}
    """
    cfg = config or {}
    api_key = cfg.get("api_key", "")
    resource_id = cfg.get("resource_id", "volc.bigasr.sauc.duration")

    if not api_key:
        return {"created": 0, "error": "api_key 未配置"}

    headers = {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": resource_id,
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }
    try:
        created = await ws_prewarm(ASR_URL, headers, count=2,
                                   pool_headers=["X-Api-Key", "X-Api-Resource-Id"])
        return {"created": created, "error": None}
    except Exception as e:
        return {"created": 0, "error": f"预热失败: {e}"}


@tool(cache=False)
async def asr_volcengine_start_session(config: dict | None = None,
                                       tool_manager=None) -> dict:
    """开始 ASR 识别会话，返回 session_id。

    Args:
        config: 配置，包含 api_key, resource_id, model_name

    Returns:
        {"session_id": str, "error": str|null}
    """
    cfg = config or {}
    api_key = cfg.get("api_key", "")
    resource_id = cfg.get("resource_id", "volc.bigasr.sauc.duration")
    model_name = cfg.get("model_name", "bigmodel")

    if not api_key:
        return {"session_id": "", "error": "api_key 未配置"}

    headers = {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": resource_id,
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }

    # 先触发后台预取（为下次会话提前建连，预取 2 个保证池中有备用），再取当前连接
    try:
        asyncio.get_running_loop().create_task(
            ws_prewarm(ASR_URL, headers, count=2,
                       pool_headers=["X-Api-Key", "X-Api-Resource-Id"])
        )
    except Exception:
        pass

    # 从框架预热池取连接（prewarm 模式：取预热连接，会话结束真正关闭）
    try:
        ws_id = await ws_connect(ASR_URL, headers, pool="prewarm",
                                 pool_headers=["X-Api-Key", "X-Api-Resource-Id"])
    except Exception as e:
        return {"session_id": "", "error": f"WebSocket 连接失败: {e}"}

    # 发送初始化配置（SAUC 协议：message_type=1）
    config_request = _make_header(message_type=1, flags=0)
    config_payload = _make_payload({
        "user": {"uid": "esp-ai"},
        "audio": {
            "format": "pcm",
            "rate": 16000,
            "bits": 16,
            "channel": 1,
        },
        "request": {
            "model_name": model_name,
            "enable_itn": False,
            "enable_punc": False,
            "end_window_size": 400,
            "vad_segment_duration": 2000,
            "force_to_speech_time": 1000,
        },
    })
    await ws_send(ws_id, config_request + config_payload)

    sess_id = uuid.uuid4().hex[:8]
    _sessions[sess_id] = {
        "ws_id": ws_id,
        "current_text": "",
        "is_final": False,
        "buffer": [],
    }
    return {"session_id": sess_id, "error": None}


@tool(cache=False)
async def asr_volcengine_send_audio(session_id: str, audio: str,
                                    tool_manager=None) -> dict:
    """发送音频数据分片，返回当前识别结果。

    Args:
        session_id: 会话 ID（由 start_session 返回）
        audio: base64 编码的音频数据（16bit PCM，16000Hz 单声道）

    Returns:
        {"text": str, "is_final": bool, "error": str|null}
    """
    import base64

    session = _sessions.get(session_id)
    if not session:
        return {"text": "", "is_final": True, "error": "session not found"}

    audio_bytes = base64.b64decode(audio)

    # 发送音频数据（SAUC 协议：message_type=2），不等待结果
    audio_header = _make_header(message_type=2)
    audio_payload = struct.pack(">I", len(audio_bytes)) + audio_bytes
    try:
        await ws_send(session["ws_id"], audio_header + audio_payload)
    except Exception as e:
        return {"text": session["current_text"], "is_final": True,
                "error": f"发送音频失败: {e}"}

    return {"text": session["current_text"], "is_final": session.get("is_final", False), "error": None}


@tool(cache=False)
async def asr_volcengine_get_result(session_id: str, tool_manager=None) -> dict:
    """获取当前识别结果。

    Args:
        session_id: 会话 ID

    Returns:
        {"text": str, "is_final": bool, "error": str|null}
    """
    session = _sessions.get(session_id)
    if not session:
        return {"text": "", "is_final": True, "error": "session not found"}

    # 尝试接收最新结果
    try:
        data = await ws_recv(session["ws_id"], timeout=0.1)
        if data:
            result = _parse_response(data)
            if result:
                if not session.get("logged_first_resp"):
                    session["logged_first_resp"] = True
                    print(f"[asr_volcengine] 首个响应: {json.dumps(result, ensure_ascii=False)[:200]}", flush=True)
                text = _extract_text(result)
                if text:
                    session["current_text"] = text
                if _is_final(result):
                    session["is_final"] = True
    except Exception as e:
        # 连接已断开等致命错误：不再吞掉，让上层立即终止会话
        return {"text": session["current_text"], "is_final": True,
                "error": f"接收失败: {e}"}

    return {
        "text": session["current_text"],
        "is_final": session.get("is_final", False),
        "error": None,
    }


@tool(cache=False)
async def asr_volcengine_end_session(session_id: str,
                                     tool_manager=None) -> dict:
    """结束 ASR 会话，返回最终识别结果。

    Args:
        session_id: 会话 ID

    Returns:
        {"final_text": str, "error": str|null}
    """
    session = _sessions.pop(session_id, None)
    if not session:
        return {"final_text": "", "error": "session not found"}

    # 发送结束信号（SAUC 协议：message_type=2, flags=2）
    # 注意：结束帧也必须带 4 字节 payload 长度前缀（值为 0），
    # 否则火山报 "parse payload size failed: body too short" 并强制断连
    try:
        end_frame = _make_header(message_type=2, flags=2) + struct.pack(">I", 0)
        await ws_send(session["ws_id"], end_frame)
    except Exception as e:
        return {"final_text": session["current_text"], "error": f"发送结束帧失败: {e}"}

    # 读取最终结果
    final_text = session["current_text"]
    try:
        while True:
            data = await ws_recv(session["ws_id"], timeout=0.5)
            if data is None:
                break
            result = _parse_response(data)
            if result:
                text = _extract_text(result)
                if text:
                    final_text = text
                if _is_final(result) or result.get("code") == 0:
                    break
    except Exception:
        pass

    # 关闭连接
    try:
        await ws_close(session["ws_id"])
    except Exception:
        pass

    return {"final_text": final_text, "error": None}