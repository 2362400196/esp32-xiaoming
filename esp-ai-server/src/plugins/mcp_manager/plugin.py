"""MCP 管理插件：MCP 服务器配置管理，添加、移除、启用、禁用。

前端 API（通过 exec 桥梁调用）：
  - get_servers(mac) → list
  - update_server(mac, server_name, type, url, headers, auth) → dict
  - delete_server(mac, server_name) → dict
  - get_tools(mac, server_name) → list
  - get_all_tools(mac) → list
  - toggle_server(mac, server_name, disabled) → dict
  - toggle_tool(mac, server_name, tool_name, disabled) → dict
  - get_disabled(mac) → dict
"""

from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import resolve_device_key

# ============================================================
# SDK 方法
# ============================================================

def _get_repo():
    from src.infrastructure.db.repositories.device_repository import DeviceRepository
    return DeviceRepository()


def _hot_reload(mac: str):
    try:
        from src.infrastructure.web import _hot_reload_device_config
        _hot_reload_device_config(mac, force=True)
    except Exception:
        pass


async def _resolve_device(mac: str):
    repo = _get_repo()
    return await repo.resolve_device(mac)


async def _get_mcp_tools(mac: str, server_name: str) -> list:
    """获取某个 MCP 服务器的工具列表。"""
    from src.use_cases.tools_system import MCPClient
    repo = _get_repo()
    mcp_servers = await repo.get_mcp_servers(mac)
    cfg = mcp_servers.get(server_name)
    if not cfg:
        return []
    client = MCPClient(
        cfg.get("url", ""),
        name=server_name,
        headers=cfg.get("headers") or None,
        auth=cfg.get("auth") or None,
    )
    try:
        await client.connect()
        schemas = client.get_tools_schema()
    finally:
        await client.disconnect()
    return [
        {"name": s.get("function", {}).get("name", ""), "description": s.get("function", {}).get("description", "")}
        for s in schemas
    ]


async def _get_all_tools(mac: str) -> list:
    """获取设备所有工具（内置 + MCP）。"""
    from src.use_cases.tools_system import get_openai_tools_schema, MCPClient
    seen = set()
    result = []
    for t in get_openai_tools_schema():
        fn = t.get("function", {})
        name = fn.get("name", "")
        if name and name not in seen:
            seen.add(name)
            result.append({"type": "global", "name": name, "description": fn.get("description", "")})
    repo = _get_repo()
    for server_name, cfg in ((await repo.get_mcp_servers(mac)) or {}).items():
        url = cfg.get("url", "")
        if not url:
            continue
        client = MCPClient(url, name=server_name, headers=cfg.get("headers") or None, auth=cfg.get("auth") or None)
        try:
            await client.connect()
            for s in client.get_tools_schema():
                fn = s.get("function", {})
                name = fn.get("name", "")
                if name and name not in seen:
                    seen.add(name)
                    result.append({"type": "mcp", "name": name, "description": fn.get("description", "")})
        except Exception:
            pass
        finally:
            await client.disconnect()
    return result


# ============================================================
# 前端 API（通过 exec 桥梁调用）
# ============================================================

async def _api_get_servers(mac: str) -> list:
    device_id, _ = await _resolve_device(mac)
    if not device_id:
        raise ValueError(f"设备不存在: {mac}")
    repo = _get_repo()
    return await repo.get_mcp_servers(mac)


async def _api_update_server(mac: str, server_name: str, type: str = "streamable_http",
                              url: str = "", headers: dict = None, auth: dict = None) -> dict:
    device_id, config = await _resolve_device(mac)
    if not device_id:
        raise ValueError(f"设备不存在: {mac}")
    server_cfg = {"type": type, "url": url}
    if headers:
        server_cfg["headers"] = headers
    if auth:
        server_cfg["auth"] = auth
    repo = _get_repo()
    await repo.set_mcp_server(device_id, server_name, server_cfg)
    await repo.mcp_enabled_plugins_add(device_id, server_name)
    _hot_reload(mac)
    return server_cfg


async def _api_delete_server(mac: str, server_name: str) -> dict:
    device_id, config = await _resolve_device(mac)
    if not device_id:
        raise ValueError(f"设备不存在: {mac}")
    mcp_servers = (config or {}).get("mcp_servers", {}) or {}
    if server_name not in mcp_servers:
        raise ValueError(f"MCP 服务器不存在: {server_name}")
    repo = _get_repo()
    await repo.delete_mcp_server(device_id, server_name)
    await repo.mcp_enabled_plugins_remove(device_id, server_name)
    _hot_reload(mac)
    return {"deleted": server_name}


async def _api_get_tools(mac: str, server_name: str) -> list:
    device_id, _ = await _resolve_device(mac)
    if not device_id:
        raise ValueError(f"设备不存在: {mac}")
    return await _get_mcp_tools(mac, server_name)


async def _api_get_all_tools(mac: str) -> list:
    device_id, _ = await _resolve_device(mac)
    if not device_id:
        raise ValueError(f"设备不存在: {mac}")
    return await _get_all_tools(mac)


async def _api_toggle_server(mac: str, server_name: str, disabled: bool = True) -> dict:
    device_id, _ = await _resolve_device(mac)
    if not device_id:
        raise ValueError(f"设备不存在: {mac}")
    repo = _get_repo()
    await repo.toggle_mcp_server(device_id, server_name, disabled)
    _hot_reload(mac)
    return {"disabled": disabled}


async def _api_toggle_tool(mac: str, server_name: str, tool_name: str, disabled: bool = True) -> dict:
    device_id, _ = await _resolve_device(mac)
    if not device_id:
        raise ValueError(f"设备不存在: {mac}")
    repo = _get_repo()
    await repo.toggle_mcp_tool(device_id, server_name, tool_name, disabled)
    _hot_reload(mac)
    return {"disabled": disabled}


async def _api_get_disabled(mac: str) -> dict:
    device_id, _ = await _resolve_device(mac)
    if not device_id:
        raise ValueError(f"设备不存在: {mac}")
    repo = _get_repo()
    return await repo.get_disabled_mcp(device_id)


frontend_api = {
    "get_servers": _api_get_servers,
    "update_server": _api_update_server,
    "delete_server": _api_delete_server,
    "get_tools": _api_get_tools,
    "get_all_tools": _api_get_all_tools,
    "toggle_server": _api_toggle_server,
    "toggle_tool": _api_toggle_tool,
    "get_disabled": _api_get_disabled,
}


# ============================================================
# AI 工具（LLM 调用）
# ============================================================

@tool()
async def list_mcp_servers(device_mac: str, tool_manager=None) -> str:
    """列出设备配置的所有 MCP 服务器。
    参数:
        device_mac: 设备的 MAC 地址
    """
    try:
        servers = await _api_get_servers(device_mac)
        if not servers:
            return f"设备 {device_mac} 没有配置 MCP 服务器"
        disabled = await _api_get_disabled(device_mac)
        ds = set(disabled.get("disabled_servers", []))
        lines = []
        for name, info in servers.items():
            status = "（已禁用）" if name in ds else "（启用）"
            lines.append(f"· {name}{status}：{info.get('url', '')}")
        return f"设备 {device_mac} 的 MCP 服务器列表：\n" + "\n".join(lines)
    except Exception as e:
        return f"查询失败: {e}"


@tool()
async def add_mcp_server(
    device_mac: str,
    server_name: str,
    server_url: str,
    server_type: str = "streamable_http",
    tool_manager=None,
) -> str:
    """为设备添加一个 MCP 服务器。
    参数:
        device_mac: 设备的 MAC 地址
        server_name: 服务器名称，唯一标识
        server_url: 服务器 URL
        server_type: 服务器类型，如 streamable_http
    """
    try:
        await _api_update_server(device_mac, server_name, server_type, server_url)
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
    try:
        await _api_delete_server(device_mac, server_name)
        return f"MCP 服务器「{server_name}」已移除"
    except Exception as e:
        return f"移除失败: {e}"


@tool()
async def toggle_mcp_server_status(device_mac: str, server_name: str, disabled: bool = True, tool_manager=None) -> str:
    """启用或禁用设备的 MCP 服务器。
    参数:
        device_mac: 设备的 MAC 地址
        server_name: 服务器名称
        disabled: true 为禁用，false 为启用
    """
    try:
        await _api_toggle_server(device_mac, server_name, disabled)
        status = "已禁用" if disabled else "已启用"
        return f"MCP 服务器「{server_name}」{status}"
    except Exception as e:
        return f"操作失败: {e}"