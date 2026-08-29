"""技能路由

技能的查询、创建、更新、删除、启停、重载等管理路由。

阶段 3：数据源从 users.json 切换到 DB（DeviceRepository）。
认证方式：JWT 用户认证。
"""
from __future__ import annotations

import json
import os

from fastapi import Depends, APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select, or_, func

from src.infrastructure.logging import get_logger
from src.infrastructure.security_jwt import get_current_user, require_admin
from src.infrastructure.db.models.user import UserModel
from src.infrastructure.db.models.marketplace import MarketplaceSkillModel
from src.infrastructure.db.session import get_session_ctx
from src.infrastructure.routes._deps import check_device_owner as _check_device_owner
from src.infrastructure.web import (
    _add_skill_to_device,
    _remove_skill_from_all_devices,
    _hot_reload_device_config,
)

logger = get_logger(__name__)

router = APIRouter(tags=["skills"])


def _get_repo():
    """延迟导入 DeviceRepository，避免循环引用。"""
    from src.infrastructure.db.repositories.device_repository import DeviceRepository
    return DeviceRepository()


class CreateSkillRequest(BaseModel):
    name: str
    description: str
    instructions: str
    category: list[str] = []
    tags: list[str] = []
    cap_groups: list[str] = []
    device_id: str = ""

# ============================================================
#  技能市场（轻量版：上传 / 发布 / 列表 / 搜索 / 分类 / 安装 / 删除）
# ============================================================

SKILL_CATEGORIES = ["通用", "工具", "生活", "娱乐", "学习"]
_MAX_SKILL_UPLOAD_BYTES = 100 * 1024  # 100KB


def _user_display_name(user: UserModel) -> str:
    """用户显示名：优先 nickname，其次 email 前缀"""
    return user.nickname or (user.email.split("@")[0] if user.email else str(user.id))


def _extract_skill_from_upload(file_bytes: bytes, filename: str) -> tuple[str, str, dict]:
    """从上传文件解析技能，返回 (skill_id, content, meta_dict)。

    支持 .md 文件或包含 SKILL.md 的 zip（根目录或单层子目录）。
    """
    import io
    import zipfile

    name_lower = (filename or "").lower()
    if name_lower.endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                names = [n for n in zf.namelist() if not n.endswith("/")]
                skill_md = next((n for n in names if n.endswith("SKILL.md")), None)
                if not skill_md:
                    raise ValueError("zip 中未找到 SKILL.md")
                if ".." in skill_md or skill_md.startswith("/") or "\\" in skill_md:
                    raise ValueError("非法的文件路径")
                # 限额读取（防 zip 炸弹：单文件 5MB / 累计 20MB / 文件数 200）
                from src.infrastructure.routes.marketplace import read_zip_member_checked
                content = read_zip_member_checked(zf, skill_md).decode("utf-8", errors="replace")
        except zipfile.BadZipFile:
            raise ValueError("无效的 zip 文件")
    elif name_lower.endswith(".md"):
        content = file_bytes.decode("utf-8", errors="replace")
    else:
        raise ValueError("仅支持 .md 或 .zip 文件")

    from src.use_cases import skill_system
    meta = skill_system.parse_skill_content(content)
    return meta["id"], content, meta


def _bump_version(version: str) -> str:
    """版本号 patch 位 +1（1.0.0 → 1.0.1）"""
    try:
        parts = version.split(".")
        while len(parts) < 3:
            parts.append("0")
        parts[2] = str(int(parts[2]) + 1)
        return ".".join(parts)
    except Exception:
        return "1.0.1"


@router.post("/api/v1/skills/upload")
async def upload_skill(
    file: UploadFile = File(...),
    device_id: str = Form(""),
    user: UserModel = Depends(get_current_user),
):
    """本地上传技能（SKILL.md 或 zip），安装到全局技能目录，可选绑定到设备。"""
    if device_id and not await _check_device_owner(device_id, user):
        raise HTTPException(403, "Device not bound to you")

    file_bytes = await file.read()
    if len(file_bytes) == 0:
        return {"code": 1, "message": "上传文件为空", "data": None}
    if len(file_bytes) > _MAX_SKILL_UPLOAD_BYTES:
        return {"code": 1, "message": "文件过大，最大支持 100KB", "data": None}

    try:
        skill_id, content, meta = _extract_skill_from_upload(file_bytes, file.filename)
    except ValueError as e:
        # 客户端上传内容非法（zip 损坏 / 缺 SKILL.md / 非 md 文件），属业务错误
        return {"code": 1, "message": str(e), "data": None}

    from src.use_cases import skill_system
    entry = skill_system.import_skill_from_content(content)

    if device_id:
        await _add_skill_to_device(device_id, entry.id)

    return {
        "code": 0, "message": "ok",
        "data": {
            "id": entry.id,
            "description": entry.metadata.description,
            "category": entry.metadata.category,
            "tags": entry.metadata.tags,
        },
    }


@router.post("/api/v1/skills/marketplace/publish")
async def publish_skill(
    file: UploadFile = File(...),
    category: str = Form("通用"),
    tags: str = Form("[]"),
    user: UserModel = Depends(get_current_user),
):
    """发布技能到市场（同一 slug 重复发布视为更新，仅限本人）。"""
    file_bytes = await file.read()
    if len(file_bytes) == 0:
        return {"code": 1, "message": "上传文件为空", "data": None}
    if len(file_bytes) > _MAX_SKILL_UPLOAD_BYTES:
        return {"code": 1, "message": "文件过大，最大支持 100KB", "data": None}

    try:
        skill_id, content, meta = _extract_skill_from_upload(file_bytes, file.filename)
    except ValueError as e:
        # 客户端上传内容非法（zip 损坏 / 缺 SKILL.md / 非 md 文件），属业务错误
        return {"code": 1, "message": str(e), "data": None}

    try:
        tags_list = json.loads(tags) if tags else []
        if not isinstance(tags_list, list):
            tags_list = []
    except json.JSONDecodeError:
        tags_list = []

    async with get_session_ctx() as session:
        result = await session.execute(
            select(MarketplaceSkillModel).where(MarketplaceSkillModel.slug == skill_id).with_for_update()
        )
        existing = result.scalar_one_or_none()
        if existing and existing.developer_id != str(user.id):
            return {"code": 1, "message": "无权修改他人发布的技能", "data": None}

        if existing:
            existing.name = meta["name"]
            existing.description = meta["description"]
            existing.category = category
            existing.tags = json.dumps(tags_list, ensure_ascii=False)
            existing.content = content
            existing.version = _bump_version(existing.version)
            existing.is_active = True
            await session.flush()
            record_id = existing.id
            version = existing.version
            is_new = False
        else:
            record = MarketplaceSkillModel(
                slug=skill_id,
                name=meta["name"],
                description=meta["description"],
                author=_user_display_name(user),
                developer_id=str(user.id),
                category=category,
                tags=json.dumps(tags_list, ensure_ascii=False),
                version="1.0.0",
                content=content,
            )
            session.add(record)
            await session.flush()
            record_id = record.id
            version = record.version
            is_new = True

    logger.info(f"[SkillMarket] 技能发布: slug={skill_id} ver={version} user={user.id} new={is_new}")
    return {
        "code": 0, "message": "ok",
        "data": {"id": record_id, "slug": skill_id, "name": meta["name"], "version": version, "is_new": is_new},
    }


@router.get("/api/v1/skills/marketplace")
async def list_market_skills(
    search: str = "",
    category: str = "",
    page: int = 1,
    size: int = 20,
    user: UserModel = Depends(get_current_user),
):
    """技能市场列表（搜索 / 分类 / 分页，按下载量排序）"""
    page = max(1, page)
    size = min(50, max(1, size))
    async with get_session_ctx() as session:
        query = select(MarketplaceSkillModel).where(MarketplaceSkillModel.is_active == True)
        if search:
            like = f"%{search}%"
            query = query.where(or_(
                MarketplaceSkillModel.name.like(like),
                MarketplaceSkillModel.description.like(like),
            ))
        if category:
            query = query.where(MarketplaceSkillModel.category == category)

        total = (await session.execute(
            select(func.count()).select_from(query.subquery())
        )).scalar() or 0

        result = await session.execute(
            query.order_by(MarketplaceSkillModel.downloads.desc())
            .offset((page - 1) * size).limit(size)
        )
        items = result.scalars().all()

    data = [
        {
            "slug": s.slug,
            "name": s.name,
            "description": s.description,
            "author": s.author,
            "category": s.category,
            "tags": json.loads(s.tags or "[]"),
            "version": s.version,
            "downloads": s.downloads,
            "created_at": s.created_at,
        }
        for s in items
    ]
    return {"code": 0, "message": "ok", "data": {"items": data, "total": total, "page": page, "size": size}}


@router.get("/api/v1/skills/marketplace/categories")
async def list_skill_categories(user: UserModel = Depends(get_current_user)):
    """技能市场分类"""
    return {"code": 0, "message": "ok", "data": {"categories": SKILL_CATEGORIES}}


@router.get("/api/v1/skills/marketplace/mine")
async def my_market_skills(user: UserModel = Depends(get_current_user)):
    """我发布的技能"""
    async with get_session_ctx() as session:
        result = await session.execute(
            select(MarketplaceSkillModel).where(MarketplaceSkillModel.developer_id == str(user.id))
        )
        items = result.scalars().all()
    data = [
        {
            "slug": s.slug,
            "name": s.name,
            "description": s.description,
            "category": s.category,
            "version": s.version,
            "downloads": s.downloads,
            "created_at": s.created_at,
        }
        for s in items
    ]
    return {"code": 0, "message": "ok", "data": {"items": data}}


@router.get("/api/v1/skills/marketplace/{slug}")
async def get_market_skill(slug: str, user: UserModel = Depends(get_current_user)):
    """技能市场详情（含完整 SKILL.md 内容）"""
    async with get_session_ctx() as session:
        result = await session.execute(
            select(MarketplaceSkillModel).where(MarketplaceSkillModel.slug == slug)
        )
        s = result.scalar_one_or_none()
    if not s or not s.is_active:
        return {"code": 1, "message": "技能不存在", "data": None}
    return {
        "code": 0, "message": "ok",
        "data": {
            "slug": s.slug,
            "name": s.name,
            "description": s.description,
            "author": s.author,
            "category": s.category,
            "tags": json.loads(s.tags or "[]"),
            "version": s.version,
            "downloads": s.downloads,
            "content": s.content,
            "created_at": s.created_at,
        },
    }


@router.post("/api/v1/skills/marketplace/{slug}/install")
async def install_market_skill(
    slug: str,
    device_id: str = "",
    user: UserModel = Depends(get_current_user),
):
    """从市场安装技能到全局目录，可选绑定到设备"""
    if device_id and not await _check_device_owner(device_id, user):
        raise HTTPException(403, "Device not bound to you")

    async with get_session_ctx() as session:
        result = await session.execute(
            select(MarketplaceSkillModel).where(MarketplaceSkillModel.slug == slug).with_for_update()
        )
        s = result.scalar_one_or_none()
        if not s or not s.is_active:
            return {"code": 1, "message": "技能不存在", "data": None}
        content = s.content
        s.downloads += 1

    from src.use_cases import skill_system
    entry = skill_system.import_skill_from_content(content)

    if device_id:
        await _add_skill_to_device(device_id, entry.id)

    return {
        "code": 0, "message": "ok",
        "data": {"id": entry.id, "description": entry.metadata.description},
    }


@router.delete("/api/v1/skills/marketplace/{slug}")
async def delete_market_skill(slug: str, user: UserModel = Depends(get_current_user)):
    """删除自己发布的技能（仅限本人）"""
    async with get_session_ctx() as session:
        result = await session.execute(
            select(MarketplaceSkillModel).where(MarketplaceSkillModel.slug == slug)
        )
        s = result.scalar_one_or_none()
        if not s:
            return {"code": 1, "message": "技能不存在", "data": None}
        if s.developer_id != str(user.id):
            return {"code": 1, "message": "无权删除他人发布的技能", "data": None}
        await session.delete(s)
    return {"code": 0, "message": "ok", "data": {"deleted": slug}}


# ============================================================
#  Skill 查询 API（JWT 用户认证）
# ============================================================
@router.get("/api/v1/skills")
async def list_skills(device_id: str = "", user: UserModel = Depends(get_current_user)):
    """获取所有可用 Skill，可按 device_id 过滤"""
    # 传了 device_id 时校验设备归属
    if device_id and not await _check_device_owner(device_id, user):
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


@router.post("/api/v1/skills/{skill_id}/toggle")
async def toggle_skill(skill_id: str, device_id: str = "", disabled: bool = True, user: UserModel = Depends(get_current_user)):
    """禁用或启用技能"""
    if not device_id:
        return {"code": 1, "message": "device_id is required", "data": None}
    if not await _check_device_owner(device_id, user):
        raise HTTPException(403, "Device not bound to you")
    repo = _get_repo()
    # 检查设备是否存在
    config = await repo.get_device_config(device_id)
    if config is None:
        return {"code": 1, "message": f"设备不存在: {device_id}", "data": None}
    await repo.toggle_skill(device_id, skill_id, disabled)
    _hot_reload_device_config(device_id)
    return {"code": 0, "message": "ok", "data": {"disabled": disabled}}


@router.get("/api/v1/skills/{skill_id}")
async def get_skill_detail(skill_id: str, user: UserModel = Depends(get_current_user)):
    """获取技能详情（含完整文档）"""
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


@router.post("/api/v1/skills")
async def create_skill(body: CreateSkillRequest, user: UserModel = Depends(get_current_user)):
    """创建新技能"""
    # 传了 device_id 时校验设备归属
    if body.device_id and not await _check_device_owner(body.device_id, user):
        raise HTTPException(403, "Device not bound to you")
    from src.use_cases import skill_system
    try:
        entry = skill_system.create_skill(
            name=body.name,
            description=body.description,
            instructions=body.instructions,
            category=body.category,
            tags=body.tags,
            cap_groups=body.cap_groups,
        )
    except ValueError as e:
        # 技能内容非法（名称/描述等校验不通过），属业务错误
        return {"code": 1, "message": str(e), "data": None}
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


@router.put("/api/v1/skills/{skill_id}")
async def update_skill(skill_id: str, body: CreateSkillRequest, _admin: UserModel = Depends(require_admin)):
    """更新已有技能"""
    from src.use_cases import skill_system
    try:
        entry = skill_system.update_skill(
            skill_id=skill_id,
            description=body.description,
            instructions=body.instructions,
            category=body.category,
            tags=body.tags,
            cap_groups=body.cap_groups,
        )
    except ValueError as e:
        # 技能内容非法（名称/描述等校验不通过），属业务错误
        return {"code": 1, "message": str(e), "data": None}
    return {
        "code": 0, "message": "ok",
        "data": {
            "id": entry.id,
            "description": entry.metadata.description,
            "category": entry.metadata.category,
            "tags": entry.metadata.tags,
        },
    }


@router.delete("/api/v1/skills/{skill_id}")
async def delete_skill(skill_id: str, _admin: UserModel = Depends(require_admin)):
    """删除技能"""
    from src.use_cases import skill_system
    ok = skill_system.delete_skill(skill_id)
    if ok:
        await _remove_skill_from_all_devices(skill_id)
        return {"code": 0, "message": "ok", "data": {"deleted": skill_id}}
    return {"code": 1, "message": f"技能不存在: {skill_id}", "data": None}


@router.post("/api/v1/skills/reload")
async def reload_skills(_admin: UserModel = Depends(require_admin)):
    """重新加载所有技能"""
    from src.use_cases import skill_system
    skill_system.reload()
    count = len(skill_system._skills_by_id)
    return {"code": 0, "message": "ok", "data": {"count": count}}


