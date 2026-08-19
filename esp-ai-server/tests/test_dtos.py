"""
dtos.py 单元测试

覆盖范围：
- MessageType 枚举
- ASRRequestDTO / ASRResponseDTO
- LLMRequestDTO / LLMResponseDTO
- TTSRequestDTO / TTSResponseDTO
- PipelineRequestDTO / PipelineResponseDTO
- SessionRequestDTO / SessionResponseDTO
- DeviceRequestDTO / DeviceResponseDTO
- WebSocketMessageDTO（to_json / from_json）
"""
import time
from unittest.mock import patch

import pytest

from src.use_cases.dtos import (
    ASRRequestDTO,
    ASRResponseDTO,
    DeviceRequestDTO,
    DeviceResponseDTO,
    LLMRequestDTO,
    LLMResponseDTO,
    MessageType,
    PipelineRequestDTO,
    PipelineResponseDTO,
    SessionRequestDTO,
    SessionResponseDTO,
    TTSRequestDTO,
    TTSResponseDTO,
    WebSocketMessageDTO,
)


# ============================================================
# MessageType 枚举
# ============================================================


class TestMessageType:
    """MessageType 枚举值验证"""

    def test_ping_value(self):
        assert MessageType.PING.value == "ping"

    def test_pong_value(self):
        assert MessageType.PONG.value == "pong"

    def test_keepalive_value(self):
        assert MessageType.KEEPALIVE.value == "keepalive"

    def test_start_value(self):
        assert MessageType.START.value == "start"

    def test_session_start_value(self):
        assert MessageType.SESSION_START.value == "session_start"

    def test_session_end_value(self):
        assert MessageType.SESSION_END.value == "session_end"

    def test_audio_data_value(self):
        assert MessageType.AUDIO_DATA.value == "audio_data"

    def test_play_audio_value(self):
        assert MessageType.PLAY_AUDIO.value == "play_audio"

    def test_iat_end_value(self):
        assert MessageType.IAT_END.value == "iat_end"

    def test_ws_connected_value(self):
        assert MessageType.WS_CONNECTED.value == "play_audio_ws_conntceed"

    def test_is_str_enum(self):
        # str 枚举应可直接与字符串比较
        assert MessageType.PING == "ping"

    def test_from_value(self):
        assert MessageType("start") is MessageType.START


# ============================================================
# ASRRequestDTO
# ============================================================


class TestASRRequestDTO:
    """ASR 请求 DTO"""

    def test_defaults(self):
        dto = ASRRequestDTO()
        assert dto.session_id == ""
        assert dto.device_id == ""
        assert dto.audio_data == b""
        assert dto.audio_format == "pcm"
        assert dto.sample_rate == 16000
        assert dto.streaming is True
        assert dto.language == "zh-CN"
        assert dto.metadata == {}

    def test_with_values(self):
        dto = ASRRequestDTO(
            session_id="s1",
            device_id="d1",
            audio_data=b"abc",
            audio_format="wav",
            sample_rate=8000,
            streaming=False,
            language="en-US",
            metadata={"k": "v"},
        )
        assert dto.session_id == "s1"
        assert dto.audio_data == b"abc"
        assert dto.audio_format == "wav"
        assert dto.sample_rate == 8000
        assert dto.streaming is False
        assert dto.metadata == {"k": "v"}

    def test_metadata_independent_per_instance(self):
        # 默认 factory 应保证每个实例独立
        a = ASRRequestDTO()
        b = ASRRequestDTO()
        a.metadata["x"] = 1
        assert "x" not in b.metadata


# ============================================================
# ASRResponseDTO
# ============================================================


class TestASRResponseDTO:
    """ASR 响应 DTO"""

    def test_defaults(self):
        dto = ASRResponseDTO()
        assert dto.success is False
        assert dto.text == ""
        assert dto.is_final is False
        assert dto.confidence == 0.0
        assert dto.error is None
        assert dto.processing_time_ms == 0.0

    def test_with_error(self):
        dto = ASRResponseDTO(success=False, error="timeout")
        assert dto.error == "timeout"
        assert dto.success is False

    def test_with_success(self):
        dto = ASRResponseDTO(
            success=True, text="你好", is_final=True, confidence=0.95
        )
        assert dto.success is True
        assert dto.text == "你好"
        assert dto.is_final is True


# ============================================================
# LLMRequestDTO / LLMResponseDTO
# ============================================================


class TestLLMRequestDTO:
    """LLM 请求 DTO"""

    def test_defaults(self):
        dto = LLMRequestDTO()
        assert dto.messages == []
        assert dto.system_prompt == ""
        assert dto.user_input == ""
        assert dto.temperature == 0.7
        assert dto.max_tokens == 2000
        assert dto.stream is True
        assert dto.tools == []
        assert dto.tool_calls == []

    def test_with_messages(self):
        msgs = [{"role": "user", "content": "hi"}]
        dto = LLMRequestDTO(messages=msgs, user_input="hi", temperature=0.1)
        assert dto.messages == msgs
        assert dto.user_input == "hi"
        assert dto.temperature == 0.1


class TestLLMResponseDTO:
    """LLM 响应 DTO"""

    def test_defaults(self):
        dto = LLMResponseDTO()
        assert dto.success is False
        assert dto.content == ""
        assert dto.is_stream is True
        assert dto.tokens_used == 0
        assert dto.finish_reason == ""
        assert dto.tool_calls == []

    def test_with_content(self):
        dto = LLMResponseDTO(success=True, content="hello", tokens_used=10, finish_reason="stop")
        assert dto.content == "hello"
        assert dto.tokens_used == 10


# ============================================================
# TTSRequestDTO / TTSResponseDTO
# ============================================================


class TestTTSRequestDTO:
    def test_defaults(self):
        dto = TTSRequestDTO()
        assert dto.text == ""
        assert dto.voice_type == ""
        assert dto.speed == 1.0
        assert dto.volume == 1.0
        assert dto.pitch == 1.0
        assert dto.format == "mp3"
        assert dto.streaming is True
        assert dto.task_id == ""

    def test_with_values(self):
        dto = TTSRequestDTO(text="你好", voice_type="v1", speed=1.5, task_id="t1")
        assert dto.text == "你好"
        assert dto.voice_type == "v1"
        assert dto.speed == 1.5
        assert dto.task_id == "t1"


class TestTTSResponseDTO:
    def test_defaults(self):
        dto = TTSResponseDTO()
        assert dto.success is False
        assert dto.audio_data == b""
        assert dto.is_final is False
        assert dto.task_id == ""
        assert dto.duration_ms == 0.0
        assert dto.error is None

    def test_with_audio(self):
        dto = TTSResponseDTO(success=True, audio_data=b"audio", duration_ms=1234.5)
        assert dto.audio_data == b"audio"
        assert dto.duration_ms == 1234.5


# ============================================================
# PipelineRequestDTO / PipelineResponseDTO
# ============================================================


class TestPipelineRequestDTO:
    def test_defaults(self):
        dto = PipelineRequestDTO()
        assert dto.input_text == ""
        assert dto.asr_text == ""
        assert dto.interrupt is False
        assert dto.cancel_event is None
        assert dto.metadata == {}

    def test_with_cancel_event(self):
        ev = object()
        dto = PipelineRequestDTO(input_text="hi", cancel_event=ev, interrupt=True)
        assert dto.cancel_event is ev
        assert dto.interrupt is True


class TestPipelineResponseDTO:
    def test_defaults(self):
        dto = PipelineResponseDTO()
        assert dto.success is False
        assert dto.stage == ""
        assert dto.output_text == ""
        assert dto.audio_chunks == []
        assert dto.total_duration_ms == 0.0
        assert dto.sentences_count == 0
        assert dto.interrupted is False

    def test_with_output(self):
        dto = PipelineResponseDTO(
            success=True,
            stage="tts",
            output_text="hi",
            audio_chunks=[b"a", b"b"],
            total_duration_ms=500.0,
            sentences_count=2,
        )
        assert dto.audio_chunks == [b"a", b"b"]
        assert dto.sentences_count == 2


# ============================================================
# SessionRequestDTO / SessionResponseDTO
# ============================================================


class TestSessionRequestDTO:
    def test_defaults(self):
        dto = SessionRequestDTO()
        assert dto.device_id == ""
        assert dto.device_key == ""
        assert dto.action == ""
        assert dto.metadata == {}

    def test_with_action(self):
        dto = SessionRequestDTO(device_id="d1", action="close")
        assert dto.action == "close"


class TestSessionResponseDTO:
    def test_defaults(self):
        dto = SessionResponseDTO()
        assert dto.success is False
        assert dto.session_id == ""
        assert dto.is_active is False
        assert dto.message_count == 0
        assert dto.created_at == 0.0

    def test_with_values(self):
        dto = SessionResponseDTO(
            success=True, session_id="s1", state="idle", is_active=True, message_count=5
        )
        assert dto.is_active is True
        assert dto.message_count == 5


# ============================================================
# DeviceRequestDTO / DeviceResponseDTO
# ============================================================


class TestDeviceRequestDTO:
    def test_defaults(self):
        dto = DeviceRequestDTO()
        assert dto.device_key == ""
        assert dto.api_key == ""
        assert dto.action == ""
        assert dto.config == {}

    def test_with_config(self):
        cfg = {"ip": "1.2.3.4"}
        dto = DeviceRequestDTO(device_key="k1", api_key="a1", action="register", config=cfg)
        assert dto.config == cfg
        assert dto.action == "register"


class TestDeviceResponseDTO:
    def test_defaults(self):
        dto = DeviceResponseDTO()
        assert dto.success is False
        assert dto.is_online is False
        assert dto.is_authenticated is False
        assert dto.last_seen is None
        assert dto.error is None

    def test_with_values(self):
        dto = DeviceResponseDTO(
            success=True, device_id="d1", name="dev", is_online=True, is_authenticated=True
        )
        assert dto.is_online is True
        assert dto.name == "dev"


# ============================================================
# WebSocketMessageDTO
# ============================================================


class TestWebSocketMessageDTOToJson:
    """WebSocketMessageDTO.to_json"""

    def test_minimal(self):
        dto = WebSocketMessageDTO(type=MessageType.PING)
        result = dto.to_json()
        assert result["type"] == "ping"
        assert "timestamp" in result
        # 无 data/session_id/trace_id 时不应包含这些键
        assert "data" not in result
        assert "session_id" not in result
        assert "trace_id" not in result

    def test_with_data(self):
        dto = WebSocketMessageDTO(type=MessageType.PLAY_AUDIO, data={"url": "x"})
        result = dto.to_json()
        assert result["data"] == {"url": "x"}
        assert result["type"] == "play_audio"

    def test_with_session_and_trace(self):
        dto = WebSocketMessageDTO(
            type=MessageType.PONG, session_id="s1", trace_id="t1"
        )
        result = dto.to_json()
        assert result["session_id"] == "s1"
        assert result["trace_id"] == "t1"

    def test_type_as_string(self):
        # type 为字符串时也应原样输出
        dto = WebSocketMessageDTO(type="custom_type")
        result = dto.to_json()
        assert result["type"] == "custom_type"

    def test_data_none_not_included(self):
        dto = WebSocketMessageDTO(type=MessageType.PING, data=None)
        result = dto.to_json()
        assert "data" not in result


class TestWebSocketMessageDTOFromJson:
    """WebSocketMessageDTO.from_json"""

    def test_with_known_type(self):
        data = {"type": "ping", "data": "hello", "session_id": "s1", "trace_id": "t1"}
        dto = WebSocketMessageDTO.from_json(data)
        assert dto.type is MessageType.PING
        assert dto.data == "hello"
        assert dto.session_id == "s1"
        assert dto.trace_id == "t1"

    def test_with_unknown_type_keeps_string(self):
        data = {"type": "unknown_type"}
        dto = WebSocketMessageDTO.from_json(data)
        # 未知类型应保留为字符串
        assert dto.type == "unknown_type"
        assert not isinstance(dto.type, MessageType)

    def test_missing_type_returns_empty_string(self):
        # from_json 中 data.get("type", "") 返回空串，无法匹配 MessageType，保留为字符串
        data = {}
        dto = WebSocketMessageDTO.from_json(data)
        assert dto.type == ""

    def test_empty_type_returns_empty_string(self):
        data = {"type": ""}
        dto = WebSocketMessageDTO.from_json(data)
        assert dto.type == ""

    def test_missing_timestamp_uses_now(self):
        data = {"type": "ping"}
        before = time.time()
        dto = WebSocketMessageDTO.from_json(data)
        after = time.time()
        assert before <= dto.timestamp <= after

    def test_explicit_timestamp(self):
        data = {"type": "ping", "timestamp": 12345.0}
        dto = WebSocketMessageDTO.from_json(data)
        assert dto.timestamp == 12345.0

    def test_roundtrip(self):
        original = WebSocketMessageDTO(
            type=MessageType.SESSION_START, data="start", session_id="s1", trace_id="t1"
        )
        js = original.to_json()
        restored = WebSocketMessageDTO.from_json(js)
        assert restored.type is MessageType.SESSION_START
        assert restored.data == "start"
        assert restored.session_id == "s1"
        assert restored.trace_id == "t1"

    def test_data_defaults_none(self):
        dto = WebSocketMessageDTO.from_json({"type": "ping"})
        assert dto.data is None

    def test_empty_data_field(self):
        # data 显式为 None
        dto = WebSocketMessageDTO.from_json({"type": "ping", "data": None})
        assert dto.data is None
