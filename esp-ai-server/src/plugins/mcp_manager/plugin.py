"""MCP 管理插件：MCP 服务器配置管理，添加、移除、启用、禁用。"""

from src.use_cases.tools_system import tool


@tool()
async def list_mcp_servers(device_mac: str, tool_manager=None) -> str:
    """列出设备配置的所有 MCP 服务器。
    参数:
        device_mac: 设备的 MAC 地址
    """
    from src.infrastructure.routes.mcp import _resolve_device
    from src.infrastructure.db.repositories.device_repository import DeviceRepository
    repo = DeviceRepository()
    try:
        device_id, config = await _resolve_device(device_mac)
        if not config:
            return f"设备 {device_mac} 未找到或未配置 MCP"
        servers = config.get("mcp_servers", {})
        disabled_servers = set(config.get("disabled_servers", []))
        if not servers:
            return f"设备 {device_mac} 没有配置 MCP 服务器"
        lines = []
        for name, info in servers.items():
            status = "（已禁用）" if name in disabled_servers else "（启用）"
            lines.append(f"· {name}{status}：{info.get('url', '')}")
        return f"设备 {device_mac} 的 MCP 服务器列表：\n" + "\n".join(lines)
    except Exception as e:
        return f"查询失败: {e}"


@tool()
async def add_mcp_server(
    device_mac: str,
    server_name: str,
    server_url: str,
    server_type: str = "stdio",
    tool_manager=None,
) -> str:
    """为设备添加一个 MCP 服务器。
    参数:
        device_mac: 设备的 MAC 地址
        server_name: 服务器名称，唯一标识
        server_url: 服务器 URL 或命令
        server_type: 服务器类型，stdio 或 sse
    """
    from src.infrastructure.routes.mcp import _resolve_device
    from src.infrastructure.db.repositories.device_repository import DeviceRepository
    repo = DeviceRepository()
    try:
        device_id, config = await _resolve_device(device_mac)
        if not device_id:
            return f"设备 {device_mac} 未找到"
        servers = config.get("mcp_servers", {})
        servers[server_name] = {"type": server_type, "url": server_url, "headers": {}, "auth": {}}
        # 更新配置
        await repo.update(device_id, {"mcp_servers": servers})
        return f"MCP 服务器「{server_name}」已添加到设备 {device_mac}"
    except Exception as e:
        return f"添加失败: {e}"


@tool()
async def remove_mcp_server(device_mac: str, server_name: str, tool_manager=None) -> str:
    """移除设备的 MCP 服务器配置。
    参数:
        device_mac: 设备的 MAC 地址
        server_name: 要移除的服务器名称
    """
    from src.infrastructure.routes.mcp import _resolve_device
    from src.infrastructure.db.repositories.device_repository import DeviceRepository
    repo = DeviceRepository()
    try:
        device_id, config = await _resolve_device(device_mac)
        if not device_id:
            return f"设备 {device_mac} 未找到"
        servers = config.get("mcp_servers", {})
        if server_name not in servers:
            return f"服务器 {server_name} 不存在"
        del servers[server_name]
        await repo.update(device_id, {"mcp_servers": servers})
        return f"MCP 服务器「{server_name}」已移除"
    except Exception as e:
        return f"移除失败: {e}"


@tool()
async def toggle_mcp_server(device_mac: str, server_name: str, disabled: bool = True, tool_manager=None) -> str:
    """启用或禁用设备的 MCP 服务器。
    参数:
        device_mac: 设备的 MAC 地址
        server_name: 服务器名称
        disabled: true 为禁用，false 为启用
    """
    from src.infrastructure.routes.mcp import _resolve_device
    from src.infrastructure.db.repositories.device_repository import DeviceRepository
    repo = DeviceRepository()
    try:
        device_id, config = await _resolve_device(device_mac)
        if not device_id:
            return f"设备 {device_mac} 未找到"
        disabled_servers = set(config.get("disabled_servers", []))
        if disabled:
            disabled_servers.add(server_name)
        else:
            disabled_servers.discard(server_name)
        await repo.update(device_id, {"disabled_servers": list(disabled_servers)})
        status = "已禁用" if disabled else "已启用"
        return f"MCP 服务器「{server_name}」{status}"
    except Exception as e:
        return f"操作失败: {e}"