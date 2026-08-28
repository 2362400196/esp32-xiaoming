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