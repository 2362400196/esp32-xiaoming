"""
Config 配置系统单元测试
- Settings 加载
- 环境变量解析
- 配置验证
- 各模块配置
"""
import os
import pytest
from unittest.mock import patch


class TestSettingsBasic:
    """基础配置测试"""

    def test_settings_singleton(self):
        from src.infrastructure.config import get_settings, Settings
        settings1 = get_settings()
        settings2 = get_settings()
        assert settings1 is settings2

    def test_settings_has_asr_config(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert hasattr(settings, "asr")

    def test_settings_has_llm_config(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert hasattr(settings, "llm")

    def test_settings_has_tts_config(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert hasattr(settings, "tts")

    def test_settings_has_server_config(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert hasattr(settings, "server")

    def test_settings_has_log_config(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert hasattr(settings, "log")

    def test_settings_has_auth_config(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert hasattr(settings, "auth")

    def test_settings_has_wakeup_config(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert hasattr(settings, "wakeup")

    def test_settings_has_emotion_config(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert hasattr(settings, "emotion")


class TestServerConfig:
    """Server 配置测试"""

    def test_server_defaults(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert settings.server.host == "0.0.0.0"
        assert settings.server.port == 8088

    def test_server_ws_settings(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert settings.server.ws_max_size > 0
        assert settings.server.ws_ping_interval > 0
        assert settings.server.ws_ping_timeout > 0


class TestASRConfig:
    """ASR 配置测试"""

    def test_asr_provider_defaults(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert settings.asr.provider in ["volcengine", "tencent", "aliyun", "xfyun"]

    def test_asr_volcengine_config(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        if settings.asr.provider == "volcengine":
            assert hasattr(settings.asr, "volcengine_api_key")
            assert hasattr(settings.asr, "tencent_app_id")
            assert hasattr(settings.asr, "max_concurrency")

    def test_asr_timeout(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert settings.asr.no_speech_timeout > 0

    def test_asr_concurrency(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert settings.asr.max_concurrency == 100


class TestLLMConfig:
    """LLM 配置测试"""

    def test_llm_defaults(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert settings.llm.provider in ["openai", "qwen", "deepseek", "ollama"]

    def test_llm_openai_config(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        if settings.llm.provider == "openai":
            assert hasattr(settings.llm, "api_key")
            assert hasattr(settings.llm, "base_url")
            assert hasattr(settings.llm, "model")

    def test_llm_temperature(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert 0 <= settings.llm.temperature <= 2

    def test_llm_max_tokens(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert settings.llm.max_tokens > 0


class TestTTSConfig:
    """TTS 配置测试"""

    def test_tts_provider_defaults(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert settings.tts.provider in ["volcengine", "cosy", "azure"]

    def test_tts_volcengine_config(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        if settings.tts.provider == "volcengine":
            assert hasattr(settings.tts, "api_key")
            assert hasattr(settings.tts, "api_key")
            assert hasattr(settings.tts, "resource_id")

    def test_tts_voice_type(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert hasattr(settings.tts, "voice_type")
        assert isinstance(settings.tts.voice_type, str)

    def test_tts_speed_ratio(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert settings.tts.speed_ratio == 1.0


class TestAuthConfig:
    """Auth 配置测试"""

    def test_auth_defaults(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert hasattr(settings.auth, "enabled")
        assert isinstance(settings.auth.enabled, bool)


class TestLogConfig:
    """Log 配置测试"""

    def test_log_level(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert settings.log.level.value in ["DEBUG", "INFO", "WARNING", "ERROR"]

    def test_log_format(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert settings.log.format != ""

    def test_log_file_path(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert hasattr(settings.log, "file_path")


class TestWakeupConfig:
    """Wakeup 配置测试"""

    def test_wakeup_defaults(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert hasattr(settings.wakeup, "enable_audio")
        assert hasattr(settings.wakeup, "audio_cache_enabled")


class TestEmotionConfig:
    """Emotion 配置测试"""

    def test_emotion_defaults(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        assert hasattr(settings.emotion, "enabled")


class TestValidateConfig:
    """配置验证测试"""

    def test_validate_config_returns_list(self):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        result = settings.validate_config()
        assert isinstance(result, list)


class TestConstants:
    """常量测试"""

    def test_sid_connected(self):
        from src.infrastructure.config import SID_CONNECTED
        assert SID_CONNECTED == "0001"

    def test_sid_tts(self):
        from src.infrastructure.config import SID_TTS
        assert SID_TTS == "0010"

    def test_sid_wake(self):
        from src.infrastructure.config import SID_WAKE
        assert SID_WAKE == "1001"

    def test_sid_rest(self):
        from src.infrastructure.config import SID_REST
        assert SID_REST == "1002"

    def test_screen_dimensions(self):
        from src.infrastructure.config import SCREEN_WIDTH, SCREEN_HEIGHT
        assert SCREEN_WIDTH > 0
        assert SCREEN_HEIGHT > 0


# ============================================================
# 以下为新增测试 —— 覆盖 reset_settings / 环境变量迁移 /
# validate_config 各 provider / MCPConfig / PerformanceConfig /
# SessionConfig / 默认系统提示词等
# ============================================================


class TestSettingsSingleton:
    """Settings 单例与 reset_settings 测试"""

    def test_reset_settings_clears_singleton(self):
        """reset_settings 后 get_settings 应返回新实例"""
        from src.infrastructure.config import get_settings, reset_settings
        s1 = get_settings()
        reset_settings()
        s2 = get_settings()
        assert s1 is not s2
        # 清理：重置回单例状态
        reset_settings()

    def test_get_settings_returns_same_after_reset(self):
        """reset_settings 后连续两次 get_settings 返回同一实例"""
        from src.infrastructure.config import get_settings, reset_settings
        reset_settings()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_get_compat_settings_returns_settings(self):
        """_get_compat_settings 返回 Settings 实例"""
        from src.infrastructure.config import _get_compat_settings, Settings
        s = _get_compat_settings()
        assert isinstance(s, Settings)


class TestEnvVarMigration:
    """环境变量迁移测试 —— model_post_init 将扁平环境变量迁移到嵌套配置"""

    def test_llm_api_key_migrates(self, monkeypatch):
        """LLM_API_KEY → llm.api_key"""
        monkeypatch.setenv("LLM_API_KEY", "test-llm-key-123")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.llm.api_key == "test-llm-key-123"

    def test_llm_base_url_migrates(self, monkeypatch):
        """LLM_BASE_URL → llm.base_url"""
        monkeypatch.setenv("LLM_BASE_URL", "https://api.test.com/v1")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.llm.base_url == "https://api.test.com/v1"

    def test_llm_model_migrates(self, monkeypatch):
        """LLM_MODEL → llm.model"""
        monkeypatch.setenv("LLM_MODEL", "gpt-test-4")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.llm.model == "gpt-test-4"

    def test_llm_system_prompt_migrates(self, monkeypatch):
        """LLM_SYSTEM_PROMPT → llm.system_prompt（覆盖默认提示词）"""
        monkeypatch.setenv("LLM_SYSTEM_PROMPT", "你是一个测试助手")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.llm.system_prompt == "你是一个测试助手"

    def test_asr_provider_migrates(self, monkeypatch):
        """ASR_PROVIDER → asr.provider"""
        monkeypatch.setenv("ASR_PROVIDER", "tencent")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.asr.provider == "tencent"

    def test_asr_volcengine_api_key_migrates(self, monkeypatch):
        """ASR_VOLCENGINE_API_KEY → asr.volcengine_api_key"""
        monkeypatch.setenv("ASR_VOLCENGINE_API_KEY", "asr-volc-key")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.asr.volcengine_api_key == "asr-volc-key"

    def test_asr_tencent_secret_key_migrates(self, monkeypatch):
        """ASR_TENCENT_SECRET_KEY → asr.tencent_secret_key"""
        monkeypatch.setenv("ASR_TENCENT_SECRET_KEY", "tencent-secret")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.asr.tencent_secret_key == "tencent-secret"

    def test_asr_no_speech_timeout_migrates(self, monkeypatch):
        """ASR_NO_SPEECH_TIMEOUT → asr.no_speech_timeout"""
        monkeypatch.setenv("ASR_NO_SPEECH_TIMEOUT", "10")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.asr.no_speech_timeout == 10

    def test_asr_silence_timeout_migrates(self, monkeypatch):
        """ASR_SILENCE_TIMEOUT → asr.silence_timeout"""
        monkeypatch.setenv("ASR_SILENCE_TIMEOUT", "5")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.asr.silence_timeout == 5

    def test_tts_volcengine_api_key_migrates(self, monkeypatch):
        """TTS_VOLCENGINE_API_KEY → tts.api_key"""
        monkeypatch.setenv("TTS_VOLCENGINE_API_KEY", "tts-volc-key")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.tts.api_key == "tts-volc-key"

    def test_tts_volcengine_voice_type_migrates(self, monkeypatch):
        """TTS_VOLCENGINE_VOICE_TYPE → tts.voice_type"""
        monkeypatch.setenv("TTS_VOLCENGINE_VOICE_TYPE", "zh_female_test")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.tts.voice_type == "zh_female_test"

    def test_tts_volcengine_speed_parses_float(self, monkeypatch):
        """TTS_VOLCENGINE_SPEED → tts.speed_ratio（字符串解析为 float）"""
        monkeypatch.setenv("TTS_VOLCENGINE_SPEED", "1.5")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.tts.speed_ratio == 1.5

    def test_tts_volcengine_volume_parses_float(self, monkeypatch):
        """TTS_VOLCENGINE_VOLUME → tts.volume_ratio"""
        monkeypatch.setenv("TTS_VOLCENGINE_VOLUME", "0.8")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.tts.volume_ratio == 0.8

    def test_tts_volcengine_pitch_parses_float(self, monkeypatch):
        """TTS_VOLCENGINE_PITCH → tts.pitch_ratio"""
        monkeypatch.setenv("TTS_VOLCENGINE_PITCH", "1.2")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.tts.pitch_ratio == 1.2

    def test_tts_speed_invalid_value_ignored(self, monkeypatch):
        """TTS_VOLCENGINE_SPEED 无效值时保持默认 1.0"""
        monkeypatch.setenv("TTS_VOLCENGINE_SPEED", "not-a-number")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.tts.speed_ratio == 1.0

    def test_tts_volume_invalid_value_ignored(self, monkeypatch):
        """TTS_VOLCENGINE_VOLUME 无效值时保持默认 1.0"""
        monkeypatch.setenv("TTS_VOLCENGINE_VOLUME", "invalid")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.tts.volume_ratio == 1.0

    def test_tts_pitch_invalid_value_ignored(self, monkeypatch):
        """TTS_VOLCENGINE_PITCH 无效值时保持默认 1.0"""
        monkeypatch.setenv("TTS_VOLCENGINE_PITCH", "bad")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.tts.pitch_ratio == 1.0

    def test_host_port_migrates(self, monkeypatch):
        """HOST/PORT → server.host/server.port"""
        monkeypatch.setenv("HOST", "127.0.0.1")
        monkeypatch.setenv("PORT", "9999")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.server.host == "127.0.0.1"
        assert s.server.port == 9999

    def test_debug_log_level_migrates_valid(self, monkeypatch):
        """DEBUG_LOG_LEVEL → log.level（有效值）"""
        monkeypatch.setenv("DEBUG_LOG_LEVEL", "debug")
        from src.infrastructure.config import Settings, LogLevel
        s = Settings()
        assert s.log.level == LogLevel.DEBUG

    def test_debug_log_level_migrates_warning(self, monkeypatch):
        """DEBUG_LOG_LEVEL=WARNING → log.level"""
        monkeypatch.setenv("DEBUG_LOG_LEVEL", "WARNING")
        from src.infrastructure.config import Settings, LogLevel
        s = Settings()
        assert s.log.level == LogLevel.WARNING

    def test_debug_log_level_invalid_ignored(self, monkeypatch):
        """DEBUG_LOG_LEVEL 无效值时保持默认 INFO"""
        monkeypatch.setenv("DEBUG_LOG_LEVEL", "INVALID_LEVEL")
        from src.infrastructure.config import Settings, LogLevel
        s = Settings()
        assert s.log.level == LogLevel.INFO

    def test_mcp_servers_json_migrates(self, monkeypatch):
        """MCP_SERVERS_JSON → mcp.servers_json"""
        monkeypatch.setenv("MCP_SERVERS_JSON", '{"server1": {"command": "cmd"}}')
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.mcp.servers_json == '{"server1": {"command": "cmd"}}'

    def test_server_emotion_enabled_false(self, monkeypatch):
        """SERVER_EMOTION_ENABLED=false → emotion.enabled=False"""
        monkeypatch.setenv("SERVER_EMOTION_ENABLED", "false")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.emotion.enabled is False

    def test_server_emotion_enabled_true(self, monkeypatch):
        """SERVER_EMOTION_ENABLED=true → emotion.enabled=True"""
        monkeypatch.setenv("SERVER_EMOTION_ENABLED", "true")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.emotion.enabled is True

    def test_perf_global_max_concurrent_sessions_migrates(self, monkeypatch):
        """PERF_GLOBAL_MAX_CONCURRENT_SESSIONS → performance.global_max_concurrent_sessions"""
        monkeypatch.setenv("PERF_GLOBAL_MAX_CONCURRENT_SESSIONS", "1000")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.performance.global_max_concurrent_sessions == 1000

    def test_perf_enable_global_concurrency_limit_false(self, monkeypatch):
        """PERF_ENABLE_GLOBAL_CONCURRENCY_LIMIT=false → performance.enable_global_concurrency_limit=False"""
        monkeypatch.setenv("PERF_ENABLE_GLOBAL_CONCURRENCY_LIMIT", "false")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.performance.enable_global_concurrency_limit is False

    def test_perf_process_pool_max_workers_migrates(self, monkeypatch):
        """PERF_PROCESS_POOL_MAX_WORKERS → performance.process_pool_max_workers"""
        monkeypatch.setenv("PERF_PROCESS_POOL_MAX_WORKERS", "16")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.performance.process_pool_max_workers == 16

    def test_perf_audio_queue_max_size_migrates(self, monkeypatch):
        """PERF_AUDIO_QUEUE_MAX_SIZE → performance.audio_queue_max_size"""
        monkeypatch.setenv("PERF_AUDIO_QUEUE_MAX_SIZE", "500")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.performance.audio_queue_max_size == 500

    def test_perf_send_queue_max_size_migrates(self, monkeypatch):
        """PERF_SEND_QUEUE_MAX_SIZE → performance.send_queue_max_size"""
        monkeypatch.setenv("PERF_SEND_QUEUE_MAX_SIZE", "1000")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.performance.send_queue_max_size == 1000

    def test_perf_rate_limit_global_rpm_migrates(self, monkeypatch):
        """PERF_RATE_LIMIT_GLOBAL_RPM → performance.rate_limit_global_rpm"""
        monkeypatch.setenv("PERF_RATE_LIMIT_GLOBAL_RPM", "5000")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.performance.rate_limit_global_rpm == 5000

    def test_auth_enabled_migrates(self, monkeypatch):
        """AUTH_ENABLED → auth.enabled"""
        monkeypatch.setenv("AUTH_ENABLED", "false")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.auth.enabled is False

    def test_auth_api_key_migrates(self, monkeypatch):
        """AUTH_API_KEY → auth.api_key"""
        monkeypatch.setenv("AUTH_API_KEY", "my-secret-key")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.auth.api_key == "my-secret-key"

    def test_wakeup_text_migrates(self, monkeypatch):
        """WAKEUP_TEXT → wakeup.text"""
        monkeypatch.setenv("WAKEUP_TEXT", "你好小智")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.wakeup.text == "你好小智"

    def test_log_format_migrates(self, monkeypatch):
        """LOG_FORMAT → log.format（仅当默认为 console 时覆盖）"""
        monkeypatch.setenv("LOG_FORMAT", "json")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.log.format == "json"

    def test_rate_limit_max_rpm_migrates(self, monkeypatch):
        """RATE_LIMIT_MAX_RPM → rate_limit.max_rpm"""
        monkeypatch.setenv("RATE_LIMIT_MAX_RPM", "120")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.rate_limit.max_rpm == 120

    def test_shutdown_grace_period_migrates(self, monkeypatch):
        """SHUTDOWN_GRACE_PERIOD → shutdown.grace_period"""
        monkeypatch.setenv("SHUTDOWN_GRACE_PERIOD", "30")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.shutdown.grace_period == 30

    def test_ota_enabled_false_migrates(self, monkeypatch):
        """OTA_ENABLED=false → ota.enabled=False"""
        monkeypatch.setenv("OTA_ENABLED", "false")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.ota.enabled is False

    def test_ota_version_migrates(self, monkeypatch):
        """OTA_VERSION → ota.version"""
        monkeypatch.setenv("OTA_VERSION", "2.0.0")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.ota.version == "2.0.0"

    def test_asr_pool_disabled_migrates(self, monkeypatch):
        """ASR_POOL_ENABLED=false → asr.enable_pool=False"""
        monkeypatch.setenv("ASR_POOL_ENABLED", "false")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.asr.enable_pool is False

    def test_tts_pool_disabled_migrates(self, monkeypatch):
        """TTS_POOL_ENABLED=false → tts.enable_pool=False"""
        monkeypatch.setenv("TTS_POOL_ENABLED", "false")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.tts.enable_pool is False

    def test_llm_memory_disabled_migrates(self, monkeypatch):
        """LLM_MEMORY_ENABLED=false → llm.memory_enabled=False"""
        monkeypatch.setenv("LLM_MEMORY_ENABLED", "false")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.llm.memory_enabled is False

    def test_llm_memory_max_messages_migrates(self, monkeypatch):
        """LLM_MEMORY_MAX_MESSAGES → llm.memory_max_messages"""
        monkeypatch.setenv("LLM_MEMORY_MAX_MESSAGES", "50")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.llm.memory_max_messages == 50

    def test_music_api_url_migrates(self, monkeypatch):
        """MUSIC_API_URL → music.api_url"""
        monkeypatch.setenv("MUSIC_API_URL", "http://music.test.com")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.music.api_url == "http://music.test.com"

    def test_lyrics_offset_migrates(self, monkeypatch):
        """LYRICS_OFFSET → music.lyrics_offset"""
        monkeypatch.setenv("LYRICS_OFFSET", "500")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.music.lyrics_offset == 500


class TestValidateConfigProviders:
    """validate_config 各 ASR provider 测试"""

    def _make_settings(self):
        """构造 Settings 实例（从 .env 加载），后续手动覆盖字段"""
        from src.infrastructure.config import Settings
        s = Settings()
        # 确保 single 模式下检查密钥（.env 可能配置了 multi 模式）
        s.deploy_mode = "single"
        return s

    def test_missing_llm_key(self):
        """缺少 LLM_API_KEY 时返回对应错误"""
        s = self._make_settings()
        s.llm.api_key = ""
        s.tts.api_key = "has-tts-key"
        s.asr.provider = "tencent"
        s.asr.tencent_secret_key = "has-asr-key"
        result = s.validate_config()
        assert "LLM_API_KEY" in result

    def test_missing_tts_key(self):
        """缺少 TTS_API_KEY 时返回对应错误"""
        s = self._make_settings()
        s.llm.api_key = "has-llm-key"
        s.tts.api_key = ""
        s.asr.provider = "tencent"
        s.asr.tencent_secret_key = "has-asr-key"
        result = s.validate_config()
        assert "TTS_API_KEY" in result

    def test_tencent_missing_secret_key(self):
        """tencent provider 缺少 secret_key"""
        s = self._make_settings()
        s.llm.api_key = "k"
        s.tts.api_key = "k"
        s.asr.provider = "tencent"
        s.asr.tencent_secret_key = ""
        result = s.validate_config()
        assert "ASR_TENCENT_SECRET_KEY" in result

    def test_tencent_all_configured(self):
        """tencent provider 全部配置正确"""
        s = self._make_settings()
        s.llm.api_key = "k"
        s.tts.api_key = "k"
        s.asr.provider = "tencent"
        s.asr.tencent_secret_key = "k"
        result = s.validate_config()
        assert result == []

    def test_volcengine_missing_api_key(self):
        """volcengine provider 缺少 api_key"""
        s = self._make_settings()
        s.llm.api_key = "k"
        s.tts.api_key = "k"
        s.asr.provider = "volcengine"
        s.asr.volcengine_api_key = ""
        result = s.validate_config()
        assert "ASR_VOLCENGINE_API_KEY" in result

    def test_volcengine_all_configured(self):
        """volcengine provider 全部配置正确"""
        s = self._make_settings()
        s.llm.api_key = "k"
        s.tts.api_key = "k"
        s.asr.provider = "volcengine"
        s.asr.volcengine_api_key = "k"
        result = s.validate_config()
        assert result == []

    def test_aliyun_missing_access_key(self):
        """aliyun provider 缺少 access_key_id"""
        s = self._make_settings()
        s.llm.api_key = "k"
        s.tts.api_key = "k"
        s.asr.provider = "aliyun"
        s.asr.aliyun_access_key_id = ""
        result = s.validate_config()
        assert "ASR_ALIYUN_ACCESS_KEY_ID" in result

    def test_aliyun_all_configured(self):
        """aliyun provider 全部配置正确"""
        s = self._make_settings()
        s.llm.api_key = "k"
        s.tts.api_key = "k"
        s.asr.provider = "aliyun"
        s.asr.aliyun_access_key_id = "k"
        result = s.validate_config()
        assert result == []

    def test_xunfei_missing_app_id(self):
        """xunfei provider 缺少 app_id"""
        s = self._make_settings()
        s.llm.api_key = "k"
        s.tts.api_key = "k"
        s.asr.provider = "xunfei"
        s.asr.xunfei_app_id = ""
        result = s.validate_config()
        assert "ASR_XUNFEI_APP_ID" in result

    def test_xunfei_all_configured(self):
        """xunfei provider 全部配置正确"""
        s = self._make_settings()
        s.llm.api_key = "k"
        s.tts.api_key = "k"
        s.asr.provider = "xunfei"
        s.asr.xunfei_app_id = "k"
        result = s.validate_config()
        assert result == []

    def test_unknown_provider_no_asr_error(self):
        """未知 provider 不检查 ASR 配置（不返回 ASR 错误）"""
        s = self._make_settings()
        s.llm.api_key = "k"
        s.tts.api_key = "k"
        s.asr.provider = "unknown_provider"
        result = s.validate_config()
        assert result == []

    def test_missing_llm_and_tts_and_asr(self):
        """同时缺少 LLM、TTS、ASR 配置"""
        s = self._make_settings()
        s.llm.api_key = ""
        s.tts.api_key = ""
        s.asr.provider = "volcengine"
        s.asr.volcengine_api_key = ""
        result = s.validate_config()
        assert "LLM_API_KEY" in result
        assert "TTS_API_KEY" in result
        assert "ASR_VOLCENGINE_API_KEY" in result


class TestMCPConfig:
    """MCPConfig.get_servers 测试"""

    def test_get_servers_valid_json(self):
        """有效 JSON 返回解析后的字典"""
        from src.infrastructure.config import MCPConfig
        cfg = MCPConfig(servers_json='{"server1": {"command": "cmd"}}')
        result = cfg.get_servers()
        assert result == {"server1": {"command": "cmd"}}

    def test_get_servers_invalid_json(self):
        """无效 JSON 返回空字典"""
        from src.infrastructure.config import MCPConfig
        cfg = MCPConfig(servers_json='invalid json {{{')
        result = cfg.get_servers()
        assert result == {}

    def test_get_servers_empty_string(self):
        """空字符串返回空字典"""
        from src.infrastructure.config import MCPConfig
        cfg = MCPConfig(servers_json='')
        result = cfg.get_servers()
        assert result == {}

    def test_get_servers_default(self):
        """默认值（空字符串）返回空字典"""
        from src.infrastructure.config import MCPConfig
        cfg = MCPConfig()
        assert cfg.servers_json == ""
        result = cfg.get_servers()
        assert result == {}

    def test_get_servers_complex_json(self):
        """复杂 JSON 结构正确解析"""
        from src.infrastructure.config import MCPConfig
        json_str = '{"amap": {"type": "streamable_http", "url": "https://example.com/mcp"}, "local": {"command": "python", "args": ["-m", "server"]}}'
        cfg = MCPConfig(servers_json=json_str)
        result = cfg.get_servers()
        assert "amap" in result
        assert "local" in result
        assert result["amap"]["type"] == "streamable_http"
        assert result["local"]["command"] == "python"


class TestPerformanceConfig:
    """PerformanceConfig 默认值测试"""

    def test_defaults(self):
        """PerformanceConfig 所有默认值正确"""
        from src.infrastructure.config import PerformanceConfig
        cfg = PerformanceConfig()
        assert cfg.global_max_concurrent_sessions == 500
        assert cfg.enable_global_concurrency_limit is True
        assert cfg.audio_queue_max_size == 200
        assert cfg.send_queue_max_size == 500
        assert cfg.max_messages_per_session == 100
        assert cfg.rate_limit_global_rpm == 3000
        assert cfg.process_pool_max_workers == 8

    def test_custom_values(self):
        """PerformanceConfig 自定义值"""
        from src.infrastructure.config import PerformanceConfig
        cfg = PerformanceConfig(
            global_max_concurrent_sessions=1000,
            enable_global_concurrency_limit=False,
            process_pool_max_workers=16,
        )
        assert cfg.global_max_concurrent_sessions == 1000
        assert cfg.enable_global_concurrency_limit is False
        assert cfg.process_pool_max_workers == 16


class TestSessionConfig:
    """SessionConfig TTS 播放超时配置测试"""

    def test_defaults(self):
        """SessionConfig TTS 播放超时默认值"""
        from src.infrastructure.config import SessionConfig
        cfg = SessionConfig()
        assert cfg.max_sessions == 1000
        assert cfg.timeout == 3600.0
        assert cfg.idle_timeout == 300.0
        assert cfg.enable_auto_conversation is True
        assert cfg.tts_playback_base_timeout == 30.0
        assert cfg.tts_playback_max_timeout == 300.0
        assert cfg.tts_playback_duration_multiplier == 1.5

    def test_custom_tts_playback_config(self):
        """SessionConfig 自定义 TTS 播放超时"""
        from src.infrastructure.config import SessionConfig
        cfg = SessionConfig(
            tts_playback_base_timeout=60.0,
            tts_playback_max_timeout=600.0,
            tts_playback_duration_multiplier=2.0,
        )
        assert cfg.tts_playback_base_timeout == 60.0
        assert cfg.tts_playback_max_timeout == 600.0
        assert cfg.tts_playback_duration_multiplier == 2.0


class TestDefaultSystemPrompt:
    """默认系统提示词测试"""

    def test_default_prompt_not_empty(self):
        """_DEFAULT_SYSTEM_PROMPT 不为空"""
        from src.infrastructure.config import _DEFAULT_SYSTEM_PROMPT
        assert _DEFAULT_SYSTEM_PROMPT != ""
        assert len(_DEFAULT_SYSTEM_PROMPT) > 50

    def test_default_prompt_contains_key_instructions(self):
        """_DEFAULT_SYSTEM_PROMPT 包含关键指令"""
        from src.infrastructure.config import _DEFAULT_SYSTEM_PROMPT
        assert "TTS" in _DEFAULT_SYSTEM_PROMPT or "语音" in _DEFAULT_SYSTEM_PROMPT
        assert "情绪" in _DEFAULT_SYSTEM_PROMPT

    def test_default_prompt_applied_to_settings(self):
        """Settings 构造后 llm.system_prompt 使用默认值"""
        from src.infrastructure.config import Settings, _DEFAULT_SYSTEM_PROMPT
        s = Settings()
        assert s.llm.system_prompt == _DEFAULT_SYSTEM_PROMPT

    def test_custom_prompt_overrides_default(self, monkeypatch):
        """LLM_SYSTEM_PROMPT 环境变量覆盖默认提示词"""
        monkeypatch.setenv("LLM_SYSTEM_PROMPT", "自定义提示词")
        from src.infrastructure.config import Settings
        s = Settings()
        assert s.llm.system_prompt == "自定义提示词"


class TestLogLevel:
    """LogLevel 枚举测试"""

    def test_log_level_values(self):
        """LogLevel 枚举值正确"""
        from src.infrastructure.config import LogLevel
        assert LogLevel.DEBUG == "DEBUG"
        assert LogLevel.INFO == "INFO"
        assert LogLevel.WARNING == "WARNING"
        assert LogLevel.ERROR == "ERROR"
        assert LogLevel.CRITICAL == "CRITICAL"

    def test_log_level_is_str_enum(self):
        """LogLevel 是 str 枚举"""
        from src.infrastructure.config import LogLevel
        assert isinstance(LogLevel.INFO, str)
        assert LogLevel.INFO == "INFO"


class TestAdditionalConfigModels:
    """其他配置模型默认值测试"""

    def test_audio_config_defaults(self):
        """AudioConfig 默认值"""
        from src.infrastructure.config import AudioConfig
        cfg = AudioConfig()
        assert cfg.sample_rate == 16000
        assert cfg.channels == 1
        assert cfg.sample_width == 2
        assert cfg.format == "pcm"

    def test_ota_config_defaults(self):
        """OTAConfig 默认值"""
        from src.infrastructure.config import OTAConfig
        cfg = OTAConfig()
        assert cfg.enabled is True
        assert cfg.bin_id == ""
        assert cfg.is_official == "0"

    def test_shutdown_config_defaults(self):
        """ShutdownConfig 默认值"""
        from src.infrastructure.config import ShutdownConfig
        cfg = ShutdownConfig()
        assert cfg.grace_period == 5

    def test_rate_limit_config_defaults(self):
        """RateLimitConfig 默认值"""
        from src.infrastructure.config import RateLimitConfig
        cfg = RateLimitConfig()
        assert cfg.max_rpm == 0

    def test_remote_config_defaults(self):
        """RemoteConfigSettings 默认值"""
        from src.infrastructure.config import RemoteConfigSettings
        cfg = RemoteConfigSettings()
        assert cfg.enabled is False
        assert cfg.cache_ttl == 300
        assert cfg.refresh_interval == 60
        assert cfg.timeout == 10.0

    def test_music_config_defaults(self):
        """MusicConfig 默认值"""
        from src.infrastructure.config import MusicConfig
        cfg = MusicConfig()
        assert cfg.api_url == ""
        assert cfg.lyrics_offset == 0

    def test_wakeup_config_defaults(self):
        """WakeupConfig 默认值"""
        from src.infrastructure.config import WakeupConfig
        cfg = WakeupConfig()
        assert cfg.text == "我在呢"
        assert cfg.enable_audio is True
        assert cfg.audio_cache_enabled is True
        assert cfg.audio_play_enabled is True
        assert cfg.audio_source == "file"
        assert cfg.play_on_next_round is False

    def test_emotion_config_defaults(self):
        """EmotionConfig 默认值"""
        from src.infrastructure.config import EmotionConfig
        cfg = EmotionConfig()
        assert cfg.enabled is False
        assert cfg.gif_dir == "emos"
        assert cfg.static_dir == "static_emos"

    def test_server_config_defaults(self):
        """ServerConfig 默认值"""
        from src.infrastructure.config import ServerConfig
        cfg = ServerConfig()
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 8088
        assert cfg.workers == 1
        assert cfg.reload is False
        assert cfg.ws_max_size == 20 * 1024 * 1024

    def test_auth_config_defaults(self):
        """AuthConfig 默认值"""
        from src.infrastructure.config import AuthConfig
        cfg = AuthConfig()
        # 安全优先：认证默认开启
        assert cfg.enabled is True
        assert cfg.api_key == ""
        assert cfg.admin_api_key == ""
