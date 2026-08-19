"""DeviceRepository 鍗曞厓娴嬭瘯

瑕嗙洊锛?
- 鍩烘湰 CRUD锛坲psert / get / get_all / partial update锛?
- find_by_key / find_by_mac
- add_skill / remove_skill
- toggle_skill
- MCP 閰嶇疆 CRUD锛坓et / set / delete锛?
- 鍚屾鍔犺浇锛坙oad_all_devices_sync锛?
- upsert 骞傜瓑鎬?
- dict 缁撴瀯涓?users.json 鍏煎鎬?

浣跨敤鍐呭瓨 SQLite锛坰qlite+aiosqlite:///:memory:锛夛紝鍙傝€?tests/test_db_infra.py 鐨勫す鍏锋ā寮忋€?
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
# 娴嬭瘯鏁版嵁锛堜笌 users.json 涓殑璁惧閰嶇疆缁撴瀯涓€鑷达級
# ============================================================

SAMPLE_DEVICE_ID = "D8:3B:DA:6D:D9:3C"

SAMPLE_CONFIG: dict = {
    "name": "瀹㈠巺鐨勮澶?,
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
        "system_prompt": "浣犵殑鍚嶅瓧鍙嚒鍑?,
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
        "text": "鎴戝湪锛屼綘璇?,
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
# 寮傛澶瑰叿锛?memory: + StaticPool锛屽弬鑰?test_db_infra.py锛?
# ============================================================

@pytest_asyncio.fixture
async def async_engine():
    """鍐呭瓨 SQLite 寮傛寮曟搸锛圫taticPool 纭繚 :memory: 鍗曡繛鎺ュ鐢級"""
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
    """DeviceRepository锛堝紓姝ワ紝瑕嗙洊鍏ㄥ眬 async session factory锛?""
    async_factory = async_sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    import src.infrastructure.db.engine as engine_mod
    monkeypatch.setattr(engine_mod, "_async_engine", async_engine)
    monkeypatch.setattr(engine_mod, "_async_session_factory", async_factory)
    yield DeviceRepository()


# ============================================================
# 鍚屾澶瑰叿锛堢嫭绔?:memory: DB锛岃嚜鍖呭惈鍐欏叆 + 璇诲彇锛?
# ============================================================

@pytest.fixture
def sync_repo(monkeypatch):
    """DeviceRepository锛堝悓姝ワ紝瑕嗙洊鍏ㄥ眬 sync session factory锛?

    浣跨敤 :memory: + StaticPool锛屽崟杩炴帴澶嶇敤淇濊瘉鍐欏叆涓庤鍙栧湪鍚屼竴鍐呭瓨 DB銆?
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
# 娴嬭瘯锛氬熀鏈?CRUD
# ============================================================

class TestBasicCRUD:
    """鍩烘湰 CRUD锛歶psert / get / get_all / partial update"""

    @pytest.mark.asyncio
    async def test_upsert_and_get(self, repo):
        """upsert 鏂拌澶囧悗鑳借鍙栧埌"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)
        assert cfg is not None
        assert cfg["name"] == "瀹㈠巺鐨勮澶?
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
        """鏌ヨ涓嶅瓨鍦ㄧ殑璁惧杩斿洖 None"""
        assert await repo.get_device_config("nonexistent") is None

    @pytest.mark.asyncio
    async def test_get_by_device_key(self, repo):
        """閫氳繃 device_key 鏌ヨ璁惧"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        cfg = await repo.get_device_config("test-key-123")
        assert cfg is not None
        assert cfg["name"] == "瀹㈠巺鐨勮澶?

    @pytest.mark.asyncio
    async def test_get_by_mac(self, repo):
        """閫氳繃 mac_address 鏌ヨ璁惧"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        cfg = await repo.get_device_config("D8:3B:DA:6D:D9:3C")
        assert cfg is not None
        assert cfg["name"] == "瀹㈠巺鐨勮澶?

    @pytest.mark.asyncio
    async def test_get_all_devices(self, repo):
        """get_all_devices 杩斿洖鎵€鏈夎澶?""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        await repo.upsert_device("AA:BB:CC:DD:EE:FF", {
            "name": "鍗у鐨勮澶?,
            "key": "another-key",
        })
        all_devices = await repo.get_all_devices()
        assert len(all_devices) == 2
        assert SAMPLE_DEVICE_ID in all_devices
        assert "AA:BB:CC:DD:EE:FF" in all_devices
        assert all_devices[SAMPLE_DEVICE_ID]["name"] == "瀹㈠巺鐨勮澶?
        assert all_devices["AA:BB:CC:DD:EE:FF"]["name"] == "鍗у鐨勮澶?

    @pytest.mark.asyncio
    async def test_get_all_devices_empty(self, repo):
        """绌烘暟鎹簱杩斿洖绌?dict"""
        assert await repo.get_all_devices() == {}

    @pytest.mark.asyncio
    async def test_update_device_partial_scalar(self, repo):
        """閮ㄥ垎鏇存柊鏍囬噺瀛楁"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        updated = await repo.update_device_partial(SAMPLE_DEVICE_ID, {
            "name": "鏂扮殑鍚嶅瓧",
            "rate_limit_rpm": 100,
        })
        assert updated is not None
        assert updated["name"] == "鏂扮殑鍚嶅瓧"
        assert updated["rate_limit_rpm"] == 100
        # 鏈洿鏂扮殑瀛楁淇濇寔涓嶅彉
        assert updated["key"] == "test-key-123"
        assert updated["llm"]["model"] == "deepseek-v4-flash"

    @pytest.mark.asyncio
    async def test_update_device_partial_nested(self, repo):
        """閮ㄥ垎鏇存柊宓屽 dict锛堟繁搴﹀悎骞讹級"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        updated = await repo.update_device_partial(SAMPLE_DEVICE_ID, {
            "llm": {"model": "gpt-4"},
        })
        assert updated is not None
        # llm.model 琚洿鏂?
        assert updated["llm"]["model"] == "gpt-4"
        # llm 鍏朵粬瀛楁淇濈暀
        assert updated["llm"]["api_key"] == "sk-test-key-1234567890"
        assert updated["llm"]["system_prompt"] == "浣犵殑鍚嶅瓧鍙嚒鍑?

    @pytest.mark.asyncio
    async def test_update_device_partial_list_replace(self, repo):
        """閮ㄥ垎鏇存柊 list 瀛楁锛堢洿鎺ユ浛鎹紝涓嶅悎骞讹級"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        updated = await repo.update_device_partial(SAMPLE_DEVICE_ID, {
            "skills": ["new_skill"],
        })
        assert updated is not None
        assert updated["skills"] == ["new_skill"]

    @pytest.mark.asyncio
    async def test_update_device_partial_mcp_merge(self, repo):
        """閮ㄥ垎鏇存柊 mcp_servers锛堟繁搴﹀悎骞讹紝淇濈暀鍘熸湁鏈嶅姟鍣級"""
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
        """鏇存柊涓嶅瓨鍦ㄧ殑璁惧杩斿洖 None"""
        assert await repo.update_device_partial("nonexistent", {"name": "x"}) is None


# ============================================================
# 娴嬭瘯锛歠ind_by_key / find_by_mac
# ============================================================

class TestFindByKeyAndMac:
    """find_by_key / find_by_mac 鏌ユ壘"""

    @pytest.mark.asyncio
    async def test_find_by_key(self, repo):
        """鎸?device_key锛圓PI key锛夋煡鎵?""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        result = await repo.find_by_key("test-key-123")
        assert result is not None
        device_id, cfg = result
        assert device_id == SAMPLE_DEVICE_ID
        assert cfg["name"] == "瀹㈠巺鐨勮澶?

    @pytest.mark.asyncio
    async def test_find_by_key_not_found(self, repo):
        """device_key 涓嶅瓨鍦ㄨ繑鍥?None"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        assert await repo.find_by_key("nonexistent-key") is None

    @pytest.mark.asyncio
    async def test_find_by_key_empty(self, repo):
        """绌?key 杩斿洖 None"""
        assert await repo.find_by_key("") is None

    @pytest.mark.asyncio
    async def test_find_by_mac_via_mac_address_column(self, repo):
        """鎸?mac_address 鍒楁煡鎵?""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        # SAMPLE_CONFIG["mac"] = "D8:3B:DA:6D:D9:3C"
        result = await repo.find_by_mac("D8:3B:DA:6D:D9:3C")
        assert result is not None
        device_id, cfg = result
        assert device_id == SAMPLE_DEVICE_ID
        assert cfg["name"] == "瀹㈠巺鐨勮澶?

    @pytest.mark.asyncio
    async def test_find_by_mac_via_device_id_fallback(self, repo):
        """mac_address 鍒楁湭鍛戒腑鏃讹紝鍥為€€鍖归厤 device_id锛坉ict key 鍗?MAC锛?""
        # 涓嶆彁渚?mac 瀛楁锛宮ac_address 浼氶粯璁や负 device_id
        await repo.upsert_device("AA:BB:CC:DD:EE:FF", {
            "name": "娴嬭瘯璁惧",
            "key": "key-ff",
        })
        result = await repo.find_by_mac("AA:BB:CC:DD:EE:FF")
        assert result is not None
        device_id, cfg = result
        assert device_id == "AA:BB:CC:DD:EE:FF"

    @pytest.mark.asyncio
    async def test_find_by_mac_not_found(self, repo):
        """MAC 涓嶅瓨鍦ㄨ繑鍥?None"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        assert await repo.find_by_mac("00:00:00:00:00:00") is None

    @pytest.mark.asyncio
    async def test_find_by_mac_empty(self, repo):
        """绌?MAC 杩斿洖 None"""
        assert await repo.find_by_mac("") is None


# ============================================================
# 娴嬭瘯锛氭妧鑳界鐞?
# ============================================================

class TestSkills:
    """add_skill_to_device / remove_skill_from_all_devices"""

    @pytest.mark.asyncio
    async def test_add_skill_to_device(self, repo):
        """鍚戣澶囨坊鍔犳柊鎶€鑳?""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        ok = await repo.add_skill_to_device(SAMPLE_DEVICE_ID, "new_skill")
        assert ok is True
        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)
        assert "new_skill" in cfg["skills"]
        assert "guess_number" in cfg["skills"]  # 鍘熸湁鎶€鑳戒繚鐣?

    @pytest.mark.asyncio
    async def test_add_skill_already_exists(self, repo):
        """娣诲姞宸插瓨鍦ㄧ殑鎶€鑳斤紙骞傜瓑锛?""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        ok = await repo.add_skill_to_device(SAMPLE_DEVICE_ID, "guess_number")
        assert ok is True
        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)
        assert cfg["skills"].count("guess_number") == 1  # 涓嶉噸澶?

    @pytest.mark.asyncio
    async def test_add_skill_nonexistent_device(self, repo):
        """鍚戜笉瀛樺湪鐨勮澶囨坊鍔犳妧鑳借繑鍥?False"""
        ok = await repo.add_skill_to_device("nonexistent", "skill")
        assert ok is False

    @pytest.mark.asyncio
    async def test_add_skill_by_device_key(self, repo):
        """閫氳繃 device_key 娣诲姞鎶€鑳?""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        ok = await repo.add_skill_to_device("test-key-123", "new_skill")
        assert ok is True
        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)
        assert "new_skill" in cfg["skills"]

    @pytest.mark.asyncio
    async def test_remove_skill_from_all_devices(self, repo):
        """浠庢墍鏈夎澶囩Щ闄ゆ妧鑳?""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        await repo.upsert_device("dev2", {
            "name": "device2",
            "key": "key2",
            "skills": ["guess_number", "another_skill"],
        })
        count = await repo.remove_skill_from_all_devices("guess_number")
        assert count == 2  # 涓や釜璁惧閮借淇敼
        cfg1 = await repo.get_device_config(SAMPLE_DEVICE_ID)
        cfg2 = await repo.get_device_config("dev2")
        assert "guess_number" not in cfg1["skills"]
        assert "guess_number" not in cfg2["skills"]
        assert "another_skill" in cfg2["skills"]  # 鍏朵粬鎶€鑳戒繚鐣?

    @pytest.mark.asyncio
    async def test_remove_skill_not_present(self, repo):
        """绉婚櫎涓嶅瓨鍦ㄧ殑鎶€鑳借繑鍥?0"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        count = await repo.remove_skill_from_all_devices("nonexistent_skill")
        assert count == 0

    @pytest.mark.asyncio
    async def test_remove_skill_empty_name(self, repo):
        """绌烘妧鑳藉悕杩斿洖 0"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        count = await repo.remove_skill_from_all_devices("")
        assert count == 0


# ============================================================
# 娴嬭瘯锛氭妧鑳藉惎鍋?
# ============================================================

class TestToggleSkill:
    """toggle_skill 鎿嶄綔 disabled_skills 鍒楄〃"""

    @pytest.mark.asyncio
    async def test_disable_skill(self, repo):
        """绂佺敤鎶€鑳斤細鍔犲叆 disabled_skills"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        # 鍒濆 disabled_skills = ["guess_number"]
        await repo.toggle_skill(SAMPLE_DEVICE_ID, "gushi", disabled=True)
        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)
        assert "gushi" in cfg["disabled_skills"]
        assert "guess_number" in cfg["disabled_skills"]  # 鍘熸湁鐨勪繚鐣?

    @pytest.mark.asyncio
    async def test_enable_skill(self, repo):
        """鍚敤鎶€鑳斤細浠?disabled_skills 绉婚櫎"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        # 鍒濆 disabled_skills = ["guess_number"]
        await repo.toggle_skill(SAMPLE_DEVICE_ID, "guess_number", disabled=False)
        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)
        assert "guess_number" not in cfg["disabled_skills"]
        assert cfg["disabled_skills"] == []

    @pytest.mark.asyncio
    async def test_toggle_skill_idempotent(self, repo):
        """閲嶅绂佺敤涓嶄細閲嶅娣诲姞"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        await repo.toggle_skill(SAMPLE_DEVICE_ID, "gushi", disabled=True)
        await repo.toggle_skill(SAMPLE_DEVICE_ID, "gushi", disabled=True)
        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)
        assert cfg["disabled_skills"].count("gushi") == 1

    @pytest.mark.asyncio
    async def test_enable_non_disabled_skill(self, repo):
        """鍚敤鏈鐢ㄧ殑鎶€鑳斤紙鏃犳搷浣滐級"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        # guess_number 宸茬鐢紝gushi 鏈鐢?
        await repo.toggle_skill(SAMPLE_DEVICE_ID, "gushi", disabled=False)
        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)
        assert "gushi" not in cfg["disabled_skills"]

    @pytest.mark.asyncio
    async def test_toggle_skill_by_device_key(self, repo):
        """閫氳繃 device_key 鍚仠鎶€鑳?""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        await repo.toggle_skill("test-key-123", "gushi", disabled=True)
        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)
        assert "gushi" in cfg["disabled_skills"]

    @pytest.mark.asyncio
    async def test_toggle_skill_nonexistent_device(self, repo):
        """瀵逛笉瀛樺湪鐨勮澶囧惎鍋滄妧鑳斤紙鏃犳搷浣滐紝涓嶆姤閿欙級"""
        # 涓嶅簲鎶涘嚭寮傚父
        await repo.toggle_skill("nonexistent", "gushi", disabled=True)


# ============================================================
# 娴嬭瘯锛歁CP 閰嶇疆 CRUD
# ============================================================

class TestMCP:
    """MCP 鏈嶅姟鍣ㄩ厤缃殑澧炲垹鏀规煡"""

    @pytest.mark.asyncio
    async def test_get_mcp_servers(self, repo):
        """鑾峰彇璁惧鐨?MCP 鏈嶅姟鍣ㄩ厤缃?""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        servers = await repo.get_mcp_servers(SAMPLE_DEVICE_ID)
        assert "amap-maps" in servers
        assert servers["amap-maps"]["url"].startswith("https://")

    @pytest.mark.asyncio
    async def test_get_mcp_servers_nonexistent_device(self, repo):
        """鑾峰彇涓嶅瓨鍦ㄨ澶囩殑 MCP 閰嶇疆杩斿洖绌?dict"""
        assert await repo.get_mcp_servers("nonexistent") == {}

    @pytest.mark.asyncio
    async def test_set_mcp_server(self, repo):
        """娣诲姞鏂扮殑 MCP 鏈嶅姟鍣?""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        await repo.set_mcp_server(SAMPLE_DEVICE_ID, "weather-server", {
            "type": "streamable_http",
            "url": "https://example.com/mcp",
        })
        servers = await repo.get_mcp_servers(SAMPLE_DEVICE_ID)
        assert "weather-server" in servers
        assert servers["weather-server"]["url"] == "https://example.com/mcp"
        # 鍘熸湁鐨勪繚鐣?
        assert "amap-maps" in servers

    @pytest.mark.asyncio
    async def test_update_mcp_server(self, repo):
        """鏇存柊宸叉湁 MCP 鏈嶅姟鍣ㄩ厤缃?""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        await repo.set_mcp_server(SAMPLE_DEVICE_ID, "amap-maps", {
            "type": "streamable_http",
            "url": "https://new-url.com/mcp",
        })
        servers = await repo.get_mcp_servers(SAMPLE_DEVICE_ID)
        assert servers["amap-maps"]["url"] == "https://new-url.com/mcp"

    @pytest.mark.asyncio
    async def test_delete_mcp_server(self, repo):
        """鍒犻櫎 MCP 鏈嶅姟鍣?""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        await repo.delete_mcp_server(SAMPLE_DEVICE_ID, "amap-maps")
        servers = await repo.get_mcp_servers(SAMPLE_DEVICE_ID)
        assert "amap-maps" not in servers

    @pytest.mark.asyncio
    async def test_delete_nonexistent_mcp_server(self, repo):
        """鍒犻櫎涓嶅瓨鍦ㄧ殑 MCP 鏈嶅姟鍣紙鏃犳搷浣滐紝涓嶆姤閿欙級"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        await repo.delete_mcp_server(SAMPLE_DEVICE_ID, "nonexistent")
        servers = await repo.get_mcp_servers(SAMPLE_DEVICE_ID)
        assert "amap-maps" in servers  # 鍘熸湁鐨勪繚鐣?

    @pytest.mark.asyncio
    async def test_mcp_by_device_key(self, repo):
        """閫氳繃 device_key 鎿嶄綔 MCP"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        await repo.set_mcp_server("test-key-123", "new-server", {
            "url": "https://example.com",
        })
        servers = await repo.get_mcp_servers("test-key-123")
        assert "new-server" in servers

    @pytest.mark.asyncio
    async def test_mcp_nonexistent_device(self, repo):
        """瀵逛笉瀛樺湪鐨勮澶囨搷浣?MCP锛堟棤鎿嶄綔锛屼笉鎶ラ敊锛?""
        # 涓嶅簲鎶涘嚭寮傚父
        await repo.set_mcp_server("nonexistent", "server", {"url": "x"})
        await repo.delete_mcp_server("nonexistent", "server")
        assert await repo.get_mcp_servers("nonexistent") == {}


# ============================================================
# 娴嬭瘯锛氬悓姝ュ姞杞?
# ============================================================

class TestSyncLoad:
    """load_all_devices_sync 鍚屾鍔犺浇"""

    def test_load_all_devices_sync(self, sync_repo):
        """鍚屾鍔犺浇璁惧閰嶇疆锛堣嚜鍖呭惈锛氱洿鎺ュ啓鍏?+ 鍚屾璇诲彇锛?""
        from src.infrastructure.db.compat.sync_session import get_sync_session_factory
        factory = get_sync_session_factory()
        with factory() as session:
            fields = _dict_to_model_fields(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
            session.add(DeviceModel(**fields))
            session.commit()

        result = sync_repo.load_all_devices_sync()
        assert SAMPLE_DEVICE_ID in result
        cfg = result[SAMPLE_DEVICE_ID]
        # 楠岃瘉 dict 缁撴瀯涓?users.json 涓€鑷?
        assert cfg["name"] == "瀹㈠巺鐨勮澶?
        assert cfg["key"] == "test-key-123"
        assert cfg["asr_provider"] == "volcengine"
        assert cfg["llm"]["model"] == "deepseek-v4-flash"
        assert cfg["tts_config"]["voice_type"] == "zh_female_vv_uranus_bigtts"
        assert cfg["music"]["api_url"] == "http://192.168.31.176:2233"
        assert "amap-maps" in cfg["mcp_servers"]
        assert cfg["wakeup"]["text"] == "鎴戝湪锛屼綘璇?
        assert cfg["skills"] == ["guess_number", "gushi", "new"]
        assert cfg["disabled_skills"] == ["guess_number"]
        assert cfg["ota"]["enabled"] is True

    def test_load_all_devices_sync_empty(self, sync_repo):
        """绌烘暟鎹簱鍚屾鍔犺浇杩斿洖绌?dict"""
        result = sync_repo.load_all_devices_sync()
        assert result == {}

    def test_load_all_devices_sync_multiple(self, sync_repo):
        """鍚屾鍔犺浇澶氫釜璁惧"""
        from src.infrastructure.db.compat.sync_session import get_sync_session_factory
        factory = get_sync_session_factory()
        with factory() as session:
            session.add(DeviceModel(
                device_id="dev1", name="璁惧1", device_key="key1",
            ))
            session.add(DeviceModel(
                device_id="dev2", name="璁惧2", device_key="key2",
            ))
            session.commit()

        result = sync_repo.load_all_devices_sync()
        assert len(result) == 2
        assert result["dev1"]["name"] == "璁惧1"
        assert result["dev2"]["name"] == "璁惧2"


# ============================================================
# 娴嬭瘯锛歶psert 骞傜瓑鎬?
# ============================================================

class TestUpsertIdempotent:
    """upsert 骞傜瓑鎬э細澶氭 upsert 鍚屼竴璁惧涓嶄骇鐢熼噸澶嶈"""

    @pytest.mark.asyncio
    async def test_upsert_idempotent(self, repo):
        """澶氭 upsert 鍚屼竴璁惧涓嶄骇鐢熼噸澶?""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)

        all_devices = await repo.get_all_devices()
        assert len(all_devices) == 1
        assert SAMPLE_DEVICE_ID in all_devices

    @pytest.mark.asyncio
    async def test_upsert_updates_existing(self, repo):
        """upsert 鏇存柊宸插瓨鍦ㄨ澶囷紙瑕嗙洊瀛楁锛?""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        new_config = copy.deepcopy(SAMPLE_CONFIG)
        new_config["name"] = "鏂板悕绉?
        new_config["llm"]["model"] = "gpt-4"
        await repo.upsert_device(SAMPLE_DEVICE_ID, new_config)

        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)
        assert cfg["name"] == "鏂板悕绉?
        assert cfg["llm"]["model"] == "gpt-4"
        # 鍏朵粬瀛楁淇濈暀
        assert cfg["key"] == "test-key-123"

    @pytest.mark.asyncio
    async def test_upsert_preserves_created_at(self, repo):
        """upsert 鏇存柊鏃?created_at 涓嶅彉锛寀pdated_at 鍒锋柊"""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        # 璇诲彇鍒濆鏃堕棿鎴?
        from src.infrastructure.db.session import get_session_ctx
        async with get_session_ctx() as session:
            model = (await session.execute(
                select(DeviceModel).where(DeviceModel.device_id == SAMPLE_DEVICE_ID)
            )).scalar_one()
            created_before = model.created_at
            updated_before = model.updated_at

        time.sleep(0.02)  # 纭繚 updated_at 鏈夊彉鍖?
        await repo.upsert_device(SAMPLE_DEVICE_ID, {"name": "鏂板悕绉?})

        async with get_session_ctx() as session:
            model = (await session.execute(
                select(DeviceModel).where(DeviceModel.device_id == SAMPLE_DEVICE_ID)
            )).scalar_one()
            assert model.created_at == created_before  # 鍒涘缓鏃堕棿涓嶅彉
            assert model.updated_at > updated_before  # 鏇存柊鏃堕棿鍒锋柊

    @pytest.mark.asyncio
    async def test_upsert_multiple_devices(self, repo):
        """upsert 澶氫釜涓嶅悓璁惧"""
        await repo.upsert_device("dev1", {"name": "d1", "key": "k1"})
        await repo.upsert_device("dev2", {"name": "d2", "key": "k2"})
        await repo.upsert_device("dev3", {"name": "d3", "key": "k3"})
        all_devices = await repo.get_all_devices()
        assert len(all_devices) == 3

    @pytest.mark.asyncio
    async def test_upsert_empty_device_id(self, repo):
        """绌?device_id 涓嶆墽琛屾搷浣?""
        await repo.upsert_device("", {"name": "x"})
        assert await repo.get_all_devices() == {}


# ============================================================
# 娴嬭瘯锛歞ict 缁撴瀯鍏煎鎬?
# ============================================================

class TestDictCompat:
    """杩斿洖鐨?dict 缁撴瀯涓?users.json 瀹屽叏涓€鑷?""

    @pytest.mark.asyncio
    async def test_dict_structure_matches_users_json(self, repo):
        """upsert + get 杩斿洖鐨?dict 缁撴瀯涓?users.json 涓€鑷?""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)

        # 楠岃瘉鎵€鏈?users.json 涓簲鏈夌殑椤跺眰瀛楁
        expected_keys = {
            "name", "key", "asr_provider", "asr_config",
            "llm_type", "llm",
            "tts_type", "tts_config",
            "music", "mcp_servers", "wakeup",
            "rate_limit_rpm",
            "ota",
            "disabled_tools", "disabled_mcp_servers", "disabled_mcp_tools",
            "disabled_skills", "skills",
        }
        assert set(cfg.keys()) == expected_keys, (
            f"瀛楁涓嶄竴鑷? 澶?{set(cfg.keys()) - expected_keys}, "
            f"灏?{expected_keys - set(cfg.keys())}"
        )

        # 楠岃瘉宓屽瀛楁
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
        """杩斿洖鐨?dict 鍙 load_devices() 姝ｇ‘瑙ｆ瀽涓?DeviceConfig"""
        from src.use_cases.device_config import DeviceConfig
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)

        # 妯℃嫙 load_devices() 鐨勮В鏋愰€昏緫
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

        # 楠岃瘉瀛楁姝ｇ‘瑙ｆ瀽
        assert dc.device_id == SAMPLE_DEVICE_ID
        assert dc.name == "瀹㈠巺鐨勮澶?
        assert dc.key == "test-key-123"
        assert dc.asr_provider == "volcengine"
        assert dc.llm_type == "openai"
        assert dc.tts_type == "volcengine"
        assert dc.llm_api_key == "sk-test-key-1234567890"
        assert dc.llm_model == "deepseek-v4-flash"
        assert dc.llm_system_prompt == "浣犵殑鍚嶅瓧鍙嚒鍑?
        assert dc.llm_memory_enabled is True
        assert dc.llm_memory_max_messages == 20
        assert dc.rate_limit_rpm == 60
        assert dc.ota_enabled is True
        assert dc.ota_is_official == "0"
        assert dc.skills == ["guess_number", "gushi", "new"]
        assert dc.disabled_skills == ["guess_number"]
        assert dc.disabled_tools == []
        assert dc.wakeup_config["text"] == "鎴戝湪锛屼綘璇?
        assert "amap-maps" in (dc.mcp_servers or {})

    @pytest.mark.asyncio
    async def test_roundtrip_preserves_data(self, repo):
        """upsert -> get 寰€杩斾繚鎸佹暟鎹畬鏁?""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        cfg = await repo.get_device_config(SAMPLE_DEVICE_ID)
        # 鍐嶆 upsert 璇诲彇鐨?dict锛堟ā鎷熶粠 DB 璇诲嚭鍚庡啓鍥烇級
        await repo.upsert_device(SAMPLE_DEVICE_ID, cfg)
        cfg2 = await repo.get_device_config(SAMPLE_DEVICE_ID)
        # 鏁版嵁搴斾繚鎸佷竴鑷?
        assert cfg2 == cfg

    @pytest.mark.asyncio
    async def test_get_all_devices_returns_users_json_structure(self, repo):
        """get_all_devices 杩斿洖鐨?dict 缁撴瀯涓?users.json 鐨?devices 瀛楁涓€鑷?""
        await repo.upsert_device(SAMPLE_DEVICE_ID, SAMPLE_CONFIG)
        all_devices = await repo.get_all_devices()
        # 妯℃嫙 users.json 鐨勫畬鏁寸粨鏋?
        users_json_like = {"devices": all_devices}
        assert "devices" in users_json_like
        assert SAMPLE_DEVICE_ID in users_json_like["devices"]
        cfg = users_json_like["devices"][SAMPLE_DEVICE_ID]
        assert cfg["name"] == "瀹㈠巺鐨勮澶?
        assert cfg["llm"]["model"] == "deepseek-v4-flash"

    @pytest.mark.asyncio
    async def test_defaults_for_minimal_config(self, repo):
        """鏈€灏忛厤缃篃鑳芥甯稿線杩旓紙浣跨敤榛樿鍊硷級"""
        await repo.upsert_device("minimal-dev", {
            "name": "鏈€灏忚澶?,
            "key": "min-key",
        })
        cfg = await repo.get_device_config("minimal-dev")
        assert cfg is not None
        # 榛樿鍊?
        assert cfg["name"] == "鏈€灏忚澶?
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
