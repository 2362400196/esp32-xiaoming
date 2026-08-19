"""
Phase 1 核心工具类单元测试
- VoiceGenerator
- ConversationMemory
- BackpressureQueues
"""
import asyncio
import pytest

from src.use_cases.voice_generator import VoiceGenerator
from src.use_cases.auxiliary_services import ConversationMemory
from src.use_cases.queues import (
    BackpressureQueue,
    TextQueue,
    AudioQueue,
    SendQueue,
    BackpressureQueues,
)


# ==================== VoiceGenerator 测试 ====================


class TestVoiceGenerator:
    def setup_method(self):
        self.gen = VoiceGenerator()

    def test_make_tts_frame_normal(self):
        audio = b"\x00\x01\x02\x03"
        frame = self.gen.make_tts_frame("0001", audio)
        assert frame == b"0001" + b"00" + audio

    def test_make_tts_frame_with_status(self):
        audio = b"\xff\xfe"
        frame = self.gen.make_tts_frame("abcd", audio, status="01")
        assert frame == b"abcd" + b"01" + audio

    def test_make_end_frame(self):
        frame = self.gen.make_end_frame("0001")
        assert frame == b"0001" + b"03"

    def test_make_end_frame_different_session(self):
        frame = self.gen.make_end_frame("zz99")
        assert frame == b"zz99" + b"03"

    def test_make_tts_frame_empty_audio(self):
        frame = self.gen.make_tts_frame("0001", b"")
        assert frame == b"0001" + b"00"

    def test_make_tts_frame_large_audio(self):
        audio = b"\x00" * 10000
        frame = self.gen.make_tts_frame("0001", audio)
        assert frame[:4] == b"0001"
        assert frame[4:6] == b"00"
        assert len(frame) == 10006


# ==================== ConversationMemory 测试 ====================


class TestConversationMemory:
    def test_add_message(self):
        mem = ConversationMemory()
        mem.add_message("user", "hello")
        assert mem.message_count == 1
        assert not mem.is_empty

    def test_add_user_and_assistant_messages(self):
        mem = ConversationMemory()
        mem.add_user_message("hi")
        mem.add_assistant_message("hello")
        assert mem.message_count == 2

    def test_add_empty_message_ignored(self):
        mem = ConversationMemory()
        mem.add_message("user", "")
        mem.add_message("user", "   ")
        assert mem.message_count == 0
        assert mem.is_empty

    def test_message_truncation(self):
        mem = ConversationMemory()
        long_content = "a" * 3000
        mem.add_message("user", long_content)
        assert mem.message_count == 1
        msg = mem._messages[0]
        assert len(msg["content"]) == ConversationMemory.MAX_CHARS_PER_MESSAGE

    def test_build_messages(self):
        mem = ConversationMemory()
        mem.add_user_message("hi")
        mem.add_assistant_message("hello")
        messages = mem.build_messages("You are helpful.", "how are you?")
        assert len(messages) == 4
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are helpful."
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "hi"
        assert messages[2]["role"] == "assistant"
        assert messages[2]["content"] == "hello"
        assert messages[3]["role"] == "user"
        assert messages[3]["content"] == "how are you?"

    def test_build_messages_truncates_long_current(self):
        mem = ConversationMemory()
        long_msg = "x" * 3000
        messages = mem.build_messages("system", long_msg)
        assert len(messages[-1]["content"]) == ConversationMemory.MAX_CHARS_PER_MESSAGE

    def test_trim_by_max_messages(self):
        mem = ConversationMemory(max_messages=3)
        for i in range(5):
            mem.add_message("user", f"msg{i}")
        assert mem.message_count <= 3

    def test_trim_by_token_estimate(self):
        mem = ConversationMemory(max_messages=100)
        mem.MAX_TOKENS_ESTIMATE = 10
        mem.add_message("user", "a" * 100)
        mem.add_message("assistant", "b" * 100)
        total_tokens = sum(mem._estimate_tokens(m["content"]) for m in mem._messages)
        assert total_tokens <= mem.MAX_TOKENS_ESTIMATE

    def test_clear(self):
        mem = ConversationMemory()
        mem.add_user_message("hi")
        mem.add_assistant_message("hello")
        mem.clear()
        assert mem.is_empty
        assert mem.message_count == 0

    def test_estimate_tokens(self):
        mem = ConversationMemory()
        assert mem._estimate_tokens("") == 1
        assert mem._estimate_tokens("a") == 1
        assert mem._estimate_tokens("ab") == 1
        assert mem._estimate_tokens("abc") == 1
        assert mem._estimate_tokens("abcd") == 2
        assert mem._estimate_tokens("abcde") == 2


# ==================== BackpressureQueue 测试 ====================


class TestBackpressureQueue:
    @pytest.mark.asyncio
    async def test_put_and_get(self):
        q = BackpressureQueue(maxsize=10, name="test", on_full="block")
        await q.put("item1")
        result = await q.get()
        assert result == "item1"

    def test_put_nowait_and_get_nowait(self):
        q = BackpressureQueue(maxsize=10, name="test", on_full="block")
        q.put_nowait("item1")
        result = q.get_nowait()
        assert result == "item1"

    def test_empty_and_full(self):
        q = BackpressureQueue(maxsize=2, name="test", on_full="block")
        assert q.empty()
        q.put_nowait("a")
        q.put_nowait("b")
        assert q.full()
        assert q.qsize() == 2

    def test_clear(self):
        q = BackpressureQueue(maxsize=10, name="test", on_full="block")
        for i in range(5):
            q.put_nowait(f"item{i}")
        cleared = q.clear()
        assert cleared == 5
        assert q.empty()

    @pytest.mark.asyncio
    async def test_drop_oldest_on_full(self):
        q = BackpressureQueue(maxsize=2, name="test", on_full="drop_oldest")
        await q.put("first")
        await q.put("second")
        await q.put("third")
        assert q.qsize() == 2
        first = await q.get()
        assert first == "second"

    def test_drop_newest_on_full(self):
        q = BackpressureQueue(maxsize=2, name="test", on_full="drop_newest")
        q.put_nowait("first")
        q.put_nowait("second")
        q.put_nowait("third")
        assert q.qsize() == 2
        assert q.dropped == 1

    def test_dropped_counter(self):
        q = BackpressureQueue(maxsize=2, name="test", on_full="drop_newest")
        q.put_nowait("a")
        q.put_nowait("b")
        q.put_nowait("c")
        q.put_nowait("d")
        assert q.dropped == 2

    def test_reset_stats(self):
        q = BackpressureQueue(maxsize=2, name="test", on_full="drop_newest")
        q.put_nowait("a")
        q.put_nowait("b")
        q.put_nowait("c")
        q.reset_stats()
        assert q.dropped == 0


class TestTextQueue:
    def test_is_drop_oldest(self):
        q = TextQueue(maxsize=5)
        assert q._on_full == "drop_oldest"
        assert q._name == "text_queue"


class TestAudioQueue:
    def test_is_block(self):
        q = AudioQueue(maxsize=10)
        assert q._on_full == "block"
        assert q._name == "audio_queue"


class TestSendQueue:
    def test_is_block(self):
        q = SendQueue(maxsize=50)
        assert q._on_full == "block"
        assert q._name == "send_queue"


class TestBackpressureQueues:
    def test_clear_all(self):
        qs = BackpressureQueues()
        qs.text.put_nowait("a")
        qs.audio.put_nowait("b")
        qs.send.put_nowait("c")
        qs.clear_all()
        assert qs.text.empty()
        assert qs.audio.empty()
        assert qs.send.empty()

    def test_put_sentinel(self):
        qs = BackpressureQueues()
        qs.put_sentinel()
        text_item = qs.text.get_nowait()
        assert text_item == (-1, None)
        audio_item = qs.audio.get_nowait()
        assert audio_item == (-1, None, None)
