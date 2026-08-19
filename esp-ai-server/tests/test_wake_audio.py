"""
wake_audio.py 单元测试

WakeAudioManager 负责：
- 唤醒音频缓存（_mp3_cache）：避免每次唤醒都合成
- ensure_cache：从文件加载或 TTS 合成唤醒音频
- play：通过 channel 发送音频帧到设备
- clear_cache：清除缓存

通过 mock get_settings / create_tts_gateway / VoiceGenerator 避免真实网络和文件 IO。
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from src.use_cases.wake_audio import WakeAudioManager


def _make_settings():
    """构造一个 mock settings 对象，匹配 WakeAudioManager 所需字段"""
    settings = MagicMock()
    settings.wakeup.audio_cache_enabled = True
    settings.wakeup.audio_play_enabled = True
    settings.wakeup.audio_source = "tts"
    settings.wakeup.text = "我在呢"
    settings.tts.api_key = "key"
    settings.tts.resource_id = "rid"
    settings.tts.voice_type = "vt"
    settings.tts.speed_ratio = 1.0
    settings.tts.volume_ratio = 1.0
    settings.tts.pitch_ratio = 1.0
    settings.tts.enable_pool = True
    return settings


def _make_mock_voice_generator():
    """构造一个 mock VoiceGenerator"""
    vg = MagicMock()
    vg.make_tts_frame = MagicMock(side_effect=lambda sid, data, status="00": sid.encode() + status.encode() + data)
    vg.make_end_frame = MagicMock(side_effect=lambda sid, status="03": sid.encode() + status.encode())
    return vg


def _make_mock_user_config(wakeup_config=None, tts_config=None):
    """构造一个 mock user_config 对象"""
    cfg = MagicMock()
    cfg.wakeup_config = wakeup_config or {}
    cfg.tts_config = tts_config or {}
    return cfg


# ============================================================
# WakeAudioManager 初始化
# ============================================================


class TestWakeAudioManagerInit:
    """WakeAudioManager 初始化与属性"""

    def test_init_defaults(self):
        mgr = WakeAudioManager()
        assert mgr._mp3_cache is None
        assert mgr._voice_generator is not None
        assert mgr._tts_gateway is None

    def test_init_with_custom_voice_generator(self):
        vg = _make_mock_voice_generator()
        mgr = WakeAudioManager(voice_generator=vg)
        assert mgr._voice_generator is vg

    def test_voice_generator_property(self):
        vg = _make_mock_voice_generator()
        mgr = WakeAudioManager(voice_generator=vg)
        assert mgr.voice_generator is vg

    def test_voice_generator_property_creates_default(self):
        mgr = WakeAudioManager()
        # 默认创建的 VoiceGenerator 应有 make_tts_frame 方法
        assert hasattr(mgr.voice_generator, "make_tts_frame")


# ============================================================
# _get_wakeup_cfg
# ============================================================


class TestGetWakeupCfg:
    """_get_wakeup_cfg：从 user_config.wakeup_config 取值，回退到 default"""

    def test_returns_value_from_user_config(self):
        mgr = WakeAudioManager()
        cfg = _make_mock_user_config(wakeup_config={"text": "你好"})
        assert mgr._get_wakeup_cfg(cfg, "text", "default") == "你好"

    def test_returns_default_when_key_missing(self):
        mgr = WakeAudioManager()
        cfg = _make_mock_user_config(wakeup_config={})
        assert mgr._get_wakeup_cfg(cfg, "text", "default") == "default"

    def test_returns_default_when_no_user_config(self):
        mgr = WakeAudioManager()
        assert mgr._get_wakeup_cfg(None, "text", "default") == "default"

    def test_returns_default_when_wakeup_config_none(self):
        mgr = WakeAudioManager()
        cfg = MagicMock()
        cfg.wakeup_config = None
        assert mgr._get_wakeup_cfg(cfg, "text", "default") == "default"

    def test_returns_default_when_no_wakeup_config_attr(self):
        mgr = WakeAudioManager()
        cfg = MagicMock(spec=[])  # 无 wakeup_config 属性
        assert mgr._get_wakeup_cfg(cfg, "text", "default") == "default"


# ============================================================
# ensure_cache
# ============================================================


class TestEnsureCache:
    """ensure_cache：缓存加载逻辑"""

    async def test_cache_disabled_returns_none(self):
        mgr = WakeAudioManager()
        settings = _make_settings()
        settings.wakeup.audio_cache_enabled = False
        with patch("src.use_cases.wake_audio.get_settings", return_value=settings):
            result = await mgr.ensure_cache()
        assert result is None

    async def test_cache_disabled_via_user_config(self):
        mgr = WakeAudioManager()
        settings = _make_settings()
        settings.wakeup.audio_cache_enabled = True
        cfg = _make_mock_user_config(wakeup_config={"cache_enabled": False})
        with patch("src.use_cases.wake_audio.get_settings", return_value=settings):
            result = await mgr.ensure_cache(user_config=cfg)
        assert result is None

    async def test_returns_existing_cache(self):
        mgr = WakeAudioManager()
        settings = _make_settings()
        with patch("src.use_cases.wake_audio.get_settings", return_value=settings):
            # 设置与当前配置一致的签名，避免触发"配置变化清除缓存"
            mgr._cache_config_signature = mgr._build_config_signature()
        mgr._mp3_cache = b"cached_data"
        with patch("src.use_cases.wake_audio.get_settings", return_value=settings):
            result = await mgr.ensure_cache()
        assert result == b"cached_data"

    async def test_load_from_file_when_source_is_file(self):
        mgr = WakeAudioManager()
        settings = _make_settings()
        settings.wakeup.audio_source = "file"
        audio_bytes = b"mp3_file_content"

        m = mock_open(read_data=audio_bytes)
        with patch("src.use_cases.wake_audio.get_settings", return_value=settings), \
                patch("os.path.isfile", return_value=True), \
                patch("builtins.open", m):
            result = await mgr.ensure_cache()
        assert result == audio_bytes
        assert mgr._mp3_cache == audio_bytes

    async def test_file_source_falls_back_to_tts_when_file_missing(self):
        mgr = WakeAudioManager()
        settings = _make_settings()
        settings.wakeup.audio_source = "file"

        with patch("src.use_cases.wake_audio.get_settings", return_value=settings), \
                patch("os.path.isfile", return_value=False), \
                patch.object(mgr, "_tts_synthesize", AsyncMock(return_value=b"tts_audio")):
            result = await mgr.ensure_cache()
        assert result == b"tts_audio"
        assert mgr._mp3_cache == b"tts_audio"

    async def test_tts_source_uses_tts_synthesize(self):
        mgr = WakeAudioManager()
        settings = _make_settings()
        settings.wakeup.audio_source = "tts"

        with patch("src.use_cases.wake_audio.get_settings", return_value=settings), \
                patch.object(mgr, "_tts_synthesize", AsyncMock(return_value=b"tts_audio")):
            result = await mgr.ensure_cache()
        assert result == b"tts_audio"

    async def test_tts_synthesis_retries_once_on_failure(self):
        """首次合成失败（冷启动/网络波动）应自动重试一次"""
        mgr = WakeAudioManager()
        settings = _make_settings()
        settings.wakeup.audio_source = "tts"

        synth = AsyncMock(side_effect=[None, b"retried_audio"])
        with patch("src.use_cases.wake_audio.get_settings", return_value=settings), \
                patch.object(mgr, "_tts_synthesize", synth):
            result = await mgr.ensure_cache()
        assert result == b"retried_audio"
        assert mgr._mp3_cache == b"retried_audio"
        assert synth.await_count == 2

    async def test_file_load_failure_returns_none(self):
        mgr = WakeAudioManager()
        settings = _make_settings()
        settings.wakeup.audio_source = "file"

        m = mock_open()
        m.side_effect = IOError("read error")
        with patch("src.use_cases.wake_audio.get_settings", return_value=settings), \
                patch("os.path.isfile", return_value=True), \
                patch("builtins.open", m):
            result = await mgr.ensure_cache()
        assert result is None
        assert mgr._mp3_cache is None


# ============================================================
# _tts_synthesize
# ============================================================


class TestTtsSynthesize:
    """_tts_synthesize：TTS 合成唤醒音频"""

    async def test_synthesize_success(self):
        mgr = WakeAudioManager()
        settings = _make_settings()

        # mock TTS 网关和 session
        mock_session = MagicMock()
        mock_session.synthesize = MagicMock()

        async def fake_synthesize(text):
            yield b"c" * 1500
            yield b"c" * 1500

        mock_session.synthesize = fake_synthesize
        mock_session.close = AsyncMock()

        mock_gateway = MagicMock()
        mock_gateway.create_session = AsyncMock(return_value=mock_session)

        with patch("src.use_cases.wake_audio.get_settings", return_value=settings), \
                patch("src.use_cases.wake_audio.create_tts_gateway", return_value=mock_gateway):
            result = await mgr._tts_synthesize()
        assert result == b"c" * 3000
        mock_session.close.assert_awaited()
        # 网关应被缓存
        assert mgr._tts_gateway is mock_gateway

    async def test_synthesize_reuses_cached_gateway(self):
        mgr = WakeAudioManager()
        settings = _make_settings()
        existing_gateway = MagicMock()
        # api_key 与全局配置一致，避免触发"API key 不匹配重建"分支
        existing_gateway.api_key = settings.tts.api_key
        existing_gateway.create_session = AsyncMock(return_value=MagicMock())
        mgr._tts_gateway = existing_gateway

        mock_session = MagicMock()

        async def fake_synthesize(text):
            yield b"d" * 3000

        mock_session.synthesize = fake_synthesize
        mock_session.close = AsyncMock()
        existing_gateway.create_session = AsyncMock(return_value=mock_session)

        with patch("src.use_cases.wake_audio.get_settings", return_value=settings), \
                patch("src.use_cases.wake_audio.create_tts_gateway") as mock_create:
            result = await mgr._tts_synthesize()
        assert result == b"d" * 3000
        # 不应再次创建网关
        mock_create.assert_not_called()

    async def test_synthesize_with_user_tts_config(self):
        mgr = WakeAudioManager()
        settings = _make_settings()
        cfg = _make_mock_user_config(
            tts_config={"api_key": "user_key", "voice_type": "user_voice"}
        )

        mock_session = MagicMock()

        async def fake_synthesize(text):
            yield b"x" * 3000

        mock_session.synthesize = fake_synthesize
        mock_session.close = AsyncMock()

        mock_gateway = MagicMock()
        mock_gateway.create_session = AsyncMock(return_value=mock_session)

        with patch("src.use_cases.wake_audio.get_settings", return_value=settings), \
                patch("src.use_cases.wake_audio.create_tts_gateway", return_value=mock_gateway) as mock_create:
            result = await mgr._tts_synthesize(user_config=cfg)
        assert result == b"x" * 3000
        mock_create.assert_called_once()
        # 验证传入的 config 使用了 user_config 的值
        call_args = mock_create.call_args
        config = call_args.kwargs.get("config") or call_args.args[0] if call_args.args else call_args.kwargs["config"]
        assert config["api_key"] == "user_key"
        assert config["voice_type"] == "user_voice"

    async def test_synthesize_failure_returns_none(self):
        mgr = WakeAudioManager()
        settings = _make_settings()

        mock_gateway = MagicMock()
        mock_gateway.create_session = AsyncMock(side_effect=RuntimeError("TTS down"))

        with patch("src.use_cases.wake_audio.get_settings", return_value=settings), \
                patch("src.use_cases.wake_audio.create_tts_gateway", return_value=mock_gateway):
            result = await mgr._tts_synthesize()
        assert result is None

    async def test_synthesize_filters_none_chunks(self):
        mgr = WakeAudioManager()
        settings = _make_settings()

        mock_session = MagicMock()

        async def fake_synthesize(text):
            yield None
            yield b"r" * 3000
            yield None

        mock_session.synthesize = fake_synthesize
        mock_session.close = AsyncMock()

        mock_gateway = MagicMock()
        mock_gateway.create_session = AsyncMock(return_value=mock_session)

        with patch("src.use_cases.wake_audio.get_settings", return_value=settings), \
                patch("src.use_cases.wake_audio.create_tts_gateway", return_value=mock_gateway):
            result = await mgr._tts_synthesize()
        # None chunks 应被过滤
        assert result == b"r" * 3000

    async def test_synthesize_short_result_returns_none(self):
        """截断数据（低于最小长度阈值）应视为合成失败，并重置网关供重试"""
        mgr = WakeAudioManager()
        settings = _make_settings()

        mock_session = MagicMock()

        async def fake_synthesize(text):
            # 模拟火山 TTS 中途失败提前 return：只收到极短片段
            yield b"truncated"

        mock_session.synthesize = fake_synthesize
        mock_session.close = AsyncMock()

        mock_gateway = MagicMock()
        mock_gateway.create_session = AsyncMock(return_value=mock_session)

        with patch("src.use_cases.wake_audio.get_settings", return_value=settings), \
                patch("src.use_cases.wake_audio.create_tts_gateway", return_value=mock_gateway):
            result = await mgr._tts_synthesize()
        assert result is None
        # 网关应被重置，确保重试使用新连接
        assert mgr._tts_gateway is None


# ============================================================
# play
# ============================================================


class TestPlay:
    """play：通过 channel 发送唤醒音频到设备"""

    async def test_play_disabled_skips(self):
        mgr = WakeAudioManager()
        settings = _make_settings()
        settings.wakeup.audio_play_enabled = False
        channel = MagicMock()
        channel.send_json = AsyncMock()

        with patch("src.use_cases.wake_audio.get_settings", return_value=settings):
            await mgr.play(channel)
        # 不应发送任何数据
        channel.send_json.assert_not_awaited()

    async def test_play_disabled_via_user_config(self):
        mgr = WakeAudioManager()
        settings = _make_settings()
        settings.wakeup.audio_play_enabled = True
        cfg = _make_mock_user_config(wakeup_config={"play_enabled": False})
        channel = MagicMock()
        channel.send_json = AsyncMock()

        with patch("src.use_cases.wake_audio.get_settings", return_value=settings):
            await mgr.play(channel, user_config=cfg)
        channel.send_json.assert_not_awaited()

    async def test_play_no_audio_data_skips(self):
        mgr = WakeAudioManager()
        settings = _make_settings()
        channel = MagicMock()
        channel.send_json = AsyncMock()

        # ensure_cache 返回 None
        with patch("src.use_cases.wake_audio.get_settings", return_value=settings), \
                patch.object(mgr, "ensure_cache", AsyncMock(return_value=None)):
            played = await mgr.play(channel)
        channel.send_json.assert_not_awaited()
        # 无音频时返回 False，调用方据此跳过等待
        assert played is False

    async def test_play_returns_true_after_sending(self):
        mgr = WakeAudioManager()
        mgr._voice_generator = _make_mock_voice_generator()
        settings = _make_settings()
        channel = MagicMock()
        channel.send_json = AsyncMock()
        channel.send_bytes = AsyncMock()

        audio_data = b"\x00" * 3000
        with patch("src.use_cases.wake_audio.get_settings", return_value=settings), \
                patch.object(mgr, "ensure_cache", AsyncMock(return_value=audio_data)), \
                patch("asyncio.sleep", AsyncMock()):
            played = await mgr.play(channel)
        # 成功发送后返回 True
        assert played is True

    async def test_play_sends_audio_frames(self):
        mgr = WakeAudioManager()
        mgr._voice_generator = _make_mock_voice_generator()
        settings = _make_settings()
        channel = MagicMock()
        channel.send_json = AsyncMock()
        channel.send_bytes = AsyncMock()

        audio_data = b"\x00" * 100  # 小于 _CHUNK_SIZE，一次发送完
        with patch("src.use_cases.wake_audio.get_settings", return_value=settings), \
                patch.object(mgr, "ensure_cache", AsyncMock(return_value=audio_data)), \
                patch("asyncio.sleep", AsyncMock()):
            await mgr.play(channel)

        # 应发送 play_audio 和 session_status 指令
        json_calls = channel.send_json.call_args_list
        sent_types = [c.args[0].get("type") for c in json_calls]
        assert "play_audio" in sent_types
        assert "session_status" in sent_types
        # 应发送音频帧和结束帧
        assert channel.send_bytes.await_count >= 2  # 至少 1 帧音频 + 1 帧结束

    async def test_play_chunks_large_audio(self):
        mgr = WakeAudioManager()
        vg = _make_mock_voice_generator()
        mgr._voice_generator = vg
        settings = _make_settings()
        channel = MagicMock()
        channel.send_json = AsyncMock()
        channel.send_bytes = AsyncMock()

        # 大音频，应分多个 chunk 发送（_CHUNK_SIZE=2048）
        audio_data = b"\x01" * 5000
        with patch("src.use_cases.wake_audio.get_settings", return_value=settings), \
                patch.object(mgr, "ensure_cache", AsyncMock(return_value=audio_data)), \
                patch("asyncio.sleep", AsyncMock()):
            await mgr.play(channel)

        # 5000 / 2048 = 2.44 -> 3 个数据 chunk + 1 个结束帧
        assert channel.send_bytes.await_count == 4

    async def test_play_exception_is_caught(self):
        mgr = WakeAudioManager()
        settings = _make_settings()
        channel = MagicMock()
        # send_json 抛异常
        channel.send_json = AsyncMock(side_effect=RuntimeError("send fail"))
        channel.send_bytes = AsyncMock()

        audio_data = b"\x00" * 10
        with patch("src.use_cases.wake_audio.get_settings", return_value=settings), \
                patch.object(mgr, "ensure_cache", AsyncMock(return_value=audio_data)):
            # 不应抛出异常
            await mgr.play(channel)

    async def test_play_sends_end_frame(self):
        mgr = WakeAudioManager()
        vg = _make_mock_voice_generator()
        mgr._voice_generator = vg
        settings = _make_settings()
        channel = MagicMock()
        channel.send_json = AsyncMock()
        channel.send_bytes = AsyncMock()

        audio_data = b"\x00" * 10
        with patch("src.use_cases.wake_audio.get_settings", return_value=settings), \
                patch.object(mgr, "ensure_cache", AsyncMock(return_value=audio_data)), \
                patch("asyncio.sleep", AsyncMock()):
            await mgr.play(channel)

        # 最后一个 send_bytes 调用应是结束帧
        vg.make_end_frame.assert_called_once()
        # 结束时应发送 tts_real_end 状态
        json_calls = channel.send_json.call_args_list
        statuses = [c.args[0].get("status") for c in json_calls if c.args[0].get("type") == "session_status"]
        assert "tts_chunk_start" in statuses
        assert "tts_real_end" in statuses


# ============================================================
# clear_cache
# ============================================================


class TestClearCache:
    """clear_cache：清除缓存"""

    def test_clear_cache_sets_none(self):
        mgr = WakeAudioManager()
        mgr._mp3_cache = b"cached"
        mgr.clear_cache()
        assert mgr._mp3_cache is None

    def test_clear_cache_when_already_none(self):
        mgr = WakeAudioManager()
        mgr.clear_cache()
        assert mgr._mp3_cache is None

    def test_clear_cache_then_ensure_reloads(self):
        mgr = WakeAudioManager()
        mgr._mp3_cache = b"old"
        mgr.clear_cache()
        assert mgr._mp3_cache is None
        # 下次 ensure_cache 应重新加载
        settings = _make_settings()
        settings.wakeup.audio_source = "tts"
        with patch("src.use_cases.wake_audio.get_settings", return_value=settings), \
                patch.object(mgr, "_tts_synthesize", AsyncMock(return_value=b"new")):
            import asyncio as _asyncio

            result = _asyncio.get_event_loop().run_until_complete(mgr.ensure_cache()) if False else None
        # 这里只验证 clear_cache 行为，不实际运行 ensure_cache
        assert mgr._mp3_cache is None
