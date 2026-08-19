"""
voice_generator.py 单元测试

VoiceGenerator 负责生成 TTS 音频帧：
- make_tts_frame(session_id, audio_data, status)：会话ID + 状态 + 音频
- make_end_frame(session_id)：结束帧（状态 03）

帧结构与 esp-ai audio_sender.js 一致：
  会话ID(4字节 utf-8) + 会话状态(2字节 utf-8) + 原始音频数据

注：源文件 VoiceGenerator 只提供 make_tts_frame / make_end_frame 两个方法，
没有 make_start_frame（旧 API 已移除），本测试只覆盖实际存在的方法。
"""
import pytest

from src.use_cases.voice_generator import VoiceGenerator


class TestVoiceGeneratorInit:
    """VoiceGenerator 初始化与内部缓存"""

    def test_init_creates_empty_prefix_cache(self):
        gen = VoiceGenerator()
        assert gen._prefix_cache == {}

    def test_init_no_args(self):
        # 无参数构造应成功
        gen = VoiceGenerator()
        assert gen is not None


class TestMakeTtsFrame:
    """make_tts_frame：构造 TTS 数据帧"""

    def setup_method(self):
        self.gen = VoiceGenerator()

    def test_default_status_00(self):
        # 默认 status="00"
        audio = b"\x00\x01\x02\x03"
        frame = self.gen.make_tts_frame("0001", audio)
        assert frame == b"0001" + b"00" + audio

    def test_custom_status(self):
        audio = b"\xff\xfe"
        frame = self.gen.make_tts_frame("abcd", audio, status="01")
        assert frame == b"abcd" + b"01" + audio

    def test_status_03(self):
        audio = b"\xaa\xbb"
        frame = self.gen.make_tts_frame("0001", audio, status="03")
        assert frame == b"0001" + b"03" + audio

    def test_empty_audio(self):
        frame = self.gen.make_tts_frame("0001", b"")
        assert frame == b"0001" + b"00"

    def test_large_audio(self):
        audio = b"\x00" * 10000
        frame = self.gen.make_tts_frame("0001", audio)
        assert frame[:4] == b"0001"
        assert frame[4:6] == b"00"
        assert len(frame) == 10006

    def test_prefix_cache_populated_on_first_call(self):
        self.gen.make_tts_frame("0001", b"x", status="00")
        assert ("0001", "00") in self.gen._prefix_cache

    def test_prefix_cache_reused_on_subsequent_calls(self):
        # 第一次调用填充缓存
        frame1 = self.gen.make_tts_frame("0001", b"x", status="00")
        cached_prefix = self.gen._prefix_cache[("0001", "00")]
        # 第二次调用应复用缓存的前缀
        frame2 = self.gen.make_tts_frame("0001", b"y", status="00")
        assert self.gen._prefix_cache[("0001", "00")] is cached_prefix
        assert frame1 == b"0001" + b"00" + b"x"
        assert frame2 == b"0001" + b"00" + b"y"

    def test_different_session_ids_produce_different_prefixes(self):
        self.gen.make_tts_frame("0001", b"x")
        self.gen.make_tts_frame("0002", b"x")
        assert ("0001", "00") in self.gen._prefix_cache
        assert ("0002", "00") in self.gen._prefix_cache

    def test_different_statuses_produce_different_prefixes(self):
        self.gen.make_tts_frame("0001", b"x", status="00")
        self.gen.make_tts_frame("0001", b"x", status="03")
        assert ("0001", "00") in self.gen._prefix_cache
        assert ("0001", "03") in self.gen._prefix_cache

    def test_frame_structure_length(self):
        # 4字节session + 2字节status + N字节audio
        audio = b"\x01" * 100
        frame = self.gen.make_tts_frame("sid1", audio)
        assert len(frame) == 4 + 2 + 100

    def test_frame_concatenation_order(self):
        audio = b"DATA"
        frame = self.gen.make_tts_frame("s_id", audio, status="02")
        # 验证拼接顺序：session_id + status + audio
        assert frame == b"s_id" + b"02" + b"DATA"

    def test_unicode_session_id(self):
        # session_id 用 utf-8 编码
        audio = b"x"
        frame = self.gen.make_tts_frame("0001", audio)
        assert frame.startswith(b"0001")


class TestMakeEndFrame:
    """make_end_frame：构造结束帧（状态 03）"""

    def setup_method(self):
        self.gen = VoiceGenerator()

    def test_basic_end_frame(self):
        frame = self.gen.make_end_frame("0001")
        assert frame == b"0001" + b"03"

    def test_different_session_id(self):
        frame = self.gen.make_end_frame("zz99")
        assert frame == b"zz99" + b"03"

    def test_end_frame_length(self):
        frame = self.gen.make_end_frame("abcd")
        # 4字节session + 2字节status
        assert len(frame) == 6

    def test_end_frame_no_audio(self):
        # 结束帧不含音频数据
        frame = self.gen.make_end_frame("0001")
        assert frame == b"000103"

    def test_end_frame_starts_with_session(self):
        frame = self.gen.make_end_frame("sess")
        assert frame.startswith(b"sess")

    def test_end_frame_ends_with_03(self):
        frame = self.gen.make_end_frame("0001")
        assert frame.endswith(b"03")


class TestVoiceGeneratorIntegration:
    """VoiceGenerator 集成场景"""

    def test_multiple_frames_same_session(self):
        gen = VoiceGenerator()
        # 模拟流式 TTS：多个数据帧 + 结束帧
        frames = []
        for chunk in [b"chunk1", b"chunk2", b"chunk3"]:
            frames.append(gen.make_tts_frame("0001", chunk))
        frames.append(gen.make_end_frame("0001"))

        # 所有数据帧应以 session + "00" 开头
        for f in frames[:-1]:
            assert f[:6] == b"000100"
        # 结束帧应以 session + "03" 开头
        assert frames[-1] == b"000103"

    def test_prefix_cache_shared_across_calls(self):
        gen = VoiceGenerator()
        # 同一 (session_id, status) 组合应共享缓存前缀
        gen.make_tts_frame("0001", b"a", status="00")
        gen.make_tts_frame("0001", b"b", status="00")
        gen.make_tts_frame("0001", b"c", status="00")
        # 缓存中只有一个条目
        assert len(gen._prefix_cache) == 1

    def test_different_status_cache_entries(self):
        gen = VoiceGenerator()
        gen.make_tts_frame("0001", b"a", status="00")
        gen.make_tts_frame("0001", b"b", status="01")
        gen.make_tts_frame("0001", b"c", status="03")
        # 三个不同 status 各一个条目
        assert len(gen._prefix_cache) == 3


class TestVoiceGeneratorWithFixtures:
    """使用 conftest 中的 fixtures"""

    def test_with_sample_audio_chunk(self, sample_audio_chunk):
        gen = VoiceGenerator()
        frame = gen.make_tts_frame("0001", sample_audio_chunk)
        assert frame[:6] == b"000100"
        assert len(frame) == 6 + len(sample_audio_chunk)

    def test_end_frame_independent_of_audio(self, sample_audio_chunk):
        gen = VoiceGenerator()
        # 结束帧长度固定，与音频数据无关
        end = gen.make_end_frame("0001")
        assert len(end) == 6
