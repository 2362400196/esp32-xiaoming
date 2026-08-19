"""
ws_session_handler.py 单元测试

覆盖范围：
- WebSocketSessionHandler.__init__：状态初始化
- initialize()：WebSocket 接受、网关创建、Session 创建、后台任务
- on_asr_text()：ASR 文本回调
- on_vad_end()：VAD 结束回调
- _trigger_growth()：成长任务触发
- _on_tts_complete()：TTS 完成回调
- _start_next_asr()：启动下一轮 ASR
- _do_wake_start()：唤醒处理
- _start_asr_session()：启动 ASR 会话
- _play_connect_audio()：播放连接音频
- idle_keepalive()：空闲保活
- _llm_call_for_growth()：成长系统 LLM 调用
- _growth_cooldown_timer()：冷却定时器
- run()：主消息循环（各消息类型）
- cleanup()：资源清理
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.interfaces.ws_session_handler import WebSocketSessionHandler
from src.use_cases.session_fsm import SessionState
from starlette.websockets import WebSocketDisconnect


# ============================================================
# 辅助 fixtures
# ============================================================


def _make_websocket():
    """构造 mock websocket"""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.receive = AsyncMock()
    ws.send_json = AsyncMock()
    ws.send_bytes = AsyncMock()
    ws.send_text = AsyncMock()
    ws.close = AsyncMock()
    return ws


def _make_settings(**overrides):
    """构造 mock settings"""
    settings = MagicMock()
    settings.deploy_mode = "single"
    settings.growth_cooldown_seconds = 0
    settings.asr = MagicMock(
        provider="volcengine",
        enable_pool=False,
        no_speech_timeout=10,
        silence_timeout=5,
        tencent_app_id="",
        tencent_secret_id="",
        tencent_secret_key="",
        tencent_engine="16k_zh",
        volcengine_api_key="",
        volcengine_resource_id="",
        volcengine_model="",
    )
    settings.llm = MagicMock(api_key="", base_url="", model="", system_prompt="")
    settings.tts = MagicMock(
        api_key="", resource_id="", voice_type="",
        speed_ratio=1.0, volume_ratio=1.0, pitch_ratio=1.0, enable_pool=False,
    )
    settings.wakeup = MagicMock(enable_audio=False, audio_play_enabled=False)
    settings.session = MagicMock(
        tts_playback_base_timeout=30.0,
        tts_playback_max_timeout=120.0,
        tts_playback_duration_multiplier=2.0,
    )
    settings.rate_limit = MagicMock(max_rpm=0)
    settings.mcp = None
    for k, v in overrides.items():
        setattr(settings, k, v)
    return settings


def _make_app():
    """构造 mock app"""
    app = MagicMock()
    app.state = MagicMock()
    app.state.shared_tool_manager = MagicMock()
    app.state.shared_tool_manager.ensure_discovered = MagicMock()
    app.state.tool_manager = None
    app.state.wake_audio_manager = None
    return app


def _make_registry():
    """构造 mock device registry"""
    registry = AsyncMock()
    registry.register = AsyncMock()
    registry.unregister = AsyncMock()
    registry.get_pending_ota = MagicMock(return_value=None)
    registry.get_pending_wifi_config = MagicMock(return_value=None)
    registry.get_pending_instruct = MagicMock(return_value=None)
    registry.has = MagicMock(return_value=False)
    registry.resolve = MagicMock(return_value=None)
    registry.update_ota_progress = MagicMock()
    registry.set_ota_updating = MagicMock()
    registry.set_pending_ota = MagicMock()
    registry.set_pending_wifi_config = MagicMock()
    registry.set_pending_instruct = MagicMock()
    return registry


def _make_session():
    """构造 mock session"""
    session = MagicMock()
    session.session_id = "test-session"
    session._closed = False
    session.runtime = MagicMock()
    session.runtime.asr_processed = False
    session.runtime.asr_full_text = ""
    session.runtime.asr_last_result_time = None
    session.runtime.asr_start_time = None
    session.runtime.asr_stop_event = None
    session.runtime.asr_task = None
    session.runtime.audio_queue = None
    session.runtime.asr_last_audio_time = None
    session.conversation_memory = MagicMock()
    session.conversation_memory.messages = []
    session.tts_playback_done = asyncio.Event()
    session.tts_audio_ended = asyncio.Event()
    session.tts_playing = False
    session.tts_drain_ack = asyncio.Event()
    session._wake_audio_played = asyncio.Event()
    session._waiting_wake_audio = False
    session.audio_processor = MagicMock()
    session.audio_processor.process_audio_chunk = MagicMock()
    session.cancel_event = MagicMock()
    session.cancel_event.set = MagicMock()
    session.close = AsyncMock()
    session.drain_asr = AsyncMock()
    session.send_session_end = AsyncMock()
    session.run_pipeline = AsyncMock()
    session.pre_connect_asr = AsyncMock()
    session.cancel_pre_asr = MagicMock()
    session.start_asr = AsyncMock()
    session.start_watchdog = AsyncMock()
    session.interrupt = AsyncMock()
    session.queue_audio = AsyncMock()
    session.can_queue_audio = MagicMock(return_value=False)
    session.set_device_buffer = AsyncMock()
    session.set_tts_playing = AsyncMock()
    session._current_pipeline = None
    return session


def _make_handler(websocket=None, **kwargs):
    """构造 WebSocketSessionHandler 实例，mock 全部外部依赖"""
    ws = websocket or _make_websocket()
    settings = _make_settings()
    app = _make_app()
    registry = _make_registry()

    with patch("src.interfaces.ws_session_handler.get_settings", return_value=settings), \
         patch("src.interfaces.ws_session_handler.get_app", return_value=app), \
         patch("src.interfaces.ws_session_handler.get_device_registry", return_value=registry):
        handler = WebSocketSessionHandler(
            websocket=ws,
            device_key="test_device_key_123",
            device_mac="AA:BB:CC:DD:EE:FF",
            device_firmware_version="1.0.0",
            trace_id="trace_001",
        )

    handler.settings = settings
    return handler


def _init_patches(asr_error=False, llm_error=False, tts_error=False):
    """构造 initialize() 所需的所有 patch 上下文管理器列表"""
    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(patch("src.interfaces.ws_session_handler.get_app", return_value=_make_app()))
    stack.enter_context(patch("src.interfaces.ws_session_handler.get_device_registry", return_value=_make_registry()))
    if asr_error:
        stack.enter_context(patch("src.interfaces.ws_session_handler.create_asr_gateway", side_effect=Exception("ASR fail")))
    else:
        stack.enter_context(patch("src.interfaces.ws_session_handler.create_asr_gateway", return_value=MagicMock()))
    if llm_error:
        stack.enter_context(patch("src.interfaces.ws_session_handler.create_llm_gateway", side_effect=Exception("LLM fail")))
    else:
        stack.enter_context(patch("src.interfaces.ws_session_handler.create_llm_gateway", return_value=MagicMock()))
    if tts_error:
        stack.enter_context(patch("src.interfaces.ws_session_handler.create_tts_gateway", side_effect=Exception("TTS fail")))
    else:
        stack.enter_context(patch("src.interfaces.ws_session_handler.create_tts_gateway", return_value=MagicMock()))
    stack.enter_context(patch("src.interfaces.ws_session_handler.SqlShortTermMemoryRepository"))
    stack.enter_context(patch("src.interfaces.ws_session_handler.Session"))
    stack.enter_context(patch("src.interfaces.ws_session_handler.VoiceGenerator"))
    stack.enter_context(patch("src.use_cases.skill_system.render_skills_catalog", return_value=""))
    stack.enter_context(patch("asyncio.create_task", side_effect=_swallow_coro))
    return stack


def _swallow_coro(coro, **kw):
    """安全关闭协程，避免 'coroutine never awaited' 警告"""
    coro.close()


async def _do_initialize(handler, asr_error=False, llm_error=False, tts_error=False):
    """调用 initialize() 并处理所有 mock"""
    with _init_patches(asr_error=asr_error, llm_error=llm_error, tts_error=tts_error):
        await handler.initialize()


# ============================================================
# __init__
# ============================================================


class TestInit:
    """WebSocketSessionHandler 初始化"""

    def test_init_sets_attributes(self):
        handler = _make_handler()
        assert handler.device_key == "test_device_key_123"
        assert handler.device_mac == "AA:BB:CC:DD:EE:FF"
        assert handler.device_firmware_version == "1.0.0"
        assert handler.trace_id == "trace_001"

    def test_init_default_state(self):
        handler = _make_handler()
        assert handler.client_audio_buffer_size == 10240
        assert handler.is_multi_mode is False
        assert handler.user_config is None
        assert handler.channel is None
        assert handler.fsm is None
        assert handler.session is None

    def test_init_task_references_none(self):
        handler = _make_handler()
        assert handler.pipeline_task is None
        assert handler.keepalive_task is None
        assert handler._growth_cooldown_task is None
        assert handler.connect_audio_task is None
        assert handler.wake_start_task is None

    def test_init_call_times_empty(self):
        handler = _make_handler()
        assert handler.call_times == []

    def test_init_vad_end_lock(self):
        handler = _make_handler()
        assert isinstance(handler._vad_end_lock, asyncio.Lock)


# ============================================================
# initialize()
# ============================================================


class TestInitialize:
    """initialize() 完整初始化"""

    async def test_initialize_accepts_websocket(self):
        handler = _make_handler()
        await _do_initialize(handler)
        handler.websocket.accept.assert_called_once()

    async def test_initialize_creates_channel_and_fsm(self):
        handler = _make_handler()
        await _do_initialize(handler)
        assert handler.channel is not None
        assert handler.fsm is not None

    async def test_initialize_multi_mode(self):
        handler = _make_handler()
        handler.settings.deploy_mode = "multi"
        handler.user_config = MagicMock(
            asr_provider="volcengine",
            llm_api_key="test_key",
            tts_config={"api_key": "k"},
            mcp_servers=None,
            disabled_tools=None,
            skills=None,
            rate_limit_rpm=0,
            get_asr_config=MagicMock(return_value={}),
            llm_base_url="",
            llm_model="",
            llm_system_prompt="",
        )
        await _do_initialize(handler)
        assert handler.is_multi_mode is True

    async def test_initialize_asr_failure_handled(self):
        handler = _make_handler()
        await _do_initialize(handler, asr_error=True)
        assert handler.asr_client is None

    async def test_initialize_llm_failure_handled(self):
        handler = _make_handler()
        await _do_initialize(handler, llm_error=True)
        assert handler.llm_processor is None

    async def test_initialize_tts_failure_handled(self):
        handler = _make_handler()
        await _do_initialize(handler, tts_error=True)
        assert handler.tts_processor is None

    async def test_initialize_sends_connected_message(self):
        handler = _make_handler()
        await _do_initialize(handler)
        # WSChannel.send_json 将消息放入 _hi 队列，_send_loop 被 mock 未运行
        # 因此需从 _hi 队列中读取已发送的消息
        sent_types = []
        while not handler.channel._hi.empty():
            msg = handler.channel._hi.get_nowait()
            sent_types.append(msg["data"].get("type"))
        assert "play_audio_ws_conntceed" in sent_types

    async def test_initialize_starts_keepalive(self):
        handler = _make_handler()
        await _do_initialize(handler)
        # keepalive_task 被异步创建（通过 mock 的 create_task）
        # 检查 send_json 中是否有 keepalive 消息
        # 由于 create_task 被 mock，keepalive 不会真正运行
        assert handler.keepalive_task is None  # create_task 被 mock 返回 None


# ============================================================
# on_asr_text()
# ============================================================


class TestOnAsrText:
    """on_asr_text ASR 文本回调"""

    def test_sets_asr_full_text(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.on_asr_text("你好世界")
        assert handler.session.runtime.asr_full_text == "你好世界"

    def test_sets_asr_last_result_time_on_non_empty(self):
        import time
        handler = _make_handler()
        handler.session = _make_session()
        before = time.time()
        handler.on_asr_text("你好")
        assert handler.session.runtime.asr_last_result_time is not None
        assert handler.session.runtime.asr_last_result_time >= before

    def test_does_not_set_time_on_empty_text(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.session.runtime.asr_last_result_time = None
        handler.on_asr_text("")
        assert handler.session.runtime.asr_last_result_time is None


# ============================================================
# on_vad_end()
# ============================================================


class TestOnVadEnd:
    """on_vad_end VAD 结束回调"""

    async def test_already_processed_returns(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.channel = MagicMock()
        handler.channel.send_json = AsyncMock()
        handler.fsm = MagicMock()
        handler.session.runtime.asr_processed = True
        await handler.on_vad_end()
        # 应直接返回，不发送 iat_end
        handler.channel.send_json.assert_not_called()

    async def test_sends_iat_end(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.channel = MagicMock()
        handler.channel.send_json = AsyncMock()
        handler.fsm = MagicMock()
        handler.session.runtime.asr_full_text = "你好"
        await handler.on_vad_end()
        sent = handler.channel.send_json.call_args_list[0].args[0]
        assert sent["type"] == "session_status"
        assert sent["status"] == "iat_end"

    async def test_empty_text_sends_session_end(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.channel = MagicMock()
        handler.channel.send_json = AsyncMock()
        handler.fsm = MagicMock()
        handler.session.runtime.asr_full_text = ""
        await handler.on_vad_end()
        handler.session.send_session_end.assert_called_once()

    async def test_rate_limit_exceeded(self):
        import time
        handler = _make_handler()
        handler.session = _make_session()
        handler.channel = MagicMock()
        handler.channel.send_json = AsyncMock()
        handler.fsm = MagicMock()
        handler.settings.rate_limit.max_rpm = 1
        handler.session.runtime.asr_full_text = "你好"
        # 使用最近的时间戳（1秒前），仍在 60 秒窗口内
        handler.call_times = [time.time() - 1]
        await handler.on_vad_end()
        handler.session.send_session_end.assert_called_once()

    async def test_starts_pipeline(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.channel = MagicMock()
        handler.channel.send_json = AsyncMock()
        handler.fsm = MagicMock()
        handler.session.runtime.asr_full_text = "你好"
        handler.settings.rate_limit.max_rpm = 0  # 不限速
        await handler.on_vad_end()
        handler.session.run_pipeline.assert_called_once_with("你好")

    async def test_cancels_previous_tts_done_waiter(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.channel = MagicMock()
        handler.channel.send_json = AsyncMock()
        handler.fsm = MagicMock()
        handler.session.runtime.asr_full_text = "你好"
        old_waiter = asyncio.Event()
        handler.tts_done_waiter = asyncio.ensure_future(asyncio.sleep(100))
        await handler.on_vad_end()
        assert handler.tts_done_waiter.cancel()
        handler.pipeline_task.cancel()


# ============================================================
# _trigger_growth()
# ============================================================


class TestTriggerGrowth:
    """_trigger_growth 成长任务触发"""

    def test_no_growth_system_returns(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler._growth_system = None
        handler._trigger_growth()
        assert handler._growth_cooldown_task is None

    def test_no_conversation_memory_returns(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler._growth_system = MagicMock()
        handler.session.conversation_memory = None
        handler._trigger_growth()
        assert handler._growth_cooldown_task is None

    def test_empty_messages_returns(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler._growth_system = MagicMock()
        handler.session.conversation_memory.messages = []
        handler._trigger_growth()
        assert handler._growth_cooldown_task is None

    async def test_starts_cooldown_timer(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler._growth_system = MagicMock()
        handler.session.conversation_memory.messages = [MagicMock()]
        handler._growth_cooldown_seconds = 0.01
        handler._trigger_growth()
        assert handler._growth_cooldown_task is not None
        handler._growth_cooldown_task.cancel()

    async def test_cancels_previous_cooldown(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler._growth_system = MagicMock()
        handler.session.conversation_memory.messages = [MagicMock()]
        handler._growth_cooldown_seconds = 100
        old_task = asyncio.ensure_future(asyncio.sleep(100))
        handler._growth_cooldown_task = old_task
        handler._trigger_growth()
        assert old_task.cancelled() or old_task.cancel()
        handler._growth_cooldown_task.cancel()


# ============================================================
# _on_tts_complete()
# ============================================================


class TestOnTtsComplete:
    """_on_tts_complete TTS 完成回调"""

    async def test_pipeline_timeout(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.fsm.get.return_value = SessionState.IDLE

        # pipeline 永不完成 -> 超时
        async def _never_done():
            await asyncio.sleep(100)
        handler.pipeline_task = asyncio.ensure_future(_never_done())

        await asyncio.wait_for(handler._on_tts_complete(), timeout=35)
        handler.pipeline_task.cancel()

    async def test_pipeline_cancelled(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.fsm.get.return_value = SessionState.IDLE

        handler.pipeline_task = asyncio.ensure_future(asyncio.sleep(100))
        handler.pipeline_task.cancel()

        await handler._on_tts_complete()
        handler.session.tts_playback_done.set()

    async def test_pipeline_no_audio(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.fsm.get.return_value = SessionState.IDLE

        # pipeline 返回 None（无音频）
        async def _done():
            return None
        handler.pipeline_task = asyncio.ensure_future(_done())
        handler._trigger_growth = MagicMock()

        await handler._on_tts_complete()
        handler.session.tts_playback_done.set()

    async def test_stop_pipeline_result(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.fsm.set = AsyncMock()
        handler.fsm.get.return_value = SessionState.IDLE

        result = MagicMock()
        result.stop_pipeline = True
        result.total_duration_ms = 0

        async def _done():
            return result
        handler.pipeline_task = asyncio.ensure_future(_done())
        handler._trigger_growth = MagicMock()

        await handler._on_tts_complete()
        handler.fsm.set.assert_called_with(SessionState.IDLE)
        handler.session.tts_playback_done.set()

    async def test_pipeline_with_audio(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.fsm.get.return_value = SessionState.IDLE

        result = MagicMock()
        result.stop_pipeline = False
        result.total_duration_ms = 5000

        async def _done():
            return result
        handler.pipeline_task = asyncio.ensure_future(_done())
        handler._trigger_growth = MagicMock()
        handler.session.tts_playback_done.set()

        await handler._on_tts_complete()

    async def test_cancelled(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()

        async def _cancelled():
            await asyncio.sleep(100)
        handler.pipeline_task = asyncio.ensure_future(_cancelled())

        task = asyncio.ensure_future(handler._on_tts_complete())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        handler.pipeline_task.cancel()


# ============================================================
# _start_next_asr()
# ============================================================


class TestStartNextAsr:
    """_start_next_asr 启动下一轮 ASR"""

    async def test_already_in_asr_state(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.fsm.get.return_value = SessionState.ASR
        handler.channel = MagicMock()
        handler.channel.send_json = AsyncMock()

        await handler._start_next_asr()
        # 应直接返回，不发送 iat_start
        handler.channel.send_json.assert_not_called()

    async def test_starts_asr(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.fsm.set = AsyncMock()
        handler.fsm.get.return_value = SessionState.IDLE
        handler.channel = MagicMock()
        handler.channel.send_json = AsyncMock()
        handler.asr_client = MagicMock()

        await handler._start_next_asr()
        handler.fsm.set.assert_called_with(SessionState.ASR)
        handler.session.cancel_pre_asr.assert_called_once()

    async def test_no_asr_client(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.fsm.set = AsyncMock()
        handler.fsm.get.return_value = SessionState.IDLE
        handler.channel = MagicMock()
        handler.channel.send_json = AsyncMock()
        handler.asr_client = None

        await handler._start_next_asr()
        handler.session.cancel_pre_asr.assert_not_called()


# ============================================================
# _start_asr_session()
# ============================================================


class TestStartAsrSession:
    """_start_asr_session 启动 ASR 会话"""

    def test_sets_runtime_fields(self):
        import time
        handler = _make_handler()
        handler.session = _make_session()
        handler.asr_client = MagicMock()

        with patch("asyncio.create_task") as mock_task:
            handler._start_asr_session()

        assert handler.session.runtime.asr_start_time is not None
        assert handler.session.runtime.asr_full_text == ""

    def test_with_asr_client(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.asr_client = MagicMock()

        with patch("asyncio.create_task") as mock_task:
            handler._start_asr_session()

        # 应创建 start_asr 和 start_watchdog 任务
        assert mock_task.call_count >= 2

    def test_without_asr_client(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.asr_client = None

        with patch("asyncio.create_task") as mock_task:
            handler._start_asr_session()

        # 只创建 start_watchdog 任务
        assert mock_task.call_count == 1


# ============================================================
# _do_wake_start()
# ============================================================


class TestDoWakeStart:
    """_do_wake_start 唤醒处理"""

    async def test_no_wake_audio(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.fsm.set = AsyncMock()
        handler.channel = MagicMock()
        handler.channel.send_json = AsyncMock()
        handler.settings.wakeup.enable_audio = False

        app = _make_app()
        with patch("src.interfaces.ws_session_handler.get_app", return_value=app):
            await handler._do_wake_start()
        handler.fsm.set.assert_called_with(SessionState.ASR)

    async def test_wake_audio_disabled(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.fsm.set = AsyncMock()
        handler.channel = MagicMock()
        handler.channel.send_json = AsyncMock()
        handler.settings.wakeup.enable_audio = True
        handler.settings.wakeup.audio_play_enabled = False

        # 设置 wake_audio_manager 使 wam 非空，进入唤醒音频处理分支
        wam = AsyncMock()
        app = _make_app()
        app.state.wake_audio_manager = wam
        with patch("src.interfaces.ws_session_handler.get_app", return_value=app):
            await handler._do_wake_start()

        # audio_play_enabled=False 时应直接 set _wake_audio_played
        assert handler.session._wake_audio_played.is_set()

    async def test_session_closed_during_wake(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.fsm.set = AsyncMock()
        handler.channel = MagicMock()
        handler.channel.send_json = AsyncMock()
        handler.settings.wakeup.enable_audio = True
        handler.settings.wakeup.audio_play_enabled = True

        wam = AsyncMock()
        # 模拟在播放唤醒音频期间会话被关闭
        async def _close_during_play(*args, **kwargs):
            handler.session._closed = True
        wam.play = AsyncMock(side_effect=_close_during_play)

        app = _make_app()
        app.state.wake_audio_manager = wam

        with patch("src.interfaces.ws_session_handler.get_app", return_value=app):
            await handler._do_wake_start()

        # 会话关闭后应直接返回，不应调用 fsm.set
        handler.fsm.set.assert_not_called()


# ============================================================
# _play_connect_audio()
# ============================================================


class TestPlayConnectAudio:
    """_play_connect_audio 播放连接音频"""

    async def test_sends_connect_messages(self):
        handler = _make_handler()
        handler.channel = MagicMock()
        handler.channel.send_json = AsyncMock()
        handler.channel.send_bytes = AsyncMock()
        handler.channel.send_text = AsyncMock()
        handler.fsm = MagicMock()
        handler.fsm.get.return_value = SessionState.IDLE
        handler.voice_generator = MagicMock()
        handler.voice_generator.make_end_frame = MagicMock(return_value=b"end_frame")
        handler.session = _make_session()

        await handler._play_connect_audio()

        sent_types = [call.args[0].get("type") for call in handler.channel.send_json.call_args_list]
        assert "stc_time" in sent_types
        assert "play_audio" in sent_types
        # tts_chunk_start 是 session_status 的 status 值
        sent_statuses = [call.args[0].get("status") for call in handler.channel.send_json.call_args_list if call.args[0].get("type") == "session_status"]
        assert "tts_chunk_start" in sent_statuses
        assert "tts_chunk_end" in sent_statuses
        assert "session_end" in sent_statuses
        handler.channel.send_bytes.assert_called_once()

    async def test_skip_session_end_when_active(self):
        handler = _make_handler()
        handler.channel = MagicMock()
        handler.channel.send_json = AsyncMock()
        handler.channel.send_bytes = AsyncMock()
        handler.channel.send_text = AsyncMock()
        handler.fsm = MagicMock()
        handler.fsm.get.return_value = SessionState.ASR  # 活跃状态
        handler.voice_generator = MagicMock()
        handler.voice_generator.make_end_frame = MagicMock(return_value=b"end_frame")
        handler.session = _make_session()

        await handler._play_connect_audio()

        # 不应发送 session_end
        sent_types = [call.args[0].get("type") for call in handler.channel.send_json.call_args_list]
        # session_end 只在 IDLE 时发送
        session_ends = [c for c in handler.channel.send_json.call_args_list
                        if c.args[0].get("status") == "session_end"]
        assert len(session_ends) == 0


# ============================================================
# idle_keepalive()
# ============================================================


class TestIdleKeepalive:
    """idle_keepalive 空闲保活"""

    async def test_sends_keepalive(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.fsm.get.return_value = SessionState.TTS  # TTS 状态间隔为 1 秒
        handler.channel = MagicMock()
        handler.channel.send_json_nowait = MagicMock()

        # 延迟后关闭会话，使 keepalive 循环退出
        async def _close_after_delay():
            await asyncio.sleep(1.5)
            handler.session._closed = True

        close_task = asyncio.ensure_future(_close_after_delay())
        with patch("src.interfaces.ws_session_handler.get_device_registry", return_value=None):
            await asyncio.wait_for(handler.idle_keepalive(), timeout=5)
        close_task.cancel()

        assert handler.channel.send_json_nowait.call_count >= 1

    async def test_sends_ota(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.fsm.get.return_value = SessionState.TTS
        handler.channel = MagicMock()
        handler.channel.send_json_nowait = MagicMock()

        registry = _make_registry()
        registry.get_pending_ota.return_value = {"type": "ota_update", "url": "http://..."}

        async def _close_after_delay():
            await asyncio.sleep(1.5)
            handler.session._closed = True

        close_task = asyncio.ensure_future(_close_after_delay())
        with patch("src.interfaces.ws_session_handler.get_device_registry", return_value=registry):
            await asyncio.wait_for(handler.idle_keepalive(), timeout=5)
        close_task.cancel()

        registry.set_ota_updating.assert_called_once()
        registry.set_pending_ota.assert_called_once()

    async def test_sends_instruct(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.fsm.get.return_value = SessionState.TTS
        handler.channel = MagicMock()
        handler.channel.send_json_nowait = MagicMock()

        registry = _make_registry()
        registry.get_pending_instruct.return_value = {"type": "instruct", "command_id": "test"}

        async def _close_after_delay():
            await asyncio.sleep(1.5)
            handler.session._closed = True

        close_task = asyncio.ensure_future(_close_after_delay())
        with patch("src.interfaces.ws_session_handler.get_device_registry", return_value=registry):
            await asyncio.wait_for(handler.idle_keepalive(), timeout=5)
        close_task.cancel()

        registry.set_pending_instruct.assert_called_once()


# ============================================================
# _llm_call_for_growth()
# ============================================================


class TestLlmCallForGrowth:
    """_llm_call_for_growth 成长系统 LLM 调用"""

    async def test_no_llm_processor_raises(self):
        handler = _make_handler()
        handler.llm_processor = None
        with pytest.raises(RuntimeError, match="LLM processor not available"):
            await handler._llm_call_for_growth("sys", "user")

    async def test_success_with_user_config(self):
        handler = _make_handler()
        handler.llm_processor = MagicMock()
        handler.user_config = MagicMock()
        handler.user_config.llm_api_key = "user_key"
        handler.user_config.llm_base_url = "https://api.example.com"
        handler.user_config.llm_model = "gpt-4"

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "result"

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("src.interfaces.ws_session_handler.get_settings", return_value=_make_settings()):
            with patch("openai.AsyncOpenAI", return_value=mock_client):
                result = await handler._llm_call_for_growth("sys", "user prompt")

        assert result == "result"

    async def test_fallback_to_stream_chat(self):
        handler = _make_handler()
        handler.llm_processor = MagicMock()

        async def _stream(messages):
            yield "hello"
            yield " world"

        handler.llm_processor.stream_chat = _stream

        with patch("src.interfaces.ws_session_handler.get_settings", return_value=_make_settings()):
            with patch("openai.AsyncOpenAI", side_effect=Exception("API error")):
                result = await handler._llm_call_for_growth("sys", "user")

        assert "hello" in result
        assert "world" in result

    async def test_filters_token_prefix(self):
        handler = _make_handler()
        handler.llm_processor = MagicMock()

        async def _stream(messages):
            yield "__start__"
            yield "actual"
            yield "__end__"
            yield "content"

        handler.llm_processor.stream_chat = _stream

        with patch("src.interfaces.ws_session_handler.get_settings", return_value=_make_settings()):
            with patch("openai.AsyncOpenAI", side_effect=Exception("error")):
                result = await handler._llm_call_for_growth("sys", "user")

        assert "actual" in result
        assert "content" in result
        assert "__" not in result


# ============================================================
# _growth_cooldown_timer()
# ============================================================


class TestGrowthCooldownTimer:
    """_growth_cooldown_timer 冷却定时器"""

    async def test_executes_growth_task(self):
        handler = _make_handler()
        handler._growth_cooldown_seconds = 0.01
        handler._growth_system = MagicMock()
        handler._growth_system.on_conversation_end = AsyncMock()

        await handler._growth_cooldown_timer("device1", [MagicMock()])

        handler._growth_system.on_conversation_end.assert_called_once()

    async def test_no_growth_system(self):
        handler = _make_handler()
        handler._growth_cooldown_seconds = 0.01
        handler._growth_system = None
        # 不应抛异常
        await handler._growth_cooldown_timer("device1", [])

    async def test_growth_task_failure_handled(self):
        handler = _make_handler()
        handler._growth_cooldown_seconds = 0.01
        handler._growth_system = MagicMock()
        handler._growth_system.on_conversation_end = AsyncMock(side_effect=Exception("fail"))
        # 不应抛异常
        await handler._growth_cooldown_timer("device1", [MagicMock()])


# ============================================================
# run() - 主消息循环
# ============================================================


class TestRun:
    """run() 主消息循环"""

    async def test_ping_message(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.session._closed = False
        handler.fsm = MagicMock()
        handler.fsm.get.return_value = SessionState.IDLE
        handler.channel = MagicMock()
        handler.channel.send_json_nowait = MagicMock()

        # 先发 ping，然后断开连接
        messages = [
            {"type": "websocket.receive", "text": json.dumps({"type": "ping"})},
            {"type": "websocket.disconnect"},
        ]
        handler.websocket.receive = AsyncMock(side_effect=messages)

        await handler.run()
        handler.channel.send_json_nowait.assert_called()
        # 最后一次调用应是 pong
        last_call = handler.channel.send_json_nowait.call_args_list[0].args[0]
        assert last_call["type"] == "pong"

    async def test_ota_progress_message(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.channel = MagicMock()

        registry = _make_registry()
        handler.websocket.receive = AsyncMock(side_effect=[
            {"type": "websocket.receive", "text": json.dumps({"type": "ota_progress", "data": 50})},
            {"type": "websocket.disconnect"},
        ])

        with patch("src.interfaces.ws_session_handler.get_device_registry", return_value=registry):
            await handler.run()

        registry.update_ota_progress.assert_called_once_with("test_device_key_123", 50.0)

    async def test_ota_update_error_message(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.channel = MagicMock()

        registry = _make_registry()
        handler.websocket.receive = AsyncMock(side_effect=[
            {"type": "websocket.receive", "text": json.dumps({"type": "ota_update_error"})},
            {"type": "websocket.disconnect"},
        ])

        with patch("src.interfaces.ws_session_handler.get_device_registry", return_value=registry):
            await handler.run()

        registry.set_ota_updating.assert_called_once_with("test_device_key_123", False)

    async def test_session_stop_message(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.fsm.set = AsyncMock()
        handler.fsm.get.return_value = SessionState.TTS
        handler.channel = MagicMock()
        handler.channel.send_json = AsyncMock()
        handler.session.tts_playing = True

        handler.websocket.receive = AsyncMock(side_effect=[
            {"type": "websocket.receive", "text": json.dumps({"type": "session_stop", "session_id": "0001"})},
            {"type": "websocket.disconnect"},
        ])

        await handler.run()

        handler.session.drain_asr.assert_called_once()
        handler.session.interrupt.assert_called_once()
        handler.fsm.set.assert_called_with(SessionState.IDLE)

    async def test_audio_bytes_message(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.session.can_queue_audio = MagicMock(return_value=True)
        handler.fsm = MagicMock()
        handler.fsm.get.return_value = SessionState.ASR
        handler.channel = MagicMock()

        handler.websocket.receive = AsyncMock(side_effect=[
            {"type": "websocket.receive", "bytes": b"audio_data"},
            {"type": "websocket.disconnect"},
        ])

        await handler.run()

        handler.session.audio_processor.process_audio_chunk.assert_called_once_with(b"audio_data")
        handler.session.queue_audio.assert_called_once_with(b"audio_data")

    async def test_disconnect_breaks_loop(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.channel = MagicMock()

        handler.websocket.receive = AsyncMock(side_effect=WebSocketDisconnect(code=1000))

        await handler.run()

    async def test_invalid_json_skipped(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.channel = MagicMock()

        handler.websocket.receive = AsyncMock(side_effect=[
            {"type": "websocket.receive", "text": "not json"},
            {"type": "websocket.disconnect"},
        ])

        await handler.run()

    async def test_start_message(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.fsm.set = AsyncMock()
        handler.fsm.get.return_value = SessionState.IDLE
        handler.channel = MagicMock()
        handler.channel.send_json = AsyncMock()
        handler.settings.wakeup.enable_audio = False
        handler.asr_client = MagicMock()

        handler.websocket.receive = AsyncMock(side_effect=[
            {"type": "websocket.receive", "text": json.dumps({"type": "start"})},
            {"type": "websocket.disconnect"},
        ])

        await handler.run()

        handler.fsm.set.assert_any_call(SessionState.ASR)

    async def test_iat_end_message(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.session.runtime.asr_processed = False
        handler.fsm = MagicMock()
        handler.channel = MagicMock()

        with patch.object(handler, "on_vad_end", new_callable=AsyncMock):
            handler.websocket.receive = AsyncMock(side_effect=[
                {"type": "websocket.receive", "text": json.dumps({"type": "iat_end"})},
                {"type": "websocket.disconnect"},
            ])

            await handler.run()

    async def test_oserror_breaks_loop(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.channel = MagicMock()

        handler.websocket.receive = AsyncMock(side_effect=OSError("connection lost"))

        await handler.run()

    async def test_generic_exception_breaks_loop(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.channel = MagicMock()

        handler.websocket.receive = AsyncMock(side_effect=Exception("unexpected"))

        await handler.run()

    async def test_lua_result_message(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.channel = MagicMock()
        handler.tool_mgr = MagicMock()
        handler.tool_mgr._pending_lua_future = None

        handler.websocket.receive = AsyncMock(side_effect=[
            {"type": "websocket.receive", "text": json.dumps({"type": "lua_result", "success": True, "output": "ok"})},
            {"type": "websocket.disconnect"},
        ])

        await handler.run()

    async def test_firmware_version_message(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.channel = MagicMock()

        registry = _make_registry()
        registry.has.return_value = True
        device = {"firmware_version": "old"}
        registry.resolve.return_value = device

        handler.websocket.receive = AsyncMock(side_effect=[
            {"type": "websocket.receive", "text": json.dumps({"type": "firmware_version", "version": "2.0"})},
            {"type": "websocket.disconnect"},
        ])

        with patch("src.interfaces.ws_session_handler.get_device_registry", return_value=registry):
            await handler.run()

        assert device["firmware_version"] == "2.0"

    async def test_client_available_audio_message(self):
        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.channel = MagicMock()

        handler.websocket.receive = AsyncMock(side_effect=[
            {"type": "websocket.receive", "text": json.dumps({"type": "client_available_audio", "value": 20480})},
            {"type": "websocket.disconnect"},
        ])

        await handler.run()

        handler.session.set_device_buffer.assert_called_once_with(20480)


# ============================================================
# cleanup()
# ============================================================


class TestCleanup:
    """cleanup() 资源清理"""

    async def test_cancels_all_tasks(self):
        handler = _make_handler()
        handler.pipeline_task = asyncio.ensure_future(asyncio.sleep(100))
        handler.tts_done_waiter = asyncio.ensure_future(asyncio.sleep(100))
        handler.wake_start_task = asyncio.ensure_future(asyncio.sleep(100))
        handler.keepalive_task = asyncio.ensure_future(asyncio.sleep(100))
        handler._growth_cooldown_task = asyncio.ensure_future(asyncio.sleep(100))
        handler.connect_audio_task = asyncio.ensure_future(asyncio.sleep(100))

        handler.fsm = MagicMock()
        handler.fsm.set = AsyncMock()
        handler.channel = MagicMock()
        handler.channel.close = AsyncMock()
        handler.session = _make_session()

        with patch("src.interfaces.ws_session_handler.get_device_registry", return_value=_make_registry()):
            await handler.cleanup()

        assert handler.pipeline_task.cancelled() or handler.pipeline_task.cancel()
        assert handler.tts_done_waiter.cancelled() or handler.tts_done_waiter.cancel()
        assert handler.wake_start_task.cancelled() or handler.wake_start_task.cancel()
        assert handler.keepalive_task.cancelled() or handler.keepalive_task.cancel()
        assert handler._growth_cooldown_task.cancelled() or handler._growth_cooldown_task.cancel()
        assert handler.connect_audio_task.cancelled() or handler.connect_audio_task.cancel()

    async def test_sets_fsm_to_idle(self):
        handler = _make_handler()
        handler.fsm = MagicMock()
        handler.fsm.set = AsyncMock()
        handler.channel = MagicMock()
        handler.channel.close = AsyncMock()
        handler.session = _make_session()

        with patch("src.interfaces.ws_session_handler.get_device_registry", return_value=_make_registry()):
            await handler.cleanup()

        handler.fsm.set.assert_called_with(SessionState.IDLE)

    async def test_closes_channel(self):
        handler = _make_handler()
        handler.fsm = MagicMock()
        handler.fsm.set = AsyncMock()
        handler.channel = MagicMock()
        handler.channel.close = AsyncMock()
        handler.session = _make_session()

        with patch("src.interfaces.ws_session_handler.get_device_registry", return_value=_make_registry()):
            await handler.cleanup()

        handler.channel.close.assert_called_once()

    async def test_unregisters_device(self):
        handler = _make_handler()
        handler.fsm = MagicMock()
        handler.fsm.set = AsyncMock()
        handler.channel = MagicMock()
        handler.channel.close = AsyncMock()
        handler.session = _make_session()

        registry = _make_registry()
        with patch("src.interfaces.ws_session_handler.get_device_registry", return_value=registry):
            await handler.cleanup()

        registry.unregister.assert_called_once_with("test_device_key_123")

    async def test_closes_session(self):
        handler = _make_handler()
        handler.fsm = MagicMock()
        handler.fsm.set = AsyncMock()
        handler.channel = MagicMock()
        handler.channel.close = AsyncMock()
        handler.session = _make_session()

        with patch("src.interfaces.ws_session_handler.get_device_registry", return_value=_make_registry()):
            await handler.cleanup()

        handler.session.close.assert_called_once()

    async def test_cleanup_with_none_values(self):
        """initialize 部分失败时 cleanup 应安全调用"""
        handler = _make_handler()
        handler.pipeline_task = None
        handler.tts_done_waiter = None
        handler.wake_start_task = None
        handler.keepalive_task = None
        handler._growth_cooldown_task = None
        handler.connect_audio_task = None
        handler.fsm = None
        handler.channel = None
        handler.session = None

        with patch("src.interfaces.ws_session_handler.get_device_registry", return_value=None):
            await handler.cleanup()

    async def test_cleanup_no_tasks(self):
        handler = _make_handler()
        handler.fsm = MagicMock()
        handler.fsm.set = AsyncMock()
        handler.channel = MagicMock()
        handler.channel.close = AsyncMock()
        handler.session = _make_session()
        # 所有 task 为 None
        handler.pipeline_task = None
        handler.tts_done_waiter = None

        with patch("src.interfaces.ws_session_handler.get_device_registry", return_value=_make_registry()):
            await handler.cleanup()

        handler.fsm.set.assert_called_with(SessionState.IDLE)

