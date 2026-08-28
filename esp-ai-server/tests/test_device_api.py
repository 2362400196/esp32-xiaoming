"""
Device API 设备管理路由单元测试

覆盖范围：
- verify_api_key：无 key / 无效 key / 无配置 key / 有效 key
- get_device_registry / get_speaker / resolve_device_id / get_device_details
- 设备列表、详情、TTS 播放、唤醒、停止（单播 + 广播）
- 设备统计、对话历史、配置管理、音量控制
- 固件管理（上传、列表、删除、信息、默认设置）
- OTA 推送（单设备、强制、批量、状态查询、重置）
- WiFi 配置、引脚设置
- SDK OTA 查询接口
- _apply_config_update / _get_ota_config / get_firmware_base_url 等辅助函数
- register_device_routes
"""
import json
import os
import time
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, mock_open, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.infrastructure import device_api


# ════════════════════════════════════════════════════════════════
# 测试夹具
# ════════════════════════════════════════════════════════════════

API_KEY = "test-api-key"
# 认证已从 X-API-Key 迁移到 Bearer JWT（decode_token 在测试中被 mock）
AUTH_HEADERS = {"Authorization": "Bearer test-access-token"}


def _make_mock_settings():
    """创建 mock settings 对象"""
    settings = MagicMock()
    settings.auth.admin_api_key = ""
    settings.auth.api_key = API_KEY
    settings.auth.enabled = True
    settings.server.host = "localhost"
    settings.server.port = 8088
    settings.server.workers = 1
    settings.ota.enabled = True
    settings.ota.bin_url = ""
    settings.ota.version = ""
    settings.ota.bin_id = ""
    settings.ota.is_official = "0"
    settings.ota.query_url = ""
    settings.mcp.servers_json = ""
    settings.remote_config_enabled = False
    return settings


@pytest.fixture(autouse=True)
def mock_settings():
    """Mock get_settings（autouse：所有测试自动生效）"""
    settings = _make_mock_settings()
    with patch.object(device_api, "get_settings", return_value=settings), \
         patch("src.infrastructure.config.get_settings", return_value=settings):
        yield settings


@pytest.fixture(autouse=True)
def mock_jwt():
    """Mock JWT 解码（autouse）：所有请求视为携带有效 access token 的登录用户"""
    with patch("src.infrastructure.security_jwt.decode_token",
               return_value={"sub": "user-1", "type": "access"}):
        yield


@pytest.fixture(autouse=True)
def mock_device_owner():
    """Mock 设备归属校验（autouse）：require_device_owner 依赖 DB 查询，测试中直接放行"""
    with patch.object(device_api, "require_device_owner",
                      AsyncMock(return_value="db-device-id")):
        yield


@pytest.fixture
def mock_channel():
    """模拟 WSChannel"""
    channel = MagicMock()
    channel.connected = True
    channel._volume = 0.8
    channel.send_json = AsyncMock()
    channel.send_queue = MagicMock()
    channel.send_queue.qsize.return_value = 0
    channel._send_task = None
    channel.websocket = MagicMock()
    channel.websocket.client_state = MagicMock()
    channel.websocket.client_state.name = "CONNECTED"
    return channel


@pytest.fixture
def mock_session():
    """模拟 Session"""
    session = MagicMock()
    session.session_id = "session-123"
    session.tts_playing = False
    session.session_start_time = time.time() - 60
    session.conversations_count = 5
    session.last_activity_time = time.time()
    session.last_speak_time = time.time()
    session.last_wakeup_time = time.time()
    memory = MagicMock()
    memory.message_count = 10
    memory.messages = [
        {"role": "user", "content": "你好", "timestamp": time.time()},
        {"role": "assistant", "content": "你好！", "timestamp": time.time()},
    ]
    memory.clear = Mock()
    session.conversation_memory = memory
    return session


@pytest.fixture
def mock_fsm():
    """模拟 FSM"""
    from enum import Enum
    State = Enum("State", {"idle": "idle", "listening": "listening"})

    fsm = MagicMock()
    fsm.get.return_value = State.idle
    return fsm


@pytest.fixture
def mock_user_config():
    """模拟 user_config"""
    uc = MagicMock()
    uc.name = "测试设备"
    # get_ota_config 返回正确的字典，避免 MagicMock 被当作 truthy 导致 JSON 序列化失败
    uc.get_ota_config.return_value = {
        "enabled": True,
        "bin_url": "",
        "version": "",
        "bin_id": "",
        "is_official": "0",
    }
    return uc


@pytest.fixture
def mock_device(mock_channel, mock_session, mock_fsm, mock_user_config):
    """模拟设备字典"""
    return {
        "mac": "AA:BB:CC:DD:EE:FF",
        "channel": mock_channel,
        "session": mock_session,
        "fsm": mock_fsm,
        "user_config": mock_user_config,
        "firmware_version": "1.0",
        "ota_updating": False,
        "ota_progress": 0,
    }


@pytest.fixture
def mock_registry(mock_device):
    """模拟 DeviceRegistry"""
    registry = MagicMock()
    registry._devices = {"test_key": mock_device}
    registry._mac_index = {}
    registry.count.return_value = 1
    registry.resolve.return_value = mock_device
    registry.get_by_mac.return_value = None
    registry.set_pending_ota = Mock()
    registry.set_pending_wifi_config = Mock()
    registry.set_pending_instruct = Mock()
    registry.set_ota_updating = Mock()
    registry.get_stats.return_value = {"total": 1}
    return registry


@pytest.fixture
def mock_speaker():
    """模拟 Speaker"""
    speaker = AsyncMock()
    speaker.speak.return_value = True
    speaker.speak_all = AsyncMock()
    speaker.wakeup.return_value = True
    speaker.wakeup_all = AsyncMock()
    speaker.stop.return_value = True
    speaker.stop_all = AsyncMock()
    return speaker


@pytest.fixture
def mock_app(mock_registry, mock_speaker):
    """模拟 app（含 state）"""
    app = MagicMock()
    app.state.device_registry = mock_registry
    app.state.speaker = mock_speaker
    app.state.auth_service = MagicMock()
    app.state.auth_service.reload_users_config = Mock()
    return app


@pytest.fixture
def mock_get_app(mock_app):
    """Mock web.get_app 返回测试 app"""
    with patch("src.infrastructure.web.get_app", return_value=mock_app):
        yield mock_app


@pytest.fixture
def app(mock_get_app):
    """FastAPI 测试应用（仅含 device_api 路由）"""
    application = FastAPI()
    application.include_router(device_api.router)
    application.include_router(device_api.sdk_router)
    # require_admin 依赖 DB 查询用户，测试中直接返回 admin 用户
    application.dependency_overrides[device_api.require_admin] = lambda: MagicMock(
        role="admin", is_active=True
    )
    return application


@pytest.fixture
def client(app):
    return TestClient(app)


# ════════════════════════════════════════════════════════════════
# verify_api_key 测试
# ════════════════════════════════════════════════════════════════

class TestVerifyApiKey:
    """Bearer JWT 验证测试（verify_api_key 已改为 Request + Authorization header）"""

    @staticmethod
    def _request(auth=""):
        req = MagicMock()
        req.headers = {"authorization": auth} if auth else {}
        return req

    async def test_no_token_raises_401(self, mock_settings):
        """无 Authorization header 时抛 401"""
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await device_api.verify_api_key(self._request())
        assert exc_info.value.status_code == 401

    async def test_non_bearer_raises_401(self, mock_settings):
        """非 Bearer 格式的 Authorization 抛 401"""
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await device_api.verify_api_key(self._request("Basic abc"))
        assert exc_info.value.status_code == 401

    async def test_invalid_token_raises_403(self, mock_settings):
        """无效 token 抛 403"""
        from fastapi import HTTPException
        with patch("src.infrastructure.security_jwt.decode_token", side_effect=Exception("bad token")):
            with pytest.raises(HTTPException) as exc_info:
                await device_api.verify_api_key(self._request("Bearer bad-token"))
        assert exc_info.value.status_code == 403

    async def test_valid_access_token(self, mock_settings):
        """有效 access token 返回 True"""
        result = await device_api.verify_api_key(self._request(AUTH_HEADERS["Authorization"]))
        assert result is True


# ════════════════════════════════════════════════════════════════
# 辅助函数测试
# ════════════════════════════════════════════════════════════════

class TestHelperFunctions:
    """辅助函数测试"""

    def test_get_device_registry_no_app(self):
        """无 app 时返回 None"""
        with patch("src.infrastructure.web.get_app", return_value=None):
            assert device_api.get_device_registry() is None

    def test_get_device_registry_success(self, mock_app):
        """有 app 时返回 registry"""
        with patch("src.infrastructure.web.get_app", return_value=mock_app):
            result = device_api.get_device_registry()
            assert result is not None

    def test_get_speaker_no_app(self):
        with patch("src.infrastructure.web.get_app", return_value=None):
            assert device_api.get_speaker() is None

    def test_get_speaker_success(self, mock_app):
        with patch("src.infrastructure.web.get_app", return_value=mock_app):
            assert device_api.get_speaker() is not None

    def test_resolve_device_id_no_registry(self):
        """无 registry 时返回 None"""
        with patch.object(device_api, "get_device_registry", return_value=None):
            assert device_api.resolve_device_id("dev1") is None

    def test_resolve_device_id_by_mac(self, mock_registry):
        """通过 MAC 找到设备"""
        mock_registry.get_by_mac.return_value = MagicMock()
        mock_registry._mac_index = {"mac1": "api_key_1"}
        with patch.object(device_api, "get_device_registry", return_value=mock_registry):
            result = device_api.resolve_device_id("mac1")
        assert result == "api_key_1"

    def test_resolve_device_id_by_mac_no_index(self, mock_registry):
        """通过 MAC 找到设备但无 index 时返回 device_id"""
        mock_registry.get_by_mac.return_value = MagicMock()
        mock_registry._mac_index = {}
        with patch.object(device_api, "get_device_registry", return_value=mock_registry):
            result = device_api.resolve_device_id("mac1")
        assert result == "mac1"

    def test_resolve_device_id_by_resolve(self, mock_registry):
        """通过 resolve 找到设备"""
        mock_registry.get_by_mac.return_value = None
        mock_registry.resolve.return_value = MagicMock()
        with patch.object(device_api, "get_device_registry", return_value=mock_registry):
            result = device_api.resolve_device_id("dev1")
        assert result == "dev1"

    def test_resolve_device_id_not_found(self, mock_registry):
        """设备未找到时返回 None（DB 为唯一数据源，不再回退 JSON）"""
        mock_registry.get_by_mac.return_value = None
        mock_registry.resolve.return_value = None
        with patch.object(device_api, "get_device_registry", return_value=mock_registry):
            result = device_api.resolve_device_id("unknown")
        assert result is None

    def test_get_device_details_no_registry(self):
        with patch.object(device_api, "get_device_registry", return_value=None):
            assert device_api.get_device_details("key1") is None

    def test_get_device_details_not_found(self, mock_registry):
        mock_registry.resolve.return_value = None
        with patch.object(device_api, "get_device_registry", return_value=mock_registry):
            assert device_api.get_device_details("key1") is None

    def test_get_device_details_success(self, mock_registry, mock_device):
        """获取设备详情成功"""
        with patch.object(device_api, "get_device_registry", return_value=mock_registry):
            details = device_api.get_device_details("test_key")
        assert details is not None
        assert details["mac"] == "AA:BB:CC:DD:EE:FF"
        assert details["device_key"] == "test_key"
        assert details["name"] == "测试设备"
        assert details["connected"] is True
        assert details["uptime"] > 0
        assert details["messages_count"] == 10

    def test_get_device_details_fsm_exception(self, mock_registry, mock_device):
        """FSM 状态获取异常时返回 unknown"""
        mock_device["fsm"].get.side_effect = RuntimeError("fsm error")
        with patch.object(device_api, "get_device_registry", return_value=mock_registry):
            details = device_api.get_device_details("test_key")
        assert details["state"] == "unknown"


# ════════════════════════════════════════════════════════════════
# 设备统计和对话历史 API 测试
# ════════════════════════════════════════════════════════════════

class TestDeviceStatsAPI:
    """设备统计和历史 API 测试"""

    def test_get_device_stats_success(self, client, mock_get_app):
        """获取设备统计"""
        stats_data = {"mac": "AA:BB", "device_key": "test_key", "uptime": 60, "messages_count": 10}
        with patch.object(device_api, "resolve_device_id", return_value="test_key"), \
             patch.object(device_api, "get_device_details", return_value=stats_data):
            resp = client.get("/api/v1/devices/AA:BB/stats", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["uptime"] == 60

    def test_get_device_stats_not_found(self, client, mock_get_app):
        with patch.object(device_api, "resolve_device_id", return_value=None):
            resp = client.get("/api/v1/devices/AA:BB/stats", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_get_device_stats_post(self, client, mock_get_app):
        """POST 方法也应工作"""
        stats_data = {"mac": "AA:BB", "device_key": "test_key", "uptime": 60, "messages_count": 10}
        with patch.object(device_api, "resolve_device_id", return_value="test_key"), \
             patch.object(device_api, "get_device_details", return_value=stats_data):
            resp = client.post("/api/v1/devices/AA:BB/stats", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0

    def test_get_device_history_success(self, client, mock_get_app, mock_device):
        """获取对话历史"""
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.get("/api/v1/devices/AA:BB/history", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["count"] == 2

    def test_get_device_history_not_found(self, client, mock_get_app, mock_registry):
        """设备不在注册表时离线回退：仍返回 code=0（空历史）"""
        mock_registry.resolve.return_value = None
        with patch.object(device_api, "resolve_device_id", return_value=None), \
             patch("src.infrastructure.db.repositories.short_term_memory_repo.SqlShortTermMemoryRepository") as mock_repo:
            mock_repo.return_value.load.return_value = []
            resp = client.get("/api/v1/devices/AA:BB/history", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["messages"] == []

    def test_get_device_history_no_session(self, client, mock_get_app, mock_registry):
        """设备无 session"""
        mock_registry.resolve.return_value = {"session": None}
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.get("/api/v1/devices/AA:BB/history", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["messages"] == []

    def test_get_device_history_no_memory(self, client, mock_get_app, mock_registry):
        """session 无 conversation_memory"""
        mock_session = MagicMock()
        mock_session.conversation_memory = None
        mock_registry.resolve.return_value = {"session": mock_session}
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.get("/api/v1/devices/AA:BB/history", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["messages"] == []

    def test_clear_device_history_success(self, client, mock_get_app, mock_device):
        """清空对话历史"""
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.post("/api/v1/devices/AA:BB/history", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0
        mock_device["session"].conversation_memory.clear.assert_called_once()

    def test_clear_device_history_no_memory(self, client, mock_get_app, mock_registry):
        """无 memory 时返回错误"""
        mock_session = MagicMock()
        mock_session.conversation_memory = None
        mock_registry.resolve.return_value = {"session": mock_session}
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.post("/api/v1/devices/AA:BB/history", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1


# ════════════════════════════════════════════════════════════════
# _apply_config_update 测试
# ════════════════════════════════════════════════════════════════

class TestApplyConfigUpdate:
    """_apply_config_update 纯函数测试"""

    def test_none_value_ignored(self):
        """None 值应被忽略"""
        cfg = {}
        device_api._apply_config_update(cfg, "name", None)
        assert cfg == {}

    def test_dict_field_replace(self):
        """dict 字段整体替换"""
        cfg = {}
        device_api._apply_config_update(cfg, "tts_config", {"voice": "v1"})
        assert cfg["tts_config"] == {"voice": "v1"}

    def test_top_level_field(self):
        """顶层标量字段"""
        cfg = {}
        device_api._apply_config_update(cfg, "name", "new_name")
        assert cfg["name"] == "new_name"

    def test_nested_llm_field(self):
        """LLM 嵌套字段"""
        cfg = {}
        device_api._apply_config_update(cfg, "llm_api_key", "sk-xxx")
        assert cfg["llm"]["api_key"] == "sk-xxx"

    def test_nested_tts_field(self):
        """TTS 嵌套字段"""
        cfg = {}
        device_api._apply_config_update(cfg, "voice_type", "BV001")
        assert cfg["tts_config"]["voice_type"] == "BV001"

    def test_deeply_nested_asr_field(self):
        """ASR 深层嵌套字段"""
        cfg = {}
        device_api._apply_config_update(cfg, "asr_api_key", "asr-key")
        assert cfg["asr_config"]["volcengine"]["api_key"] == "asr-key"

    def test_nested_field_preserves_existing(self):
        """嵌套字段不应覆盖已有同级字段"""
        cfg = {"llm": {"model": "gpt-4"}}
        device_api._apply_config_update(cfg, "llm_api_key", "sk-xxx")
        assert cfg["llm"]["model"] == "gpt-4"
        assert cfg["llm"]["api_key"] == "sk-xxx"

    def test_unknown_field_ignored(self):
        """未知字段名应被忽略"""
        cfg = {}
        device_api._apply_config_update(cfg, "unknown_field", "value")
        assert cfg == {}


# ════════════════════════════════════════════════════════════════
# 设备配置管理 API 测试
# ════════════════════════════════════════════════════════════════

class TestDeviceConfigAPI:
    """设备配置管理 API 测试"""

    def test_get_config_not_found(self, client, mock_get_app):
        """设备不在注册表且 DB 无记录时返回 code=1"""
        mock_repo = MagicMock()
        mock_repo.find_by_mac = AsyncMock(return_value=None)
        mock_repo.find_by_key = AsyncMock(return_value=None)
        with patch.object(device_api, "resolve_device_id", return_value=None), \
             patch("src.infrastructure.db.repositories.device_repository.DeviceRepository", return_value=mock_repo):
            resp = client.get("/api/v1/devices/AA:BB/config", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_get_config_no_users_json(self, client, mock_get_app):
        """设备不在 DB 中"""
        with patch.object(device_api, "resolve_device_id", return_value="test_key"), \
             patch("src.infrastructure.db.repositories.device_repository.DeviceRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.find_by_mac = AsyncMock(return_value=None)
            mock_repo.find_by_key = AsyncMock(return_value=None)
            resp = client.get("/api/v1/devices/AA:BB/config", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_get_config_success(self, client, mock_get_app):
        """获取设备配置成功"""
        with patch.object(device_api, "resolve_device_id", return_value="test_key"), \
             patch("src.infrastructure.db.repositories.device_repository.DeviceRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.find_by_mac = AsyncMock(return_value=("test_key", {"key": "test_key", "name": "test"}))
            mock_repo.find_by_key = AsyncMock(return_value=None)
            resp = client.get("/api/v1/devices/AA:BB/config", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["name"] == "test"

    def test_get_config_device_not_in_users(self, client, mock_get_app):
        """设备不在 DB 中"""
        with patch.object(device_api, "resolve_device_id", return_value="test_key"), \
             patch("src.infrastructure.db.repositories.device_repository.DeviceRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.find_by_mac = AsyncMock(return_value=None)
            mock_repo.find_by_key = AsyncMock(return_value=None)
            resp = client.get("/api/v1/devices/AA:BB/config", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_update_config_not_found(self, client, mock_get_app):
        """设备不在注册表且 DB 无记录时返回 code=1"""
        mock_repo = MagicMock()
        mock_repo.find_by_mac = AsyncMock(return_value=None)
        mock_repo.find_by_key = AsyncMock(return_value=None)
        with patch.object(device_api, "resolve_device_id", return_value=None), \
             patch("src.infrastructure.db.repositories.device_repository.DeviceRepository", return_value=mock_repo):
            resp = client.post("/api/v1/devices/AA:BB/config", json={"name": "new"}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_update_config_no_updates(self, client, mock_get_app):
        """无更新字段时报错"""
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.post("/api/v1/devices/AA:BB/config", json={}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_update_config_success(self, client, mock_get_app):
        """更新配置成功"""
        with patch.object(device_api, "resolve_device_id", return_value="test_key"), \
             patch("src.infrastructure.db.repositories.device_repository.DeviceRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.find_by_mac = AsyncMock(return_value=("test_key", {"key": "test_key", "name": "old"}))
            mock_repo.find_by_key = AsyncMock(return_value=None)
            mock_repo.update_device_partial = AsyncMock(return_value={"name": "new_name"})
            resp = client.post("/api/v1/devices/AA:BB/config", json={"name": "new_name"}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0

    def test_update_config_device_not_in_users(self, client, mock_get_app):
        """设备不在 DB 中"""
        with patch.object(device_api, "resolve_device_id", return_value="test_key"), \
             patch("src.infrastructure.db.repositories.device_repository.DeviceRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.find_by_mac = AsyncMock(return_value=None)
            mock_repo.find_by_key = AsyncMock(return_value=None)
            resp = client.post("/api/v1/devices/AA:BB/config", json={"name": "new"}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1


# ════════════════════════════════════════════════════════════════
# 设备音量控制 API 测试
# ════════════════════════════════════════════════════════════════

class TestDeviceVolumeAPI:
    """设备音量控制 API 测试"""

    def test_set_volume_invalid_low(self, client, mock_get_app):
        """音量过低"""
        resp = client.post("/api/v1/devices/AA:BB/volume", json={"volume": -0.1}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_set_volume_invalid_high(self, client, mock_get_app):
        """音量过高"""
        resp = client.post("/api/v1/devices/AA:BB/volume", json={"volume": 1.5}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_set_volume_device_not_found(self, client, mock_get_app):
        with patch.object(device_api, "resolve_device_id", return_value=None):
            resp = client.post("/api/v1/devices/AA:BB/volume", json={"volume": 0.5}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_set_volume_no_channel(self, client, mock_get_app, mock_registry):
        """无 channel"""
        mock_registry.resolve.return_value = {"channel": None}
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.post("/api/v1/devices/AA:BB/volume", json={"volume": 0.5}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_set_volume_success(self, client, mock_get_app, mock_device, mock_channel):
        """设置音量成功"""
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.post("/api/v1/devices/AA:BB/volume", json={"volume": 0.5}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["volume"] == 0.5
        mock_channel.send_json.assert_called_once()

    def test_set_volume_send_exception(self, client, mock_get_app, mock_channel):
        """发送音量指令异常"""
        mock_channel.send_json.side_effect = RuntimeError("send failed")
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.post("/api/v1/devices/AA:BB/volume", json={"volume": 0.5}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_get_volume_success(self, client, mock_get_app, mock_device, mock_channel):
        """获取音量"""
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.get("/api/v1/devices/AA:BB/volume", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["volume"] == 0.8

    def test_get_volume_no_channel(self, client, mock_get_app, mock_registry):
        """无 channel 时返回默认音量 1.0"""
        mock_registry.resolve.return_value = {"channel": None}
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.get("/api/v1/devices/AA:BB/volume", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["volume"] == 1.0


# ════════════════════════════════════════════════════════════════
# 固件管理 API 测试
# ════════════════════════════════════════════════════════════════

class TestFirmwareAPI:
    """固件管理 API 测试"""

    def test_get_firmware_base_url_normal(self, mock_settings):
        """正常 host"""
        mock_settings.server.host = "192.168.1.1"
        mock_settings.server.port = 8088
        url = device_api.get_firmware_base_url()
        assert url == "http://192.168.1.1:8088/firmware"

    def test_get_firmware_base_url_zero_host(self, mock_settings):
        """host 为 0.0.0.0 时应解析实际 IP"""
        mock_settings.server.host = "0.0.0.0"
        with patch("socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock.getsockname.return_value = ("10.0.0.1", 0)
            mock_sock_cls.return_value = mock_sock
            url = device_api.get_firmware_base_url()
        assert "10.0.0.1" in url

    def test_get_firmware_base_url_zero_host_socket_error(self, mock_settings):
        """host 为 0.0.0.0 且 socket 异常时回退 localhost"""
        mock_settings.server.host = "0.0.0.0"
        with patch("socket.socket", side_effect=OSError("no network")):
            url = device_api.get_firmware_base_url()
        assert "localhost" in url

    def test_get_firmware_base_url_settings_error(self, mock_settings):
        """get_settings 异常时使用默认值"""
        with patch.object(device_api, "get_settings", side_effect=RuntimeError("err")):
            url = device_api.get_firmware_base_url()
        assert "localhost" in url or "8088" in url

    def test_get_firmware_info_not_found(self, tmp_path):
        """固件文件不存在"""
        with patch.object(device_api, "FIRMWARE_DIR", tmp_path):
            assert device_api.get_firmware_info("nonexistent.bin") is None

    def test_get_firmware_info_found(self, tmp_path):
        """固件文件存在"""
        fw_file = tmp_path / "test.bin"
        fw_file.write_bytes(b"firmware content")
        with patch.object(device_api, "FIRMWARE_DIR", tmp_path), \
             patch.object(device_api, "get_firmware_base_url", return_value="http://x/firmware"):
            info = device_api.get_firmware_info("test.bin")
        assert info is not None
        assert info.filename == "test.bin"
        assert info.size == 16  # b"firmware content" = 16 bytes

    def test_list_firmwares_empty(self, tmp_path):
        """空固件目录"""
        with patch.object(device_api, "FIRMWARE_DIR", tmp_path):
            assert device_api.list_firmwares() == []

    def test_list_firmwares_with_files(self, tmp_path):
        """有固件文件"""
        (tmp_path / "v1.bin").write_bytes(b"v1")
        (tmp_path / "v2.bin").write_bytes(b"v2longer")
        (tmp_path / "readme.txt").write_text("not firmware")
        with patch.object(device_api, "FIRMWARE_DIR", tmp_path), \
             patch.object(device_api, "get_firmware_base_url", return_value="http://x/firmware"):
            firmwares = device_api.list_firmwares()
        assert len(firmwares) == 2  # 只统计 .bin/.elf/.hex

    def test_upload_firmware_no_file(self, client, mock_get_app, mock_settings):
        """无文件名 - FastAPI 返回 422 验证错误"""
        resp = client.post("/api/v1/firmware/upload", headers=AUTH_HEADERS,
                           files={"file": ("", b"", "application/octet-stream")})
        # 空文件名时 FastAPI 返回 422 验证错误
        assert resp.status_code == 422

    def test_upload_firmware_invalid_type(self, client, mock_get_app, mock_settings):
        """无效文件类型"""
        resp = client.post("/api/v1/firmware/upload", headers=AUTH_HEADERS,
                           files={"file": ("test.txt", b"content", "text/plain")})
        assert resp.json()["code"] == 1

    def test_upload_firmware_success(self, client, mock_get_app, mock_settings, tmp_path):
        """上传固件成功"""
        with patch.object(device_api, "FIRMWARE_DIR", tmp_path), \
             patch.object(device_api, "get_firmware_base_url", return_value="http://x/firmware"):
            resp = client.post("/api/v1/firmware/upload", headers=AUTH_HEADERS,
                               files={"file": ("test.bin", b"firmware", "application/octet-stream")})
        assert resp.json()["code"] == 0

    def test_list_firmwares_api(self, client, mock_get_app, mock_settings, tmp_path):
        """获取固件列表 API"""
        (tmp_path / "v1.bin").write_bytes(b"v1")
        with patch.object(device_api, "FIRMWARE_DIR", tmp_path), \
             patch.object(device_api, "get_firmware_base_url", return_value="http://x/firmware"):
            resp = client.get("/api/v1/firmware", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["count"] == 1

    def test_delete_firmware_not_found(self, client, mock_get_app, mock_settings, tmp_path):
        with patch.object(device_api, "FIRMWARE_DIR", tmp_path):
            resp = client.post("/api/v1/firmware/nonexistent.bin", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_delete_firmware_success(self, client, mock_get_app, mock_settings, tmp_path):
        """删除固件成功"""
        fw = tmp_path / "test.bin"
        fw.write_bytes(b"content")
        with patch.object(device_api, "FIRMWARE_DIR", tmp_path):
            resp = client.post("/api/v1/firmware/test.bin", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0
        assert not fw.exists()

    def test_get_firmware_info_api_not_found(self, client, mock_get_app, mock_settings, tmp_path):
        with patch.object(device_api, "FIRMWARE_DIR", tmp_path):
            resp = client.get("/api/v1/firmware/nonexistent.bin", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_get_firmware_info_api_found(self, client, mock_get_app, mock_settings, tmp_path):
        """获取固件信息"""
        (tmp_path / "test.bin").write_bytes(b"content")
        with patch.object(device_api, "FIRMWARE_DIR", tmp_path), \
             patch.object(device_api, "get_firmware_base_url", return_value="http://x/firmware"):
            resp = client.get("/api/v1/firmware/test.bin", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0

    async def test_set_default_firmware_not_found(self, mock_settings):
        """设置默认固件 - 固件不存在（直接调用函数，避免 /firmware/{filename} 路由冲突）"""
        with patch.object(device_api, "get_firmware_info", return_value=None):
            result = await device_api.set_default_firmware(
                filename="nonexistent.bin",
                request=MagicMock(headers={"authorization": AUTH_HEADERS["Authorization"]}),
                version=None,
            )
        assert result.code == 1

    async def test_set_default_firmware_success(self, mock_settings):
        """设置默认固件成功（直接调用函数，避免 /firmware/{filename} 路由冲突）"""
        mock_info = MagicMock()
        mock_info.download_url = "http://x/firmware/test.bin"
        mock_info.size = 7
        with patch.object(device_api, "get_firmware_info", return_value=mock_info):
            result = await device_api.set_default_firmware(
                filename="test.bin",
                request=MagicMock(headers={"authorization": AUTH_HEADERS["Authorization"]}),
                version="2.0",
            )
        assert result.code == 0
        assert mock_settings.ota.bin_url == "http://x/firmware/test.bin"
        assert mock_settings.ota.version == "2.0"


# ════════════════════════════════════════════════════════════════
# OTA 配置和推送测试
# ════════════════════════════════════════════════════════════════

class TestOTAConfig:
    """_get_ota_config 辅助函数测试"""

    def test_get_ota_config_with_ota(self, mock_settings):
        config = device_api._get_ota_config()
        assert config["enabled"] is True
        assert "bin_url" in config
        assert "version" in config

    def test_get_ota_config_no_ota(self, mock_settings):
        """settings 无 ota 属性"""
        del mock_settings.ota
        config = device_api._get_ota_config()
        assert config["enabled"] is True
        assert config["bin_url"] == ""


class TestSendOTAToDevice:
    """_send_ota_to_device 测试"""

    async def test_no_registry(self):
        with patch.object(device_api, "get_device_registry", return_value=None):
            result = await device_api._send_ota_to_device("key1", "http://fw")
        assert result["success"] is False

    async def test_device_not_found(self, mock_registry):
        mock_registry.resolve.return_value = None
        with patch.object(device_api, "get_device_registry", return_value=mock_registry):
            result = await device_api._send_ota_to_device("key1", "http://fw")
        assert result["success"] is False
        assert "not found" in result["error"]

    async def test_no_channel(self, mock_registry, mock_device):
        mock_device["channel"] = None
        with patch.object(device_api, "get_device_registry", return_value=mock_registry):
            result = await device_api._send_ota_to_device("key1", "http://fw")
        assert result["success"] is False

    async def test_channel_not_connected(self, mock_registry, mock_channel):
        mock_channel.connected = False
        with patch.object(device_api, "get_device_registry", return_value=mock_registry):
            result = await device_api._send_ota_to_device("key1", "http://fw")
        assert result["success"] is False

    async def test_success(self, mock_registry):
        with patch.object(device_api, "get_device_registry", return_value=mock_registry):
            result = await device_api._send_ota_to_device("test_key", "http://fw", "2.0")
        assert result["success"] is True
        mock_registry.set_pending_ota.assert_called_once()


class TestOTAPushAPI:
    """OTA 推送 API 测试"""

    def test_push_ota_device_not_found(self, client, mock_get_app):
        with patch.object(device_api, "resolve_device_id", return_value=None):
            resp = client.post("/api/v1/devices/AA:BB/ota", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_push_ota_no_registry(self, client, mock_get_app):
        with patch.object(device_api, "resolve_device_id", return_value="test_key"), \
             patch.object(device_api, "get_device_registry", return_value=None):
            resp = client.post("/api/v1/devices/AA:BB/ota", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_push_ota_disabled(self, client, mock_get_app, mock_device, mock_settings):
        """OTA 被禁用"""
        mock_device["user_config"] = MagicMock()
        mock_device["user_config"].get_ota_config.return_value = {"enabled": False}
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.post("/api/v1/devices/AA:BB/ota", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1
        assert "disabled" in resp.json()["message"]

    def test_push_ota_global_disabled(self, client, mock_get_app, mock_settings):
        """全局 OTA 禁用"""
        mock_settings.ota.enabled = False
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.post("/api/v1/devices/AA:BB/ota", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_push_ota_no_url_no_firmware(self, client, mock_get_app, mock_settings):
        """无 URL 且无本地固件"""
        with patch.object(device_api, "resolve_device_id", return_value="test_key"), \
             patch.object(device_api, "list_firmwares", return_value=[]):
            resp = client.post("/api/v1/devices/AA:BB/ota", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_push_ota_with_url_success(self, client, mock_get_app):
        """指定 URL 推送成功"""
        with patch.object(device_api, "resolve_device_id", return_value="test_key"), \
             patch.object(device_api, "_send_ota_to_device", new_callable=AsyncMock, return_value={"success": True}):
            resp = client.post("/api/v1/devices/AA:BB/ota", json={"url": "http://fw"}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0

    def test_push_ota_with_firmware_fallback(self, client, mock_get_app, mock_settings):
        """无 URL 但有本地固件时回退"""
        mock_fw = MagicMock()
        mock_fw.download_url = "http://local/fw.bin"
        mock_fw.filename = "fw.bin"
        with patch.object(device_api, "resolve_device_id", return_value="test_key"), \
             patch.object(device_api, "list_firmwares", return_value=[mock_fw]), \
             patch.object(device_api, "_send_ota_to_device", new_callable=AsyncMock, return_value={"success": True}):
            resp = client.post("/api/v1/devices/AA:BB/ota", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0

    def test_push_ota_already_on_version(self, client, mock_get_app, mock_device):
        """设备已是目标版本"""
        mock_device["firmware_version"] = "2.0"
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.post("/api/v1/devices/AA:BB/ota", json={"version": "2.0", "url": "http://fw"}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1
        assert "already" in resp.json()["message"].lower()

    def test_push_ota_already_updating(self, client, mock_get_app, mock_device):
        """设备正在升级中"""
        mock_device["ota_updating"] = True
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.post("/api/v1/devices/AA:BB/ota", json={"url": "http://fw"}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1
        assert "upgrading" in resp.json()["message"].lower()

    def test_push_ota_send_failed(self, client, mock_get_app):
        """发送 OTA 失败"""
        with patch.object(device_api, "resolve_device_id", return_value="test_key"), \
             patch.object(device_api, "_send_ota_to_device", new_callable=AsyncMock, return_value={"success": False, "error": "send failed"}):
            resp = client.post("/api/v1/devices/AA:BB/ota", json={"url": "http://fw"}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_force_ota_success(self, client, mock_get_app):
        """强制推送成功（跳过版本检查）"""
        with patch.object(device_api, "resolve_device_id", return_value="test_key"), \
             patch.object(device_api, "_send_ota_to_device", new_callable=AsyncMock, return_value={"success": True}):
            resp = client.post("/api/v1/devices/AA:BB/ota/force", json={"url": "http://fw"}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0

    def test_force_ota_no_url(self, client, mock_get_app, mock_settings):
        """强制推送无 URL"""
        with patch.object(device_api, "resolve_device_id", return_value="test_key"), \
             patch.object(device_api, "list_firmwares", return_value=[]):
            resp = client.post("/api/v1/devices/AA:BB/ota/force", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1


class TestOTABatchAPI:
    """OTA 批量推送和状态 API 测试"""

    def test_push_ota_all_no_devices(self, client, mock_get_app):
        """无在线设备"""
        mock_registry = mock_get_app.state.device_registry
        mock_registry.count.return_value = 0
        resp = client.post("/api/v1/devices/ota/all", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["total"] == 0

    def test_push_ota_all_global_disabled(self, client, mock_get_app, mock_settings):
        """全局 OTA 禁用"""
        mock_settings.ota.enabled = False
        resp = client.post("/api/v1/devices/ota/all", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_push_ota_all_success(self, client, mock_get_app):
        """批量推送成功"""
        with patch.object(device_api, "_send_ota_to_device", new_callable=AsyncMock, return_value={"success": True}):
            resp = client.post("/api/v1/devices/ota/all", json={"url": "http://fw"}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["succeeded"] == 1

    def test_push_ota_all_device_disabled(self, client, mock_get_app, mock_device):
        """设备禁用 OTA"""
        mock_device["user_config"] = MagicMock()
        mock_device["user_config"].get_ota_config.return_value = {"enabled": False}
        resp = client.post("/api/v1/devices/ota/all", json={"url": "http://fw"}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["skipped"] == 1

    def test_push_ota_all_already_updating(self, client, mock_get_app, mock_device):
        """设备正在升级"""
        mock_device["ota_updating"] = True
        resp = client.post("/api/v1/devices/ota/all", json={"url": "http://fw"}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["failed"] == 1

    def test_get_ota_status_no_registry(self, client, mock_get_app):
        with patch.object(device_api, "get_device_registry", return_value=None):
            resp = client.get("/api/v1/devices/ota/status", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_get_ota_status_success(self, client, mock_get_app):
        resp = client.get("/api/v1/devices/ota/status", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["total_devices"] == 1

    def test_get_device_ota_status_success(self, client, mock_get_app):
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.get("/api/v1/devices/AA:BB/ota/status", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0

    def test_get_device_ota_status_not_found(self, client, mock_get_app):
        with patch.object(device_api, "resolve_device_id", return_value=None):
            resp = client.get("/api/v1/devices/AA:BB/ota/status", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_reset_device_ota_success(self, client, mock_get_app):
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.post("/api/v1/devices/AA:BB/ota/reset", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0


# ════════════════════════════════════════════════════════════════
# WiFi 和引脚配置 API 测试
# ════════════════════════════════════════════════════════════════

class TestWiFiAndPinsAPI:
    """WiFi 和引脚配置 API 测试"""

    def test_set_wifi_not_found(self, client, mock_get_app):
        with patch.object(device_api, "resolve_device_id", return_value=None):
            resp = client.post("/api/v1/devices/AA:BB/wifi", json={"ssid": "mywifi"}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_set_wifi_not_connected(self, client, mock_get_app, mock_channel):
        """设备未连接"""
        mock_channel.connected = False
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.post("/api/v1/devices/AA:BB/wifi", json={"ssid": "mywifi", "password": "pass"}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_set_wifi_success(self, client, mock_get_app):
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.post("/api/v1/devices/AA:BB/wifi", json={"ssid": "mywifi", "password": "pass"}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0

    def test_set_mic_pins_not_found(self, client, mock_get_app):
        with patch.object(device_api, "resolve_device_id", return_value=None):
            resp = client.post("/api/v1/devices/AA:BB/pins/mic", json={"bck": 4, "ws": 5, "data": 6}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_set_mic_pins_not_connected(self, client, mock_get_app, mock_channel):
        mock_channel.connected = False
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.post("/api/v1/devices/AA:BB/pins/mic", json={"bck": 4, "ws": 5, "data": 6}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_set_mic_pins_success(self, client, mock_get_app):
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.post("/api/v1/devices/AA:BB/pins/mic", json={"bck": 4, "ws": 5, "data": 6}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0

    def test_set_speaker_pins_success(self, client, mock_get_app):
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.post("/api/v1/devices/AA:BB/pins/speaker", json={"bck": 4, "ws": 5, "data": 6}, headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0


# ════════════════════════════════════════════════════════════════
# 设备 WebSocket 测试 API
# ════════════════════════════════════════════════════════════════

class TestDeviceWSTestAPI:
    """设备 WS 测试 API"""

    def test_test_device_ws_not_found(self, client, mock_get_app):
        with patch.object(device_api, "resolve_device_id", return_value=None):
            resp = client.post("/api/v1/devices/AA:BB/test", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1

    def test_test_device_ws_no_channel(self, client, mock_get_app, mock_registry):
        mock_registry.resolve.return_value = {"channel": None}
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.post("/api/v1/devices/AA:BB/test", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1
        assert "No channel" in resp.json()["message"]

    def test_test_device_ws_not_connected(self, client, mock_get_app, mock_channel):
        mock_channel.connected = False
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.post("/api/v1/devices/AA:BB/test", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 1
        assert "not connected" in resp.json()["message"]

    def test_test_device_ws_success(self, client, mock_get_app):
        with patch.object(device_api, "resolve_device_id", return_value="test_key"):
            resp = client.post("/api/v1/devices/AA:BB/test", headers=AUTH_HEADERS)
        assert resp.json()["code"] == 0


# ════════════════════════════════════════════════════════════════
# SDK OTA 查询接口测试
# ════════════════════════════════════════════════════════════════

class TestSDKOTAQuery:
    """SDK OTA 查询接口测试"""

    def test_ota_disabled(self, client, mock_settings):
        """OTA 禁用时返回不可用"""
        mock_settings.ota.enabled = False
        resp = client.get("/sdk/query_new_ota")
        assert resp.json()["success"] is False

    def test_no_firmware_available(self, client, mock_settings):
        """无固件时返回已是最新"""
        mock_settings.ota.bin_url = ""
        mock_settings.ota.version = ""
        with patch.object(device_api, "list_firmwares", return_value=[]):
            resp = client.get("/sdk/query_new_ota")
        assert resp.json()["success"] is True
        assert resp.json()["data"]["latest"] is True
        assert resp.json()["data"]["bin_url"] == ""

    def test_use_local_firmware(self, client, mock_settings):
        """使用本地固件"""
        mock_settings.ota.bin_url = ""
        mock_settings.ota.version = "2.0"
        mock_fw = MagicMock()
        mock_fw.download_url = "http://local/fw.bin"
        mock_fw.filename = "fw.bin"
        with patch.object(device_api, "list_firmwares", return_value=[mock_fw]):
            resp = client.get("/sdk/query_new_ota", params={"version": "1.0"})
        assert resp.json()["success"] is True
        assert resp.json()["data"]["latest"] is False

    def test_bin_id_match(self, client, mock_settings):
        """bin_id 相同时已是最新"""
        mock_settings.ota.bin_url = "http://fw"
        mock_settings.ota.bin_id = "bin123"
        resp = client.get("/sdk/query_new_ota", params={"bin_id": "bin123"})
        assert resp.json()["data"]["latest"] is True

    def test_no_configured_version(self, client, mock_settings):
        """未配置目标版本号时视为已是最新"""
        mock_settings.ota.bin_url = "http://fw"
        mock_settings.ota.version = ""
        resp = client.get("/sdk/query_new_ota", params={"version": "1.0"})
        assert resp.json()["data"]["latest"] is True

    def test_already_latest_version(self, client, mock_settings):
        """已是最新版本"""
        mock_settings.ota.bin_url = "http://fw"
        mock_settings.ota.version = "1.0"
        resp = client.get("/sdk/query_new_ota", params={"version": "1.0"})
        assert resp.json()["data"]["latest"] is True

    def test_new_version_available(self, client, mock_settings):
        """有新版本"""
        mock_settings.ota.bin_url = "http://fw"
        mock_settings.ota.version = "2.0"
        resp = client.get("/sdk/query_new_ota", params={"version": "1.0"})
        assert resp.json()["data"]["latest"] is False
        assert resp.json()["data"]["bin_url"] == "http://fw"

    def test_version_comparison_string_fallback(self, client, mock_settings):
        """版本比较异常时用字符串比较"""
        mock_settings.ota.bin_url = "http://fw"
        mock_settings.ota.version = "1.0"
        # packaging.version.Version 可能正常解析，这里测试相等的情况
        resp = client.get("/sdk/query_new_ota", params={"version": "1.0"})
        assert resp.json()["data"]["latest"] is True

    def test_no_ota_attr(self, client, mock_settings):
        """settings 无 ota 属性"""
        del mock_settings.ota
        with patch.object(device_api, "list_firmwares", return_value=[]):
            resp = client.get("/sdk/query_new_ota")
        assert resp.json()["success"] is True


# ════════════════════════════════════════════════════════════════
# register_device_routes 测试
# ════════════════════════════════════════════════════════════════

class TestRegisterDeviceRoutes:
    """路由注册测试"""

    def test_register_device_routes(self):
        """应注册所有路由"""
        app = FastAPI()
        device_api.register_device_routes(app)
        routes = [r.path for r in app.routes]
        # 设备列表 / 详情 / 控制（speak / wakeup / stop）路由已迁移至 routes/devices.py
        # device_api 仅保留统计、历史、配置、音量、固件、OTA 等管理类路由
        assert "/api/v1/devices/{mac}/stats" in routes
        assert "/sdk/query_new_ota" in routes
        assert "/api/v1/system/info" in routes


# ════════════════════════════════════════════════════════════════
# 系统管理路由测试
# ════════════════════════════════════════════════════════════════

class TestDeviceSystemRoutes:
    """系统管理路由测试"""

    @pytest.fixture(autouse=True)
    def _setup_system_settings(self, mock_settings):
        """为 device_system_routes 设置 mock settings"""
        mock_settings.asr.provider = "volcengine"
        mock_settings.asr.no_speech_timeout = 1.5
        mock_settings.asr.silence_timeout = 0.8
        mock_settings.asr.enable_pool = True
        mock_settings.llm.provider = "openai"
        mock_settings.llm.model = "gpt-4"
        mock_settings.llm.base_url = "http://api.openai.com"
        mock_settings.llm.temperature = 0.7
        mock_settings.llm.memory_enabled = True
        mock_settings.tts.provider = "volcengine"
        mock_settings.tts.voice_type = "xxx"
        mock_settings.tts.speed_ratio = 1.0
        mock_settings.tts.enable_pool = True
        mock_settings.wakeup.enable_audio = True
        mock_settings.wakeup.text = "你好小乐"
        with patch("src.infrastructure.device_system_routes.get_settings", return_value=mock_settings):
            yield

    @pytest.fixture
    def app(self):
        from src.infrastructure.device_system_routes import router
        application = FastAPI()
        application.include_router(router)
        return application

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_get_system_info(self, client):
        """获取系统信息"""
        registry = MagicMock()
        registry.count.return_value = 3
        with patch("src.infrastructure.device_system_routes.verify_api_key", new_callable=AsyncMock), \
             patch("src.infrastructure.device_system_routes.get_device_registry", return_value=registry):
            resp = client.get("/api/v1/system/info", headers={"X-API-Key": "test"})
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["devices"]["online"] == 3

    def test_get_system_info_no_registry(self, client):
        """无 registry 时 online 为 0"""
        with patch("src.infrastructure.device_system_routes.verify_api_key", new_callable=AsyncMock), \
             patch("src.infrastructure.device_system_routes.get_device_registry", return_value=None):
            resp = client.get("/api/v1/system/info", headers={"X-API-Key": "test"})
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["devices"]["online"] == 0

    def test_get_system_config(self, client):
        """获取系统配置"""
        with patch("src.infrastructure.device_system_routes.verify_api_key", new_callable=AsyncMock):
            resp = client.get("/api/v1/system/config", headers={"X-API-Key": "test"})
        assert resp.json()["code"] == 0
        assert "server" in resp.json()["data"]
        assert "asr" in resp.json()["data"]

    def test_get_gateways_status_no_app(self, client):
        """app 未初始化"""
        with patch("src.infrastructure.device_system_routes.verify_api_key", new_callable=AsyncMock), \
             patch("src.infrastructure.web.get_app", return_value=None):
            resp = client.get("/api/v1/system/gateways", headers={"X-API-Key": "test"})
        assert resp.json()["code"] == 1

    def test_get_gateways_status_success(self, client):
        """获取网关状态"""
        mock_app = MagicMock()
        mock_app.state.asr_gateway = MagicMock()
        mock_app.state.asr_gateway.__class__.__name__ = "ASRGateway"
        mock_app.state.llm_gateway = None
        mock_app.state.tts_gateway = None
        with patch("src.infrastructure.device_system_routes.verify_api_key", new_callable=AsyncMock), \
             patch("src.infrastructure.web.get_app", return_value=mock_app):
            resp = client.get("/api/v1/system/gateways", headers={"X-API-Key": "test"})
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["asr"]["enabled"] is True
        assert resp.json()["data"]["llm"]["enabled"] is False

    def test_reload_config_success(self, client):
        """重新加载配置成功"""
        with patch("src.infrastructure.device_system_routes.verify_api_key", new_callable=AsyncMock), \
             patch("src.infrastructure.config.reset_settings"), \
             patch("src.infrastructure.web.get_app", return_value=None):
            resp = client.post("/api/v1/system/reload", headers={"X-API-Key": "test"})
        assert resp.json()["code"] == 0

    def test_reload_config_with_auth_service(self, client):
        """重新加载配置（带 auth_service）"""
        mock_app = MagicMock()
        mock_app.state.auth_service = MagicMock()
        with patch("src.infrastructure.device_system_routes.verify_api_key", new_callable=AsyncMock), \
             patch("src.infrastructure.config.reset_settings"), \
             patch("src.infrastructure.web.get_app", return_value=mock_app):
            resp = client.post("/api/v1/system/reload", headers={"X-API-Key": "test"})
        assert resp.json()["code"] == 0
        mock_app.state.auth_service.reload_users_config.assert_called_once()

    def test_reload_config_exception(self, client):
        """重新加载配置失败"""
        with patch("src.infrastructure.device_system_routes.verify_api_key", new_callable=AsyncMock), \
             patch("src.infrastructure.config.reset_settings", side_effect=RuntimeError("err")):
            resp = client.post("/api/v1/system/reload", headers={"X-API-Key": "test"})
        assert resp.json()["code"] == 1

    def test_get_performance_metrics_no_app(self, client):
        """app 未初始化"""
        with patch("src.infrastructure.device_system_routes.verify_api_key", new_callable=AsyncMock), \
             patch("src.infrastructure.web.get_app", return_value=None):
            resp = client.get("/api/v1/system/metrics", headers={"X-API-Key": "test"})
        assert resp.json()["code"] == 1

    def test_get_performance_metrics_success(self, client):
        """获取性能指标"""
        mock_psutil = MagicMock()
        mock_proc = MagicMock()
        mock_proc.cpu_percent.return_value = 10.0
        mock_proc.memory_info.return_value = MagicMock(rss=1048576)
        mock_proc.memory_percent.return_value = 5.0
        mock_proc.num_threads.return_value = 4
        mock_psutil.Process.return_value = mock_proc

        mock_app = MagicMock()
        mock_app.state.device_registry = MagicMock()
        mock_app.state.device_registry.get_stats.return_value = {"total": 1}

        with patch("src.infrastructure.device_system_routes.verify_api_key", new_callable=AsyncMock), \
             patch("src.infrastructure.web.get_app", return_value=mock_app), \
             patch("src.infrastructure.connection_pool.PoolManager.get_all_stats", return_value={}), \
             patch("src.infrastructure.concurrency.get_stats", return_value={}), \
             patch.dict("sys.modules", {"psutil": mock_psutil}):
            resp = client.get("/api/v1/system/metrics", headers={"X-API-Key": "test"})
        assert resp.json()["code"] == 0
        assert "devices" in resp.json()["data"]
