"""
sdk/events.py 事件系统 + exec 桥权限上下文 + 音乐白名单 单元测试

覆盖：
- events: 订阅/发布/取消订阅、异常隔离、协程回调后台执行
- plugin_exec（exec 桥）：调用插件前端 API 前设置插件权限上下文，finally 复位
- DeviceRegistry register/unregister 发布设备上线/离线事件
- music 白名单拦截：devices.py _device_action 与 WS music_play_next 路径
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.use_cases.sdk import events as events_mod
from src.use_cases.sdk.events import (
    subscribe,
    unsubscribe,
    publish,
    EVENT_DEVICE_ONLINE,
    EVENT_DEVICE_OFFLINE,
)


# ============================================================
# 事件系统基础
# ============================================================

class TestEvents:
    def setup_method(self):
        # 每个测试前清空全局订阅，避免相互影响
        events_mod._subscriptions.clear()

    def teardown_method(self):
        events_mod._subscriptions.clear()

    def test_subscribe_publish_sync_callback(self):
        """同步回调：publish 时收到 payload"""
        received = []
        sub_id = subscribe("test_event", lambda **kw: received.append(kw), plugin_name="p1")
        assert isinstance(sub_id, str) and sub_id

        publish("test_event", device_id="dev1")
        assert received == [{"device_id": "dev1"}]

    def test_unsubscribe_stops_delivery(self):
        """取消订阅后不再收到事件"""
        received = []
        sub_id = subscribe("test_event", lambda **kw: received.append(kw))
        assert unsubscribe(sub_id) is True
        # 再次取消返回 False
        assert unsubscribe(sub_id) is False

        publish("test_event", x=1)
        assert received == []

    def test_publish_no_subscribers_is_noop(self):
        """无人订阅时 publish 为空操作且不报错"""
        publish("nobody_listens", a=1)

    def test_exception_isolation_between_subscribers(self):
        """单个订阅者抛异常不影响其他订阅者，也不向发布方传播"""
        received = []

        def bad_cb(**kw):
            raise RuntimeError("订阅者炸了")

        subscribe("test_event", bad_cb)
        subscribe("test_event", lambda **kw: received.append(kw))

        # 不应抛出异常
        publish("test_event", n=42)
        assert received == [{"n": 42}]

    def test_bad_callback_payload_does_not_break_others(self):
        """回调签名不匹配（unexpected kwarg）同样被隔离"""
        received = []
        subscribe("test_event", lambda: None)  # 不接受任何参数
        subscribe("test_event", lambda **kw: received.append(kw))

        publish("test_event", n=1)
        assert received == [{"n": 1}]

    async def test_async_callback_runs_via_background_task(self):
        """协程函数回调：不阻塞 publish，由后台任务完成"""
        received = []

        async def async_cb(**kw):
            await asyncio.sleep(0)
            received.append(kw)

        subscribe("test_event", async_cb)
        publish("test_event", v="hello")

        # publish 同步返回，回调在后台任务中执行
        await asyncio.sleep(0.05)
        assert received == [{"v": "hello"}]

    async def test_async_callback_exception_isolated(self):
        """协程回调抛异常不影响后续订阅者"""
        received = []

        async def bad_async(**kw):
            await asyncio.sleep(0)
            raise ValueError("async 炸了")

        subscribe("test_event", bad_async)
        subscribe("test_event", lambda **kw: received.append(kw))

        publish("test_event", n=1)
        await asyncio.sleep(0.05)
        assert received == [{"n": 1}]


# ============================================================
# DeviceRegistry 设备上线/离线事件
# ============================================================

def _make_registry_device(channel=None, session=None, tool_manager=None):
    return {
        "channel": channel,
        "session": session,
        "tool_manager": tool_manager,
    }


class TestDeviceRegistryEvents:
    async def test_register_publishes_device_online(self):
        """register 成功后发布 EVENT_DEVICE_ONLINE"""
        from src.use_cases.device_registry import DeviceRegistry

        received = []
        sub_id = subscribe(EVENT_DEVICE_ONLINE, lambda **kw: received.append(kw))
        try:
            reg = DeviceRegistry()
            await reg.register("dev_key_1", channel=MagicMock(), session=MagicMock(), fsm=MagicMock())
            assert received == [{"device_id": "dev_key_1"}]
        finally:
            unsubscribe(sub_id)

    async def test_unregister_publishes_device_offline(self):
        """实际删除后发布 EVENT_DEVICE_OFFLINE"""
        from src.use_cases.device_registry import DeviceRegistry

        online, offline = [], []
        s1 = subscribe(EVENT_DEVICE_ONLINE, lambda **kw: online.append(kw))
        s2 = subscribe(EVENT_DEVICE_OFFLINE, lambda **kw: offline.append(kw))
        try:
            reg = DeviceRegistry()
            tm = MagicMock()
            tm.cleanup = AsyncMock()
            ch = MagicMock()
            ch.close = AsyncMock()
            await reg.register("dev_key_2", channel=ch, session=MagicMock(), fsm=MagicMock(),
                               tool_manager=tm)
            await reg.unregister("dev_key_2")
            assert offline == [{"device_id": "dev_key_2"}]
            # 重复注销（设备已不存在）不发布离线事件
            await reg.unregister("dev_key_2")
            assert offline == [{"device_id": "dev_key_2"}]
        finally:
            unsubscribe(s1)
            unsubscribe(s2)

    async def test_registry_event_subscriber_exception_does_not_break_register(self):
        """事件订阅者异常不影响注册/注销主流程"""
        from src.use_cases.device_registry import DeviceRegistry

        def bad(**kw):
            raise RuntimeError("boom")

        s1 = subscribe(EVENT_DEVICE_ONLINE, bad)
        s2 = subscribe(EVENT_DEVICE_OFFLINE, bad)
        try:
            reg = DeviceRegistry()
            await reg.register("dev_key_3", channel=MagicMock(), session=MagicMock(), fsm=MagicMock())
            assert reg.has("dev_key_3")
            await reg.unregister("dev_key_3")
            assert not reg.has("dev_key_3")
        finally:
            unsubscribe(s1)
            unsubscribe(s2)


# ============================================================
# exec 桥权限上下文（plugin_frontend.plugin_exec）
# ============================================================

class TestPluginExecContext:
    async def _run_exec(self, name, method, fn):
        """直接调用 plugin_exec 路由函数（mock 插件加载状态）"""
        from src.infrastructure.routes.plugin_frontend import plugin_exec, ExecRequest

        plugin_module = MagicMock()
        plugin_module.frontend_api = {method: fn}

        with patch("src.infrastructure.plugin_loader._loaded_tools", {name: MagicMock()}), \
             patch("src.infrastructure.plugin_loader.get_plugin_module", return_value=plugin_module), \
             patch("src.infrastructure.plugin_loader._plugin_meta",
                   {name: {"permissions": ["storage", "http"]}}):
            # pytest asyncio auto 模式下直接 await（必须在 patch 上下文内执行）
            return await plugin_exec(name, ExecRequest(method=method, args={}), user=MagicMock())

    async def test_exec_sets_plugin_context(self):
        """exec 调用期间 current_plugin() 应返回插件上下文（含 manifest 权限）"""
        from src.infrastructure.plugin_security import current_plugin

        seen = {}

        async def fake_api(**kwargs):
            ctx = current_plugin()
            seen["plugin"] = ctx.plugin if ctx else None
            seen["permissions"] = set(ctx.permissions) if ctx else None
            return {"ok": True}

        resp = await self._run_exec("my_plugin", "do_thing", fake_api)
        assert resp["code"] == 0
        assert seen["plugin"] == "my_plugin"
        assert seen["permissions"] == {"storage", "http"}

    async def test_exec_resets_context_after_call(self):
        """调用结束后上下文必须复位（finally）"""
        from src.infrastructure.plugin_security import current_plugin

        async def fake_api(**kwargs):
            return "ok"

        await self._run_exec("my_plugin", "do_thing", fake_api)
        assert current_plugin() is None

    async def test_exec_resets_context_on_exception(self):
        """插件方法抛异常时上下文同样被复位"""
        from src.infrastructure.plugin_security import current_plugin

        async def bad_api(**kwargs):
            raise PermissionError("未声明权限")

        with pytest.raises(PermissionError):
            await self._run_exec("my_plugin", "do_thing", bad_api)
        assert current_plugin() is None

    async def test_exec_denied_without_permission_declaration(self):
        """manifest 未声明权限时，require_permission 应在 exec 桥内生效（修复前静默放行）"""
        from src.infrastructure.plugin_security import require_permission

        async def guarded_api(**kwargs):
            require_permission("net", "http_get_json")
            return "should not reach"

        with pytest.raises(PermissionError):
            await self._run_exec("my_plugin", "guarded", guarded_api)


# ============================================================
# music 白名单拦截
# ============================================================

def _make_action_env(tool_allowed: bool, call_tool=None):
    """构造 _device_action("music") 所需的 mock 环境返回 (registry, tool_mgr)"""
    tool_mgr = MagicMock()
    tool_mgr._device_tool_allowed = MagicMock(return_value=tool_allowed)
    if call_tool is not None:
        tool_mgr.call_tool = call_tool
    else:
        tool_mgr.call_tool = AsyncMock(return_value="ok")

    d = {
        "fsm": MagicMock(get=MagicMock(return_value="IDLE")),
        "session": MagicMock(),
        "tool_manager": tool_mgr,
        "channel": MagicMock(),
    }
    registry = MagicMock()
    registry.resolve = MagicMock(return_value=d)
    return registry, tool_mgr


class TestDevicesMusicWhitelist:
    async def test_music_blocked_by_whitelist(self):
        """设备未启用音乐插件 → 返回「音乐插件未启用」，不调用任何插件能力"""
        from src.infrastructure.routes import devices as devices_mod

        registry, tool_mgr = _make_action_env(tool_allowed=False)

        with patch.object(devices_mod, "get_device_registry", return_value=registry), \
             patch.object(devices_mod, "get_speaker", return_value=MagicMock()), \
             patch("src.infrastructure.device_api.resolve_device_id", return_value=None):
            resp = await devices_mod._device_action("dev_key_x", "music", "")

        assert resp["code"] == 1
        assert "音乐插件未启用" in resp["message"]
        tool_mgr.call_tool.assert_not_awaited()

    async def test_music_allowed_uses_regular_tool_call(self):
        """白名单允许时走正规 call_tool('play_music')，StopPipeline 视为成功"""
        from src.infrastructure.routes import devices as devices_mod
        from src.use_cases.tools_system import StopPipeline
        from src.infrastructure.device_api import resolve_device_id

        async def _raise_stop(tool_name, args):
            assert tool_name == "play_music"
            assert args == {"song": "", "artist": ""}
            raise StopPipeline()

        registry, tool_mgr = _make_action_env(tool_allowed=True, call_tool=_raise_stop)

        with patch.object(devices_mod, "get_device_registry", return_value=registry), \
             patch.object(devices_mod, "get_speaker", return_value=MagicMock()), \
             patch("src.infrastructure.device_api.resolve_device_id", return_value=None):
            resp = await devices_mod._device_action("dev_key_x", "music", "")

        assert resp["code"] == 0
        assert "正在播放" in resp["message"]

    async def test_music_tool_failure_returns_error(self):
        """工具调用返回错误字符串（未配置/搜索失败）→ code 1"""
        from src.infrastructure.routes import devices as devices_mod
        from src.infrastructure.device_api import resolve_device_id

        registry, tool_mgr = _make_action_env(
            tool_allowed=True,
            call_tool=AsyncMock(return_value="音乐服务未配置，请在 App 插件商店中配置音乐服务地址"),
        )

        with patch.object(devices_mod, "get_device_registry", return_value=registry), \
             patch.object(devices_mod, "get_speaker", return_value=MagicMock()), \
             patch("src.infrastructure.device_api.resolve_device_id", return_value=None):
            resp = await devices_mod._device_action("dev_key_x", "music", "")

        assert resp["code"] == 1
        assert "音乐服务不可用" in resp["message"]


class TestWsMusicPlayNextWhitelist:
    """WS music_play_next 消息的白名单拦截"""

    def _make_ws_env(self, tool_allowed: bool, call_tool=None):
        """复用 test_ws_session_handler 的 handler 构造辅助"""
        from tests.test_ws_session_handler import _make_handler, _make_session

        handler = _make_handler()
        handler.session = _make_session()
        handler.fsm = MagicMock()
        handler.fsm.get.return_value = "IDLE"
        handler.channel = MagicMock()
        handler.channel.send_json = AsyncMock()

        tool_mgr = MagicMock()
        tool_mgr._device_tool_allowed = MagicMock(return_value=tool_allowed)
        if call_tool is not None:
            tool_mgr.call_tool = call_tool
        else:
            tool_mgr.call_tool = AsyncMock(return_value="ok")
        handler.tool_mgr = tool_mgr
        return handler, tool_mgr


    async def _run_with_music_play_next(self, handler):
        messages = [
            {"type": "websocket.receive", "text": json.dumps({"type": "music_play_next"})},
            {"type": "websocket.disconnect"},
        ]
        handler.websocket.receive = AsyncMock(side_effect=messages)
        await handler.run()
        # 等待 _play_next 后台任务执行完成
        for _ in range(20):
            await asyncio.sleep(0.01)

    async def test_blocked_sends_stop_music_without_plugin_call(self):
        """白名单拦截：只发 stop_music，不调用插件"""
        handler, tool_mgr = self._make_ws_env(tool_allowed=False)

        await self._run_with_music_play_next(handler)

        tool_mgr.call_tool.assert_not_awaited()
        handler.channel.send_json.assert_called_with({
            "type": "instruct",
            "command_id": "stop_music",
        })

    async def test_allowed_stop_pipeline_means_success(self):
        """白名单允许 + StopPipeline（音乐已发送）→ 不发 stop_music"""
        from src.use_cases.tools_system import StopPipeline

        call_tool = AsyncMock(side_effect=StopPipeline())
        handler, tool_mgr = self._make_ws_env(tool_allowed=True, call_tool=call_tool)

        await self._run_with_music_play_next(handler)

        tool_mgr.call_tool.assert_awaited_once()
        handler.channel.send_json.assert_not_called()

    async def test_tool_failure_sends_stop_music(self):
        """工具调用返回失败字符串 → 发 stop_music（与原 False 行为一致）"""
        handler, tool_mgr = self._make_ws_env(
            tool_allowed=True,
            call_tool=AsyncMock(return_value="随机推荐失败，音乐库可能为空"),
        )

        await self._run_with_music_play_next(handler)

        handler.channel.send_json.assert_called_with({
            "type": "instruct",
            "command_id": "stop_music",
        })
