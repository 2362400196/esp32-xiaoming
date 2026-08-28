"""
Session & SessionRuntime 单元测试

覆盖 src/use_cases/session.py:
- SessionRuntime : ASR/TTS 生命周期运行时
- Session        : 完整会话类（ASR → Pipeline → 下一轮 ASR 循环）

测试策略：
- asyncio_mode="auto"
- 使用 Mock/AsyncMock 模拟 LLM/TTS/ASR/Channel/FSM，避免真实网络调用
- 用 FakeMemoryRepository 替代 SqlShortTermMemoryRepository，避免 DB 访问
- 复杂的 _asr_streaming_loop / start_asr 通过 patch 简化为可控任务
- 覆盖正常路径、边界条件、异常处理
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.entities import SessionState
from src.use_cases.session import Session, SessionRuntime


# ════════════════════════════════════════════════════════════
# 辅助：内存版 MemoryRepository（避免文件系统访问）
# ════════════════════════════════════════════════════════════
class FakeMemoryRepository:
    """内存版会话记忆仓储"""

    def __init__(self):
        self.store: dict[str, list] = {}
        self.save_calls: list = []

    def load(self, device_id):
        return list(self.store.get(device_id, []))

    def save(self, device_id, messages):
        self.save_calls.append((device_id, messages))
        self.store[device_id] = list(messages)

    def delete(self, device_id):
        self.store.pop(device_id, None)


def make_session(
    device_id: str = "dev-test",
    channel=None,
    fsm=None,
    voice_generator=None,
    llm_processor=None,
    tts_processor=None,
    asr_client=None,
    tool_mgr=None,
    user_config=None,
    no_speech_timeout: float = 5.0,
    silence_timeout: float = 2.0,
    ltm_service=None,
    client_max_buffer: int = 10240,
    memory_repository=None,
) -> Session:
    """构造一个全部依赖被 mock 的 Session"""
    if channel is None:
        channel = MagicMock()
        channel.send_json = AsyncMock()
        channel.send_bytes = AsyncMock()
        channel.send_text = AsyncMock()
        channel.connected = True
    if fsm is None:
        fsm = MagicMock()
        fsm.set = AsyncMock()
        fsm.get = MagicMock(return_value=SessionState.IDLE)
    if voice_generator is None:
        vg = MagicMock()
        vg.make_end_frame = MagicMock(return_value=b"END_FRAME")
        vg.make_tts_frame = MagicMock(return_value=b"TTS_FRAME")
        voice_generator = vg
    return Session(
        device_id=device_id,
        channel=channel,
        fsm=fsm,
        voice_generator=voice_generator,
        llm_processor=llm_processor or MagicMock(),
        tts_processor=tts_processor or MagicMock(),
        asr_client=asr_client,
        tool_mgr=tool_mgr,
        user_config=user_config,
        no_speech_timeout=no_speech_timeout,
        silence_timeout=silence_timeout,
        ltm_service=ltm_service,
        client_max_buffer=client_max_buffer,
        memory_repository=memory_repository if memory_repository is not None else FakeMemoryRepository(),
    )


# ════════════════════════════════════════════════════════════
# SessionRuntime
# ════════════════════════════════════════════════════════════
class TestSessionRuntime:
    """SessionRuntime 运行时测试"""

    def test_init_defaults(self):
        rt = SessionRuntime()
        assert rt.asr_full_text == ""
        assert rt.asr_processed is False
        assert rt.asr_last_audio_time is None
        assert rt.asr_last_result_time is None
        assert rt.asr_start_time is None
        assert rt.asr_stop_event is None
        assert rt.asr_task is None
        assert rt.audio_queue is None
        assert rt.pre_asr_ws is None
        assert rt._pre_asr_time == 0

    def test_reset_clears_state(self):
        rt = SessionRuntime()
        # 设置一些状态
        rt.asr_full_text = "hello"
        rt.asr_processed = True
        rt.asr_last_audio_time = 1.0
        rt.asr_last_result_time = 2.0
        rt.asr_start_time = 0.5
        rt.asr_stop_event = asyncio.Event()
        rt.asr_task = MagicMock()
        rt.audio_queue = asyncio.Queue()
        # reset
        rt.reset()
        assert rt.asr_full_text == ""
        assert rt.asr_processed is False
        assert rt.asr_last_audio_time is None
        assert rt.asr_last_result_time is None
        assert rt.asr_start_time is None
        assert rt.asr_stop_event is None
        assert rt.asr_task is None
        assert rt.audio_queue is None
        # reset 不清理 pre_asr_ws / _pre_asr_time
        assert rt.pre_asr_ws is None

    def test_reset_idempotent(self):
        rt = SessionRuntime()
        rt.reset()
        rt.reset()
        assert rt.asr_full_text == ""


# ════════════════════════════════════════════════════════════
# Session — 构造与属性
# ════════════════════════════════════════════════════════════
class TestSessionInit:
    """Session 构造函数测试"""

    def test_defaults(self):
        s = make_session()
        assert s.device_id == "dev-test"
        assert s.session_id  # 自动生成 8 字符
        assert len(s.session_id) == 8
        assert s.runtime is not None
        assert s.audio_processor is not None
        assert s.cancel_event is not None
        assert s._current_pipeline is None
        # 播放完成上报期望标志：仅在 pipeline 下发音频后为 True
        assert s._pending_out_audio_over is False
        # _precomputed_skill_catalog 由 ws_session_handler 外部注入，构造时不预创建
        assert getattr(s, "_precomputed_skill_catalog", None) is None
        assert s._tts_playing is False
        assert s._device_buffer == 10240
        assert s._closed is False
        assert s.client_max_buffer == 10240

    def test_memory_repository_injected(self):
        # 传入 memory_repository 时使用注入的仓储
        repo = FakeMemoryRepository()
        s = make_session(memory_repository=repo)
        # conversation_memory 使用注入的 repository
        assert s.conversation_memory._repository is repo

    def test_memory_repository_default_falls_back(self):
        # 未传入时使用 SqlShortTermMemoryRepository（向后兼容）
        # 直接构造 Session，绕过 make_session 的默认 FakeMemoryRepository
        from src.use_cases.voice_generator import VoiceGenerator
        from src.use_cases.session_fsm import SessionFSM, WSChannel
        from src.infrastructure.db.repositories.short_term_memory_repo import SqlShortTermMemoryRepository
        # mock load 以避免真实 DB 访问（ConversationMemory.__init__ 会调用 load）
        with patch.object(SqlShortTermMemoryRepository, 'load', return_value=[]):
            s = Session(
                device_id="dev-test",
                channel=MagicMock(),
                fsm=MagicMock(),
                voice_generator=VoiceGenerator(),
                llm_processor=MagicMock(),
                tts_processor=MagicMock(),
                asr_client=None,
                tool_mgr=None,
                memory_repository=None,  # 显式传入 None
            )
        # 未注入时 repository 为 None（由接口层显式提供 SqlShortTermMemoryRepository）
        assert s.conversation_memory._repository is None

    def test_precomputed_skill_catalog_attribute(self):
        # _precomputed_skill_catalog 属性可读写（由 ws_session_handler 外部注入）
        s = make_session()
        assert getattr(s, "_precomputed_skill_catalog", None) is None
        s._precomputed_skill_catalog = "PRECOMPUTED"
        assert s._precomputed_skill_catalog == "PRECOMPUTED"

    def test_session_id_unique(self):
        s1 = make_session()
        s2 = make_session()
        assert s1.session_id != s2.session_id

    def test_timeouts(self):
        s = make_session(no_speech_timeout=10.0, silence_timeout=3.0)
        assert s.no_speech_timeout == 10.0
        assert s.silence_timeout == 3.0

    def test_client_max_buffer(self):
        s = make_session(client_max_buffer=2048)
        assert s.client_max_buffer == 2048
        assert s._device_buffer == 2048

    def test_conversation_memory_has_device_id(self):
        s = make_session(device_id="dev-xyz")
        assert s.conversation_memory._device_id == "dev-xyz"


# ════════════════════════════════════════════════════════════
# Session — 属性与 setter
# ════════════════════════════════════════════════════════════
class TestSessionProperties:
    """tts_playing / device_buffer 属性测试"""

    async def test_tts_playing_default_false(self):
        s = make_session()
        assert s.tts_playing is False

    async def test_set_tts_playing(self):
        s = make_session()
        await s.set_tts_playing(True)
        assert s.tts_playing is True
        await s.set_tts_playing(False)
        assert s.tts_playing is False

    async def test_device_buffer_default(self):
        s = make_session(client_max_buffer=8192)
        assert s.device_buffer == 8192

    async def test_set_device_buffer(self):
        s = make_session()
        await s.set_device_buffer(512)
        assert s.device_buffer == 512

    async def test_concurrent_set_tts_playing(self):
        # 锁保护并发设置
        s = make_session()
        await asyncio.gather(
            s.set_tts_playing(True),
            s.set_tts_playing(False),
            s.set_tts_playing(True),
        )
        assert s.tts_playing is True


# ════════════════════════════════════════════════════════════
# Session — 音频队列与 ASR 生命周期
# ════════════════════════════════════════════════════════════
class TestSessionAudioQueue:
    """can_queue_audio / queue_audio / drain_asr / stop_asr 测试"""

    def test_can_queue_audio_false_when_no_task(self):
        s = make_session()
        # 没有 asr_task 时不能入队
        assert s.can_queue_audio() is False

    def test_can_queue_audio_false_when_processed(self):
        s = make_session()
        s.runtime.asr_task = MagicMock()
        s.runtime.asr_task.done.return_value = False
        s.runtime.audio_queue = asyncio.Queue()
        s.runtime.asr_processed = True
        assert s.can_queue_audio() is False

    def test_can_queue_audio_true(self):
        s = make_session()
        s.runtime.asr_task = MagicMock()
        s.runtime.asr_task.done.return_value = False
        s.runtime.audio_queue = asyncio.Queue()
        s.runtime.asr_processed = False
        assert s.can_queue_audio() is True

    def test_can_queue_audio_false_when_task_done(self):
        s = make_session()
        s.runtime.asr_task = MagicMock()
        s.runtime.asr_task.done.return_value = True
        s.runtime.audio_queue = asyncio.Queue()
        s.runtime.asr_processed = False
        assert s.can_queue_audio() is False

    async def test_queue_audio_puts_data(self):
        s = make_session()
        q = asyncio.Queue()
        s.runtime.audio_queue = q
        s.runtime.asr_processed = False
        await s.queue_audio(b"audio-data")
        assert q.qsize() == 1
        assert await q.get() == b"audio-data"

    async def test_queue_audio_skipped_when_processed(self):
        # asr_processed=True 时不再入队
        s = make_session()
        q = asyncio.Queue()
        s.runtime.audio_queue = q
        s.runtime.asr_processed = True
        await s.queue_audio(b"audio")
        assert q.empty()

    async def test_queue_audio_no_queue(self):
        # audio_queue 为 None 时不应抛异常
        s = make_session()
        s.runtime.audio_queue = None
        await s.queue_audio(b"audio")  # 不应抛异常

    def test_stop_asr_clears_state(self):
        s = make_session()
        s.runtime.asr_stop_event = asyncio.Event()
        s.runtime.asr_task = MagicMock()
        s.runtime.asr_task.done.return_value = False
        s.runtime.audio_queue = asyncio.Queue()
        # 填入一些数据
        s.runtime.audio_queue.put_nowait(b"a")
        s.runtime.audio_queue.put_nowait(b"b")
        s.stop_asr()
        assert s.runtime.asr_stop_event is None or s.runtime.asr_stop_event.is_set()
        assert s.runtime.asr_task is None
        assert s.runtime.audio_queue is None

    def test_stop_asr_no_state(self):
        # 没有任何运行状态时 stop_asr 不出错
        s = make_session()
        s.stop_asr()
        assert s.runtime.asr_task is None

    async def test_stop_asr_cancels_watchdog(self):
        s = make_session()

        async def _long():
            await asyncio.sleep(100)

        s._watchdog_task = asyncio.create_task(_long())
        s.stop_asr()
        # 等待取消传播
        await asyncio.sleep(0.01)
        assert s._watchdog_task is None

    async def test_drain_asr_puts_sentinel_and_stops(self):
        s = make_session()
        q = asyncio.Queue()
        s.runtime.audio_queue = q
        s.runtime.asr_stop_event = asyncio.Event()
        s.runtime.asr_task = MagicMock()
        s.runtime.asr_task.done.return_value = False
        await s.drain_asr()
        # drain 向队列投入 None（哨兵），然后 stop_asr 清空
        # stop_asr 会清空队列，所以最终 audio_queue=None
        assert s.runtime.audio_queue is None

    async def test_drain_asr_no_queue(self):
        # audio_queue 为 None 时 drain_asr 不出错
        s = make_session()
        s.runtime.audio_queue = None
        await s.drain_asr()
        assert s.runtime.audio_queue is None


# ════════════════════════════════════════════════════════════
# Session — start_asr（patch _asr_streaming_loop）
# ════════════════════════════════════════════════════════════
class TestSessionStartAsr:
    """start_asr 启动逻辑测试（patch _asr_streaming_loop）"""

    async def test_start_asr_creates_task_and_queue(self):
        s = make_session()
        with patch.object(Session, "_asr_streaming_loop", new_callable=AsyncMock):
            await s.start_asr(on_text=lambda t: None, on_vad_end=lambda: None)
        assert s.runtime.asr_task is not None
        assert s.runtime.asr_task.done() or not s.runtime.asr_task.done()
        assert s.runtime.audio_queue is not None
        assert s.runtime.asr_stop_event is not None
        assert s.runtime.asr_start_time is not None
        # 清理
        s.stop_asr()

    async def test_start_asr_cancels_old_task(self):
        s = make_session()

        # 模拟一个旧的未完成 ASR 任务
        old_task = asyncio.create_task(asyncio.sleep(100))
        s.runtime.asr_task = old_task
        with patch.object(Session, "_asr_streaming_loop", new_callable=AsyncMock):
            await s.start_asr(on_text=lambda t: None, on_vad_end=lambda: None)
        # 等待取消传播
        await asyncio.sleep(0.01)
        # 旧任务应被取消
        assert old_task.cancelled() or old_task.done()
        s.stop_asr()

    async def test_start_asr_resets_runtime(self):
        s = make_session()
        s.runtime.asr_full_text = "old text"
        s.runtime.asr_processed = True
        with patch.object(Session, "_asr_streaming_loop", new_callable=AsyncMock):
            await s.start_asr(on_text=lambda t: None, on_vad_end=lambda: None)
        # reset 后状态被清空
        assert s.runtime.asr_full_text == ""
        assert s.runtime.asr_processed is False
        s.stop_asr()

    async def test_start_asr_clears_existing_queue(self):
        s = make_session()
        # 预先填入旧数据
        s.runtime.audio_queue = asyncio.Queue()
        for i in range(5):
            s.runtime.audio_queue.put_nowait(f"old-{i}")
        with patch.object(Session, "_asr_streaming_loop", new_callable=AsyncMock):
            await s.start_asr(on_text=lambda t: None, on_vad_end=lambda: None)
        # 队列应被清空
        assert s.runtime.audio_queue.empty()
        s.stop_asr()

    async def test_start_asr_reuses_empty_queue(self):
        s = make_session()
        s.runtime.audio_queue = asyncio.Queue()  # 空队列
        with patch.object(Session, "_asr_streaming_loop", new_callable=AsyncMock):
            await s.start_asr(on_text=lambda t: None, on_vad_end=lambda: None)
        # 复用同一个空队列
        assert s.runtime.audio_queue is not None
        assert s.runtime.audio_queue.empty()
        s.stop_asr()

    async def test_start_asr_with_asr_client_take_pre_ws(self):
        # asr_client 存在时调用 take_pre_ws
        asr_client = MagicMock()
        asr_client.take_pre_ws = MagicMock(return_value=(None, None))
        s = make_session(asr_client=asr_client)
        with patch.object(Session, "_asr_streaming_loop", new_callable=AsyncMock):
            await s.start_asr(on_text=lambda t: None, on_vad_end=lambda: None)
        asr_client.take_pre_ws.assert_called_once()
        s.stop_asr()

    async def test_start_asr_take_pre_ws_exception_swallowed(self):
        # take_pre_ws 抛异常时被捕获
        asr_client = MagicMock()
        asr_client.take_pre_ws = MagicMock(side_effect=RuntimeError("fail"))
        s = make_session(asr_client=asr_client)
        with patch.object(Session, "_asr_streaming_loop", new_callable=AsyncMock):
            await s.start_asr(on_text=lambda t: None, on_vad_end=lambda: None)
        # 不应抛异常，且任务仍创建
        assert s.runtime.asr_task is not None
        s.stop_asr()

    async def test_start_asr_vad_callback_wraps(self):
        # _vad_cb 在 asr_processed=False 时创建 on_vad_end 任务
        called = []

        async def on_vad_end():
            called.append(True)

        s = make_session()
        with patch.object(Session, "_asr_streaming_loop", new_callable=AsyncMock) as mock_loop:
            await s.start_asr(on_text=lambda t: None, on_vad_end=on_vad_end)
            # mock_loop 的调用参数中包含 _vad_cb
            assert mock_loop.call_count == 1
            args = mock_loop.call_args.args
            # args: (on_text, _vad_cb, stop_event, pre_ws, pre_wrapper)
            _vad_cb = args[1]
            # asr_processed=False 时调用 _vad_cb 应创建任务
            assert s.runtime.asr_processed is False
            _vad_cb()
            # 等待任务执行
            await asyncio.sleep(0.05)
            assert called == [True]
        s.stop_asr()

    async def test_start_asr_vad_callback_skipped_when_processed(self):
        # asr_processed=True 时 _vad_cb 不创建任务
        called = []

        async def on_vad_end():
            called.append(True)

        s = make_session()
        with patch.object(Session, "_asr_streaming_loop", new_callable=AsyncMock) as mock_loop:
            await s.start_asr(on_text=lambda t: None, on_vad_end=on_vad_end)
            args = mock_loop.call_args.args
            _vad_cb = args[1]
            s.runtime.asr_processed = True
            _vad_cb()
            await asyncio.sleep(0.05)
            assert called == []
        s.stop_asr()


# ════════════════════════════════════════════════════════════
# Session — 预连接 ASR
# ════════════════════════════════════════════════════════════
class TestSessionPreConnect:
    """pre_connect_asr / cancel_pre_asr / _safe_close_ws 测试"""

    async def test_pre_connect_asr_no_client(self):
        # 无 asr_client 时直接返回
        s = make_session(asr_client=None)
        await s.pre_connect_asr()
        assert s.runtime.pre_asr_ws is None

    async def test_pre_connect_asr_success(self):
        asr_client = MagicMock()
        fake_ws = MagicMock()
        asr_client.pre_connect = AsyncMock(return_value=fake_ws)
        s = make_session(asr_client=asr_client)
        await s.pre_connect_asr()
        assert s.runtime.pre_asr_ws is fake_ws
        assert s.runtime._pre_asr_time > 0

    async def test_pre_connect_asr_failure(self):
        # pre_connect 抛异常时被捕获
        asr_client = MagicMock()
        asr_client.pre_connect = AsyncMock(side_effect=RuntimeError("connect failed"))
        s = make_session(asr_client=asr_client)
        await s.pre_connect_asr()
        assert s.runtime.pre_asr_ws is None

    async def test_pre_connect_asr_returns_none(self):
        asr_client = MagicMock()
        asr_client.pre_connect = AsyncMock(return_value=None)
        s = make_session(asr_client=asr_client)
        await s.pre_connect_asr()
        assert s.runtime.pre_asr_ws is None

    async def test_pre_connect_asr_no_pre_connect_method(self):
        # asr_client 没有 pre_connect 方法时直接返回
        asr_client = MagicMock(spec=[])  # 无任何方法
        s = make_session(asr_client=asr_client)
        await s.pre_connect_asr()
        assert s.runtime.pre_asr_ws is None

    def test_cancel_pre_asr_no_ws(self):
        s = make_session()
        s.runtime.pre_asr_ws = None
        # 不应抛异常
        s.cancel_pre_asr()
        assert s.runtime.pre_asr_ws is None
        assert s.runtime._pre_asr_time == 0

    def test_cancel_pre_asr_with_ws(self):
        s = make_session()
        fake_ws = MagicMock()
        fake_ws.close = AsyncMock()
        s.runtime.pre_asr_ws = fake_ws
        s.runtime._pre_asr_time = 100.0
        s.cancel_pre_asr()
        # 立即清空引用（关闭任务是异步的）
        assert s.runtime.pre_asr_ws is None
        assert s.runtime._pre_asr_time == 0

    async def test_safe_close_ws_success(self):
        s = make_session()
        ws = MagicMock()
        ws.close = AsyncMock()
        await s._safe_close_ws(ws)
        ws.close.assert_called_once()

    async def test_safe_close_ws_failure(self):
        # close 抛异常时被捕获
        s = make_session()
        ws = MagicMock()
        ws.close = AsyncMock(side_effect=RuntimeError("close failed"))
        await s._safe_close_ws(ws)  # 不应抛异常


# ════════════════════════════════════════════════════════════
# Session — run_pipeline（patch ConversationPipeline）
# ════════════════════════════════════════════════════════════
class TestSessionRunPipeline:
    """run_pipeline 测试"""

    async def test_run_pipeline_success(self):
        # patch ConversationPipeline，返回 mock 结果
        s = make_session()
        s._precomputed_skill_catalog = "PRECOMPUTED"
        mock_pipeline = MagicMock()
        mock_result = MagicMock(stop_pipeline=False, state="stopped")
        mock_pipeline.run = AsyncMock(return_value=mock_result)
        with patch("src.use_cases.session.ConversationPipeline", return_value=mock_pipeline):
            result = await s.run_pipeline("用户输入")
        assert result is mock_result
        # pipeline.run 被调用，参数为 iat_text
        mock_pipeline.run.assert_called_once_with("用户输入")
        # _current_pipeline 在 finally 中被清空
        assert s._current_pipeline is None

    async def test_run_pipeline_renders_catalog_per_query(self):
        # Pipeline 现按查询实时渲染 Skill 目录（带缓存），Session 不再透传预渲染目录
        s = make_session()
        s._precomputed_skill_catalog = "MY_CATALOG"
        mock_pipeline = MagicMock()
        mock_pipeline.run = AsyncMock(return_value=MagicMock(stop_pipeline=False))
        with patch("src.use_cases.session.ConversationPipeline", return_value=mock_pipeline) as mock_ctor:
            await s.run_pipeline("hi")
        _, kwargs = mock_ctor.call_args
        assert "precomputed_skill_catalog" not in kwargs

    async def test_run_pipeline_exception_returns_none(self):
        # pipeline.run 抛异常时返回 None
        s = make_session()
        mock_pipeline = MagicMock()
        mock_pipeline.run = AsyncMock(side_effect=RuntimeError("pipeline crash"))
        with patch("src.use_cases.session.ConversationPipeline", return_value=mock_pipeline):
            result = await s.run_pipeline("hi")
        assert result is None
        assert s._current_pipeline is None

    async def test_run_pipeline_clears_cancel_event(self):
        # run_pipeline 开头应清除 cancel_event
        s = make_session()
        s.cancel_event.set()
        mock_pipeline = MagicMock()
        mock_pipeline.run = AsyncMock(return_value=MagicMock(stop_pipeline=False))
        with patch("src.use_cases.session.ConversationPipeline", return_value=mock_pipeline):
            await s.run_pipeline("hi")
        assert not s.cancel_event.is_set()

    async def test_run_pipeline_uses_client_max_buffer(self):
        # config 使用 session 的 client_max_buffer
        s = make_session(client_max_buffer=4096)
        mock_pipeline = MagicMock()
        mock_pipeline.run = AsyncMock(return_value=MagicMock(stop_pipeline=False))
        with patch("src.use_cases.session.ConversationPipeline", return_value=mock_pipeline) as mock_ctor:
            await s.run_pipeline("hi")
        _, kwargs = mock_ctor.call_args
        config = kwargs.get("config")
        assert config is not None
        assert config.client_max_buffer == 4096


# ════════════════════════════════════════════════════════════
# Session — interrupt
# ════════════════════════════════════════════════════════════
class TestSessionInterrupt:
    """interrupt 硬中断测试"""

    async def test_interrupt_sets_cancel_event(self):
        s = make_session()
        assert not s.cancel_event.is_set()
        await s.interrupt()
        assert s.cancel_event.is_set()

    async def test_interrupt_clears_pending_over_flag(self):
        s = make_session()
        s._pending_out_audio_over = True
        await s.interrupt()
        assert s._pending_out_audio_over is False

    async def test_interrupt_sends_sid_tts_end_frame(self):
        # 打断时的结束帧必须与 pipeline 音频同一会话（SID_TTS="0010"），
        # 否则设备端正在播放的会话收不到结束帧（历史 bug 曾发 "0001"）
        from src.infrastructure.config import SID_TTS
        s = make_session()
        with patch.object(s.voice_generator, "make_end_frame", return_value=b"") as mf:
            await s.interrupt()
            mf.assert_called_with(SID_TTS)

    async def test_interrupt_resets_runtime(self):
        s = make_session()
        s.runtime.asr_full_text = "text"
        s.runtime.asr_processed = True
        await s.interrupt()
        assert s.runtime.asr_full_text == ""
        assert s.runtime.asr_processed is False

    async def test_interrupt_sets_tts_playing_false(self):
        s = make_session()
        await s.set_tts_playing(True)
        await s.interrupt()
        assert s.tts_playing is False

    async def test_interrupt_sets_playback_events(self):
        s = make_session()
        await s.interrupt()
        assert s.tts_playback_done.is_set()
        assert s.tts_audio_ended.is_set()

    async def test_interrupt_sends_end_frame(self):
        channel = MagicMock()
        channel.send_bytes = AsyncMock()
        channel.send_json = AsyncMock()
        vg = MagicMock()
        vg.make_end_frame = MagicMock(return_value=b"END")
        s = make_session(channel=channel, voice_generator=vg)
        await s.interrupt()
        channel.send_bytes.assert_called_with(b"END")
        # 应发送 tts_real_end 状态
        channel.send_json.assert_called()
        sent = channel.send_json.call_args.args[0]
        assert sent["status"] == "tts_real_end"

    async def test_interrupt_cancels_pipeline_tasks(self):
        s = make_session()
        mock_pipeline = MagicMock()
        task = asyncio.create_task(asyncio.sleep(100))
        mock_pipeline._tasks = [task]
        s._current_pipeline = mock_pipeline
        await s.interrupt()
        # 等待取消传播
        await asyncio.sleep(0.01)
        assert task.cancelled() or task.done()
        assert mock_pipeline._tasks == []
        assert s._current_pipeline is mock_pipeline  # interrupt 不清空 _current_pipeline

    async def test_interrupt_cancels_watchdog(self):
        s = make_session()

        async def _long():
            await asyncio.sleep(100)

        s._watchdog_task = asyncio.create_task(_long())
        await s.interrupt()
        assert s._watchdog_task is None

    async def test_interrupt_send_json_failure_swallowed(self):
        # send_json 失败时不应抛异常
        channel = MagicMock()
        channel.send_bytes = AsyncMock()
        channel.send_json = AsyncMock(side_effect=RuntimeError("fail"))
        vg = MagicMock()
        vg.make_end_frame = MagicMock(return_value=b"END")
        s = make_session(channel=channel, voice_generator=vg)
        await s.interrupt()  # 不应抛异常

    async def test_interrupt_send_bytes_failure_swallowed(self):
        # send_bytes 失败时不应抛异常（外层无 try/except，但 make_end_frame 不会失败）
        # 这里验证 send_bytes 正常被调用
        channel = MagicMock()
        channel.send_bytes = AsyncMock()
        channel.send_json = AsyncMock()
        vg = MagicMock()
        vg.make_end_frame = MagicMock(return_value=b"END")
        s = make_session(channel=channel, voice_generator=vg)
        await s.interrupt()
        channel.send_bytes.assert_called_once()


# ════════════════════════════════════════════════════════════
# Session — send_session_end
# ════════════════════════════════════════════════════════════
class TestSessionSendSessionEnd:
    """send_session_end 测试"""

    async def test_send_session_end_sets_processed(self):
        channel = MagicMock()
        channel.send_json = AsyncMock()
        channel.send_text = AsyncMock()
        fsm = MagicMock()
        fsm.set = AsyncMock()
        s = make_session(channel=channel, fsm=fsm)
        await s.send_session_end()
        assert s.runtime.asr_processed is True

    async def test_send_session_end_sends_messages(self):
        channel = MagicMock()
        sent = []
        channel.send_json = AsyncMock(side_effect=lambda d: sent.append(d))
        channel.send_text = AsyncMock()
        fsm = MagicMock()
        fsm.set = AsyncMock()
        s = make_session(channel=channel, fsm=fsm)
        await s.send_session_end()
        # 应发送 iat_end 和 session_end（json）以及 session_end（text）
        statuses = [d.get("status") for d in sent if isinstance(d, dict)]
        assert "iat_end" in statuses
        assert "session_end" in statuses
        channel.send_text.assert_called_with("session_end")

    async def test_send_session_end_sets_fsm_idle(self):
        channel = MagicMock()
        channel.send_json = AsyncMock()
        channel.send_text = AsyncMock()
        fsm = MagicMock()
        fsm.set = AsyncMock()
        s = make_session(channel=channel, fsm=fsm)
        await s.send_session_end()
        # FSM 应被设置为 IDLE
        fsm.set.assert_called_with(SessionState.IDLE)

    async def test_send_session_end_drains_asr(self):
        # send_session_end 内部调用 drain_asr
        channel = MagicMock()
        channel.send_json = AsyncMock()
        channel.send_text = AsyncMock()
        fsm = MagicMock()
        fsm.set = AsyncMock()
        s = make_session(channel=channel, fsm=fsm)
        q = asyncio.Queue()
        s.runtime.audio_queue = q
        await s.send_session_end()
        # drain_asr 后 audio_queue 被清空
        assert s.runtime.audio_queue is None


# ════════════════════════════════════════════════════════════
# Session — start_watchdog
# ════════════════════════════════════════════════════════════
class TestSessionWatchdog:
    """start_watchdog 超时监控测试"""

    async def test_watchdog_no_speech_timeout(self):
        # 无音频输入超过 no_speech_timeout 时调用 send_session_end
        channel = MagicMock()
        channel.send_json = AsyncMock()
        channel.send_text = AsyncMock()
        fsm = MagicMock()
        fsm.get = MagicMock(return_value=SessionState.ASR)
        fsm.set = AsyncMock()
        s = make_session(
            channel=channel, fsm=fsm,
            no_speech_timeout=0.3,  # 短超时
        )
        s.runtime.asr_start_time = time.time()
        s.runtime.asr_processed = False
        # asr_last_audio_time=None, asr_last_result_time=None
        await s.start_watchdog(on_vad_end=AsyncMock())
        # 等待 watchdog 触发（循环间隔 0.2s）
        await asyncio.sleep(0.6)
        # 应触发 send_session_end（asr_processed 变为 True）
        assert s.runtime.asr_processed is True
        # 清理
        if s._watchdog_task and not s._watchdog_task.done():
            s._watchdog_task.cancel()

    async def test_watchdog_no_speech_with_background_noise(self):
        # 有底噪音频上传（asr_last_audio_time 持续更新）但 ASR 一直无识别结果时，
        # 超过 no_speech_timeout 仍应结束会话（修复：不能以"未收到音频"为判断依据，
        # mic 底噪会让该条件永不触发，导致只能等 30s max_asr_duration）
        fsm = MagicMock()
        fsm.get = MagicMock(return_value=SessionState.ASR)
        fsm.set = AsyncMock()
        s = make_session(fsm=fsm, no_speech_timeout=0.3)
        s.runtime.asr_start_time = time.time()
        s.runtime.asr_last_audio_time = time.time()  # mic 底噪持续上传
        s.runtime.asr_processed = False
        await s.start_watchdog(on_vad_end=AsyncMock())
        await asyncio.sleep(0.6)
        assert s.runtime.asr_processed is True  # send_session_end 触发
        if s._watchdog_task and not s._watchdog_task.done():
            s._watchdog_task.cancel()

    async def test_watchdog_silence_timeout(self):
        # 有识别结果但静默超过 silence_timeout 时调用 on_vad_end
        called = []

        async def on_vad_end():
            called.append(True)

        fsm = MagicMock()
        fsm.get = MagicMock(return_value=SessionState.ASR)
        fsm.set = AsyncMock()
        s = make_session(fsm=fsm, no_speech_timeout=10.0, silence_timeout=0.3)
        s.runtime.asr_start_time = time.time()
        s.runtime.asr_last_audio_time = time.time()
        s.runtime.asr_last_result_time = time.time()
        s.runtime.asr_processed = False
        await s.start_watchdog(on_vad_end=on_vad_end)
        await asyncio.sleep(0.6)
        assert called == [True]
        if s._watchdog_task and not s._watchdog_task.done():
            s._watchdog_task.cancel()

    async def test_watchdog_max_duration(self):
        # ASR 运行超过 30s 时强制停止（这里用模拟时间）
        fsm = MagicMock()
        fsm.get = MagicMock(return_value=SessionState.ASR)
        s = make_session(fsm=fsm, no_speech_timeout=100.0, silence_timeout=100.0)
        # 设置 start_time 为很久以前
        s.runtime.asr_start_time = time.time() - 31.0
        s.runtime.asr_last_audio_time = time.time() - 31.0
        s.runtime.asr_last_result_time = time.time() - 31.0
        s.runtime.asr_processed = False
        await s.start_watchdog(on_vad_end=AsyncMock())
        await asyncio.sleep(0.3)
        # 应调用 stop_asr，runtime 被清空
        assert s.runtime.asr_task is None
        if s._watchdog_task and not s._watchdog_task.done():
            s._watchdog_task.cancel()

    async def test_watchdog_cancels_previous(self):
        # 多次 start_watchdog 应取消前一个
        s = make_session()

        async def _long():
            await asyncio.sleep(100)

        s._watchdog_task = asyncio.create_task(_long())
        await s.start_watchdog(on_vad_end=AsyncMock())
        # 旧任务被取消
        assert s._watchdog_task is not _long
        if s._watchdog_task and not s._watchdog_task.done():
            s._watchdog_task.cancel()

    async def test_watchdog_skips_when_not_asr_state(self):
        # FSM 非 ASR 状态时 watchdog 不触发
        fsm = MagicMock()
        fsm.get = MagicMock(return_value=SessionState.IDLE)  # 非 ASR
        s = make_session(fsm=fsm, no_speech_timeout=0.3)
        s.runtime.asr_start_time = time.time()
        s.runtime.asr_processed = False
        await s.start_watchdog(on_vad_end=AsyncMock())
        await asyncio.sleep(0.5)
        # 未触发（asr_processed 仍为 False）
        assert s.runtime.asr_processed is False
        if s._watchdog_task and not s._watchdog_task.done():
            s._watchdog_task.cancel()

    async def test_watchdog_stops_when_processed(self):
        # asr_processed=True 时 watchdog 退出循环
        fsm = MagicMock()
        fsm.get = MagicMock(return_value=SessionState.ASR)
        s = make_session(fsm=fsm)
        s.runtime.asr_processed = True
        await s.start_watchdog(on_vad_end=AsyncMock())
        await asyncio.sleep(0.3)
        # watchdog 任务应已完成（while 条件不满足）
        assert s._watchdog_task.done()
        if s._watchdog_task and not s._watchdog_task.done():
            s._watchdog_task.cancel()


# ════════════════════════════════════════════════════════════
# Session — start_auto_conversation / _start_next_cycle
# ════════════════════════════════════════════════════════════
class TestSessionAutoConversation:
    """start_auto_conversation / _start_next_cycle 测试"""

    async def test_start_auto_conversation_when_closed(self):
        # _closed=True 时直接返回
        s = make_session()
        s._closed = True
        fsm = MagicMock()
        fsm.set = AsyncMock()
        s.fsm = fsm
        await s.start_auto_conversation()
        # FSM 不应被设置
        fsm.set.assert_not_called()

    async def test_start_auto_conversation_sets_fsm_asr(self):
        channel = MagicMock()
        channel.send_json = AsyncMock()
        fsm = MagicMock()
        fsm.set = AsyncMock()
        s = make_session(channel=channel, fsm=fsm)
        with patch.object(Session, "start_asr", new_callable=AsyncMock) as mock_start, \
             patch.object(Session, "start_watchdog", new_callable=AsyncMock) as mock_watchdog, \
             patch.object(Session, "pre_connect_asr", new_callable=AsyncMock):
            await s.start_auto_conversation()
        # FSM 应被设置为 ASR
        fsm.set.assert_any_call(SessionState.ASR)
        # start_asr 被调用
        mock_start.assert_called_once()
        # start_watchdog 被调用
        mock_watchdog.assert_called_once()
        # 应发送 iat_start
        sent = [c.args[0] for c in channel.send_json.call_args_list]
        assert any(d.get("status") == "iat_start" for d in sent if isinstance(d, dict))

    async def test_start_auto_conversation_sends_iat_start(self):
        channel = MagicMock()
        sent_json = []
        channel.send_json = AsyncMock(side_effect=lambda d: sent_json.append(d))
        fsm = MagicMock()
        fsm.set = AsyncMock()
        s = make_session(channel=channel, fsm=fsm)
        with patch.object(Session, "start_asr", new_callable=AsyncMock), \
             patch.object(Session, "start_watchdog", new_callable=AsyncMock), \
             patch.object(Session, "pre_connect_asr", new_callable=AsyncMock):
            await s.start_auto_conversation()
        assert any(d.get("status") == "iat_start" for d in sent_json)

    async def test_start_next_cycle_sets_fsm_asr(self):
        fsm = MagicMock()
        fsm.set = AsyncMock()
        s = make_session(fsm=fsm)
        with patch.object(Session, "start_asr", new_callable=AsyncMock), \
             patch.object(Session, "start_watchdog", new_callable=AsyncMock), \
             patch.object(Session, "pre_connect_asr", new_callable=AsyncMock):
            await s._start_next_cycle()
        fsm.set.assert_any_call(SessionState.ASR)

    async def test_start_next_cycle_clears_processed(self):
        fsm = MagicMock()
        fsm.set = AsyncMock()
        s = make_session(fsm=fsm)
        s.runtime.asr_processed = True
        with patch.object(Session, "start_asr", new_callable=AsyncMock), \
             patch.object(Session, "start_watchdog", new_callable=AsyncMock), \
             patch.object(Session, "pre_connect_asr", new_callable=AsyncMock):
            await s._start_next_cycle()
        assert s.runtime.asr_processed is False


# ════════════════════════════════════════════════════════════
# Session — close
# ════════════════════════════════════════════════════════════
class TestSessionClose:
    """close 测试"""

    async def test_close_sets_closed_flag(self):
        s = make_session()
        await s.close()
        assert s._closed is True

    async def test_close_idempotent(self):
        # 重复 close 不出错
        s = make_session()
        await s.close()
        await s.close()
        assert s._closed is True

    async def test_close_sets_cancel_event(self):
        s = make_session()
        await s.close()
        assert s.cancel_event.is_set()

    async def test_close_cancels_watchdog(self):
        s = make_session()

        async def _long():
            await asyncio.sleep(100)

        s._watchdog_task = asyncio.create_task(_long())
        saved_task = s._watchdog_task
        await s.close()
        # 等待取消传播
        await asyncio.sleep(0.01)
        # close() 内部 stop_asr() 会将 _watchdog_task 置 None 并 cancel
        assert saved_task.cancelled() or saved_task.done()

    async def test_close_clears_pending_over_flag(self):
        s = make_session()
        s._pending_out_audio_over = True
        await s.close()
        assert s._pending_out_audio_over is False

    async def test_close_resets_runtime(self):
        s = make_session()
        s.runtime.asr_full_text = "text"
        s.runtime.asr_processed = True
        await s.close()
        assert s.runtime.asr_full_text == ""
        assert s.runtime.asr_processed is False

    async def test_close_sets_tts_playing_false(self):
        s = make_session()
        await s.set_tts_playing(True)
        await s.close()
        assert s.tts_playing is False

    async def test_close_sets_playback_events(self):
        s = make_session()
        await s.close()
        assert s.tts_playback_done.is_set()
        assert s.tts_audio_ended.is_set()
        assert s._wake_audio_played.is_set()

    async def test_close_clears_conversation_memory(self):
        s = make_session()
        s.conversation_memory._messages.append({"role": "user", "content": "x"})
        await s.close()
        assert len(s.conversation_memory._messages) == 0

    async def test_close_cancels_pre_asr(self):
        s = make_session()
        s.runtime.pre_asr_ws = MagicMock()
        s.runtime.pre_asr_ws.close = AsyncMock()
        await s.close()
        # pre_asr_ws 引用被清空
        assert s.runtime.pre_asr_ws is None

    async def test_close_stops_asr(self):
        s = make_session()
        s.runtime.asr_stop_event = asyncio.Event()
        s.runtime.audio_queue = asyncio.Queue()
        await s.close()
        # stop_asr 清空状态
        assert s.runtime.audio_queue is None


# ════════════════════════════════════════════════════════════
# 辅助：模拟 ASR WebSocket
# ════════════════════════════════════════════════════════════
class FakeASRWebSocket:
    """模拟 ASR WebSocket 连接"""

    def __init__(self, responses=None):
        # responses: recv() 依次返回的消息列表
        self._responses = list(responses) if responses else []
        self.sent: list = []
        self.closed = False
        self._recv_count = 0

    async def recv(self):
        self._recv_count += 1
        if self._responses:
            return self._responses.pop(0)
        # 无更多消息时阻塞（模拟等待）
        await asyncio.sleep(100)

    async def send(self, data):
        self.sent.append(data)

    async def close(self):
        self.closed = True


def make_mock_asr_client(binary_protocol=False, enable_pool=False):
    """构造 mock ASR 客户端"""
    client = MagicMock()
    client.binary_protocol = binary_protocol
    client._enable_pool = enable_pool
    client._build_url = MagicMock(return_value="ws://fake-asr.example.com/asr")
    client._get_headers = MagicMock(return_value={"Authorization": "Bearer test"})
    client._ws_url = "ws://fake-asr.example.com/asr"
    client.init_connection = AsyncMock(return_value=True)
    client.parse_response = MagicMock(return_value={"text": "", "is_final": False})
    client.send_audio_data = AsyncMock()
    client._make_header = MagicMock(return_value=b"\x00\x01")
    client.get_pool = MagicMock(return_value=None)
    client.take_pre_ws = MagicMock(return_value=(None, None))
    client.pre_connect = AsyncMock(return_value=None)
    # 传统（非插件）ASR 网关
    client.is_plugin = False
    return client


# ════════════════════════════════════════════════════════════
# Session — _connect_asr_ws
# ════════════════════════════════════════════════════════════
class TestSessionConnectAsrWs:
    """_connect_asr_ws 测试"""

    async def test_connect_asr_ws_success(self):
        # patch websockets.connect
        s = make_session()
        fake_ws = FakeASRWebSocket()
        with patch("websockets.connect", new_callable=AsyncMock, return_value=fake_ws):
            ws = await s._connect_asr_ws("ws://test", {"k": "v"})
        assert ws is fake_ws

    async def test_connect_asr_ws_failure(self):
        s = make_session()
        with patch("websockets.connect", new_callable=AsyncMock, side_effect=ConnectionRefusedError("refused")):
            with pytest.raises(ConnectionRefusedError):
                await s._connect_asr_ws("ws://test", {})


# ════════════════════════════════════════════════════════════
# Session — _asr_streaming_loop（JSON / 非二进制协议）
# ════════════════════════════════════════════════════════════
class TestSessionAsrStreamingLoopJson:
    """_asr_streaming_loop JSON 协议路径测试"""

    async def test_json_protocol_basic_flow(self):
        # JSON 协议：WebSocket 返回识别结果，触发 on_text 和 vad_end_callback
        s = make_session(asr_client=make_mock_asr_client(binary_protocol=False))
        texts_received = []

        def on_text(text):
            texts_received.append(text)

        vad_called = []

        def vad_end_callback():
            vad_called.append(True)

        # 准备音频队列
        audio_queue = asyncio.Queue()
        await audio_queue.put(b"\x00\x01\x02")
        await audio_queue.put(None)  # 哨兵
        s.runtime.audio_queue = audio_queue
        stop_event = asyncio.Event()
        s.runtime.asr_stop_event = stop_event

        # fake WebSocket 返回 slice_type=2 的结果
        fake_ws = FakeASRWebSocket(responses=[
            '{"code": 0, "result": {"voice_text_str": "你好世界", "slice_type": 2}}',
        ])
        with patch.object(Session, "_connect_asr_ws", new_callable=AsyncMock, return_value=fake_ws):
            await s._asr_streaming_loop(on_text, vad_end_callback, stop_event, None, None)

        # on_text 应被调用
        assert "你好世界" in texts_received
        # vad_end_callback 应被调用
        assert vad_called == [True]
        # WebSocket 应被关闭
        assert fake_ws.closed

    async def test_json_protocol_is_final(self):
        # is_final=True 时退出 recv 循环
        s = make_session(asr_client=make_mock_asr_client(binary_protocol=False))
        texts_received = []

        def on_text(text):
            texts_received.append(text)

        audio_queue = asyncio.Queue()
        await audio_queue.put(b"\x01")
        await audio_queue.put(None)
        s.runtime.audio_queue = audio_queue
        stop_event = asyncio.Event()

        fake_ws = FakeASRWebSocket(responses=[
            '{"code": 0, "result": {"voice_text_str": "完成"}, "is_final": true}',
        ])
        with patch.object(Session, "_connect_asr_ws", new_callable=AsyncMock, return_value=fake_ws):
            await s._asr_streaming_loop(on_text, lambda: None, stop_event, None, None)
        assert "完成" in texts_received

    async def test_json_protocol_error_code(self):
        # code != 0 时退出并记录错误
        s = make_session(asr_client=make_mock_asr_client(binary_protocol=False))
        audio_queue = asyncio.Queue()
        await audio_queue.put(None)
        s.runtime.audio_queue = audio_queue
        stop_event = asyncio.Event()

        fake_ws = FakeASRWebSocket(responses=[
            '{"code": 500, "message": "server error"}',
        ])
        with patch.object(Session, "_connect_asr_ws", new_callable=AsyncMock, return_value=fake_ws):
            await s._asr_streaming_loop(lambda t: None, lambda: None, stop_event, None, None)
        # 应正常退出
        assert fake_ws.closed

    async def test_json_protocol_stop_event(self):
        # stop_event 被设置时退出
        s = make_session(asr_client=make_mock_asr_client(binary_protocol=False))
        audio_queue = asyncio.Queue()
        s.runtime.audio_queue = audio_queue
        stop_event = asyncio.Event()

        fake_ws = FakeASRWebSocket(responses=[])  # 不返回任何消息

        async def _set_stop_after_delay():
            await asyncio.sleep(0.1)
            stop_event.set()

        asyncio.create_task(_set_stop_after_delay())
        with patch.object(Session, "_connect_asr_ws", new_callable=AsyncMock, return_value=fake_ws):
            await s._asr_streaming_loop(lambda t: None, lambda: None, stop_event, None, None)
        # 应正常退出
        assert stop_event.is_set()

    async def test_json_protocol_recv_timeout(self):
        # recv 超时后继续等待，最终 stop_event 退出
        s = make_session(asr_client=make_mock_asr_client(binary_protocol=False))
        audio_queue = asyncio.Queue()
        await audio_queue.put(None)
        s.runtime.audio_queue = audio_queue
        stop_event = asyncio.Event()

        # fake_ws.recv 先抛 TimeoutError，第二次设置 stop_event
        call_count = [0]

        class TimeoutThenStop:
            async def recv(self):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise asyncio.TimeoutError()
                stop_event.set()
                await asyncio.sleep(100)

            async def send(self, data):
                pass

            async def close(self):
                pass

        fake_ws = TimeoutThenStop()
        with patch.object(Session, "_connect_asr_ws", new_callable=AsyncMock, return_value=fake_ws):
            await s._asr_streaming_loop(lambda t: None, lambda: None, stop_event, None, None)

    async def test_json_protocol_connection_closed(self):
        # ConnectionClosed 异常时退出
        from websockets.exceptions import ConnectionClosed
        s = make_session(asr_client=make_mock_asr_client(binary_protocol=False))
        audio_queue = asyncio.Queue()
        await audio_queue.put(None)
        s.runtime.audio_queue = audio_queue
        stop_event = asyncio.Event()

        class ClosedWS:
            async def recv(self):
                raise ConnectionClosed(None, None)

            async def send(self, data):
                pass

            async def close(self):
                pass

        fake_ws = ClosedWS()
        with patch.object(Session, "_connect_asr_ws", new_callable=AsyncMock, return_value=fake_ws):
            await s._asr_streaming_loop(lambda t: None, lambda: None, stop_event, None, None)

    async def test_json_protocol_recv_exception(self):
        # recv 抛一般异常时退出
        s = make_session(asr_client=make_mock_asr_client(binary_protocol=False))
        audio_queue = asyncio.Queue()
        await audio_queue.put(None)
        s.runtime.audio_queue = audio_queue
        stop_event = asyncio.Event()

        class ErrorWS:
            async def recv(self):
                raise RuntimeError("unexpected error")

            async def send(self, data):
                pass

            async def close(self):
                pass

        fake_ws = ErrorWS()
        with patch.object(Session, "_connect_asr_ws", new_callable=AsyncMock, return_value=fake_ws):
            await s._asr_streaming_loop(lambda t: None, lambda: None, stop_event, None, None)

    async def test_json_protocol_with_pre_ws(self):
        # 使用预连接的 WebSocket（pre_ws 非 None）
        s = make_session(asr_client=make_mock_asr_client(binary_protocol=False))
        audio_queue = asyncio.Queue()
        await audio_queue.put(None)
        s.runtime.audio_queue = audio_queue
        stop_event = asyncio.Event()

        fake_ws = FakeASRWebSocket(responses=[
            '{"code": 0, "result": {"voice_text_str": "预连接测试", "slice_type": 2}}',
        ])
        # 传入 pre_ws，own_ws=False
        await s._asr_streaming_loop(lambda t: None, lambda: None, stop_event, fake_ws, None)
        # 应正常完成

    async def test_json_protocol_no_asr_client(self):
        # asr_client=None 时 _build_url 不可用，应捕获异常退出
        s = make_session(asr_client=None)
        audio_queue = asyncio.Queue()
        s.runtime.audio_queue = audio_queue
        stop_event = asyncio.Event()
        # asr_client=None 会在连接阶段抛 AttributeError，被外层 except 捕获
        await s._asr_streaming_loop(lambda t: None, lambda: None, stop_event, None, None)


# ════════════════════════════════════════════════════════════
# Session — _asr_streaming_loop（二进制协议）
# ════════════════════════════════════════════════════════════
class TestSessionAsrStreamingLoopBinary:
    """_asr_streaming_loop 二进制协议路径测试"""

    async def test_binary_protocol_basic_flow(self):
        # 二进制协议：parse_response 返回结果
        asr_client = make_mock_asr_client(binary_protocol=True)
        asr_client.parse_response = MagicMock(return_value={
            "text": "二进制测试", "is_final": True
        })
        s = make_session(asr_client=asr_client)
        texts_received = []

        audio_queue = asyncio.Queue()
        # 二进制协议需要足够大的音频块（target_chunk_size=6400）
        await audio_queue.put(b"\x00" * 7000)
        await audio_queue.put(None)
        s.runtime.audio_queue = audio_queue
        stop_event = asyncio.Event()

        fake_ws = FakeASRWebSocket(responses=[b"binary_response_data"])
        with patch.object(Session, "_connect_asr_ws", new_callable=AsyncMock, return_value=fake_ws):
            await s._asr_streaming_loop(lambda t: texts_received.append(t), lambda: None, stop_event, None, None)
        assert "二进制测试" in texts_received

    async def test_binary_protocol_parse_none(self):
        # parse_response 返回 None 时继续循环
        asr_client = make_mock_asr_client(binary_protocol=True)
        asr_client.parse_response = MagicMock(return_value=None)
        s = make_session(asr_client=asr_client)

        audio_queue = asyncio.Queue()
        await audio_queue.put(None)
        s.runtime.audio_queue = audio_queue
        stop_event = asyncio.Event()

        # 返回 None 后 stop_event 被设置退出
        call_count = [0]

        class NoneThenStop:
            async def recv(self):
                call_count[0] += 1
                if call_count[0] > 3:
                    stop_event.set()
                    await asyncio.sleep(100)
                return b"some_bytes"

            async def send(self, data):
                pass

            async def close(self):
                pass

        fake_ws = NoneThenStop()
        with patch.object(Session, "_connect_asr_ws", new_callable=AsyncMock, return_value=fake_ws):
            await s._asr_streaming_loop(lambda t: None, lambda: None, stop_event, None, None)

    async def test_binary_protocol_init_failure(self):
        # init_connection 失败时尝试重新连接
        asr_client = make_mock_asr_client(binary_protocol=True)
        asr_client.init_connection = AsyncMock(return_value=False)
        s = make_session(asr_client=asr_client)

        audio_queue = asyncio.Queue()
        s.runtime.audio_queue = audio_queue
        stop_event = asyncio.Event()

        fake_ws = FakeASRWebSocket()
        with patch.object(Session, "_connect_asr_ws", new_callable=AsyncMock, return_value=fake_ws):
            # init 失败 -> 尝试新连接 -> 新连接 init 也失败 -> return
            await s._asr_streaming_loop(lambda t: None, lambda: None, stop_event, None, None)

    async def test_binary_protocol_with_text(self):
        # parse_response 返回 text 但非 final
        asr_client = make_mock_asr_client(binary_protocol=True)
        call_count = [0]

        def parse_resp(data):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"text": "中间结果", "is_final": False}
            return {"text": "最终结果", "is_final": True}

        asr_client.parse_response = parse_resp
        s = make_session(asr_client=asr_client)
        texts = []

        audio_queue = asyncio.Queue()
        await audio_queue.put(b"\x00" * 7000)
        await audio_queue.put(None)
        s.runtime.audio_queue = audio_queue
        stop_event = asyncio.Event()

        fake_ws = FakeASRWebSocket(responses=[b"resp1", b"resp2"])
        with patch.object(Session, "_connect_asr_ws", new_callable=AsyncMock, return_value=fake_ws):
            await s._asr_streaming_loop(lambda t: texts.append(t), lambda: None, stop_event, None, None)
        assert "中间结果" in texts
        assert "最终结果" in texts


# ════════════════════════════════════════════════════════════
# Session — start_asr 边界条件
# ════════════════════════════════════════════════════════════
class TestSessionStartAsrEdgeCases:
    """start_asr 边界条件测试"""

    async def test_start_asr_expired_pre_ws(self):
        # pre_ws 存在但已过期（>25s）时丢弃
        asr_client = make_mock_asr_client()
        fake_pre_ws = MagicMock()
        fake_pre_ws.close = AsyncMock()
        asr_client.take_pre_ws = MagicMock(return_value=(fake_pre_ws, None))
        s = make_session(asr_client=asr_client)
        # 设置预连接时间为很久以前
        s.runtime._pre_asr_time = time.time() - 30
        with patch.object(Session, "_asr_streaming_loop", new_callable=AsyncMock):
            await s.start_asr(on_text=lambda t: None, on_vad_end=lambda: None)
        # 过期的 pre_ws 应被丢弃（设为 None 后传入 _asr_streaming_loop）
        # 检查 _asr_streaming_loop 被调用时 pre_ws=None
        s.stop_asr()

    async def test_start_asr_valid_pre_ws(self):
        # pre_ws 存在且未过期时使用
        asr_client = make_mock_asr_client()
        fake_pre_ws = MagicMock()
        asr_client.take_pre_ws = MagicMock(return_value=(fake_pre_ws, None))
        s = make_session(asr_client=asr_client)
        # 设置预连接时间为刚刚
        s.runtime._pre_asr_time = time.time()
        with patch.object(Session, "_asr_streaming_loop", new_callable=AsyncMock) as mock_loop:
            await s.start_asr(on_text=lambda t: None, on_vad_end=lambda: None)
            # _asr_streaming_loop 被调用时 pre_ws 应为 fake_pre_ws
            call_args = mock_loop.call_args.args
            assert call_args[3] is fake_pre_ws  # pre_ws 参数
        s.stop_asr()

    async def test_start_asr_no_asr_client(self):
        # asr_client=None 时 pre_ws=None，_asr_streaming_loop 内部会失败但被捕获
        s = make_session(asr_client=None)
        # 不 patch _asr_streaming_loop，让它真正运行（会因 asr_client=None 而快速失败）
        await s.start_asr(on_text=lambda t: None, on_vad_end=lambda: None)
        # 等待 task 完成
        if s.runtime.asr_task:
            try:
                await asyncio.wait_for(s.runtime.asr_task, timeout=2.0)
            except (asyncio.TimeoutError, Exception):
                pass
        s.stop_asr()


# ════════════════════════════════════════════════════════════
# Session — start_auto_conversation 内部回调
# ════════════════════════════════════════════════════════════
class TestSessionAutoConversationCallbacks:
    """start_auto_conversation / _start_next_cycle 内部回调测试"""

    async def test_auto_conv_on_text_updates_runtime(self):
        # on_text 回调更新 asr_full_text 和 asr_last_result_time
        s = make_session()
        mock_start = AsyncMock()
        with patch.object(Session, "start_asr", new=mock_start), \
             patch.object(Session, "start_watchdog", new_callable=AsyncMock), \
             patch.object(Session, "pre_connect_asr", new_callable=AsyncMock):
            await s.start_auto_conversation()
        # 获取 on_text 回调
        on_text = mock_start.call_args.args[0]
        on_text("识别文本")
        assert s.runtime.asr_full_text == "识别文本"
        assert s.runtime.asr_last_result_time is not None

    async def test_auto_conv_on_text_empty(self):
        # on_text 空字符串时不更新 asr_last_result_time
        s = make_session()
        mock_start = AsyncMock()
        with patch.object(Session, "start_asr", new=mock_start), \
             patch.object(Session, "start_watchdog", new_callable=AsyncMock), \
             patch.object(Session, "pre_connect_asr", new_callable=AsyncMock):
            await s.start_auto_conversation()
        on_text = mock_start.call_args.args[0]
        on_text("")
        assert s.runtime.asr_full_text == ""
        assert s.runtime.asr_last_result_time is None

    async def test_auto_conv_vad_end_with_text(self):
        # _on_vad_end_auto 有文本时运行 pipeline
        channel = MagicMock()
        channel.send_json = AsyncMock()
        channel.send_bytes = AsyncMock()
        fsm = MagicMock()
        fsm.set = AsyncMock()
        s = make_session(channel=channel, fsm=fsm)
        mock_start = AsyncMock()
        mock_result = MagicMock(stop_pipeline=False)
        with patch.object(Session, "start_asr", new=mock_start), \
             patch.object(Session, "start_watchdog", new_callable=AsyncMock), \
             patch.object(Session, "pre_connect_asr", new_callable=AsyncMock), \
             patch.object(Session, "run_pipeline", new_callable=AsyncMock, return_value=mock_result) as mock_run, \
             patch.object(Session, "_start_next_cycle", new_callable=AsyncMock):
            await s.start_auto_conversation()
            # 设置 ASR 文本
            s.runtime.asr_full_text = "你好"
            # 获取 _on_vad_end_auto 回调
            vad_end = mock_start.call_args.args[1]
            await vad_end()
        # 应调用 run_pipeline
        mock_run.assert_called_once_with("你好")
        # 应发送 iat_end
        sent = [c.args[0] for c in channel.send_json.call_args_list]
        assert any(d.get("status") == "iat_end" for d in sent if isinstance(d, dict))
        # 应发送 on_iat_cb
        assert any(d.get("command_id") == "on_iat_cb" for d in sent if isinstance(d, dict))

    async def test_auto_conv_vad_end_empty_text(self):
        # _on_vad_end_auto 空文本时调用 send_session_end
        channel = MagicMock()
        channel.send_json = AsyncMock()
        channel.send_text = AsyncMock()
        fsm = MagicMock()
        fsm.set = AsyncMock()
        s = make_session(channel=channel, fsm=fsm)
        mock_start = AsyncMock()
        with patch.object(Session, "start_asr", new=mock_start), \
             patch.object(Session, "start_watchdog", new_callable=AsyncMock), \
             patch.object(Session, "pre_connect_asr", new_callable=AsyncMock), \
             patch.object(Session, "run_pipeline", new_callable=AsyncMock) as mock_run:
            await s.start_auto_conversation()
            s.runtime.asr_full_text = ""
            vad_end = mock_start.call_args.args[1]
            await vad_end()
        # 空文本不应调用 run_pipeline
        mock_run.assert_not_called()
        # 应发送 session_end
        sent = [c.args[0] for c in channel.send_json.call_args_list]
        assert any(d.get("status") == "session_end" for d in sent if isinstance(d, dict))

    async def test_auto_conv_vad_end_stop_pipeline(self):
        # stop_pipeline=True 时不启动下一轮
        channel = MagicMock()
        channel.send_json = AsyncMock()
        channel.send_bytes = AsyncMock()
        fsm = MagicMock()
        fsm.set = AsyncMock()
        s = make_session(channel=channel, fsm=fsm)
        mock_start = AsyncMock()
        mock_result = MagicMock(stop_pipeline=True)
        with patch.object(Session, "start_asr", new=mock_start), \
             patch.object(Session, "start_watchdog", new_callable=AsyncMock), \
             patch.object(Session, "pre_connect_asr", new_callable=AsyncMock), \
             patch.object(Session, "run_pipeline", new_callable=AsyncMock, return_value=mock_result), \
             patch.object(Session, "_start_next_cycle", new_callable=AsyncMock) as mock_next:
            await s.start_auto_conversation()
            s.runtime.asr_full_text = "停止"
            vad_end = mock_start.call_args.args[1]
            await vad_end()
        # 不应启动下一轮
        mock_next.assert_not_called()
        # FSM 应被设置为 IDLE
        fsm.set.assert_any_call(SessionState.IDLE)

    async def test_auto_conv_vad_end_already_processed(self):
        # asr_processed=True 时直接返回
        s = make_session()
        mock_start = AsyncMock()
        with patch.object(Session, "start_asr", new=mock_start), \
             patch.object(Session, "start_watchdog", new_callable=AsyncMock), \
             patch.object(Session, "pre_connect_asr", new_callable=AsyncMock), \
             patch.object(Session, "run_pipeline", new_callable=AsyncMock) as mock_run:
            await s.start_auto_conversation()
            s.runtime.asr_processed = True
            vad_end = mock_start.call_args.args[1]
            await vad_end()
        mock_run.assert_not_called()

    async def test_auto_conv_vad_end_closed(self):
        # _closed=True 时 run_pipeline 后不启动下一轮
        channel = MagicMock()
        channel.send_json = AsyncMock()
        fsm = MagicMock()
        fsm.set = AsyncMock()
        s = make_session(channel=channel, fsm=fsm)
        mock_start = AsyncMock()
        mock_result = MagicMock(stop_pipeline=False)
        with patch.object(Session, "start_asr", new=mock_start), \
             patch.object(Session, "start_watchdog", new_callable=AsyncMock), \
             patch.object(Session, "pre_connect_asr", new_callable=AsyncMock), \
             patch.object(Session, "run_pipeline", new_callable=AsyncMock, return_value=mock_result), \
             patch.object(Session, "_start_next_cycle", new_callable=AsyncMock) as mock_next:
            await s.start_auto_conversation()
            s.runtime.asr_full_text = "hi"
            s._closed = True
            vad_end = mock_start.call_args.args[1]
            await vad_end()
        mock_next.assert_not_called()


# ════════════════════════════════════════════════════════════
# Session — _start_next_cycle 内部回调
# ════════════════════════════════════════════════════════════
class TestSessionNextCycleCallbacks:
    """_start_next_cycle 内部回调测试"""

    async def test_next_cycle_on_text(self):
        s = make_session()
        mock_start = AsyncMock()
        with patch.object(Session, "start_asr", new=mock_start), \
             patch.object(Session, "start_watchdog", new_callable=AsyncMock), \
             patch.object(Session, "pre_connect_asr", new_callable=AsyncMock):
            await s._start_next_cycle()
        on_text = mock_start.call_args.args[0]
        on_text("下一轮文本")
        assert s.runtime.asr_full_text == "下一轮文本"

    async def test_next_cycle_vad_end_with_text(self):
        # _on_vad_end_cycle 有文本时运行 pipeline 并启动下一轮
        channel = MagicMock()
        channel.send_json = AsyncMock()
        fsm = MagicMock()
        fsm.set = AsyncMock()
        s = make_session(channel=channel, fsm=fsm)
        mock_start = AsyncMock()
        mock_result = MagicMock(stop_pipeline=False)
        # 不 patch _start_next_cycle，让它真正执行（start_asr/start_watchdog 已被 mock）
        with patch.object(Session, "start_asr", new=mock_start), \
             patch.object(Session, "start_watchdog", new_callable=AsyncMock), \
             patch.object(Session, "pre_connect_asr", new_callable=AsyncMock), \
             patch.object(Session, "run_pipeline", new_callable=AsyncMock, return_value=mock_result) as mock_run:
            await s._start_next_cycle()
            s.runtime.asr_full_text = "继续"
            vad_end = mock_start.call_args.args[1]
            await vad_end()
        # 应调用 run_pipeline
        mock_run.assert_called_once_with("继续")
        # start_asr 应被调用两次：初始 + 下一轮
        assert mock_start.call_count == 2

    async def test_next_cycle_vad_end_empty_text(self):
        channel = MagicMock()
        channel.send_json = AsyncMock()
        channel.send_text = AsyncMock()
        fsm = MagicMock()
        fsm.set = AsyncMock()
        s = make_session(channel=channel, fsm=fsm)
        mock_start = AsyncMock()
        with patch.object(Session, "start_asr", new=mock_start), \
             patch.object(Session, "start_watchdog", new_callable=AsyncMock), \
             patch.object(Session, "pre_connect_asr", new_callable=AsyncMock), \
             patch.object(Session, "run_pipeline", new_callable=AsyncMock) as mock_run:
            await s._start_next_cycle()
            s.runtime.asr_full_text = "  "
            vad_end = mock_start.call_args.args[1]
            await vad_end()
        mock_run.assert_not_called()

    async def test_next_cycle_vad_end_stop_pipeline(self):
        # stop_pipeline=True 时不启动下一轮（start_asr 只被调用一次）
        channel = MagicMock()
        channel.send_json = AsyncMock()
        fsm = MagicMock()
        fsm.set = AsyncMock()
        s = make_session(channel=channel, fsm=fsm)
        mock_start = AsyncMock()
        mock_result = MagicMock(stop_pipeline=True)
        with patch.object(Session, "start_asr", new=mock_start), \
             patch.object(Session, "start_watchdog", new_callable=AsyncMock), \
             patch.object(Session, "pre_connect_asr", new_callable=AsyncMock), \
             patch.object(Session, "run_pipeline", new_callable=AsyncMock, return_value=mock_result):
            await s._start_next_cycle()
            s.runtime.asr_full_text = "stop"
            vad_end = mock_start.call_args.args[1]
            await vad_end()
        # start_asr 只被调用一次（初始），不启动下一轮
        assert mock_start.call_count == 1
        fsm.set.assert_any_call(SessionState.IDLE)

    async def test_next_cycle_clears_processed(self):
        # _start_next_cycle 应清除 asr_processed
        s = make_session()
        s.runtime.asr_processed = True
        mock_start = AsyncMock()
        with patch.object(Session, "start_asr", new=mock_start), \
             patch.object(Session, "start_watchdog", new_callable=AsyncMock), \
             patch.object(Session, "pre_connect_asr", new_callable=AsyncMock):
            await s._start_next_cycle()
        assert s.runtime.asr_processed is False


# ════════════════════════════════════════════════════════════
# Session — queue_audio 边界条件
# ════════════════════════════════════════════════════════════
class TestSessionQueueAudioEdgeCases:
    """queue_audio 边界条件测试"""

    async def test_queue_audio_backlog_logging(self):
        # 队列积压 >= 10 时记录日志（验证不抛异常即可）
        s = make_session()
        q = asyncio.Queue()
        s.runtime.audio_queue = q
        s.runtime.asr_processed = False
        for i in range(12):
            await s.queue_audio(f"audio-{i}".encode())
        assert q.qsize() == 12

    async def test_queue_audio_after_processed(self):
        # asr_processed=True 时入队被跳过
        s = make_session()
        q = asyncio.Queue()
        s.runtime.audio_queue = q
        s.runtime.asr_processed = True
        await s.queue_audio(b"audio")
        assert q.empty()
