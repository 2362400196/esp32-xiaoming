"""远程配置插件：查询设备远程配置、上报状态、管理缓存。"""

from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import get_device_key


@tool()
async def get_device_remote_config(device_key: str = "", tool_manager=None) -> str:
    """获取设备的远程配置信息。
    参数:
        device_key: 设备标识，不传则自动使用当前设备
    """
    from src.infrastructure.remote_config import get_remote_config_provider
    if not device_key:
        device_key = get_device_key(tool_manager)
    if not device_key:
        return "未获取到设备信息"
    provider = get_remote_config_provider()
    config = await provider.get_device_config(device_key)
    if config:
        import json
        return f"设备远程配置：\n{json.dumps(config, ensure_ascii=False, indent=2)}"
    return "该设备没有远程配置，或远程配置服务未连接"


@tool()
async def report_device_status_to_remote(
    status: str,
    metadata: str = "{}",
    device_key: str = "",
    tool_manager=None,
) -> str:
    """上报设备状态到远程管理后台。
    参数:
        status: 设备状态，如 online/offline/error
        metadata: 附加信息，JSON 格式
        device_key: 设备标识，不传则自动使用当前设备
    """
    from src.infrastructure.remote_config import get_remote_config_provider
    import json
    if not device_key:
        device_key = get_device_key(tool_manager)
    if not device_key:
        return "未获取到设备信息"
    try:
        meta = json.loads(metadata) if metadata else {}
    except json.JSONDecodeError:
        meta = {}
    provider = get_remote_config_provider()
    ok = await provider.report_device_status(device_key, status, meta)
    return "状态已上报" if ok else "上报失败，远程配置服务未连接"


@tool()
async def clear_remote_config_cache(tool_manager=None) -> str:
    """清空远程配置的本地缓存，下次查询将重新拉取。"""
    from src.infrastructure.remote_config import get_remote_config_provider
    provider = get_remote_config_provider()
    await provider.clear_cache()
    return "远程配置缓存已清空"