"""
web 模块单元测试

覆盖范围：
- create_app / get_app / get_speaker / get_device_registry / get_auth_service
- trace_id_middleware（X-Trace-Id 透传 / 自动生成 / 响应头）
- _add_skill_to_device / _remove_skill_from_all_devices（DB 读写）
- _hot_reload_device_config（registry 不存在 / resolve 失败等分支）
- _register_routes（路由注册）
- get_server_ips
- lifespan（startup + shutdown，mock 全部依赖）
"""
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.infrastructure import web


# ════════════════════════════════════════════════════════════════
# 测试夹具
# ════════════════════════════════════════════════════════════════

@pytest.fixture
def reset_app_instance():
    """每个测试前后重置全局 app 实例"""
    web._app_instance = None
    yield
    web._app_instance = None


@pytest.fixture
def mock_settings():
    """Mock get_settings 返回"""
    settings = MagicMock()
    settings.server.host = "localhost"
    settings.server.port = 8088
    settings.server.workers = 1
    settings.server.reload = False
    settings.server.ws_max_size = 20 * 1024 * 1024
    settings.server.cors_origins = ["*"]
    settings.auth.enabled = False
    settings.auth.api_key = ""
    settings.auth.admin_api_key = ""
    settings.asr.provider = "tencent"
    settings.asr.tencent_app_id = ""
    settings.asr.tencent_secret_id = ""
    settings.asr.tencent_secret_key = ""
    settings.asr.tencent_engine = "16k_zh"
    settings.asr.volcengine_api_key = ""
    settings.asr.volcengine_resource_id = ""
    settings.asr.volcengine_model = ""
    settings.asr.enable_pool = False
    settings.llm.api_key = ""
    settings.llm.base_url = ""
    settings.llm.model = ""
    settings.llm.system_prompt = ""
    settings.tts.api_key = ""
    settings.tts.resource_id = ""
    settings.tts.voice_type = ""
    settings.tts.speed_ratio = 1.0
    settings.tts.volume_ratio = 1.0
    settings.tts.pitch_ratio = 1.0
    settings.tts.enable_pool = False
    settings.mcp.servers_json = ""
    return settings


# ════════════════════════════════════════════════════════════════
# get_app / get_speaker / get_device_registry / get_auth_service 测试
# ════════════════════════════════════════════════════════════════

class TestGetApp:
    """get_app 及相关访问器测试"""

    def test_get_app_none_when_not_set(self, reset_app_instance):
        """未创建时 get_app 返回 None"""
        assert web.get_app() is None

    def test_get_app_returns_instance(self, reset_app_instance):
        """设置后返回实例"""
        fake_app = MagicMock()
        web._app_instance = fake_app
        assert web.get_app() is fake_app

    def test_get_speaker_no_app(self, reset_app_instance):
        """无 app 时 get_speaker 返回 None"""
        assert web.get_speaker() is None

    def test_get_speaker_with_app(self, reset_app_instance):
        """有 app 且有 speaker 时返回 speaker"""
        fake_app = MagicMock()
        fake_app.state.speaker = "speaker_instance"
        web._app_instance = fake_app
        assert web.get_speaker() == "speaker_instance"

    def test_get_speaker_app_without_speaker(self, reset_app_instance):
        """有 app 但无 speaker 属性时返回 None"""
        fake_app = MagicMock()
        fake_app.state = MagicMock()
        del fake_app.state.speaker
        web._app_instance = fake_app
        assert web.get_speaker() is None

    def test_get_device_registry_no_app(self, reset_app_instance):
        assert web.get_device_registry() is None

    def test_get_device_registry_with_app(self, reset_app_instance):
        fake_app = MagicMock()
        fake_app.state.device_registry = "registry_instance"
        web._app_instance = fake_app
        assert web.get_device_registry() == "registry_instance"

    def test_get_auth_service_no_app(self, reset_app_instance):
        assert web.get_auth_service() is None

    def test_get_auth_service_with_app(self, reset_app_instance):
        fake_app = MagicMock()
        fake_app.state.auth_service = "auth_instance"
        web._app_instance = fake_app
        assert web.get_auth_service() == "auth_instance"


# ════════════════════════════════════════════════════════════════
# trace_id_middleware 测试
# ════════════════════════════════════════════════════════════════

class TestTraceIdMiddleware:
    """trace_id 中间件测试"""

    async def test_middleware_with_trace_id_header(self):
        """请求带 X-Trace-Id 时应透传"""
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            return {"ok": True}

        app.middleware("http")(web.trace_id_middleware)
        client = TestClient(app)
        response = client.get("/test", headers={"X-Trace-Id": "my-trace-123"})
        assert response.status_code == 200
        assert response.headers["X-Trace-Id"] == "my-trace-123"
        assert "X-Response-Time" in response.headers

    async def test_middleware_generates_trace_id(self):
        """请求不带 X-Trace-Id 时应自动生成"""
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            return {"ok": True}

        app.middleware("http")(web.trace_id_middleware)
        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200
        assert response.headers["X-Trace-Id"] != ""
        assert len(response.headers["X-Trace-Id"]) > 0

    async def test_middleware_resets_context_var(self):
        """中间件结束后应重置 trace_id_var"""
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            return {"ok": True}

        app.middleware("http")(web.trace_id_middleware)
        client = TestClient(app)
        client.get("/test", headers={"X-Trace-Id": "trace-abc"})
        # 重置后默认值应为空
        assert web.trace_id_var.get() == ""


# ════════════════════════════════════════════════════════════════
# _add_skill_to_device / _remove_skill_from_all_devices 测试
# ════════════════════════════════════════════════════════════════

class TestSkillManagement:
    """技能写入 DB 测试（阶段 3：通过 DeviceRepository）"""

    async def test_add_skill_to_device_existing(self, tmp_path):
        """向已有设备添加技能"""
        with patch("src.infrastructure.db.repositories.device_repository.DeviceRepository") as MockRepo, \
             patch("src.infrastructure.web._hot_reload_device_config") as mock_reload:
            mock_repo = MockRepo.return_value
            mock_repo.add_skill_to_device = AsyncMock(return_value=True)
            await web._add_skill_to_device("dev1", "skill1")
            mock_repo.add_skill_to_device.assert_called_once_with("dev1", "skill1")
            mock_reload.assert_called_once_with("dev1")

    async def test_add_skill_to_device_by_key(self, tmp_path):
        """通过 key 匹配设备添加技能"""
        with patch("src.infrastructure.db.repositories.device_repository.DeviceRepository") as MockRepo, \
             patch("src.infrastructure.web._hot_reload_device_config"):
            mock_repo = MockRepo.return_value
            mock_repo.add_skill_to_device = AsyncMock(return_value=True)
            await web._add_skill_to_device("secret_key", "skill1")
            mock_repo.add_skill_to_device.assert_called_once_with("secret_key", "skill1")

    async def test_add_skill_creates_skills_list(self, tmp_path):
        """设备无 skills 字段时由仓储层创建"""
        with patch("src.infrastructure.db.repositories.device_repository.DeviceRepository") as MockRepo, \
             patch("src.infrastructure.web._hot_reload_device_config"):
            mock_repo = MockRepo.return_value
            mock_repo.add_skill_to_device = AsyncMock(return_value=True)
            await web._add_skill_to_device("dev1", "skill1")
            mock_repo.add_skill_to_device.assert_called_once_with("dev1", "skill1")

    async def test_add_skill_duplicate_not_added(self, tmp_path):
        """已存在的技能由仓储层去重"""
        with patch("src.infrastructure.db.repositories.device_repository.DeviceRepository") as MockRepo, \
             patch("src.infrastructure.web._hot_reload_device_config"):
            mock_repo = MockRepo.return_value
            mock_repo.add_skill_to_device = AsyncMock(return_value=True)
            await web._add_skill_to_device("dev1", "skill1")
            mock_repo.add_skill_to_device.assert_called_once_with("dev1", "skill1")

    async def test_add_skill_device_not_found(self, tmp_path):
        """设备不存在时仓储层返回 False，仍触发热重载"""
        with patch("src.infrastructure.db.repositories.device_repository.DeviceRepository") as MockRepo, \
             patch("src.infrastructure.web._hot_reload_device_config") as mock_reload:
            mock_repo = MockRepo.return_value
            mock_repo.add_skill_to_device = AsyncMock(return_value=False)
            await web._add_skill_to_device("nonexistent", "skill1")
            mock_repo.add_skill_to_device.assert_called_once_with("nonexistent", "skill1")
            mock_reload.assert_called_once_with("nonexistent")

    async def test_add_skill_db_exception_handled(self, tmp_path):
        """DB 异常时记录日志不抛出"""
        with patch("src.infrastructure.db.repositories.device_repository.DeviceRepository") as MockRepo, \
             patch("src.infrastructure.web._hot_reload_device_config"):
            mock_repo = MockRepo.return_value
            mock_repo.add_skill_to_device = AsyncMock(side_effect=RuntimeError("db error"))
            # 不应抛出异常
            await web._add_skill_to_device("dev1", "skill1")

    async def test_remove_skill_from_all_devices(self, tmp_path):
        """从所有设备移除技能"""
        with patch("src.infrastructure.db.repositories.device_repository.DeviceRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.remove_skill_from_all_devices = AsyncMock(return_value=2)
            await web._remove_skill_from_all_devices("skill1")
            mock_repo.remove_skill_from_all_devices.assert_called_once_with("skill1")

    async def test_remove_skill_no_changes(self, tmp_path):
        """无设备包含该技能时仓储层返回 0"""
        with patch("src.infrastructure.db.repositories.device_repository.DeviceRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.remove_skill_from_all_devices = AsyncMock(return_value=0)
            await web._remove_skill_from_all_devices("skill1")
            mock_repo.remove_skill_from_all_devices.assert_called_once_with("skill1")

    async def test_remove_skill_db_exception_handled(self, tmp_path):
        """DB 异常时记录日志不抛出"""
        with patch("src.infrastructure.db.repositories.device_repository.DeviceRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.remove_skill_from_all_devices = AsyncMock(side_effect=RuntimeError("db error"))
            # 不应抛出异常
            await web._remove_skill_from_all_devices("skill1")


# ════════════════════════════════════════════════════════════════
# _hot_reload_device_config 测试
# ════════════════════════════════════════════════════════════════

class TestHotReloadConfig:
    """_hot_reload_device_config 测试"""

    async def test_hot_reload_no_registry(self):
        """registry 不存在时应无操作"""
        with patch("src.infrastructure.device_api.get_device_registry", return_value=None), \
             patch("src.infrastructure.web.get_app", return_value=None):
            web._hot_reload_device_config("dev1")

    async def test_hot_reload_resolve_returns_none(self):
        """resolve_device_id 返回 None 时应无操作"""
        mock_registry = MagicMock()
        with patch("src.infrastructure.device_api.get_device_registry", return_value=mock_registry), \
             patch("src.infrastructure.device_api.resolve_device_id", return_value=None):
            web._hot_reload_device_config("dev1")

    async def test_hot_reload_device_not_in_registry(self):
        """registry.resolve 返回 None 时应无操作"""
        mock_registry = MagicMock()
        mock_registry.resolve.return_value = None
        with patch("src.infrastructure.device_api.get_device_registry", return_value=mock_registry), \
             patch("src.infrastructure.device_api.resolve_device_id", return_value="key1"):
            web._hot_reload_device_config("dev1")

    async def test_hot_reload_exception_handled(self):
        """整体异常应被捕获不抛出"""
        with patch("src.infrastructure.device_api.get_device_registry", side_effect=RuntimeError("boom")):
            # 不应抛异常
            web._hot_reload_device_config("dev1")

    async def test_hot_reload_success(self):
        """成功热重载时更新 user_config"""
        mock_registry = MagicMock()
        mock_device = {"user_config": MagicMock(), "tool_manager": MagicMock(), "session": MagicMock()}
        mock_registry.resolve.return_value = mock_device

        mock_dm = MagicMock()
        fresh_config = MagicMock()
        mock_dm.resolve.return_value = fresh_config

        with patch("src.infrastructure.device_api.get_device_registry", return_value=mock_registry), \
             patch("src.infrastructure.device_api.resolve_device_id", return_value="key1"), \
             patch("src.use_cases.auxiliary_services.load_devices", return_value=mock_dm):
            web._hot_reload_device_config("dev1")

        assert mock_device["user_config"] is fresh_config
        assert mock_device["tool_manager"].user_config is fresh_config
        assert mock_device["session"].user_config is fresh_config

    async def test_hot_reload_fresh_config_from_mac(self):
        """dm.resolve 返回 None 时回退到 dm.devices.get(device_id)"""
        mock_registry = MagicMock()
        mock_device = {"user_config": MagicMock(), "tool_manager": MagicMock()}
        mock_registry.resolve.return_value = mock_device

        mock_dm = MagicMock()
        mock_dm.resolve.return_value = None
        fresh_config = MagicMock()
        mock_dm.devices = {"dev1": fresh_config}

        with patch("src.infrastructure.device_api.get_device_registry", return_value=mock_registry), \
             patch("src.infrastructure.device_api.resolve_device_id", return_value="key1"), \
             patch("src.use_cases.auxiliary_services.load_devices", return_value=mock_dm):
            web._hot_reload_device_config("dev1")

        assert mock_device["user_config"] is fresh_config


# ════════════════════════════════════════════════════════════════
# get_server_ips 测试
# ════════════════════════════════════════════════════════════════

class TestGetServerIps:
    """get_server_ips 测试"""

    def test_returns_list(self):
        """应返回列表"""
        with patch("socket.socket") as mock_socket_cls:
            mock_sock = MagicMock()
            mock_sock.getsockname.return_value = ("192.168.1.100", 12345)
            mock_socket_cls.return_value = mock_sock
            ips = web.get_server_ips()
        assert isinstance(ips, list)
        assert "192.168.1.100" in ips
        assert "127.0.0.1" in ips

    def test_socket_exception_returns_empty(self):
        """socket 异常时返回空列表"""
        with patch("socket.socket", side_effect=OSError("no network")):
            ips = web.get_server_ips()
        assert ips == []


# ════════════════════════════════════════════════════════════════
# create_app 测试
# ════════════════════════════════════════════════════════════════

class TestCreateApp:
    """create_app 测试"""

    def test_create_app_returns_fastapi(self, reset_app_instance, mock_settings):
        """create_app 应返回 FastAPI 实例"""
        with patch("src.infrastructure.web.get_settings", return_value=mock_settings), \
             patch("src.infrastructure.web._register_routes"):
            app = web.create_app()
        assert app is not None
        assert isinstance(app, FastAPI)
        assert app.title == "ESP AI Server"
        # OpenAPI 元数据应包含分组与文档地址
        assert app.docs_url == "/docs"
        assert app.redoc_url == "/redoc"
        tag_names = {t["name"] for t in app.openapi_tags}
        assert {"system", "devices", "mcp", "skills", "emos", "growth"} <= tag_names

    def test_create_app_sets_global_instance(self, reset_app_instance, mock_settings):
        """create_app 应设置全局 app 实例"""
        with patch("src.infrastructure.web.get_settings", return_value=mock_settings), \
             patch("src.infrastructure.web._register_routes"):
            app = web.create_app()
        assert web.get_app() is app

    def test_create_app_registers_middleware(self, reset_app_instance, mock_settings):
        """create_app 应注册 trace_id 中间件"""
        with patch("src.infrastructure.web.get_settings", return_value=mock_settings), \
             patch("src.infrastructure.web._register_routes"):
            app = web.create_app()
        # 通过实际请求验证中间件工作
        client = TestClient(app)
        response = client.get("/health/live")
        # 路由可能不存在（_register_routes 被 mock），但中间件应添加 header
        assert "X-Trace-Id" in response.headers


# ════════════════════════════════════════════════════════════════
# _register_routes 测试
# ════════════════════════════════════════════════════════════════

class TestRegisterRoutes:
    """_register_routes 路由注册测试"""

    def test_register_routes_calls_all_registrars(self, mock_settings):
        """应调用所有路由模块的 register_routes"""
        app = FastAPI()

        # 用真实异步函数代替 MagicMock，避免 FastAPI 内部签名检查失败
        async def _fake_ws_handler(websocket):
            pass

        with patch("src.infrastructure.device_api.register_device_routes") as mock_device, \
             patch("src.infrastructure.routes.system.register_routes") as mock_system, \
             patch("src.infrastructure.routes.devices.register_routes") as mock_devices, \
             patch("src.infrastructure.routes.skills.register_routes") as mock_skills, \
             patch("src.infrastructure.routes.mcp.register_routes") as mock_mcp, \
             patch("src.infrastructure.routes.emos.register_routes") as mock_emos, \
             patch("src.infrastructure.routes.growth.register_routes") as mock_growth, \
             patch("src.interfaces.websocket_handler.handle_websocket", new=_fake_ws_handler):
            web._register_routes(app)

        mock_device.assert_called_once_with(app)
        mock_system.assert_called_once_with(app)
        mock_devices.assert_called_once_with(app)
        mock_skills.assert_called_once_with(app)
        mock_mcp.assert_called_once_with(app)
        mock_emos.assert_called_once_with(app)
        mock_growth.assert_called_once_with(app)

    def test_register_routes_adds_websocket_endpoints(self, mock_settings):
        """应添加 WebSocket 端点"""
        app = FastAPI()

        async def _fake_ws_handler(websocket):
            pass

        with patch("src.infrastructure.device_api.register_device_routes"), \
             patch("src.infrastructure.routes.system.register_routes"), \
             patch("src.infrastructure.routes.devices.register_routes"), \
             patch("src.infrastructure.routes.skills.register_routes"), \
             patch("src.infrastructure.routes.mcp.register_routes"), \
             patch("src.infrastructure.routes.emos.register_routes"), \
             patch("src.infrastructure.routes.growth.register_routes"), \
             patch("src.interfaces.websocket_handler.handle_websocket", new=_fake_ws_handler):
            web._register_routes(app)

        # 验证 WebSocket 路由存在
        ws_routes = [r for r in app.routes if hasattr(r, "path") and r.path in ("/", "/connect_espai_node")]
        assert len(ws_routes) >= 2


# ════════════════════════════════════════════════════════════════
# lifespan 测试
# ════════════════════════════════════════════════════════════════

class TestLifespan:
    """lifespan 启动/关闭测试"""

    async def test_lifespan_startup_and_shutdown(self, mock_settings, tmp_path):
        """lifespan 应正常启动和关闭"""
        app = FastAPI()

        with patch("src.infrastructure.web.get_settings", return_value=mock_settings), \
             patch("src.infrastructure.concurrency.init_concurrency_control"), \
             patch("src.infrastructure.concurrency.shutdown"), \
             patch("src.infrastructure.emo_pack.migrate_old_format", new_callable=AsyncMock), \
             patch("src.interfaces.gateways.create_asr_gateway", side_effect=Exception("skip")), \
             patch("src.interfaces.llm_gateways.create_llm_gateway", side_effect=Exception("skip")), \
             patch("src.interfaces.tts_gateways.create_tts_gateway", side_effect=Exception("skip")), \
             patch("src.use_cases.tools_system.create_tool_manager", side_effect=Exception("skip")), \
             patch("src.use_cases.auxiliary_services.DeviceRegistry"), \
             patch("src.use_cases.auxiliary_services.WakeAudioManager"), \
             patch("src.use_cases.auxiliary_services.create_speaker", side_effect=Exception("skip")), \
             patch("src.use_cases.auxiliary_services.create_auth_service", side_effect=Exception("skip")), \
             patch("pathlib.Path.mkdir"):
            async with web.lifespan(app):
                pass  # startup 完成
            # shutdown 完成后无异常即可

    async def test_lifespan_shutdown_closes_gateways(self, mock_settings):
        """shutdown 应关闭各 gateway"""
        app = FastAPI()
        # 在 lifespan 启动后设置 mock，避免被 startup 覆盖
        mock_tts = AsyncMock()
        mock_asr = AsyncMock()
        mock_llm = AsyncMock()
        mock_tool = AsyncMock()
        mock_shared = AsyncMock()

        with patch("src.infrastructure.web.get_settings", return_value=mock_settings), \
             patch("src.infrastructure.concurrency.init_concurrency_control"), \
             patch("src.infrastructure.concurrency.shutdown"), \
             patch("src.infrastructure.emo_pack.migrate_old_format", new_callable=AsyncMock), \
             patch("src.interfaces.gateways.create_asr_gateway", side_effect=Exception("skip")), \
             patch("src.interfaces.llm_gateways.create_llm_gateway", side_effect=Exception("skip")), \
             patch("src.interfaces.tts_gateways.create_tts_gateway", side_effect=Exception("skip")), \
             patch("src.use_cases.tools_system.create_tool_manager", side_effect=Exception("skip")), \
             patch("src.use_cases.auxiliary_services.DeviceRegistry"), \
             patch("src.use_cases.auxiliary_services.WakeAudioManager"), \
             patch("src.use_cases.auxiliary_services.create_speaker", side_effect=Exception("skip")), \
             patch("src.use_cases.auxiliary_services.create_auth_service", side_effect=Exception("skip")), \
             patch("src.interfaces.gateways.TencentASRGateway.close_pool", new_callable=AsyncMock), \
             patch("src.interfaces.gateways.VolcEngineASRGateway.close_pool", new_callable=AsyncMock), \
             patch("src.interfaces.tts_gateways.VolcEngineTTSGateway.close_pool", new_callable=AsyncMock), \
             patch("pathlib.Path.mkdir"):
            async with web.lifespan(app):
                # 在 startup 之后、shutdown 之前设置 mock gateway
                app.state.tts_gateway = mock_tts
                app.state.asr_gateway = mock_asr
                app.state.llm_gateway = mock_llm
                app.state.tool_manager = mock_tool
                app.state.shared_tool_manager = mock_shared

        mock_tts.close.assert_called_once()
        mock_asr.close.assert_called_once()
        mock_llm.close.assert_called_once()
        mock_tool.cleanup.assert_called_once()
        mock_shared.cleanup.assert_called_once()

    async def test_lifespan_shutdown_handles_close_exception(self, mock_settings):
        """shutdown 关闭 gateway 异常时不应中断"""
        app = FastAPI()
        mock_tts = AsyncMock()
        mock_tts.close.side_effect = RuntimeError("close failed")

        with patch("src.infrastructure.web.get_settings", return_value=mock_settings), \
             patch("src.infrastructure.concurrency.init_concurrency_control"), \
             patch("src.infrastructure.concurrency.shutdown"), \
             patch("src.infrastructure.emo_pack.migrate_old_format", new_callable=AsyncMock), \
             patch("src.interfaces.gateways.create_asr_gateway", side_effect=Exception("skip")), \
             patch("src.interfaces.llm_gateways.create_llm_gateway", side_effect=Exception("skip")), \
             patch("src.interfaces.tts_gateways.create_tts_gateway", side_effect=Exception("skip")), \
             patch("src.use_cases.tools_system.create_tool_manager", side_effect=Exception("skip")), \
             patch("src.use_cases.auxiliary_services.DeviceRegistry"), \
             patch("src.use_cases.auxiliary_services.WakeAudioManager"), \
             patch("src.use_cases.auxiliary_services.create_speaker", side_effect=Exception("skip")), \
             patch("src.use_cases.auxiliary_services.create_auth_service", side_effect=Exception("skip")), \
             patch("src.interfaces.gateways.TencentASRGateway.close_pool", new_callable=AsyncMock), \
             patch("src.interfaces.gateways.VolcEngineASRGateway.close_pool", new_callable=AsyncMock), \
             patch("src.interfaces.tts_gateways.VolcEngineTTSGateway.close_pool", new_callable=AsyncMock), \
             patch("pathlib.Path.mkdir"):
            # 不应抛异常
            async with web.lifespan(app):
                app.state.tts_gateway = mock_tts

    async def test_lifespan_shutdown_no_gateways(self, mock_settings):
        """无 gateway 时 shutdown 也不报错"""
        app = FastAPI()

        with patch("src.infrastructure.web.get_settings", return_value=mock_settings), \
             patch("src.infrastructure.concurrency.init_concurrency_control"), \
             patch("src.infrastructure.concurrency.shutdown"), \
             patch("src.infrastructure.emo_pack.migrate_old_format", new_callable=AsyncMock), \
             patch("src.interfaces.gateways.create_asr_gateway", side_effect=Exception("skip")), \
             patch("src.interfaces.llm_gateways.create_llm_gateway", side_effect=Exception("skip")), \
             patch("src.interfaces.tts_gateways.create_tts_gateway", side_effect=Exception("skip")), \
             patch("src.use_cases.tools_system.create_tool_manager", side_effect=Exception("skip")), \
             patch("src.use_cases.auxiliary_services.DeviceRegistry"), \
             patch("src.use_cases.auxiliary_services.WakeAudioManager"), \
             patch("src.use_cases.auxiliary_services.create_speaker", side_effect=Exception("skip")), \
             patch("src.use_cases.auxiliary_services.create_auth_service", side_effect=Exception("skip")), \
             patch("src.interfaces.gateways.TencentASRGateway.close_pool", new_callable=AsyncMock), \
             patch("src.interfaces.gateways.VolcEngineASRGateway.close_pool", new_callable=AsyncMock), \
             patch("src.interfaces.tts_gateways.VolcEngineTTSGateway.close_pool", new_callable=AsyncMock), \
             patch("pathlib.Path.mkdir"):
            async with web.lifespan(app):
                pass

    async def test_lifespan_init_tool_manager_and_mcp(self, mock_settings):
        """tool_manager 初始化成功后应预连接 MCP"""
        app = FastAPI()
        mock_tool_manager = MagicMock()
        mock_tool_manager.initialize_mcp = AsyncMock()
        mock_settings.mcp.get_servers.return_value = {"server1": {}}

        with patch("src.infrastructure.web.get_settings", return_value=mock_settings), \
             patch("src.infrastructure.concurrency.init_concurrency_control"), \
             patch("src.infrastructure.concurrency.shutdown"), \
             patch("src.infrastructure.emo_pack.migrate_old_format", new_callable=AsyncMock), \
             patch("src.interfaces.gateways.create_asr_gateway", side_effect=Exception("skip")), \
             patch("src.interfaces.llm_gateways.create_llm_gateway", side_effect=Exception("skip")), \
             patch("src.interfaces.tts_gateways.create_tts_gateway", side_effect=Exception("skip")), \
             patch("src.use_cases.tools_system.create_tool_manager", return_value=mock_tool_manager), \
             patch("src.use_cases.tools_system._shared_tool_manager", MagicMock()), \
             patch("src.use_cases.skill_system.init"), \
             patch("src.use_cases.auxiliary_services.DeviceRegistry"), \
             patch("src.use_cases.auxiliary_services.WakeAudioManager"), \
             patch("src.use_cases.auxiliary_services.create_speaker", side_effect=Exception("skip")), \
             patch("src.use_cases.auxiliary_services.create_auth_service", side_effect=Exception("skip")), \
             patch("pathlib.Path.mkdir"):
            async with web.lifespan(app):
                pass

        mock_tool_manager.initialize_mcp.assert_called_once()

    async def test_lifespan_mcp_preconnect_failure(self, mock_settings):
        """MCP 预连接失败不应中断启动"""
        app = FastAPI()
        mock_tool_manager = MagicMock()
        mock_tool_manager.initialize_mcp = AsyncMock(side_effect=RuntimeError("mcp failed"))
        mock_settings.mcp.get_servers.return_value = {"server1": {}}

        with patch("src.infrastructure.web.get_settings", return_value=mock_settings), \
             patch("src.infrastructure.concurrency.init_concurrency_control"), \
             patch("src.infrastructure.concurrency.shutdown"), \
             patch("src.infrastructure.emo_pack.migrate_old_format", new_callable=AsyncMock), \
             patch("src.interfaces.gateways.create_asr_gateway", side_effect=Exception("skip")), \
             patch("src.interfaces.llm_gateways.create_llm_gateway", side_effect=Exception("skip")), \
             patch("src.interfaces.tts_gateways.create_tts_gateway", side_effect=Exception("skip")), \
             patch("src.use_cases.tools_system.create_tool_manager", return_value=mock_tool_manager), \
             patch("src.use_cases.tools_system._shared_tool_manager", MagicMock()), \
             patch("src.use_cases.skill_system.init"), \
             patch("src.use_cases.auxiliary_services.DeviceRegistry"), \
             patch("src.use_cases.auxiliary_services.WakeAudioManager"), \
             patch("src.use_cases.auxiliary_services.create_speaker", side_effect=Exception("skip")), \
             patch("src.use_cases.auxiliary_services.create_auth_service", side_effect=Exception("skip")), \
             patch("pathlib.Path.mkdir"):
            # 不应抛异常
            async with web.lifespan(app):
                pass


# ════════════════════════════════════════════════════════════════
# infrastructure 包懒加载测试
# ════════════════════════════════════════════════════════════════

class TestInfrastructureInit:
    """infrastructure 包 __init__.py 懒加载测试"""

    def test_get_settings(self):
        from src.infrastructure import get_settings
        assert callable(get_settings)

    def test_get_settings_class(self):
        from src.infrastructure import Settings
        assert Settings is not None

    def test_get_logger(self):
        from src.infrastructure import get_logger
        assert callable(get_logger)

    def test_structured_logger(self):
        from src.infrastructure import StructuredLogger
        assert StructuredLogger is not None

    def test_metrics_collector(self):
        from src.infrastructure import MetricsCollector
        assert MetricsCollector is not None

    def test_remote_config_provider(self):
        from src.infrastructure import RemoteConfigProvider
        assert RemoteConfigProvider is not None

    def test_get_remote_config_provider(self):
        from src.infrastructure import get_remote_config_provider
        assert callable(get_remote_config_provider)

    def test_create_app(self):
        from src.infrastructure import create_app
        assert callable(create_app)

    def test_lifespan(self):
        from src.infrastructure import lifespan
        assert callable(lifespan)

    def test_connection_pool_base(self):
        from src.infrastructure import ConnectionPoolBase
        assert ConnectionPoolBase is not None

    def test_connection_wrapper(self):
        from src.infrastructure import ConnectionWrapper
        assert ConnectionWrapper is not None

    def test_invalid_attribute(self):
        """访问不存在的属性应抛出 AttributeError"""
        import src.infrastructure as infra
        with pytest.raises(AttributeError):
            _ = infra.nonexistent_attribute
