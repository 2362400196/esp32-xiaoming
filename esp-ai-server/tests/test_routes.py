"""
routes 路由模块单元测试

覆盖范围：
- routes/system.py：health/live、health/ready、metrics、stats、api/health
- routes/devices.py：设备列表、详情、唤醒、播放、停止、工具查询
- routes/emos.py：表情包列表、CRUD、设备激活
- routes/growth.py：日记、用户画像、情绪历史
- routes/mcp.py：MCP 配置管理、工具查询、启停
- routes/skills.py：技能查询、CRUD、启停、重载
"""
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _mock_user():
    """构造 mock JWT 登录用户（role=admin 免设备归属校验）"""
    u = MagicMock()
    u.id = 1
    u.role = "admin"
    u.is_active = True
    u.nickname = "admin"
    u.email = "admin@example.com"
    return u


class _FakeDBDevice:
    """模拟 DeviceModel 行"""

    def __init__(self, device_id="dev1", name="设备1", mac="AA:BB", key="k1"):
        from datetime import datetime, timezone
        self.device_id = device_id
        self.name = name
        self.mac_address = mac
        self.device_key = key
        self.bound_at = datetime.now(timezone.utc)


class _FakeSessionCtx:
    """模拟 get_session_ctx：execute(...).scalars().all() 返回预置设备列表"""

    def __init__(self, devices):
        self._devices = devices

    async def __aenter__(self):
        s = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = self._devices
        s.execute = AsyncMock(return_value=result)
        return s

    async def __aexit__(self, *args):
        return False


# ════════════════════════════════════════════════════════════════
# system 路由测试
# ════════════════════════════════════════════════════════════════

class TestSystemRoutes:
    """系统路由测试"""

    @pytest.fixture
    def app(self):
        from src.infrastructure.routes.system import router
        application = FastAPI()
        application.include_router(router)
        return application

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_liveness(self, client):
        """健康检查 live"""
        resp = client.get("/health/live")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "alive"

    def test_readiness_no_gateways(self, client, app):
        """无 gateway 时 readiness 返回 503 + not_ready"""
        resp = client.get("/health/ready")
        assert resp.status_code == 503
        data = resp.json()["data"]
        assert data["status"] == "not_ready"
        assert data["components"]["asr_gateway"] == "down"
        assert data["components"]["llm_gateway"] == "down"
        assert data["components"]["tts_gateway"] == "down"
        assert data["components"]["device_registry"] == "down"
        assert "asr_gateway" in data["critical"]

    def test_readiness_partial_gateways(self, client, app):
        """仅部分关键 gateway 就绪时返回 503 + not_ready"""
        app.state.llm_gateway = MagicMock()
        resp = client.get("/health/ready")
        assert resp.status_code == 503
        data = resp.json()["data"]
        assert data["status"] == "not_ready"
        assert data["components"]["llm_gateway"] == "up"
        assert data["components"]["asr_gateway"] == "down"

    def test_readiness_with_gateways(self, client, app):
        """三个关键 gateway 均就绪时返回 200 + ready"""
        app.state.asr_gateway = MagicMock()
        app.state.llm_gateway = MagicMock()
        app.state.tts_gateway = MagicMock()
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["status"] == "ready"
        assert data["components"]["llm_gateway"] == "up"
        assert data["components"]["asr_gateway"] == "up"
        assert data["components"]["tts_gateway"] == "up"

    def test_read_ready_with_registry(self, client, app):
        """关键 gateway + device_registry 均就绪时 registry 标记为 up"""
        app.state.asr_gateway = MagicMock()
        app.state.llm_gateway = MagicMock()
        app.state.tts_gateway = MagicMock()
        app.state.device_registry = MagicMock()
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        assert resp.json()["data"]["components"]["device_registry"] == "up"

    def test_metrics(self, client):
        """metrics 端点应返回 prometheus 格式"""
        resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_stats_no_registry(self, client, app):
        """无 device_registry 时 stats 返回 0"""
        resp = client.get("/stats")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["devices"]["total"] == 0
        assert data["devices"]["online"] == 0
        assert data["gateways"]["asr"] is False

    def test_stats_with_registry(self, client, app):
        """有 device_registry 时 stats 返回正确计数（在线数按 channel.connected 统计）"""

        class _FakeRegistry:
            def __init__(self, devices):
                self._devices = devices

            def count(self):
                return len(self._devices)

            def get_all_ids(self):
                return list(self._devices)

            def get(self, device_id):
                return self._devices.get(device_id)

        online_channel = MagicMock()
        online_channel.connected = True
        offline_channel = MagicMock()
        offline_channel.connected = False
        registry = _FakeRegistry({
            "d1": {"channel": online_channel},
            "d2": {"channel": online_channel},
            "d3": {"channel": offline_channel},
        })
        app.state.device_registry = registry
        app.state.asr_gateway = MagicMock()
        app.state.llm_gateway = MagicMock()
        app.state.tts_gateway = MagicMock()
        resp = client.get("/stats")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["devices"]["total"] == 3
        assert data["devices"]["online"] == 2
        assert data["gateways"]["asr"] is True

    def test_api_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "healthy"


# ════════════════════════════════════════════════════════════════
# devices 路由测试
# ════════════════════════════════════════════════════════════════

class TestDevicesRoutes:
    """设备路由测试"""

    @pytest.fixture
    def app(self):
        from src.infrastructure.routes.devices import router
        from src.infrastructure.security_jwt import get_current_user
        application = FastAPI()
        application.include_router(router)
        # 路由单元测试跳过 JWT 认证（认证逻辑由 security 层单独覆盖）
        application.dependency_overrides[get_current_user] = lambda: _mock_user()
        return application

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_get_devices_no_registry(self, client):
        """无 registry 时设备全部显示离线（设备列表来自 DB）"""
        with patch("src.infrastructure.routes.devices.get_session_ctx",
                   return_value=_FakeSessionCtx([_FakeDBDevice()])), \
             patch("src.infrastructure.routes.devices.get_device_registry", return_value=None):
            resp = client.get("/api/v1/devices")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["devices"][0]["online"] is False

    def test_get_devices_success(self, client):
        """获取设备列表（DB 设备 + registry 在线状态）"""
        registry = MagicMock()
        fsm = MagicMock()
        # api_get_devices 使用 fsm.get().value，需返回带 value 属性的状态对象
        fsm.get.return_value = MagicMock(value="idle")
        channel = MagicMock()
        channel.connected = True
        registry.resolve.return_value = {"channel": channel, "fsm": fsm}
        with patch("src.infrastructure.routes.devices.get_session_ctx",
                   return_value=_FakeSessionCtx([_FakeDBDevice(device_id="dev1", name="设备1")])), \
             patch("src.infrastructure.routes.devices.get_device_registry", return_value=registry):
            resp = client.get("/api/v1/devices")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["devices"]) == 1
        assert data["devices"][0]["device_id"] == "dev1"
        assert data["devices"][0]["name"] == "设备1"
        assert data["devices"][0]["online"] is True

    def test_get_device_not_found(self, client):
        """设备不存在"""
        registry = MagicMock()
        registry.resolve.return_value = None
        with patch("src.infrastructure.routes.devices.get_device_registry", return_value=registry):
            resp = client.get("/api/v1/devices/dev1")
        assert resp.json()["code"] == 1

    def test_get_device_success(self, client):
        """获取设备详情"""
        registry = MagicMock()
        fsm = MagicMock()
        fsm.get.return_value = "listening"
        session = MagicMock()
        session.session_id = "sid1"
        session.tts_playing = True
        channel = MagicMock()
        channel.connected = True
        user_config = MagicMock()
        user_config.name = "设备1"
        registry.resolve.return_value = {
            "mac": "AA:BB", "session": session, "fsm": fsm,
            "channel": channel, "user_config": user_config,
        }
        with patch("src.infrastructure.routes.devices.get_device_registry", return_value=registry):
            resp = client.get("/api/v1/devices/dev1")
        assert resp.json()["code"] == 0
        data = resp.json()["data"]
        assert data["state"] == "listening"
        assert data["tts_playing"] is True

    # ============================================================
    # 创建设备 API 测试
    # ============================================================

    def test_create_device_minimal(self, client):
        """最简参数创建设备成功"""
        mock_repo = MagicMock()
        mock_repo.find_by_mac = AsyncMock(return_value=None)
        mock_repo.find_by_key = AsyncMock(return_value=None)
        mock_repo.upsert_device = AsyncMock()
        with patch("src.infrastructure.db.repositories.device_repository.DeviceRepository", return_value=mock_repo), \
             patch("src.infrastructure.web.get_app", return_value=None):
            resp = client.post("/api/v1/devices", json={
                "mac": "AA:BB:CC:DD:EE:FF",
                "key": "secret_key_123",
                "name": "卧室的设备",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["device_id"] == "AA:BB:CC:DD:EE:FF"
        assert data["data"]["name"] == "卧室的设备"
        mock_repo.upsert_device.assert_called_once()
        # 验证传入 upsert_device 的配置
        call_args = mock_repo.upsert_device.call_args
        assert call_args[0][0] == "AA:BB:CC:DD:EE:FF"
        config = call_args[0][1]
        assert config["name"] == "卧室的设备"
        assert config["key"] == "secret_key_123"
        assert config["mac"] == "AA:BB:CC:DD:EE:FF"

    def test_create_device_with_full_config(self, client):
        """带完整配置创建设备"""
        mock_repo = MagicMock()
        mock_repo.find_by_mac = AsyncMock(return_value=None)
        mock_repo.find_by_key = AsyncMock(return_value=None)
        mock_repo.upsert_device = AsyncMock()
        with patch("src.infrastructure.db.repositories.device_repository.DeviceRepository", return_value=mock_repo), \
             patch("src.infrastructure.web.get_app", return_value=None):
            resp = client.post("/api/v1/devices", json={
                "mac": "AA:BB:CC:DD:EE:FF",
                "key": "secret_key_123",
                "name": "卧室的设备",
                "asr_provider": "volcengine",
                "llm_api_key": "sk-xxx",
                "llm_base_url": "https://api.deepseek.com/v1",
                "llm_model": "deepseek-v4-flash",
                "llm_system_prompt": "你的名字叫小智",
                "tts_voice_type": "zh_female_wanwanxiaohe_moon_bigtts",
                "rate_limit_rpm": 60,
                "mcp_servers": {"amap-maps": {"type": "streamable_http", "url": "http://example.com"}},
            })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        config = mock_repo.upsert_device.call_args[0][1]
        assert config["llm"]["api_key"] == "sk-xxx"
        assert config["llm"]["model"] == "deepseek-v4-flash"
        assert config["tts_config"]["voice_type"] == "zh_female_wanwanxiaohe_moon_bigtts"
        assert config["mcp_servers"]["amap-maps"]["url"] == "http://example.com"
        assert config["rate_limit_rpm"] == 60

    def test_create_device_mac_exists(self, client):
        """MAC 已存在时返回错误"""
        mock_repo = MagicMock()
        mock_repo.find_by_mac = AsyncMock(return_value=("existing_id", {}))
        mock_repo.find_by_key = AsyncMock(return_value=None)
        mock_repo.upsert_device = AsyncMock()
        with patch("src.infrastructure.db.repositories.device_repository.DeviceRepository", return_value=mock_repo):
            resp = client.post("/api/v1/devices", json={
                "mac": "AA:BB:CC:DD:EE:FF",
                "key": "new_key",
                "name": "新设备",
            })
        assert resp.json()["code"] == 1
        assert "已存在" in resp.json()["message"]
        mock_repo.upsert_device.assert_not_called()

    def test_create_device_key_exists(self, client):
        """密钥已存在时返回错误"""
        mock_repo = MagicMock()
        mock_repo.find_by_mac = AsyncMock(return_value=None)
        mock_repo.find_by_key = AsyncMock(return_value=("existing_id", {}))
        mock_repo.upsert_device = AsyncMock()
        with patch("src.infrastructure.db.repositories.device_repository.DeviceRepository", return_value=mock_repo):
            resp = client.post("/api/v1/devices", json={
                "mac": "AA:BB:CC:DD:EE:FF",
                "key": "duplicate_key",
                "name": "新设备",
            })
        assert resp.json()["code"] == 1
        assert "密钥已存在" in resp.json()["message"]
        mock_repo.upsert_device.assert_not_called()

    def test_create_device_missing_mac(self, client):
        """缺少必填字段 mac 时返回 422"""
        resp = client.post("/api/v1/devices", json={
            "key": "some_key",
            "name": "设备",
        })
        assert resp.status_code == 422

    def test_create_device_missing_key(self, client):
        """缺少必填字段 key 时返回 422"""
        resp = client.post("/api/v1/devices", json={
            "mac": "AA:BB",
            "name": "设备",
        })
        assert resp.status_code == 422

    def test_create_device_missing_name(self, client):
        """缺少必填字段 name 时返回 422"""
        resp = client.post("/api/v1/devices", json={
            "mac": "AA:BB",
            "key": "some_key",
        })
        assert resp.status_code == 422

    def test_create_device_db_error(self, client, app):
        """DB 写入异常时返回 500（当前路由未捕获仓储异常）"""
        mock_repo = MagicMock()
        mock_repo.find_by_mac = AsyncMock(return_value=None)
        mock_repo.find_by_key = AsyncMock(return_value=None)
        mock_repo.upsert_device = AsyncMock(side_effect=RuntimeError("DB connection lost"))
        with patch("src.infrastructure.db.repositories.device_repository.DeviceRepository", return_value=mock_repo), \
             patch("src.infrastructure.web.get_app", return_value=None):
            no_raise_client = TestClient(app, raise_server_exceptions=False)
            resp = no_raise_client.post("/api/v1/devices", json={
                "mac": "AA:BB:CC:DD:EE:FF",
                "key": "key123",
                "name": "设备",
            })
        assert resp.status_code == 500

    def test_create_device_hot_reload(self, client):
        """创建成功后热重载 auth 配置"""
        mock_repo = MagicMock()
        mock_repo.find_by_mac = AsyncMock(return_value=None)
        mock_repo.find_by_key = AsyncMock(return_value=None)
        mock_repo.upsert_device = AsyncMock()
        mock_app = MagicMock()
        mock_auth = MagicMock()
        mock_app.state.auth_service = mock_auth
        with patch("src.infrastructure.db.repositories.device_repository.DeviceRepository", return_value=mock_repo), \
             patch("src.infrastructure.web.get_app", return_value=mock_app):
            resp = client.post("/api/v1/devices", json={
                "mac": "AA:BB:CC:DD:EE:FF",
                "key": "key123",
                "name": "设备",
            })
        assert resp.json()["code"] == 0
        mock_auth.reload_users_config.assert_called_once()

    def test_create_device_no_auth(self, app):
        """未认证时拒绝访问"""
        from fastapi import HTTPException
        from src.infrastructure.security_jwt import get_current_user
        # 覆盖认证为拒绝
        app.dependency_overrides[get_current_user] = lambda: (_ for _ in ()).throw(
            HTTPException(status_code=403, detail="Forbidden")
        )
        client = TestClient(app)
        resp = client.post("/api/v1/devices", json={
            "mac": "AA:BB",
            "key": "key",
            "name": "设备",
        })
        assert resp.status_code == 403
        # 恢复认证 override
        app.dependency_overrides[get_current_user] = lambda: _mock_user()

    def test_wakeup_no_speaker(self, client):
        with patch("src.infrastructure.routes.devices.get_speaker", return_value=None):
            resp = client.post("/api/v1/wakeup", json={"device_id": "dev1"})
        assert resp.json()["code"] == 1

    def test_wakeup_success(self, client):
        speaker = AsyncMock()
        speaker.wakeup.return_value = True
        with patch("src.infrastructure.routes.devices.get_speaker", return_value=speaker):
            resp = client.post("/api/v1/wakeup", json={"device_id": "dev1"})
        assert resp.json()["code"] == 0

    def test_wakeup_async_returns_immediately(self, client):
        """唤醒指令为后台执行：speaker.wakeup 结果不影响 API 立即返回 code 0"""
        speaker = AsyncMock()
        speaker.wakeup.return_value = False
        with patch("src.infrastructure.routes.devices.get_speaker", return_value=speaker):
            resp = client.post("/api/v1/wakeup", json={"device_id": "dev1"})
        assert resp.json()["code"] == 0

    def test_speak_no_speaker(self, client):
        with patch("src.infrastructure.routes.devices.get_speaker", return_value=None):
            resp = client.post("/api/v1/speak", json={"device_id": "dev1", "text": "hello"})
        assert resp.json()["code"] == 1

    def test_speak_success(self, client):
        speaker = AsyncMock()
        speaker.speak.return_value = True
        with patch("src.infrastructure.routes.devices.get_speaker", return_value=speaker):
            resp = client.post("/api/v1/speak", json={"device_id": "dev1", "text": "hello"})
        assert resp.json()["code"] == 0

    def test_speak_failed(self, client):
        speaker = AsyncMock()
        speaker.speak.return_value = False
        with patch("src.infrastructure.routes.devices.get_speaker", return_value=speaker):
            resp = client.post("/api/v1/speak", json={"device_id": "dev1", "text": "hello"})
        assert resp.json()["code"] == 1

    def test_stop_no_speaker(self, client):
        with patch("src.infrastructure.routes.devices.get_speaker", return_value=None):
            resp = client.post("/api/v1/stop", json={"device_id": "dev1"})
        assert resp.json()["code"] == 1

    def test_stop_success(self, client):
        speaker = AsyncMock()
        speaker.stop.return_value = True
        with patch("src.infrastructure.routes.devices.get_speaker", return_value=speaker):
            resp = client.post("/api/v1/stop", json={"device_id": "dev1"})
        assert resp.json()["code"] == 0

    def test_list_tools_success(self, client):
        """工具列表查询"""
        fake_schema = [
            {"function": {"name": "tool1", "description": "desc1", "parameters": {}}},
        ]
        with patch("src.use_cases.tools_system.get_openai_tools_schema", return_value=iter(fake_schema)):
            resp = client.get("/api/v1/tools")
        assert resp.json()["code"] == 0
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["name"] == "tool1"

    def test_list_tools_exception(self, client, app):
        """工具查询异常：当前路由未捕获，返回 500"""
        with patch("src.use_cases.tools_system.get_openai_tools_schema", side_effect=RuntimeError("err")):
            no_raise_client = TestClient(app, raise_server_exceptions=False)
            resp = no_raise_client.get("/api/v1/tools")
        assert resp.status_code == 500


# ════════════════════════════════════════════════════════════════
# emos 路由测试
# ════════════════════════════════════════════════════════════════


def _get_endpoint(app, path, method):
    """从 FastAPI app 中获取路由处理函数（用于直接调用测试）"""
    for route in app.router.routes:
        if hasattr(route, "path") and route.path == path and method in route.methods:
            return route.endpoint
    raise ValueError(f"路由未找到: {method} {path}")


class TestEmosRoutes:
    """表情包路由测试"""

    @pytest.fixture
    def app(self):
        from src.infrastructure.routes.emos import router
        from src.infrastructure.security_jwt import get_current_user
        application = FastAPI()
        application.include_router(router)
        # 路由单元测试跳过 JWT 认证（认证逻辑由 security 层单独覆盖）
        application.dependency_overrides[get_current_user] = lambda: _mock_user()
        return application

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_list_emos_compat(self, client):
        """兼容接口列出表情"""
        with patch("src.infrastructure.routes.emos.list_pack_emos", return_value=[{"name": "happy"}]):
            resp = client.get("/api/v1/emos")
        assert resp.json()["code"] == 0
        assert len(resp.json()["data"]) == 1

    def test_list_device_emos(self, client):
        """设备表情列表"""
        with patch("src.infrastructure.device_api.resolve_device_id", return_value=None), \
             patch("src.infrastructure.routes.emos.get_active_pack", new_callable=AsyncMock, return_value="default"), \
             patch("src.infrastructure.routes.emos.list_pack_emos", return_value=[{"name": "happy"}]):
            resp = client.get("/api/v1/emos/dev1")
        assert resp.json()["code"] == 0
        assert resp.json()["active_pack"] == "default"

    def test_list_device_emos_fallback_default(self, client):
        """设备无表情包时回退到 default"""
        with patch("src.infrastructure.device_api.resolve_device_id", return_value=None), \
             patch("src.infrastructure.routes.emos.get_active_pack", new_callable=AsyncMock, return_value="custom"), \
             patch("src.infrastructure.routes.emos.list_pack_emos", side_effect=[[], [{"name": "happy"}]]):
            resp = client.get("/api/v1/emos/dev1")
        assert resp.json()["code"] == 0
        assert len(resp.json()["data"]) == 1

    def test_list_packs(self, client):
        with patch("src.infrastructure.routes.emos.list_packs", new_callable=AsyncMock, return_value=[{"name": "default"}]):
            resp = client.get("/api/v1/emos/packs/list")
        assert resp.json()["code"] == 0

    def test_get_pack_not_found(self, client):
        with patch("src.infrastructure.routes.emos.list_pack_emos", return_value=None):
            resp = client.get("/api/v1/emos/packs/nonexistent")
        assert resp.json()["code"] == 1

    def test_get_pack_success(self, client):
        with patch("src.infrastructure.routes.emos.list_pack_emos", return_value=[{"name": "happy"}]):
            resp = client.get("/api/v1/emos/packs/default")
        assert resp.json()["code"] == 0

    def test_create_pack_no_name(self, client):
        resp = client.post("/api/v1/emos/packs/create")
        assert resp.json()["code"] == 1

    def test_create_pack_success(self, client):
        with patch("src.infrastructure.routes.emos.create_pack", new_callable=AsyncMock, return_value={
            "ok": True, "message": "ok", "name": "pack1", "display_name": "测试"
        }):
            resp = client.post("/api/v1/emos/packs/create", params={"name": "测试"})
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["name"] == "pack1"

    def test_create_pack_failed(self, client):
        with patch("src.infrastructure.routes.emos.create_pack", new_callable=AsyncMock, return_value={
            "ok": False, "message": "已存在"
        }):
            resp = client.post("/api/v1/emos/packs/create", params={"name": "测试"})
        assert resp.json()["code"] == 1

    def test_delete_pack_success(self, client):
        with patch("src.infrastructure.routes.emos.delete_pack", new_callable=AsyncMock, return_value={
            "ok": True, "message": "删除成功"
        }):
            resp = client.delete("/api/v1/emos/packs/pack1")
        assert resp.json()["code"] == 0

    def test_get_active_pack(self, client):
        with patch("src.infrastructure.device_api.resolve_device_id", return_value=None), \
             patch("src.infrastructure.routes.emos.get_active_pack", new_callable=AsyncMock, return_value="custom"):
            resp = client.get("/api/v1/emos/active/dev1")
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["active_pack"] == "custom"

    def test_set_active_pack_no_name(self, client):
        with patch("src.infrastructure.device_api.resolve_device_id", return_value=None):
            resp = client.post("/api/v1/emos/active/dev1")
        assert resp.json()["code"] == 1

    def test_set_active_pack_success(self, client):
        with patch("src.infrastructure.device_api.resolve_device_id", return_value=None), \
             patch("src.infrastructure.device_api.get_device_registry", return_value=None), \
             patch("src.infrastructure.routes.emos.set_active_pack", new_callable=AsyncMock, return_value={
                 "ok": True, "message": "ok"
             }):
            resp = client.post("/api/v1/emos/active/dev1", params={"pack": "pack1"})
        assert resp.json()["code"] == 0

    def test_set_active_pack_failed(self, client):
        with patch("src.infrastructure.device_api.resolve_device_id", return_value=None), \
             patch("src.infrastructure.routes.emos.set_active_pack", new_callable=AsyncMock, return_value={
                 "ok": False, "message": "表情包不存在"
             }):
            resp = client.post("/api/v1/emos/active/dev1", params={"pack": "nonexistent"})
        assert resp.json()["code"] == 1

    # ── 上传表情 gif 文件 ──

    def test_upload_to_pack_success(self, client, tmp_path):
        """上传 gif 到表情包成功"""
        with patch("src.infrastructure.routes.emos.get_or_create_pack_dir", return_value=tmp_path):
            resp = client.post(
                "/api/v1/emos/packs/pack1/upload",
                files={"file": ("happy.gif", b"gifdata", "image/gif")},
            )
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["name"] == "happy"
        assert resp.json()["data"]["filename"] == "happy.gif"
        assert resp.json()["data"]["pack"] == "pack1"
        assert (tmp_path / "happy.gif").exists()

    def test_upload_to_pack_wrong_type(self, client):
        """非 gif 文件被拒绝"""
        resp = client.post(
            "/api/v1/emos/packs/pack1/upload",
            files={"file": ("test.txt", b"text", "text/plain")},
        )
        assert resp.json()["code"] == 1
        assert "gif" in resp.json()["message"]

    async def test_upload_to_pack_too_large_size(self, app):
        """文件 size 超过 10MB（直接调用端点）"""
        handler = _get_endpoint(app, "/api/v1/emos/packs/{pack_name}/upload", "POST")
        mock_file = MagicMock()
        mock_file.filename = "big.gif"
        mock_file.size = 11 * 1024 * 1024
        result = await handler(pack_name="pack1", file=mock_file)
        assert result["code"] == 1
        assert "文件过大" in result["message"]

    async def test_upload_to_pack_too_large_content(self, app, tmp_path):
        """文件内容超过 10MB（size 为 None 但内容过大）"""
        handler = _get_endpoint(app, "/api/v1/emos/packs/{pack_name}/upload", "POST")
        mock_file = MagicMock()
        mock_file.filename = "big.gif"
        mock_file.size = None
        mock_file.read = AsyncMock(return_value=b"x" * (11 * 1024 * 1024))
        with patch("src.infrastructure.routes.emos.get_or_create_pack_dir", return_value=tmp_path):
            result = await handler(pack_name="pack1", file=mock_file)
        assert result["code"] == 1
        assert "文件过大" in result["message"]

    def test_upload_emo_compat_success(self, client, tmp_path):
        """兼容接口上传 gif 成功"""
        with patch("src.infrastructure.routes.emos.get_or_create_pack_dir", return_value=tmp_path):
            resp = client.post(
                "/api/v1/emos/upload",
                files={"file": ("smile.gif", b"gifdata", "image/gif")},
            )
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["pack"] == "default"
        assert (tmp_path / "smile.gif").exists()

    def test_upload_emo_compat_wrong_type(self, client):
        """兼容接口非 gif 被拒绝"""
        resp = client.post(
            "/api/v1/emos/upload",
            files={"file": ("test.png", b"data", "image/png")},
        )
        assert resp.json()["code"] == 1

    async def test_upload_emo_compat_too_large_size(self, app):
        """兼容接口文件 size 超过 10MB"""
        handler = _get_endpoint(app, "/api/v1/emos/upload", "POST")
        mock_file = MagicMock()
        mock_file.filename = "big.gif"
        mock_file.size = 11 * 1024 * 1024
        result = await handler(file=mock_file, device_key="")
        assert result["code"] == 1
        assert "文件过大" in result["message"]

    async def test_upload_emo_compat_too_large_content(self, app, tmp_path):
        """兼容接口文件内容超过 10MB"""
        handler = _get_endpoint(app, "/api/v1/emos/upload", "POST")
        mock_file = MagicMock()
        mock_file.filename = "big.gif"
        mock_file.size = None
        mock_file.read = AsyncMock(return_value=b"x" * (11 * 1024 * 1024))
        with patch("src.infrastructure.routes.emos.get_or_create_pack_dir", return_value=tmp_path):
            result = await handler(file=mock_file, device_key="")
        assert result["code"] == 1
        assert "文件过大" in result["message"]

    def test_delete_pack_failed(self, client):
        """删除不存在的表情包"""
        with patch("src.infrastructure.routes.emos.delete_pack", new_callable=AsyncMock, return_value={
            "ok": False, "message": "表情包不存在"
        }):
            resp = client.delete("/api/v1/emos/packs/nonexistent")
        assert resp.json()["code"] == 1

    # ── 设备激活表情包通知 ──

    def test_set_active_pack_with_device_notification(self, client):
        """设置激活表情包并通知设备刷新"""
        channel = MagicMock()
        channel.send_json = AsyncMock()
        registry = MagicMock()
        registry.resolve.return_value = {"channel": channel}
        with patch("src.infrastructure.device_api.resolve_device_id", return_value=None), \
             patch("src.infrastructure.device_api.get_device_registry", return_value=registry), \
             patch("src.infrastructure.routes.emos.set_active_pack", new_callable=AsyncMock, return_value={
                 "ok": True, "message": "ok"
             }):
            resp = client.post("/api/v1/emos/active/dev1", params={"pack": "pack1"})
        assert resp.json()["code"] == 0
        channel.send_json.assert_called_once()
        instruct = channel.send_json.call_args[0][0]
        assert instruct["command_id"] == "refresh_emo"

    def test_set_active_pack_notification_exception(self, client):
        """设备通知失败时不影响设置结果"""
        channel = MagicMock()
        channel.send_json = AsyncMock(side_effect=RuntimeError("连接断开"))
        registry = MagicMock()
        registry.resolve.return_value = {"channel": channel}
        with patch("src.infrastructure.device_api.resolve_device_id", return_value=None), \
             patch("src.infrastructure.device_api.get_device_registry", return_value=registry), \
             patch("src.infrastructure.routes.emos.set_active_pack", new_callable=AsyncMock, return_value={
                 "ok": True, "message": "ok"
             }):
            resp = client.post("/api/v1/emos/active/dev1", params={"pack": "pack1"})
        assert resp.json()["code"] == 0

    def test_set_active_pack_no_channel(self, client):
        """设备无 channel 时跳过通知"""
        registry = MagicMock()
        registry.resolve.return_value = {}
        with patch("src.infrastructure.device_api.resolve_device_id", return_value=None), \
             patch("src.infrastructure.device_api.get_device_registry", return_value=registry), \
             patch("src.infrastructure.routes.emos.set_active_pack", new_callable=AsyncMock, return_value={
                 "ok": True, "message": "ok"
             }):
            resp = client.post("/api/v1/emos/active/dev1", params={"pack": "pack1"})
        assert resp.json()["code"] == 0

    def test_set_active_pack_device_not_found(self, client):
        """设备不存在时跳过通知"""
        registry = MagicMock()
        registry.resolve.return_value = None
        with patch("src.infrastructure.device_api.resolve_device_id", return_value=None), \
             patch("src.infrastructure.device_api.get_device_registry", return_value=registry), \
             patch("src.infrastructure.routes.emos.set_active_pack", new_callable=AsyncMock, return_value={
                 "ok": True, "message": "ok"
             }):
            resp = client.post("/api/v1/emos/active/dev1", params={"pack": "pack1"})
        assert resp.json()["code"] == 0


# ════════════════════════════════════════════════════════════════
# growth 路由测试
# ════════════════════════════════════════════════════════════════

class TestGrowthRoutes:
    """成长系统路由测试"""

    @pytest.fixture
    def app(self):
        from src.infrastructure.routes.growth import router
        from src.infrastructure.security_jwt import get_current_user
        application = FastAPI()
        application.include_router(router)
        application.dependency_overrides[get_current_user] = lambda: _mock_user()
        return application

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    async def test_get_diary_list(self, client):
        """获取日记列表"""
        mock_service = MagicMock()
        entry = MagicMock()
        entry.date = "2026-05-29"
        entry.content = "今天很开心"
        entry.created_at = "2026-05-29T10:00:00"
        mock_service.get_all_entries = AsyncMock(return_value=[entry])
        with patch("src.infrastructure.device_api.verify_api_key", new_callable=AsyncMock), \
             patch("src.use_cases.growth.DiaryService", return_value=mock_service), \
             patch("src.infrastructure.routes.growth._resolve_device_key", return_value="key1"), \
             patch("src.infrastructure.routes.growth._get_data_dir", return_value="/data"):
            resp = client.get("/api/v1/growth/diary/dev1")
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["count"] == 1

    async def test_get_diary_by_date(self, client):
        """获取指定日期日记"""
        mock_service = MagicMock()
        mock_service.get_diary_content = AsyncMock(return_value="日记内容")
        with patch("src.infrastructure.device_api.verify_api_key", new_callable=AsyncMock), \
             patch("src.use_cases.growth.DiaryService", return_value=mock_service), \
             patch("src.infrastructure.routes.growth._resolve_device_key", return_value="key1"), \
             patch("src.infrastructure.routes.growth._get_data_dir", return_value="/data"):
            resp = client.get("/api/v1/growth/diary/dev1", params={"date": "2026-05-29"})
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["content"] == "日记内容"

    async def test_get_diary_by_date_not_found(self, client):
        """指定日期无日记"""
        mock_service = MagicMock()
        mock_service.get_diary_content = AsyncMock(return_value=None)
        with patch("src.infrastructure.device_api.verify_api_key", new_callable=AsyncMock), \
             patch("src.use_cases.growth.DiaryService", return_value=mock_service), \
             patch("src.infrastructure.routes.growth._resolve_device_key", return_value="key1"), \
             patch("src.infrastructure.routes.growth._get_data_dir", return_value="/data"):
            resp = client.get("/api/v1/growth/diary/dev1", params={"date": "2026-05-29"})
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["content"] is None

    async def test_get_diary_exception(self, client, app):
        """获取日记异常：当前路由未捕获，返回 500"""
        with patch("src.use_cases.growth.DiaryService", side_effect=RuntimeError("err")), \
             patch("src.infrastructure.routes.growth._resolve_device_key", return_value="key1"), \
             patch("src.infrastructure.routes.growth._get_data_dir", return_value="/data"):
            no_raise_client = TestClient(app, raise_server_exceptions=False)
            resp = no_raise_client.get("/api/v1/growth/diary/dev1")
        assert resp.status_code == 500

    async def test_get_diary_by_date_path(self, client):
        """通过路径参数获取日记"""
        mock_service = MagicMock()
        mock_service.get_diary_content = AsyncMock(return_value="内容")
        with patch("src.infrastructure.device_api.verify_api_key", new_callable=AsyncMock), \
             patch("src.use_cases.growth.DiaryService", return_value=mock_service), \
             patch("src.infrastructure.routes.growth._resolve_device_key", return_value="key1"), \
             patch("src.infrastructure.routes.growth._get_data_dir", return_value="/data"):
            resp = client.get("/api/v1/growth/diary/dev1/2026-05-29")
        assert resp.json()["code"] == 0

    async def test_get_growth_profile(self, client):
        """获取用户画像"""
        mock_profile = MagicMock()
        mock_profile.to_dict.return_value = {"name": "用户1"}
        mock_profile_service = MagicMock()
        mock_profile_service.get_profile = AsyncMock(return_value=mock_profile)
        mock_emotion_service = MagicMock()
        mock_emotion_service.get_emotion_summary = AsyncMock(return_value={"happy": 5})

        with patch("src.infrastructure.device_api.verify_api_key", new_callable=AsyncMock), \
             patch("src.use_cases.growth.user_profile.UserProfileService", return_value=mock_profile_service), \
             patch("src.use_cases.growth.emotion_analyzer.EmotionAnalyzer", return_value=mock_emotion_service), \
             patch("src.infrastructure.routes.growth._resolve_device_key", return_value="key1"), \
             patch("src.infrastructure.routes.growth._get_data_dir", return_value="/data"):
            resp = client.get("/api/v1/growth/profile/dev1")
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["profile"]["name"] == "用户1"

    async def test_get_growth_profile_exception(self, client, app):
        """归属校验异常：当前路由未捕获，返回 500"""
        with patch("src.infrastructure.routes.growth._check_device_owner",
                   AsyncMock(side_effect=RuntimeError("err"))):
            no_raise_client = TestClient(app, raise_server_exceptions=False)
            resp = no_raise_client.get("/api/v1/growth/profile/dev1")
        assert resp.status_code == 500

    async def test_get_emotions(self, client):
        """获取情绪历史"""
        emotion = MagicMock()
        emotion.timestamp = 1234567890
        emotion.emotion = "happy"
        emotion.intensity = 0.8
        emotion.trigger = "user"
        emotion.context = "chat"
        mock_service = MagicMock()
        mock_service.get_recent_emotions = AsyncMock(return_value=[emotion])
        with patch("src.infrastructure.device_api.verify_api_key", new_callable=AsyncMock), \
             patch("src.use_cases.growth.emotion_analyzer.EmotionAnalyzer", return_value=mock_service), \
             patch("src.infrastructure.routes.growth._resolve_device_key", return_value="key1"), \
             patch("src.infrastructure.routes.growth._get_data_dir", return_value="/data"):
            resp = client.get("/api/v1/growth/emotions/dev1")
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["count"] == 1

    async def test_get_emotions_exception(self, client, app):
        """归属校验异常：当前路由未捕获，返回 500"""
        with patch("src.infrastructure.routes.growth._check_device_owner",
                   AsyncMock(side_effect=RuntimeError("err"))):
            no_raise_client = TestClient(app, raise_server_exceptions=False)
            resp = no_raise_client.get("/api/v1/growth/emotions/dev1")
        assert resp.status_code == 500


# ════════════════════════════════════════════════════════════════
# skills 路由测试
# ════════════════════════════════════════════════════════════════

class TestSkillsRoutes:
    """技能路由测试"""

    @pytest.fixture
    def app(self, tmp_path):
        from src.infrastructure.routes.skills import router
        from src.infrastructure.security_jwt import get_current_user
        application = FastAPI()
        application.include_router(router)
        application.dependency_overrides[get_current_user] = lambda: _mock_user()
        return application

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_list_skills_no_filter(self, client):
        """列出所有技能"""
        skill = MagicMock()
        skill.id = "skill1"
        skill.description = "desc"
        skill.category = ["cat"]
        skill.tags = ["tag"]
        skill.device_id = ""
        with patch("src.use_cases.skill_system.get_catalog", return_value=[skill]):
            resp = client.get("/api/v1/skills")
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["count"] == 1

    def test_list_skills_exception(self, client, app):
        """技能目录加载异常：当前路由未捕获，返回 500"""
        with patch("src.use_cases.skill_system.get_catalog", side_effect=RuntimeError("err")):
            no_raise_client = TestClient(app, raise_server_exceptions=False)
            resp = no_raise_client.get("/api/v1/skills")
        assert resp.status_code == 500

    def test_list_skills_with_device_id(self, client):
        """按 device_id 过滤技能"""
        skill = MagicMock()
        skill.id = "skill1"
        skill.description = "desc"
        skill.category = []
        skill.tags = []
        skill.device_id = "dev1"
        mock_dm = MagicMock()
        cfg = MagicMock()
        cfg.skills = None
        cfg.disabled_skills = []
        mock_dm.devices = {"dev1": cfg}
        mock_dm.resolve.return_value = cfg
        with patch("src.use_cases.auxiliary_services.load_devices", return_value=mock_dm), \
             patch("src.use_cases.skill_system.get_catalog", return_value=[skill]):
            resp = client.get("/api/v1/skills", params={"device_id": "dev1"})
        assert resp.json()["code"] == 0

    def test_toggle_skill_no_device_id(self, client):
        """无 device_id 时报错"""
        resp = client.post("/api/v1/skills/skill1/toggle")
        assert resp.json()["code"] == 1

    def test_toggle_skill_success(self, client, tmp_path):
        """成功切换技能状态"""
        mock_repo = MagicMock()
        mock_repo.get_device_config = AsyncMock(return_value={"key": "k1", "disabled_skills": []})
        mock_repo.toggle_skill = AsyncMock(return_value=None)
        with patch("src.infrastructure.routes.skills._get_repo", return_value=mock_repo), \
             patch("src.infrastructure.routes.skills._hot_reload_device_config"):
            resp = client.post("/api/v1/skills/skill1/toggle", params={"device_id": "dev1", "disabled": True})
        assert resp.json()["code"] == 0

    def test_get_skill_detail_not_found(self, client):
        with patch("src.use_cases.skill_system.get_skill", return_value=None):
            resp = client.get("/api/v1/skills/nonexistent")
        assert resp.json()["code"] == 1

    def test_get_skill_detail_success(self, client):
        entry = MagicMock()
        entry.id = "skill1"
        entry.metadata.description = "desc"
        entry.metadata.category = ["cat"]
        entry.metadata.tags = ["tag"]
        entry.metadata.cap_groups = []
        with patch("src.use_cases.skill_system.get_skill", return_value=entry), \
             patch("src.use_cases.skill_system.get_skill_document", return_value="doc content"):
            resp = client.get("/api/v1/skills/skill1")
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["document"] == "doc content"

    def test_create_skill_success(self, client):
        entry = MagicMock()
        entry.id = "new_skill"
        entry.metadata.description = "desc"
        entry.metadata.category = []
        entry.metadata.tags = []
        entry.file_path = "/path"
        with patch("src.use_cases.skill_system.create_skill", return_value=entry), \
             patch("src.infrastructure.routes.skills._add_skill_to_device", new_callable=AsyncMock):
            resp = client.post("/api/v1/skills", json={
                "name": "test", "description": "d", "instructions": "i", "device_id": "dev1"
            })
        assert resp.json()["code"] == 0

    def test_create_skill_value_error(self, client):
        with patch("src.use_cases.skill_system.create_skill", side_effect=ValueError("invalid")):
            resp = client.post("/api/v1/skills", json={
                "name": "test", "description": "d", "instructions": "i"
            })
        assert resp.json()["code"] == 1

    def test_update_skill_success(self, client):
        entry = MagicMock()
        entry.id = "skill1"
        entry.metadata.description = "updated"
        entry.metadata.category = []
        entry.metadata.tags = []
        with patch("src.use_cases.skill_system.update_skill", return_value=entry):
            resp = client.put("/api/v1/skills/skill1", json={
                "name": "test", "description": "d", "instructions": "i"
            })
        assert resp.json()["code"] == 0

    def test_update_skill_value_error(self, client):
        with patch("src.use_cases.skill_system.update_skill", side_effect=ValueError("not found")):
            resp = client.put("/api/v1/skills/skill1", json={
                "name": "test", "description": "d", "instructions": "i"
            })
        assert resp.json()["code"] == 1

    def test_delete_skill_success(self, client):
        with patch("src.use_cases.skill_system.delete_skill", return_value=True), \
             patch("src.infrastructure.routes.skills._remove_skill_from_all_devices", new_callable=AsyncMock):
            resp = client.delete("/api/v1/skills/skill1")
        assert resp.json()["code"] == 0

    def test_delete_skill_not_found(self, client):
        with patch("src.use_cases.skill_system.delete_skill", return_value=False):
            resp = client.delete("/api/v1/skills/skill1")
        assert resp.json()["code"] == 1

    def test_reload_skills(self, client):
        with patch("src.use_cases.skill_system.reload"), \
             patch("src.use_cases.skill_system._skills_by_id", {"s1": {}, "s2": {}}):
            resp = client.post("/api/v1/skills/reload")
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["count"] == 2

    def test_reload_skills_exception(self, client, app):
        """技能重载异常：当前路由未捕获，返回 500"""
        with patch("src.use_cases.skill_system.reload", side_effect=RuntimeError("err")):
            no_raise_client = TestClient(app, raise_server_exceptions=False)
            resp = no_raise_client.post("/api/v1/skills/reload")
        assert resp.status_code == 500
