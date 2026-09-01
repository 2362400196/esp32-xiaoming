"""
管理员后台修复回归测试

覆盖范围：
- GET /admin/conversations：短期记忆按 device_key（bound_*）存储时能正确
  映射回设备（历史 bug：按 devices.device_id 查询导致列表恒为空）；
  device_id 筛选参数转换为记忆键；无设备的遗留记忆仍可见
- GET /admin/operation-logs：分页（total/total_pages）、最新在前排序
"""
import asyncio

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.infrastructure.db.base import Base
from src.infrastructure.db.models.device import DeviceModel
from src.infrastructure.db.models.memory import ShortTermMemoryModel
from src.infrastructure.db.models.user import UserModel
from src.infrastructure.routes import admin as admin_routes
from src.infrastructure.routes.admin import router


# ════════════════════════════════════════════════════════════════
# 夹具：内存 DB + 绕过鉴权的 admin 路由
# ════════════════════════════════════════════════════════════════

@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    # 独立文件库：接口内部既走 async session（设备/用户）又走 sync session
    # （短期记忆仓储），两侧必须指向同一份数据
    db_file = tmp_path / "test_admin.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_file}", echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker
    sync_engine = create_engine(f"sqlite:///{db_file}", future=True)
    sync_factory = sessionmaker(bind=sync_engine, class_=Session, expire_on_commit=False, autoflush=False)
    import src.infrastructure.db.compat.sync_session as sync_mod
    monkeypatch.setattr(sync_mod, "_sync_engine", sync_engine)
    monkeypatch.setattr(sync_mod, "_sync_session_factory", sync_factory)

    async_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    import src.infrastructure.db.engine as engine_mod
    monkeypatch.setattr(engine_mod, "_async_engine", engine)
    monkeypatch.setattr(engine_mod, "_async_session_factory", async_factory)

    # 操作日志文件隔离到临时目录
    monkeypatch.setattr(
        admin_routes, "OPLOG_FILE", str(tmp_path / "admin_operation_logs.json")
    )

    app = FastAPI()
    app.include_router(router)

    async def fake_admin():
        user = MagicMock_user()
        return user

    class MagicMock_user:
        email = "admin@test.local"

    app.dependency_overrides[admin_routes.require_admin] = fake_admin

    # 造数据：
    #   用户 u1 绑定设备 dev-mac（device_key=bound_key1）
    #   记忆按 bound_key1 存储（与线上行为一致）
    #   另有一条无设备对应的遗留记忆 orphan_key
    async with async_factory() as session:
        session.add(UserModel(
            id="u1", email="user1@test.local", nickname="用户一",
            password_hash="x", role="user",
        ))
        session.add(DeviceModel(
            device_id="D8:3B:DA:6D:D9:3C", device_key="bound_key1",
            name="测试设备", user_id="u1",
        ))
        session.add(ShortTermMemoryModel(
            device_id="bound_key1", role="user", content="你好", seq=1, timestamp=100,
        ))
        session.add(ShortTermMemoryModel(
            device_id="bound_key1", role="assistant", content="你好呀", seq=2, timestamp=101,
        ))
        session.add(ShortTermMemoryModel(
            device_id="orphan_key", role="user", content="遗留消息", seq=1, timestamp=50,
        ))
        await session.commit()

    yield TestClient(app), async_factory
    await engine.dispose()
    sync_engine.dispose()


# ════════════════════════════════════════════════════════════════
# 对话记录
# ════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestAdminConversations:
    def test_lists_memory_by_device_key(self, client):
        """记忆按 device_key 存储时，对话记录不再为空"""
        tc, _factory = client
        res = tc.get("/api/v1/admin/conversations")
        assert res.status_code == 200
        convs = res.json()["data"]["conversations"]
        assert len(convs) == 2  # 绑定设备 + 遗留记忆

        bound = next(c for c in convs if c["device_key"] == "bound_key1")
        assert bound["device_id"] == "D8:3B:DA:6D:D9:3C"  # 映射回设备表主键
        assert bound["device_name"] == "测试设备"
        assert bound["owner_email"] == "user1@test.local"
        assert len(bound["messages"]) == 2

        orphan = next(c for c in convs if c["device_key"] == "orphan_key")
        assert orphan["device_name"] == "orphan_key"  # 无设备对应时回退显示原始键
        assert orphan["owner_email"] == ""

    def test_filter_by_device_id_translates_to_key(self, client):
        """筛选参数是 devices 表 device_id（MAC），内部转换为记忆键"""
        tc, _factory = client
        res = tc.get("/api/v1/admin/conversations", params={"device_id": "D8:3B:DA:6D:D9:3C"})
        assert res.status_code == 200
        convs = res.json()["data"]["conversations"]
        assert len(convs) == 1
        assert convs[0]["device_key"] == "bound_key1"
        assert len(convs[0]["messages"]) == 2

    def test_sorted_by_latest_message(self, client):
        tc, _factory = client
        res = tc.get("/api/v1/admin/conversations")
        convs = res.json()["data"]["conversations"]
        timestamps = [max(m["timestamp"] for m in c["messages"]) for c in convs]
        assert timestamps == sorted(timestamps, reverse=True)


# ════════════════════════════════════════════════════════════════
# 操作日志分页
# ════════════════════════════════════════════════════════════════

class TestOperationLogsPagination:
    def _seed_logs(self, count):
        # 模拟 _add_oplog 的 insert(0) 行为：第 1 条写入后排在最前（最新）
        logs = []
        for i in range(count):
            logs.insert(0, {"time": 1000.0 + i, "admin": f"a{i}@x", "action": "test", "detail": f"#{i}"})
        return logs

    def test_pagination_and_order(self, client, tmp_path):
        tc, _factory = client
        # 写入 25 条日志文件（最新在前）
        import json
        with open(admin_routes.OPLOG_FILE, "w", encoding="utf-8") as f:
            json.dump(self._seed_logs(25), f, ensure_ascii=False)

        res = tc.get("/api/v1/admin/operation-logs", params={"page": 1, "page_size": 10})
        data = res.json()["data"]
        assert data["total"] == 25
        assert data["total_pages"] == 3
        assert len(data["logs"]) == 10
        # 最新在前：#24（最后写入，insert(0) 后排最前）
        assert data["logs"][0]["detail"] == "#24"

        res2 = tc.get("/api/v1/admin/operation-logs", params={"page": 3, "page_size": 10})
        data2 = res2.json()["data"]
        assert len(data2["logs"]) == 5
        assert data2["logs"][-1]["detail"] == "#0"  # 最旧在最后一页末尾

    def test_empty_logs(self, client):
        tc, _factory = client
        res = tc.get("/api/v1/admin/operation-logs")
        data = res.json()["data"]
        assert data["total"] == 0
        assert data["logs"] == []
        assert data["total_pages"] == 1


# ════════════════════════════════════════════════════════════════
# 性能指标（活跃任务等并发数据）
# ════════════════════════════════════════════════════════════════

class TestAdminMetrics:
    def test_metrics_json_shape(self, client):
        """指标端点返回结构化 JSON（/system/metrics 是 Prometheus 文本，前端无法用）"""
        tc, _factory = client
        res = tc.get("/api/v1/admin/metrics")
        assert res.status_code == 200
        data = res.json()["data"]
        assert isinstance(data["system"]["cpu_percent"], (int, float))
        assert isinstance(data["system"]["num_threads"], int)
        conc = data["concurrency"]
        assert isinstance(conc["active_tasks"], int)
        assert conc["queued_tasks"] == 0
        assert isinstance(conc["completed_tasks"], int) and conc["completed_tasks"] >= 0
        # 活跃任务明细：[{name, elapsed}]，供仪表盘弹窗展示
        assert isinstance(conc["active_task_list"], list)
        for t in conc["active_task_list"]:
            assert isinstance(t["name"], str) and t["name"]
            assert isinstance(t["elapsed"], (int, float)) and t["elapsed"] >= 0
        # 最近完成任务（最新在前，含名称/耗时/成败）
        assert isinstance(conc["recent_task_list"], list)
        for t in conc["recent_task_list"]:
            assert isinstance(t["name"], str) and t["name"]
            assert isinstance(t["success"], bool)
            assert isinstance(t["ended_at"], float)
        assert isinstance(data["pools"], dict)
        assert isinstance(data["uptime"], float)


class TestAdminLogsFormat:
    def test_json_lines_formatted_like_console(self, client, tmp_path, monkeypatch):
        """文件日志为 JSON-lines 时格式化成终端同款可读样式，非 JSON 行原样保留"""
        from src.infrastructure.config import get_settings
        tc, _factory = client
        log_file = tmp_path / "esp_ai.log"
        log_file.write_text(
            '{"ts": "2026-08-30T12:47:48.290331Z", "level": "INFO", "msg": "[DB] 数据库初始化完成", '
            '"name": "esp_ai", "trace_id": "t1", "session_id": "-", "device_id": "d9"}' + chr(10) +
            "uvicorn 访问日志原样保留" + chr(10),
            encoding="utf-8",
        )
        settings = get_settings()
        saved = settings.log.file_path
        settings.log.file_path = str(log_file)
        try:
            res = tc.get("/api/v1/admin/logs?lines=10")
        finally:
            settings.log.file_path = saved
        lines = res.json()["data"]["lines"]
        assert lines[0] == "[12:47:48.290] [INFO] [t1/-/d9] [DB] 数据库初始化完成"
        assert lines[1] == "uvicorn 访问日志原样保留"


class TestAdminDeviceDetail:
    @pytest.mark.asyncio
    async def test_device_detail_fields(self, client):
        """详情接口返回运行时字段（离线设备 online_seconds 为 None）"""
        tc, _factory = client
        res = tc.get("/api/v1/admin/devices/D8:3B:DA:6D:D9:3C/detail")
        assert res.status_code == 200
        d = res.json()["data"]
        assert d["device_id"] == "D8:3B:DA:6D:D9:3C"
        assert d["device_key"] == "bound_key1"
        assert d["owner_email"] == "user1@test.local"
        assert d["online_seconds"] is None  # 测试环境无真实 WS 连接
        assert d["device_state"] in ("unknown", "idle", "llm", "tts", "asr")
        assert isinstance(d["enabled_plugins"], list)

    @pytest.mark.asyncio
    async def test_device_detail_not_found(self, client):
        tc, _factory = client
        res = tc.get("/api/v1/admin/devices/NO:EXIST/detail")
        assert res.status_code == 404


class TestAdminDeviceOta:
    @pytest.fixture
    def empty_meta(self, tmp_path, monkeypatch):
        """固件管理元数据置空（无启用固件，OTA 目标回退环境变量）"""
        from src.infrastructure import device_api
        monkeypatch.setattr(device_api, "FIRMWARE_META_FILE", tmp_path / "meta.json")

    @pytest.mark.asyncio
    async def test_ota_check_no_config(self, client, monkeypatch, empty_meta):
        """未配置固件地址时检测返回明确原因"""
        from src.infrastructure.config import get_settings
        tc, _factory = client
        settings = get_settings()
        saved = (settings.ota.bin_url, settings.ota.version)
        settings.ota.bin_url = ""
        settings.ota.version = ""
        try:
            res = tc.get("/api/v1/admin/devices/D8:3B:DA:6D:D9:3C/ota-check")
            assert res.status_code == 200
            data = res.json()["data"]
            assert data["has_update"] is False
            assert "未配置固件下载地址" in data["reason"]
        finally:
            settings.ota.bin_url, settings.ota.version = saved

    @pytest.mark.asyncio
    async def test_ota_check_version_compare(self, client, monkeypatch, empty_meta):
        """设备上报版本与目标版本不一致 → has_update"""
        from src.infrastructure.config import get_settings
        tc, _factory = client
        # 离线设备无 registry 条目 → current_version 未知，需走设备在线才能比版本；
        # 这里 stub 一个 registry 模拟在线设备已上报固件版本
        class _Ch: connected = True
        class _FakeRegistry:
            def resolve(self, device_id):
                if device_id == "D8:3B:DA:6D:D9:3C":
                    return {"channel": _Ch(), "session": None, "fsm": None,
                            "mac": device_id, "firmware_version": "1.0.0",
                            "register_time": 0.0, "ota_updating": False, "ota_progress": 0.0}
                return None
            def get_by_mac(self, mac):
                return self.resolve(mac)
        monkeypatch.setattr(admin_routes, "get_device_registry", lambda: _FakeRegistry())
        settings = get_settings()
        saved = (settings.ota.bin_url, settings.ota.version)
        settings.ota.bin_url = "http://x/firmware.bin"
        settings.ota.version = "1.1.0"
        try:
            res = tc.get("/api/v1/admin/devices/D8:3B:DA:6D:D9:3C/ota-check")
            data = res.json()["data"]
            assert data["has_update"] is True
            assert data["current_version"] == "1.0.0"
            assert data["target_version"] == "1.1.0"
        finally:
            settings.ota.bin_url, settings.ota.version = saved

    @pytest.mark.asyncio
    async def test_ota_force_offline_rejected(self, client, empty_meta):
        """设备离线时强制升级返回 400"""
        tc, _factory = client
        res = tc.post("/api/v1/admin/devices/D8:3B:DA:6D:D9:3C/ota-force")
        assert res.status_code == 400

    @pytest.mark.asyncio
    async def test_ota_force_placeholder_url_rejected(self, client, monkeypatch, empty_meta):
        """环境变量残留占位地址（your-server-ip）时强制升级明确拒绝"""
        from src.infrastructure.config import get_settings
        tc, _factory = client

        class _Ch: connected = True
        class _FakeRegistry:
            def resolve(self, device_id):
                return {"channel": _Ch(), "session": None, "fsm": None,
                        "mac": device_id, "firmware_version": "1.0.0", "bin_id": "b",
                        "register_time": 0.0, "ota_updating": False, "ota_progress": 0.0}
            def get_by_mac(self, mac):
                return self.resolve(mac)
        monkeypatch.setattr(admin_routes, "get_device_registry", lambda: _FakeRegistry())

        settings = get_settings()
        saved = (settings.ota.bin_url, settings.ota.version)
        settings.ota.bin_url = "http://your-server-ip:8088/firmware/1.0.bin"
        settings.ota.version = "1.0"
        try:
            res = tc.post("/api/v1/admin/devices/D8:3B:DA:6D:D9:3C/ota-force")
            assert res.status_code == 400
            assert "your-server-ip" in res.json()["detail"]
        finally:
            settings.ota.bin_url, settings.ota.version = saved


class TestAdminDeviceOtaBinId:
    """bin_id 优先级比对（与 /sdk/query_new_ota 同语义）"""

    @pytest.fixture(autouse=True)
    def _no_active_firmware(self, tmp_path, monkeypatch):
        # 隔离固件管理状态：本组测试验证目标解析与比对，不受已上传固件影响
        from src.infrastructure import device_api
        fw = tmp_path / "fw"; fw.mkdir()
        monkeypatch.setattr(device_api, "FIRMWARE_DIR", fw)
        monkeypatch.setattr(device_api, "FIRMWARE_META_FILE", tmp_path / "meta.json")

    def _stub_registry(self, monkeypatch, firmware_version, bin_id):
        class _Ch: connected = True
        class _FakeRegistry:
            def resolve(self, device_id):
                if device_id == "D8:3B:DA:6D:D9:3C":
                    return {"channel": _Ch(), "session": None, "fsm": None,
                            "mac": device_id, "firmware_version": firmware_version,
                            "bin_id": bin_id, "register_time": 0.0,
                            "ota_updating": False, "ota_progress": 0.0}
                return None
            def get_by_mac(self, mac):
                return self.resolve(mac)
        monkeypatch.setattr(admin_routes, "get_device_registry", lambda: _FakeRegistry())

    def _setup_ota(self, bin_id, version):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        saved = (settings.ota.bin_url, settings.ota.version, settings.ota.bin_id)
        settings.ota.bin_url = "http://x/firmware.bin"
        settings.ota.version = version
        settings.ota.bin_id = bin_id
        return saved

    def _restore_ota(self, saved):
        from src.infrastructure.config import get_settings
        settings = get_settings()
        settings.ota.bin_url, settings.ota.version, settings.ota.bin_id = saved

    @pytest.mark.asyncio
    async def test_bin_id_same_means_latest(self, client, monkeypatch):
        """bin_id 一致 → 最新，即使版本号不同（bin_id 优先级最高）"""
        from src.infrastructure.config import get_settings
        tc, _factory = client
        self._stub_registry(monkeypatch, "1.0.0", "bin-aaa")
        saved = self._setup_ota("bin-aaa", "9.9.9")
        try:
            res = tc.get("/api/v1/admin/devices/D8:3B:DA:6D:D9:3C/ota-check")
            data = res.json()["data"]
            assert data["has_update"] is False
            assert "bin_id 一致" in data["reason"]
        finally:
            self._restore_ota(saved)

    @pytest.mark.asyncio
    async def test_bin_id_diff_means_update(self, client, monkeypatch):
        """bin_id 不同 → 需要升级（即使版本号相同）"""
        from src.infrastructure.config import get_settings
        tc, _factory = client
        self._stub_registry(monkeypatch, "1.1.0", "bin-old")
        saved = self._setup_ota("bin-new", "1.1.0")
        try:
            res = tc.get("/api/v1/admin/devices/D8:3B:DA:6D:D9:3C/ota-check")
            data = res.json()["data"]
            assert data["has_update"] is True
            assert "bin_id 不同" in data["reason"]
        finally:
            self._restore_ota(saved)

    @pytest.mark.asyncio
    async def test_version_semantic_compare_fallback(self, client, monkeypatch):
        """无 bin_id 配置时回退版本号语义化比对（1.10 > 1.9）"""
        from src.infrastructure.config import get_settings
        tc, _factory = client
        self._stub_registry(monkeypatch, "1.9.0", "")
        saved = self._setup_ota("", "1.10.0")
        try:
            res = tc.get("/api/v1/admin/devices/D8:3B:DA:6D:D9:3C/ota-check")
            data = res.json()["data"]
            assert data["has_update"] is True
            assert "发现新版本 1.10.0" in data["reason"]
        finally:
            self._restore_ota(saved)


class TestAdminFirmwares:
    @pytest_asyncio.fixture
    async def fw_client(self, client, tmp_path, monkeypatch):
        """固件目录与元数据文件隔离到临时目录"""
        from src.infrastructure import device_api
        fw_dir = tmp_path / "firmware"
        fw_dir.mkdir()
        monkeypatch.setattr(device_api, "FIRMWARE_DIR", fw_dir)
        monkeypatch.setattr(device_api, "FIRMWARE_META_FILE", tmp_path / "firmware_meta.json")
        tc, _factory = client
        yield tc, fw_dir

    @pytest.mark.asyncio
    async def test_upload_list_set_active_delete(self, fw_client):
        from src.infrastructure import device_api
        tc, fw_dir = fw_client

        # 上传（bin_id_mode=custom 指定 bin_id/版本）→ 自动启用
        res = tc.post("/api/v1/admin/firmwares/upload",
                      files={"file": ("esp32s3-1.1.0.bin", b"FWDATA123", "application/octet-stream")},
                      data={"bin_id_mode": "custom", "bin_id": "bin-new", "version": "1.1.0"})
        assert res.status_code == 200
        assert res.json()["data"]["active"] is True
        assert (fw_dir / "esp32s3-1.1.0.bin").exists()

        # 列表：元数据齐全、启用中
        res = tc.get("/api/v1/admin/firmwares")
        items = res.json()["data"]["firmwares"]
        assert len(items) == 1
        assert items[0]["bin_id"] == "bin-new"
        assert items[0]["version"] == "1.1.0"
        assert items[0]["active"] is True

        # 元数据查询：get_active_firmware 返回启用固件
        active = device_api.get_active_firmware()
        assert active["bin_id"] == "bin-new"
        assert active["filename"] == "esp32s3-1.1.0.bin"

        # 上传第二个固件 → 旧的自动取消启用
        tc.post("/api/v1/admin/firmwares/upload",
                files={"file": ("esp32s3-1.2.0.bin", b"FWDATA456", "application/octet-stream")},
                data={"bin_id_mode": "custom", "bin_id": "bin-newer", "version": "1.2.0"})
        items = tc.get("/api/v1/admin/firmwares").json()["data"]["firmwares"]
        actives = [i for i in items if i["active"]]
        assert len(actives) == 1 and actives[0]["filename"] == "esp32s3-1.2.0.bin"
        assert device_api.get_active_firmware()["bin_id"] == "bin-newer"

        # 手动切回旧固件启用
        res = tc.post("/api/v1/admin/firmwares/esp32s3-1.1.0.bin/set-active")
        assert res.status_code == 200
        assert device_api.get_active_firmware()["bin_id"] == "bin-new"

        # 删除
        res = tc.delete("/api/v1/admin/firmwares/esp32s3-1.1.0.bin")
        assert res.status_code == 200
        assert not (fw_dir / "esp32s3-1.1.0.bin").exists()

    @pytest.mark.asyncio
    async def test_upload_rejects_bad_extension(self, fw_client):
        tc, _fw_dir = fw_client
        res = tc.post("/api/v1/admin/firmwares/upload",
                      files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
                      data={"bin_id": "x"})
        assert res.status_code == 400

    @pytest.mark.asyncio
    async def test_set_active_missing_file_404(self, fw_client):
        tc, _fw_dir = fw_client
        res = tc.post("/api/v1/admin/firmwares/no-such.bin/set-active")
        assert res.status_code == 404


    @pytest.mark.asyncio
    async def test_active_firmware_overrides_env(self, client, tmp_path, monkeypatch):
        """固件管理里有启用固件时，其 bin_id 优先于环境变量参与比对"""
        from src.infrastructure import device_api
        from src.infrastructure.config import get_settings
        tc, _factory = client

        # 启用中固件 bin_id=bin-fw（元数据指向临时固件文件）
        fw_dir = tmp_path / "firmware"; fw_dir.mkdir()
        (fw_dir / "fw-1.2.0.bin").write_bytes(b"FW")
        monkeypatch.setattr(device_api, "FIRMWARE_DIR", fw_dir)
        monkeypatch.setattr(device_api, "FIRMWARE_META_FILE", tmp_path / "meta.json")
        device_api.save_firmware_meta({
            "fw-1.2.0.bin": {"bin_id": "bin-fw", "version": "1.2.0",
                             "uploaded_by": "a@x", "uploaded_at": 0.0, "active": True}
        })

        # 环境变量故意配置不同的 bin_id —— 应被启用固件覆盖
        class _Ch: connected = True
        class _FakeRegistry:
            def resolve(self, device_id):
                return {"channel": _Ch(), "session": None, "fsm": None,
                        "mac": device_id, "firmware_version": "1.0.0",
                        "bin_id": "bin-device-old", "register_time": 0.0,
                        "ota_updating": False, "ota_progress": 0.0}
            def get_by_mac(self, mac):
                return self.resolve(mac)
        monkeypatch.setattr(admin_routes, "get_device_registry", lambda: _FakeRegistry())

        settings = get_settings()
        saved = (settings.ota.bin_url, settings.ota.version, settings.ota.bin_id)
        settings.ota.bin_url = "http://env/firmware.bin"
        settings.ota.version = "9.9.9"
        settings.ota.bin_id = "bin-env"
        try:
            res = tc.get("/api/v1/admin/devices/D8:3B:DA:6D:D9:3C/ota-check")
            data = res.json()["data"]
            # 启用固件优先：target 来自固件管理而非环境变量
            assert data["target_source"] == "固件管理（启用中固件）"
            assert data["target_bin_id" if False else "target_version"] == "1.2.0"
            assert data["has_update"] is True
            assert "bin_id 不同" in data["reason"]
        finally:
            settings.ota.bin_url, settings.ota.version, settings.ota.bin_id = saved
