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

import asyncio
import json
import os
import secrets
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import csv
import io
import logging
import re
import shutil

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
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


def _serialize_device(device: DeviceModel, owner_email: str = "", owner_nickname: str = "") -> dict:
    return {
        "device_id": device.device_id,
        "name": device.name,
        "mac": device.mac_address,
        "device_key": device.device_key,
        "user_id": device.user_id,
        "owner_email": owner_email,
        "owner_nickname": owner_nickname,
        "online": _device_online(device),
        "bound_at": device.bound_at,
        "last_seen": device.last_seen,
        "created_at": device.created_at,
        "updated_at": device.updated_at,
        "is_banned": device.is_banned,
        "ban_reason": device.ban_reason,
        "banned_at": device.banned_at,
    }


async def _load_owner_map(session, user_ids: set[str | None]) -> dict:
    """批量查询设备归属用户信息，返回 user_id -> {email, nickname}"""
    ids = {u for u in user_ids if u}
    if not ids:
        return {}
    rows = await session.execute(
        select(UserModel.id, UserModel.email, UserModel.nickname).where(UserModel.id.in_(ids))
    )
    return {uid: {"email": email, "nickname": nickname} for uid, email, nickname in rows}


# ==================== 统计 ====================

@router.get("/metrics")
async def admin_metrics(_: UserModel = Depends(require_admin)):
    """管理员性能指标（JSON）。

    /system/metrics 返回的是 Prometheus 文本格式，前端无法解析——
    此端点提供结构化指标供仪表盘展示：
    - system: CPU/内存/线程
    - concurrency: 全局并发信号量 + 后台任务计数（活跃/排队/已完成）
    - pools: 各连接池状态
    - uptime: 进程启动时间戳
    """
    import os

    import psutil

    from src.infrastructure import task_manager
    from src.infrastructure.concurrency import get_stats as get_concurrency_stats
    from src.infrastructure.connection_pool import PoolManager

    process = psutil.Process(os.getpid())
    memory_info = process.memory_info()
    # CPU 显示整机使用率：服务器进程空闲时自身占用≈0%，看进程值没有参考意义
    cpu_percent = psutil.cpu_percent(interval=0.2)
    conc = get_concurrency_stats()

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "system": {
                "cpu_percent": cpu_percent,
                "memory_mb": memory_info.rss / 1024 / 1024,
                "memory_percent": process.memory_percent(),
                "num_threads": process.num_threads(),
            },
            "concurrency": {
                "semaphore_size": conc.get("global_concurrency_max"),
                "semaphore_available": conc.get("global_concurrency_available"),
                "limit_enabled": conc.get("global_concurrency_limit_enabled", False),
                # 后台任务：asyncio task 无排队概念，排队恒为 0
                "active_tasks": task_manager.get_active_count(),
                "queued_tasks": 0,
                "completed_tasks": task_manager.get_completed_count(),
                # 活跃任务明细：[{name, elapsed}]，供仪表盘点击查看
                "active_task_list": task_manager.list_active_tasks(),
                # 最近完成的任务（最新在前，最多 20 条）：任务多为毫秒级短命任务，
                # 仅靠活跃快照大多数时刻是空的，配最近完成才能看清跑过什么
                "recent_task_list": task_manager.list_recent_completed(),
            },
            "pools": PoolManager.get_all_stats(),
            "uptime": process.create_time(),
        },
    }

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
        owners = await _load_owner_map(session, {d.user_id for d in devices})

    # 注册表快照（诊断用：核对运行时连接与数据库设备的映射关系）
    registry_snapshot = []
    registry = get_device_registry()
    if registry:
        for key in registry.get_all_ids():
            entry = registry.resolve(key)
            if not entry:
                continue
            channel = entry.get("channel")
            registry_snapshot.append({
                "key": key,
                "mac": entry.get("mac", ""),
                "connected": bool(channel and getattr(channel, "connected", False)),
                "register_time": entry.get("register_time", 0),
            })

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "devices": [
                _serialize_device(
                    d,
                    owners.get(d.user_id or "", {}).get("email", ""),
                    owners.get(d.user_id or "", {}).get("nickname", ""),
                )
                for d in devices
            ],
            "registry_devices": registry_snapshot,
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


# ==================== 固件管理 ====================

FIRMWARE_ALLOWED_EXT = {".bin", ".elf", ".hex"}
FIRMWARE_MAX_BYTES = 32 * 1024 * 1024  # 32MB（固件约 6MB，留足余量）


def _firmware_meta() -> dict:
    from src.infrastructure.device_api import load_firmware_meta
    return load_firmware_meta()


def _sanitize_firmware_name(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in "._-")


def _auto_bin_id(filename: str, meta: dict) -> str:
    """兜底生成 bin_id：默认取文件名主干；与其他固件冲突时追加时间戳保证唯一"""
    stem = Path(filename).stem
    current = meta.get(filename, {}).get("bin_id", "")
    if current and current == stem:
        return stem  # 同一文件重复上传，保持 bin_id 稳定
    used = {m.get("bin_id", "") for m in meta.values() if m.get("bin_id")}
    if stem not in used:
        return stem
    import time as _t
    return f"{stem}-{int(_t.time())}"


# 板卡 bin_id：32 位十六进制字符串（board_config_t.bin_id，编译进固件的 C 字符串常量）
_BIN_ID_RE = re.compile(rb"(?<![0-9a-fA-F])([0-9a-fA-F]{32})(?![0-9a-fA-F])")


def _extract_bin_id_from_firmware(content: bytes) -> str:
    """从固件二进制中提取 bin_id（板卡编译 ID），提取不到返回空串"""
    m = _BIN_ID_RE.search(content)
    if m:
        return m.group(1).decode("ascii")
    return ""


@router.get("/firmwares")
async def admin_list_firmwares(_: UserModel = Depends(require_admin)):
    # 固件列表（含 bin_id/版本/上传者/启用状态）
    from src.infrastructure.device_api import list_firmwares
    meta = _firmware_meta()
    items = []
    for f in await asyncio.to_thread(list_firmwares):
        m = meta.get(f.filename, {})
        items.append({
            "filename": f.filename,
            "size": f.size,
            "created_time": f.created_time,
            "download_url": f.download_url,
            "bin_id": m.get("bin_id", ""),
            "version": m.get("version", "") or f.version or "",
            "uploaded_by": m.get("uploaded_by", ""),
            "uploaded_at": m.get("uploaded_at"),
            "active": bool(m.get("active")),
        })
    # 启用中的排最前，其余按时间倒序
    items.sort(key=lambda x: (not x["active"], -x["created_time"]))
    return {"code": 0, "message": "ok", "data": {"firmwares": items}}


@router.post("/firmwares/upload")
async def admin_upload_firmware(
    request: Request,
    file: UploadFile = File(...),
    bin_id: str = Form(""),
    bin_id_mode: str = Form("auto"),
    version: str = Form(""),
    admin: UserModel = Depends(require_admin),
):
    # 上传固件并登记 bin_id/版本（上传后自动设为启用中，作为设备 OTA 回退目标）
    # bin_id_mode: auto=一键生成（取文件名主干，冲突追加时间戳）; custom=自定义输入
    from src.infrastructure.device_api import (
        FIRMWARE_DIR, load_firmware_meta, save_firmware_meta,
    )
    import time as _time

    if not file.filename:
        raise HTTPException(400, "未选择文件")
    ext = Path(file.filename).suffix.lower()
    if ext not in FIRMWARE_ALLOWED_EXT:
        raise HTTPException(400, "仅支持固件格式: " + ", ".join(sorted(FIRMWARE_ALLOWED_EXT)))

    safe_filename = _sanitize_firmware_name(file.filename)
    if not safe_filename:
        raise HTTPException(400, "文件名不合法")

    content = await file.read(FIRMWARE_MAX_BYTES + 1)
    if len(content) > FIRMWARE_MAX_BYTES:
        raise HTTPException(400, "固件文件过大（>32MB）")

    def _write():
        FIRMWARE_DIR.mkdir(parents=True, exist_ok=True)
        (FIRMWARE_DIR / safe_filename).write_bytes(content)

    await asyncio.to_thread(_write)

    # 元数据登记：新上传自动设为启用中（单选）
    meta = load_firmware_meta()
    for name, m in meta.items():
        m["active"] = False

    # bin_id：auto=从固件中识别（提取不到回退文件名主干）; custom=自定义输入
    if bin_id_mode == "auto" or not bin_id.strip():
        bin_id = _extract_bin_id_from_firmware(content) or _auto_bin_id(safe_filename, meta)
    else:
        bin_id = bin_id.strip()

    meta[safe_filename] = {
        "bin_id": bin_id,
        "version": version.strip(),
        "uploaded_by": admin.email,
        "uploaded_at": _time.time(),
        "active": True,
    }
    await asyncio.to_thread(save_firmware_meta, meta)

    _add_oplog(admin.email, "firmware_upload", "上传固件 " + safe_filename + "（bin_id=" + (bin_id or "未填写") + "）")
    logger.info("[Admin] 固件上传: %s（%d 字节, bin_id=%s, 上传者 %s）",
                safe_filename, len(content), bin_id or "未填写", admin.email)
    return {
        "code": 0,
        "message": "固件已上传并设为启用中",
        "data": {"filename": safe_filename, "bin_id": bin_id, "version": version, "active": True},
    }


@router.post("/firmwares/{filename}/set-active")
async def admin_set_active_firmware(filename: str, admin: UserModel = Depends(require_admin)):
    # 设置启用中的固件（设备 OTA 无显式配置时的回退目标）
    from src.infrastructure.device_api import set_active_firmware
    safe_filename = _sanitize_firmware_name(filename)
    ok = await asyncio.to_thread(set_active_firmware, safe_filename)
    if not ok:
        raise HTTPException(404, "固件文件不存在")
    _add_oplog(admin.email, "firmware_set_active", "启用固件 " + safe_filename)
    return {"code": 0, "message": "已启用固件 " + safe_filename}


@router.delete("/firmwares/{filename}")
async def admin_delete_firmware(filename: str, admin: UserModel = Depends(require_admin)):
    # 删除固件文件及其元数据
    from src.infrastructure.device_api import FIRMWARE_DIR, load_firmware_meta, save_firmware_meta
    safe_filename = _sanitize_firmware_name(filename)
    filepath = FIRMWARE_DIR / safe_filename
    if not filepath.exists():
        raise HTTPException(404, "固件文件不存在")

    def _delete():
        filepath.unlink()

    await asyncio.to_thread(_delete)
    meta = load_firmware_meta()
    was_active = bool(meta.get(safe_filename, {}).get("active"))
    meta.pop(safe_filename, None)
    await asyncio.to_thread(save_firmware_meta, meta)

    _add_oplog(admin.email, "firmware_delete", "删除固件 " + safe_filename)
    return {"code": 0, "message": "固件已删除", "data": {"was_active": was_active}}


# ==================== 用户管理增强 ====================

@router.post("/devices/{device_id}/wakeup")
async def admin_device_wakeup(device_id: str, _: UserModel = Depends(require_admin)):
    """管理员远程唤醒单台设备（复用设备控制内部逻辑，跳过归属校验）"""
    from src.infrastructure.routes.devices import _wakeup
    return await _wakeup(device_id)


@router.get("/devices/{device_id}/detail")
async def admin_device_detail(device_id: str, _: UserModel = Depends(require_admin)):
    """设备详情：基本信息 + 运行时状态（连接时长/会话/固件/OTA）"""
    async with get_session_ctx() as session:
        device = await session.get(DeviceModel, device_id)
        if not device:
            raise HTTPException(404, "Device not found")
        owners = await _load_owner_map(session, {device.user_id})
    owner = owners.get(device.user_id or "", {})

    registry = get_device_registry()
    entry = None
    if registry:
        entry = registry.resolve(device.device_id)
        if not entry and device.mac_address:
            entry = registry.get_by_mac(device.mac_address)
        if not entry and device.device_key:
            entry = registry.resolve(device.device_key)

    channel = (entry or {}).get("channel")
    online = bool(channel and getattr(channel, "connected", False))
    session_obj = (entry or {}).get("session")
    fsm = (entry or {}).get("fsm")
    register_time = (entry or {}).get("register_time")

    detail = _serialize_device(device, owner.get("email", ""), owner.get("nickname", ""))
    detail.update({
        # 运行时（仅在线时有值）
        "online_seconds": round(time.time() - register_time, 0) if (online and register_time) else None,
        "connected_at": register_time if online else None,
        "session_id": (getattr(session_obj, "session_id", "") or "") if session_obj else "",
        "device_state": (fsm.get() if fsm and hasattr(fsm, "get") else "unknown") if fsm else "unknown",
        "tts_playing": bool(getattr(session_obj, "tts_playing", False)) if session_obj else False,
        "last_wakeup_time": getattr(session_obj, "last_wakeup_time", None) if session_obj else None,
        # 固件与 OTA
        "firmware_version": (entry or {}).get("firmware_version", "") or "",
        "bin_id": (entry or {}).get("bin_id", "") or "",
        "ota_updating": (entry or {}).get("ota_updating", False),
        "ota_progress": (entry or {}).get("ota_progress", 0.0),
        # 其他
        "enabled_plugins": device.enabled_plugins or [],
    })
    return {"code": 0, "message": "ok", "data": detail}


@router.get("/devices/{device_id}/ota-check")
async def admin_device_ota_check(device_id: str, _: UserModel = Depends(require_admin)):
    """检测设备是否有可用升级（与 /sdk/query_new_ota 同一套判断逻辑，面向管理员）"""
    from src.infrastructure.config import get_settings

    async with get_session_ctx() as session:
        device = await session.get(DeviceModel, device_id)
        if not device:
            raise HTTPException(404, "Device not found")

    registry = get_device_registry()
    entry = None
    if registry:
        entry = registry.resolve(device.device_id)
        if not entry and device.mac_address:
            entry = registry.get_by_mac(device.mac_address)
        if not entry and device.device_key:
            entry = registry.resolve(device.device_key)
    current_version = (entry or {}).get("firmware_version", "") or ""
    device_bin_id = (entry or {}).get("bin_id", "") or ""

    settings = get_settings()
    ota = settings.ota
    ota_enabled = bool(device.ota_enabled) and bool(ota.enabled if ota else True)

    # OTA 目标优先级：设备级配置 → 固件管理「启用中」固件 → 全局环境变量
    from src.infrastructure.device_api import get_active_firmware
    active = get_active_firmware()
    if device.ota_bin_id or device.ota_bin_url or device.ota_version:
        target_version = device.ota_version
        target_url = device.ota_bin_url
        target_bin_id = device.ota_bin_id
        target_source = "设备级配置"
    elif active:
        target_version = active["version"]
        target_url = active["download_url"]
        target_bin_id = active["bin_id"]
        target_source = "固件管理（启用中固件）"
    else:
        target_version = ota.version if ota else ""
        target_url = ota.bin_url if ota else ""
        target_bin_id = ota.bin_id if ota else ""
        target_source = "全局环境变量"

    has_update = False
    reason = ""
    if not ota_enabled:
        reason = "OTA 已停用（设备级或全局）"
    elif not target_url:
        reason = "未配置固件下载地址"
    # ── 优先级 1：bin_id 比对（与设备自检 /sdk/query_new_ota 同一套语义）──
    # bin_id 是固件包唯一标识，两侧都有且一致即视为最新，不看版本号
    elif target_bin_id and device_bin_id:
        if target_bin_id == device_bin_id:
            reason = f"固件 bin_id 一致，已是最新（当前 {current_version or '未知'}）"
        else:
            has_update = True
            reason = f"固件 bin_id 不同（设备 {device_bin_id} / 目标 {target_bin_id}），需要升级"
    elif not current_version:
        reason = "设备固件版本未知（需设备在线并重连一次上报版本）"
    elif not target_version:
        reason = f"未配置目标版本号，视为最新（当前 {current_version}）"
    # ── 优先级 2：版本号语义化比对（bin_id 缺失任一侧时回退到这里）──
    else:
        comparable = True
        try:
            from packaging.version import Version
            if Version(target_version) <= Version(current_version):
                reason = f"已是最新版本 {current_version}（目标 {target_version}）"
            else:
                has_update = True
                reason = f"发现新版本 {target_version}（当前 {current_version}）"
        except Exception:
            comparable = False
        if not comparable:
            # 版本号无法解析时退化为字符串相等判断
            if target_version == current_version:
                reason = f"已是最新版本 {current_version}"
            else:
                has_update = True
                reason = f"发现新版本 {target_version}（当前 {current_version}）"

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "has_update": has_update,
            "reason": reason,
            "current_version": current_version,
            "target_version": target_version,
            "target_url": target_url,
            "target_source": target_source,
            "ota_enabled": ota_enabled,
        },
    }


@router.post("/devices/{device_id}/ota-force")
async def admin_device_ota_force(device_id: str, admin: UserModel = Depends(require_admin)):
    """强制设备 OTA 升级：直接下发固件 URL（跳过版本比对，设备收到即下载刷写）。

    前提：设备在线，且设备固件支持 ota_update 指令（v1.4+ 客户端）。
    """
    from src.infrastructure.config import get_settings
    from src.infrastructure.device_api import _send_ota_to_device

    async with get_session_ctx() as session:
        device = await session.get(DeviceModel, device_id)
        if not device:
            raise HTTPException(404, "Device not found")

    registry = get_device_registry()
    entry = None
    if registry:
        entry = registry.resolve(device.device_id)
        if not entry and device.mac_address:
            entry = registry.get_by_mac(device.mac_address)
        if not entry and device.device_key:
            entry = registry.resolve(device.device_key)
    channel = (entry or {}).get("channel")
    if not (channel and getattr(channel, "connected", False)):
        raise HTTPException(400, "设备不在线，无法下发升级指令")

    # OTA 目标优先级与「检测升级」一致：设备级 → 固件管理启用中固件 → 全局环境变量
    settings = get_settings()
    ota = settings.ota
    from src.infrastructure.device_api import get_active_firmware
    active = get_active_firmware()
    if device.ota_bin_url:
        url = device.ota_bin_url
        version = device.ota_version
    elif active:
        url = active["download_url"]
        version = active["version"]
    else:
        url = ota.bin_url if ota else ""
        version = ota.version if ota else ""
    if not url:
        raise HTTPException(400, "未配置固件下载地址：请在固件管理上传固件，或配置 OTA_BIN_URL")
    if "your-server-ip" in url or "your-server" in url or "localhost" in url:
        # .env.example 的占位地址/回环地址设备不可达，直接拒绝并给出明确指引
        raise HTTPException(400, "固件下载地址不可达（含占位符 your-server-ip 或 localhost），"
                                 "请在固件管理上传固件（自动生成本机局域网地址）或修正 OTA_BIN_URL")

    result = await _send_ota_to_device(device.device_key, url, version)
    if not result.get("success"):
        raise HTTPException(400, result.get("error", "下发失败"))

    _add_oplog(admin.email, "force_ota", f"强制升级设备 {device_id}，固件: {url}")
    logger.info(f"[Admin] 强制 OTA 下发: device={device_id}, url={url}, version={version}")
    return {
        "code": 0,
        "message": "升级指令已下发，设备将在数秒内开始下载固件",
        "data": {"url": url, "version": version},
    }


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
        content = await asyncio.to_thread(path.read_text, "utf-8")
    except Exception as e:
        raise HTTPException(500, f"读取日志失败: {e}")
    all_lines = content.splitlines()
    formatted = [
        l if (l := _format_log_line(raw)) is not None else raw
        for raw in all_lines[-lines:]
    ]
    return {"code": 0, "message": "ok", "data": {"path": str(path), "lines": formatted}}


def _format_log_line(raw: str) -> str | None:
    """把 JSON-lines 文件日志格式化成与终端控制台一致的可读样式。

    文件日志是给日志收集用的 JSON（ts/level/msg/trace_id/session_id/device_id），
    终端是给人看的 `[时间] [级别] [trace/session/device] 消息`；
    非 JSON 行（uvicorn 访问日志等）原样返回 None 由调用方兜底。
    """
    raw = raw.strip()
    if not raw.startswith("{"):
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or "msg" not in obj:
        return None
    ts = str(obj.get("ts", ""))
    # ISO 时间戳 → 终端同款 HH:MM:SS.mmm
    short_ts = ts[11:23] if len(ts) >= 23 else ts
    ids = "/".join([
        str(obj.get("trace_id", "-") or "-"),
        str(obj.get("session_id", "-") or "-"),
        str(obj.get("device_id", "-") or "-"),
    ])
    level = str(obj.get("level", "INFO"))
    return f"[{short_ts}] [{level}] [{ids}] {obj['msg']}"


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
    """查看对话历史（短期记忆表）。

    注意：短期记忆按 WS 会话的 device_key（bound_* 随机标识）存储，
    而 devices 表主键是 MAC 式 device_id —— 历史版本按 device_id 查记忆
    导致列表恒为空。此处以记忆表实际存在的 device_id 为准，再映射回设备。
    """
    from src.infrastructure.db.models.memory import ShortTermMemoryModel
    from src.infrastructure.db.repositories.short_term_memory_repo import SqlShortTermMemoryRepository

    repo = SqlShortTermMemoryRepository()

    async with get_session_ctx() as session:
        devices = (await session.execute(select(DeviceModel))).scalars().all()
        owners = await _load_owner_map(session, {d.user_id for d in devices})
        # 记忆表实际存有对话的会话设备标识（去重）
        memory_ids = (await session.execute(
            select(ShortTermMemoryModel.device_id).distinct()
        )).scalars().all()

    # 记忆键 → 设备：device_key 优先（bound_*），回退 device_id（遗留数据）
    by_key = {d.device_key: d for d in devices if d.device_key}
    by_id = {d.device_id: d for d in devices}

    if device_id:
        # 前端筛选传的是 devices 表 device_id，转换为记忆键后查询
        dev = by_id.get(device_id)
        mem_key = (dev.device_key if dev else None) or device_id
        target_keys = [mem_key]
    else:
        target_keys = list(memory_ids)

    conversations = []
    for mem_id in target_keys:
        # 同步仓储走线程池，避免阻塞事件循环
        msgs = await asyncio.to_thread(repo.load, mem_id)
        if not msgs:
            continue
        dev = by_key.get(mem_id) or by_id.get(mem_id)
        owner = owners.get(dev.user_id or "", {}) if dev else {}
        conversations.append({
            "device_id": dev.device_id if dev else mem_id,
            "device_key": mem_id,
            "device_name": (dev.name if dev and dev.name else None) or mem_id,
            "owner_email": owner.get("email", "") if dev else "",
            "messages": msgs[-limit:],
        })

    conversations.sort(key=lambda c: max((m.get("timestamp") or 0) for m in c["messages"]), reverse=True)
    return {"code": 0, "data": {"conversations": conversations}}


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

# ==================== 健康检查扩展 ====================

async def _first_device_with(predicate) -> Optional[DeviceModel]:
    """返回第一个满足条件的设备（用于全局未配置时回退到设备级配置）"""
    async with get_session_ctx() as session:
        devices = (await session.execute(select(DeviceModel))).scalars().all()
        for d in devices:
            if predicate(d):
                return d
    return None


async def _check_llm_connectivity() -> dict:
    """LLM 连通性：发送极简 chat 请求（max_tokens=1），验证 Key/端点可用"""
    from src.infrastructure.config import get_settings
    settings = get_settings()
    api_key = settings.llm.api_key
    base_url = settings.llm.base_url
    model = settings.llm.model
    if not api_key:
        dev = await _first_device_with(lambda d: bool(d.llm_api_key))
        if dev:
            api_key = dev.llm_api_key
            base_url = dev.llm_base_url or base_url
            model = dev.llm_model or model
    if not api_key:
        return {"status": "skipped", "reason": "未配置 LLM API Key"}
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or None,
            timeout=10,
            max_retries=0,
        )
        start = time.monotonic()
        try:
            await client.chat.completions.create(
                model=model or "gpt-3.5-turbo",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
            )
        finally:
            await client.close()
        return {"status": "ok", "latency_ms": round((time.monotonic() - start) * 1000)}
    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}


async def _check_tts_connectivity() -> dict:
    """TTS 连通性：建立到火山引擎 TTS 的 WebSocket 连接（验证可达性与鉴权）"""
    from src.infrastructure.config import get_settings
    settings = get_settings()
    api_key = settings.tts.api_key
    voice_type = settings.tts.voice_type
    if not api_key:
        dev = await _first_device_with(lambda d: bool((d.tts_config or {}).get("api_key")))
        if dev:
            tts_cfg = dev.tts_config or {}
            api_key = tts_cfg.get("api_key")
            voice_type = tts_cfg.get("voice_type") or voice_type
    if not api_key:
        return {"status": "skipped", "reason": "未配置 TTS API Key"}
    try:
        from src.interfaces.tts_gateways import VolcEngineTTSGateway
        gateway = VolcEngineTTSGateway({"api_key": api_key, "voice_type": voice_type})
        start = time.monotonic()
        conn = await asyncio.wait_for(gateway._create_connection(), timeout=10)
        try:
            await conn.close()
        except Exception:
            pass
        return {"status": "ok", "latency_ms": round((time.monotonic() - start) * 1000)}
    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}


async def _check_asr_connectivity() -> dict:
    """ASR 连通性：建立到火山引擎 ASR 的 WebSocket 连接（验证可达性与鉴权）"""
    from src.infrastructure.config import get_settings
    settings = get_settings()
    api_key = settings.asr.volcengine_api_key
    resource_id = settings.asr.volcengine_resource_id
    model_name = settings.asr.volcengine_model
    if not api_key:
        dev = await _first_device_with(lambda d: bool((d.asr_config or {}).get("volcengine", {}).get("api_key")))
        if dev:
            asr_cfg = (dev.asr_config or {}).get("volcengine", {})
            api_key = asr_cfg.get("api_key")
            resource_id = asr_cfg.get("resource_id") or resource_id
            model_name = asr_cfg.get("model_name") or model_name
    if not api_key:
        return {"status": "skipped", "reason": "未配置 ASR API Key"}
    try:
        import websockets
        from src.interfaces.asr.volcengine import VolcEngineASRGateway
        gateway = VolcEngineASRGateway({
            "api_key": api_key,
            "resource_id": resource_id,
            "model_name": model_name,
        })
        start = time.monotonic()
        conn = await asyncio.wait_for(
            websockets.connect(gateway._build_url(), additional_headers=gateway._get_headers(), open_timeout=10),
            timeout=10,
        )
        try:
            await conn.close()
        except Exception:
            pass
        return {"status": "ok", "latency_ms": round((time.monotonic() - start) * 1000)}
    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}


def _check_system_resources() -> dict:
    """系统资源：进程内存/CPU、系统内存占用"""
    try:
        import psutil
        proc = psutil.Process()
        rss_mb = round(proc.memory_info().rss / (1024**2), 1)
        cpu_pct = proc.cpu_percent(interval=0.3)
        vm = psutil.virtual_memory()
        return {
            "status": "ok",
            "process_memory_mb": rss_mb,
            "process_cpu_pct": cpu_pct,
            "system_memory_used_pct": round(vm.percent, 1),
            "system_memory_total_gb": round(vm.total / (1024**3), 1),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}


def _count_recent_errors(log_path: Path, minutes: int = 30) -> int:
    """统计日志文件最近 N 分钟内的 ERROR/CRITICAL 条数"""
    if not log_path.exists():
        return 0
    cutoff = time.time() - minutes * 60
    count = 0
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-2000:]
    except Exception:
        return 0
    for line in lines:
        try:
            obj = json.loads(line)
            if obj.get("level") not in ("ERROR", "CRITICAL"):
                continue
            ts = obj.get("ts", "")
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.timestamp() >= cutoff:
                    count += 1
            except Exception:
                count += 1
        except Exception:
            continue
    return count


def _check_runtime_status() -> dict:
    """运行时状态：在线设备数、ASR/TTS 连接池、最近错误日志"""
    result = {"status": "ok"}
    try:
        registry = get_device_registry()
        result["online_devices"] = len(registry.get_all_ids()) if registry else 0
    except Exception as e:
        result["online_devices"] = -1
        result["registry_error"] = str(e)[:200]
    try:
        from src.interfaces.asr.volcengine import VolcEngineASRGateway
        from src.interfaces.tts_gateways import VolcEngineTTSGateway
        asr_pools = VolcEngineASRGateway._pools
        tts_pools = VolcEngineTTSGateway._pools
        result["asr_pools"] = len(asr_pools)
        result["tts_pools"] = len(tts_pools)
        result["asr_active_conns"] = sum(p._active_count for p in asr_pools.values() if not p.is_closed)
        result["tts_active_conns"] = sum(p._active_count for p in tts_pools.values() if not p.is_closed)
    except Exception as e:
        result["pool_error"] = str(e)[:200]
    try:
        result["errors_last_30m"] = _count_recent_errors(_project_root() / "logs" / "esp_ai.log", minutes=30)
    except Exception as e:
        result["log_error"] = str(e)[:200]
    return result


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
        # TTS 实际生效依赖 tts_config.api_key（tts_type 仅前端创建时写入，
        # 通过 WebSocket 自动注册/网页保存的设备可能为空），故两者任一非空即视为已配置
        tts_configured = sum(1 for d in devices if d.tts_type or (d.tts_config or {}).get("api_key"))
        results["services"] = {"status": "ok", "asr_configured": asr_configured, "llm_configured": llm_configured, "tts_configured": tts_configured}

    # 5. 系统资源
    results["system"] = _check_system_resources()

    # 6. 运行时状态
    results["runtime"] = _check_runtime_status()

    # 7. 外部服务连通性（并发执行，各限时 10s；未配置的服务跳过，不算异常）
    ext = await asyncio.gather(
        _check_llm_connectivity(),
        _check_tts_connectivity(),
        _check_asr_connectivity(),
    )
    results["external_services"] = {
        "status": "ok" if all(r.get("status") != "error" for r in ext) else "degraded",
        "llm": ext[0],
        "tts": ext[1],
        "asr": ext[2],
    }

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
async def admin_operation_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: UserModel = Depends(require_admin),
):
    """分页查看操作日志（按时间倒序，最新在前）"""
    logs = _load_oplogs()  # _add_oplog 用 insert(0) 写入，文件序即最新在前
    total = len(logs)
    start = (page - 1) * page_size
    return {
        "code": 0,
        "data": {
            "logs": logs[start:start + page_size],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        },
    }


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


# ==================== 系统设置（网站设置） ====================

# 设置项分组（仪表盘「设置」页签的分区展示）
SETTING_GROUPS = [
    {"id": "basic", "label": "基础"},
    {"id": "llm", "label": "大模型 (LLM)"},
    {"id": "asr", "label": "语音识别 (ASR)"},
    {"id": "tts", "label": "语音合成 (TTS)"},
    {"id": "session", "label": "唤醒与会话"},
    {"id": "music", "label": "音乐"},
    {"id": "ota", "label": "固件 OTA"},
    {"id": "emotion", "label": "表情"},
    {"id": "perf", "label": "性能与限流"},
]

# 可编辑设置项定义。
# key 为 Settings 扁平字段名的大写形式（即 .env 键名，与 pydantic-settings 映射一致）。
# type: str/text/int/float/bool/secret/select
# restart: True 表示该项在 AI 服务商连接池/启动逻辑中快照，修改需重启服务才完全生效
SETTING_DEFS: list[dict[str, Any]] = [
    # ---- 基础 ----
    {"key": "DEPLOY_MODE", "group": "basic", "label": "部署模式", "type": "select",
     "options": ["single", "multi"], "restart": True,
     "desc": "single=单用户，multi=多用户（AI 配置改从数据库读取）"},
    {"key": "CORS_ORIGINS", "group": "basic", "label": "CORS 允许来源", "type": "str",
     "restart": True, "desc": "逗号分隔的域名，如 https://a.com,https://b.com；留空禁止跨域"},
    {"key": "SHUTDOWN_GRACE_PERIOD", "group": "basic", "label": "关机宽限期（秒）", "type": "int",
     "restart": True, "desc": "服务停止时等待后台任务完成的秒数"},
    # ---- LLM ----
    {"key": "LLM_API_KEY", "group": "llm", "label": "API Key", "type": "secret",
     "restart": True, "desc": "大模型服务密钥"},
    {"key": "LLM_BASE_URL", "group": "llm", "label": "API 地址", "type": "str",
     "restart": True, "desc": "兼容 OpenAI 格式的接口地址"},
    {"key": "LLM_MODEL", "group": "llm", "label": "模型名称", "type": "str",
     "restart": True, "desc": "如 deepseek-chat、gpt-4o"},
    {"key": "LLM_TEMPERATURE", "group": "llm", "label": "温度", "type": "float",
     "restart": True, "desc": "0-2，越高回答越随机"},
    {"key": "LLM_MAX_TOKENS", "group": "llm", "label": "最大 Token", "type": "int",
     "restart": True, "desc": "单次回复的最大 token 数"},
    {"key": "LLM_SYSTEM_PROMPT", "group": "llm", "label": "系统提示词", "type": "text",
     "restart": True, "desc": "设备对话的全局系统提示词（留空使用内置默认）"},
    {"key": "LLM_MEMORY_ENABLED", "group": "llm", "label": "对话记忆", "type": "bool",
     "restart": True, "desc": "是否携带历史对话上下文"},
    {"key": "LLM_MEMORY_MAX_MESSAGES", "group": "llm", "label": "记忆条数上限", "type": "int",
     "restart": True, "desc": ""},
    {"key": "LLM_MEMORY_MAX_TOKENS", "group": "llm", "label": "记忆 Token 上限", "type": "int",
     "restart": True, "desc": ""},
    {"key": "LLM_MEMORY_LONG_TERM_ENABLED", "group": "llm", "label": "长期记忆", "type": "bool",
     "restart": True, "desc": ""},
    # ---- ASR ----
    {"key": "ASR_PROVIDER", "group": "asr", "label": "识别服务商", "type": "select",
     "options": ["tencent", "volcengine", "aliyun", "xunfei"], "restart": True,
     "desc": "语音识别服务商"},
    {"key": "ASR_TENCENT_APP_ID", "group": "asr", "label": "腾讯云 AppID", "type": "str",
     "restart": True, "desc": "provider=tencent 时使用"},
    {"key": "ASR_TENCENT_SECRET_ID", "group": "asr", "label": "腾讯云 SecretId", "type": "str",
     "restart": True, "desc": ""},
    {"key": "ASR_TENCENT_SECRET_KEY", "group": "asr", "label": "腾讯云 SecretKey", "type": "secret",
     "restart": True, "desc": ""},
    {"key": "ASR_TENCENT_ENGINE", "group": "asr", "label": "腾讯云引擎", "type": "str",
     "restart": True, "desc": "如 16k_zh"},
    {"key": "ASR_VOLCENGINE_API_KEY", "group": "asr", "label": "火山引擎 Key", "type": "secret",
     "restart": True, "desc": "provider=volcengine 时使用"},
    {"key": "ASR_VOLCENGINE_RESOURCE_ID", "group": "asr", "label": "火山引擎资源 ID", "type": "str",
     "restart": True, "desc": ""},
    {"key": "ASR_VOLCENGINE_MODEL", "group": "asr", "label": "火山引擎模型", "type": "str",
     "restart": True, "desc": ""},
    {"key": "ASR_NO_SPEECH_TIMEOUT", "group": "asr", "label": "无语音超时（秒）", "type": "int",
     "restart": True, "desc": ""},
    {"key": "ASR_SILENCE_TIMEOUT", "group": "asr", "label": "静音超时（秒）", "type": "int",
     "restart": True, "desc": ""},
    {"key": "ASR_MAX_CONCURRENCY", "group": "asr", "label": "最大并发", "type": "int",
     "restart": True, "desc": ""},
    # ---- TTS ----
    {"key": "TTS_VOLCENGINE_API_KEY", "group": "tts", "label": "火山引擎 API Key", "type": "secret",
     "restart": True, "desc": "语音合成服务密钥"},
    {"key": "TTS_VOLCENGINE_RESOURCE_ID", "group": "tts", "label": "资源 ID", "type": "str",
     "restart": True, "desc": ""},
    {"key": "TTS_VOLCENGINE_VOICE_TYPE", "group": "tts", "label": "默认音色", "type": "str",
     "restart": True, "desc": "如 BV001_streaming"},
    {"key": "TTS_VOLCENGINE_SPEED", "group": "tts", "label": "语速倍率", "type": "float",
     "restart": True, "desc": "1.0 为正常语速"},
    {"key": "TTS_VOLCENGINE_VOLUME", "group": "tts", "label": "音量倍率", "type": "float",
     "restart": True, "desc": ""},
    {"key": "TTS_VOLCENGINE_PITCH", "group": "tts", "label": "音调倍率", "type": "float",
     "restart": True, "desc": ""},
    {"key": "TTS_VOLCENGINE_DIALECT", "group": "tts", "label": "方言", "type": "str",
     "restart": True,
     "desc": "可选 beijing/dongbei/henan/shaanxi/shanghai/sichuan/tianjin/yue，留空为普通话"},
    # ---- 唤醒与会话（运行时动态读取，保存后即时生效）----
    {"key": "WAKEUP_TEXT", "group": "session", "label": "唤醒回复语", "type": "str",
     "restart": False, "desc": "设备唤醒后 TTS 播报的第一句话"},
    {"key": "WAKE_AUDIO_CACHE_ENABLED", "group": "session", "label": "唤醒音频缓存", "type": "bool",
     "restart": False, "desc": ""},
    {"key": "WAKE_AUDIO_PLAY_ENABLED", "group": "session", "label": "唤醒音频播放", "type": "bool",
     "restart": False, "desc": ""},
    {"key": "GROWTH_COOLDOWN_SECONDS", "group": "session", "label": "成长任务冷却（秒）", "type": "int",
     "restart": False, "desc": "对话结束后等待多少秒无新对话才触发 AI 成长任务，0 为立即"},
    # ---- 音乐（即时生效）----
    {"key": "MUSIC_API_URL", "group": "music", "label": "音乐服务地址", "type": "str",
     "restart": False, "desc": "网络音乐播放的 HTTP 服务地址"},
    {"key": "LYRICS_OFFSET", "group": "music", "label": "歌词偏移（毫秒）", "type": "int",
     "restart": False, "desc": "正数提前、负数延后"},
    # ---- OTA（即时生效）----
    {"key": "OTA_ENABLED", "group": "ota", "label": "启用 OTA", "type": "bool",
     "restart": False, "desc": ""},
    {"key": "OTA_BIN_URL", "group": "ota", "label": "固件地址", "type": "str",
     "restart": False, "desc": ""},
    {"key": "OTA_VERSION", "group": "ota", "label": "固件版本", "type": "str",
     "restart": False, "desc": ""},
    {"key": "OTA_BIN_ID", "group": "ota", "label": "固件 ID", "type": "str",
     "restart": False, "desc": "与客户端板型 bin_id 对应"},
    {"key": "OTA_IS_OFFICIAL", "group": "ota", "label": "官方固件标记", "type": "str",
     "restart": False, "desc": "0/1"},
    # ---- 表情（即时生效）----
    {"key": "SERVER_EMOTION_ENABLED", "group": "emotion", "label": "情绪检测", "type": "bool",
     "restart": False, "desc": "LLM 回复末尾解析 [e:情绪] 标签并下发表情"},
    {"key": "SERVER_EMOTION_GIF_DIR", "group": "emotion", "label": "GIF 目录", "type": "str",
     "restart": False, "desc": ""},
    {"key": "SERVER_EMOTION_STATIC_DIR", "group": "emotion", "label": "静态表情目录", "type": "str",
     "restart": False, "desc": ""},
    # ---- 性能与限流（启动时快照，需重启）----
    {"key": "PERF_GLOBAL_MAX_CONCURRENT_SESSIONS", "group": "perf", "label": "最大并发会话", "type": "int",
     "restart": True, "desc": ""},
    {"key": "PERF_ENABLE_GLOBAL_CONCURRENCY_LIMIT", "group": "perf", "label": "启用并发限制", "type": "bool",
     "restart": True, "desc": ""},
    {"key": "PERF_RATE_LIMIT_GLOBAL_RPM", "group": "perf", "label": "全局 RPM 限制", "type": "int",
     "restart": True, "desc": ""},
    {"key": "PERF_MAX_MESSAGES_PER_SESSION", "group": "perf", "label": "单会话消息上限", "type": "int",
     "restart": True, "desc": ""},
    {"key": "PERF_AUDIO_QUEUE_MAX_SIZE", "group": "perf", "label": "音频队列上限", "type": "int",
     "restart": True, "desc": ""},
    {"key": "PERF_SEND_QUEUE_MAX_SIZE", "group": "perf", "label": "发送队列上限", "type": "int",
     "restart": True, "desc": ""},
]

_SETTINGS_BY_KEY = {d["key"]: d for d in SETTING_DEFS}


def _format_env_value(value: str) -> str:
    """将值格式化为 .env 字段：含换行/引号的值用双引号包裹（python-dotenv 支持 \\n 转义）"""
    if value == "":
        return '""'
    if '"' in value or "\n" in value or "\r" in value:
        escaped = (
            value.replace("\r", "")
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
        )
        return f'"{escaped}"'
    return value


def _update_env_content(content: str, key: str, value: str) -> str:
    """更新 .env 内容中指定键；键不存在则追加。

    原值若为多行引号包裹（含未闭合引号），会吞掉后续行直到引号闭合后再替换，
    避免多行值残留中间行破坏文件结构。
    """
    lines = content.split("\n")
    pattern = re.compile(rf"^{re.escape(key)}=")
    out: list[str] = []
    replaced = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if not replaced and pattern.match(line):
            out.append(f"{key}={_format_env_value(value)}")
            replaced = True
            raw = line.split("=", 1)[1] if "=" in line else ""
            while ((raw.count('"') % 2 == 1 or raw.count("'") % 2 == 1)
                   and i + 1 < len(lines)):
                i += 1
                raw += "\n" + lines[i]
            i += 1
            continue
        out.append(line)
        i += 1
    if not replaced:
        if out and out[-1] != "":
            out.append("")
        out.append(f"{key}={_format_env_value(value)}")
    return "\n".join(out)


def _to_env_str(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _convert_setting_value(d: dict, value: Any) -> Any:
    """按设置项定义做类型转换与取值校验，非法值抛 HTTPException(400)"""
    t = d["type"]
    if t == "bool":
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in ("true", "1", "yes", "on"):
            return True
        if s in ("false", "0", "no", "off"):
            return False
        raise HTTPException(400, f"{d['key']} 需为布尔值")
    if t == "int":
        try:
            return int(value)
        except (TypeError, ValueError):
            raise HTTPException(400, f"{d['key']} 需为整数")
    if t == "float":
        try:
            return float(value)
        except (TypeError, ValueError):
            raise HTTPException(400, f"{d['key']} 需为数字")
    if t == "select":
        s = str(value)
        if s not in (d.get("options") or []):
            raise HTTPException(400, f"{d['key']} 仅支持: {', '.join(d.get('options') or [])}")
        return s
    return str(value)


@router.get("/settings")
async def admin_get_settings(_: UserModel = Depends(require_admin)):
    """获取可编辑的系统设置（按分组返回；密钥类只回是否已设置，不回明文）"""
    from src.infrastructure.config import get_settings
    settings = get_settings()
    groups = []
    for g in SETTING_GROUPS:
        items = []
        for d in SETTING_DEFS:
            if d["group"] != g["id"]:
                continue
            current = getattr(settings, d["key"].lower(), None)
            item = {k: v for k, v in d.items()}
            if d["type"] == "secret":
                item["value"] = ""
                item["has_value"] = bool(current)
            else:
                item["value"] = current
            items.append(item)
        groups.append({**g, "items": items})
    env_path = _project_root() / ".env"
    return {
        "code": 0,
        "message": "ok",
        "data": {"groups": groups, "env_file_exists": env_path.exists()},
    }


@router.put("/settings")
async def admin_update_settings(data: dict, admin: UserModel = Depends(require_admin)):
    """更新系统设置：白名单校验 → 写入 .env → 热应用内存配置。

    - 密钥类字段留空表示保持现有值不覆盖
    - "restart": true 的项（AI 服务商连接池等启动时快照）需重启服务才完全生效，
      其余项更新内存配置后立即生效
    """
    if not isinstance(data, dict) or not data:
        raise HTTPException(400, "请求体不能为空")

    updates: dict[str, tuple[dict, Any]] = {}
    for key, value in data.items():
        d = _SETTINGS_BY_KEY.get(key)
        if not d:
            raise HTTPException(400, f"不支持的配置项: {key}")
        if d["type"] == "secret" and (value is None or str(value).strip() == ""):
            continue  # 密钥留空 = 保持现有值
        if value is None:
            continue
        updates[key] = (d, _convert_setting_value(d, value))
    if not updates:
        return {"code": 0, "message": "没有需要保存的修改",
                "data": {"updated": 0, "restart_keys": []}}

    # 1. 写入 .env（同步文件 IO 放线程池）
    env_path = _project_root() / ".env"
    content = ""
    if env_path.exists():
        content = await asyncio.to_thread(env_path.read_text, "utf-8")
    for key, (_d, typed) in updates.items():
        content = _update_env_content(content, key, _to_env_str(typed))
    await asyncio.to_thread(lambda: env_path.write_text(content, encoding="utf-8"))

    # 2. 热应用：更新内存单例的扁平字段后重跑 flat→nested 映射（与重启加载等效）
    from src.infrastructure.config import get_settings
    settings = get_settings()
    for key, (_d, typed) in updates.items():
        setattr(settings, key.lower(), typed)
    settings.model_post_init(None)

    restart_keys = [k for k, (d, _t) in updates.items() if d.get("restart")]
    _add_oplog(admin.email, "update_settings", f"修改系统设置: {', '.join(sorted(updates.keys()))}")
    logger.info(f"[Admin] 更新系统设置: {sorted(updates.keys())}，需重启项: {restart_keys}")
    return {
        "code": 0,
        "message": f"已保存 {len(updates)} 项设置",
        "data": {"updated": len(updates), "restart_keys": restart_keys},
    }


# ==================== 网站设置 ====================

@router.get("/site-settings")
async def admin_get_site_settings(_: UserModel = Depends(require_admin)):
    """获取网站设置（管理员）"""
    from src.infrastructure.routes.site import get_site_settings
    settings = await get_site_settings()
    return {"code": 0, "message": "ok", "data": settings}


@router.put("/site-settings")
async def admin_update_site_settings(data: dict, admin: UserModel = Depends(require_admin)):
    """更新网站设置（管理员）：白名单过滤后写入数据库"""
    if not isinstance(data, dict) or not data:
        raise HTTPException(400, "请求体不能为空")
    from src.infrastructure.routes.site import save_site_settings
    settings = await save_site_settings(data)
    _add_oplog(admin.email, "update_site_settings", f"修改网站设置: {', '.join(sorted(k for k in data if k))}")
    logger.info(f"[Admin] 更新网站设置: {sorted(k for k in data if k)}")
    return {"code": 0, "message": "网站设置已保存", "data": settings}


# ==================== 计费系统 ====================

@router.get("/billing/config")
async def admin_get_billing_config(_: UserModel = Depends(require_admin)):
    """获取计费配置（单价）"""
    from src.use_cases.billing import get_billing_config
    config = await get_billing_config()
    return {"code": 0, "message": "ok", "data": config}


@router.put("/billing/config")
async def admin_update_billing_config(data: dict, admin: UserModel = Depends(require_admin)):
    """更新计费配置（单价）：白名单过滤 + 数值校验后写入数据库"""
    if not isinstance(data, dict) or not data:
        raise HTTPException(400, "请求体不能为空")
    from src.use_cases.billing import save_billing_config
    config = await save_billing_config(data)
    _add_oplog(admin.email, "update_billing_config", f"修改计费配置: {', '.join(sorted(k for k in data if k))}")
    logger.info(f"[Admin] 更新计费配置: {sorted(k for k in data if k)}")
    return {"code": 0, "message": "计费配置已保存", "data": config}


@router.get("/billing/records")
async def admin_billing_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    device_id: str = Query("", description="按设备过滤"),
    _: UserModel = Depends(require_admin),
):
    """计费记录列表（分页，按时间倒序）"""
    from src.infrastructure.db.models.billing import BillingRecordModel
    async with get_session_ctx() as session:
        conds = []
        if device_id:
            conds.append(BillingRecordModel.device_id == device_id)
        total = await session.scalar(
            select(func.count()).select_from(BillingRecordModel).where(*conds)
        ) or 0
        rows = (
            await session.execute(
                select(BillingRecordModel)
                .where(*conds)
                .order_by(desc(BillingRecordModel.created_at))
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        records = [
            {
                "id": r.id,
                "device_id": r.device_id,
                "session_id": r.session_id,
                "asr_minutes": r.asr_minutes,
                "llm_input_tokens": r.llm_input_tokens,
                "llm_output_tokens": r.llm_output_tokens,
                "llm_cache_hit_tokens": r.llm_cache_hit_tokens,
                "tts_chars": r.tts_chars,
                "asr_cost": r.asr_cost,
                "llm_cost": r.llm_cost,
                "tts_cost": r.tts_cost,
                "total_cost": r.total_cost,
                "llm_offpeak": bool(r.llm_offpeak),
                "created_at": r.created_at,
            }
            for r in rows
        ]
        return {"code": 0, "message": "ok", "data": {"total": total, "records": records}}


@router.get("/billing/stats")
async def admin_billing_stats(_: UserModel = Depends(require_admin)):
    """计费统计：累计用量与费用 + 按设备汇总（设备级记账）"""
    from src.infrastructure.db.models.billing import BillingRecordModel
    async with get_session_ctx() as session:
        row = (
            await session.execute(
                select(
                    func.count(BillingRecordModel.id),
                    func.coalesce(func.sum(BillingRecordModel.asr_minutes), 0),
                    func.coalesce(func.sum(BillingRecordModel.llm_input_tokens), 0),
                    func.coalesce(func.sum(BillingRecordModel.llm_output_tokens), 0),
                    func.coalesce(func.sum(BillingRecordModel.llm_cache_hit_tokens), 0),
                    func.coalesce(func.sum(BillingRecordModel.tts_chars), 0),
                    func.coalesce(func.sum(BillingRecordModel.asr_cost), 0.0),
                    func.coalesce(func.sum(BillingRecordModel.llm_cost), 0.0),
                    func.coalesce(func.sum(BillingRecordModel.tts_cost), 0.0),
                    func.coalesce(func.sum(BillingRecordModel.total_cost), 0.0),
                )
            )
        ).one()
        # 按设备汇总（费用从高到低）
        per_device_rows = (
            await session.execute(
                select(
                    BillingRecordModel.device_id,
                    func.count(BillingRecordModel.id),
                    func.coalesce(func.sum(BillingRecordModel.asr_minutes), 0),
                    func.coalesce(func.sum(BillingRecordModel.llm_input_tokens), 0),
                    func.coalesce(func.sum(BillingRecordModel.llm_output_tokens), 0),
                    func.coalesce(func.sum(BillingRecordModel.llm_cache_hit_tokens), 0),
                    func.coalesce(func.sum(BillingRecordModel.tts_chars), 0),
                    func.coalesce(func.sum(BillingRecordModel.asr_cost), 0.0),
                    func.coalesce(func.sum(BillingRecordModel.llm_cost), 0.0),
                    func.coalesce(func.sum(BillingRecordModel.tts_cost), 0.0),
                    func.coalesce(func.sum(BillingRecordModel.total_cost), 0.0),
                )
                .group_by(BillingRecordModel.device_id)
                .order_by(desc(func.sum(BillingRecordModel.total_cost)))
            )
        ).all()
        per_device = [
            {
                "device_id": r[0],
                "record_count": r[1],
                "asr_minutes": r[2],
                "llm_input_tokens": r[3],
                "llm_output_tokens": r[4],
                "llm_cache_hit_tokens": r[5],
                "tts_chars": r[6],
                "asr_cost": round(r[7], 6),
                "llm_cost": round(r[8], 6),
                "tts_cost": round(r[9], 6),
                "total_cost": round(r[10], 6),
            }
            for r in per_device_rows
        ]
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "record_count": row[0],
                "asr_minutes": row[1],
                "llm_input_tokens": row[2],
                "llm_output_tokens": row[3],
                "llm_cache_hit_tokens": row[4],
                "tts_chars": row[5],
                "asr_cost": round(row[6], 6),
                "llm_cost": round(row[7], 6),
                "tts_cost": round(row[8], 6),
                "total_cost": round(row[9], 6),
                "per_device": per_device,
            },
        }


@router.get("/billing/daily")
async def admin_billing_daily(days: int = Query(7, ge=1, le=31), _: UserModel = Depends(require_admin)):
    """近 N 天每日累计费用（按本地日期分组 sum(total_cost)，无记录的天补 0）"""
    from datetime import datetime, timedelta
    from src.infrastructure.db.models.billing import BillingRecordModel
    async with get_session_ctx() as session:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start = today - timedelta(days=days - 1)
        # created_at 为 UTC UNIX 时间戳（秒），按本地时区转日期后分组
        rows = (
            await session.execute(
                select(BillingRecordModel.created_at, BillingRecordModel.total_cost)
                .where(BillingRecordModel.created_at >= start.timestamp())
            )
        ).all()
        by_date: dict[str, float] = {}
        for ts, cost in rows:
            key = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            by_date[key] = by_date.get(key, 0.0) + (cost or 0.0)
        daily = [
            {
                "date": (start + timedelta(days=i)).strftime("%Y-%m-%d"),
                "total_cost": round(by_date.get((start + timedelta(days=i)).strftime("%Y-%m-%d"), 0.0), 6),
            }
            for i in range(days)
        ]
        return {"code": 0, "message": "ok", "data": {"days": days, "daily": daily}}


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
.settings-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 12px; }
.setting-item { background: #0f1923; border: 1px solid #1e3a4a; border-radius: 8px; padding: 14px; }
.setting-item .setting-label { font-size: 13px; color: #e0e6ed; font-weight: 600; margin-bottom: 4px; display: flex; align-items: center; gap: 8px; }
.setting-item .setting-desc { font-size: 11px; color: #667788; margin-bottom: 8px; line-height: 1.5; }
.setting-item input[type=text], .setting-item input[type=password], .setting-item input[type=number], .setting-item select, .setting-item textarea {
  width: 100%; padding: 8px 12px; background: #1a2a3a; border: 1px solid #1e3a4a; border-radius: 6px; color: #e0e6ed; font-size: 13px; outline: none; font-family: inherit;
}
.setting-item input:focus, .setting-item select:focus, .setting-item textarea:focus { border-color: #2a5a7a; }
.setting-item textarea { resize: vertical; font-family: monospace; }
.setting-item .switch-row { display: flex; align-items: center; gap: 10px; font-size: 13px; color: #e0e6ed; cursor: pointer; }
.setting-item .switch-row input[type=checkbox] { width: 18px; height: 18px; accent-color: #2a5a7a; cursor: pointer; }
.restart-badge { font-size: 10px; color: #ffb74d; border: 1px solid #ffb74d; border-radius: 4px; padding: 1px 6px; font-weight: 400; }
.save-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding: 14px 18px; background: #1a2a3a; border: 1px solid #1e3a4a; border-radius: 10px; }
.save-bar .hint { font-size: 12px; color: #667788; }
.settings-actions { display: flex; gap: 10px; }
.save-btn { background: #2e7d32; color: #fff; border: none; padding: 9px 28px; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 600; }
.save-btn:hover { background: #388e3c; }
.save-btn:disabled { background: #455a64; cursor: not-allowed; }
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
    <button class="nav-tab active" onclick="switchTab('overview',this)">概览</button>
    <button class="nav-tab" onclick="switchTab('settings',this)">设置</button>
    <button class="nav-tab" onclick="switchTab('metrics',this)">性能指标</button>
    <button class="nav-tab" onclick="switchTab('pools',this)">连接池</button>
    <button class="nav-tab" onclick="switchTab('system',this)">系统信息</button>
  </div>

  <div id="tab-overview" class="tab-content active">
    <div class="row row-4" id="statsCards">
      <div class="card loading" style="grid-column:1/-1;">加载统计信息中...</div>
    </div>
    <div class="section-title">实时动态</div>
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
    <div class="section-title">系统资源</div>
    <div class="row row-4" id="systemResourceCards">
      <div class="card loading" style="grid-column:1/-1;">加载中...</div>
    </div>
  </div>

  <div id="tab-settings" class="tab-content">
    <div class="save-bar">
      <div class="hint">修改写入 .env 并即时热应用；标有「需重启」的项涉及服务连接池，重启后完全生效。密钥留空表示保持现有值。</div>
      <div class="settings-actions">
        <button class="refresh-btn" onclick="loadSettings()">&#x21bb; 重新加载</button>
        <button class="save-btn" id="saveSettingsBtn" onclick="saveSettings(this)">保存全部修改</button>
      </div>
    </div>
    <div id="settingsContainer"><div class="loading" style="padding:60px;text-align:center;color:#667788;">加载设置中...</div></div>
  </div>

  <div id="tab-pools" class="tab-content">
    <div class="section-title">连接池详情</div>
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
  if (name === 'settings') loadSettings();
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
      fetchJSON('/api/v1/admin/metrics').catch(() => null)
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
      c.innerHTML = '<div>加载失败: ' + e.message + '</div>';
    });
  }
}
function renderStats(stats) {
  document.getElementById('statsCards').innerHTML = [
    { label: '用户总数', value: stats.users, sub: '管理员 ' + stats.admins, cls: 'users',  },
    { label: '设备总数', value: stats.devices, sub: '已绑定 ' + stats.bound_devices, cls: 'devices',  },
    { label: '在线设备', value: stats.online_devices, sub: '在线率 ' + (stats.devices ? (stats.online_devices/stats.devices*100).toFixed(1) : 0) + '%', cls: 'online',  },
    { label: '未绑定设备', value: stats.devices - stats.bound_devices, sub: '待绑定设备数', cls: 'cpu',  },
  ].map(c => '<div class="card ' + c.cls + '"><div class="label">' + c.label + '</div><div class="value">' + c.value + '</div><div class="sub">' + c.sub + '</div></div>').join('');
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
    '<div style="grid-column:1/-1;"><div class="section-title">并发控制</div><div class="concurrency-grid">' +
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
        ? online.map(d => '● ' + escapeHtml(d.name || d.device_id) + ' (' + escapeHtml(d.mac || '') + ')').join('<br>')
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
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
// ==================== 设置页签 ====================
let settingsLoaded = false;
async function loadSettings() {
  const container = document.getElementById('settingsContainer');
  try {
    const data = await fetchJSON('/api/v1/admin/settings');
    container.innerHTML = data.groups.map(g =>
      '<div class="section-title">' + g.label + '</div>' +
      '<div class="settings-grid">' + g.items.map(renderSettingField).join('') + '</div>'
    ).join('');
    settingsLoaded = true;
  } catch(e) {
    container.innerHTML = '<div class="error">加载设置失败: ' + escapeHtml(e.message) + '</div>';
  }
}
function renderSettingField(it) {
  const badge = it.restart ? '<span class="restart-badge">需重启</span>' : '';
  const desc = it.desc ? '<div class="setting-desc">' + escapeHtml(it.desc) + '</div>' : '';
  let input;
  if (it.type === 'bool') {
    input = '<label class="switch-row"><input type="checkbox" data-key="' + it.key + '"' + (it.value ? ' checked' : '') + '><span>' + (it.value ? '已开启' : '已关闭') + '</span></label>';
  } else if (it.type === 'select') {
    input = '<select data-key="' + it.key + '">' + (it.options || []).map(o =>
      '<option value="' + escapeHtml(o) + '"' + (o === it.value ? ' selected' : '') + '>' + escapeHtml(o) + '</option>'
    ).join('') + '</select>';
  } else if (it.type === 'text') {
    input = '<textarea data-key="' + it.key + '" rows="3" placeholder="留空保持不变">' + escapeHtml(it.value == null ? '' : it.value) + '</textarea>';
  } else if (it.type === 'secret') {
    input = '<input type="password" data-key="' + it.key + '" data-secret="1" autocomplete="new-password" placeholder="' + (it.has_value ? '已设置（留空保持不变）' : '未设置') + '">';
  } else if (it.type === 'int' || it.type === 'float') {
    input = '<input type="number" ' + (it.type === 'float' ? 'step="0.1" ' : 'step="1" ') + 'data-key="' + it.key + '" value="' + escapeHtml(String(it.value == null ? '' : it.value)) + '" placeholder="留空保持不变">';
  } else {
    input = '<input type="text" data-key="' + it.key + '" value="' + escapeHtml(it.value == null ? '' : it.value) + '" placeholder="留空保持不变">';
  }
  return '<div class="setting-item"><div class="setting-label">' + escapeHtml(it.label) + ' ' + badge + '</div>' + desc + input + '</div>';
}
async function saveSettings(btn) {
  const payload = {};
  document.querySelectorAll('#settingsContainer [data-key]').forEach(el => {
    const key = el.dataset.key;
    if (el.type === 'checkbox') { payload[key] = el.checked; return; }
    const v = el.value;
    if (v === '' || (el.dataset.secret && v.trim() === '')) return; // 空值/密钥留空 = 不覆盖
    payload[key] = v;
  });
  if (!Object.keys(payload).length) { alert('没有修改需要保存'); return; }
  btn.disabled = true; btn.textContent = '保存中...';
  try {
    const res = await fetch('/api/v1/admin/settings', {
      method: 'PUT', headers: Object.assign(getAuthHeaders(), { 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.code !== 0) throw new Error(data.message || '保存失败');
    const rk = (data.data && data.data.restart_keys || []).length;
    alert('已保存 ' + data.data.updated + ' 项设置' + (rk ? '，其中 ' + rk + ' 项涉及服务连接，需重启服务完全生效' : '，已即时生效'));
    loadSettings();
  } catch(e) {
    alert('保存失败: ' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = '保存全部修改';
  }
}
checkAuth();
if (token) setInterval(refreshAll, 30000);
</script>
</body>
</html>"""
