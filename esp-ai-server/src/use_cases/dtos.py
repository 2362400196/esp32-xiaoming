"""
DTOs - Data Transfer Objects (数据传输对象)

用于在Use Case和外部层之间传递数据
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class MessageType(str, Enum):
    """WebSocket消息类型"""
    # 连接管理
    PING = "ping"
    PONG = "pong"
    KEEPALIVE = "keepalive"

    # 会话控制
    START = "start"
    STOP = "session_stop"
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    SESSION_STATUS = "session_status"

    # 音频相关
    AUDIO_DATA = "audio_data"
    PLAY_AUDIO = "play_audio"
    CLIENT_OUT_AUDIO_OVER = "client_out_audio_over"
    CLIENT_OUT_AUDIO_ING = "client_out_audio_ing"
    CLIENT_AVAILABLE_AUDIO = "client_available_audio"

    # ASR相关
    IAT_END = "iat_end"
    IAT_START = "iat_start"
    INSTRUCT_IAT_CB = "instruct"  # on_iat_cb

    # LLM相关
    INSTRUCT_LLM_CB = "instruct"  # on_llm_cb

    # TTS相关
    TTS_CHUNK_START = "tts_chunk_start"
    TTS_CHUNK_END = "tts_chunk_end"
    TTS_REAL_END = "tts_real_end"
    STC_TIME = "stc_time"

    # 连接确认
    WS_CONNECTED = "play_audio_ws_conntceed"


@dataclass
class ASRRequestDTO:
    """ASR请求DTO"""
    session_id: str = ""
    device_id: str = ""
    audio_data: bytes = b""
    audio_format: str = "pcm"
    sample_rate: int = 16000
    streaming: bool = True
    language: str = "zh-CN"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ASRResponseDTO:
    """ASR响应DTO"""
    success: bool = False
    text: str = ""
    is_final: bool = False
    confidence: float = 0.0
    session_id: str = ""
    device_id: str = ""
    error: Optional[str] = None
    processing_time_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMRequestDTO:
    """LLM请求DTO"""
    session_id: str = ""
    device_id: str = ""
    messages: list[dict] = field(default_factory=list)
    system_prompt: str = ""
    user_input: str = ""
    temperature: float = 0.7
    max_tokens: int = 2000
    stream: bool = True
    tools: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponseDTO:
    """LLM响应DTO"""
    success: bool = False
    content: str = ""
    is_stream: bool = True
    tokens_used: int = 0
    finish_reason: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    session_id: str = ""
    error: Optional[str] = None
    processing_time_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TTSRequestDTO:
    """TTS请求DTO"""
    session_id: str = ""
    device_id: str = ""
    text: str = ""
    voice_type: str = ""
    speed: float = 1.0
    volume: float = 1.0
    pitch: float = 1.0
    format: str = "mp3"
    streaming: bool = True
    task_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TTSResponseDTO:
    """TTS响应DTO"""
    success: bool = False
    audio_data: bytes = b""
    is_final: bool = False
    task_id: str = ""
    session_id: str = ""
    duration_ms: float = 0.0
    error: Optional[str] = None
    processing_time_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineRequestDTO:
    """Pipeline请求DTO"""
    session_id: str = ""
    device_id: str = ""
    input_text: str = ""
    asr_text: str = ""
    interrupt: bool = False
    cancel_event: Any = None  # asyncio.Event
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineResponseDTO:
    """Pipeline响应DTO"""
    success: bool = False
    stage: str = ""  # asr, llm, tts
    output_text: str = ""
    audio_chunks: list[bytes] = field(default_factory=list)
    total_duration_ms: float = 0.0
    sentences_count: int = 0
    interrupted: bool = False
    error: Optional[str] = None
    session_id: str = ""
    processing_time_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionRequestDTO:
    """会话请求DTO"""
    device_id: str = ""
    device_key: str = ""
    action: str = ""  # create, close, interrupt, get_status
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionResponseDTO:
    """会话响应DTO"""
    success: bool = False
    session_id: str = ""
    device_id: str = ""
    state: str = ""
    duration: float = 0.0
    message_count: int = 0
    is_active: bool = False
    created_at: float = 0.0
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceRequestDTO:
    """设备请求DTO"""
    device_key: str = ""
    device_id: str = ""
    api_key: str = ""
    action: str = ""  # register, unregister, authenticate, get_info
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceResponseDTO:
    """设备响应DTO"""
    success: bool = False
    device_id: str = ""
    device_key: str = ""
    name: str = ""
    is_online: bool = False
    is_authenticated: bool = False
    last_seen: Optional[float] = None
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WebSocketMessageDTO:
    """WebSocket消息DTO"""
    type: MessageType = MessageType.PING
    data: Any = None
    bytes_data: Optional[bytes] = None
    session_id: str = ""
    device_id: str = ""
    timestamp: float = field(default_factory=time.time)
    trace_id: str = ""

    def to_json(self) -> dict:
        """转换为JSON字典"""
        result = {
            "type": self.type.value if isinstance(self.type, MessageType) else self.type,
            "timestamp": self.timestamp,
        }
        if self.data is not None:
            result["data"] = self.data
        if self.session_id:
            result["session_id"] = self.session_id
        if self.trace_id:
            result["trace_id"] = self.trace_id
        return result

    @classmethod
    def from_json(cls, data: dict) -> WebSocketMessageDTO:
        """从JSON字典创建"""
        msg_type = data.get("type", "")
        try:
            msg_type = MessageType(msg_type)
        except ValueError:
            pass

        return cls(
            type=msg_type,
            data=data.get("data"),
            session_id=data.get("session_id", ""),
            trace_id=data.get("trace_id", ""),
            timestamp=data.get("timestamp", time.time()),
        )


# ── 内部使用DTOs ──

__all__ = [
    # Enums
    "MessageType",
    # Request/Response DTOs
    "ASRRequestDTO",
    "ASRResponseDTO",
    "LLMRequestDTO",
    "LLMResponseDTO",
    "TTSRequestDTO",
    "TTSResponseDTO",
    "PipelineRequestDTO",
    "PipelineResponseDTO",
    "SessionRequestDTO",
    "SessionResponseDTO",
    "DeviceRequestDTO",
    "DeviceResponseDTO",
    "WebSocketMessageDTO",
    # Internal DTOs
    "SentenceDTO",
    "AudioFrameDTO",
    "ToolCallDTO",
    "EmotionResultDTO",
    "ConnectionStatsDTO",
]
