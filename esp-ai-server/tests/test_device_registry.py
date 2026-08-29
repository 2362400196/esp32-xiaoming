"""
device_registry.py 单元测试

DeviceRegistry 负责：
- 设备注册 / 注销（async，使用 asyncio.Lock 保护 _devices 和 _mac_index）
- 设备查询：get / get_by_mac / resolve / has / get_all_ids / count / get_all_sessions
- 统计：get_stats
- OTA 管理：update_ota_progress / set_ota_updating / set_pending_ota / get_pending_ota
- 待推送管理：set_pending_wifi_config / get_pending_wifi_config /
  set_pending_instruct / get_pending_instruct

关键点：
- register 是 async 方法，内部使用 `async with self._lock`
- get_all_ids 返回 `list(self._devices.keys())`
- get / has / count / get_all_ids 等查询方法是同步方法（无锁读取）
- 设备信息存储为 dict，包含 channel/session/fsm/user_config 等字段
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.use_cases.device_registry import DeviceRegistry


def _make_session():
    """构造一个带 cancel_event 的 mock session"""
    s = MagicMock()
    s.cancel_event = MagicMock()
    s.cancel_event.set = MagicMock()
    return s


def _make_fsm():
    """构造一个 mock fsm"""
    return MagicMock()


def _make_channel():
    """构造一个 mock channel"""
    ch = MagicMock()
    ch.close = AsyncMock()
    return ch


def _make_tool_manager():
    """构造一个带 cleanup 的 mock tool_manager"""
    tm = MagicMock()
    tm.cleanup = AsyncMock()
    return tm


# ============================================================
# DeviceRegistry 初始化
# ============================================================


class TestDeviceRegistryInit:
    """DeviceRegistry 初始化"""

    def test_init_empty(self):
        reg = DeviceRegistry()
        assert reg._devices == {}
        assert reg._mac_index == {}
        assert reg._lock is not None
        assert reg._stats["register_count"] == 0
        assert reg._stats["unregister_count"] == 0
        assert reg._stats["lookup_count"] == 0


# ============================================================
# register 注册设备
# ============================================================


class TestRegister:
    """register：async 注册设备（使用锁保护）"""

    async def test_register_new_device(self):
        reg = DeviceRegistry()
        channel = _make_channel()
        session = _make_session()
        fsm = _make_fsm()
        await reg.register("d1", channel, session, fsm)
        assert "d1" in reg._devices
        device = reg._devices["d1"]
        assert device["channel"] is channel
        assert device["session"] is session
        assert device["fsm"] is fsm
        assert device["register_time"] > 0

    async def test_register_includes_all_fields(self):
        reg = DeviceRegistry()
        channel = _make_channel()
        session = _make_session()
        fsm = _make_fsm()
        user_config = {"key": "val"}
        asr_client = MagicMock()
        tm = _make_tool_manager()
        await reg.register(
            "d1", channel, session, fsm,
            user_config=user_config,
            asr_client=asr_client,
            tool_manager=tm,
            mac="AA:BB:CC",
            firmware_version="1.0.0",
        )
        device = reg._devices["d1"]
        assert device["user_config"] == user_config
        assert device["asr_client"] is asr_client
        assert device["tool_manager"] is tm
        assert device["mac"] == "AA:BB:CC"
        assert device["firmware_version"] == "1.0.0"
        assert device["ota_updating"] is False
        assert device["ota_progress"] == 0.0

    async def test_register_with_mac_creates_mac_index(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm(), mac="AA:BB:CC")
        assert reg._mac_index["AA:BB:CC"] == "d1"

    async def test_register_without_mac_no_mac_index(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        assert reg._mac_index == {}

    async def test_register_overwrites_existing(self):
        reg = DeviceRegistry()
        ch1 = _make_channel()
        ch2 = _make_channel()
        await reg.register("d1", ch1, _make_session(), _make_fsm())
        await reg.register("d1", ch2, _make_session(), _make_fsm())
        assert reg._devices["d1"]["channel"] is ch2

    async def test_register_reconnect_cleans_old_mac_index(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm(), mac="old_mac")
        assert reg._mac_index["old_mac"] == "d1"
        # 重连时用新 mac
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm(), mac="new_mac")
        assert "old_mac" not in reg._mac_index
        assert reg._mac_index["new_mac"] == "d1"

    async def test_register_reconnect_cancels_old_session(self):
        reg = DeviceRegistry()
        old_session = _make_session()
        await reg.register("d1", _make_channel(), old_session, _make_fsm())
        # 重连
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        # 旧 session 的 cancel_event 应被 set
        old_session.cancel_event.set.assert_called_once()

    async def test_register_reconnect_cleans_old_tool_manager(self):
        reg = DeviceRegistry()
        old_tm = _make_tool_manager()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm(), tool_manager=old_tm)
        # 重连（需要让 create_task 执行）
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        # 等待 create_task 完成
        await asyncio.sleep(0.05)
        old_tm.cleanup.assert_awaited()

    async def test_register_increments_stats(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        await reg.register("d2", _make_channel(), _make_session(), _make_fsm())
        assert reg._stats["register_count"] == 2

    async def test_register_multiple_devices(self):
        reg = DeviceRegistry()
        for i in range(5):
            await reg.register(f"d{i}", _make_channel(), _make_session(), _make_fsm())
        assert len(reg._devices) == 5

    async def test_register_concurrent_safe(self):
        """并发注册不应丢失设备（锁保护）"""
        reg = DeviceRegistry()
        await asyncio.gather(*[
            reg.register(f"d{i}", _make_channel(), _make_session(), _make_fsm())
            for i in range(10)
        ])
        assert len(reg._devices) == 10


# ============================================================
# unregister 注销设备
# ============================================================


class TestUnregister:
    """unregister：async 注销设备"""

    async def test_unregister_existing(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        await reg.unregister("d1")
        assert "d1" not in reg._devices

    async def test_unregister_nonexistent_is_noop(self):
        reg = DeviceRegistry()
        # 不应抛异常
        await reg.unregister("nonexistent")

    async def test_unregister_closes_channel(self):
        reg = DeviceRegistry()
        channel = _make_channel()
        await reg.register("d1", channel, _make_session(), _make_fsm())
        await reg.unregister("d1")
        channel.close.assert_awaited()

    async def test_unregister_cancels_session(self):
        reg = DeviceRegistry()
        session = _make_session()
        await reg.register("d1", _make_channel(), session, _make_fsm())
        await reg.unregister("d1")
        session.cancel_event.set.assert_called_once()

    async def test_unregister_cleans_tool_manager(self):
        reg = DeviceRegistry()
        tm = _make_tool_manager()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm(), tool_manager=tm)
        await reg.unregister("d1")
        tm.cleanup.assert_awaited()

    async def test_unregister_removes_mac_index(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm(), mac="AA:BB")
        await reg.unregister("d1")
        assert "AA:BB" not in reg._mac_index

    async def test_unregister_increments_stats(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        await reg.unregister("d1")
        assert reg._stats["unregister_count"] == 1

    async def test_unregister_specific_device(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        await reg.register("d2", _make_channel(), _make_session(), _make_fsm())
        await reg.unregister("d1")
        assert "d1" not in reg._devices
        assert "d2" in reg._devices

    async def test_unregister_cleanup_exception_handled(self):
        reg = DeviceRegistry()
        channel = _make_channel()
        channel.close = AsyncMock(side_effect=RuntimeError("close fail"))
        await reg.register("d1", channel, _make_session(), _make_fsm())
        # 不应抛异常
        await reg.unregister("d1")
        assert "d1" not in reg._devices

    async def test_unregister_session_mismatch_skips(self):
        """重连竞态：注册表中 session 已被新会话覆盖时，旧会话迟到的注销应跳过（不杀新会话）"""
        reg = DeviceRegistry()
        old_session = _make_session()
        old_tm = _make_tool_manager()
        await reg.register("d1", _make_channel(), old_session, _make_fsm(), tool_manager=old_tm)

        # 设备重连：新会话先 register 覆盖条目
        new_session = _make_session()
        new_tm = _make_tool_manager()
        await reg.register("d1", _make_channel(), new_session, _make_fsm(), tool_manager=new_tm)

        # 旧 handler 迟到的 cleanup：传入旧 session → 属主不匹配，跳过注销
        await reg.unregister("d1", session=old_session)
        assert "d1" in reg._devices
        assert reg._devices["d1"]["session"] is new_session
        new_tm.cleanup.assert_not_awaited()

        # 新会话自己注销：属主匹配，正常注销
        await reg.unregister("d1", session=new_session)
        assert "d1" not in reg._devices
        new_tm.cleanup.assert_awaited()

    async def test_unregister_session_none_keeps_old_behavior(self):
        """session=None（默认）保持旧行为：无条件注销（兼容其他调用点）"""
        reg = DeviceRegistry()
        session = _make_session()
        await reg.register("d1", _make_channel(), session, _make_fsm())
        # 即使传入与注册表不一致的对象也不影响 None 路径
        await reg.unregister("d1", session=None)
        assert "d1" not in reg._devices


# ============================================================
# get / get_by_mac / resolve 同步查询
# ============================================================


class TestGet:
    """get：同步获取设备信息"""

    async def test_get_existing(self):
        reg = DeviceRegistry()
        channel = _make_channel()
        await reg.register("d1", channel, _make_session(), _make_fsm())
        device = reg.get("d1")
        assert device is not None
        assert device["channel"] is channel

    async def test_get_nonexistent_returns_none(self):
        reg = DeviceRegistry()
        assert reg.get("nonexistent") is None

    async def test_get_increments_lookup_count(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        reg.get("d1")
        reg.get("d1")
        assert reg._stats["lookup_count"] == 2


class TestGetByMac:
    """get_by_mac：通过 MAC 地址查询设备"""

    async def test_get_by_mac_existing(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm(), mac="AA:BB:CC")
        device = reg.get_by_mac("AA:BB:CC")
        assert device is not None
        assert device["mac"] == "AA:BB:CC"

    async def test_get_by_mac_nonexistent(self):
        reg = DeviceRegistry()
        # 无 mac 索引时回退到 device_id 查询
        assert reg.get_by_mac("nonexistent") is None

    async def test_get_by_mac_fallback_to_device_id(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        # 无 mac 时，get_by_mac 回退到用参数作为 device_id
        device = reg.get_by_mac("d1")
        assert device is not None


class TestResolve:
    """resolve：先查 mac 索引再查 device_id"""

    async def test_resolve_by_mac(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm(), mac="AA:BB")
        device = reg.resolve("AA:BB")
        assert device is not None
        assert device["mac"] == "AA:BB"

    async def test_resolve_by_device_id(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        device = reg.resolve("d1")
        assert device is not None

    async def test_resolve_nonexistent(self):
        reg = DeviceRegistry()
        assert reg.resolve("nonexistent") is None


# ============================================================
# has / get_all_ids / count / get_all_sessions
# ============================================================


class TestHas:
    """has：检查设备是否已注册"""

    async def test_has_true(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        assert reg.has("d1") is True

    async def test_has_false(self):
        reg = DeviceRegistry()
        assert reg.has("nonexistent") is False

    async def test_has_false_after_unregister(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        await reg.unregister("d1")
        assert reg.has("d1") is False


class TestGetAllIds:
    """get_all_ids：返回所有设备 ID 列表"""

    async def test_empty(self):
        reg = DeviceRegistry()
        assert reg.get_all_ids() == []

    async def test_returns_list(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        await reg.register("d2", _make_channel(), _make_session(), _make_fsm())
        result = reg.get_all_ids()
        assert isinstance(result, list)
        assert set(result) == {"d1", "d2"}

    async def test_returns_copy(self):
        """get_all_ids 应返回列表的副本，修改不影响内部状态"""
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        result = reg.get_all_ids()
        result.append("fake")
        assert "fake" not in reg._devices


class TestCount:
    """count：返回设备数量"""

    async def test_empty(self):
        reg = DeviceRegistry()
        assert reg.count() == 0

    async def test_with_devices(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        await reg.register("d2", _make_channel(), _make_session(), _make_fsm())
        assert reg.count() == 2

    async def test_after_unregister(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        await reg.register("d2", _make_channel(), _make_session(), _make_fsm())
        await reg.unregister("d1")
        assert reg.count() == 1


class TestGetAllSessions:
    """get_all_sessions：返回所有设备的 session 列表"""

    async def test_empty(self):
        reg = DeviceRegistry()
        assert reg.get_all_sessions() == []

    async def test_returns_sessions(self):
        reg = DeviceRegistry()
        s1 = _make_session()
        s2 = _make_session()
        await reg.register("d1", _make_channel(), s1, _make_fsm())
        await reg.register("d2", _make_channel(), s2, _make_fsm())
        sessions = reg.get_all_sessions()
        assert len(sessions) == 2
        assert s1 in sessions
        assert s2 in sessions

    async def test_filters_none_sessions(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        await reg.register("d2", _make_channel(), None, _make_fsm())
        sessions = reg.get_all_sessions()
        assert len(sessions) == 1  # None session 被过滤


# ============================================================
# get_stats 统计
# ============================================================


class TestGetStats:
    """get_stats：返回统计信息"""

    async def test_empty_stats(self):
        reg = DeviceRegistry()
        stats = reg.get_stats()
        assert stats["total_devices"] == 0
        assert stats["mac_index_size"] == 0
        assert stats["register_count"] == 0
        assert stats["unregister_count"] == 0
        assert stats["lookup_count"] == 0

    async def test_stats_after_operations(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm(), mac="AA")
        await reg.register("d2", _make_channel(), _make_session(), _make_fsm())
        reg.get("d1")
        await reg.unregister("d1")
        stats = reg.get_stats()
        assert stats["total_devices"] == 1
        assert stats["mac_index_size"] == 0  # d1 被注销，mac 索引也清除
        assert stats["register_count"] == 2
        assert stats["unregister_count"] == 1
        assert stats["lookup_count"] == 1


# ============================================================
# OTA 管理
# ============================================================


class TestOTAManagement:
    """OTA 相关方法：update_ota_progress / set_ota_updating / set_pending_ota / get_pending_ota"""

    async def test_set_ota_updating_true(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        reg.set_ota_updating("d1", True)
        assert reg._devices["d1"]["ota_updating"] is True
        assert reg._devices["d1"]["ota_progress"] == 0.0

    async def test_set_ota_updating_false(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        reg.set_ota_updating("d1", False)
        assert reg._devices["d1"]["ota_updating"] is False

    async def test_update_ota_progress(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        reg.update_ota_progress("d1", 50.0)
        assert reg._devices["d1"]["ota_progress"] == 50.0

    async def test_update_ota_progress_100_sets_updating_false(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        reg.set_ota_updating("d1", True)
        reg.update_ota_progress("d1", 100)
        assert reg._devices["d1"]["ota_updating"] is False

    async def test_set_pending_ota(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        ota_cmd = {"url": "http://ota.url", "version": "2.0"}
        reg.set_pending_ota("d1", ota_cmd)
        assert reg._devices["d1"]["pending_ota"] == ota_cmd

    async def test_get_pending_ota(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        ota_cmd = {"url": "http://ota.url"}
        reg.set_pending_ota("d1", ota_cmd)
        assert reg.get_pending_ota("d1") == ota_cmd

    async def test_get_pending_ota_none(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        assert reg.get_pending_ota("d1") is None

    async def test_clear_pending_ota(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        reg.set_pending_ota("d1", {"url": "x"})
        reg.set_pending_ota("d1", None)
        assert reg.get_pending_ota("d1") is None

    async def test_ota_methods_on_nonexistent_device(self):
        reg = DeviceRegistry()
        # 对不存在的设备操作不应抛异常
        reg.set_ota_updating("nope", True)
        reg.update_ota_progress("nope", 50)
        reg.set_pending_ota("nope", {"x": 1})
        assert reg.get_pending_ota("nope") is None

    async def test_ota_methods_use_resolve(self):
        """OTA 方法应通过 resolve 查找（支持 mac 地址）"""
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm(), mac="AA:BB")
        reg.set_ota_updating("AA:BB", True)
        # 通过 mac 查找应能设置
        assert reg.resolve("AA:BB")["ota_updating"] is True


# ============================================================
# 待推送管理
# ============================================================


class TestPendingManagement:
    """待推送 WiFi 配置和指令管理"""

    async def test_set_pending_wifi_config(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        config = {"wifi_name": "MyWiFi", "wifi_pwd": "pass"}
        reg.set_pending_wifi_config("d1", config)
        assert reg._devices["d1"]["pending_wifi_config"] == config

    async def test_get_pending_wifi_config(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        config = {"wifi_name": "MyWiFi"}
        reg.set_pending_wifi_config("d1", config)
        assert reg.get_pending_wifi_config("d1") == config

    async def test_get_pending_wifi_config_none(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        assert reg.get_pending_wifi_config("d1") is None

    async def test_clear_pending_wifi_config(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        reg.set_pending_wifi_config("d1", {"wifi_name": "x"})
        reg.set_pending_wifi_config("d1", None)
        assert reg.get_pending_wifi_config("d1") is None

    async def test_set_pending_instruct(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        cmd = {"command_id": "set_volume", "data": "0.5"}
        reg.set_pending_instruct("d1", cmd)
        assert reg._devices["d1"]["pending_instruct"] == cmd

    async def test_get_pending_instruct(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        cmd = {"command_id": "set_volume"}
        reg.set_pending_instruct("d1", cmd)
        assert reg.get_pending_instruct("d1") == cmd

    async def test_get_pending_instruct_none(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        assert reg.get_pending_instruct("d1") is None

    async def test_clear_pending_instruct(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm())
        reg.set_pending_instruct("d1", {"command_id": "x"})
        reg.set_pending_instruct("d1", None)
        assert reg.get_pending_instruct("d1") is None

    async def test_pending_methods_on_nonexistent_device(self):
        reg = DeviceRegistry()
        reg.set_pending_wifi_config("nope", {"x": 1})
        reg.set_pending_instruct("nope", {"y": 2})
        assert reg.get_pending_wifi_config("nope") is None
        assert reg.get_pending_instruct("nope") is None


# ============================================================
# 集成场景
# ============================================================


class TestDeviceRegistryIntegration:
    """DeviceRegistry 集成场景"""

    async def test_register_get_unregister_flow(self):
        reg = DeviceRegistry()
        channel = _make_channel()
        session = _make_session()
        # 注册
        await reg.register("d1", channel, session, _make_fsm())
        assert reg.has("d1") is True
        # 获取
        device = reg.get("d1")
        assert device["channel"] is channel
        # 注销
        await reg.unregister("d1")
        assert reg.has("d1") is False
        assert reg.get("d1") is None

    async def test_multiple_devices_management(self):
        reg = DeviceRegistry()
        for i in range(5):
            await reg.register(f"d{i}", _make_channel(), _make_session(), _make_fsm(), mac=f"mac{i}")
        assert reg.count() == 5
        # 注销一半
        for i in range(0, 5, 2):
            await reg.unregister(f"d{i}")
        assert reg.count() == 2
        remaining = reg.get_all_ids()
        assert set(remaining) == {"d1", "d3"}

    async def test_mac_index_after_operations(self):
        reg = DeviceRegistry()
        await reg.register("d1", _make_channel(), _make_session(), _make_fsm(), mac="mac1")
        await reg.register("d2", _make_channel(), _make_session(), _make_fsm(), mac="mac2")
        assert reg._mac_index["mac1"] == "d1"
        assert reg._mac_index["mac2"] == "d2"
        # 注销 d1 后 mac1 索引应被清除
        await reg.unregister("d1")
        assert "mac1" not in reg._mac_index
        assert reg._mac_index["mac2"] == "d2"

    async def test_concurrent_register_and_unregister(self):
        """并发注册和注销不应导致数据不一致"""
        reg = DeviceRegistry()
        await asyncio.gather(
            reg.register("d1", _make_channel(), _make_session(), _make_fsm()),
            reg.register("d2", _make_channel(), _make_session(), _make_fsm()),
            reg.unregister("d1"),
            reg.register("d3", _make_channel(), _make_session(), _make_fsm()),
        )
        # d2 和 d3 应存在
        assert reg.has("d2") is True
        assert reg.has("d3") is True
