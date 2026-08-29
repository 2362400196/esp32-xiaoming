"""SDK 设备通信 - 设备指令下发、状态查询"""

import asyncio

from src.infrastructure.plugin_security import require_permission
from src.use_cases.sdk.utils import get_device_key


async def send_instruct(channel, command_id, data="") -> None:
    """向设备通道发送一条 instruct 指令（不检查连接状态）。"""
    require_permission("device", f"下发设备指令 {command_id}")
    await channel.send_json({"type": "instruct", "command_id": command_id, "data": data})


def _discard_stale_future(tool_manager, future_attr: str) -> None:
    """主动失败旧的未完成回执 Future。

    单槽 pending future 被新指令覆盖时，旧等待方将永远收不到结果、
    只能干等到超时；这里在覆盖前主动给它一个失败结果，让旧调用立即返回。
    """
    old = getattr(tool_manager, future_attr, None)
    if old is not None and not old.done():
        try:
            old.set_result("[Error] 有更新的设备指令发出，本次结果已被丢弃")
        except Exception:
            pass
    setattr(tool_manager, future_attr, None)


async def send_device_command(tool_manager, command_id, data="") -> str | None:
    """向设备发送一条 instruct 指令。

    Returns:
        None 表示发送成功；字符串表示失败原因。
    """
    if not tool_manager or not tool_manager.channel:
        return "设备未连接"
    try:
        await send_instruct(tool_manager.channel, command_id, data)
        return None
    except PermissionError:
        return "设备指令权限未声明"
    except Exception as e:
        return f"发送失败: {e}"


async def send_device_command_ack(tool_manager, command_id, data="", timeout=8.0) -> tuple:
    """下发设备指令并等待设备 ack 确认。

    Returns:
        (result, status, detail)：status="ok"/"offline"/"timeout"/"error"
    """
    if not tool_manager or not tool_manager.channel:
        return None, "offline", "设备未连接"
    loop = asyncio.get_running_loop()
    _discard_stale_future(tool_manager, "_pending_command_ack_future")
    future = loop.create_future()
    tool_manager._pending_command_ack_future = future
    try:
        await send_instruct(tool_manager.channel, command_id, data)
    except PermissionError as e:
        tool_manager._pending_command_ack_future = None
        return None, "error", str(e)
    except Exception as e:
        tool_manager._pending_command_ack_future = None
        return None, "error", f"发送失败: {e}"
    try:
        result = await asyncio.wait_for(future, timeout=timeout)
        return result, "ok", ""
    except asyncio.TimeoutError:
        return None, "timeout", f"设备未在 {timeout} 秒内确认指令 {command_id}"
    finally:
        tool_manager._pending_command_ack_future = None


async def request_device_result(tool_manager, command_id, future_attr, timeout=8.0, data="", if_busy=None):
    """下发设备指令并等待设备通过 future 回复结果。

    .. deprecated::
        旧 API，要求调用方理解框架 Future 槽位（future_attr 私有属性名），
        保留兼容既有插件。新插件推荐使用高层封装：
        :func:`lua_execute` / :func:`get_device_state` / :func:`device_command_ack`。

    Returns:
        (result, status, detail)：status="ok"/"offline"/"timeout"/"error"/"busy"
    """
    if not tool_manager or not tool_manager.channel:
        return None, "offline", "设备未连接"
    require_permission("device", f"下发设备指令 {command_id} 并等待结果")
    if if_busy is not None:
        busy_future = getattr(tool_manager, future_attr, None)
        if busy_future is not None and not busy_future.done():
            return None, "busy", if_busy
    loop = asyncio.get_running_loop()
    _discard_stale_future(tool_manager, future_attr)
    future = loop.create_future()
    setattr(tool_manager, future_attr, future)
    try:
        await send_instruct(tool_manager.channel, command_id, data)
    except Exception as e:
        setattr(tool_manager, future_attr, None)
        return None, "error", f"发送失败: {e}"
    try:
        result = await asyncio.wait_for(future, timeout=timeout)
        return result, "ok", ""
    except asyncio.TimeoutError:
        return None, "timeout", f"设备未在 {timeout} 秒内响应"
    finally:
        setattr(tool_manager, future_attr, None)


# ══════════════════════════════════════════════════════════════
# 高层封装（推荐）：插件无需理解框架 Future 槽位等私有机制
# ══════════════════════════════════════════════════════════════


async def lua_execute(tool_manager, code: str, timeout=8.0) -> tuple:
    """在设备 Lua 引擎上执行脚本并等待执行结果（推荐封装）。

    内部封装 request_device_result(execute_lua + "_pending_lua_future")，
    插件无需传入框架私有属性名。

    Args:
        tool_manager: 自动传入
        code: Lua 脚本代码
        timeout: 等待设备响应的超时秒数

    Returns:
        (result, status, detail)：status="ok"/"offline"/"timeout"/"error"/"busy"
    """
    return await request_device_result(
        tool_manager, "execute_lua", "_pending_lua_future",
        timeout=timeout, data=code,
    )


async def get_device_state(tool_manager, command_id: str, timeout=5.0) -> tuple:
    """下发设备状态查询指令并等待设备回复（推荐封装）。

    内部封装 request_device_result(command_id + "_pending_device_state_future")，
    使用独立的 Future 槽位，避免与 execute_lua 的 future 冲突。

    Args:
        tool_manager: 自动传入
        command_id: 状态查询指令名（如 "get_volume" / "get_brightness"）
        timeout: 等待设备响应的超时秒数

    Returns:
        (result, status, detail)：status="ok"/"offline"/"timeout"/"error"/"busy"
    """
    return await request_device_result(
        tool_manager, command_id, "_pending_device_state_future",
        timeout=timeout,
    )


async def device_command_ack(tool_manager, command_id: str, data="", timeout=8.0) -> tuple:
    """下发设备指令并等待设备 ack 确认（推荐封装）。

    内部封装 request_device_result(command_id + "_pending_command_ack_future")。

    Args:
        tool_manager: 自动传入
        command_id: 指令名
        data: 指令附带数据
        timeout: 等待设备确认的超时秒数

    Returns:
        (result, status, detail)：status="ok"/"offline"/"timeout"/"error"/"busy"
    """
    return await request_device_result(
        tool_manager, command_id, "_pending_command_ack_future",
        timeout=timeout, data=data,
    )


def device_is_online(device_key: str = "", tool_manager=None) -> bool:
    """检查设备是否在线。

    Args:
        device_key: 设备标识（bound_xxx 格式），为空时自动推断
        tool_manager: 自动传入

    Returns:
        True 表示设备在线
    """
    require_permission("device", "查询设备在线状态")
    if not device_key and tool_manager:
        device_key = get_device_key(tool_manager)
    if not device_key:
        return False
    from src.infrastructure.device_api import get_device_registry
    registry = get_device_registry()
    if not registry:
        return False
    return registry.has(device_key)


async def device_get_info(device_key: str = "", tool_manager=None) -> dict:
    """获取设备信息。

    Args:
        device_key: 设备标识，为空时自动推断
        tool_manager: 自动传入

    Returns:
        dict 包含设备信息，设备不在线时返回空 dict
    """
    require_permission("device", "查询设备信息")
    if not device_key and tool_manager:
        device_key = get_device_key(tool_manager)
    if not device_key:
        return {}
    from src.infrastructure.device_api import get_device_registry
    registry = get_device_registry()
    if not registry:
        return {}
    device = registry.get(device_key)
    if not device:
        return {}
    return {
        "device_key": device_key,
        "mac": device.get("mac", ""),
        "firmware_version": device.get("firmware_version", ""),
        "register_time": device.get("register_time", 0),
        "ota_updating": device.get("ota_updating", False),
        "ota_progress": device.get("ota_progress", 0.0),
    }