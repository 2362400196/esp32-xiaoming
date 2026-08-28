"""
speaker.py 单元测试

覆盖范围：
- Speaker._speak_core：TTS 合成流程、通道未连接、会话创建失败、异常处理
- Speaker.speak / speak_direct / speak_all
- Speaker.wakeup / wakeup_all / stop / stop_all
- Speaker.register_device / unregister_device / get_device / get_all_devices
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.use_cases.speaker import Speaker
from src.use_cases.session_fsm import SessionState


# ============================================================
# 辅助 fixtures
# ============================================================


def _make_device(channel=None, fsm=None, session=None, user_config=None):
    """构造一个设备字典"""
    return {
        "channel": channel or MagicMock(),
        "fsm": fsm or MagicMock(),
        "session": session or MagicMock(),
        "user_config": user_config,
    }


def _make_speaker(devices=None, by_mac=None):
    """构造 Speaker 实例，mock registry 和 wake_audio"""
    registry = MagicMock()
    registry.get = MagicMock(return_value=None)
    registry.get_by_mac = MagicMock(return_value=None)
    if devices:
        registry.get.return_value = devices.get("by_id")
    if by_mac:
        registry.get_by_mac.return_value = by_mac
    registry.get_all_ids.return_value = list(devices.keys()) if devices else []

    wake_audio = MagicMock()
    wake_audio.voice_generator = MagicMock()
    wake_audio.voice_generator.make_tts_frame.return_value = b"frame"
    wake_audio.voice_generator.make_end_frame.return_value = b"end_frame"
    wake_audio.play = AsyncMock()

    speaker = Speaker(device_registry=registry, wake_audio_manager=wake_audio)
    return speaker, registry, wake_audio


# ============================================================
# Speaker._speak_core
# ============================================================


class TestSpeakCore:
    """_speak_core TTS 合成核心"""

    async def test_channel_not_connected(self):
        speaker, _, _ = _make_speaker()
        channel = MagicMock()
        channel.connected = False
        fsm = MagicMock()
        result = await speaker._speak_core(channel, fsm, "你好")
        assert result is False

    async def test_channel_none(self):
        speaker, _, _ = _make_speaker()
        fsm = MagicMock()
        result = await speaker._speak_core(None, fsm, "你好")
        assert result is False

    async def test_successful_speak(self):
        speaker, _, wake_audio = _make_speaker()
        channel = MagicMock()
        channel.connected = True
        channel.send_json = AsyncMock()
        channel.send_bytes = AsyncMock()
        fsm = MagicMock()
        fsm.set = AsyncMock()

        # mock create_tts_gateway
        mock_session = AsyncMock()
        mock_session.synthesize_audio = _make_synthesize([b"chunk1", b"chunk2"])
        mock_session.close = AsyncMock()
        mock_gateway = AsyncMock()
        mock_gateway.create_session = AsyncMock(return_value=mock_session)
        mock_gateway.close = AsyncMock()

        with patch("src.use_cases.speaker.create_tts_gateway", return_value=mock_gateway):
            result = await speaker._speak_core(channel, fsm, "你好世界")

        assert result is True
        fsm.set.assert_called()
        # 应发送 instruct、play_audio 等消息
        assert channel.send_json.call_count >= 3
        # 应发送音频帧
        assert channel.send_bytes.call_count >= 2

    async def test_tts_session_creation_fails(self):
        speaker, _, _ = _make_speaker()
        channel = MagicMock()
        channel.connected = True
        channel.send_json = AsyncMock()
        channel.send_bytes = AsyncMock()
        fsm = MagicMock()
        fsm.set = AsyncMock()

        mock_gateway = AsyncMock()
        mock_gateway.create_session = AsyncMock(return_value=None)

        with patch("src.use_cases.speaker.create_tts_gateway", return_value=mock_gateway):
            result = await speaker._speak_core(channel, fsm, "你好")

        assert result is False

    async def test_exception_during_speak(self):
        speaker, _, wake_audio = _make_speaker()
        channel = MagicMock()
        channel.connected = True
        channel.send_json = AsyncMock()
        channel.send_bytes = AsyncMock()
        fsm = MagicMock()
        fsm.set = AsyncMock()

        mock_gateway = AsyncMock()
        mock_gateway.create_session = AsyncMock(side_effect=Exception("TTS error"))

        with patch("src.use_cases.speaker.create_tts_gateway", return_value=mock_gateway):
            result = await speaker._speak_core(channel, fsm, "你好")

        assert result is False

    async def test_need_wakeup_sends_extra_messages(self):
        speaker, _, _ = _make_speaker()
        channel = MagicMock()
        channel.connected = True
        channel.send_json = AsyncMock()
        channel.send_bytes = AsyncMock()
        fsm = MagicMock()
        fsm.set = AsyncMock()

        mock_session = AsyncMock()
        mock_session.synthesize_audio = _make_synthesize([b"chunk1"])
        mock_session.close = AsyncMock()
        mock_gateway = AsyncMock()
        mock_gateway.create_session = AsyncMock(return_value=mock_session)
        mock_gateway.close = AsyncMock()

        with patch("src.use_cases.speaker.create_tts_gateway", return_value=mock_gateway):
            await speaker._speak_core(channel, fsm, "你好", need_wakeup=True)

        # need_wakeup 应发送 session_start 和 iat_start
        sent_types = [call.args[0].get("type") for call in channel.send_json.call_args_list]
        assert "session_start" in sent_types

    async def test_empty_chunks_skipped(self):
        speaker, _, _ = _make_speaker()
        channel = MagicMock()
        channel.connected = True
        channel.send_json = AsyncMock()
        channel.send_bytes = AsyncMock()
        fsm = MagicMock()
        fsm.set = AsyncMock()

        mock_session = AsyncMock()
        # 包含空 chunk
        mock_session.synthesize_audio = _make_synthesize([b"chunk1", b"", None, b"chunk2"])
        mock_session.close = AsyncMock()
        mock_gateway = AsyncMock()
        mock_gateway.create_session = AsyncMock(return_value=mock_session)
        mock_gateway.close = AsyncMock()

        with patch("src.use_cases.speaker.create_tts_gateway", return_value=mock_gateway):
            result = await speaker._speak_core(channel, fsm, "你好")

        assert result is True


# ============================================================
# Speaker.speak
# ============================================================


class TestSpeak:
    """speak 通过设备ID播放"""

    async def test_speak_device_not_found(self):
        speaker, registry, _ = _make_speaker()
        registry.get.return_value = None
        registry.get_by_mac.return_value = None
        result = await speaker.speak("unknown", "你好")
        assert result is False

    async def test_speak_success(self):
        channel = MagicMock()
        channel.connected = True
        channel.send_json = AsyncMock()
        channel.send_bytes = AsyncMock()
        fsm = MagicMock()
        fsm.set = AsyncMock()
        device = _make_device(channel=channel, fsm=fsm)

        speaker, registry, _ = _make_speaker()
        registry.get_by_mac.return_value = device

        mock_session = AsyncMock()
        mock_session.synthesize_audio = _make_synthesize([b"chunk"])
        mock_session.close = AsyncMock()
        mock_gateway = AsyncMock()
        mock_gateway.create_session = AsyncMock(return_value=mock_session)
        mock_gateway.close = AsyncMock()

        with patch("src.use_cases.speaker.create_tts_gateway", return_value=mock_gateway):
            result = await speaker.speak("dev1", "你好")

        assert result is True

    async def test_speak_with_user_config(self):
        channel = MagicMock()
        channel.connected = True
        channel.send_json = AsyncMock()
        channel.send_bytes = AsyncMock()
        fsm = MagicMock()
        fsm.set = AsyncMock()
        user_config = MagicMock()
        user_config.tts_config = {"api_key": "test_key"}
        device = _make_device(channel=channel, fsm=fsm, user_config=user_config)

        speaker, registry, _ = _make_speaker()
        registry.get_by_mac.return_value = device

        mock_session = AsyncMock()
        mock_session.synthesize_audio = _make_synthesize([b"chunk"])
        mock_session.close = AsyncMock()
        mock_gateway = AsyncMock()
        mock_gateway.create_session = AsyncMock(return_value=mock_session)
        mock_gateway.close = AsyncMock()

        with patch("src.use_cases.speaker.create_tts_gateway", return_value=mock_gateway), \
             patch("src.use_cases.speaker.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                tts=MagicMock(api_key="g", resource_id="r", voice_type="v", speed_ratio=1.0,
                              volume_ratio=1.0, pitch_ratio=1.0, enable_pool=False)
            )
            result = await speaker.speak("dev1", "你好")

        assert result is True


# ============================================================
# Speaker.speak_direct
# ============================================================


class TestSpeakDirect:
    """speak_direct 直接通过 channel 播放"""

    async def test_speak_direct_success(self):
        speaker, _, _ = _make_speaker()
        channel = MagicMock()
        channel.connected = True
        channel.send_json = AsyncMock()
        channel.send_bytes = AsyncMock()
        fsm = MagicMock()
        fsm.set = AsyncMock()
        session = MagicMock()

        mock_tts_session = AsyncMock()
        mock_tts_session.synthesize_audio = _make_synthesize([b"chunk"])
        mock_tts_session.close = AsyncMock()
        mock_gateway = AsyncMock()
        mock_gateway.create_session = AsyncMock(return_value=mock_tts_session)
        mock_gateway.close = AsyncMock()

        with patch("src.use_cases.speaker.create_tts_gateway", return_value=mock_gateway):
            result = await speaker.speak_direct(channel, session, fsm, "你好")

        assert result is True


# ============================================================
# Speaker.speak_all
# ============================================================


class TestSpeakAll:
    """speak_all 向所有设备播放"""

    async def test_no_devices(self):
        speaker, registry, _ = _make_speaker()
        registry.get_all_ids.return_value = []
        result = await speaker.speak_all("你好")
        assert result is None  # 无设备时直接返回

    async def test_multiple_devices(self):
        speaker, registry, _ = _make_speaker()
        registry.get_all_ids.return_value = ["dev1", "dev2"]
        registry.get_by_mac.return_value = None  # 设备未找到
        await speaker.speak_all("你好")
        # 应尝试对每个设备调用 speak
        assert registry.get_by_mac.call_count >= 2


# ============================================================
# Speaker.wakeup
# ============================================================


class TestWakeup:
    """wakeup 唤醒设备"""

    async def test_wakeup_device_not_found(self):
        speaker, registry, _ = _make_speaker()
        registry.get_by_mac.return_value = None
        registry.get.return_value = None
        result = await speaker.wakeup("unknown")
        assert result is False

    async def test_wakeup_channel_not_connected(self):
        channel = MagicMock()
        channel.connected = False
        device = _make_device(channel=channel)
        speaker, registry, _ = _make_speaker()
        registry.get_by_mac.return_value = device
        result = await speaker.wakeup("dev1")
        assert result is False

    async def test_wakeup_success(self):
        channel = MagicMock()
        channel.connected = True
        channel.send_json = AsyncMock()
        session = MagicMock()
        session._wake_audio_played = asyncio.Event()
        session._wake_audio_played.set()
        session.start_auto_conversation = AsyncMock()
        fsm = MagicMock()
        device = _make_device(channel=channel, session=session, fsm=fsm)

        speaker, registry, wake_audio = _make_speaker()
        registry.get_by_mac.return_value = device
        wake_audio._get_wakeup_cfg.return_value = False

        with patch("src.use_cases.speaker.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                wakeup=MagicMock(enable_audio=True, audio_play_enabled=False)
            )
            result = await speaker.wakeup("dev1")

        assert result is True
        session.start_auto_conversation.assert_called_once()

    async def test_wakeup_audio_disabled(self):
        channel = MagicMock()
        channel.connected = True
        channel.send_json = AsyncMock()
        session = MagicMock()
        session._wake_audio_played = asyncio.Event()
        session.start_auto_conversation = AsyncMock()
        fsm = MagicMock()
        device = _make_device(channel=channel, session=session, fsm=fsm)

        speaker, registry, wake_audio = _make_speaker()
        registry.get_by_mac.return_value = device

        with patch("src.use_cases.speaker.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                wakeup=MagicMock(enable_audio=False, audio_play_enabled=False)
            )
            result = await speaker.wakeup("dev1")

        assert result is True
        wake_audio.play.assert_not_called()

    async def test_wakeup_exception(self):
        channel = MagicMock()
        channel.connected = True
        channel.send_json = AsyncMock(side_effect=Exception("send error"))
        session = MagicMock()
        device = _make_device(channel=channel, session=session)

        speaker, registry, _ = _make_speaker()
        registry.get_by_mac.return_value = device

        with patch("src.use_cases.speaker.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                wakeup=MagicMock(enable_audio=False, audio_play_enabled=False)
            )
            result = await speaker.wakeup("dev1")

        assert result is False


# ============================================================
# Speaker.wakeup_all
# ============================================================


class TestWakeupAll:
    """wakeup_all 唤醒所有设备"""

    async def test_no_devices(self):
        speaker, registry, _ = _make_speaker()
        registry.get_all_ids.return_value = []
        result = await speaker.wakeup_all()
        assert result is None

    async def test_multiple_devices(self):
        speaker, registry, _ = _make_speaker()
        registry.get_all_ids.return_value = ["dev1", "dev2"]
        registry.get_by_mac.return_value = None
        await speaker.wakeup_all()
        assert registry.get_by_mac.call_count >= 2


# ============================================================
# Speaker.stop
# ============================================================


class TestStop:
    """stop 停止设备"""

    async def test_stop_device_not_found(self):
        speaker, registry, _ = _make_speaker()
        registry.get_by_mac.return_value = None
        registry.get.return_value = None
        result = await speaker.stop("unknown")
        assert result is False

    async def test_stop_channel_not_connected(self):
        channel = MagicMock()
        channel.connected = False
        device = _make_device(channel=channel)
        speaker, registry, _ = _make_speaker()
        registry.get_by_mac.return_value = device
        result = await speaker.stop("dev1")
        assert result is False

    async def test_stop_success(self):
        channel = MagicMock()
        channel.connected = True
        channel.send_json = AsyncMock()
        channel.send_text = AsyncMock()
        session = MagicMock()
        session.runtime.asr_processed = False
        session.drain_asr = AsyncMock()
        session.tts_playing = False
        session.cancel_event = MagicMock()
        session.cancel_event.set = MagicMock()
        fsm = MagicMock()
        fsm.set = AsyncMock()
        device = _make_device(channel=channel, session=session, fsm=fsm)

        speaker, registry, _ = _make_speaker()
        registry.get_by_mac.return_value = device

        result = await speaker.stop("dev1")
        assert result is True
        session.drain_asr.assert_called_once()
        fsm.set.assert_called_with(SessionState.IDLE)

    async def test_stop_with_tts_playing(self):
        channel = MagicMock()
        channel.connected = True
        channel.send_json = AsyncMock()
        channel.send_text = AsyncMock()
        session = MagicMock()
        session.runtime.asr_processed = False
        session.drain_asr = AsyncMock()
        session.tts_playing = True
        session.interrupt = AsyncMock()
        session.cancel_event = MagicMock()
        session.cancel_event.set = MagicMock()
        fsm = MagicMock()
        fsm.set = AsyncMock()
        device = _make_device(channel=channel, session=session, fsm=fsm)

        speaker, registry, _ = _make_speaker()
        registry.get_by_mac.return_value = device

        result = await speaker.stop("dev1")
        assert result is True
        session.interrupt.assert_called_once()

    async def test_stop_exception(self):
        channel = MagicMock()
        channel.connected = True
        channel.send_json = AsyncMock(side_effect=Exception("send error"))
        session = MagicMock()
        session.runtime.asr_processed = False
        session.drain_asr = AsyncMock()
        session.tts_playing = False
        session.cancel_event = MagicMock()
        session.cancel_event.set = MagicMock()
        fsm = MagicMock()
        fsm.set = AsyncMock()
        device = _make_device(channel=channel, session=session, fsm=fsm)

        speaker, registry, _ = _make_speaker()
        registry.get_by_mac.return_value = device

        result = await speaker.stop("dev1")
        assert result is False


# ============================================================
# Speaker.stop_all
# ============================================================


class TestStopAll:
    """stop_all 停止所有设备"""

    async def test_no_devices(self):
        speaker, registry, _ = _make_speaker()
        registry.get_all_ids.return_value = []
        result = await speaker.stop_all()
        assert result is None

    async def test_multiple_devices(self):
        speaker, registry, _ = _make_speaker()
        registry.get_all_ids.return_value = ["dev1", "dev2"]
        registry.get_by_mac.return_value = None
        await speaker.stop_all()
        assert registry.get_by_mac.call_count >= 2


# ============================================================
# Speaker.register_device / unregister_device / get_device / get_all_devices
# ============================================================


class TestDeviceManagement:
    """设备管理方法"""

    async def test_register_device(self):
        speaker, registry, _ = _make_speaker()
        registry.register = AsyncMock()
        channel = MagicMock()
        session = MagicMock()
        fsm = MagicMock()

        await speaker.register_device(
            "dev1", channel, session, fsm,
            mac="mac1", firmware_version="1.0",
        )

        registry.register.assert_called_once_with(
            "dev1", channel, session, fsm,
            user_config=None, asr_client=None,
            mac="mac1", firmware_version="1.0",
        )

    def test_unregister_device(self):
        speaker, registry, _ = _make_speaker()
        speaker.unregister_device("dev1")
        registry.unregister.assert_called_once_with("dev1")

    def test_get_device(self):
        device = _make_device()
        speaker, registry, _ = _make_speaker()
        registry.get_by_mac.return_value = device
        result = speaker.get_device("dev1")
        assert result is device

    def test_get_device_not_found(self):
        speaker, registry, _ = _make_speaker()
        registry.get_by_mac.return_value = None
        registry.get.return_value = None
        result = speaker.get_device("unknown")
        assert result is None

    def test_get_all_devices(self):
        speaker, registry, _ = _make_speaker()
        registry.get_all_ids.return_value = ["dev1", "dev2"]
        result = speaker.get_all_devices()
        assert result == ["dev1", "dev2"]

    def test_resolve_device_by_mac(self):
        device = _make_device()
        speaker, registry, _ = _make_speaker()
        registry.get_by_mac.return_value = device
        result = speaker._resolve_device("dev1")
        assert result is device

    def test_resolve_device_by_id_fallback(self):
        device = _make_device()
        speaker, registry, _ = _make_speaker()
        registry.get_by_mac.return_value = None
        registry.get.return_value = device
        result = speaker._resolve_device("dev1")
        assert result is device


# ============================================================
# 辅助函数
# ============================================================


def _make_synthesize(chunks):
    """构造一个可调用的异步生成器（模拟 session.synthesize_audio(text)）"""
    async def _gen(*args, **kwargs):
        for chunk in chunks:
            yield chunk
    return _gen

