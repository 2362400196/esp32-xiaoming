"""MCP 路由

设备的 MCP 服务器配置管理、工具查询、启停等路由。

阶段 3：数据源从 users.json 切换到 DB（DeviceRepository）。
认证方式：JWT 用户认证 + 设备归属校验。
"""
from __future__ import annotations

import json
import os

from fastapi import Depends, APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.infrastructure.logging import get_logger
from src.infrastructure.security_jwt import get_current_user
from src.infrastructure.db.models.user import UserModel
from src.infrastructure.db.models.device import DeviceModel
from src.infrastructure.db.session import get_session_ctx
from src.infrastructure.web import _hot_reload_device_config

logger = get_logger(__name__)

router = APIRouter(tags=["mcp"])


class MCPServerConfig(BaseModel):
    type: str = "streamable_http"
    url: str = Field(max_length=2048)
    headers: dict = {}
    auth: dict = {}


def _get_repo():
    """延迟导入 DeviceRepository，避免循环引用。"""
    from src.infrastructure.db.repositories.device_repository import DeviceRepository
    return DeviceRepository()


async def _resolve_device(mac: str):
    """从 DB 解析设备，返回 (device_id, config_dict) 或 (None, None)。

    依次按 mac_address / device_id(PK) / device_key 查找。
    """
    try:
        repo = _get_repo()
        found = await repo.find_by_mac(mac)
        if found is None:
            found = await repo.find_by_key(mac)
        if found is None:
            return None, None
        return found
    except Exception as e:
        logger.warning(f"[MCP] DB 解析设备失败: {e}")
        return None, None


async def _check_device_owner(device_id: str, user: UserModel) -> bool:
    """校验设备归属当前用户（兼容 mac_address / device_id / device_key 查找）"""
    from sqlalchemy import or_
    async with get_session_ctx() as session:
        result = await session.execute(
            select(DeviceModel).where(
                or_(
                    DeviceModel.device_id == device_id,
                    DeviceModel.mac_address == device_id,
                    DeviceModel.device_key == device_id,
                ),
                DeviceModel.user_id == user.id,
            )
        )
        return result.scalar_one_or_none() is not None


# ============================================================
#  MCP 配置管理 API（JWT 用户认证 + 设备归属校验）
# ============================================================


@router.get("/api/v1/devices/{mac}/mcp")
async def get_device_mcp(mac: str, user: UserModel = Depends(get_current_user)):
    """获取设备的 MCP 服务器配置"""
    if not await _check_device_owner(mac, user):
        from fastapi import HTTPException
        raise HTTPException(403, "Device not bound to you")
    try:
        repo = _get_repo()
        mcp_servers = await repo.get_mcp_servers(mac)
        if not mcp_servers:
            # 区分"设备不存在"和"设备存在但无 MCP 配置"
            device_id, config = await _resolve_device(mac)
            if device_id is None:
                return {"code": 1, "message": f"设备不存在: {mac}", "data": None}
        return {"code": 0, "message": "ok", "data": mcp_servers or {}}
    except Exception as e:
        return {"code": 1, "message": str(e), "data": None}


@router.put("/api/v1/devices/{mac}/mcp/{server_name}")
async def update_device_mcp(mac: str, server_name: str, body: MCPServerConfig, user: UserModel = Depends(get_current_user)):
    """添加或更新设备的 MCP 服务器配置"""
    if not await _check_device_owner(mac, user):
        from fastapi import HTTPException
        raise HTTPException(403, "Device not bound to you")
    try:
        device_id, _config = await _resolve_device(mac)
        if device_id is None:
            return {"code": 1, "message": f"设备不存在: {mac}", "data": None}

        server_cfg = {"type": body.type, "url": body.url}
        if body.headers:
            server_cfg["headers"] = body.headers
        if body.auth:
            server_cfg["auth"] = body.auth

        repo = _get_repo()
        await repo.set_mcp_server(device_id, server_name, server_cfg)
        _hot_reload_device_config(mac)
        return {"code": 0, "message": "ok", "data": server_cfg}
    except Exception as e:
        return {"code": 1, "message": f"更新失败: {e}", "data": None}


@router.delete("/api/v1/devices/{mac}/mcp/{server_name}")
async def delete_device_mcp(mac: str, server_name: str, user: UserModel = Depends(get_current_user)):
    """删除设备的 MCP 服务器配置"""
    if not await _check_device_owner(mac, user):
        from fastapi import HTTPException
        raise HTTPException(403, "Device not bound to you")
    try:
        device_id, config = await _resolve_device(mac)
        if device_id is None:
            return {"code": 1, "message": f"设备不存在: {mac}", "data": None}

        mcp_servers = (config or {}).get("mcp_servers", {}) or {}
        if server_name not in mcp_servers:
            return {"code": 1, "message": f"MCP 服务器不存在: {server_name}", "data": None}

        repo = _get_repo()
        await repo.delete_mcp_server(device_id, server_name)
        _hot_reload_device_config(mac)
        return {"code": 0, "message": "ok", "data": {"deleted": server_name}}
    except Exception as e:
        return {"code": 1, "message": f"删除失败: {e}", "data": None}


@router.get("/api/v1/devices/{mac}/mcp/{server_name}/tools")
async def get_device_mcp_tools(mac: str, server_name: str, user: UserModel = Depends(get_current_user)):
    """获取设备某个 MCP 服务器的工具列表"""
    if not await _check_device_owner(mac, user):
        from fastapi import HTTPException
        raise HTTPException(403, "Device not bound to you")
    try:
        from src.use_cases.tools_system import MCPClient
        repo = _get_repo()
        mcp_servers = await repo.get_mcp_servers(mac)
        if not mcp_servers:
            device_id, _ = await _resolve_device(mac)
            if device_id is None:
                return {"code": 1, "message": f"设备不存在: {mac}", "data": None}
        if server_name not in mcp_servers:
            return {"code": 1, "message": f"MCP 服务器不存在: {server_name}", "data": None}
        cfg = mcp_servers[server_name]
        url = cfg.get("url", "")
        if not url:
            return {"code": 1, "message": "MCP 服务器 URL 为空", "data": None}
        headers = cfg.get("headers") or None
        auth = cfg.get("auth") or None
        client = MCPClient(url, name=server_name, headers=headers, auth=auth)
        try:
            await client.connect()
            schemas = client.get_tools_schema()
        finally:
            await client.disconnect()
        tools = []
        for s in schemas:
            fn = s.get("function", {})
            tools.append({"name": fn.get("name", ""), "description": fn.get("description", "")})
        return {"code": 0, "message": "ok", "data": tools}
    except Exception as e:
        logger.error(f"获取 MCP 工具列表失败: {e}")
        return {"code": 1, "message": f"获取工具列表失败: {e}", "data": None}


@router.get("/api/v1/devices/{mac}/tools")
async def get_device_all_tools(mac: str, user: UserModel = Depends(get_current_user)):
    """获取设备所有工具（内置 + 该设备的 MCP 工具）"""
    if not await _check_device_owner(mac, user):
        from fastapi import HTTPException
        raise HTTPException(403, "Device not bound to you")
    try:
        from src.use_cases.tools_system import get_openai_tools_schema, MCPClient
        seen = set()
        result = []

        # 内置工具
        for t in get_openai_tools_schema():
            fn = t.get("function", {})
            name = fn.get("name", "")
            if name and name not in seen:
                seen.add(name)
                result.append({"type": "global", "name": name, "description": fn.get("description", "")})

        # 设备 MCP 工具
        repo = _get_repo()
        mcp_servers = await repo.get_mcp_servers(mac)
        for server_name, cfg in (mcp_servers or {}).items():
            url = cfg.get("url", "")
            if not url:
                continue
            headers = cfg.get("headers") or None
            auth = cfg.get("auth") or None
            client = MCPClient(url, name=server_name, headers=headers, auth=auth)
            try:
                await client.connect()
                schemas = client.get_tools_schema()
                for s in schemas:
                    fn = s.get("function", {})
                    name = fn.get("name", "")
                    if name and name not in seen:
                        seen.add(name)
                        result.append({"type": "mcp", "name": name, "description": fn.get("description", "")})
            except Exception as e:
                logger.warning(f"MCP 服务器 {server_name} 获取工具失败: {e}")
            finally:
                await client.disconnect()

        return {"code": 0, "message": "ok", "data": result}
    except Exception as e:
        logger.error(f"获取设备工具列表失败: {e}")
        return {"code": 1, "message": f"获取工具列表失败: {e}", "data": None}


@router.post("/api/v1/devices/{mac}/mcp/{server_name}/toggle")
async def toggle_mcp_server(mac: str, server_name: str, disabled: bool = True, user: UserModel = Depends(get_current_user)):
    """禁用或启用整个 MCP 服务器"""
    if not await _check_device_owner(mac, user):
        from fastapi import HTTPException
        raise HTTPException(403, "Device not bound to you")
    try:
        device_id, config = await _resolve_device(mac)
        if device_id is None:
            return {"code": 1, "message": f"设备不存在: {mac}", "data": None}

        ds = list((config or {}).get("disabled_mcp_servers", []) or [])
        if disabled:
            if server_name not in ds:
                ds.append(server_name)
        else:
            ds = [s for s in ds if s != server_name]

        repo = _get_repo()
        await repo.update_device_partial(device_id, {"disabled_mcp_servers": ds})
        _hot_reload_device_config(mac)
        return {"code": 0, "message": "ok", "data": {"disabled": disabled}}
    except Exception as e:
        return {"code": 1, "message": str(e), "data": None}


@router.post("/api/v1/devices/{mac}/mcp/{server_name}/tools/{tool_name}/toggle")
async def toggle_mcp_tool(mac: str, server_name: str, tool_name: str, disabled: bool = True, user: UserModel = Depends(get_current_user)):
    """禁用或启用 MCP 服务器中的单个工具"""
    if not await _check_device_owner(mac, user):
        from fastapi import HTTPException
        raise HTTPException(403, "Device not bound to you")
    try:
        device_id, config = await _resolve_device(mac)
        if device_id is None:
            return {"code": 1, "message": f"设备不存在: {mac}", "data": None}

        dt = dict((config or {}).get("disabled_mcp_tools", {}) or {})
        server_disabled = list(dt.get(server_name, []) or [])
        if disabled:
            if tool_name not in server_disabled:
                server_disabled.append(tool_name)
        else:
            server_disabled = [t for t in server_disabled if t != tool_name]
        dt[server_name] = server_disabled

        repo = _get_repo()
        await repo.update_device_partial(device_id, {"disabled_mcp_tools": dt})
        _hot_reload_device_config(mac)
        return {"code": 0, "message": "ok", "data": {"disabled": disabled}}
    except Exception as e:
        return {"code": 1, "message": str(e), "data": None}


@router.get("/api/v1/devices/{mac}/mcp/disabled")
async def get_mcp_disabled(mac: str, user: UserModel = Depends(get_current_user)):
    """获取设备的 MCP 禁用列表"""
    if not await _check_device_owner(mac, user):
        from fastapi import HTTPException
        raise HTTPException(403, "Device not bound to you")
    try:
        device_id, config = await _resolve_device(mac)
        if device_id is None:
            return {"code": 1, "message": f"设备不存在: {mac}", "data": None}
        disabled_servers = (config or {}).get("disabled_mcp_servers", []) or []
        disabled_tools = (config or {}).get("disabled_mcp_tools", {}) or {}
        return {"code": 0, "message": "ok", "data": {"disabled_servers": disabled_servers, "disabled_tools": disabled_tools}}
    except Exception as e:
        return {"code": 1, "message": str(e), "data": None}