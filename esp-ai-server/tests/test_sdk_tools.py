"""SDK tools / device 高层封装 / speak_to_device 测试。

覆盖：
1. sdk.tools 导出的 tool / StopPipeline / ToolDefinition 与 tools_system 是同一对象
   （单一实现源，不做复制）。
2. sdk.device 三个高层封装（lua_execute / get_device_state / device_command_ack）
   正确透传参数给 request_device_result（插件无需理解框架 Future 槽位）。
3. sdk.infrastructure.speak_to_device：设备离线返回 False；
   设备在线时正确解析 channel/session/fsm 并调用 speaker.speak_direct。

注意：不要使用 `from __future__ import annotations`，否则 @tool 装饰器
无法通过真实注解对象推断参数类型。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.use_cases import tools_system
from src.use_cases.sdk import tools as sdk_tools
from src.use_cases.sdk.device import (
    device_command_ack,
    get_device_state,
    lua_execute,
    request_device_result,
)


# ════════════════════════════════════════════════════════════
# 任务1：sdk.tools 与 tools_system 同源
# ════════════════════════════════════════════════════════════

class TestSdkToolsReexport:
    def test_tool_is_same_object(self):
        """sdk.tools.tool 必须就是 tools_system.tool（同一对象，非复制）。"""
        assert sdk_tools.tool is tools_system.tool

    def test_stop_pipeline_is_same_object(self):
        """sdk.tools.StopPipeline 必须就是 tools_system.StopPipeline。"""
        assert sdk_tools.StopPipeline is tools_system.StopPipeline

    def test_tool_definition_is_same_object(self):
        assert sdk_tools.ToolDefinition is tools_system.ToolDefinition

    def test_plugin_helpers_reexports_too(self):
        """旧导入路径 _plugin_helpers 也同步导出这两个名字。"""
        from src.use_cases import _plugin_helpers
        assert _plugin_helpers.tool is tools_system.tool
        assert _plugin_helpers.StopPipeline is tools_system.StopPipeline

    def test_tool_decorator_registers_via_sdk(self):
        """通过 sdk.tools 的 @tool 装饰器注册后，工具进入 tools_system 全局注册表。"""
        tool_name = "__sdk_tools_test_unique_tool__"
        try:
            @sdk_tools.tool(name=tool_name, description="SDK 注册测试")
            async def my_tool(city: str, tool_manager=None) -> str:
                return city

            registered = tools_system._registry.get(tool_name)
            assert registered is not None
            assert registered.func is my_tool
            assert registered.description == "SDK 注册测试"
            # 参数 schema 推断正常（city 为必填 string）
            assert registered.parameters["properties"]["city"] == {"type": "string"}
            assert registered.parameters["required"] == ["city"]
        finally:
            # 清理，避免污染其他测试的全局注册表
            tools_system._registry.pop(tool_name, None)


# ════════════════════════════════════════════════════════════
# 任务2：device 高层封装参数传递
# ════════════════════════════════════════════════════════════

def _make_tool_manager():
    """构造带 channel 的 mock tool_manager。"""
    tm = MagicMock()
    tm.channel = MagicMock()
    return tm


class TestDeviceHighLevelWrappers:
    @pytest.mark.asyncio
    async def test_lua_execute_passes_lua_future_attr(self):
        """lua_execute 固定使用 execute_lua + _pending_lua_future。"""
        tm = _make_tool_manager()
        expected = ("print('hi')", "ok", "")
        with patch(
            "src.use_cases.sdk.device.request_device_result", new_callable=AsyncMock
        ) as mock_req:
            mock_req.return_value = expected
            result = await lua_execute(tm, "print('hi')", timeout=3.0)

        assert result == expected
        mock_req.assert_awaited_once_with(
            tm, "execute_lua", "_pending_lua_future",
            timeout=3.0, data="print('hi')",
        )

    @pytest.mark.asyncio
    async def test_lua_execute_default_timeout(self):
        tm = _make_tool_manager()
        with patch(
            "src.use_cases.sdk.device.request_device_result", new_callable=AsyncMock
        ) as mock_req:
            mock_req.return_value = (None, "timeout", "超时")
            result = await lua_execute(tm, "code")

        assert result == (None, "timeout", "超时")
        assert mock_req.await_args.kwargs["timeout"] == 8.0

    @pytest.mark.asyncio
    async def test_get_device_state_passes_state_future_attr(self):
        """get_device_state 固定使用 _pending_device_state_future，不带 data。"""
        tm = _make_tool_manager()
        with patch(
            "src.use_cases.sdk.device.request_device_result", new_callable=AsyncMock
        ) as mock_req:
            mock_req.return_value = ("volume=80", "ok", "")
            result = await get_device_state(tm, "get_volume", timeout=2.5)

        assert result == ("volume=80", "ok", "")
        mock_req.assert_awaited_once_with(
            tm, "get_volume", "_pending_device_state_future", timeout=2.5,
        )

    @pytest.mark.asyncio
    async def test_device_command_ack_passes_ack_future_attr(self):
        """device_command_ack 固定使用 _pending_command_ack_future，透传 data。"""
        tm = _make_tool_manager()
        with patch(
            "src.use_cases.sdk.device.request_device_result", new_callable=AsyncMock
        ) as mock_req:
            mock_req.return_value = ("ack", "ok", "")
            result = await device_command_ack(tm, "reboot", data="now", timeout=1.0)

        assert result == ("ack", "ok", "")
        mock_req.assert_awaited_once_with(
            tm, "reboot", "_pending_command_ack_future",
            timeout=1.0, data="now",
        )

    @pytest.mark.asyncio
    async def test_lua_execute_real_passthrough_offline(self):
        """不 mock 底层：离线 tool_manager 时走真实 request_device_result 返回 offline。"""
        tm = MagicMock()
        tm.channel = None  # 未连接设备
        result, status, detail = await lua_execute(tm, "print('x')")
        assert result is None
        assert status == "offline"
        assert detail == "设备未连接"

    @pytest.mark.asyncio
    async def test_old_api_request_device_result_still_works(self):
        """旧 API request_device_result 保持可用（兼容既有插件）。"""
        tm = MagicMock()
        tm.channel = None
        result, status, _ = await request_device_result(
            tm, "execute_lua", "_pending_lua_future",
        )
        assert status == "offline"


# ════════════════════════════════════════════════════════════
# 任务3：speak_to_device 高层主动播报
# ════════════════════════════════════════════════════════════

class TestSpeakToDevice:
    @pytest.mark.asyncio
    async def test_offline_returns_false(self):
        """设备不在注册表 → 返回 False。"""
        registry = MagicMock()
        registry.resolve.return_value = None
        with patch(
            "src.use_cases.sdk.infrastructure.get_device_registry", return_value=registry
        ):
            from src.use_cases.sdk.infrastructure import speak_to_device
            assert await speak_to_device("bound_none", "你好") is False

    @pytest.mark.asyncio
    async def test_registry_unavailable_returns_false(self):
        with patch(
            "src.use_cases.sdk.infrastructure.get_device_registry", return_value=None
        ):
            from src.use_cases.sdk.infrastructure import speak_to_device
            assert await speak_to_device("bound_x", "你好") is False

    @pytest.mark.asyncio
    async def test_channel_none_returns_false(self):
        """设备条目存在但 channel 为 None（离线）→ 返回 False。"""
        registry = MagicMock()
        registry.resolve.return_value = {"channel": None, "session": None, "fsm": None}
        with patch(
            "src.use_cases.sdk.infrastructure.get_device_registry", return_value=registry
        ):
            from src.use_cases.sdk.infrastructure import speak_to_device
            assert await speak_to_device("bound_x", "你好") is False

    @pytest.mark.asyncio
    async def test_empty_args_return_false(self):
        from src.use_cases.sdk.infrastructure import speak_to_device
        assert await speak_to_device("", "你好") is False
        assert await speak_to_device("bound_x", "") is False

    @pytest.mark.asyncio
    async def test_online_speaks_via_speaker(self):
        """设备在线 → 解析 channel/session/fsm/user_config 并调 speaker.speak_direct。"""
        channel = MagicMock()
        channel.connected = True
        session, fsm, user_config = MagicMock(), MagicMock(), MagicMock()
        device = {
            "channel": channel,
            "session": session,
            "fsm": fsm,
            "user_config": user_config,
        }
        registry = MagicMock()
        registry.resolve.return_value = device

        speaker = MagicMock()
        speaker.speak_direct = AsyncMock(return_value=None)
        app = MagicMock()
        app.state.speaker = speaker

        with patch(
            "src.use_cases.sdk.infrastructure.get_device_registry", return_value=registry
        ), patch(
            "src.infrastructure.web.get_app", return_value=app
        ):
            from src.use_cases.sdk.infrastructure import speak_to_device
            ok = await speak_to_device("bound_x", "该喝水了")

        assert ok is True
        # speak_direct(channel, session, fsm, text, user_config=...)
        speaker.speak_direct.assert_awaited_once_with(
            channel, session, fsm, "该喝水了", user_config=user_config,
        )

    @pytest.mark.asyncio
    async def test_speaker_exception_returns_false(self):
        """speaker 播报抛异常时吞掉并返回 False（不让插件崩溃）。"""
        channel = MagicMock()
        channel.connected = True
        registry = MagicMock()
        registry.resolve.return_value = {"channel": channel, "session": None, "fsm": None}

        speaker = MagicMock()
        speaker.speak_direct = AsyncMock(side_effect=RuntimeError("boom"))
        app = MagicMock()
        app.state.speaker = speaker

        with patch(
            "src.use_cases.sdk.infrastructure.get_device_registry", return_value=registry
        ), patch(
            "src.infrastructure.web.get_app", return_value=app
        ):
            from src.use_cases.sdk.infrastructure import speak_to_device
            assert await speak_to_device("bound_x", "你好") is False
