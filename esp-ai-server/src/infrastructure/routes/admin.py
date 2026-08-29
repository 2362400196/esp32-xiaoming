"""管理员后台 API

所有接口均要求当前用户 role=admin：
- GET    /api/v1/admin/stats              - 后台仪表盘统计
- GET    /api/v1/admin/users              - 用户列表
- PUT    /api/v1/admin/users/{user_id}    - 更新用户（角色/设备上限/启用状态/昵称）
- DELETE /api/v1/admin/users/{user_id}    - 删除用户（自动解绑其设备）
- GET    /api/v1/admin/devices            - 全量设备列表
- PUT    /api/v1/admin/devices/{device_id} - 更新设备（名称）
- POST   /api/v1/admin/devices/{device_id}/unbind - 管理员解绑设备
"""
from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Optional

import csv
import io
import logging
import re
import shutil

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select, update

from src.infrastructure.db.models.device import DeviceModel
from src.infrastructure.db.models.marketplace import (
    MarketplacePluginModel,
    PluginReviewModel,
    PluginVersionModel,
)
from src.infrastructure.db.models.user import UserModel
from src.infrastructure.db.session import get_session_ctx
from src.infrastructure.logging import get_logger
from src.infrastructure.security_jwt import hash_password, require_admin
from src.infrastructure.web import get_device_registry, get_speaker

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


# ==================== Pydantic 模型 ====================

class UserUpdateReq(BaseModel):
    nickname: Optional[str] = Field(default=None, max_length=64)
    role: Optional[str] = None
    max_devices: Optional[int] = Field(default=None, ge=0, le=10000)
    is_active: Optional[bool] = None


class DeviceUpdateReq(BaseModel):
    name: Optional[str] = Field(default=None, max_length=64)


class BatchSpeakReq(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)


class ResetPasswordReq(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=128)


class MarketplaceUpdateReq(BaseModel):
    is_active: Optional[bool] = None
    is_featured: Optional[bool] = None


class BanDeviceReq(BaseModel):
    reason: str = Field(default="", max_length=256)


class LLMConfigUpdateReq(BaseModel):
    llm_type: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_model: Optional[str] = None
    llm_system_prompt: Optional[str] = None
    llm_memory_enabled: Optional[bool] = None
    llm_memory_max_messages: Optional[int] = None
    asr_provider: Optional[str] = None
    tts_type: Optional[str] = None


# ==================== 序列化/工具函数 ====================

def _serialize_user(user: UserModel, device_count: int = 0) -> dict:
    return {
        "user_id": user.id,
        "email": user.email,
        "nickname": user.nickname,
        "role": user.role,
        "max_devices": user.max_devices,
        "is_active": user.is_active,
        "created_at": user.created_at,
        "last_login": user.last_login,
        "is_developer": bool(user.developer_api_key),
        "device_count": device_count,
    }


def _device_online(device: DeviceModel) -> bool:
    """从设备注册表判断设备当前是否在线"""
    registry = get_device_registry()
    if not registry:
        return False
    info = registry.resolve(device.device_id)
    if not info and device.mac_address:
        info = registry.get_by_mac(device.mac_address)
    if not info and device.device_key:
        info = registry.resolve(device.device_key)
    if not info:
        return False
    channel = info.get("channel")
    return bool(channel and getattr(channel, "connected", False))


def _serialize_device(device: DeviceModel, owner_email: str = "") -> dict:
    return {
        "device_id": device.device_id,
        "name": device.name,
        "mac": device.mac_address,
        "device_key": device.device_key,
        "user_id": device.user_id,
        "owner_email": owner_email,
        "online": _device_online(device),
        "bound_at": device.bound_at,
        "last_seen": device.last_seen,
        "created_at": device.created_at,
        "updated_at": device.updated_at,
        "is_banned": device.is_banned,
        "ban_reason": device.ban_reason,
        "banned_at": device.banned_at,
    }


# ==================== 统计 ====================

@router.get("/stats")
async def admin_stats(_: UserModel = Depends(require_admin)):
    """后台首页统计：用户数、设备数、在线设备数等"""
    async with get_session_ctx() as session:
        user_count = (await session.execute(
            select(func.count()).select_from(UserModel)
        )).scalar_one()
        admin_count = (await session.execute(
            select(func.count()).select_from(UserModel).where(UserModel.role == "admin")
        )).scalar_one()
        device_count = (await session.execute(
            select(func.count()).select_from(DeviceModel)
        )).scalar_one()
        bound_count = (await session.execute(
            select(func.count()).select_from(DeviceModel).where(DeviceModel.user_id.isnot(None))
        )).scalar_one()

    registry = get_device_registry()
    online_count = 0
    if registry:
        for did in registry.get_all_ids():
            d = registry.get(did)
            if d:
                channel = d.get("channel")
                if channel and getattr(channel, "connected", False):
                    online_count += 1

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "users": user_count,
            "admins": admin_count,
            "devices": device_count,
            "bound_devices": bound_count,
            "online_devices": online_count,
        },
    }


@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard():
    """管理员仪表盘页面（HTML），页面内处理登录认证"""
    return HTMLResponse(ADMIN_DASHBOARD_HTML)


# ==================== 用户管理 ====================

@router.get("/users")
async def list_users(_: UserModel = Depends(require_admin)):
    """全量用户列表（含每用户绑定设备数）"""
    async with get_session_ctx() as session:
        users = (await session.execute(
            select(UserModel).order_by(UserModel.created_at.desc())
        )).scalars().all()

        count_rows = await session.execute(
            select(DeviceModel.user_id, func.count())
            .where(DeviceModel.user_id.isnot(None))
            .group_by(DeviceModel.user_id)
        )
        counts = {uid: cnt for uid, cnt in count_rows}

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "users": [_serialize_user(u, counts.get(u.id, 0)) for u in users],
        },
    }


@router.put("/users/{user_id}")
async def update_user(user_id: str, req: UserUpdateReq, admin: UserModel = Depends(require_admin)):
    """更新用户：角色、设备上限、启用状态、昵称"""
    async with get_session_ctx() as session:
        result = await session.execute(select(UserModel).where(UserModel.id == user_id))
        target = result.scalar_one_or_none()
        if not target:
            raise HTTPException(404, "User not found")

        if req.role is not None:
            if req.role not in ("admin", "user"):
                raise HTTPException(400, "Role must be 'admin' or 'user'")
            if target.role == "admin" and req.role == "user":
                if target.id == admin.id:
                    raise HTTPException(400, "不能取消自己的管理员角色")
                admin_count = (await session.execute(
                    select(func.count()).select_from(UserModel).where(UserModel.role == "admin")
                )).scalar_one()
                if admin_count <= 1:
                    raise HTTPException(400, "系统至少需要保留一个管理员")
            target.role = req.role

        if req.max_devices is not None:
            target.max_devices = req.max_devices

        if req.is_active is not None:
            if target.id == admin.id and req.is_active is False:
                raise HTTPException(400, "不能停用当前登录的管理员账号")
            target.is_active = req.is_active
            if req.is_active is False:
                # 吊销语义：停用用户后 token_version +1，使其所有已签发 JWT 失效
                target.token_version = (target.token_version or 0) + 1

        if req.nickname is not None:
            target.nickname = req.nickname

        session.add(target)

    return {
        "code": 0,
        "message": "ok",
        "data": _serialize_user(target),
    }


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, admin: UserModel = Depends(require_admin)):
    """删除用户；同时解绑该用户的所有设备"""
    async with get_session_ctx() as session:
        result = await session.execute(select(UserModel).where(UserModel.id == user_id))
        target = result.scalar_one_or_none()
        if not target:
            raise HTTPException(404, "User not found")
        if target.id == admin.id:
            raise HTTPException(400, "不能删除当前登录的管理员账号")

        admin_count = (await session.execute(
            select(func.count()).select_from(UserModel).where(UserModel.role == "admin")
        )).scalar_one()
        if target.role == "admin" and admin_count <= 1:
            raise HTTPException(400, "系统至少需要保留一个管理员")

        await session.execute(
            update(DeviceModel)
            .where(DeviceModel.user_id == target.id)
            .values(user_id=None, bound_at=None)
        )
        await session.delete(target)

    return {"code": 0, "message": "用户已删除"}


# ==================== 设备管理 ====================

@router.get("/devices")
async def list_devices(_: UserModel = Depends(require_admin)):
    """全量设备列表（含归属用户邮箱）"""
    async with get_session_ctx() as session:
        devices = (await session.execute(
            select(DeviceModel).order_by(DeviceModel.created_at.desc())
        )).scalars().all()

        user_ids = {d.user_id for d in devices if d.user_id}
        owners: dict[str, str] = {}
        if user_ids:
            owner_rows = await session.execute(
                select(UserModel.id, UserModel.email).where(UserModel.id.in_(user_ids))
            )
            owners = {uid: email for uid, email in owner_rows}

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "devices": [
                _serialize_device(d, owners.get(d.user_id or "", ""))
                for d in devices
            ],
        },
    }


@router.put("/devices/{device_id}")
async def update_device(device_id: str, req: DeviceUpdateReq, _: UserModel = Depends(require_admin)):
    """更新设备信息（当前支持名称）"""
    async with get_session_ctx() as session:
        result = await session.execute(select(DeviceModel).where(DeviceModel.device_id == device_id))
        device = result.scalar_one_or_none()
        if not device:
            raise HTTPException(404, "Device not found")

        if req.name is not None:
            device.name = req.name

        session.add(device)

    return {
        "code": 0,
        "message": "ok",
        "data": _serialize_device(device),
    }


@router.post("/devices/{device_id}/unbind")
async def unbind_device(device_id: str, _: UserModel = Depends(require_admin)):
    """管理员解绑设备，设备恢复为未绑定状态"""
    async with get_session_ctx() as session:
        result = await session.execute(select(DeviceModel).where(DeviceModel.device_id == device_id))
        device = result.scalar_one_or_none()
        if not device:
            raise HTTPException(404, "Device not found")

        device.user_id = None
        device.bound_at = None
        device.bind_code = None
        device.bind_code_expires = None
        session.add(device)

    return {"code": 0, "message": "设备已解绑", "data": {"device_id": device_id}}


@router.delete("/devices/{device_id}")
async def delete_device(device_id: str, _: UserModel = Depends(require_admin)):
    """管理员删除设备记录（仅限未绑定设备）"""
    async with get_session_ctx() as session:
        result = await session.execute(select(DeviceModel).where(DeviceModel.device_id == device_id))
        device = result.scalar_one_or_none()
        if not device:
            raise HTTPException(404, "Device not found")
        if device.user_id:
            raise HTTPException(400, "已绑定的设备请先解绑再删除")
        await session.delete(device)

    return {"code": 0, "message": "设备已删除", "data": {"device_id": device_id}}



# ==================== 设备批量操作 ====================

@router.post("/devices/batch/wakeup")
async def admin_batch_wakeup(_: UserModel = Depends(require_admin)):
    """批量唤醒所有在线设备"""
    speaker = get_speaker()
    if not speaker:
        raise HTTPException(503, "Speaker not available")
    await speaker.wakeup_all()
    return {"code": 0, "message": "已批量唤醒所有在线设备"}


@router.post("/devices/batch/stop")
async def admin_batch_stop(_: UserModel = Depends(require_admin)):
    """批量停止所有在线设备播放/对话"""
    speaker = get_speaker()
    if not speaker:
        raise HTTPException(503, "Speaker not available")
    await speaker.stop_all()
    return {"code": 0, "message": "已批量停止所有在线设备"}


@router.post("/devices/batch/speak")
async def admin_batch_speak(req: BatchSpeakReq, _: UserModel = Depends(require_admin)):
    """向所有在线设备广播一段语音"""
    speaker = get_speaker()
    if not speaker:
        raise HTTPException(503, "Speaker not available")
    await speaker.speak_all(req.text, need_wakeup=False)
    return {"code": 0, "message": "已向所有在线设备广播", "data": {"text": req.text}}


# ==================== 用户管理增强 ====================

@router.get("/users/{user_id}/devices")
async def admin_user_devices(user_id: str, _: UserModel = Depends(require_admin)):
    """查看指定用户绑定的所有设备"""
    async with get_session_ctx() as session:
        devices = (await session.execute(
            select(DeviceModel).where(DeviceModel.user_id == user_id).order_by(DeviceModel.created_at.desc())
        )).scalars().all()

    registry = get_device_registry()
    items = []
    for d in devices:
        online = False
        if registry:
            info = registry.resolve(d.device_id)
            if not info and d.mac_address:
                info = registry.get_by_mac(d.mac_address)
            if info:
                channel = info.get("channel")
                online = bool(channel and getattr(channel, "connected", False))
        items.append({
            "device_id": d.device_id,
            "name": d.name,
            "mac": d.mac_address,
            "device_key": d.device_key,
            "online": online,
            "bound_at": d.bound_at,
        })
    return {"code": 0, "message": "ok", "data": {"devices": items}}


@router.post("/users/{user_id}/reset-password")
async def admin_reset_password(user_id: str, req: ResetPasswordReq, _: UserModel = Depends(require_admin)):
    """管理员重置用户密码"""
    async with get_session_ctx() as session:
        target = (await session.execute(
            select(UserModel).where(UserModel.id == user_id)
        )).scalar_one_or_none()
        if not target:
            raise HTTPException(404, "User not found")
        target.password_hash = hash_password(req.new_password)
        # 吊销语义：重置密码后 token_version +1，使该用户所有已签发 JWT（含 refresh）失效
        target.token_version = (target.token_version or 0) + 1
        session.add(target)
    return {"code": 0, "message": "密码已重置"}


@router.post("/users/{user_id}/toggle-developer")
async def admin_toggle_developer(user_id: str, _: UserModel = Depends(require_admin)):
    """开启/关闭用户的开发者权限"""
    async with get_session_ctx() as session:
        target = (await session.execute(
            select(UserModel).where(UserModel.id == user_id)
        )).scalar_one_or_none()
        if not target:
            raise HTTPException(404, "User not found")
        target.developer_api_key = None if target.developer_api_key else secrets.token_urlsafe(32)
        session.add(target)
        is_developer = bool(target.developer_api_key)
    return {"code": 0, "message": "开发者权限已更新", "data": {"is_developer": is_developer}}


# ==================== 系统监控与日志 ====================

@router.get("/system/info")
async def admin_system_info(_: UserModel = Depends(require_admin)):
    """获取服务器基础信息、数据库/日志大小、进程资源占用（psutil 可选）"""
    import platform
    import sys

    from src.infrastructure.config import get_settings

    settings = get_settings()
    db_path = None
    sync_url = getattr(settings.database, "sync_url", "")
    if ":///" in sync_url:
        db_path = Path(sync_url.split(":///", 1)[1])
        if not db_path.is_absolute():
            db_path = _project_root() / db_path

    log_path = Path(settings.log.file_path) if settings.log.file_path else None
    if log_path and not log_path.is_absolute():
        log_path = _project_root() / log_path

    registry = get_device_registry()
    data = {
        "server_version": "3.0.0-clean-arch",
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "db_path": str(db_path.resolve()) if db_path else "",
        "db_size": db_path.stat().st_size if db_path and db_path.exists() else 0,
        "log_path": str(log_path.resolve()) if log_path else "",
        "log_size": log_path.stat().st_size if log_path and log_path.exists() else 0,
        "registry_devices": registry.count() if registry else 0,
        "memory_bytes": None,
        "cpu_percent": None,
    }
    try:
        import psutil
        proc = psutil.Process()
        data["memory_bytes"] = proc.memory_info().rss
        data["cpu_percent"] = proc.cpu_percent(interval=0.1)
    except Exception:
        pass
    return {"code": 0, "message": "ok", "data": data}


@router.get("/logs")
async def admin_logs(lines: int = Query(200, ge=1, le=5000), _: UserModel = Depends(require_admin)):
    """读取服务日志末尾 N 行"""
    from src.infrastructure.config import get_settings

    settings = get_settings()
    log_path = settings.log.file_path
    if not log_path:
        return {"code": 0, "message": "ok", "data": {"path": "", "lines": []}}

    path = Path(log_path)
    if not path.is_absolute():
        path = _project_root() / path

    if not path.exists():
        return {"code": 0, "message": "ok", "data": {"path": str(path), "lines": []}}

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        all_lines = content.splitlines()
        return {"code": 0, "message": "ok", "data": {"path": str(path), "lines": all_lines[-lines:]}}
    except Exception as e:
        raise HTTPException(500, f"读取日志失败: {e}")


# ==================== 数据库备份 ====================

def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def _backup_dir() -> Path:
    return _project_root() / "data" / "backups"


@router.post("/backup")
async def admin_backup(_: UserModel = Depends(require_admin)):
    """创建 SQLite 数据库备份"""
    from scripts.backup_db import _resolve_db_path, backup_database

    db_path = _resolve_db_path()
    if not db_path.is_absolute():
        db_path = _project_root() / db_path

    backup_dir = _backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    try:
        backup_path = backup_database(db_path, backup_dir, keep_days=30)
    except Exception as e:
        raise HTTPException(500, f"备份失败: {e}")

    return {
        "code": 0,
        "message": "备份成功",
        "data": {
            "path": str(backup_path),
            "name": backup_path.name,
            "size": backup_path.stat().st_size,
            "mtime": backup_path.stat().st_mtime,
        },
    }


@router.get("/backups")
async def admin_list_backups(_: UserModel = Depends(require_admin)):
    """列出最近数据库备份"""
    backup_dir = _backup_dir()
    if not backup_dir.exists():
        return {"code": 0, "message": "ok", "data": {"backups": []}}

    files = sorted(
        backup_dir.glob("espai_backup_*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    items = [{
        "name": p.name,
        "size": p.stat().st_size,
        "mtime": p.stat().st_mtime,
        "path": str(p),
    } for p in files]
    return {"code": 0, "message": "ok", "data": {"backups": items}}


@router.get("/backup/download/{filename}")
async def admin_download_backup(filename: str, _: UserModel = Depends(require_admin)):
    """下载备份文件"""
    import os
    # 防止路径穿越
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "非法文件名")
    backup_dir = _backup_dir()
    file_path = backup_dir / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(404, "备份文件不存在")
    from starlette.responses import FileResponse
    return FileResponse(str(file_path), media_type="application/octet-stream", filename=filename)


@router.delete("/backup/{filename}")
async def admin_delete_backup(filename: str, _: UserModel = Depends(require_admin)):
    """删除指定备份文件"""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "非法文件名")
    backup_dir = _backup_dir()
    file_path = backup_dir / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(404, "备份文件不存在")
    file_path.unlink()
    logger.info(f"[Admin] 删除备份文件: {filename}")
    return {"code": 0, "message": "备份文件已删除"}


# ==================== 设备封禁/解封 ====================

@router.post("/devices/{device_id}/ban")
async def admin_ban_device(device_id: str, req: BanDeviceReq, _: UserModel = Depends(require_admin)):
    """封禁设备（被封禁的设备无法连接服务端）"""
    async with get_session_ctx() as session:
        device = await session.get(DeviceModel, device_id)
        if not device:
            raise HTTPException(404, "设备不存在")
        device.is_banned = True
        device.banned_at = time.time()
        device.ban_reason = req.reason
        # 踢下线
        from src.infrastructure.web import get_device_registry
        registry = get_device_registry()
        if registry:
            session_data = registry.resolve(device_id)
            if session_data and session_data.get('channel'):
                try:
                    session_data['channel'].send_queue.put_nowait({"kind": "close", "data": {"reason": "banned"}})
                except Exception:
                    pass
        await session.commit()
        _add_oplog(_.email, "封禁设备", f"device_id={device_id}, reason={req.reason}")
        logger.info(f"[Admin] 封禁设备: {device_id}, 原因: {req.reason}")
        return {"code": 0, "message": "设备已封禁"}


@router.post("/devices/{device_id}/unban")
async def admin_unban_device(device_id: str, _: UserModel = Depends(require_admin)):
    """解封设备"""
    async with get_session_ctx() as session:
        device = await session.get(DeviceModel, device_id)
        if not device:
            raise HTTPException(404, "设备不存在")
        device.is_banned = False
        device.banned_at = None
        device.ban_reason = ""
        await session.commit()
        _add_oplog(_.email, "解封设备", f"device_id={device_id}")
        logger.info(f"[Admin] 解封设备: {device_id}")
        return {"code": 0, "message": "设备已解封"}


# ==================== LLM 配置管理 ====================

@router.get("/llm-configs")
async def admin_llm_configs(device_id: Optional[str] = Query(None), _: UserModel = Depends(require_admin)):
    """查看所有设备的 LLM 配置"""
    async with get_session_ctx() as session:
        stmt = select(DeviceModel)
        if device_id:
            stmt = stmt.where(DeviceModel.device_id == device_id)
        rows = (await session.execute(stmt)).scalars().all()
        items = []
        for d in rows:
            items.append({
                "device_id": d.device_id,
                "name": d.name,
                "llm_type": d.llm_type,
                "llm_api_key": "***" + d.llm_api_key[-4:] if d.llm_api_key else "",
                "llm_base_url": d.llm_base_url,
                "llm_model": d.llm_model,
                "llm_system_prompt": d.llm_system_prompt[:200] if d.llm_system_prompt else "",
                "llm_memory_enabled": d.llm_memory_enabled,
                "llm_memory_max_messages": d.llm_memory_max_messages,
                "llm_memory_long_term_enabled": d.llm_memory_long_term_enabled,
                "asr_provider": d.asr_provider,
                "tts_type": d.tts_type,
            })
        return {"code": 0, "data": {"configs": items}}


@router.put("/llm-configs/{device_id}")
async def admin_update_llm_config(device_id: str, req: LLMConfigUpdateReq, _: UserModel = Depends(require_admin)):
    """更新设备 LLM 配置"""
    async with get_session_ctx() as session:
        device = await session.get(DeviceModel, device_id)
        if not device:
            raise HTTPException(404, "设备不存在")
        update_data = req.model_dump(exclude_none=True)
        for key, val in update_data.items():
            setattr(device, key, val)
        await session.commit()
        logger.info(f"[Admin] 更新 LLM 配置: {device_id}")
        return {"code": 0, "message": "LLM 配置已更新"}


# ==================== 对话历史 ====================

@router.get("/conversations")
async def admin_conversations(device_id: Optional[str] = Query(None), limit: int = Query(50, ge=1, le=200), _: UserModel = Depends(require_admin)):
    """查看对话历史（从短期记忆表读取）"""
    from src.infrastructure.db.repositories.short_term_memory_repo import SqlShortTermMemoryRepository
    repo = SqlShortTermMemoryRepository()
    if not device_id:
        conversations = []
        async with get_session_ctx() as session:
            devices = (await session.execute(select(DeviceModel))).scalars().all()
            for d in devices:
                msgs = repo.load(d.device_id)
                if msgs:
                    conversations.append({"device_id": d.device_id, "device_name": d.name, "messages": msgs[-10:]})
        return {"code": 0, "data": {"conversations": conversations}}
    else:
        msgs = repo.load(device_id)
        async with get_session_ctx() as session:
            device = await session.get(DeviceModel, device_id)
            name = device.name if device else device_id
        return {"code": 0, "data": {"device_id": device_id, "device_name": name, "messages": msgs[-limit:]}}


# ==================== WebSocket 状态 ====================

@router.get("/ws-status")
async def admin_ws_status(_: UserModel = Depends(require_admin)):
    """查看所有 WebSocket 连接状态"""
    from src.infrastructure.web import get_device_registry
    registry = get_device_registry()
    if not registry:
        return {"code": 0, "data": {"connections": []}}
    ids = registry.get_all_ids()
    connections = []
    for did in ids:
        info = registry.resolve(did)
        if info:
            channel = info.get("channel")
            connections.append({
                "device_id": did,
                "mac": info.get("mac", ""),
                "connected": bool(channel and getattr(channel, "connected", False)),
                "session_id": info.get("session_id", ""),
                "last_seen": info.get("last_seen", 0),
            })
    return {"code": 0, "data": {"connections": connections, "total": len(connections)}}


# ==================== 系统健康检查 ====================

@router.get("/health")
async def admin_health_check(_: UserModel = Depends(require_admin)):
    """系统健康检查"""
    results = {}
    # 1. 数据库
    try:
        async with get_session_ctx() as session:
            await session.execute(select(func.count()).select_from(DeviceModel))
        results["database"] = {"status": "ok", "latency_ms": 0}
    except Exception as e:
        results["database"] = {"status": "error", "message": str(e)}

    # 2. 磁盘空间
    try:
        du = shutil.disk_usage(_project_root())
        results["disk"] = {"status": "ok", "total_gb": round(du.total / (1024**3), 1), "free_gb": round(du.free / (1024**3), 1), "usage_pct": round(du.used / du.total * 100, 1)}
    except Exception as e:
        results["disk"] = {"status": "error", "message": str(e)}

    # 3. 设备注册表
    try:
        registry = get_device_registry()
        count = len(registry.get_all_ids()) if registry else 0
        results["registry"] = {"status": "ok", "device_count": count}
    except Exception as e:
        results["registry"] = {"status": "error", "message": str(e)}

    # 4. ASR/LLM/TTS 配置检查
    async with get_session_ctx() as session:
        devices = (await session.execute(select(DeviceModel))).scalars().all()
        asr_configured = sum(1 for d in devices if d.asr_provider)
        llm_configured = sum(1 for d in devices if d.llm_type)
        tts_configured = sum(1 for d in devices if d.tts_type)
        results["services"] = {"status": "ok", "asr_configured": asr_configured, "llm_configured": llm_configured, "tts_configured": tts_configured}

    overall = "ok" if all(r.get("status") == "ok" for r in results.values()) else "degraded"
    return {"code": 0, "data": {"overall": overall, "checks": results}}


# ==================== 操作日志 ====================

# 操作日志文件基于项目根目录的绝对路径（避免相对 CWD，换工作目录启动时日志写到别处）
OPLOG_FILE = str(_project_root() / "data" / "admin_operation_logs.json")


def _load_oplogs() -> list:
    if not os.path.exists(OPLOG_FILE):
        return []
    try:
        with open(OPLOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_oplogs(logs: list) -> None:
    os.makedirs(os.path.dirname(OPLOG_FILE), exist_ok=True)
    with open(OPLOG_FILE, "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)


def _add_oplog(admin_email: str, action: str, detail: str = "") -> None:
    logs = _load_oplogs()
    logs.insert(0, {"time": time.time(), "admin": admin_email, "action": action, "detail": detail})
    if len(logs) > 1000:
        logs = logs[:1000]
    _save_oplogs(logs)


@router.get("/operation-logs")
async def admin_operation_logs(limit: int = Query(100, ge=1, le=500), _: UserModel = Depends(require_admin)):
    """查看操作日志"""
    logs = _load_oplogs()
    return {"code": 0, "data": {"logs": logs[:limit]}}


# ==================== 表情包管理 ====================

@router.get("/emojis")
async def admin_list_emojis(request: Request, _: UserModel = Depends(require_admin)):
    """查看所有表情包（含预览图）"""
    from src.infrastructure.emo_pack import list_packs as _list_packs, list_pack_emos
    packs = await _list_packs()
    host = request.headers.get("host", "localhost:8088")
    scheme = request.headers.get("x-forwarded-proto", "http")
    result = []
    for p in packs:
        emos = list_pack_emos(p["name"], scheme, host)
        result.append({**p, "emos": emos})  # 返回所有预览
    return {"code": 0, "data": {"packs": result}}


@router.post("/emojis/upload")
async def admin_upload_emoji(file: bytes, name: str = Query(...), _: UserModel = Depends(require_admin)):
    """上传表情包（保存到 src/emos/packs/）"""
    from src.infrastructure.emo_pack import get_or_create_pack_dir
    target_dir = get_or_create_pack_dir(name)
    if not target_dir:
        return {"code": 1, "message": "无效的表情包名称"}
    zip_path = target_dir / "pack.zip"
    with open(zip_path, "wb") as f:
        f.write(file)
    _add_oplog(_.email, "上传表情包", f"pack={name}")
    logger.info(f"[Admin] 上传表情包: {name}")
    return {"code": 0, "message": "表情包已上传"}


@router.delete("/emojis/{name}")
async def admin_delete_emoji(name: str, _: UserModel = Depends(require_admin)):
    """删除表情包"""
    from src.infrastructure.emo_pack import delete_pack as _delete_pack
    result = await _delete_pack(name)
    _add_oplog(_.email, "删除表情包", f"pack={name}")
    logger.info(f"[Admin] 删除表情包: {name}")
    return {"code": 0, "message": result.get("message", "表情包已删除")}


@router.delete("/emojis/{pack_name}/emoji/{filename}")
async def admin_delete_emoji_file(pack_name: str, filename: str, request: Request, _: UserModel = Depends(require_admin)):
    """删除表情包中的单个表情"""
    from src.infrastructure.emo_pack import get_pack_dir, _validate_pack_name
    if not _validate_pack_name(pack_name):
        raise HTTPException(400, "无效的表情包名称")
    p = get_pack_dir(pack_name)
    if not p:
        raise HTTPException(404, "表情包不存在")
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "无效的文件名")
    fpath = p / filename
    if not fpath.exists() or not fpath.is_file():
        raise HTTPException(404, "文件不存在")
    fpath.unlink()
    _add_oplog(_.email, "删除表情", f"pack={pack_name}, file={filename}")
    logger.info(f"[Admin] 删除表情: {pack_name}/{filename}")
    return {"code": 0, "message": "表情已删除"}


# ==================== 数据导出 ====================

@router.get("/export/{data_type}")
async def admin_export_data(data_type: str, _: UserModel = Depends(require_admin)):
    """导出数据 (users/devices)"""
    if data_type == "users":
        async with get_session_ctx() as session:
            rows = (await session.execute(select(UserModel))).scalars().all()
            output = io.StringIO()
            w = csv.writer(output)
            w.writerow(["ID", "邮箱", "昵称", "角色", "状态", "最大设备数", "注册时间", "最后登录"])
            for r in rows:
                w.writerow([r.id, r.email, r.nickname, r.role, "启用" if r.is_active else "停用", r.max_devices, r.created_at, r.last_login or ""])
            from starlette.responses import StreamingResponse
            output.seek(0)
            return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=users.csv"})
    elif data_type == "devices":
        async with get_session_ctx() as session:
            rows = (await session.execute(select(DeviceModel))).scalars().all()
            output = io.StringIO()
            w = csv.writer(output)
            w.writerow(["ID", "名称", "MAC", "设备Key", "用户ID", "在线", "封禁", "最后在线", "创建时间"])
            for r in rows:
                # 安全：device_key 是设备 WS 凭据，导出只保留前 8 位掩码，防止明文泄露
                masked_key = (r.device_key or "")[:8] + "***" if r.device_key else ""
                w.writerow([r.device_id, r.name, r.mac_address, masked_key, r.user_id or "", "是" if r.is_online else "否", "是" if r.is_banned else "否", r.last_seen or "", r.created_at or ""])
            from starlette.responses import StreamingResponse
            output.seek(0)
            return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=devices.csv"})
    raise HTTPException(400, "不支持的数据类型，仅支持 users/devices")


# ==================== 定时任务 ====================

@router.get("/scheduled-tasks")
async def admin_scheduled_tasks(_: UserModel = Depends(require_admin)):
    """查看定时任务"""
    task_file = _project_root() / "data" / "scheduled_tasks.json"
    tasks = []
    if task_file.exists():
        try:
            tasks = json.loads(task_file.read_text(encoding="utf-8"))
        except Exception:
            tasks = []
    return {"code": 0, "data": {"tasks": tasks}}


@router.post("/scheduled-tasks")
async def admin_create_scheduled_task(data: dict, _: UserModel = Depends(require_admin)):
    """创建定时任务"""
    # 记录到文件
    task_file = _project_root() / "data" / "scheduled_tasks.json"
    tasks = []
    if task_file.exists():
        try:
            tasks = json.loads(task_file.read_text(encoding="utf-8"))
        except Exception:
            tasks = []
    tasks.append({"id": str(int(time.time())), "created_at": time.time(), **data})
    task_file.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"[Admin] 创建定时任务: {data}")
    return {"code": 0, "message": "定时任务已创建"}


@router.delete("/scheduled-tasks/{task_id}")
async def admin_delete_scheduled_task(task_id: str, _: UserModel = Depends(require_admin)):
    """删除定时任务"""
    task_file = _project_root() / "data" / "scheduled_tasks.json"
    if task_file.exists():
        try:
            tasks = json.loads(task_file.read_text(encoding="utf-8"))
            tasks = [t for t in tasks if t.get("id") != task_id]
            task_file.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    return {"code": 0, "message": "定时任务已删除"}


# ==================== 全局配置 ====================

# 全局配置中文标签与说明
GLOBAL_CONFIG_LABELS = {
    "app_name": ("应用名称", "设备显示的应用名称"),
    "deploy_mode": ("部署模式", "single=单用户, multi=多用户"),
    "asr_provider": ("ASR 提供商", "语音识别服务商，如 volc(火山引擎)、tencent(腾讯云)"),
    "asr_language": ("ASR 语言", "语音识别语言，如 zh(中文)、en(英文)"),
    "llm_type": ("LLM 类型", "大模型提供商，如 openai、deepseek、qwen"),
    "llm_base_url": ("LLM 地址", "API 地址，兼容 OpenAI 格式"),
    "llm_model": ("LLM 模型", "使用的模型名称，如 gpt-4o、deepseek-chat"),
    "tts_type": ("TTS 类型", "语音合成类型，如 volc_tts"),
    "tts_voice": ("TTS 音色", "语音合成使用的音色标识"),
    "wake_word": ("唤醒词", "设备唤醒的关键词"),
    "max_connections": ("最大连接数", "服务端同时接受的最大 WebSocket 连接数"),
}

@router.get("/config/export")
async def admin_export_config(_: UserModel = Depends(require_admin)):
    """导出系统配置（.env 中的关键配置）"""
    from src.infrastructure.config import get_settings
    settings = get_settings()
    config = {
        "export_time": time.time(),
        "app_name": settings.APP_NAME,
        "deploy_mode": settings.DEPLOY_MODE,
        "asr_provider": settings.ASR_PROVIDER,
        "asr_language": settings.ASR_LANGUAGE,
        "llm_type": settings.LLM_TYPE,
        "llm_base_url": settings.LLM_BASE_URL,
        "llm_model": settings.LLM_MODEL,
        "tts_type": settings.TTS_TYPE,
        "tts_voice": settings.TTS_VOICE,
        "wake_word": settings.WAKE_WORD,
        "max_connections": settings.MAX_CONNECTIONS,
    }
    items = []
    for k, v in config.items():
        if k == "export_time":
            continue
        label, desc = GLOBAL_CONFIG_LABELS.get(k, (k, ""))
        items.append({"key": k, "label": label, "desc": desc, "value": v})
    return {"code": 0, "data": {"items": items}}


@router.post("/config/import")
async def admin_import_config(data: dict, _: UserModel = Depends(require_admin)):
    """导入系统配置"""
    # 合法环境变量名白名单：仅允许大写字母/下划线开头，后接大写字母/数字/下划线
    _env_key_pattern = r"^[A-Z_][A-Z0-9_]*$"
    env_path = _project_root() / ".env"
    if not env_path.exists():
        raise HTTPException(400, ".env 文件不存在")
    content = env_path.read_text(encoding="utf-8")
    for key, val in data.items():
        if val is None:
            continue
        # key 白名单校验：不合法的环境变量名直接拒绝，防止注入任意配置项
        if not re.match(_env_key_pattern, str(key)):
            raise HTTPException(400, f"非法配置项名: {key}")
        # value 过滤换行符，防止伪造多行 .env 内容注入额外配置
        value = str(val).replace("\n", " ").replace("\r", " ")
        # key 用 re.escape 转义；替换文本用 lambda 返回，避免 value 中的反斜杠被当作正则替换引用
        if re.search(rf"^{re.escape(str(key))}=", content, re.MULTILINE):
            content = re.sub(
                rf"^{re.escape(str(key))}=.*",
                lambda _m: f"{key}={value}",
                content,
                flags=re.MULTILINE,
            )
        else:
            content += f"\n{key}={value}"
    env_path.write_text(content, encoding="utf-8")
    logger.info(f"[Admin] 导入系统配置: {list(data.keys())}")
    return {"code": 0, "message": "配置已导入，重启后生效"}


# ==================== 动态日志级别 ====================

@router.put("/log-level")
async def admin_set_log_level(level: str = Query(...), _: UserModel = Depends(require_admin)):
    """动态设置日志级别 (debug/info/warning/error)"""
    valid = {"debug", "info", "warning", "error"}
    if level.lower() not in valid:
        raise HTTPException(400, f"无效的日志级别，可选: {', '.join(valid)}")
    logging.getLogger().setLevel(level.upper())
    logger.info(f"[Admin] 日志级别已设置为: {level}")
    return {"code": 0, "message": f"日志级别已设置为 {level}"}


# ==================== 市场管理 ====================

@router.get("/marketplace/plugins")
async def admin_marketplace_plugins(_: UserModel = Depends(require_admin)):
    """查看市场上所有插件（含未上架/下架）"""
    async with get_session_ctx() as session:
        rows = (await session.execute(
            select(MarketplacePluginModel, UserModel)
            .join(UserModel, MarketplacePluginModel.developer_id == UserModel.id)
            .order_by(desc(MarketplacePluginModel.created_at))
        )).all()

    items = []
    for p, u in rows:
        try:
            tags = json.loads(p.tags) if p.tags else []
        except Exception:
            tags = []
        items.append({
            "slug": p.slug,
            "name": p.name,
            "description": p.description,
            "developer": u.nickname or (u.email.split("@")[0] if u.email else ""),
            "category": p.category,
            "tags": tags,
            "latest_version": p.latest_version,
            "total_downloads": p.total_downloads,
            "avg_rating": round(p.avg_rating or 0, 2),
            "review_count": p.review_count,
            "is_active": p.is_active,
            "is_featured": p.is_featured,
            "created_at": p.created_at,
            "updated_at": p.updated_at,
        })
    return {"code": 0, "message": "ok", "data": {"plugins": items}}


@router.put("/marketplace/plugins/{slug}")
async def admin_update_marketplace_plugin(
    slug: str,
    req: MarketplaceUpdateReq,
    _: UserModel = Depends(require_admin),
):
    """上下架/推荐/取消推荐市场插件"""
    async with get_session_ctx() as session:
        plugin = (await session.execute(
            select(MarketplacePluginModel).where(MarketplacePluginModel.slug == slug)
        )).scalar_one_or_none()
        if not plugin:
            raise HTTPException(404, "Plugin not found")
        if req.is_active is not None:
            plugin.is_active = req.is_active
        if req.is_featured is not None:
            plugin.is_featured = req.is_featured
        session.add(plugin)

    return {
        "code": 0,
        "message": "插件状态已更新",
        "data": {"slug": slug, "is_active": plugin.is_active, "is_featured": plugin.is_featured},
    }


@router.get("/marketplace/reviews")
async def admin_marketplace_reviews(_: UserModel = Depends(require_admin)):
    """查看所有市场评论"""
    async with get_session_ctx() as session:
        rows = (await session.execute(
            select(PluginReviewModel, MarketplacePluginModel)
            .join(MarketplacePluginModel, PluginReviewModel.plugin_id == MarketplacePluginModel.id)
            .order_by(desc(PluginReviewModel.created_at))
        )).all()

    items = [{
        "id": r.id,
        "plugin_slug": p.slug,
        "plugin_name": p.name,
        "username": r.username,
        "rating": r.rating,
        "comment": r.comment,
        "created_at": r.created_at,
    } for r, p in rows]
    return {"code": 0, "message": "ok", "data": {"reviews": items}}


@router.delete("/marketplace/reviews/{review_id}")
async def admin_delete_review(review_id: int, _: UserModel = Depends(require_admin)):
    """删除市场评论并重新计算插件评分"""
    async with get_session_ctx() as session:
        review = await session.get(PluginReviewModel, review_id)
        if not review:
            raise HTTPException(404, "Review not found")
        plugin = await session.get(MarketplacePluginModel, review.plugin_id)
        await session.delete(review)
        await session.flush()

        if plugin:
            agg = (await session.execute(
                select(func.count(PluginReviewModel.id), func.avg(PluginReviewModel.rating))
                .where(PluginReviewModel.plugin_id == plugin.id)
            )).one()
            count, avg = agg
            plugin.review_count = count or 0
            plugin.avg_rating = round(float(avg), 4) if avg is not None else 0
            session.add(plugin)

    return {"code": 0, "message": "评论已删除"}


ADMIN_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>管理员仪表盘 - ESP AI Server</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f1923; color: #e0e6ed; min-height: 100vh; }
.header { background: linear-gradient(135deg, #1a2a3a 0%, #0f1923 100%); padding: 20px 30px; border-bottom: 1px solid #1e3a4a; display: flex; justify-content: space-between; align-items: center; }
.header h1 { font-size: 22px; font-weight: 600; color: #4fc3f7; }
.header h1 span { color: #8899aa; font-weight: 400; }
.header .update-time { font-size: 13px; color: #667788; }
.container { max-width: 1400px; margin: 0 auto; padding: 20px; }
.row { display: grid; gap: 16px; margin-bottom: 24px; }
.row-4 { grid-template-columns: repeat(4, 1fr); }
.row-3 { grid-template-columns: repeat(3, 1fr); }
.row-2 { grid-template-columns: repeat(2, 1fr); }
.card { background: #1a2a3a; border-radius: 12px; border: 1px solid #1e3a4a; padding: 20px; transition: all 0.2s; }
.card:hover { border-color: #2a5a7a; }
.card .label { font-size: 12px; text-transform: uppercase; color: #667788; letter-spacing: 1px; margin-bottom: 8px; }
.card .value { font-size: 32px; font-weight: 700; }
.card .sub { font-size: 13px; color: #667788; margin-top: 4px; }
.card.users .value { color: #4fc3f7; }
.card.devices .value { color: #81c784; }
.card.online .value { color: #aed581; }
.card.cpu .value { color: #ffb74d; }
.card.memory .value { color: #e57373; }
.card.threads .value { color: #ba68c8; }
.card.db .value { color: #4dd0e1; }
.card.uptime .value { color: #90a4ae; font-size: 20px; }
.section-title { font-size: 16px; font-weight: 600; color: #8899aa; margin-bottom: 16px; padding-bottom: 8px; border-bottom: 1px solid #1e3a4a; }
.nav-tabs { display: flex; gap: 4px; margin-bottom: 24px; background: #1a2a3a; border-radius: 10px; padding: 4px; border: 1px solid #1e3a4a; }
.nav-tab { padding: 10px 24px; border-radius: 8px; cursor: pointer; font-size: 14px; color: #667788; transition: all 0.2s; border: none; background: none; }
.nav-tab:hover { color: #e0e6ed; }
.nav-tab.active { background: #2a5a7a; color: #fff; }
.tab-content { display: none; }
.tab-content.active { display: block; }
.pool-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.pool-item { background: #0f1923; border-radius: 8px; padding: 14px; border: 1px solid #1e3a4a; }
.pool-item .pool-name { font-size: 13px; color: #4fc3f7; margin-bottom: 6px; }
.pool-item .pool-stat { font-size: 12px; color: #8899aa; line-height: 1.6; }
.concurrency-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; }
.concurrency-item { background: #0f1923; border-radius: 8px; padding: 14px; text-align: center; }
.concurrency-item .conc-label { font-size: 11px; color: #667788; }
.concurrency-item .conc-value { font-size: 24px; font-weight: 700; margin-top: 4px; }
.concurrency-item .conc-value.semaphore { color: #81c784; }
.concurrency-item .conc-value.active { color: #ffb74d; }
.concurrency-item .conc-value.queued { color: #4fc3f7; }
.concurrency-item .conc-value.done { color: #aed581; }
.loading { text-align: center; padding: 60px; color: #667788; }
.error { text-align: center; padding: 40px; color: #e57373; }
.error .detail { font-size: 13px; color: #667788; margin-top: 8px; }
.refresh-btn { background: #2a5a7a; color: #fff; border: none; padding: 8px 20px; border-radius: 6px; cursor: pointer; font-size: 13px; transition: background 0.2s; }
.refresh-btn:hover { background: #3a7a9a; }
@media (max-width: 900px) { .row-4 { grid-template-columns: repeat(2, 1fr); } .row-3 { grid-template-columns: 1fr; } .row-2 { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>ESP AI Server <span>管理员仪表盘</span></h1>
  </div>
  <div style="display:flex;align-items:center;gap:16px;">
    <span class="update-time" id="updateTime">加载中...</span>
    <button class="refresh-btn" onclick="refreshAll()">&#x21bb; 刷新</button>
  </div>
</div>
<div id="loginPage" style="display:none;">
  <div style="max-width:400px;margin:80px auto;text-align:center;">
    <div style="font-size:28px;font-weight:700;color:#4fc3f7;margin-bottom:8px;">管理员登录</div>
    <div style="color:#667788;margin-bottom:32px;font-size:14px;">请输入管理员账号密码</div>
    <div style="background:#1a2a3a;border-radius:12px;border:1px solid #1e3a4a;padding:32px;">
      <input id="loginEmail" type="email" placeholder="邮箱" style="width:100%;padding:12px 16px;background:#0f1923;border:1px solid #1e3a4a;border-radius:8px;color:#e0e6ed;font-size:14px;margin-bottom:12px;outline:none;">
      <input id="loginPassword" type="password" placeholder="密码" style="width:100%;padding:12px 16px;background:#0f1923;border:1px solid #1e3a4a;border-radius:8px;color:#e0e6ed;font-size:14px;margin-bottom:20px;outline:none;">
      <div id="loginError" style="color:#e57373;font-size:13px;margin-bottom:12px;display:none;"></div>
      <button onclick="doLogin()" style="width:100%;padding:12px;background:#2a5a7a;color:#fff;border:none;border-radius:8px;font-size:15px;cursor:pointer;">登录</button>
    </div>
  </div>
</div>
<div id="dashboardPage" style="display:none;">
  <div class="nav-tabs">
    <button class="nav-tab active" onclick="switchTab('overview',this)">&#x1F4CA; 概览</button>
    <button class="nav-tab" onclick="switchTab('metrics',this)">&#x2699; 性能指标</button>
    <button class="nav-tab" onclick="switchTab('pools',this)">&#x1F4E1; 连接池</button>
    <button class="nav-tab" onclick="switchTab('system',this)">&#x1F4BB; 系统信息</button>
  </div>

  <div id="tab-overview" class="tab-content active">
    <div class="row row-4" id="statsCards">
      <div class="card loading" style="grid-column:1/-1;">加载统计信息中...</div>
    </div>
    <div class="section-title">&#x1F504; 实时动态</div>
    <div class="row row-2">
      <div class="card" id="lastLogsCard">
        <div class="label">最近的日志</div>
        <div id="lastLogs" style="font-size:12px;color:#667788;font-family:monospace;line-height:1.8;max-height:300px;overflow-y:auto;">加载中...</div>
      </div>
      <div class="card" id="deviceListCard">
        <div class="label">在线设备</div>
        <div id="onlineDevices" style="font-size:12px;color:#667788;font-family:monospace;line-height:1.8;max-height:300px;overflow-y:auto;">加载中...</div>
      </div>
    </div>
  </div>

  <div id="tab-metrics" class="tab-content">
    <div class="row row-3" id="metricsCards">
      <div class="card loading" style="grid-column:1/-1;">加载性能指标中...</div>
    </div>
    <div class="section-title">&#x1F4CA; 系统资源</div>
    <div class="row row-4" id="systemResourceCards">
      <div class="card loading" style="grid-column:1/-1;">加载中...</div>
    </div>
  </div>

  <div id="tab-pools" class="tab-content">
    <div class="section-title">&#x1F4E1; 连接池详情</div>
    <div id="poolDetails" class="pool-grid">
      <div class="loading" style="grid-column:1/-1;">加载连接池信息中...</div>
    </div>
  </div>

  <div id="tab-system" class="tab-content">
    <div class="row row-2" id="systemInfoCards">
      <div class="card loading" style="grid-column:1/-1;">加载系统信息中...</div>
    </div>
  </div>
</div>
</div>
<script>
let lastMetrics = null;
let token = localStorage.getItem('admin_token') || '';

function switchTab(name, btn) {
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
}
function updateTime() {
  document.getElementById('updateTime').textContent = '更新于 ' + new Date().toLocaleString('zh-CN');
}
function getAuthHeaders() {
  const h = {};
  if (token) h['Authorization'] = 'Bearer ' + token;
  return h;
}
async function fetchJSON(url) {
  const res = await fetch(url, { headers: getAuthHeaders() });
  if (res.status === 401) { token = ''; localStorage.removeItem('admin_token'); showLogin(); throw new Error('未登录'); }
  const data = await res.json();
  if (data.code !== 0) throw new Error(data.message);
  return data.data;
}
async function doLogin() {
  const email = document.getElementById('loginEmail').value.trim();
  const password = document.getElementById('loginPassword').value;
  document.getElementById('loginError').style.display = 'none';
  if (!email || !password) { document.getElementById('loginError').textContent = '请输入邮箱和密码'; document.getElementById('loginError').style.display = 'block'; return; }
  try {
    const res = await fetch('/api/v1/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) });
    const data = await res.json();
    if (data.code !== 0) throw new Error(data.message || '登录失败');
    token = data.data.access_token;
    localStorage.setItem('admin_token', token);
    showDashboard();
    refreshAll();
  } catch(e) {
    document.getElementById('loginError').textContent = e.message;
    document.getElementById('loginError').style.display = 'block';
  }
}
function showLogin() {
  document.getElementById('loginPage').style.display = 'block';
  document.getElementById('dashboardPage').style.display = 'none';
  document.querySelector('.header').style.display = 'none';
}
function showDashboard() {
  document.getElementById('loginPage').style.display = 'none';
  document.getElementById('dashboardPage').style.display = 'block';
  document.querySelector('.header').style.display = 'flex';
}
async function checkAuth() {
  if (!token) { showLogin(); return; }
  try {
    await fetchJSON('/api/v1/admin/stats');
    showDashboard();
  } catch(e) { showLogin(); }
}
async function refreshAll() {
  updateTime();
  try {
    const [stats, sysInfo, metrics] = await Promise.all([
      fetchJSON('/api/v1/admin/stats'),
      fetchJSON('/api/v1/admin/system/info'),
      fetchJSON('/api/v1/system/metrics').catch(() => null)
    ]);
    lastMetrics = metrics;
    renderStats(stats);
    renderSysInfo(sysInfo);
    if (metrics) renderMetrics(metrics);
    loadLogs();
    loadDevices();
  } catch(e) {
    document.querySelectorAll('.card.loading').forEach(c => {
      c.className = 'card error';
      c.innerHTML = '<div>&#x26A0; 加载失败: ' + e.message + '</div>';
    });
  }
}
function renderStats(stats) {
  document.getElementById('statsCards').innerHTML = [
    { label: '用户总数', value: stats.users, sub: '管理员 ' + stats.admins, cls: 'users', icon: '&#x1F464;' },
    { label: '设备总数', value: stats.devices, sub: '已绑定 ' + stats.bound_devices, cls: 'devices', icon: '&#x1F4F1;' },
    { label: '在线设备', value: stats.online_devices, sub: '在线率 ' + (stats.devices ? (stats.online_devices/stats.devices*100).toFixed(1) : 0) + '%', cls: 'online', icon: '&#x1F4E1;' },
    { label: '未绑定设备', value: stats.devices - stats.bound_devices, sub: '待绑定设备数', cls: 'cpu', icon: '&#x1F50C;' },
  ].map(c => '<div class="card ' + c.cls + '"><div class="label">' + c.icon + ' ' + c.label + '</div><div class="value">' + c.value + '</div><div class="sub">' + c.sub + '</div></div>').join('');
}
function renderSysInfo(info) {
  const memGB = info.memory_bytes ? (info.memory_bytes / 1024 / 1024 / 1024).toFixed(2) : 'N/A';
  const dbSize = info.db_size ? (info.db_size / 1024 / 1024).toFixed(2) + ' MB' : 'N/A';
  const logSize = info.log_size ? (info.log_size / 1024 / 1024).toFixed(2) + ' MB' : 'N/A';
  document.getElementById('systemInfoCards').innerHTML = [
    { label: '服务器版本', value: info.server_version, cls: 'users' },
    { label: 'Python 版本', value: info.python_version, cls: 'memory' },
    { label: '运行平台', value: info.platform, cls: 'threads' },
    { label: '数据库大小', value: dbSize, cls: 'db' },
    { label: '日志大小', value: logSize, cls: 'cpu' },
    { label: '注册设备', value: info.registry_devices, cls: 'online' },
  ].map(c => '<div class="card ' + c.cls + '"><div class="label">' + c.label + '</div><div class="value" style="font-size:18px;">' + c.value + '</div></div>').join('');
}
function renderMetrics(metrics) {
  const sys = metrics.system || {};
  const cpu = sys.cpu_percent != null ? sys.cpu_percent.toFixed(1) + '%' : 'N/A';
  const mem = sys.memory_mb != null ? sys.memory_mb.toFixed(1) + ' MB' : 'N/A';
  const memPct = sys.memory_percent != null ? sys.memory_percent.toFixed(1) + '%' : 'N/A';
  const threads = sys.num_threads != null ? sys.num_threads : 'N/A';
  const uptime = metrics.uptime ? Math.floor((Date.now()/1000 - metrics.uptime)/60) + ' 分钟' : 'N/A';

  document.getElementById('metricsCards').innerHTML = [
    { label: 'CPU 使用率', value: cpu, cls: 'cpu' },
    { label: '内存使用', value: mem, cls: 'memory' },
    { label: '内存占比', value: memPct, cls: 'db' },
    { label: '线程数', value: threads, cls: 'threads' },
  ].map(c => '<div class="card ' + c.cls + '"><div class="label">' + c.label + '</div><div class="value">' + c.value + '</div></div>').join('');

  // 并发统计
  const conc = metrics.concurrency || {};
  const concItems = [
    { label: '信号量', value: conc.semaphore_size ?? 'N/A', cls: 'semaphore' },
    { label: '活跃任务', value: conc.active_tasks ?? 'N/A', cls: 'active' },
    { label: '排队任务', value: conc.queued_tasks ?? 'N/A', cls: 'queued' },
    { label: '已完成任务', value: conc.completed_tasks ?? 'N/A', cls: 'done' },
  ];
  document.getElementById('systemResourceCards').innerHTML =
    '<div style="grid-column:1/-1;"><div class="section-title">&#x2699; 并发控制</div><div class="concurrency-grid">' +
    concItems.map(c => '<div class="concurrency-item"><div class="conc-label">' + c.label + '</div><div class="conc-value ' + c.cls + '">' + c.value + '</div></div>').join('') +
    '</div></div>';

  // 连接池
  const pools = metrics.pools || {};
  const poolHtml = Object.entries(pools).map(([name, p]) => {
    if (typeof p === 'object') {
      return '<div class="pool-item"><div class="pool-name">' + name + '</div><div class="pool-stat">' +
        Object.entries(p).map(([k, v]) => k + ': ' + v).join(' | ') +
        '</div></div>';
    }
    return '<div class="pool-item"><div class="pool-name">' + name + '</div><div class="pool-stat">' + p + '</div></div>';
  }).join('');
  if (poolHtml) document.getElementById('poolDetails').innerHTML = poolHtml || '<div style="color:#667788;text-align:center;padding:20px;">暂无连接池信息</div>';
}
async function loadLogs() {
  try {
    const data = await fetchJSON('/api/v1/admin/logs?lines=15');
    const lines = data.lines || [];
    document.getElementById('lastLogs').innerHTML = lines.length
      ? lines.map(l => escapeHtml(l)).join('<br>')
      : '暂无日志';
  } catch(e) {
    document.getElementById('lastLogs').textContent = '加载日志失败: ' + e.message;
  }
}
async function loadDevices() {
  try {
    const data = await fetchJSON('/api/v1/admin/devices');
    const devices = data.devices || data || [];
    if (Array.isArray(devices)) {
      const online = devices.filter(d => d.online);
      document.getElementById('onlineDevices').innerHTML = online.length
        ? online.map(d => '&#x1F7E2; ' + escapeHtml(d.name || d.device_id) + ' (' + escapeHtml(d.mac || '') + ')').join('<br>')
        : '暂无在线设备';
    } else {
      document.getElementById('onlineDevices').textContent = '暂无设备数据';
    }
  } catch(e) {
    document.getElementById('onlineDevices').textContent = '加载设备列表失败';
  }
}
function escapeHtml(s) {
  if (typeof s !== 'string') return s;
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
checkAuth();
if (token) setInterval(refreshAll, 30000);
</script>
</body>
</html>"""
