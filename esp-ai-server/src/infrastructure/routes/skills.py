"""技能路由

技能的查询、创建、更新、删除、启停、重载等管理路由。

阶段 3：数据源从 users.json 切换到 DB（DeviceRepository）。
认证方式：JWT 用户认证。
"""
from __future__ import annotations

import json
import os

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from sqlalchemy import select, or_

from src.infrastructure.logging import get_logger
from src.infrastructure.security_jwt import get_current_user, require_admin
from src.infrastructure.db.models.user import UserModel
from src.infrastructure.db.models.device import DeviceModel
from src.infrastructure.db.session import get_session_ctx
from src.infrastructure.web import (
    _add_skill_to_device,
    _remove_skill_from_all_devices,
    _hot_reload_device_config,
)

logger = get_logger(__name__)


def _get_repo():
    """延迟导入 DeviceRepository，避免循环引用。"""
    from src.infrastructure.db.repositories.device_repository import DeviceRepository
    return DeviceRepository()


async def _check_device_owner(device_id: str, user: UserModel) -> bool:
    """校验设备归属当前用户（兼容 mac_address / device_id / device_key 查找）"""
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


class CreateSkillRequest(BaseModel):
    name: str
    description: str
    instructions: str
    category: list[str] = []
    tags: list[str] = []
    cap_groups: list[str] = []
    device_id: str = ""


def register_routes(app: FastAPI) -> None:
    """注册技能相关路由"""

    # ============================================================
    #  Skill 查询 API（JWT 用户认证）
    # ============================================================
    @app.get("/api/v1/skills", tags=["skills"])
    async def list_skills(device_id: str = "", user: UserModel = Depends(get_current_user)):
        """获取所有可用 Skill，可按 device_id 过滤"""
        try:
            # 传了 device_id 时校验设备归属
            if device_id and not await _check_device_owner(device_id, user):
                from fastapi import HTTPException
                raise HTTPException(403, "Device not bound to you")
            from src.use_cases import skill_system
            skills = None
            disabled_skills = []
            if device_id:
                from src.use_cases.auxiliary_services import load_devices
                dm = load_devices()
                cfg = dm.devices.get(device_id) or dm.resolve(device_id)
                if cfg:
                    skills = getattr(cfg, 'skills', None) or None
                    disabled_skills = getattr(cfg, 'disabled_skills', None) or []
            catalog = skill_system.get_catalog(device_id=device_id, skills=skills)
            data = [
                {
                    "id": s.id,
                    "description": s.description,
                    "category": s.category,
                    "tags": s.tags,
                    "device_id": s.device_id,
                    "disabled": s.id in disabled_skills,
                }
                for s in catalog
            ]
            return {"code": 0, "message": "ok", "data": {"count": len(data), "skills": data}}
        except Exception as e:
            return {"code": 1, "message": str(e), "data": None}

    @app.post("/api/v1/skills/{skill_id}/toggle", tags=["skills"])
    async def toggle_skill(skill_id: str, device_id: str = "", disabled: bool = True, user: UserModel = Depends(get_current_user)):
        """禁用或启用技能"""
        try:
            if not device_id:
                return {"code": 1, "message": "device_id is required", "data": None}
            if not await _check_device_owner(device_id, user):
                from fastapi import HTTPException
                raise HTTPException(403, "Device not bound to you")
            repo = _get_repo()
            # 检查设备是否存在
            config = await repo.get_device_config(device_id)
            if config is None:
                return {"code": 1, "message": f"设备不存在: {device_id}", "data": None}
            await repo.toggle_skill(device_id, skill_id, disabled)
            _hot_reload_device_config(device_id)
            return {"code": 0, "message": "ok", "data": {"disabled": disabled}}
        except Exception as e:
            return {"code": 1, "message": str(e), "data": None}

    @app.get("/api/v1/skills/{skill_id}", tags=["skills"])
    async def get_skill_detail(skill_id: str, user: UserModel = Depends(get_current_user)):
        """获取技能详情（含完整文档）"""
        try:
            import re as _re
            from src.use_cases import skill_system
            entry = skill_system.get_skill(skill_id)
            if not entry:
                return {"code": 1, "message": f"技能不存在: {skill_id}", "data": None}
            doc = skill_system.get_skill_document(skill_id) or ""
            return {
                "code": 0, "message": "ok",
                "data": {
                    "id": entry.id,
                    "description": entry.metadata.description,
                    "category": entry.metadata.category,
                    "tags": entry.metadata.tags,
                    "cap_groups": entry.metadata.cap_groups,
                    "document": doc,
                    "instructions": doc,
                },
            }
        except Exception as e:
            return {"code": 1, "message": str(e), "data": None}

    @app.post("/api/v1/skills", tags=["skills"])
    async def create_skill(body: CreateSkillRequest, user: UserModel = Depends(get_current_user)):
        """创建新技能"""
        try:
            # 传了 device_id 时校验设备归属
            if body.device_id and not await _check_device_owner(body.device_id, user):
                from fastapi import HTTPException
                raise HTTPException(403, "Device not bound to you")
            from src.use_cases import skill_system
            entry = skill_system.create_skill(
                name=body.name,
                description=body.description,
                instructions=body.instructions,
                category=body.category,
                tags=body.tags,
                cap_groups=body.cap_groups,
            )
            # 写入 DB，让设备可用
            if body.device_id:
                await _add_skill_to_device(body.device_id, entry.id)
            return {
                "code": 0, "message": "ok",
                "data": {
                    "id": entry.id,
                    "description": entry.metadata.description,
                    "category": entry.metadata.category,
                    "tags": entry.metadata.tags,
                    "file_path": entry.file_path,
                },
            }
        except ValueError as e:
            return {"code": 1, "message": str(e), "data": None}
        except Exception as e:
            return {"code": 1, "message": f"创建失败: {e}", "data": None}

    @app.put("/api/v1/skills/{skill_id}", tags=["skills"])
    async def update_skill(skill_id: str, body: CreateSkillRequest, user: UserModel = Depends(get_current_user), _admin: UserModel = Depends(require_admin)):
        """更新已有技能"""
        try:
            from src.use_cases import skill_system
            entry = skill_system.update_skill(
                skill_id=skill_id,
                description=body.description,
                instructions=body.instructions,
                category=body.category,
                tags=body.tags,
                cap_groups=body.cap_groups,
            )
            return {
                "code": 0, "message": "ok",
                "data": {
                    "id": entry.id,
                    "description": entry.metadata.description,
                    "category": entry.metadata.category,
                    "tags": entry.metadata.tags,
                },
            }
        except ValueError as e:
            return {"code": 1, "message": str(e), "data": None}
        except Exception as e:
            return {"code": 1, "message": f"更新失败: {e}", "data": None}

    @app.delete("/api/v1/skills/{skill_id}", tags=["skills"])
    async def delete_skill(skill_id: str, user: UserModel = Depends(get_current_user), _admin: UserModel = Depends(require_admin)):
        """删除技能"""
        try:
            from src.use_cases import skill_system
            ok = skill_system.delete_skill(skill_id)
            if ok:
                await _remove_skill_from_all_devices(skill_id)
                return {"code": 0, "message": "ok", "data": {"deleted": skill_id}}
            return {"code": 1, "message": f"技能不存在: {skill_id}", "data": None}
        except Exception as e:
            return {"code": 1, "message": f"删除失败: {e}", "data": None}

    @app.post("/api/v1/skills/reload", tags=["skills"])
    async def reload_skills(user: UserModel = Depends(get_current_user), _admin: UserModel = Depends(require_admin)):
        """重新加载所有技能"""
        try:
            from src.use_cases import skill_system
            skill_system.reload()
            count = len(skill_system._skills_by_id)
            return {"code": 0, "message": "ok", "data": {"count": count}}
        except Exception as e:
            return {"code": 1, "message": f"重载失败: {e}", "data": None}
