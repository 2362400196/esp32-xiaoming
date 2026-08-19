import json

from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import (
    resolve_device_key,
    get_device_repository,
    request_device_result,
    send_device_command,
)

@tool()
async def read_device_config(key: str, tool_manager=None) -> str:
    """读取设备的某个配置项值。
    优先从服务器数据库读取，如果不存在则通过 Lua 从设备 NVS 读取。
    参数:
        key: 配置项名称，如 wifi_name、wifi_pwd、ssid(无线名称)、ext1(API Key)、ext2(音量)、ext4(协议)、ext5(地址)、ext6(端口)、
             asr_api_key、llm_api_key、tts_api_key 等
    """
    device_id = resolve_device_key(None, tool_manager)
    if not device_id:
        return "错误：无法获取设备ID"

    # 先尝试从服务器数据库读取
    repo = get_device_repository()
    db_value = None
    try:
        config = await repo.get_device_config(device_id)
        if config:
            parts = key.split(".")
            value = config
            for p in parts:
                if isinstance(value, dict):
                    value = value.get(p)
                else:
                    value = None
                    break
            if value is not None:
                if isinstance(value, (dict, list)):
                    import json
                    value = json.dumps(value, ensure_ascii=False)
                return f"{key} = {value}"
    except Exception:
        pass

    # 数据库没有，尝试从设备 NVS 读取
    lua_code = (f'local sys = require("system"); local v = sys.read_nvs("{key}"); '
                f'if v then print(v) else print("__NULL__") end')
    result, status, detail = await request_device_result(
        tool_manager, "execute_lua", "_pending_lua_future", timeout=8.0, data=lua_code,
    )
    if status != "ok":
        if status == "offline":
            return f"配置项 {key} 不存在（设备不在线）"
        if status == "timeout":
            return f"读取超时：设备未在 8 秒内响应"
        return f"从设备读取失败: {detail}"
    result = result.strip()
    if result and result != "__NULL__":
        return f"{key} = {result}"
    return f"配置项 {key} 不存在"


@tool()
async def write_device_config(key: str, value: str, tool_manager=None) -> str:
    """修改设备的某个配置项，会同步保存到服务器数据库并通过 WebSocket 下发到设备。
    参数:
        key: 配置项名称，如 wifi_name、wifi_pwd、ext1(API Key)、ext2(音量)、ext4(协议)、ext5(地址)、ext6(端口)、
             asr_api_key、llm_api_key、tts_api_key、volume 等
        value: 配置项的值（字符串）
    """
    device_id = resolve_device_key(None, tool_manager)
    if not device_id:
        return "错误：无法获取设备ID"

    # 1. 同步保存到服务器数据库
    repo = get_device_repository()
    try:
        await repo.update_device_partial(device_id, {key: value})
    except Exception as e:
        return f"保存到数据库失败: {e}"

    # 2. 下发 update_config 指令到设备
    err = await send_device_command(tool_manager, "update_config", {key: value})
    if err:
        return f"已保存到数据库，但下发到设备失败: {err}"
    return f"已更新: {key} = {value}（已保存到服务器并下发到设备）"


# ════════════════════════════════════════════════════════════
# 屏幕控制工具
# ════════════════════════════════════════════════════════════
