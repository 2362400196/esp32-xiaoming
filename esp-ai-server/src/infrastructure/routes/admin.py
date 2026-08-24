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

from fastapi import APIRouter, Depends, HTTPException, Query
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
        ? online.map(d => '&#x1F7E2; ' + escapeHtml(d.name || d.device_id) + ' (' + (d.mac || '') + ')').join('<br>')
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
