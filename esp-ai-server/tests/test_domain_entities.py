"""
领域层单元测试

覆盖：
- src/domain/entities.py    : SessionState / Message / Conversation / ToolCall /
                              AudioChunk / Session / SessionError / Device / MemoryItem
- src/domain/exceptions.py  : DomainError 及各子类异常
- src/domain/value_objects.py : 各枚举与 frozen dataclass 值对象

测试策略：
- 正常路径、边界条件、异常分支均覆盖
- 不依赖网络与文件系统（frozen dataclass 不可变，直接断言字段）
"""
from __future__ import annotations

import time

import pytest

from src.domain.entities import (
    AudioChunk,
    Conversation,
    Device,
    MemoryItem,
    Message,
    Session,
    SessionError,
    SessionState,
    ToolCall,
)
from src.domain.exceptions import (
    ASRConnectionError,
    ASRError,
    ASRNoSpeechError,
    ASRTimeoutError,
    AuthenticationError,
    AudioProcessingError,
    ConfigurationError,
    DeviceAuthenticationError,
    DeviceLimitExceededError,
    DeviceNotFoundError,
    DeviceOfflineError,
    DomainError,
    InvalidStateTransitionError,
    LLMConnectionError,
    LLMError,
    LLMStreamingError,
    LLMTimeoutError,
    LLMTokenLimitError,
    MissingConfigurationError,
    PipelineError,
    PipelineInterruptedError,
    PipelineStageError,
    RateLimitExceededError,
    SessionAlreadyExistsError,
    SessionClosedError,
    SessionLimitExceededError,
    SessionNotFoundError,
    TTSError,
    TTSConnectionError,
    TTSSynthesisError,
    TTSTimeoutError,
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolTimeoutError,
    WebSocketError,
)
from src.domain.value_objects import (
    ASRConfig,
    ASRProvider,
    AudioConfig,
    AudioFormat,
    LLMConfig,
    LLMProvider,
    MemoryQuery,
    PoolConfig,
    TTSConfig,
    TTSProvider,
    WebSocketConfig,
    EmotionType,
)


# ════════════════════════════════════════════════════════════
# entities.py — SessionState 枚举
# ════════════════════════════════════════════════════════════
class TestSessionState:
    """SessionState 枚举测试"""

    def test_all_values(self):
        # 验证全部状态值字符串
        assert SessionState.IDLE.value == "idle"
        assert SessionState.ASR.value == "asr"
        assert SessionState.LLM.value == "llm"
        assert SessionState.TTS.value == "tts"
        assert SessionState.INTERRUPTED.value == "interrupted"
        assert SessionState.CLOSED.value == "closed"

    def test_value_is_string(self):
        # 枚举值应为字符串
        for state in SessionState:
            assert isinstance(state.value, str)

    def test_member_count(self):
        # 确保枚举成员数量符合预期（防止后续误删）
        assert len(list(SessionState)) == 6


# ════════════════════════════════════════════════════════════
# entities.py — Message 实体
# ════════════════════════════════════════════════════════════
class TestMessage:
    """Message 实体测试"""

    def test_create_with_defaults(self):
        # 默认值：自动生成 message_id、timestamp、空 metadata
        msg = Message(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.metadata == {}
        assert msg.message_id  # 非空
        assert msg.timestamp > 0

    def test_message_id_length(self):
        # message_id 来自 uuid4().hex[:12]，长度为 12
        msg = Message(role="user", content="x")
        assert len(msg.message_id) == 12

    def test_message_id_unique(self):
        # 多次创建应得到不同的 message_id
        m1 = Message(role="user", content="a")
        m2 = Message(role="user", content="a")
        assert m1.message_id != m2.message_id

    def test_to_dict(self):
        # to_dict 仅保留 role 与 content（用于 LLM API）
        msg = Message(role="assistant", content="hi", metadata={"k": "v"})
        d = msg.to_dict()
        assert d == {"role": "assistant", "content": "hi"}

    def test_repr_short_content(self):
        # __repr__ 截断到前 50 字符
        short = Message(role="user", content="hi")
        r = repr(short)
        assert "Message(role=user" in r
        assert "hi" in r

    def test_repr_long_content_truncated(self):
        # 长内容在 repr 中截断
        long_text = "x" * 200
        msg = Message(role="user", content=long_text)
        r = repr(msg)
        # repr 形如 Message(role=user, content=xxxxx...)
        assert "..." in r
        # 内容部分不应完整出现 200 个字符
        assert long_text not in r


# ════════════════════════════════════════════════════════════
# entities.py — Conversation 实体
# ════════════════════════════════════════════════════════════
class TestConversation:
    """Conversation 实体测试"""

    def test_default_creation(self):
        conv = Conversation()
        assert conv.messages == []
        assert conv.max_messages == 20
        assert conv.max_tokens == 2000
        assert conv.conversation_id  # 自动生成 8 字符
        assert len(conv.conversation_id) == 8

    def test_conversation_id_unique(self):
        c1 = Conversation()
        c2 = Conversation()
        assert c1.conversation_id != c2.conversation_id

    def test_add_message_updates_timestamp(self):
        conv = Conversation()
        old = conv.updated_at
        time.sleep(0.001)
        conv.add_message(Message(role="user", content="hi"))
        assert conv.updated_at >= old
        assert conv.message_count == 1

    def test_add_user_assistant_system_messages(self):
        conv = Conversation()
        u = conv.add_user_message("user-text")
        a = conv.add_assistant_message("assistant-text")
        s = conv.add_system_message("system-text")
        assert u.role == "user"
        assert a.role == "assistant"
        assert s.role == "system"
        assert conv.message_count == 3

    def test_trim_preserves_system_messages(self):
        # 当超过 max_messages 时，应删除最旧的非系统消息，保留系统消息
        conv = Conversation(max_messages=3)
        conv.add_system_message("sys")
        conv.add_user_message("u1")
        conv.add_user_message("u2")
        conv.add_user_message("u3")  # 触发裁剪
        # 系统消息保留，总数 == max_messages
        assert conv.message_count == 3
        assert conv.messages[0].role == "system"
        # 最旧的 u1 被删除
        contents = [m.content for m in conv.messages]
        assert "u1" not in contents

    def test_trim_keeps_system_at_front(self):
        # 系统消息在裁剪后保持在最前
        conv = Conversation(max_messages=3)
        conv.add_system_message("sys")
        conv.add_user_message("u1")
        conv.add_user_message("u2")
        conv.add_user_message("u3")  # 触发裁剪
        assert conv.messages[0].role == "system"
        assert conv.message_count == 3

    def test_build_messages_for_llm(self):
        conv = Conversation()
        conv.add_user_message("历史用户")
        conv.add_assistant_message("历史助手")
        conv.add_system_message("应被排除的系统消息")
        result = conv.build_messages_for_llm("SP", "当前输入")
        # 第一条为 system_prompt
        assert result[0] == {"role": "system", "content": "SP"}
        # 中间为非系统历史消息
        roles = [m["role"] for m in result]
        assert "system" not in roles[1:]  # 历史系统消息被排除
        # 最后为当前用户输入
        assert result[-1] == {"role": "user", "content": "当前输入"}

    def test_build_messages_for_llm_empty_history(self):
        conv = Conversation()
        result = conv.build_messages_for_llm("SP", "input")
        assert result == [
            {"role": "system", "content": "SP"},
            {"role": "user", "content": "input"},
        ]

    def test_clear(self):
        conv = Conversation()
        conv.add_user_message("x")
        old_updated = conv.updated_at
        time.sleep(0.001)
        conv.clear()
        assert conv.message_count == 0
        assert conv.updated_at >= old_updated

    def test_message_count_property(self):
        conv = Conversation()
        assert conv.message_count == 0
        conv.add_user_message("a")
        assert conv.message_count == 1


# ════════════════════════════════════════════════════════════
# entities.py — ToolCall 实体
# ════════════════════════════════════════════════════════════
class TestToolCall:
    """ToolCall 实体测试"""

    def test_defaults(self):
        tc = ToolCall()
        assert tc.status == "pending"
        assert tc.result is None
        assert tc.completed_at is None
        assert tc.arguments == {}
        assert tc.tool_name == ""
        assert len(tc.tool_id) == 8

    def test_complete(self):
        tc = ToolCall(tool_name="t")
        tc.complete({"ok": True})
        assert tc.status == "completed"
        assert tc.result == {"ok": True}
        assert tc.completed_at is not None

    def test_fail(self):
        tc = ToolCall(tool_name="t")
        tc.fail("boom")
        assert tc.status == "failed"
        assert tc.result == {"error": "boom"}
        assert tc.completed_at is not None


# ════════════════════════════════════════════════════════════
# entities.py — AudioChunk 实体
# ════════════════════════════════════════════════════════════
class TestAudioChunk:
    """AudioChunk 实体测试"""

    def test_defaults(self):
        chunk = AudioChunk(data=b"abc")
        assert chunk.format == "pcm"
        assert chunk.sample_rate == 16000
        assert chunk.channels == 1
        assert chunk.sample_width == 2
        assert chunk.is_final is False

    def test_duration_ms_calculation(self):
        # 16000 Hz, 16-bit, mono：每样本 2 字节
        # 32000 字节 / 2 = 16000 样本 / 16000 Hz = 1 秒 = 1000ms
        chunk = AudioChunk(data=b"\x00" * 32000, sample_rate=16000)
        assert chunk.duration_ms == pytest.approx(1000.0)

    def test_duration_ms_stereo(self):
        # 双通道：bytes_per_sample = 2*2 = 4
        # 64000 字节 / 4 = 16000 样本 / 16000 Hz = 1000ms
        chunk = AudioChunk(data=b"\x00" * 64000, sample_rate=16000, channels=2)
        assert chunk.duration_ms == pytest.approx(1000.0)

    def test_duration_ms_zero_sample_rate(self):
        # sample_rate=0 -> 返回 0.0（边界保护）
        chunk = AudioChunk(data=b"\x00" * 100, sample_rate=0)
        assert chunk.duration_ms == 0.0

    def test_duration_ms_zero_sample_width(self):
        chunk = AudioChunk(data=b"\x00" * 100, sample_width=0)
        assert chunk.duration_ms == 0.0

    def test_duration_ms_zero_channels(self):
        chunk = AudioChunk(data=b"\x00" * 100, channels=0)
        assert chunk.duration_ms == 0.0

    def test_duration_ms_empty_data(self):
        chunk = AudioChunk(data=b"", sample_rate=16000)
        assert chunk.duration_ms == 0.0


# ════════════════════════════════════════════════════════════
# entities.py — Session 实体（注意：SessionState 在 entities.py）
# ════════════════════════════════════════════════════════════
class TestSessionEntity:
    """Session 实体测试"""

    def test_default_creation(self):
        s = Session()
        assert s.state == SessionState.IDLE
        assert s.closed is False
        assert s.tts_playing is False
        assert s.device_id == ""
        assert len(s.session_id) == 8
        assert isinstance(s.conversation, Conversation)

    def test_post_init_generates_id_when_empty(self):
        # session_id 显式传入空字符串时，__post_init__ 重新生成
        s = Session(session_id="")
        assert s.session_id != ""
        assert len(s.session_id) == 8

    def test_post_init_keeps_provided_id(self):
        s = Session(session_id="custom123")
        assert s.session_id == "custom123"

    def test_duration(self):
        s = Session()
        time.sleep(0.01)
        assert s.duration > 0

    def test_is_active_true_by_default(self):
        s = Session()
        assert s.is_active is True

    def test_is_active_false_when_closed(self):
        s = Session()
        s.close()
        assert s.is_active is False

    def test_is_active_false_when_state_closed(self):
        s = Session()
        s.state = SessionState.CLOSED
        assert s.is_active is False

    def test_close(self):
        s = Session()
        s.close()
        assert s.closed is True
        assert s.state == SessionState.CLOSED

    def test_valid_transition_idle_to_asr(self):
        s = Session()
        s.transition_to(SessionState.ASR)
        assert s.state == SessionState.ASR

    def test_valid_transition_asr_to_llm(self):
        s = Session()
        s.transition_to(SessionState.ASR)
        s.transition_to(SessionState.LLM)
        assert s.state == SessionState.LLM

    def test_valid_transition_asr_to_idle(self):
        s = Session()
        s.transition_to(SessionState.ASR)
        s.transition_to(SessionState.IDLE)
        assert s.state == SessionState.IDLE

    def test_valid_transition_llm_to_tts(self):
        s = Session()
        s.transition_to(SessionState.ASR)
        s.transition_to(SessionState.LLM)
        s.transition_to(SessionState.TTS)
        assert s.state == SessionState.TTS

    def test_valid_transition_tts_to_idle(self):
        s = Session()
        s.transition_to(SessionState.ASR)
        s.transition_to(SessionState.LLM)
        s.transition_to(SessionState.TTS)
        s.transition_to(SessionState.IDLE)
        assert s.state == SessionState.IDLE

    def test_valid_transition_to_interrupted(self):
        s = Session()
        s.transition_to(SessionState.ASR)
        s.transition_to(SessionState.INTERRUPTED)
        assert s.state == SessionState.INTERRUPTED

    def test_invalid_transition_raises(self):
        # IDLE -> TTS 非法
        s = Session()
        with pytest.raises(ValueError, match="Invalid state transition"):
            s.transition_to(SessionState.TTS)

    def test_invalid_transition_from_closed(self):
        # CLOSED 不能再转换
        s = Session()
        s.close()
        with pytest.raises(ValueError):
            s.transition_to(SessionState.IDLE)

    def test_is_valid_transition_helper(self):
        s = Session()
        assert s._is_valid_transition(SessionState.ASR) is True
        assert s._is_valid_transition(SessionState.TTS) is False


# ════════════════════════════════════════════════════════════
# entities.py — SessionError（entities.py 内的简化版）
# ════════════════════════════════════════════════════════════
class TestSessionErrorEntity:
    """entities.py 内的 SessionError 异常测试"""

    def test_session_error_is_exception(self):
        assert issubclass(SessionError, Exception)

    def test_raise_session_error(self):
        with pytest.raises(SessionError):
            raise SessionError("some error")


# ════════════════════════════════════════════════════════════
# entities.py — Device 实体
# ════════════════════════════════════════════════════════════
class TestDevice:
    """Device 实体测试"""

    def test_defaults(self):
        d = Device(device_id="d1")
        assert d.device_id == "d1"
        assert d.device_key == ""
        assert d.is_online is False
        assert d.api_key == ""
        assert d.config == {}
        assert d.last_seen is None

    def test_is_authenticated_with_api_key(self):
        d = Device(device_id="d1", api_key="key")
        assert d.is_authenticated is True

    def test_is_authenticated_without_api_key(self):
        d = Device(device_id="d1")
        assert d.is_authenticated is False

    def test_update_last_seen(self):
        d = Device(device_id="d1")
        old = d.last_seen
        d.update_last_seen()
        assert d.is_online is True
        assert d.last_seen is not None
        assert d.last_seen != old

    def test_go_offline(self):
        d = Device(device_id="d1", is_online=True)
        d.go_offline()
        assert d.is_online is False


# ════════════════════════════════════════════════════════════
# entities.py — MemoryItem 实体
# ════════════════════════════════════════════════════════════
class TestMemoryItem:
    """MemoryItem 实体测试"""

    def test_defaults(self):
        m = MemoryItem()
        assert m.memory_id == ""
        assert m.device_id == ""
        assert m.content == ""
        assert m.tags == []
        assert m.keywords == []
        assert m.source == "manual"
        assert m.access_count == 0
        assert m.deleted is False

    def test_to_dict(self):
        m = MemoryItem(
            memory_id="mem-1",
            device_id="d1",
            content="hello",
            tags=["a", "b"],
            keywords=["k"],
            source="auto_llm",
        )
        d = m.to_dict()
        assert d["memory_id"] == "mem-1"
        assert d["device_id"] == "d1"
        assert d["content"] == "hello"
        assert d["tags"] == ["a", "b"]
        assert d["keywords"] == ["k"]
        assert d["source"] == "auto_llm"
        assert "created_at" in d
        assert "updated_at" in d
        assert d["access_count"] == 0
        assert d["deleted"] is False

    def test_from_dict_full(self):
        data = {
            "memory_id": "mem-2",
            "device_id": "d2",
            "content": "world",
            "tags": ["x"],
            "keywords": ["y"],
            "source": "manual",
            "created_at": 1000.0,
            "updated_at": 2000.0,
            "access_count": 5,
            "deleted": True,
        }
        m = MemoryItem.from_dict(data)
        assert m.memory_id == "mem-2"
        assert m.device_id == "d2"
        assert m.content == "world"
        assert m.tags == ["x"]
        assert m.keywords == ["y"]
        assert m.source == "manual"
        assert m.created_at == 1000.0
        assert m.updated_at == 2000.0
        assert m.access_count == 5
        assert m.deleted is True

    def test_from_dict_empty(self):
        # 空字典应使用默认值
        m = MemoryItem.from_dict({})
        assert m.memory_id == ""
        assert m.source == "manual"
        assert m.tags == []
        assert m.access_count == 0

    def test_from_dict_partial(self):
        m = MemoryItem.from_dict({"content": "only content"})
        assert m.content == "only content"
        assert m.source == "manual"

    def test_round_trip(self):
        # to_dict -> from_dict 应保持等价
        m1 = MemoryItem(memory_id="m", device_id="d", content="c", tags=["t"])
        m2 = MemoryItem.from_dict(m1.to_dict())
        assert m2.memory_id == "m"
        assert m2.device_id == "d"
        assert m2.content == "c"
        assert m2.tags == ["t"]

    def test_summary_labels_takes_first_three(self):
        # summary_labels 取 tags 前 3 个
        m = MemoryItem(tags=["a", "b", "c", "d", "e"])
        assert m.summary_labels == ["a", "b", "c"]

    def test_summary_labels_empty(self):
        m = MemoryItem()
        assert m.summary_labels == []

    def test_summary_labels_less_than_three(self):
        m = MemoryItem(tags=["a", "b"])
        assert m.summary_labels == ["a", "b"]


# ════════════════════════════════════════════════════════════
# exceptions.py — DomainError 基类
# ════════════════════════════════════════════════════════════
class TestDomainError:
    """DomainError 基类测试"""

    def test_default_code_is_class_name(self):
        # 不传 code 时，code 默认为类名
        err = DomainError("boom")
        assert err.message == "boom"
        assert err.code == "DomainError"
        assert err.details == {}

    def test_custom_code(self):
        err = DomainError("boom", code="CUSTOM", details={"k": "v"})
        assert err.code == "CUSTOM"
        assert err.details == {"k": "v"}

    def test_details_none_becomes_empty(self):
        err = DomainError("boom", details=None)
        assert err.details == {}

    def test_to_dict(self):
        err = DomainError("msg", code="C", details={"a": 1})
        d = err.to_dict()
        assert d == {"error": "C", "message": "msg", "details": {"a": 1}}

    def test_is_exception(self):
        assert issubclass(DomainError, Exception)
        with pytest.raises(DomainError):
            raise DomainError("x")

    def test_exception_message_attribute(self):
        # message 属性与 Exception 内置 args 保持一致
        err = DomainError("hello")
        assert str(err) == "hello"


class TestSessionExceptions:
    """Session 相关异常测试"""

    def test_session_not_found(self):
        err = SessionNotFoundError("sid-1")
        assert err.code == "SESSION_NOT_FOUND"
        assert "sid-1" in err.message
        assert err.details == {"session_id": "sid-1"}

    def test_session_not_found_default(self):
        err = SessionNotFoundError()
        assert err.details == {"session_id": ""}

    def test_session_already_exists(self):
        err = SessionAlreadyExistsError("dev-1")
        assert err.code == "SESSION_ALREADY_EXISTS"
        assert err.details == {"device_id": "dev-1"}

    def test_invalid_state_transition(self):
        err = InvalidStateTransitionError("idle", "tts")
        assert err.code == "INVALID_STATE_TRANSITION"
        assert err.details == {"current_state": "idle", "target_state": "tts"}

    def test_session_closed(self):
        err = SessionClosedError("sid")
        assert err.code == "SESSION_CLOSED"
        assert err.details == {"session_id": "sid"}

    def test_session_limit_exceeded_default(self):
        err = SessionLimitExceededError()
        assert err.code == "SESSION_LIMIT_EXCEEDED"
        assert err.details == {"max_sessions": 0}

    def test_session_limit_exceeded_custom(self):
        err = SessionLimitExceededError("too many", max_sessions=10)
        assert "too many" in err.message
        assert err.details == {"max_sessions": 10}


class TestDeviceExceptions:
    """Device 相关异常测试"""

    def test_device_not_found(self):
        err = DeviceNotFoundError("d1")
        assert err.code == "DEVICE_NOT_FOUND"
        assert err.details == {"device_id": "d1"}

    def test_device_authentication(self):
        err = DeviceAuthenticationError("secret-key-1234")
        assert err.code == "DEVICE_AUTH_FAILED"
        # device_key 被截断到前 8 字符
        assert err.details == {"device_key": "secret-k"}

    def test_device_authentication_empty(self):
        err = DeviceAuthenticationError("")
        assert err.details == {"device_key": ""}

    def test_device_offline(self):
        err = DeviceOfflineError("d1")
        assert err.code == "DEVICE_OFFLINE"
        assert err.details == {"device_id": "d1"}

    def test_device_limit_exceeded_default(self):
        err = DeviceLimitExceededError()
        assert err.code == "DEVICE_LIMIT_EXCEEDED"
        assert err.details == {"max_devices": 0}

    def test_device_limit_exceeded_custom(self):
        err = DeviceLimitExceededError("limit", max_devices=5)
        assert err.details == {"max_devices": 5}


class TestASRExceptions:
    """ASR 相关异常测试"""

    def test_asr_error(self):
        err = ASRError("fail", provider="tencent")
        assert err.code == "ASR_ERROR"
        assert err.details == {"provider": "tencent"}

    def test_asr_connection_error(self):
        err = ASRConnectionError(provider="volc", reason="refused")
        assert err.code == "ASR_CONNECTION_ERROR"
        assert "refused" in err.message
        assert err.details == {"provider": "volc"}

    def test_asr_timeout_error(self):
        err = ASRTimeoutError(provider="x", timeout=3.5)
        assert err.code == "ASR_TIMEOUT"
        assert err.details["timeout"] == 3.5
        assert err.details["provider"] == "x"

    def test_asr_no_speech_error(self):
        err = ASRNoSpeechError(provider="t")
        assert err.code == "ASR_NO_SPEECH"
        assert err.details == {"provider": "t"}

    def test_asr_subclasses_inherit(self):
        # 子类应是 ASRError 子类
        assert issubclass(ASRConnectionError, ASRError)
        assert issubclass(ASRTimeoutError, ASRError)
        assert issubclass(ASRNoSpeechError, ASRError)


class TestLLMExceptions:
    """LLM 相关异常测试"""

    def test_llm_error(self):
        err = LLMError("bad", provider="openai")
        assert err.code == "LLM_ERROR"
        assert err.details == {"provider": "openai"}

    def test_llm_connection_error(self):
        err = LLMConnectionError(provider="o", reason="reset")
        assert err.code == "LLM_CONNECTION_ERROR"
        assert err.details == {"provider": "o"}

    def test_llm_token_limit_error(self):
        err = LLMTokenLimitError(provider="o", limit=4096, actual=5000)
        assert err.code == "LLM_TOKEN_LIMIT_EXCEEDED"
        assert err.details["limit"] == 4096
        assert err.details["actual"] == 5000

    def test_llm_streaming_error(self):
        err = LLMStreamingError(provider="o", reason="broken")
        assert err.code == "LLM_STREAMING_ERROR"

    def test_llm_timeout_error(self):
        err = LLMTimeoutError(provider="o", timeout=30.0)
        assert err.code == "LLM_TIMEOUT"
        assert err.details["timeout"] == 30.0


class TestTTSExceptions:
    """TTS 相关异常测试"""

    def test_tts_error(self):
        err = TTSError("bad", provider="volc")
        assert err.code == "TTS_ERROR"

    def test_tts_connection_error(self):
        err = TTSConnectionError(provider="v", reason="x")
        assert err.code == "TTS_CONNECTION_ERROR"

    def test_tts_synthesis_error(self):
        err = TTSSynthesisError(provider="v", text="hello world", reason="x")
        assert err.code == "TTS_SYNTHESIS_ERROR"
        assert err.details["text_preview"] == "hello world"

    def test_tts_synthesis_error_long_text_truncated(self):
        long_text = "x" * 200
        err = TTSSynthesisError(provider="v", text=long_text, reason="x")
        assert len(err.details["text_preview"]) == 100

    def test_tts_timeout_error(self):
        err = TTSTimeoutError(provider="v", timeout=20.0)
        assert err.code == "TTS_TIMEOUT"
        assert err.details["timeout"] == 20.0


class TestOtherExceptions:
    """其余异常（Audio/WebSocket/Pipeline/Tool/Auth/Config）测试"""

    def test_audio_processing_error_with_message(self):
        err = AudioProcessingError(message="fail", operation="encode")
        assert err.code == "AUDIO_PROCESSING_ERROR"
        assert err.details == {"operation": "encode"}
        assert err.message == "fail"

    def test_audio_processing_error_default_message(self):
        # 不传 message 时使用 operation 拼接
        err = AudioProcessingError(operation="decode")
        assert "decode" in err.message

    def test_websocket_error_default(self):
        err = WebSocketError()
        assert err.code == "WS_ERROR"
        assert err.message == "WebSocket error"

    def test_websocket_error_custom(self):
        err = WebSocketError(message="closed", code="WS_CUSTOM")
        assert err.code == "WS_CUSTOM"

    def test_pipeline_error(self):
        err = PipelineError("fail", stage="llm")
        assert err.code == "PIPELINE_ERROR"
        assert err.details == {"stage": "llm"}

    def test_pipeline_interrupted_error(self):
        err = PipelineInterruptedError(stage="tts")
        assert err.code == "PIPELINE_INTERRUPTED"
        assert err.details == {"stage": "tts"}

    def test_pipeline_stage_error(self):
        err = PipelineStageError(stage="asr", reason="timeout")
        assert err.code == "PIPELINE_STAGE_ERROR"
        assert "asr" in err.message
        assert "timeout" in err.message

    def test_tool_error(self):
        err = ToolError("bad", tool_name="weather")
        assert err.code == "TOOL_ERROR"
        assert err.details == {"tool_name": "weather"}

    def test_tool_not_found_error(self):
        err = ToolNotFoundError("missing")
        assert err.code == "TOOL_NOT_FOUND"

    def test_tool_execution_error(self):
        err = ToolExecutionError(tool_name="t", reason="crash")
        assert err.code == "TOOL_EXECUTION_ERROR"

    def test_tool_timeout_error(self):
        err = ToolTimeoutError(tool_name="t", timeout=5.0)
        assert err.code == "TOOL_TIMEOUT"
        assert err.details["timeout"] == 5.0

    def test_authentication_error_default(self):
        err = AuthenticationError()
        assert err.code == "AUTHENTICATION_ERROR"
        assert err.message == "Authentication failed"

    def test_authentication_error_custom(self):
        err = AuthenticationError("invalid token")
        assert err.message == "invalid token"

    def test_rate_limit_exceeded_error(self):
        err = RateLimitExceededError(limit=100, window="hour")
        assert err.code == "RATE_LIMIT_EXCEEDED"
        assert err.details == {"limit": 100, "window": "hour"}

    def test_configuration_error(self):
        err = ConfigurationError("bad", key="K")
        assert err.code == "CONFIGURATION_ERROR"
        assert err.details == {"key": "K"}

    def test_missing_configuration_error(self):
        err = MissingConfigurationError(key="API_KEY")
        assert err.code == "MISSING_CONFIGURATION"
        assert "API_KEY" in err.message
        assert err.details == {"key": "API_KEY"}

    def test_missing_configuration_is_subclass(self):
        assert issubclass(MissingConfigurationError, ConfigurationError)


# ════════════════════════════════════════════════════════════
# value_objects.py — 枚举值对象
# ════════════════════════════════════════════════════════════
class TestValueObjectEnums:
    """值对象中的枚举测试"""

    def test_emotion_type_values(self):
        assert EmotionType.HAPPY.value == "happy"
        assert EmotionType.SAD.value == "sad"
        assert EmotionType.ANGRY.value == "angry"
        assert EmotionType.SURPRISED.value == "surprised"
        assert EmotionType.NEUTRAL.value == "neutral"
        assert EmotionType.NEGATIVE.value == "negative"

    def test_asr_provider_values(self):
        assert ASRProvider.TENCENT.value == "tencent"
        assert ASRProvider.VOLCENGINE.value == "volcengine"
        assert ASRProvider.ALIYUN.value == "aliyun"
        assert ASRProvider.XUNFEI.value == "xunfei"

    def test_llm_provider_values(self):
        assert LLMProvider.OPENAI.value == "openai"
        assert LLMProvider.OPENAI_COMPATIBLE.value == "openai_compatible"

    def test_tts_provider_values(self):
        assert TTSProvider.VOLCENGINE.value == "volcengine"
        assert TTSProvider.ALIYUN.value == "aliyun"
        assert TTSProvider.TENCENT.value == "tencent"

    def test_audio_format_values(self):
        assert AudioFormat.PCM.value == "pcm"
        assert AudioFormat.MP3.value == "mp3"
        assert AudioFormat.WAV.value == "wav"
        assert AudioFormat.OPUS.value == "opus"


# ════════════════════════════════════════════════════════════
# value_objects.py — AudioConfig
# ════════════════════════════════════════════════════════════
class TestAudioConfig:
    """AudioConfig 值对象测试"""

    def test_defaults(self):
        c = AudioConfig()
        assert c.sample_rate == 16000
        assert c.channels == 1
        assert c.sample_width == 2
        assert c.format == AudioFormat.PCM

    def test_bytes_per_frame(self):
        c = AudioConfig(sample_width=2, channels=2)
        assert c.bytes_per_frame == 4

    def test_bits_per_second(self):
        # 16000 * 2 * 1 * 8 = 256000
        c = AudioConfig(sample_rate=16000, sample_width=2, channels=1)
        assert c.bits_per_second == 256000

    def test_frozen(self):
        # frozen dataclass 不可变
        c = AudioConfig()
        with pytest.raises(Exception):
            c.sample_rate = 8000  # type: ignore[misc]


# ════════════════════════════════════════════════════════════
# value_objects.py — ASRConfig
# ════════════════════════════════════════════════════════════
class TestASRConfig:
    """ASRConfig 值对象测试"""

    def test_defaults(self):
        c = ASRConfig(provider=ASRProvider.TENCENT)
        assert c.provider == ASRProvider.TENCENT
        assert c.no_speech_timeout == 5
        assert c.silence_timeout == 3
        assert c.max_concurrency == 5
        assert c.enable_vad is True
        assert c.language == "zh-CN"

    def test_for_tencent(self):
        c = ASRConfig.for_tencent()
        assert c.provider == ASRProvider.TENCENT

    def test_for_volcengine(self):
        c = ASRConfig.for_volcengine()
        assert c.provider == ASRProvider.VOLCENGINE

    def test_for_tencent_with_kwargs(self):
        c = ASRConfig.for_tencent(language="en-US")
        assert c.language == "en-US"

    def test_frozen(self):
        c = ASRConfig(provider=ASRProvider.TENCENT)
        with pytest.raises(Exception):
            c.provider = ASRProvider.VOLCENGINE  # type: ignore[misc]


# ════════════════════════════════════════════════════════════
# value_objects.py — LLMConfig / TTSConfig
# ════════════════════════════════════════════════════════════
class TestLLMConfig:
    """LLMConfig 值对象测试"""

    def test_defaults(self):
        c = LLMConfig()
        assert c.provider == LLMProvider.OPENAI
        assert c.temperature == 0.7
        assert c.max_tokens == 2000
        assert c.stream is True
        assert c.memory_enabled is True
        assert c.memory_max_messages == 20

    def test_custom(self):
        c = LLMConfig(model="gpt-4", api_key="k", temperature=0.1)
        assert c.model == "gpt-4"
        assert c.api_key == "k"
        assert c.temperature == 0.1


class TestTTSConfig:
    """TTSConfig 值对象测试"""

    def test_defaults(self):
        c = TTSConfig()
        assert c.provider == TTSProvider.VOLCENGINE
        assert c.speed == 1.0
        assert c.volume == 1.0
        assert c.pitch == 1.0
        assert c.max_concurrency == 10
        assert c.audio_format == AudioFormat.MP3

    def test_custom(self):
        c = TTSConfig(voice_type="v1", speed=1.5)
        assert c.voice_type == "v1"
        assert c.speed == 1.5


# ════════════════════════════════════════════════════════════
# value_objects.py — PoolConfig / WebSocketConfig
# ════════════════════════════════════════════════════════════
class TestPoolConfig:
    """PoolConfig 值对象测试"""

    def test_defaults(self):
        c = PoolConfig()
        assert c.enabled is True
        assert c.max_size == 10
        assert c.min_size == 3
        assert c.heartbeat_interval == 30
        assert c.idle_timeout == 300
        assert c.connection_timeout == 15

    def test_disabled(self):
        c = PoolConfig(enabled=False)
        assert c.enabled is False


class TestWebSocketConfig:
    """WebSocketConfig 值对象测试"""

    def test_defaults(self):
        c = WebSocketConfig()
        assert c.max_size == 20 * 1024 * 1024
        assert c.ping_interval == 20
        assert c.ping_timeout == 20
        assert c.keepalive_interval == 3


# ════════════════════════════════════════════════════════════
# value_objects.py — MemoryQuery
# ════════════════════════════════════════════════════════════
class TestMemoryQuery:
    """MemoryQuery 值对象测试"""

    def test_defaults(self):
        q = MemoryQuery()
        assert q.device_id == ""
        assert q.summary_labels == ()
        assert q.keyword == ""
        assert q.limit == 8

    def test_custom(self):
        q = MemoryQuery(device_id="d1", summary_labels=("a", "b"), keyword="k", limit=5)
        assert q.device_id == "d1"
        assert q.summary_labels == ("a", "b")
        assert q.keyword == "k"
        assert q.limit == 5

    def test_frozen(self):
        q = MemoryQuery()
        with pytest.raises(Exception):
            q.limit = 10  # type: ignore[misc]
