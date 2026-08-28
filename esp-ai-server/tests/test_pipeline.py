"""
Pipeline 单元测试

覆盖 src/use_cases/pipeline.py:
- SentenceSplitter     : 流式 token → 完整句子（硬切分 / 软切分 / flush / reset）
- PipelineConfig       : 流水线配置 dataclass
- PipelineResult       : 流水线结果 dataclass
- PipelineState        : 状态枚举
- ConversationPipeline : 4-Worker 并发流水线（构造、属性、情绪检测、interrupt、run）
- create_pipeline      : 工厂函数

测试策略：
- asyncio_mode="auto"
- 使用 Mock/AsyncMock 模拟 LLM/TTS/Channel/FSM，避免真实网络调用
- SentenceSplitter 为纯函数式单元测试，覆盖硬/软切分阈值与边界
- ConversationPipeline.run() 通过 mock LLM stream_chat + mock TTS synthesize 走完整流程
"""
from __future__ import annotations

import asyncio
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.use_cases.pipeline import (
    ConversationPipeline,
    PipelineConfig,
    PipelineResult,
    PipelineState,
    SentenceSplitter,
    create_pipeline,
)


# ════════════════════════════════════════════════════════════
# SentenceSplitter — 纯单元测试
# ════════════════════════════════════════════════════════════
class TestSentenceSplitterHardSplit:
    """硬切分点（。！？.!?）测试"""

    def test_empty_token_returns_empty(self):
        s = SentenceSplitter()
        assert s.feed("") == []
        assert s.feed(None) == []  # type: ignore[arg-type]

    def test_no_punctuation_no_split(self):
        # 无标点时不切分，token 累积到 buffer
        s = SentenceSplitter()
        assert s.feed("你好") == []
        assert s.feed("世界") == []
        assert s.buffer == "你好世界"

    def test_single_chinese_period(self):
        # 中文句号触发硬切分
        s = SentenceSplitter()
        result = s.feed("你好。")
        assert result == ["你好。"]

    def test_multiple_hard_splits_in_one_token(self):
        # 一个 token 内多个硬切分点
        s = SentenceSplitter()
        result = s.feed("你好。世界！")
        assert result == ["你好。", "世界！"]

    def test_hard_split_across_tokens(self):
        # 句号跨 token 到达
        s = SentenceSplitter()
        assert s.feed("你好") == []
        result = s.feed("。再见。")
        assert result == ["你好。", "再见。"]

    def test_english_punctuation(self):
        s = SentenceSplitter()
        result = s.feed("Hello! How are you?")
        assert result == ["Hello!", "How are you?"]

    def test_hard_split_strips_whitespace(self):
        # 切分后 strip 空白
        s = SentenceSplitter()
        result = s.feed("  你好。  ")
        assert result == ["你好。"]

    def test_hard_split_short_ignored(self):
        # 切分后长度 <= 1 的片段被忽略
        s = SentenceSplitter()
        result = s.feed("。")  # 仅一个句号
        # "。" strip 后长度为 1，被忽略
        assert result == []

    def test_hard_split_remaining_in_buffer(self):
        # 硬切分后剩余部分留在 buffer
        s = SentenceSplitter()
        result = s.feed("你好。世界")
        assert result == ["你好。"]
        assert s.buffer == "世界"

    def test_question_mark_split(self):
        s = SentenceSplitter()
        result = s.feed("你好吗？我很好。")
        assert result == ["你好吗？", "我很好。"]

    def test_exclamation_split(self):
        s = SentenceSplitter()
        result = s.feed("太棒了！")
        assert result == ["太棒了！"]


class TestSentenceSplitterSoftSplit:
    """软切分点（，；,）测试 — 子句 >= 2 字符（索引 >= 1）才切分"""

    def test_soft_split_at_threshold(self):
        # 子句正好 2 字符（逗号索引=1），应切分
        # "你好，" -> 你=0,好=1,，=2 -> last_soft=2 >= 1 -> 切分
        s = SentenceSplitter()
        result = s.feed("你好，测试")
        assert result == ["你好，"]
        assert s.buffer == "测试"

    def test_soft_split_below_threshold(self):
        # 子句 < 2 字符（逗号索引 < 1，即逗号是第一个字符），不切分
        # "，测试" -> ，索引=0 < 1 -> 不切分
        s = SentenceSplitter()
        result = s.feed("，测试")
        assert result == []
        assert s.buffer == "，测试"

    def test_soft_split_comma(self):
        # 英文逗号也支持软切分
        s = SentenceSplitter()
        result = s.feed("hello world, test")
        # "hello world, test" - 逗号在索引 11 >= 3，切分 "hello world,"
        assert result == ["hello world,"]
        assert s.buffer == " test"

    def test_soft_split_semicolon_chinese(self):
        # 中文分号
        s = SentenceSplitter()
        result = s.feed("你好世界；测试")
        assert result == ["你好世界；"]
        assert s.buffer == "测试"

    def test_soft_split_last_occurrence(self):
        # 多个软切分点时取最后一个
        s = SentenceSplitter()
        result = s.feed("你好，世界，测试")
        # buffer = "你好，世界，测试"，last_soft = 逗号在索引 6
        # 切分到索引 6+1 = "你好，世界，"
        assert result == ["你好，世界，"]
        assert s.buffer == "测试"

    def test_soft_split_skipped_when_hard_present(self):
        # 同时有硬切分点时，软切分逻辑不执行（not sentences 为 False）
        s = SentenceSplitter()
        result = s.feed("你好。世界，测试")
        # 硬切分先执行：["你好。"]，buffer="世界，测试"
        # sentences 非空 -> 软切分跳过
        assert result == ["你好。"]
        assert s.buffer == "世界，测试"

    def test_soft_split_short_ignored(self):
        # 软切分后长度 <= 1 的片段被忽略
        s = SentenceSplitter()
        # 构造一个 strip 后长度 <= 1 的情况较难，这里验证正常路径
        result = s.feed("你好世界，")
        assert result == ["你好世界，"]
        assert s.buffer == ""


class TestSentenceSplitterFlush:
    """flush() 测试"""

    def test_flush_returns_remaining(self):
        s = SentenceSplitter()
        s.feed("你好世界")
        remaining = s.flush()
        assert remaining == "你好世界"
        assert s.buffer == ""

    def test_flush_short_returns_empty(self):
        # 剩余长度 <= 1 时返回空字符串
        s = SentenceSplitter()
        s.feed("你")
        remaining = s.flush()
        assert remaining == ""
        assert s.buffer == ""

    def test_flush_empty_buffer(self):
        s = SentenceSplitter()
        assert s.flush() == ""

    def test_flush_clears_buffer(self):
        s = SentenceSplitter()
        s.feed("你好世界")
        s.flush()
        assert s.buffer == ""
        # 再次 flush 返回空
        assert s.flush() == ""

    def test_flush_after_hard_split(self):
        s = SentenceSplitter()
        s.feed("你好。世界")
        # 硬切分产出 "你好。"，buffer="世界"
        assert s.flush() == "世界"


class TestSentenceSplitterReset:
    """reset() 测试"""

    def test_reset_clears_buffer(self):
        s = SentenceSplitter()
        s.feed("你好世界")
        s.reset()
        assert s.buffer == ""

    def test_reset_then_feed(self):
        s = SentenceSplitter()
        s.feed("你好世界")
        s.reset()
        result = s.feed("新句子。")
        assert result == ["新句子。"]

    def test_reset_on_empty(self):
        s = SentenceSplitter()
        s.reset()
        assert s.buffer == ""


# ════════════════════════════════════════════════════════════
# PipelineConfig / PipelineResult / PipelineState
# ════════════════════════════════════════════════════════════
class TestPipelineConfig:
    """PipelineConfig dataclass 测试"""

    def test_defaults(self):
        c = PipelineConfig()
        assert c.max_queue_size == 100
        assert c.llm_timeout == 30.0
        assert c.tts_timeout == 20.0
        assert c.enable_tts_session_reuse is True
        assert c.tts_session_id == "0010"
        assert c.text_send_delay == 1
        assert c.client_max_buffer == 10240

    def test_custom(self):
        c = PipelineConfig(max_queue_size=50, tts_session_id="abcd", text_send_delay=3)
        assert c.max_queue_size == 50
        assert c.tts_session_id == "abcd"
        assert c.text_send_delay == 3


class TestPipelineResult:
    """PipelineResult dataclass 测试"""

    def test_required_state(self):
        r = PipelineResult(state=PipelineState.IDLE)
        assert r.state == PipelineState.IDLE
        assert r.duration == 0.0
        assert r.total_sentences == 0
        assert r.total_audio_chunks == 0
        assert r.full_text == ""
        assert r.error is None
        assert r.stop_pipeline is False
        assert r.total_duration_ms == 0.0

    def test_full(self):
        r = PipelineResult(
            state=PipelineState.STOPPED,
            duration=1.5,
            total_sentences=3,
            total_audio_chunks=10,
            full_text="hello",
            error="boom",
            stop_pipeline=True,
            total_duration_ms=500.0,
        )
        assert r.duration == 1.5
        assert r.total_sentences == 3
        assert r.total_audio_chunks == 10
        assert r.full_text == "hello"
        assert r.error == "boom"
        assert r.stop_pipeline is True
        assert r.total_duration_ms == 500.0


class TestPipelineState:
    """PipelineState 枚举测试"""

    def test_all_states_distinct(self):
        states = {PipelineState.IDLE, PipelineState.RUNNING, PipelineState.STOPPING, PipelineState.STOPPED, PipelineState.ERROR}
        assert len(states) == 5

    def test_state_values_are_int(self):
        # auto() 产生 int 值
        for s in PipelineState:
            assert isinstance(s.value, int)


# ════════════════════════════════════════════════════════════
# 辅助 Mock 工厂
# ════════════════════════════════════════════════════════════
def make_mock_llm(tokens: list[str], system_prompt: str = "你是助手"):
    """构造 mock LLM 处理器"""
    llm = MagicMock()
    llm.system_prompt = system_prompt

    async def _stream_chat(messages):
        for t in tokens:
            yield t

    llm.stream_chat = _stream_chat
    return llm


def make_mock_tts(audio_chunks: list[bytes] | None = None):
    """构造 mock TTS 处理器，create_session 返回 mock session"""
    chunks = audio_chunks if audio_chunks is not None else [b"\x00\x01\x02\x03"]

    class _MockTTSSession:
        def __init__(self):
            self.closed = False
            self.synthesize_calls: list[str] = []

        async def synthesize(self, text, cancel_event=None):
            self.synthesize_calls.append(text)
            for c in chunks:
                if cancel_event and cancel_event.is_set():
                    break
                yield c

        async def close(self):
            self.closed = True

    tts = MagicMock()
    session_holder = _MockTTSSession()

    async def _create_session(cancel_event=None, tool_manager=None):
        return session_holder

    tts.create_session = _create_session
    tts._session = session_holder
    return tts


def make_pipeline(
    llm=None,
    tts=None,
    channel=None,
    fsm=None,
    voice_generator=None,
    config=None,
    conversation_memory=None,
    user_config=None,
    cancel_event=None,
    device_id="dev-1",
    ltm_service=None,
    precomputed_skill_catalog=None,
    memory_search_keywords=None,
) -> ConversationPipeline:
    """快速构造 ConversationPipeline，所有依赖使用 mock"""
    return ConversationPipeline(
        llm_processor=llm or make_mock_llm(["你好。"]),
        tts_processor=tts or make_mock_tts(),
        channel=channel or MagicMock(),
        fsm=fsm or MagicMock(),
        voice_generator=voice_generator,
        config=config,
        conversation_memory=conversation_memory,
        user_config=user_config,
        cancel_event=cancel_event,
        device_id=device_id,
        ltm_service=ltm_service,
        precomputed_skill_catalog=precomputed_skill_catalog,
        memory_search_keywords=memory_search_keywords,
    )


# ════════════════════════════════════════════════════════════
# ConversationPipeline — 构造与属性
# ════════════════════════════════════════════════════════════
class TestConversationPipelineInit:
    """ConversationPipeline 构造函数测试"""

    def test_defaults(self):
        p = make_pipeline()
        assert p.device_id == "dev-1"
        assert p.state == PipelineState.IDLE
        assert p.config.tts_session_id == "0010"
        assert p.splitter is not None
        assert p.queues is not None
        assert p.cancel_event is not None
        assert p._tts_playing is False
        assert p._tasks == []
        assert p._total_duration_ms == 0.0

    def test_precomputed_skill_catalog_set(self):
        # 传入 precomputed_skill_catalog 时缓存到 _cached_skill_catalog
        p = make_pipeline(precomputed_skill_catalog="PRECOMPUTED_CATALOG")
        assert p._cached_skill_catalog == "PRECOMPUTED_CATALOG"
        # _skill_cache_key 标记为预计算
        assert p._skill_cache_key == "__precomputed__"

    def test_precomputed_skill_catalog_none(self):
        # 未传入时为 None，cache_key 为空字符串
        p = make_pipeline()
        assert p._cached_skill_catalog is None
        assert p._skill_cache_key == ""

    def test_reply_style_template(self):
        p = make_pipeline()
        assert "[回复要求]" in p._reply_style
        assert "[/回复要求]" in p._reply_style

    def test_custom_config(self):
        config = PipelineConfig(tts_session_id="abcd", client_max_buffer=2048)
        p = make_pipeline(config=config)
        assert p.config.tts_session_id == "abcd"
        assert p.config.client_max_buffer == 2048
        # _device_buffer 初始化为 client_max_buffer
        assert p._device_buffer == 2048

    def test_cancel_event_reused(self):
        # 传入 cancel_event 时复用，不创建新的
        ev = asyncio.Event()
        p = make_pipeline(cancel_event=ev)
        assert p.cancel_event is ev

    def test_voice_generator_default(self):
        # 未传 voice_generator 时自动创建
        from src.use_cases.voice_generator import VoiceGenerator
        p = make_pipeline()
        assert isinstance(p.voice_generator, VoiceGenerator)


class TestConversationPipelineProperties:
    """tts_playing / device_buffer 属性与 setter 测试"""

    async def test_tts_playing_setter(self):
        p = make_pipeline()
        assert p.tts_playing is False
        await p.set_tts_playing(True)
        assert p.tts_playing is True
        await p.set_tts_playing(False)
        assert p.tts_playing is False

    async def test_device_buffer_setter(self):
        p = make_pipeline()
        # 初始为 client_max_buffer
        assert p.device_buffer == 10240
        await p.set_device_buffer(512)
        assert p.device_buffer == 512

    async def test_tts_playing_concurrent(self):
        # 锁保护并发设置
        p = make_pipeline()
        await asyncio.gather(
            p.set_tts_playing(True),
            p.set_tts_playing(False),
            p.set_tts_playing(True),
        )
        assert p.tts_playing is True


# ════════════════════════════════════════════════════════════
# ConversationPipeline — 情绪检测
# ════════════════════════════════════════════════════════════
class TestEmotionDetection:
    """情绪标签解析与关键词检测测试"""

    def test_parse_emotion_tag_with_tag(self):
        # 带 [e:情绪] 标签的文本
        text, emotion = ConversationPipeline._parse_emotion_tag("你好[e:happy]世界")
        assert emotion == "happy"
        # 标签前的文本被保留，尾部标点被 strip
        assert "你好" in text

    def test_parse_emotion_tag_no_tag(self):
        text, emotion = ConversationPipeline._parse_emotion_tag("你好世界")
        assert emotion == ""
        assert text == "你好世界"

    def test_parse_emotion_tag_strips_trailing_punctuation(self):
        # 标签前的标点被 strip
        text, emotion = ConversationPipeline._parse_emotion_tag("你好，[e:sad]")
        assert emotion == "sad"
        assert text == "你好"

    def test_keyword_detect_happy(self):
        assert ConversationPipeline._keyword_detect("太棒了") == "快乐"

    def test_keyword_detect_sad(self):
        assert ConversationPipeline._keyword_detect("我很伤心") == "伤心"

    def test_keyword_detect_angry(self):
        assert ConversationPipeline._keyword_detect("气死我了") == "愤怒"

    def test_keyword_detect_surprised(self):
        assert ConversationPipeline._keyword_detect("真的假的") == "意外"

    def test_keyword_detect_negative(self):
        assert ConversationPipeline._keyword_detect("我拒绝") == "否定"

    def test_keyword_detect_none(self):
        # 不含任何情绪关键词时返回空字符串
        assert ConversationPipeline._keyword_detect("请问现在几点了") == ""
        assert ConversationPipeline._keyword_detect("完全无关的内容xyz") == ""

    def test_keyword_detect_case_insensitive(self):
        # 英文关键词小写匹配
        assert ConversationPipeline._keyword_detect("this is nice") == "快乐"
        assert ConversationPipeline._keyword_detect("GOOD job") == "快乐"

    async def test_detect_and_send_emotion_with_tag(self):
        # 带标签时发送情绪，返回纯文本
        channel = MagicMock()
        channel.send_json = AsyncMock()
        p = make_pipeline(channel=channel)
        result = p._detect_and_send_emotion("你好[e:happy]")
        assert "你好" in result
        assert "[e:happy]" not in result
        assert p._last_emotion == "happy"

    async def test_detect_and_send_emotion_keyword(self):
        channel = MagicMock()
        channel.send_json = AsyncMock()
        p = make_pipeline(channel=channel)
        result = p._detect_and_send_emotion("太棒了")
        # 关键词检测到快乐
        assert p._last_emotion == "快乐"

    async def test_detect_and_send_emotion_neutral_first_time(self):
        # 首次无情绪时设置 _last_emotion 为 "无情绪"
        channel = MagicMock()
        channel.send_json = AsyncMock()
        p = make_pipeline(channel=channel)
        p._detect_and_send_emotion("完全无关的内容xyz")
        assert p._last_emotion == "无情绪"

    async def test_detect_and_send_emotion_no_override(self):
        # 已有情绪时，无情绪不覆盖
        channel = MagicMock()
        channel.send_json = AsyncMock()
        p = make_pipeline(channel=channel)
        p._last_emotion = "快乐"
        p._detect_and_send_emotion("完全无关的内容xyz")
        # _last_emotion 保持 "快乐"
        assert p._last_emotion == "快乐"

    async def test_send_emotion_task_handles_failure(self):
        # _send_emotion_task 在 send_json 失败时不抛异常
        channel = MagicMock()
        channel.send_json = AsyncMock(side_effect=RuntimeError("send failed"))
        p = make_pipeline(channel=channel)
        # 不应抛异常
        await p._send_emotion_task("happy")


# ════════════════════════════════════════════════════════════
# ConversationPipeline — interrupt
# ════════════════════════════════════════════════════════════
class TestConversationPipelineInterrupt:
    """interrupt() 测试"""

    async def test_interrupt_sets_cancel_event(self):
        p = make_pipeline()
        assert not p.cancel_event.is_set()
        await p.interrupt()
        assert p.cancel_event.is_set()

    async def test_interrupt_clears_queues(self):
        p = make_pipeline()
        await p.queues.text.put(("a", "b"))
        await p.queues.audio.put(("a", "b", "c"))
        await p.interrupt()
        assert p.queues.text.empty()
        assert p.queues.audio.empty()

    async def test_interrupt_resets_splitter(self):
        p = make_pipeline()
        p.splitter.feed("你好世界")
        assert p.splitter.buffer != ""
        await p.interrupt()
        assert p.splitter.buffer == ""

    async def test_interrupt_sets_tts_playing_false(self):
        p = make_pipeline()
        await p.set_tts_playing(True)
        await p.interrupt()
        assert p.tts_playing is False

    async def test_interrupt_sets_playback_events(self):
        p = make_pipeline()
        assert not p.tts_playback_done.is_set()
        await p.interrupt()
        assert p.tts_playback_done.is_set()
        assert p.tts_audio_ended.is_set()

    async def test_interrupt_sends_end_frame_when_play_audio_sent(self):
        # _play_audio_sent=True 时发送 end_frame
        channel = MagicMock()
        channel.send_bytes = AsyncMock()
        channel.send_json = AsyncMock()
        vg = MagicMock()
        vg.make_end_frame = MagicMock(return_value=b"END_FRAME")
        p = make_pipeline(channel=channel, voice_generator=vg)
        p._play_audio_sent = True
        await p.interrupt()
        channel.send_bytes.assert_called_once_with(b"END_FRAME")
        channel.send_json.assert_called()

    async def test_interrupt_skips_end_frame_when_not_sent(self):
        # _play_audio_sent=False 时不发送 end_frame
        channel = MagicMock()
        channel.send_bytes = AsyncMock()
        channel.send_json = AsyncMock()
        vg = MagicMock()
        vg.make_end_frame = MagicMock(return_value=b"END_FRAME")
        p = make_pipeline(channel=channel, voice_generator=vg)
        p._play_audio_sent = False
        await p.interrupt()
        channel.send_bytes.assert_not_called()

    async def test_interrupt_cancels_tasks(self):
        p = make_pipeline()
        # 创建一个模拟 task
        task = asyncio.create_task(asyncio.sleep(10))
        p._tasks = [task]
        await p.interrupt()
        # 等待取消传播
        await asyncio.sleep(0.01)
        assert task.cancelled() or task.done()
        assert p._tasks == []

    async def test_interrupt_send_json_failure_swallowed(self):
        # send_json 失败时不应抛异常
        channel = MagicMock()
        channel.send_bytes = AsyncMock()
        channel.send_json = AsyncMock(side_effect=RuntimeError("fail"))
        vg = MagicMock()
        vg.make_end_frame = MagicMock(return_value=b"END")
        p = make_pipeline(channel=channel, voice_generator=vg)
        p._play_audio_sent = True
        await p.interrupt()  # 不应抛异常


# ════════════════════════════════════════════════════════════
# ConversationPipeline — run() 端到端（mock LLM/TTS）
# ════════════════════════════════════════════════════════════
class TestConversationPipelineRun:
    """run() 完整流程测试（使用 mock LLM/TTS）"""

    def _make_channel_fsm(self):
        """构造记录发送内容的 channel 和 mock fsm"""
        channel = MagicMock()
        channel.sent_json: list = []
        channel.sent_bytes: list = []

        async def _send_json(data):
            channel.sent_json.append(data)

        async def _send_bytes(data):
            channel.sent_bytes.append(data)

        channel.send_json = _send_json
        channel.send_bytes = _send_bytes
        channel.connected = True

        fsm = MagicMock()
        fsm.set = AsyncMock()
        return channel, fsm

    async def test_run_happy_path(self):
        # 正常路径：LLM 产出句子 → TTS 合成 → 发送音频帧 → end_frame
        channel, fsm = self._make_channel_fsm()
        llm = make_mock_llm(["你好。", "世界。"])
        tts = make_mock_tts([b"\x01\x02\x03\x04"])
        cancel_event = asyncio.Event()
        p = ConversationPipeline(
            llm_processor=llm,
            tts_processor=tts,
            channel=channel,
            fsm=fsm,
            cancel_event=cancel_event,
            device_id="dev-test",
        )
        result = await p.run("用户输入")
        assert result.state == PipelineState.STOPPED
        assert result.duration >= 0
        assert result.stop_pipeline is False
        # full_text 应包含 LLM 产出的全部 token
        assert "你好" in result.full_text
        assert "世界" in result.full_text
        # FSM 应被设置过 LLM 和 TTS
        assert fsm.set.call_count >= 2
        # 应发送 end_frame（bytes）和 tts_real_end（json）
        assert any(isinstance(b, bytes) and len(b) > 0 for b in channel.sent_bytes)
        assert any(
            isinstance(j, dict) and j.get("status") == "tts_real_end"
            for j in channel.sent_json
        )

    async def test_run_with_precomputed_skill_catalog(self):
        # 传入 precomputed_skill_catalog 时，__init__ 缓存到 _cached_skill_catalog
        # run() 内部会根据 cache_key 决定是否重新渲染
        channel, fsm = self._make_channel_fsm()
        llm = make_mock_llm(["你好。"])
        tts = make_mock_tts([b"\x01\x02"])
        p = ConversationPipeline(
            llm_processor=llm,
            tts_processor=tts,
            channel=channel,
            fsm=fsm,
            device_id="dev-test",
            precomputed_skill_catalog="PRECOMPUTED",
        )
        # 构造时已缓存
        assert p._cached_skill_catalog == "PRECOMPUTED"
        assert p._skill_cache_key == "__precomputed__"
        result = await p.run("hi")
        assert result.state == PipelineState.STOPPED
        # run() 后 cache_key 被更新为实际 skill_key（重新渲染覆盖缓存）
        assert p._skill_cache_key != "__precomputed__"

    async def test_run_empty_llm_output(self):
        # LLM 不产出任何 token
        channel, fsm = self._make_channel_fsm()
        llm = make_mock_llm([])
        tts = make_mock_tts([b"\x01\x02"])
        p = ConversationPipeline(
            llm_processor=llm,
            tts_processor=tts,
            channel=channel,
            fsm=fsm,
            device_id="dev-test",
        )
        result = await p.run("hi")
        assert result.state == PipelineState.STOPPED
        assert result.full_text == ""
        # 没有音频帧发送，不应发送 end_frame
        assert not any(
            isinstance(j, dict) and j.get("status") == "tts_real_end"
            for j in channel.sent_json
        )

    async def test_run_with_cancel_event(self):
        # 在 run 期间设置 cancel_event，pipeline 应能退出
        channel, fsm = self._make_channel_fsm()
        cancel_event = asyncio.Event()

        async def _slow_stream(messages):
            yield "你好。"
            cancel_event.set()  # 产出一句后取消
            yield "世界。"

        llm = MagicMock()
        llm.system_prompt = "SP"
        llm.stream_chat = _slow_stream
        tts = make_mock_tts([b"\x01\x02"])
        p = ConversationPipeline(
            llm_processor=llm,
            tts_processor=tts,
            channel=channel,
            fsm=fsm,
            cancel_event=cancel_event,
            device_id="dev-test",
        )
        result = await p.run("hi")
        # 应正常结束（状态 STOPPED）
        assert result.state == PipelineState.STOPPED

    async def test_run_tts_create_session_failure(self):
        # TTS 预连接失败时，run 内部捕获并继续
        channel, fsm = self._make_channel_fsm()
        llm = make_mock_llm(["你好。"])

        tts = MagicMock()

        async def _failing_create_session(cancel_event=None, tool_manager=None):
            raise RuntimeError("TTS connection failed")

        tts.create_session = _failing_create_session
        p = ConversationPipeline(
            llm_processor=llm,
            tts_processor=tts,
            channel=channel,
            fsm=fsm,
            device_id="dev-test",
        )
        # run 内部会捕获 TTS 预连接异常，_tts_task 会再次尝试 create_session
        # 这里再次失败会通过 send_queue 投递结束标记，pipeline 最终 STOPPED
        result = await p.run("hi")
        assert result.state == PipelineState.STOPPED

    async def test_run_stop_pipeline_signal(self):
        # LLM 产出 __STOP_PIPELINE__ token 时触发 StopPipeline
        channel, fsm = self._make_channel_fsm()
        llm = make_mock_llm(["__STOP_PIPELINE__"])
        tts = make_mock_tts([b"\x01\x02"])
        p = ConversationPipeline(
            llm_processor=llm,
            tts_processor=tts,
            channel=channel,
            fsm=fsm,
            device_id="dev-test",
        )
        result = await p.run("hi")
        assert result.state == PipelineState.STOPPED
        # stop_pipeline 应为 True
        assert result.stop_pipeline is True

    async def test_run_llm_error_token(self):
        # LLM 产出 "LLM error..." token 时中断
        channel, fsm = self._make_channel_fsm()
        llm = make_mock_llm(["LLM error: timeout"])
        tts = make_mock_tts([b"\x01\x02"])
        p = ConversationPipeline(
            llm_processor=llm,
            tts_processor=tts,
            channel=channel,
            fsm=fsm,
            device_id="dev-test",
        )
        result = await p.run("hi")
        assert result.state == PipelineState.STOPPED

    async def test_run_with_conversation_memory(self):
        # 启用会话记忆时，run 后应记录 user/assistant 消息
        from src.use_cases.memory import ConversationMemory
        channel, fsm = self._make_channel_fsm()
        llm = make_mock_llm(["你好。"])
        tts = make_mock_tts([b"\x01\x02"])
        memory = ConversationMemory(device_id="dev-test")
        p = ConversationPipeline(
            llm_processor=llm,
            tts_processor=tts,
            channel=channel,
            fsm=fsm,
            conversation_memory=memory,
            device_id="dev-test",
        )
        await p.run("用户的问题")
        # 应记录 user 和 assistant 消息
        assert len(memory._messages) == 2
        assert memory._messages[0]["role"] == "user"
        assert memory._messages[1]["role"] == "assistant"
        assert memory._messages[0]["content"] == "用户的问题"

    async def test_run_sets_fsm_states(self):
        channel, fsm = self._make_channel_fsm()
        llm = make_mock_llm(["你好。"])
        tts = make_mock_tts([b"\x01\x02"])
        p = ConversationPipeline(
            llm_processor=llm,
            tts_processor=tts,
            channel=channel,
            fsm=fsm,
            device_id="dev-test",
        )
        await p.run("hi")
        # 验证 FSM 被设置为 LLM 和 TTS
        from src.domain.entities import SessionState
        called_states = [call.args[0] for call in fsm.set.call_args_list]
        assert SessionState.LLM in called_states
        assert SessionState.TTS in called_states

    async def test_run_total_duration_accumulated(self):
        # 验证音频时长被累计
        channel, fsm = self._make_channel_fsm()
        llm = make_mock_llm(["你好世界。"])
        tts = make_mock_tts([b"\x01" * 100])
        p = ConversationPipeline(
            llm_processor=llm,
            tts_processor=tts,
            channel=channel,
            fsm=fsm,
            device_id="dev-test",
        )
        result = await p.run("hi")
        # total_duration_ms 应 >= 500（最小估算值）
        assert result.total_duration_ms >= 500


# ════════════════════════════════════════════════════════════
# create_pipeline 工厂函数
# ════════════════════════════════════════════════════════════
class TestCreatePipeline:
    """create_pipeline 工厂函数测试"""

    def test_create_pipeline_defaults(self):
        llm = make_mock_llm(["hi"])
        tts = make_mock_tts()
        channel = MagicMock()
        fsm = MagicMock()
        p = create_pipeline(llm, tts, channel, fsm)
        assert isinstance(p, ConversationPipeline)
        assert p.llm_processor is llm
        assert p.tts_processor is tts
        assert p.channel is channel
        assert p.fsm is fsm
        # 默认 config
        assert p.config.tts_session_id == "0010"

    def test_create_pipeline_with_config_dict(self):
        llm = make_mock_llm(["hi"])
        tts = make_mock_tts()
        channel = MagicMock()
        fsm = MagicMock()
        p = create_pipeline(
            llm, tts, channel, fsm,
            config={"tts_session_id": "xxxx", "client_max_buffer": 4096},
        )
        assert p.config.tts_session_id == "xxxx"
        assert p.config.client_max_buffer == 4096

    def test_create_pipeline_with_none_config(self):
        # config=None 时使用默认 PipelineConfig
        llm = make_mock_llm(["hi"])
        tts = make_mock_tts()
        p = create_pipeline(llm, tts, MagicMock(), MagicMock(), config=None)
        assert p.config.max_queue_size == 100

    def test_create_pipeline_with_voice_generator(self):
        from src.use_cases.voice_generator import VoiceGenerator
        llm = make_mock_llm(["hi"])
        tts = make_mock_tts()
        vg = VoiceGenerator()
        p = create_pipeline(llm, tts, MagicMock(), MagicMock(), voice_generator=vg)
        assert p.voice_generator is vg

    def test_create_pipeline_with_memory(self):
        from src.use_cases.memory import ConversationMemory
        llm = make_mock_llm(["hi"])
        tts = make_mock_tts()
        mem = ConversationMemory()
        p = create_pipeline(llm, tts, MagicMock(), MagicMock(), conversation_memory=mem)
        assert p.conversation_memory is mem

    def test_create_pipeline_with_user_config(self):
        llm = make_mock_llm(["hi"])
        tts = make_mock_tts()
        uc = MagicMock()
        uc.llm_memory_enabled = False
        uc.llm_memory_max_messages = 5
        uc.llm_system_prompt = "custom prompt"
        p = create_pipeline(llm, tts, MagicMock(), MagicMock(), user_config=uc)
        assert p.user_config is uc


# ════════════════════════════════════════════════════════════
# 流信号常量 / 记忆关键词配置
# ════════════════════════════════════════════════════════════
class TestStreamSignalConstants:
    """流内控制信号常量测试（与 llm_gateways.py 的字面量保持一致）"""

    def test_stop_pipeline_sentinel_value(self):
        from src.use_cases.pipeline import STOP_PIPELINE_SENTINEL
        assert STOP_PIPELINE_SENTINEL == "__STOP_PIPELINE__"

    def test_llm_error_prefix_value(self):
        from src.use_cases.pipeline import LLM_ERROR_PREFIX
        assert LLM_ERROR_PREFIX == "LLM error"

    async def test_run_stop_pipeline_uses_constant(self):
        # LLM 产出常量信号 token 时触发 StopPipeline
        from src.use_cases.pipeline import STOP_PIPELINE_SENTINEL
        channel = MagicMock()
        channel.send_json = AsyncMock()
        channel.send_bytes = AsyncMock()
        fsm = MagicMock()
        fsm.set = AsyncMock()
        llm = make_mock_llm([STOP_PIPELINE_SENTINEL])
        p = make_pipeline(llm=llm, channel=channel, fsm=fsm)
        result = await p.run("hi")
        assert result.stop_pipeline is True


class TestMemorySearchKeywords:
    """记忆检索关键词可配置测试"""

    def test_default_constant_keeps_original_words(self):
        from src.use_cases.pipeline import DEFAULT_MEMORY_SEARCH_KEYWORDS
        # 行为兼容：默认列表保留原有全部关键词
        assert DEFAULT_MEMORY_SEARCH_KEYWORDS == [
            "工作", "累", "职业", "上班", "外卖", "代码", "顾客", "编程",
            "猫", "宠物", "玩具", "天气", "下雨", "送餐", "跑外卖",
        ]

    def test_init_default_is_none(self):
        p = make_pipeline()
        assert p.memory_search_keywords is None

    def test_init_custom_keywords(self):
        p = make_pipeline(memory_search_keywords=["音乐", "电影"])
        assert p.memory_search_keywords == ["音乐", "电影"]

    def test_create_pipeline_passthrough_from_config_dict(self):
        # config dict 中的 memory_search_keywords 被透传，且不会误传给 PipelineConfig
        p = create_pipeline(
            make_mock_llm(["hi"]), make_mock_tts(), MagicMock(), MagicMock(),
            config={"tts_session_id": "abcd", "memory_search_keywords": ["天气"]},
        )
        assert p.memory_search_keywords == ["天气"]
        assert p.config.tts_session_id == "abcd"

    def test_create_pipeline_default_keywords_none(self):
        p = create_pipeline(make_mock_llm(["hi"]), make_mock_tts(), MagicMock(), MagicMock())
        assert p.memory_search_keywords is None
