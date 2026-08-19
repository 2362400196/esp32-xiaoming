"""
auxiliary_services.py 单元测试

覆盖类（通过 auxiliary_services 重新导出）：
- AudioProcessor（来自 audio_processor.py）：音频编解码、分块合并、格式验证、时长计算
- ConversationMemory（来自 memory.py）：对话消息管理、build_messages、token 裁剪

AudioProcessor 是纯音频处理工具类（无 channel/网络依赖）：
- decode_base64_audio / encode_base64_audio
- split_audio / merge_audio_chunks
- validate_format / calculate_duration
- reset / process_audio_chunk

ConversationMemory 管理 session 级消息历史：
- add_message / add_user_message / add_assistant_message
- build_messages(system_prompt, current_user_message)
- clear / _trim / _estimate_tokens
- messages / message_count 属性
"""
import base64
import time
from unittest.mock import MagicMock

import pytest

from src.use_cases.auxiliary_services import AudioProcessor, ConversationMemory


# ============================================================
# AudioProcessor
# ============================================================


class TestAudioProcessorInit:
    """AudioProcessor 初始化"""

    def test_init_default(self):
        ap = AudioProcessor()
        assert ap.config == {}
        assert ap.sample_rate == 16000
        assert ap.channels == 1
        assert ap.bits_per_sample == 16

    def test_init_with_config(self):
        config = {"sample_rate": 44100, "channels": 2, "bits_per_sample": 24}
        ap = AudioProcessor(config=config)
        assert ap.sample_rate == 44100
        assert ap.channels == 2
        assert ap.bits_per_sample == 24

    def test_init_with_partial_config(self):
        config = {"sample_rate": 8000}
        ap = AudioProcessor(config=config)
        assert ap.sample_rate == 8000
        assert ap.channels == 1  # 默认值
        assert ap.bits_per_sample == 16  # 默认值

    def test_supported_formats(self):
        assert AudioProcessor.SUPPORTED_FORMATS == {"pcm", "mp3", "wav", "ogg", "opus"}


class TestDecodeBase64Audio:
    """decode_base64_audio：base64 解码"""

    def test_decode_valid(self):
        original = b"hello audio"
        encoded = base64.b64encode(original).decode("utf-8")
        ap = AudioProcessor()
        result = ap.decode_base64_audio(encoded)
        assert result == original

    def test_decode_empty(self):
        ap = AudioProcessor()
        result = ap.decode_base64_audio("")
        assert result == b""

    def test_decode_invalid_raises(self):
        ap = AudioProcessor()
        with pytest.raises(Exception):  # AudioProcessingError
            ap.decode_base64_audio("!!!invalid base64!!!")

    def test_decode_with_format_param(self):
        original = b"audio data"
        encoded = base64.b64encode(original).decode("utf-8")
        ap = AudioProcessor()
        # format 参数不影响解码（仅 base64 解码）
        for fmt in ["pcm", "mp3", "wav"]:
            assert ap.decode_base64_audio(encoded, format=fmt) == original


class TestEncodeBase64Audio:
    """encode_base64_audio：base64 编码"""

    def test_encode_valid(self):
        data = b"hello audio"
        ap = AudioProcessor()
        result = ap.encode_base64_audio(data)
        assert isinstance(result, str)
        assert base64.b64decode(result) == data

    def test_encode_empty(self):
        ap = AudioProcessor()
        result = ap.encode_base64_audio(b"")
        assert result == ""

    def test_encode_decode_roundtrip(self):
        original = b"\x00\x01\x02\x03\xff\xfe"
        ap = AudioProcessor()
        encoded = ap.encode_base64_audio(original)
        decoded = ap.decode_base64_audio(encoded)
        assert decoded == original


class TestSplitAudio:
    """split_audio：音频分块"""

    def test_split_default_chunk_size(self):
        ap = AudioProcessor()
        data = b"\x00" * 12800  # 12800 bytes / 6400 = 2 chunks
        chunks = ap.split_audio(data)
        assert len(chunks) == 2
        assert all(len(c) == 6400 for c in chunks)

    def test_split_custom_chunk_size(self):
        ap = AudioProcessor()
        data = b"\x00" * 100
        chunks = ap.split_audio(data, chunk_size=30)
        assert len(chunks) == 4  # 30 + 30 + 30 + 10
        assert len(chunks[0]) == 30
        assert len(chunks[-1]) == 10

    def test_split_empty_data(self):
        ap = AudioProcessor()
        chunks = ap.split_audio(b"")
        assert chunks == []

    def test_split_exact_multiple(self):
        ap = AudioProcessor()
        data = b"\x00" * 100
        chunks = ap.split_audio(data, chunk_size=50)
        assert len(chunks) == 2
        assert all(len(c) == 50 for c in chunks)

    def test_split_single_chunk(self):
        ap = AudioProcessor()
        data = b"\x00" * 10
        chunks = ap.split_audio(data, chunk_size=100)
        assert len(chunks) == 1
        assert len(chunks[0]) == 10


class TestMergeAudioChunks:
    """merge_audio_chunks：音频块合并"""

    def test_merge_multiple(self):
        ap = AudioProcessor()
        chunks = [b"abc", b"def", b"ghi"]
        result = ap.merge_audio_chunks(chunks)
        assert result == b"abcdefghi"

    def test_merge_empty_list(self):
        ap = AudioProcessor()
        result = ap.merge_audio_chunks([])
        assert result == b""

    def test_merge_single_chunk(self):
        ap = AudioProcessor()
        result = ap.merge_audio_chunks([b"only"])
        assert result == b"only"

    def test_split_merge_roundtrip(self):
        ap = AudioProcessor()
        original = b"\x00\x01\x02\x03" * 1000
        chunks = ap.split_audio(original, chunk_size=500)
        merged = ap.merge_audio_chunks(chunks)
        assert merged == original


class TestValidateFormat:
    """validate_format：格式验证"""

    def test_valid_formats(self):
        ap = AudioProcessor()
        for fmt in ["pcm", "mp3", "wav", "ogg", "opus"]:
            assert ap.validate_format(fmt) is True

    def test_case_insensitive(self):
        ap = AudioProcessor()
        assert ap.validate_format("PCM") is True
        assert ap.validate_format("MP3") is True
        assert ap.validate_format("Wav") is True

    def test_invalid_format(self):
        ap = AudioProcessor()
        assert ap.validate_format("flac") is False
        assert ap.validate_format("aac") is False
        assert ap.validate_format("") is False

    def test_unknown_format(self):
        ap = AudioProcessor()
        assert ap.validate_format("unknown") is False


class TestCalculateDuration:
    """calculate_duration：计算音频时长"""

    def test_duration_basic(self):
        # 16-bit, mono, 16000 Hz
        # 32000 bytes = 16000 samples = 1 second
        ap = AudioProcessor()
        data = b"\x00" * 32000
        duration = ap.calculate_duration(data)
        assert duration == pytest.approx(1.0)

    def test_duration_stereo(self):
        config = {"channels": 2, "sample_rate": 16000, "bits_per_sample": 16}
        ap = AudioProcessor(config=config)
        # 16-bit stereo: 4 bytes per sample frame
        # 64000 bytes = 16000 sample frames = 1 second
        data = b"\x00" * 64000
        duration = ap.calculate_duration(data)
        assert duration == pytest.approx(1.0)

    def test_duration_empty(self):
        ap = AudioProcessor()
        assert ap.calculate_duration(b"") == 0.0

    def test_duration_24bit(self):
        config = {"bits_per_sample": 24, "sample_rate": 48000, "channels": 1}
        ap = AudioProcessor(config=config)
        # 24-bit: 3 bytes per sample
        # 144000 bytes = 48000 samples = 1 second
        data = b"\x00" * 144000
        duration = ap.calculate_duration(data)
        assert duration == pytest.approx(1.0)


class TestResetAndProcess:
    """reset / process_audio_chunk：空操作方法"""

    def test_reset_does_not_raise(self):
        ap = AudioProcessor()
        ap.reset()  # 不应抛异常

    def test_process_audio_chunk_does_not_raise(self):
        ap = AudioProcessor()
        ap.process_audio_chunk(b"\x00\x01")  # 不应抛异常


# ============================================================
# ConversationMemory
# ============================================================


class TestConversationMemoryInit:
    """ConversationMemory 初始化"""

    def test_init_default(self):
        mem = ConversationMemory()
        assert mem.messages == []
        assert mem.max_messages == 20
        assert mem._device_id == ""
        assert mem.message_count == 0

    def test_init_with_device_id(self):
        mem = ConversationMemory(device_id="d1")
        assert mem._device_id == "d1"

    def test_init_with_custom_max_messages(self):
        mem = ConversationMemory(max_messages=50)
        assert mem.max_messages == 50

    async def test_init_with_repository_loads_messages(self):
        repo = MagicMock()
        repo.load.return_value = [{"role": "user", "content": "loaded"}]
        mem = ConversationMemory(device_id="d1", repository=repo)
        # 性能优化：现在使用异步延迟加载，需要调用 ensure_loaded()
        assert len(mem.messages) == 0  # 初始状态为空
        await mem.ensure_loaded()
        assert len(mem.messages) == 1
        repo.load.assert_called_once_with("d1")

    def test_constants(self):
        assert ConversationMemory.MAX_CHARS_PER_MESSAGE == 2000
        assert ConversationMemory.MAX_TOKENS_ESTIMATE == 2000


class TestAddMessages:
    """add_message / add_user_message / add_assistant_message"""

    def test_add_user_message(self):
        mem = ConversationMemory()
        mem.add_user_message("hello")
        assert len(mem.messages) == 1
        assert mem.messages[0]["role"] == "user"
        assert mem.messages[0]["content"] == "hello"

    def test_add_assistant_message(self):
        mem = ConversationMemory()
        mem.add_assistant_message("hi there")
        assert mem.messages[0]["role"] == "assistant"
        assert mem.messages[0]["content"] == "hi there"

    def test_add_message_includes_timestamp(self):
        mem = ConversationMemory()
        mem.add_user_message("hello")
        msg = mem.messages[0]
        assert "timestamp" in msg
        assert "datetime" in msg
        assert isinstance(msg["timestamp"], float)

    def test_add_multiple_messages(self):
        mem = ConversationMemory()
        mem.add_user_message("msg1")
        mem.add_assistant_message("reply1")
        mem.add_user_message("msg2")
        assert len(mem.messages) == 3

    def test_truncates_long_content(self):
        mem = ConversationMemory()
        long_text = "x" * (ConversationMemory.MAX_CHARS_PER_MESSAGE + 100)
        mem.add_user_message(long_text)
        assert len(mem.messages[0]["content"]) == ConversationMemory.MAX_CHARS_PER_MESSAGE

    def test_skips_empty_content(self):
        mem = ConversationMemory()
        mem.add_user_message("")
        assert len(mem.messages) == 0

    def test_skips_whitespace_only(self):
        mem = ConversationMemory()
        mem.add_user_message("   ")
        assert len(mem.messages) == 0

    def test_message_count_property(self):
        mem = ConversationMemory()
        mem.add_user_message("a")
        mem.add_user_message("b")
        assert mem.message_count == 2


class TestBuildMessages:
    """build_messages：构建发给 LLM 的消息列表"""

    def test_empty_history(self):
        mem = ConversationMemory()
        msgs = mem.build_messages("system prompt", "user msg")
        # system + current user = 2
        assert len(msgs) == 2
        assert msgs[0] == {"role": "system", "content": "system prompt"}
        assert msgs[-1] == {"role": "user", "content": "user msg"}

    def test_with_history(self):
        mem = ConversationMemory()
        mem.add_user_message("old msg")
        mem.add_assistant_message("old reply")
        msgs = mem.build_messages("sys", "new msg")
        # system + 2 history + current = 4
        assert len(msgs) == 4
        assert msgs[0]["role"] == "system"
        assert msgs[1]["content"] == "old msg"
        assert msgs[2]["content"] == "old reply"
        assert msgs[3]["content"] == "new msg"

    def test_empty_system_prompt(self):
        mem = ConversationMemory()
        mem.add_user_message("old")
        msgs = mem.build_messages("", "new")
        # 即使 system_prompt 为空，仍添加 system 消息
        assert msgs[0] == {"role": "system", "content": ""}
        assert msgs[-1]["content"] == "new"

    def test_current_message_truncated(self):
        mem = ConversationMemory()
        long_msg = "y" * (ConversationMemory.MAX_CHARS_PER_MESSAGE + 100)
        msgs = mem.build_messages("sys", long_msg)
        assert len(msgs[-1]["content"]) == ConversationMemory.MAX_CHARS_PER_MESSAGE

    def test_build_messages_does_not_modify_history(self):
        mem = ConversationMemory()
        mem.add_user_message("old")
        mem.build_messages("sys", "new")
        # 历史不应被修改
        assert len(mem.messages) == 1


class TestConversationMemoryClear:
    """clear：清空对话记忆"""

    def test_clear_empties_messages(self):
        mem = ConversationMemory()
        mem.add_user_message("msg1")
        mem.add_user_message("msg2")
        mem.clear()
        assert mem.messages == []
        assert mem.message_count == 0

    def test_clear_with_repository(self):
        repo = MagicMock()
        repo.load.return_value = [{"role": "user", "content": "x"}]
        mem = ConversationMemory(device_id="d1", repository=repo)
        mem.clear()
        repo.delete.assert_called_once_with("d1")

    def test_clear_without_repository(self):
        mem = ConversationMemory()
        mem.add_user_message("msg")
        mem.clear()
        assert mem.messages == []


class TestConversationMemoryTrim:
    """_trim / _estimate_tokens：消息裁剪"""

    def test_estimate_tokens_basic(self):
        mem = ConversationMemory()
        assert mem._estimate_tokens("ab") == 1  # max(1, 2//2)
        assert mem._estimate_tokens("abcd") == 2
        assert mem._estimate_tokens("") == 1  # max(1, 0)
        assert mem._estimate_tokens("a") == 1  # max(1, 0)

    def test_trim_by_max_messages(self):
        mem = ConversationMemory(max_messages=3)
        for i in range(5):
            mem.add_user_message(f"msg{i}")
        assert len(mem.messages) <= 3

    def test_trim_by_token_limit(self):
        mem = ConversationMemory(max_messages=100)
        # 每条消息 ~1000 chars = 500 tokens，4 条就超 2000
        big = "z" * 1000
        for _ in range(5):
            mem.add_user_message(big)
        total_tokens = sum(mem._estimate_tokens(m["content"]) for m in mem.messages)
        assert total_tokens <= ConversationMemory.MAX_TOKENS_ESTIMATE

    def test_trim_preserves_recent_messages(self):
        mem = ConversationMemory(max_messages=3)
        for i in range(5):
            mem.add_user_message(f"msg{i}")
        # 裁剪后应保留最后 3 条
        contents = [m["content"] for m in mem.messages]
        assert "msg4" in contents
        assert "msg0" not in contents


class TestConversationMemoryWithRepository:
    """ConversationMemory 与持久化仓储集成"""

    async def test_loads_from_repository_on_init(self):
        repo = MagicMock()
        repo.load.return_value = [
            {"role": "user", "content": "loaded msg"},
            {"role": "assistant", "content": "loaded reply"},
        ]
        mem = ConversationMemory(device_id="d1", repository=repo)
        # 性能优化：现在使用异步延迟加载
        await mem.ensure_loaded()
        assert len(mem.messages) == 2
        repo.load.assert_called_once_with("d1")

    def test_saves_to_repository_on_add_sync(self):
        """同步上下文中 add_message 应直接调用 repository.save"""
        repo = MagicMock()
        repo.load.return_value = []
        mem = ConversationMemory(device_id="d1", repository=repo)
        mem.add_user_message("new msg")
        # save 的参数是 (device_id, messages)
        repo.save.assert_called_once()
        saved_device_id = repo.save.call_args.args[0]
        saved_msgs = repo.save.call_args.args[1]
        assert saved_device_id == "d1"
        assert len(saved_msgs) == 1
        assert saved_msgs[0]["content"] == "new msg"

    def test_no_repository_no_save(self):
        mem = ConversationMemory()
        mem.add_user_message("msg")
        # 无 repository 不应抛异常

    def test_no_device_id_no_save(self):
        repo = MagicMock()
        mem = ConversationMemory(repository=repo)  # 无 device_id
        mem.add_user_message("msg")
        repo.save.assert_not_called()


class TestConversationMemoryEdgeCases:
    """ConversationMemory 边界条件"""

    def test_max_messages_one(self):
        mem = ConversationMemory(max_messages=1)
        mem.add_user_message("msg1")
        mem.add_user_message("msg2")
        assert len(mem.messages) == 1
        assert mem.messages[0]["content"] == "msg2"

    def test_very_long_single_message(self):
        mem = ConversationMemory()
        very_long = "z" * 5000
        mem.add_user_message(very_long)
        assert len(mem.messages[0]["content"]) == ConversationMemory.MAX_CHARS_PER_MESSAGE

    def test_unicode_content(self):
        mem = ConversationMemory()
        mem.add_user_message("你好世界")
        assert mem.messages[0]["content"] == "你好世界"

    def test_build_messages_with_empty_current(self):
        mem = ConversationMemory()
        mem.add_user_message("history")
        msgs = mem.build_messages("sys", "")
        assert msgs[-1]["content"] == ""

    def test_add_message_directly(self):
        mem = ConversationMemory()
        mem.add_message("system", "sys prompt")
        assert mem.messages[0]["role"] == "system"
        assert mem.messages[0]["content"] == "sys prompt"
