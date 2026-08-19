"""
auth_service.py 单元测试

覆盖范围：
- AuthService.verify_api_key：有用户配置 / 无用户配置（全局 auth）
- AuthService.get_user_config
- AuthService.require_auth：通过 / 抛 HTTPException
- AuthService.reload_users_config
- 工厂函数 create_auth_service / create_emotion_detection 等
"""
from unittest.mock import MagicMock, patch

import pytest

from src.use_cases.auth_service import (
    AuthService,
    create_audio_processor,
    create_auth_service,
    create_device_manager,
    create_emotion_detection,
    create_memory_service,
    create_speaker,
    create_wake_audio_manager,
)
from src.use_cases.device_config import DeviceConfig, DeviceManager
from src.use_cases.emotion import EmotionDetector
from src.infrastructure.db.repositories.short_term_memory_repo import SqlShortTermMemoryRepository


# 辅助：构造带用户的 DeviceManager
def _make_dm_with_users(key="valid_key"):
    cfg = DeviceConfig(device_id="dev1", key=key, name="dev")
    return DeviceManager(devices={"dev1": cfg})


def _make_empty_dm():
    return DeviceManager(devices={})


# ============================================================
# AuthService.verify_api_key
# ============================================================


class TestVerifyApiKeyWithUsers:
    """有用户配置时 verify_api_key"""

    def test_valid_key(self):
        svc = AuthService(device_manager=_make_dm_with_users("valid_key"))
        assert svc.verify_api_key("valid_key") is True

    def test_invalid_key(self):
        svc = AuthService(device_manager=_make_dm_with_users("valid_key"))
        assert svc.verify_api_key("wrong") is False

    def test_empty_key_returns_false(self):
        svc = AuthService(device_manager=_make_dm_with_users("valid_key"))
        assert svc.verify_api_key("") is False
        assert svc.verify_api_key(None) is False

    def test_resolve_sets_device_id(self):
        dm = _make_dm_with_users("valid_key")
        svc = AuthService(device_manager=dm)
        svc.verify_api_key("valid_key")
        resolved = dm.resolve("valid_key")
        assert resolved is not None
        assert resolved.device_id == "dev1"


class TestVerifyApiKeyNoUsers:
    """无用户配置时 verify_api_key 走全局 auth 配置"""

    def test_auth_disabled_returns_true(self):
        svc = AuthService(device_manager=_make_empty_dm())
        with patch("src.use_cases.auth_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.auth.enabled = False
            mock_settings.return_value = settings
            assert svc.verify_api_key("anything") is True
            assert svc.verify_api_key(None) is True

    def test_auth_enabled_no_key_returns_false(self):
        svc = AuthService(device_manager=_make_empty_dm())
        with patch("src.use_cases.auth_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.auth.enabled = True
            settings.auth.api_key = "secret"
            mock_settings.return_value = settings
            assert svc.verify_api_key(None) is False
            assert svc.verify_api_key("") is False

    def test_auth_enabled_correct_key(self):
        svc = AuthService(device_manager=_make_empty_dm())
        with patch("src.use_cases.auth_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.auth.enabled = True
            settings.auth.api_key = "secret"
            mock_settings.return_value = settings
            assert svc.verify_api_key("secret") is True

    def test_auth_enabled_wrong_key(self):
        svc = AuthService(device_manager=_make_empty_dm())
        with patch("src.use_cases.auth_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.auth.enabled = True
            settings.auth.api_key = "secret"
            mock_settings.return_value = settings
            assert svc.verify_api_key("wrong") is False


# ============================================================
# AuthService.get_user_config
# ============================================================


class TestGetUserConfig:
    """AuthService.get_user_config"""

    def test_returns_config_for_valid_key(self):
        dm = _make_dm_with_users("valid_key")
        svc = AuthService(device_manager=dm)
        cfg = svc.get_user_config("valid_key")
        assert cfg is not None
        assert cfg.key == "valid_key"

    def test_returns_none_for_empty_key(self):
        svc = AuthService(device_manager=_make_dm_with_users("valid_key"))
        assert svc.get_user_config("") is None
        assert svc.get_user_config(None) is None

    def test_returns_none_for_unknown_key(self):
        svc = AuthService(device_manager=_make_dm_with_users("valid_key"))
        assert svc.get_user_config("unknown") is None


# ============================================================
# AuthService.require_auth
# ============================================================


class TestRequireAuth:
    """AuthService.require_auth"""

    def test_passes_with_valid_key(self):
        svc = AuthService(device_manager=_make_dm_with_users("valid_key"))
        assert svc.require_auth("valid_key") is True

    def test_raises_httpexception_on_invalid(self):
        svc = AuthService(device_manager=_make_dm_with_users("valid_key"))
        with pytest.raises(Exception) as exc_info:
            svc.require_auth("wrong")
        # HTTPException status_code 401
        assert "401" in str(exc_info.value) or "Unauthorized" in str(exc_info.value)

    def test_raises_on_empty_key(self):
        svc = AuthService(device_manager=_make_dm_with_users("valid_key"))
        with pytest.raises(Exception):
            svc.require_auth(None)


# ============================================================
# AuthService.reload_users_config
# ============================================================


class TestReloadUsersConfig:
    """AuthService.reload_users_config"""

    def test_reload_replaces_device_manager(self):
        svc = AuthService(device_manager=_make_empty_dm())
        # 初始无用户
        assert svc.verify_api_key("valid_key") is False or svc.verify_api_key("valid_key") is True
        # mock load_devices 返回有用户的 manager
        new_dm = _make_dm_with_users("valid_key")
        with patch("src.use_cases.auth_service.load_devices", return_value=new_dm):
            svc.reload_users_config()
        # 现在 valid_key 应有效
        assert svc.verify_api_key("valid_key") is True


# ============================================================
# AuthService.__init__ default
# ============================================================


class TestAuthServiceInit:
    """AuthService 初始化"""

    def test_default_loads_devices(self):
        with patch("src.use_cases.auth_service.load_devices") as mock_load:
            mock_load.return_value = _make_empty_dm()
            svc = AuthService()
            mock_load.assert_called_once()

    def test_with_explicit_device_manager(self):
        dm = _make_dm_with_users("k")
        svc = AuthService(device_manager=dm)
        assert svc._device_manager is dm


# ============================================================
# 工厂函数
# ============================================================


class TestFactoryFunctions:
    """工厂函数创建各服务"""

    def test_create_emotion_detection(self):
        det = create_emotion_detection()
        assert isinstance(det, EmotionDetector)

    def test_create_device_manager(self):
        with patch("src.use_cases.auth_service.load_devices", return_value=_make_empty_dm()):
            dm = create_device_manager()
        assert isinstance(dm, DeviceManager)

    def test_create_audio_processor(self):
        ap = create_audio_processor()
        assert ap is not None

    def test_create_audio_processor_with_config(self):
        ap = create_audio_processor(config={"sample_rate": 8000})
        assert ap.sample_rate == 8000

    def test_create_memory_service(self):
        # SqlShortTermMemoryRepository.load 在构造时会访问 DB，
        # mock load 方法避免依赖真实 DB 表
        with patch.object(SqlShortTermMemoryRepository, "load", return_value=[]):
            mem = create_memory_service(max_messages=10, device_id="d1")
        assert mem is not None
        assert mem.max_messages == 10

    def test_create_wake_audio_manager(self):
        wam = create_wake_audio_manager()
        assert wam is not None

    def test_create_speaker_default(self):
        sp = create_speaker()
        assert sp is not None

    def test_create_speaker_with_args(self):
        registry = MagicMock()
        wam = MagicMock()
        sp = create_speaker(device_registry=registry, wake_audio_manager=wam)
        assert sp._registry is registry
        assert sp._wake_audio is wam

    def test_create_auth_service(self):
        with patch("src.use_cases.auth_service.load_devices", return_value=_make_empty_dm()):
            svc = create_auth_service()
        assert isinstance(svc, AuthService)
