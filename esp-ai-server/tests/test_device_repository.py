"""DeviceRepository 单元测试

覆盖：
- 基本 CRUD（upsert / get / get_all / partial update）
- find_by_key / find_by_mac
- add_skill / remove_skill
- toggle_skill
- MCP 配置 CRUD（get / set / delete）
- 同步加载（load_all_devices_sync）
- upsert 幂等性
- dict 结构与 users.json 兼容性

使用内存 SQLite（sqlite+aiosqlite:///:memory:），参考 tests/test_db_infra.py 的夹具模式。
"""
from __future__ import annotations

import copy
import time

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.infrastructure.db.base import Base
from src.infrastructure.db.models.device import DeviceModel
from src.infrastructure.db.repositories.device_repository import (
    DeviceRepository,
    _dict_to_model_fields,
)


# ============================================================
# 测试数据（与 users.json 中设备配置结构一致）
# ============================================================

SAMPLE_DEVICE_ID = "D8:3B:DA:6D:D9:3C"

SAMPLE_CONFIG: dict = {
    "name": "客厅的设备",
    "key": "test-key-123",
    "mac": "D8:3B:DA:6D:D9:3C",
    "asr_provider": "volcengine",
    "asr_config": {
        "volcengine": {
            "api_key": "a0cee1c3-ce76-4919-9e71-701191700839",
            "resource_id": "volc.bigasr.sauc.duration",
            "model": "bigmodel",
        }
    },
    "llm_type": "openai",
    "llm": {
        "api_key": "sk-test-key-1234567890",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
        "system_prompt": "你的名字叫小凡",
        "memory_enabled": True,
        "memory_max_messages": 20,
        "memory_long_term_enabled": True,
        "memory_long_term_auto_extract": True,
    },
    "tts_type": "volcengine",
    "tts_config": {
        "api_key": "a0cee1c3-ce76-4919-9e71-701191700839",
        "resource_id": "seed-tts-2.0",
        "voice_type": "zh_female_vv_uranus_bigtts",
    },
    "music": {
        "api_url": "http://192.168.31.176:2233",
        "lyrics_offset": 400,
    },
    "mcp_servers": {
        "amap-maps": {
            "type": "streamable_http",
            "url": "https://mcp.api-inference.modelscope.net/8eb6399371b74d/mcp",
        }
    },
    "rate_limit_rpm": 60,
    "disabled_tools": [],
    "wakeup": {
        "text": "我在，你在忙吗",
        "enabled": True,
        "cache_enabled": True,
        "play_enabled": True,
        "source": "tts",
    },
    "skills": ["guess_number", "gushi", "new"],
    "disabled_mcp_servers": [],
    "disabled_mcp_tools": {},
    "disabled_skills": ["guess_number"],
}


# ============================================================
# 异步夹具（:memory: + StaticPool，参考 test_db_infra.py）
# ============================================================

@pytest_asyncio.fixture
async def async_engine():
    """内存 SQLite 异步引擎（StaticPool 保证 :memory: 单连接复用）"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def repo(async_engine, monkeypatch):
    """DeviceRepository（异步，覆盖全局 async session factory）"""
    async_factory = async_sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    import src.infrastructure.db.engine as engine_mod
    monkeypatch.setattr(engine_mod, "_async_engine", async_engine)
    monkeypatch.setattr(engine_mod, "_async_session_factory", async_factory)
    yield DeviceRepository()


# ============================================================
# 同步夹具（独立 :memory: DB，自包含写入 + 读取）
# ============================================================

@pytest.fixture
def sync_repo(monkeypatch):
    """DeviceRepository（同步，覆盖全局 sync session factory）

    使用 :memory: + StaticPool，单连接复用保证写入与读取在同一内存 DB。
    """
    sync_engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        future=True,
        poolclass=StaticPool,
    )
    Base.metadata.create_all(sync_engine)
    sync_factory = sessionmaker(
        bind=sync_engine, class_=Session, expire_on_commit=False, autoflush=False,
    )
    import src.infrastructure.db.compat.sync_session as sync_mod
    monkeypatch.setattr(sync_mod, "_sync_engine", sync_engine)
    monkeypatch.setattr(sync_mod, "_sync_session_factory", sync_factory)
    yield DeviceRepository()
    sync_engine.dispose()


# ============================================================
# 测试：基本 CRUD
# ============================================================

class TestBasicCRUD:
    """基本 CRUD：upsert / get / get_all / partial update"""

    @pytest.mark.asyncio
    async def test_upsert_and_get(self, repo):
        """upsert 新设备后能读取到"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)
        assert cfg is not None
        assert cfg["name"] == "客厅的设备"
        assert cfg["key"] == "test-key-123"
        assert cfg["asr_provider"] == "volcengine"
        assert cfg["llm"]["model"] == "deepseek-v4-flash"
        assert cfg["tts_config"]["voice_type"] == "zh_female_vv_uranus_bigtts"
        assert cfg["music"]["api_url"] == "http://192.168.31.176:2233"
        assert "amap-maps" in cfg["mcp_servers"]
        assert cfg["skills"] == ["guess_number", "gushi", "new"]
        assert cfg["disabled_skills"] == ["guess_number"]

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, repo):
        """查询不存在的设备返回 None"""
        assert await repo.get_device_config("nonexistent") is None

    @pytest.mark.asyncio
    async def test_get_by_device_key(self, repo):
        """通过 device_key 查找设备"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        cfg = await repo.get_device_config("test-key-123")
        assert cfg is not None
        assert cfg["name"] == "客厅的设备"

    @pytest.mark.asyncio
    async def test_get_by_mac(self, repo):
        """通过 mac_address 查找设备"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        cfg = await repo.get_device_config("D8:3B:DA:6D:D9:3C")
        assert cfg is not None
        assert cfg["name"] == "客厅的设备"

    @pytest.mark.asyncio
    async def test_get_all_devices(self, repo):
        """get_all_devices 返回所有设备"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        await repo.upsert_device("AA:BB:CC:DD:EE:FF", {
            "name": "卧室的设备",
            "key": "another-key",
        })
        all_devices = await repo.get_all_devices()
        assert len(all_devices) == 2
        assert SAMPLE_DEVICE_ID in all_devices
        assert "AA:BB:CC:DD:EE:FF" in all_devices
        assert all_devices[SAMPLE_DEVICE_ID]["name"] == "客厅的设备"
        assert all_devices["AA:BB:CC:DD:EE:FF"]["name"] == "卧室的设备"

    @pytest.mark.asyncio
    async def test_get_all_devices_empty(self, repo):
        """空数据库返回空 dict"""
        assert await repo.get_all_devices() == {}

    @pytest.mark.asyncio
    async def test_update_device_partial_scalar(self, repo):
        """部分更新标量字段"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        updated = await repo.update_device_partial(SAMPLE_DEVICE_ID, {
            "name": "新的名字",
            "rate_limit_rpm": 100,
        })
        assert updated is not None
        assert updated["name"] == "新的名字"
        assert updated["rate_limit_rpm"] == 100
        # 未更新的字段保持不变
        assert updated["key"] == "test-key-123"
        assert updated["llm"]["model"] == "deepseek-v4-flash"

    @pytest.mark.asyncio
    async def test_update_device_partial_nested(self, repo):
        """部分更新嵌套 dict（深度合并）"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        updated = await repo.update_device_partial(SAMPLE_DEVICE_ID, {
            "llm": {"model": "gpt-4"},
        })
        assert updated is not None
        # llm.model 被更新
        assert updated["llm"]["model"] == "gpt-4"
        # llm 其他字段保留
        assert updated["llm"]["api_key"] == "sk-test-key-1234567890"
        assert updated["llm"]["system_prompt"] == "你的名字叫小凡"

    @pytest.mark.asyncio
    async def test_update_device_partial_list_replace(self, repo):
        """部分更新 list 字段（直接替换，不合并）"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        updated = await repo.update_device_partial(SAMPLE_DEVICE_ID, {
            "skills": ["new_skill"],
        })
        assert updated is not None
        assert updated["skills"] == ["new_skill"]

    @pytest.mark.asyncio
    async def test_update_device_partial_mcp_merge(self, repo):
        """部分更新 mcp_servers（深度合并，保留原有服务器）"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        updated = await repo.update_device_partial(SAMPLE_DEVICE_ID, {
            "mcp_servers": {
                "weather": {"url": "https://weather.example.com"},
            },
        })
        assert updated is not None
        assert "amap-maps" in updated["mcp_servers"]
        assert "weather" in updated["mcp_servers"]

    @pytest.mark.asyncio
    async def test_update_nonexistent_returns_none(self, repo):
        """更新不存在的设备返回 None"""
        assert await repo.update_device_partial("nonexistent", {"name": "x"}) is None


# ============================================================
# 测试：find_by_key / find_by_mac
# ============================================================

class TestFindByKeyAndMac:
    """find_by_key / find_by_mac 查找"""

    @pytest.mark.asyncio
    async def test_find_by_key(self, repo):
        """按 device_key（API key）查找"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        result = await repo.find_by_key("test-key-123")
        assert result is not None
        device_id, cfg = result
        assert device_id == SAMPLE_DEVICE_ID
        assert cfg["name"] == "客厅的设备"

    @pytest.mark.asyncio
    async def test_find_by_key_not_found(self, repo):
        """device_key 不存在返回 None"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        assert await repo.find_by_key("nonexistent-key") is None

    @pytest.mark.asyncio
    async def test_find_by_key_empty(self, repo):
        """空 key 返回 None"""
        assert await repo.find_by_key("") is None

    @pytest.mark.asyncio
    async def test_find_by_mac_via_mac_address_column(self, repo):
        """按 mac_address 列查找"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        # SAMPLE_CONFIG["mac"] = "D8:3B:DA:6D:D9:3C"
        result = await repo.find_by_mac("D8:3B:DA:6D:D9:3C")
        assert result is not None
        device_id, cfg = result
        assert device_id == SAMPLE_DEVICE_ID
        assert cfg["name"] == "客厅的设备"

    @pytest.mark.asyncio
    async def test_find_by_mac_via_device_id_fallback(self, repo):
        """mac_address 列未命中时，回退匹配 device_id（dict key 为 MAC）"""
        # 不提供 mac 字段，mac_address 会默认为 device_id
        await repo.upsert_device("AA:BB:CC:DD:EE:FF", {
            "name": "测试设备",
            "key": "key-ff",
        })
        result = await repo.find_by_mac("AA:BB:CC:DD:EE:FF")
        assert result is not None
        device_id, cfg = result
        assert device_id == "AA:BB:CC:DD:EE:FF"

    @pytest.mark.asyncio
    async def test_find_by_mac_not_found(self, repo):
        """MAC 不存在返回 None"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        assert await repo.find_by_mac("00:00:00:00:00:00") is None

    @pytest.mark.asyncio
    async def test_find_by_mac_empty(self, repo):
        """空 MAC 返回 None"""
        assert await repo.find_by_mac("") is None


# ============================================================
# 测试：技能管理
# ============================================================

class TestSkills:
    """add_skill_to_device / remove_skill_from_all_devices"""

    @pytest.mark.asyncio
    async def test_add_skill_to_device(self, repo):
        """向设备添加新技能"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        ok = await repo.add_skill_to_device(SAMPLE_DEVICE_ID, "new_skill")
        assert ok is True
        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)
        assert "new_skill" in cfg["skills"]
        assert "guess_number" in cfg["skills"]  # 原有技能保留

    @pytest.mark.asyncio
    async def test_add_skill_already_exists(self, repo):
        """添加已存在的技能（幂等）"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        ok = await repo.add_skill_to_device(SAMPLE_DEVICE_ID, "guess_number")
        assert ok is True
        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)
        assert cfg["skills"].count("guess_number") == 1  # 不重复

    @pytest.mark.asyncio
    async def test_add_skill_nonexistent_device(self, repo):
        """向不存在的设备添加技能返回 False"""
        ok = await repo.add_skill_to_device("nonexistent", "skill")
        assert ok is False

    @pytest.mark.asyncio
    async def test_add_skill_by_device_key(self, repo):
        """通过 device_key 添加技能"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        ok = await repo.add_skill_to_device("test-key-123", "new_skill")
        assert ok is True
        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)
        assert "new_skill" in cfg["skills"]

    @pytest.mark.asyncio
    async def test_remove_skill_from_all_devices(self, repo):
        """从所有设备移除技能"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        await repo.upsert_device("dev2", {
            "name": "device2",
            "key": "key2",
            "skills": ["guess_number", "another_skill"],
        })
        count = await repo.remove_skill_from_all_devices("guess_number")
        assert count == 2  # 两个设备都包含该技能
        cfg1 = await repo.get_device_config(SAMPLE_DEVICE_ID)
        cfg2 = await repo.get_device_config("dev2")
        assert "guess_number" not in cfg1["skills"]
        assert "guess_number" not in cfg2["skills"]
        assert "another_skill" in cfg2["skills"]  # 其他技能保留

    @pytest.mark.asyncio
    async def test_remove_skill_not_present(self, repo):
        """移除不存在的技能返回 0"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        count = await repo.remove_skill_from_all_devices("nonexistent_skill")
        assert count == 0

    @pytest.mark.asyncio
    async def test_remove_skill_empty_name(self, repo):
        """空技能名返回 0"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        count = await repo.remove_skill_from_all_devices("")
        assert count == 0


# ============================================================
# 测试：技能启停
# ============================================================

class TestToggleSkill:
    """toggle_skill 操作 disabled_skills 列表"""

    @pytest.mark.asyncio
    async def test_disable_skill(self, repo):
        """禁用技能：加入 disabled_skills"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        # 初始 disabled_skills = ["guess_number"]
        await repo.toggle_skill(SAMPLE_DEVICE_ID, "gushi", disabled=True)
        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)
        assert "gushi" in cfg["disabled_skills"]
        assert "guess_number" in cfg["disabled_skills"]  # 原有的保留

    @pytest.mark.asyncio
    async def test_enable_skill(self, repo):
        """启用技能：从 disabled_skills 移除"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        # 初始 disabled_skills = ["guess_number"]
        await repo.toggle_skill(SAMPLE_DEVICE_ID, "guess_number", disabled=False)
        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)
        assert "guess_number" not in cfg["disabled_skills"]
        assert cfg["disabled_skills"] == []

    @pytest.mark.asyncio
    async def test_toggle_skill_idempotent(self, repo):
        """重复禁用不会重复添加"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        await repo.toggle_skill(SAMPLE_DEVICE_ID, "gushi", disabled=True)
        await repo.toggle_skill(SAMPLE_DEVICE_ID, "gushi", disabled=True)
        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)
        assert cfg["disabled_skills"].count("gushi") == 1

    @pytest.mark.asyncio
    async def test_enable_non_disabled_skill(self, repo):
        """启用未禁用的技能（无操作）"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        # guess_number 已禁用，gushi 未禁用
        await repo.toggle_skill(SAMPLE_DEVICE_ID, "gushi", disabled=False)
        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)
        assert "gushi" not in cfg["disabled_skills"]

    @pytest.mark.asyncio
    async def test_toggle_skill_by_device_key(self, repo):
        """通过 device_key 启停技能"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        await repo.toggle_skill("test-key-123", "gushi", disabled=True)
        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)
        assert "gushi" in cfg["disabled_skills"]

    @pytest.mark.asyncio
    async def test_toggle_skill_nonexistent_device(self, repo):
        """对不存在的设备启停技能（无操作，不报错）"""
        # 不应抛出异常
        await repo.toggle_skill("nonexistent", "gushi", disabled=True)


# ============================================================
# 测试：MCP 配置 CRUD
# ============================================================

class TestMCP:
    """MCP 服务器配置的增删改查"""

    @pytest.mark.asyncio
    async def test_get_mcp_servers(self, repo):
        """获取设备的 MCP 服务器配置"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        servers = await repo.get_mcp_servers(SAMPLE_DEVICE_ID)
        assert "amap-maps" in servers
        assert servers["amap-maps"]["url"].startswith("https://")

    @pytest.mark.asyncio
    async def test_get_mcp_servers_nonexistent_device(self, repo):
        """获取不存在设备的 MCP 配置返回空 dict"""
        assert await repo.get_mcp_servers("nonexistent") == {}

    @pytest.mark.asyncio
    async def test_set_mcp_server(self, repo):
        """添加新的 MCP 服务器"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        await repo.set_mcp_server(SAMPLE_DEVICE_ID, "weather-server", {
            "type": "streamable_http",
            "url": "https://example.com/mcp",
        })
        servers = await repo.get_mcp_servers(SAMPLE_DEVICE_ID)
        assert "weather-server" in servers
        assert servers["weather-server"]["url"] == "https://example.com/mcp"
        # 原有的保留
        assert "amap-maps" in servers

    @pytest.mark.asyncio
    async def test_update_mcp_server(self, repo):
        """更新已有 MCP 服务器配置"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        await repo.set_mcp_server(SAMPLE_DEVICE_ID, "amap-maps", {
            "type": "streamable_http",
            "url": "https://new-url.com/mcp",
        })
        servers = await repo.get_mcp_servers(SAMPLE_DEVICE_ID)
        assert servers["amap-maps"]["url"] == "https://new-url.com/mcp"

    @pytest.mark.asyncio
    async def test_delete_mcp_server(self, repo):
        """删除 MCP 服务器"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        await repo.delete_mcp_server(SAMPLE_DEVICE_ID, "amap-maps")
        servers = await repo.get_mcp_servers(SAMPLE_DEVICE_ID)
        assert "amap-maps" not in servers

    @pytest.mark.asyncio
    async def test_delete_nonexistent_mcp_server(self, repo):
        """删除不存在的 MCP 服务器（无操作，不报错）"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        await repo.delete_mcp_server(SAMPLE_DEVICE_ID, "nonexistent")
        servers = await repo.get_mcp_servers(SAMPLE_DEVICE_ID)
        assert "amap-maps" in servers  # 原有的保留

    @pytest.mark.asyncio
    async def test_mcp_by_device_key(self, repo):
        """通过 device_key 操作 MCP"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        await repo.set_mcp_server("test-key-123", "new-server", {
            "url": "https://example.com",
        })
        servers = await repo.get_mcp_servers("test-key-123")
        assert "new-server" in servers

    @pytest.mark.asyncio
    async def test_mcp_nonexistent_device(self, repo):
        """对不存在的设备操作 MCP（无操作，不报错）"""
        # 不应抛出异常
        await repo.set_mcp_server("nonexistent", "server", {"url": "x"})
        await repo.delete_mcp_server("nonexistent", "server")
        assert await repo.get_mcp_servers("nonexistent") == {}


# ============================================================
# 测试：同步加载
# ============================================================

class TestSyncLoad:
    """load_all_devices_sync 同步加载"""

    def test_load_all_devices_sync(self, sync_repo):
        """同步加载设备配置（自包含：直接写入 + 同步读取）"""
        from src.infrastructure.db.compat.sync_session import get_sync_session_factory
        factory = get_sync_session_factory()
        with factory() as session:
            fields = _dict_to_model_fields(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
            session.add(DeviceModel(**fields))
            session.commit()

        result = sync_repo.load_all_devices_sync()
        assert SAMPLE_DEVICE_ID in result
        cfg = result[SAMPLE_DEVICE_ID]
        # 验证 dict 结构与 users.json 一致
        assert cfg["name"] == "客厅的设备"
        assert cfg["key"] == "test-key-123"
        assert cfg["asr_provider"] == "volcengine"
        assert cfg["llm"]["model"] == "deepseek-v4-flash"
        assert cfg["tts_config"]["voice_type"] == "zh_female_vv_uranus_bigtts"
        assert cfg["music"]["api_url"] == "http://192.168.31.176:2233"
        assert "amap-maps" in cfg["mcp_servers"]
        assert cfg["wakeup"]["text"] == "我在，你在忙吗"
        assert cfg["skills"] == ["guess_number", "gushi", "new"]
        assert cfg["disabled_skills"] == ["guess_number"]
        assert cfg["ota"]["enabled"] is True

    def test_load_all_devices_sync_empty(self, sync_repo):
        """空数据库同步加载返回空 dict"""
        result = sync_repo.load_all_devices_sync()
        assert result == {}

    def test_load_all_devices_sync_multiple(self, sync_repo):
        """同步加载多个设备"""
        from src.infrastructure.db.compat.sync_session import get_sync_session_factory
        factory = get_sync_session_factory()
        with factory() as session:
            session.add(DeviceModel(
                device_id="dev1", name="设备1", device_key="key1",
            ))
            session.add(DeviceModel(
                device_id="dev2", name="设备2", device_key="key2",
            ))
            session.commit()

        result = sync_repo.load_all_devices_sync()
        assert len(result) == 2
        assert result["dev1"]["name"] == "设备1"
        assert result["dev2"]["name"] == "设备2"


# ============================================================
# 测试：upsert 幂等性
# ============================================================

class TestUpsertIdempotent:
    """upsert 幂等性：多次 upsert 同一设备不产生重复行"""

    @pytest.mark.asyncio
    async def test_upsert_idempotent(self, repo):
        """多次 upsert 同一设备不产生重复"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)

        all_devices = await repo.get_all_devices()
        assert len(all_devices) == 1
        assert SAMPLE_DEVICE_ID in all_devices

    @pytest.mark.asyncio
    async def test_upsert_updates_existing(self, repo):
        """upsert 更新已存在设备（覆盖字段）"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        new_config = copy.deepcopy(SAMPLE_CONFIG)
        new_config["name"] = "新名字"
        new_config["llm"]["model"] = "gpt-4"
        await repo.upsert_device(SAMPLE_DEVICE_ID, new_config)

        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)
        assert cfg["name"] == "新名字"
        assert cfg["llm"]["model"] == "gpt-4"
        # 其他字段保留
        assert cfg["key"] == "test-key-123"

    @pytest.mark.asyncio
    async def test_upsert_preserves_created_at(self, repo):
        """upsert 更新时 created_at 不变，updated_at 刷新"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        # 读取初始时间戳
        from src.infrastructure.db.session import get_session_ctx
        async with get_session_ctx() as session:
            model = (await session.execute(
                select(DeviceModel).where(DeviceModel.device_id == SAMPLE_DEVICE_ID)
            )).scalar_one()
            created_before = model.created_at
            updated_before = model.updated_at

        time.sleep(0.02)  # 确保 updated_at 有变化
        await repo.upsert_device(SAMPLE_DEVICE_ID, {"name": "新名字"})

        async with get_session_ctx() as session:
            model = (await session.execute(
                select(DeviceModel).where(DeviceModel.device_id == SAMPLE_DEVICE_ID)
            )).scalar_one()
            assert model.created_at == created_before  # 创建时间不变
            assert model.updated_at > updated_before  # 更新时间刷新

    @pytest.mark.asyncio
    async def test_upsert_multiple_devices(self, repo):
        """upsert 多个不同设备"""
        await repo.upsert_device("dev1", {"name": "d1", "key": "k1"})
        await repo.upsert_device("dev2", {"name": "d2", "key": "k2"})
        await repo.upsert_device("dev3", {"name": "d3", "key": "k3"})
        all_devices = await repo.get_all_devices()
        assert len(all_devices) == 3

    @pytest.mark.asyncio
    async def test_upsert_empty_device_id(self, repo):
        """空 device_id 不执行操作"""
        await repo.upsert_device("", {"name": "x"})
        assert await repo.get_all_devices() == {}


# ============================================================
# 测试：dict 结构兼容性
# ============================================================

class TestDictCompat:
    """返回的 dict 结构与 users.json 完全一致"""

    @pytest.mark.asyncio
    async def test_dict_structure_matches_users_json(self, repo):
        """upsert + get 返回的 dict 结构与 users.json 一致"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)

        # 验证与 users.json 中已有的顶层字段
        expected_keys = {
            "name", "key", "asr_provider", "asr_config",
            "llm_type", "llm",
            "tts_type", "tts_config",
            "music", "mcp_servers", "wakeup",
            "rate_limit_rpm",
            "ota",
            "disabled_tools", "disabled_mcp_servers", "disabled_mcp_tools",
            "disabled_skills", "skills",
            # 仓库层新增的顶层字段
            "management_api_key", "enabled_plugins", "plugin_configs",
            "has_display", "robot_mode",
            "screensaver_enabled", "screensaver_timeout",
        }
        assert set(cfg.keys()) == expected_keys, (
            f"字段不一致: 多出 {set(cfg.keys()) - expected_keys}, "
            f"缺失 {expected_keys - set(cfg.keys())}"
        )

        # 验证嵌套字段
        assert set(cfg["llm"].keys()) == {
            "api_key", "base_url", "model", "system_prompt",
            "memory_enabled", "memory_max_messages",
            "memory_long_term_enabled", "memory_long_term_auto_extract",
        }
        assert set(cfg["ota"].keys()) == {
            "enabled", "bin_url", "version", "bin_id", "is_official",
        }

    @pytest.mark.asyncio
    async def test_load_devices_compat(self, repo):
        """返回的 dict 能被 load_devices() 正确解析为 DeviceConfig"""
        from src.use_cases.device_config import DeviceConfig
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)

        # 模拟 load_devices() 的解析逻辑
        raw = cfg
        llm = raw.get("llm") or {}
        ota = raw.get("ota", {})

        dc = DeviceConfig(
            device_id=SAMPLE_DEVICE_ID,
            name=raw.get("name", ""),
            key=raw.get("key", raw.get("api_key", "")),
            asr_provider=raw.get("asr_provider"),
            llm_type=raw.get("llm_type"),
            tts_type=raw.get("tts_type"),
            asr_config=raw.get("asr_config"),
            tts_config=raw.get("tts_config"),
            music_config=raw.get("music_config") or raw.get("music"),
            llm_api_key=llm.get("api_key"),
            llm_base_url=llm.get("base_url"),
            llm_model=llm.get("model"),
            llm_system_prompt=llm.get("system_prompt"),
            mcp_servers=raw.get("mcp_servers"),
            rate_limit_rpm=raw.get("rate_limit_rpm"),
            llm_memory_enabled=llm.get("memory_enabled"),
            llm_memory_max_messages=llm.get("memory_max_messages"),
            llm_memory_long_term_enabled=llm.get("memory_long_term_enabled"),
            llm_memory_long_term_auto_extract=llm.get("memory_long_term_auto_extract"),
            ota_enabled=ota.get("enabled", True),
            ota_bin_url=ota.get("bin_url", ""),
            ota_version=ota.get("version", ""),
            ota_bin_id=ota.get("bin_id", ""),
            ota_is_official=ota.get("is_official", "0"),
            disabled_tools=raw.get("disabled_tools", []),
            disabled_mcp_servers=raw.get("disabled_mcp_servers", []),
            disabled_mcp_tools=raw.get("disabled_mcp_tools", {}),
            disabled_skills=raw.get("disabled_skills", []),
            skills=raw.get("skills", []),
            wakeup_config=raw.get("wakeup") or raw.get("wakeup_config"),
        )

        # 验证字段正确解析
        assert dc.device_id == SAMPLE_DEVICE_ID
        assert dc.name == "客厅的设备"
        assert dc.key == "test-key-123"
        assert dc.asr_provider == "volcengine"
        assert dc.llm_type == "openai"
        assert dc.tts_type == "volcengine"
        assert dc.llm_api_key == "sk-test-key-1234567890"
        assert dc.llm_model == "deepseek-v4-flash"
        assert dc.llm_system_prompt == "你的名字叫小凡"
        assert dc.llm_memory_enabled is True
        assert dc.llm_memory_max_messages == 20
        assert dc.rate_limit_rpm == 60
        assert dc.ota_enabled is True
        assert dc.ota_is_official == "0"
        assert dc.skills == ["guess_number", "gushi", "new"]
        assert dc.disabled_skills == ["guess_number"]
        assert dc.disabled_tools == []
        assert dc.wakeup_config["text"] == "我在，你在忙吗"
        assert "amap-maps" in (dc.mcp_servers or {})

    @pytest.mark.asyncio
    async def test_roundtrip_preserves_data(self, repo):
        """upsert -> get 往返保持数据一致"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)
        # 再次 upsert 读取的 dict（模拟从 DB 读出后写回）
        await repo.upsert_device(SAMPLE_DEVICE_ID, cfg)
        cfg2 = await repo.get_device_config(SAMPLE_DEVICE_ID)
        # 数据应保持一致
        assert cfg2 == cfg

    @pytest.mark.asyncio
    async def test_get_all_devices_returns_users_json_structure(self, repo):
        """get_all_devices 返回的 dict 结构与 users.json 的 devices 字段一致"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        all_devices = await repo.get_all_devices()
        # 模拟 users.json 的完整结构
        users_json_like = {"devices": all_devices}
        assert "devices" in users_json_like
        assert SAMPLE_DEVICE_ID in users_json_like["devices"]
        cfg = users_json_like["devices"][SAMPLE_DEVICE_ID]
        assert cfg["name"] == "客厅的设备"
        assert cfg["llm"]["model"] == "deepseek-v4-flash"

    @pytest.mark.asyncio
    async def test_defaults_for_minimal_config(self, repo):
        """最小配置也能正常往返（使用默认值）"""
        await repo.upsert_device("minimal-dev", {
            "name": "小明的设备",
            "key": "min-key",
        })
        cfg = await repo.get_device_config("minimal-dev")
        assert cfg is not None
        # 默认值
        assert cfg["name"] == "小明的设备"
        assert cfg["key"] == "min-key"
        assert cfg["asr_provider"] == ""
        assert cfg["asr_config"] == {}
        assert cfg["llm"] == {
            "api_key": "", "base_url": "", "model": "", "system_prompt": "",
            "memory_enabled": True, "memory_max_messages": 20,
            "memory_long_term_enabled": True, "memory_long_term_auto_extract": True,
        }
        assert cfg["tts_config"] == {}
        assert cfg["music"] == {}
        assert cfg["mcp_servers"] == {}
        assert cfg["wakeup"] == {}
        assert cfg["rate_limit_rpm"] == 0
        assert cfg["ota"] == {
            "enabled": True, "bin_url": "", "version": "", "bin_id": "", "is_official": "0",
        }
        assert cfg["disabled_tools"] == []
        assert cfg["disabled_mcp_servers"] == []
        assert cfg["disabled_mcp_tools"] == {}
        assert cfg["disabled_skills"] == []
        assert cfg["skills"] == []
