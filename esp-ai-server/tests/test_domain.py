"""
Domain 层单元测试
- Session 实体
- Conversation 实体
- Message 实体
- Device 实体
- SessionState 枚举
"""
import pytest
from src.domain.entities import (
    Session,
    Conversation,
    Message,
    Device,
    SessionState,
    ToolCall,
    AudioChunk,
)
from src.domain.value_objects import EmotionType, ASRProvider, LLMProvider, TTSProvider, AudioFormat


class TestSessionState:
    """SessionState 枚举测试"""

    def test_session_state_values(self):
        assert SessionState.IDLE.value == "idle"
        assert SessionState.ASR.value == "asr"
        assert SessionState.LLM.value == "llm"
        assert SessionState.TTS.value == "tts"
        assert SessionState.INTERRUPTED.value == "interrupted"
        assert SessionState.CLOSED.value == "closed"

    def test_session_state_is_string(self):
        assert isinstance(SessionState.IDLE.value, str)


class TestMessage:
    """Message 实体测试"""

    def test_create_message(self):
        msg = Message(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.metadata == {}

    def test_message_with_metadata(self):
        msg = Message(role="assistant", content="Hi", metadata={"finish_reason": "stop"})
        assert msg.metadata["finish_reason"] == "stop"

    def test_message_default_role(self):
        msg = Message(role="user", content="test")
        assert msg.role == "user"


class TestConversation:
    """Conversation 实体测试"""

    def test_create_conversation(self):
        conv = Conversation()
        assert conv.messages == []
        assert conv.messages == []
        assert conv.max_messages == 20

    def test_add_message(self):
        conv = Conversation()
        msg = Message(role="user", content="Hello")
        conv.add_message(msg)
        assert len(conv.messages) == 1
        assert conv.messages[0].content == "Hello"

    def test_add_user_message(self):
        conv = Conversation()
        conv.add_user_message("Hello")
        assert len(conv.messages) == 1
        assert conv.messages[0].role == "user"

    def test_add_assistant_message(self):
        conv = Conversation()
        conv.add_assistant_message("Hi there")
        assert len(conv.messages) == 1
        assert conv.messages[0].role == "assistant"

    def test_trim_messages(self):
        conv = Conversation(max_messages=3)
        for i in range(5):
            conv.add_user_message(f"msg{i}")
        assert len(conv.messages) == 3
        assert conv.messages[0].content == "msg2"

    def test_clear_conversation(self):
        conv = Conversation()
        conv.add_user_message("Hello")
        conv.add_assistant_message("Hi")
        conv.clear()
        assert len(conv.messages) == 0

    def test_get_recent_messages(self):
        conv = Conversation()
        for i in range(10):
            conv.add_user_message(f"msg{i}")
        recent = conv.messages[-3:]
        assert len(recent) == 3
        assert recent[0].content == "msg7"


class TestSession:
    """Session 实体测试"""

    def test_create_session(self):
        session = Session(device_id="device1")
        assert session.device_id == "device1"
        assert session.state == SessionState.IDLE
        assert session.closed is False
        assert session.tts_playing is False

    def test_session_has_conversation(self):
        session = Session()
        assert isinstance(session.conversation, Conversation)

    def test_session_id_auto_generated(self):
        session = Session()
        assert len(session.session_id) == 8

    def test_session_duration(self):
        import time
        session = Session()
        time.sleep(0.01)
        assert session.duration > 0

    def test_is_active(self):
        session = Session()
        assert session.is_active is True
        session.close()
        assert session.is_active is False

    def test_valid_transitions(self):
        session = Session()
        assert session._is_valid_transition(SessionState.ASR) is True

    def test_invalid_transition(self):
        session = Session()
        assert session._is_valid_transition(SessionState.TTS) is False

    def test_transition_to_asr(self):
        session = Session()
        session.transition_to(SessionState.ASR)
        assert session.state == SessionState.ASR

    def test_transition_to_llm(self):
        session = Session()
        session.transition_to(SessionState.ASR)
        session.transition_to(SessionState.LLM)
        assert session.state == SessionState.LLM

    def test_invalid_transition_raises(self):
        session = Session()
        with pytest.raises(ValueError):
            session.transition_to(SessionState.TTS)

    def test_close_session(self):
        session = Session()
        session.close()
        assert session.closed is True
        assert session.state == SessionState.CLOSED


class TestToolCall:
    """ToolCall 实体测试"""

    def test_create_tool_call(self):
        tool_call = ToolCall(
            tool_name="get_weather",
            arguments={"city": "Beijing"}
        )
        assert tool_call.tool_name == "get_weather"
        assert tool_call.arguments["city"] == "Beijing"

    def test_tool_call_with_result(self):
        tool_call = ToolCall(tool_name="test", arguments={})
        tool_call.result = "success"
        assert tool_call.result == "success"

    def test_tool_call_error(self):
        tool_call = ToolCall(tool_name="test", arguments={})
        tool_call.fail("Network error")
        assert tool_call.status == "failed"


class TestAudioChunk:
    """AudioChunk 实体测试"""

    def test_create_audio_chunk(self):
        audio = b"\x00\x01\x02\x03"
        chunk = AudioChunk(data=audio, sample_rate=16000)
        assert chunk.data == audio
        assert chunk.sample_rate == 16000

    def test_audio_chunk_duration(self):
        import struct
        audio = b"\x00" * 32000  # 2 bytes per sample
        chunk = AudioChunk(data=audio, sample_rate=16000, channels=1)
        duration_ms = chunk.duration_ms
        assert duration_ms == 1000.0

    def test_audio_chunk_duration_zero(self):
        chunk = AudioChunk(data=b"", sample_rate=16000)
        assert chunk.duration_ms == 0.0


class TestDevice:
    """Device 实体测试"""

    def test_create_device(self):
        device = Device(device_id="device1", device_key="key123")
        assert device.device_id == "device1"
        assert device.device_key == "key123"
        assert device.is_online is False

    def test_device_authenticated(self):
        device = Device(device_id="device1", api_key="secret")
        assert device.is_authenticated is True

    def test_device_not_authenticated(self):
        device = Device(device_id="device1")
        assert device.is_authenticated is False

    def test_device_go_online(self):
        device = Device(device_id="device1")
        device.update_last_seen()
        assert device.is_online is True

    def test_device_go_offline(self):
        device = Device(device_id="device1", is_online=True)
        device.go_offline()
        assert device.is_online is False


class TestValueObjects:
    """值对象测试"""

    def test_emotion_type(self):
        assert EmotionType.HAPPY.name == "HAPPY"
        assert EmotionType.SAD.name == "SAD"
        assert EmotionType.ANGRY.name == "ANGRY"

    def test_asr_provider(self):
        assert ASRProvider.VOLCENGINE.value == "volcengine"
        assert ASRProvider.TENCENT.value == "tencent"

    def test_llm_provider(self):
        assert LLMProvider.OPENAI.value == "openai"

    def test_tts_provider(self):
        assert TTSProvider.VOLCENGINE.value == "volcengine"

    def test_audio_format(self):
        assert AudioFormat.PCM.value == "pcm"
        assert AudioFormat.MP3.value == "mp3"
