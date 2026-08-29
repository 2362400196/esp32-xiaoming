"""云市场路由（Phase 2）

提供插件市场后端 API：
- 开发者：复用现有用户 JWT 体系，用户登录后生成 API Key 即可上传
- 插件管理（上传/列表/详情/版本历史/下载）—— 上传需 JWT 认证 + developer_api_key
- 社区（评论增查）—— 评论需 JWT 认证，一人一评
- 分类聚合

manifest.json 约定（zip 包根目录）：
  {
    "id": "weather",              # -> slug（转小写）
    "name": "天气插件",            # 显示名
    "version": "1.0.0",           # 语义化版本
    "description": "查询实时天气",
    "category": "weather",        # 可选，默认 general
    "tags": ["weather"],          # 可选，默认 []
    "changelog": "Initial release",  # 可选
    "signature": ""               # 可选，开发者签名
  }

zip 包必须同时包含 manifest.json 和 plugin.py，否则拒绝上传。
"""
from __future__ import annotations

import io
import json
import re
import secrets
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import and_, desc, func, or_, select

from src.infrastructure.db.models.marketplace import (
    MarketplacePluginModel,
    PluginReviewModel,
    PluginVersionModel,
)
from src.infrastructure.db.models.user import UserModel
from src.infrastructure.db.session import get_session_ctx
from src.infrastructure.logging import get_logger
from src.infrastructure.marketplace_storage import (
    MARKETPLACE_STORAGE_DIR,
    compute_checksum,
    save_icon,
    save_package,
)
from src.infrastructure.security_jwt import get_current_user

logger = get_logger(__name__)

router = APIRouter(tags=["marketplace"])

# slug 合法字符：小写字母/数字/下划线/短横线
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
# 语义化版本：主.次.修订（可选预发布标签）
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+([\-+][0-9A-Za-z.\-]+)?$")

# 上传 zip 大小上限：50MB
_MAX_UPLOAD_SIZE = 50 * 1024 * 1024

# ==================== zip 解压炸弹防护 ====================
# 解压后大小与 zip 压缩包大小无关（zip 炸弹），读取任何成员前必须校验声明大小。
MAX_ZIP_MEMBER_SIZE = 5 * 1024 * 1024        # 单个成员解压后上限：5MB
MAX_ZIP_TOTAL_UNCOMPRESSED = 20 * 1024 * 1024  # 所有已读成员累计解压后上限：20MB
MAX_ZIP_MEMBERS = 200                         # 已读成员数量上限


def create_zip_read_state() -> dict:
    """创建 zip 读取限额状态（跨多次 read_zip_member_checked 累计计数）。"""
    return {"total": 0, "count": 0}


def read_zip_member_checked(zf: zipfile.ZipFile, name: str, state: dict | None = None) -> bytes:
    """按防解压炸弹限额读取 zip 成员内容。

    读取前检查 ``ZipInfo.file_size``（解压后大小），超限抛 ValueError：
    - 单文件解压后上限 5MB
    - 累计解压后上限 20MB（同一 state 跨成员累计）
    - 已读文件数上限 200
    """
    if state is None:
        state = create_zip_read_state()
    info = zf.getinfo(name)
    state["count"] += 1
    if state["count"] > MAX_ZIP_MEMBERS:
        raise ValueError(f"zip 内文件数超过上限（{MAX_ZIP_MEMBERS} 个）")
    if info.file_size > MAX_ZIP_MEMBER_SIZE:
        raise ValueError(
            f"zip 内文件解压后过大: {name}（{info.file_size // 1024 // 1024 + 1}MB，"
            f"单文件上限 {MAX_ZIP_MEMBER_SIZE // 1024 // 1024}MB）"
        )
    state["total"] += info.file_size
    if state["total"] > MAX_ZIP_TOTAL_UNCOMPRESSED:
        raise ValueError(
            f"zip 解压后总大小超过上限（{MAX_ZIP_TOTAL_UNCOMPRESSED // 1024 // 1024}MB）"
        )
    with zf.open(name) as f:
        return f.read()

# 商店固定分类：基于插件 provides 能力（ASR/LLM/TTS/其他工具）
STORE_CATEGORIES = [
    {"name": "ASR", "key": "asr"},
    {"name": "LLM", "key": "llm"},
    {"name": "TTS", "key": "tts"},
    {"name": "其他工具", "key": "other"},
]


def _extract_provides(manifest: dict) -> list:
    """从 manifest 提取插件提供的能力（仅 asr/llm/tts 用于商店分类）。"""
    provides = manifest.get("provides", {}) or {}
    if isinstance(provides, dict):
        return [k for k in ("asr", "llm", "tts") if k in provides]
    return []


def _extract_icon_from_zip(zip_bytes: bytes, icon_name: str) -> bytes | None:
    """从 zip 包提取图标文件内容（manifest.icon 指定的文件）。

    支持根目录或单层子目录，规范化路径防止路径穿越。
    """
    icon_name = (icon_name or "").strip().replace("\\", "/").lstrip("/")
    if not icon_name or ".." in Path(icon_name).parts:
        return None
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        return None
    state = create_zip_read_state()
    try:
        # 限额读取，防 zip 炸弹（超限抛 ValueError）
        return read_zip_member_checked(zf, icon_name, state)
    except KeyError:
        for n in zf.namelist():
            if n.endswith("/" + icon_name) and n.count("/") == 1:
                try:
                    return read_zip_member_checked(zf, n, state)
                except ValueError:
                    return None
        return None
    except ValueError:
        # 图标超限：上传流程按未提取图标处理（返回 None）
        return None


def _category_filter(category: str):
    """将商店分类名映射为 provides 筛选条件（None 表示不过滤）。"""
    if category == "ASR":
        return MarketplacePluginModel.provides.like('%"asr"%')
    if category == "LLM":
        return MarketplacePluginModel.provides.like('%"llm"%')
    if category == "TTS":
        return MarketplacePluginModel.provides.like('%"tts"%')
    if category == "其他工具":
        return or_(
            MarketplacePluginModel.provides.is_(None),
            MarketplacePluginModel.provides == "",
            and_(
                MarketplacePluginModel.provides.not_like('%"asr"%'),
                MarketplacePluginModel.provides.not_like('%"llm"%'),
                MarketplacePluginModel.provides.not_like('%"tts"%'),
            ),
        )
    return None


# ==================== Pydantic 请求/响应模型 ====================

class ReviewCreateReq(BaseModel):
    rating: int
    comment: str = ""

    @field_validator("rating")
    @classmethod
    def rating_range(cls, v: int) -> int:
        if not (1 <= v <= 5):
            raise ValueError("rating 必须在 1-5 之间")
        return v


class UpdateBioReq(BaseModel):
    bio: str = ""


class PluginSourceReq(BaseModel):
    """更新插件源码（在线编辑）"""
    plugin_code: str = ""
    manifest: dict
    changelog: str = ""
    files: list[dict] = []


class CreatePluginReq(BaseModel):
    """从代码创建新插件"""
    slug: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    category: str = "general"
    tags: list[str] = []
    plugin_code: str = ""
    changelog: str = ""
    files: list[dict] = []


# ==================== 开发者辅助 ====================

def _dev_name(user: UserModel) -> str:
    """开发者显示名：优先 nickname，其次 email 前缀"""
    return user.nickname or (user.email.split("@")[0] if user.email else str(user.id))


async def _ensure_developer(user: UserModel) -> UserModel:
    """确保用户已开启开发者模式（有 developer_api_key），否则 403。"""
    if not user.developer_api_key:
        raise HTTPException(status_code=403, detail="请先在开发者页面生成 API Key")
    return user


# ==================== 开发者端点（复用用户 JWT） ====================

@router.post("/api/v1/marketplace/developer/enable")
async def enable_developer(user: UserModel = Depends(get_current_user)):
    """开启开发者模式：生成 API Key（已开启则重新生成）。
    复用现有用户 JWT 认证，无需单独注册。"""
    async with get_session_ctx() as session:
        db_user = await session.get(UserModel, str(user.id))
        if db_user is None:
            return {"code": 1, "message": "用户不存在", "data": None}
        api_key = secrets.token_urlsafe(32)
        db_user.developer_api_key = api_key
        await session.flush()
        logger.info(f"[Marketplace] 用户 {user.id} 开启开发者模式")
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "developer_api_key": api_key,
            "username": _dev_name(user),
        },
    }


@router.get("/api/v1/marketplace/developer/info")
async def developer_info(user: UserModel = Depends(get_current_user)):
    """查询当前用户的开发者状态。"""
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "is_developer": bool(user.developer_api_key),
            "developer_api_key": user.developer_api_key or "",
            "username": _dev_name(user),
            "email": user.email,
            "bio": getattr(user, "developer_bio", ""),
        },
    }


@router.put("/api/v1/marketplace/developer/bio")
async def update_developer_bio(body: UpdateBioReq, user: UserModel = Depends(get_current_user)):
    """更新开发者简介。"""
    async with get_session_ctx() as session:
        db_user = await session.get(UserModel, str(user.id))
        if db_user is None:
            return {"code": 1, "message": "用户不存在", "data": None}
        db_user.developer_bio = body.bio[:256]
        await session.flush()
    return {"code": 0, "message": "ok", "data": {"bio": body.bio[:256]}}


@router.get("/api/v1/marketplace/developer/plugins")
async def developer_plugins(user: UserModel = Depends(get_current_user)):
    """获取当前开发者上传的所有插件。"""
    async with get_session_ctx() as session:
        result = await session.execute(
            select(MarketplacePluginModel)
            .where(MarketplacePluginModel.developer_id == str(user.id))
            .order_by(desc(MarketplacePluginModel.updated_at))
        )
        plugins = result.scalars().all()

    items = []
    for p in plugins:
        items.append({
            "slug": p.slug,
            "name": p.name,
            "description": p.description,
            "latest_version": p.latest_version,
            "total_downloads": p.total_downloads,
            "category": p.category,
            "icon": p.icon,
            "is_active": p.is_active,
            "updated_at": p.updated_at,
        })
    return {"code": 0, "message": "ok", "data": items}


# ==================== 插件上传 ====================

def _read_manifest_from_zip(zip_bytes: bytes) -> tuple[dict, set]:
    """从 zip 包读取 manifest.json 并校验必需文件。

    支持两种 zip 结构：
    1. 根目录：manifest.json, plugin.py
    2. 子目录：my-plugin/manifest.json, my-plugin/plugin.py
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as e:
        raise ValueError(f"无效的 zip 文件: {e}")
    names = set(zf.namelist())

    # 优先找根目录下的 manifest.json
    manifest_name = "manifest.json" if "manifest.json" in names else None
    if manifest_name is None:
        # 回退：找子目录下的 manifest.json（排除目录条目和 __MACOSX）
        candidates = [
            n for n in names
            if n.endswith("manifest.json")
            and not n.startswith("__MACOSX")
            and not n.endswith("/")
        ]
        if len(candidates) == 1:
            manifest_name = candidates[0]
        elif len(candidates) > 1:
            raise ValueError(f"zip 包包含多个 manifest.json: {candidates}")
        else:
            raise ValueError("zip 包缺少 manifest.json")

    # 确定 prefix（子目录前缀）
    prefix = ""
    if "/" in manifest_name:
        prefix = manifest_name.rsplit("/", 1)[0] + "/"

    # 校验 plugin.py 存在（同目录）
    plugin_name = prefix + "plugin.py"
    if plugin_name not in names:
        raise ValueError(f"zip 包缺少 plugin.py（期望路径: {plugin_name}）")

    try:
        manifest = json.loads(
            read_zip_member_checked(zf, manifest_name).decode("utf-8")
        )
    except ValueError as e:
        # manifest 解压后超限（zip 炸弹防护）
        raise ValueError(f"manifest.json 读取失败: {e}")
    except Exception as e:
        raise ValueError(f"manifest.json 解析失败: {e}")
    if not isinstance(manifest, dict):
        raise ValueError("manifest.json 必须是 JSON 对象")

    # 返回 names（去掉 prefix 前缀，方便后续 install_from_zip 统一处理）
    if prefix:
        names = {n[len(prefix):] for n in names if n.startswith(prefix)}
    return manifest, names


def _validate_manifest(manifest: dict) -> tuple[str, str, str, str, str, list, str, str, list, str]:
    """校验 manifest 必需字段。"""
    raw_id = str(manifest.get("id", "")).strip()
    if not raw_id:
        raise ValueError("manifest.json 缺少 id 字段")
    slug = raw_id.lower()
    if not _SLUG_RE.match(slug):
        raise ValueError(f"manifest.id 非法: {raw_id}")

    name = str(manifest.get("name", "")).strip()
    if not name:
        raise ValueError("manifest.json 缺少 name 字段")

    version = str(manifest.get("version", "")).strip()
    if not _SEMVER_RE.match(version):
        raise ValueError(f"version 必须符合语义化版本（x.y.z）: {version}")

    description = str(manifest.get("description", "")).strip()
    category = str(manifest.get("category", "general") or "general").strip() or "general"
    tags_raw = manifest.get("tags", [])
    if not isinstance(tags_raw, list):
        raise ValueError("tags 必须是数组")
    tags = [str(t) for t in tags_raw]
    changelog = str(manifest.get("changelog", "")).strip()
    signature = str(manifest.get("signature", "") or "").strip()
    provides = _extract_provides(manifest)
    icon = str(manifest.get("icon", "") or "").strip()
    return slug, name, version, description, category, tags, changelog, signature, provides, icon


def _read_source_from_zip(zip_bytes: bytes) -> dict:
    """从 zip 包读取插件全部源码文件。

    Returns:
        {"manifest": dict, "manifest_raw": str, "plugin_code": str, "files": list}
        files 为 [{name, content}]（仅文本文件）
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as e:
        raise ValueError(f"无效的 zip 文件: {e}")
    names = set(zf.namelist())

    manifest_name = "manifest.json" if "manifest.json" in names else None
    if manifest_name is None:
        candidates = [
            n for n in names
            if n.endswith("manifest.json")
            and not n.startswith("__MACOSX")
            and not n.endswith("/")
        ]
        if len(candidates) == 1:
            manifest_name = candidates[0]
        else:
            raise ValueError("zip 包缺少 manifest.json")

    prefix = ""
    if "/" in manifest_name:
        prefix = manifest_name.rsplit("/", 1)[0] + "/"

    plugin_name = prefix + "plugin.py"
    if plugin_name not in names:
        raise ValueError("zip 包缺少 plugin.py")

    manifest_raw = read_zip_member_checked(zf, manifest_name).decode("utf-8")
    plugin_code = read_zip_member_checked(zf, plugin_name).decode("utf-8")
    manifest = json.loads(manifest_raw)

    # 收集所有文本文件（相对路径，跳过 __MACOSX 与目录条目）
    state = create_zip_read_state()
    state["total"] = len(manifest_raw) + len(plugin_code)  # 已读文件计入累计限额
    state["count"] = 2
    files = []
    for n in sorted(zf.namelist()):
        if n.endswith("/") or n.startswith("__MACOSX"):
            continue
        if n == manifest_name or n == plugin_name:
            continue
        try:
            # 限额读取，防 zip 炸弹（单文件/累计超限抛 ValueError）
            data = read_zip_member_checked(zf, n, state)
        except KeyError:
            continue
        try:
            content = data.decode("utf-8")
            files.append({"name": n, "content": content})
        except UnicodeDecodeError:
            # 二进制文件（如图标 png/jpg）以 base64 返回，编辑后重新打包时保留
            import base64
            files.append({
                "name": n,
                "content": base64.b64encode(data).decode("ascii"),
                "binary": True,
            })

    return {
        "manifest": manifest,
        "manifest_raw": manifest_raw,
        "plugin_code": plugin_code,
        "files": files,
    }


def _create_zip_from_source(manifest: dict, plugin_code: str, files: list | None = None) -> bytes:
    """从 manifest dict、plugin.py 源码和附加文件创建 zip 包。

    files 条目支持二进制文件：{"name": "icon.png", "content": "<base64>", "binary": true}
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr("plugin.py", plugin_code)
        for item in files or []:
            fname = str(item.get("name") or "").strip().lstrip("/")
            if not fname or fname in ("manifest.json", "plugin.py") or ".." in Path(fname).parts:
                continue
            if item.get("binary"):
                import base64
                try:
                    zf.writestr(fname, base64.b64decode(str(item.get("content") or "")))
                except Exception:
                    continue
            else:
                zf.writestr(fname, str(item.get("content") or ""))
    return buf.getvalue()


@router.post("/api/v1/marketplace/plugins/upload")
async def upload_plugin(
    file: UploadFile = File(...),
    user: UserModel = Depends(get_current_user),
):
    """上传插件 zip 包（需 JWT 认证 + 已开启开发者模式）。

    流程：验证 JWT → 检查 developer_api_key → 保存 zip → 读取 manifest → 存 DB。
    slug 已存在则创建新版本（需为同一开发者），否则创建新插件。
    """
    await _ensure_developer(user)

    zip_bytes = await file.read()
    if len(zip_bytes) == 0:
        return {"code": 1, "message": "上传文件为空", "data": None}
    if len(zip_bytes) > _MAX_UPLOAD_SIZE:
        return {"code": 1, "message": f"文件过大，最大支持 {_MAX_UPLOAD_SIZE // 1024 // 1024}MB", "data": None}

    try:
        manifest, _names = _read_manifest_from_zip(zip_bytes)
        slug, name, version, description, category, tags, changelog, signature, provides, icon = _validate_manifest(manifest)
    except ValueError as e:
        # manifest/zip 内容非法，属业务错误
        return {"code": 1, "message": str(e), "data": None}

    rel_path = await save_package(zip_bytes, slug, version)
    pkg_abs = MARKETPLACE_STORAGE_DIR / rel_path
    checksum = await compute_checksum(pkg_abs)

    # 提取并保存图标（manifest.icon 指定的文件）
    icon_file = ""
    if icon:
        icon_bytes = _extract_icon_from_zip(zip_bytes, icon)
        if icon_bytes:
            try:
                icon_file = await save_icon(icon_bytes, slug, icon)
            except ValueError as e:
                # 图标扩展名/内容非白名单图片，拒绝上传（400）
                raise HTTPException(status_code=400, detail=str(e))

    async with get_session_ctx() as session:
        result = await session.execute(
            select(MarketplacePluginModel).where(MarketplacePluginModel.slug == slug).with_for_update()
        )
        plugin = result.scalar_one_or_none()

        if plugin is None:
            plugin = MarketplacePluginModel(
                slug=slug,
                name=name,
                description=description,
                developer_id=str(user.id),
                category=category,
                icon=icon_file,
                provides=json.dumps(provides, ensure_ascii=False),
                tags=json.dumps(tags, ensure_ascii=False),
                latest_version=version,
            )
            session.add(plugin)
            await session.flush()
            plugin_id = plugin.id
            created_new = True
        else:
            if plugin.developer_id != str(user.id):
                return {"code": 1, "message": "无权修改他人插件", "data": None}
            ver_exists = await session.execute(
                select(PluginVersionModel.id).where(
                    PluginVersionModel.plugin_id == plugin.id,
                    PluginVersionModel.version == version,
                )
            )
            if ver_exists.first() is not None:
                return {"code": 1, "message": f"版本 {version} 已存在，请升级版本号后再上传", "data": None}
            plugin.name = name
            plugin.description = description
            plugin.category = category
            # 新包带图标则更新；manifest 无 icon 视为移除；提取失败保留旧图标
            plugin.icon = (icon_file or plugin.icon) if icon else ""
            plugin.provides = json.dumps(provides, ensure_ascii=False)
            plugin.tags = json.dumps(tags, ensure_ascii=False)
            plugin.latest_version = version
            plugin_id = plugin.id
            created_new = False

        version_record = PluginVersionModel(
            plugin_id=plugin_id,
            version=version,
            changelog=changelog,
            file_path=rel_path,
            file_size=len(zip_bytes),
            checksum=checksum,
            signature=signature,
        )
        session.add(version_record)
        await session.flush()
        version_id = version_record.id

    logger.info(f"[Marketplace] 插件上传: slug={slug} ver={version} user={user.id} new={created_new}")
    return {
        "code": 0, "message": "ok",
        "data": {"plugin_id": plugin_id, "version_id": version_id, "slug": slug, "name": name,
                 "version": version, "is_new_plugin": created_new, "checksum": checksum},
    }


@router.delete("/api/v1/marketplace/plugins/{slug}")
async def delete_plugin(
    slug: str,
    user: UserModel = Depends(get_current_user),
):
    """删除开发者自己的插件（含所有版本、评论、zip 文件）。

    仅限插件上传者本人删除。已安装该插件的用户不受影响（本地副本独立）。
    """
    await _ensure_developer(user)

    async with get_session_ctx() as session:
        result = await session.execute(
            select(MarketplacePluginModel).where(MarketplacePluginModel.slug == slug)
        )
        plugin = result.scalar_one_or_none()
        if plugin is None:
            return {"code": 1, "message": f"插件 {slug} 不存在", "data": None}
        if plugin.developer_id != str(user.id):
            return {"code": 1, "message": "无权删除他人插件", "data": None}

        # 删除所有版本记录 + 评论
        versions = (await session.execute(
            select(PluginVersionModel).where(PluginVersionModel.plugin_id == plugin.id)
        )).scalars().all()

        # 删除 zip 文件
        import shutil
        for ver in versions:
            pkg_path = MARKETPLACE_STORAGE_DIR / ver.file_path
            if pkg_path.exists():
                pkg_path.unlink(missing_ok=True)
        # 删除插件 slug 目录
        slug_dir = MARKETPLACE_STORAGE_DIR / slug
        if slug_dir.exists():
            shutil.rmtree(slug_dir, ignore_errors=True)

        # 删除数据库记录
        await session.execute(
            PluginReviewModel.__table__.delete().where(PluginReviewModel.plugin_id == plugin.id)
        )
        for ver in versions:
            await session.delete(ver)
        await session.delete(plugin)

    logger.info(f"[Marketplace] 插件删除: slug={slug} user={user.id}")
    return {"code": 0, "message": "ok", "data": {"slug": slug}}


# ==================== 插件源码在线编辑 ====================

@router.get("/api/v1/marketplace/plugins/{slug}/source")
async def get_plugin_source(slug: str, user: UserModel = Depends(get_current_user)):
    """获取插件的源码（从最新版本的 zip 中提取 manifest.json 和 plugin.py）。"""
    await _ensure_developer(user)

    async with get_session_ctx() as session:
        plugin = (await session.execute(
            select(MarketplacePluginModel).where(MarketplacePluginModel.slug == slug)
        )).scalar_one_or_none()
        if plugin is None:
            return {"code": 1, "message": f"插件不存在: {slug}", "data": None}
        if plugin.developer_id != str(user.id):
            return {"code": 1, "message": "无权查看他人插件源码", "data": None}

        ver = (await session.execute(
            select(PluginVersionModel)
            .where(PluginVersionModel.plugin_id == plugin.id)
            .order_by(desc(PluginVersionModel.created_at))
            .limit(1)
        )).scalar_one_or_none()
        if ver is None:
            return {"code": 1, "message": "插件没有可用版本", "data": None}
        file_path = ver.file_path
        ver_version = ver.version
        plugin_name = plugin.name

    zip_path = MARKETPLACE_STORAGE_DIR / file_path
    if not zip_path.is_file():
        return {"code": 1, "message": "插件包文件不存在", "data": None}

    zip_bytes = zip_path.read_bytes()
    try:
        source = _read_source_from_zip(zip_bytes)
    except ValueError as e:
        return {"code": 1, "message": str(e), "data": None}

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "slug": slug,
            "name": plugin_name,
            "version": ver_version,
            "manifest_raw": source["manifest_raw"],
            "manifest": source["manifest"],
            "plugin_code": source["plugin_code"],
            "files": source["files"],
        },
    }


@router.put("/api/v1/marketplace/plugins/{slug}/source")
async def update_plugin_source(
    slug: str,
    body: PluginSourceReq,
    user: UserModel = Depends(get_current_user),
):
    """更新插件源码（创建新版本，无需重新上传 zip）。

    从 manifest dict 和 plugin_code 构建 zip → 保存为新版本。
    """
    await _ensure_developer(user)

    try:
        m_slug, m_name, m_version, m_desc, m_cat, m_tags, m_changelog, m_sig, m_provides, m_icon = _validate_manifest(body.manifest)
    except ValueError as e:
        return {"code": 1, "message": str(e), "data": None}

    if m_slug != slug:
        return {"code": 1, "message": "manifest 中的 id 与插件 slug 不一致", "data": None}

    async with get_session_ctx() as session:
        plugin = (await session.execute(
            select(MarketplacePluginModel).where(MarketplacePluginModel.slug == slug).with_for_update()
        )).scalar_one_or_none()
        if plugin is None:
            return {"code": 1, "message": f"插件不存在: {slug}", "data": None}
        if plugin.developer_id != str(user.id):
            return {"code": 1, "message": "无权修改他人插件", "data": None}

        ver_exists = await session.execute(
            select(PluginVersionModel.id).where(
                PluginVersionModel.plugin_id == plugin.id,
                PluginVersionModel.version == m_version,
            )
        )
        if ver_exists.first() is not None:
            return {"code": 1, "message": f"版本 {m_version} 已存在，请升级版本号", "data": None}

    zip_bytes = _create_zip_from_source(body.manifest, body.plugin_code, body.files)
    if len(zip_bytes) > _MAX_UPLOAD_SIZE:
        return {"code": 1, "message": f"文件过大，最大支持 {_MAX_UPLOAD_SIZE // 1024 // 1024}MB", "data": None}

    rel_path = await save_package(zip_bytes, slug, m_version)
    pkg_abs = MARKETPLACE_STORAGE_DIR / rel_path
    checksum = await compute_checksum(pkg_abs)

    # 提取并保存图标（manifest.icon 指定的文件）
    icon_file = ""
    if m_icon:
        icon_bytes = _extract_icon_from_zip(zip_bytes, m_icon)
        if icon_bytes:
            try:
                icon_file = await save_icon(icon_bytes, slug, m_icon)
            except ValueError as e:
                # 图标扩展名/内容非白名单图片，拒绝上传（400）
                raise HTTPException(status_code=400, detail=str(e))

    changelog = body.changelog or m_changelog

    async with get_session_ctx() as session:
        result = await session.execute(
            select(MarketplacePluginModel).where(MarketplacePluginModel.slug == slug)
        )
        plugin = result.scalar_one_or_none()

        plugin.name = m_name
        plugin.description = m_desc
        plugin.category = m_cat
        # 新包带图标则更新；manifest 无 icon 视为移除；提取失败保留旧图标
        plugin.icon = (icon_file or plugin.icon) if m_icon else ""
        plugin.provides = json.dumps(m_provides, ensure_ascii=False)
        plugin.tags = json.dumps(m_tags, ensure_ascii=False)
        plugin.latest_version = m_version

        version_record = PluginVersionModel(
            plugin_id=plugin.id,
            version=m_version,
            changelog=changelog,
            file_path=rel_path,
            file_size=len(zip_bytes),
            checksum=checksum,
            signature=m_sig,
        )
        session.add(version_record)
        await session.flush()
        version_id = version_record.id

    logger.info(f"[Marketplace] 插件源码更新: slug={slug} ver={m_version} user={user.id}")
    return {
        "code": 0,
        "message": "ok",
        "data": {"slug": slug, "version": m_version, "version_id": version_id},
    }


@router.post("/api/v1/marketplace/plugins/create")
async def create_plugin_from_code(
    body: CreatePluginReq,
    user: UserModel = Depends(get_current_user),
):
    """从代码直接创建新插件（无需上传 zip）。

    从 slug/name/plugin_code 构建 manifest.json + plugin.py 的 zip → 上架到市场。
    """
    await _ensure_developer(user)

    slug = body.slug.lower()
    if not _SLUG_RE.match(slug):
        return {"code": 1, "message": f"slug 非法（仅允许小写字母/数字/_/-）: {body.slug}", "data": None}

    if not _SEMVER_RE.match(body.version):
        return {"code": 1, "message": f"version 必须符合语义化版本（x.y.z）: {body.version}", "data": None}

    if not body.name.strip():
        return {"code": 1, "message": "插件名称不能为空", "data": None}

    async with get_session_ctx() as session:
        existing = await session.execute(
            select(MarketplacePluginModel).where(MarketplacePluginModel.slug == slug)
        )
        if existing.scalar_one_or_none() is not None:
            return {"code": 1, "message": f"插件 slug '{slug}' 已存在", "data": None}

    # 从 files 中的 manifest.json 提取 provides/icon（用于商店分类和图标，并写入 zip 的 manifest）
    provides = []
    icon = ""
    for f in body.files or []:
        if isinstance(f, dict) and str(f.get("name", "")).endswith("manifest.json"):
            try:
                m = json.loads(f.get("content", "{}"))
                provides = _extract_provides(m)
                icon = str(m.get("icon", "") or "").strip()
            except Exception:
                provides = []
            break

    manifest = {
        "id": slug,
        "name": body.name,
        "version": body.version,
        "description": body.description,
        "category": body.category,
        "tags": body.tags,
        "changelog": body.changelog,
        "api_version": "1.0",
    }
    if provides:
        manifest["provides"] = {k: [] for k in provides}
    if icon:
        manifest["icon"] = icon

    zip_bytes = _create_zip_from_source(manifest, body.plugin_code, body.files)
    if len(zip_bytes) > _MAX_UPLOAD_SIZE:
        return {"code": 1, "message": f"文件过大，最大支持 {_MAX_UPLOAD_SIZE // 1024 // 1024}MB", "data": None}

    rel_path = await save_package(zip_bytes, slug, body.version)
    pkg_abs = MARKETPLACE_STORAGE_DIR / rel_path
    checksum = await compute_checksum(pkg_abs)

    # 提取并保存图标（manifest.icon 指定的文件）
    icon_file = ""
    if icon:
        icon_bytes = _extract_icon_from_zip(zip_bytes, icon)
        if icon_bytes:
            try:
                icon_file = await save_icon(icon_bytes, slug, icon)
            except ValueError as e:
                # 图标扩展名/内容非白名单图片，拒绝上传（400）
                raise HTTPException(status_code=400, detail=str(e))

    async with get_session_ctx() as session:
        plugin = MarketplacePluginModel(
            slug=slug,
            name=body.name,
            description=body.description,
            developer_id=str(user.id),
            category=body.category,
            icon=icon_file,
            provides=json.dumps(provides, ensure_ascii=False),
            tags=json.dumps(body.tags, ensure_ascii=False),
            latest_version=body.version,
        )
        session.add(plugin)
        await session.flush()
        plugin_id = plugin.id

        version_record = PluginVersionModel(
            plugin_id=plugin_id,
            version=body.version,
            changelog=body.changelog,
            file_path=rel_path,
            file_size=len(zip_bytes),
            checksum=checksum,
            signature="",
        )
        session.add(version_record)
        await session.flush()
        version_id = version_record.id

    logger.info(f"[Marketplace] 插件在线创建: slug={slug} ver={body.version} user={user.id}")
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "plugin_id": plugin_id,
            "version_id": version_id,
            "slug": slug,
            "name": body.name,
            "version": body.version,
        },
    }


# ==================== 插件查询 ====================

def _plugin_list_item(p: MarketplacePluginModel, dev_name: str) -> dict:
    return {
        "slug": p.slug,
        "name": p.name,
        "description": p.description,
        "developer_name": dev_name,
        "latest_version": p.latest_version,
        "total_downloads": p.total_downloads,
        "avg_rating": round(p.avg_rating, 2),
        "review_count": p.review_count,
        "is_featured": p.is_featured,
        "category": p.category,
        "icon": p.icon,
    }


@router.get("/api/v1/marketplace/plugins")
async def list_plugins(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    search: str = Query(""),
    category: str = Query(""),
    sort: str = Query("downloads"),
):
    """插件列表（分页 + 搜索 + 分类 + 排序），join UserModel 获取开发者名。"""
    stmt = (
        select(MarketplacePluginModel, UserModel)
        .join(UserModel, MarketplacePluginModel.developer_id == UserModel.id)
        .where(MarketplacePluginModel.is_active == True)  # noqa: E712
    )
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(
            MarketplacePluginModel.name.ilike(like),
            MarketplacePluginModel.description.ilike(like),
        ))
    if category:
        cat_cond = _category_filter(category)
        if cat_cond is not None:
            stmt = stmt.where(cat_cond)

    sort = (sort or "downloads").lower()
    if sort == "rating":
        stmt = stmt.order_by(desc(MarketplacePluginModel.avg_rating))
    elif sort == "newest":
        stmt = stmt.order_by(desc(MarketplacePluginModel.created_at))
    else:
        stmt = stmt.order_by(desc(MarketplacePluginModel.total_downloads))

    count_stmt = (
        select(func.count()).select_from(MarketplacePluginModel)
        .where(MarketplacePluginModel.is_active == True)  # noqa: E712
    )
    if search:
        like = f"%{search}%"
        count_stmt = count_stmt.where(or_(
            MarketplacePluginModel.name.ilike(like),
            MarketplacePluginModel.description.ilike(like),
        ))
    if category:
        cat_cond = _category_filter(category)
        if cat_cond is not None:
            count_stmt = count_stmt.where(cat_cond)

    async with get_session_ctx() as session:
        total = (await session.execute(count_stmt)).scalar() or 0
        stmt = stmt.offset((page - 1) * size).limit(size)
        rows = (await session.execute(stmt)).all()

    items = [_plugin_list_item(p, _dev_name(u)) for (p, u) in rows]
    return {"code": 0, "message": "ok", "data": {"items": items, "total": total, "page": page, "size": size}}


@router.get("/api/v1/marketplace/plugins/{slug}")
async def get_plugin_detail(slug: str):
    """插件详情 + 最新版本 + 开发者信息。"""
    async with get_session_ctx() as session:
        result = await session.execute(
            select(MarketplacePluginModel, UserModel)
            .join(UserModel, MarketplacePluginModel.developer_id == UserModel.id)
            .where(MarketplacePluginModel.slug == slug)
        )
        row = result.first()
        if row is None:
            return {"code": 1, "message": f"插件不存在: {slug}", "data": None}
        plugin, dev_user = row

        ver_result = await session.execute(
            select(PluginVersionModel)
            .where(PluginVersionModel.plugin_id == plugin.id)
            .order_by(desc(PluginVersionModel.created_at))
            .limit(1)
        )
        latest_ver = ver_result.scalar_one_or_none()

    try:
        tags = json.loads(plugin.tags) if plugin.tags else []
    except Exception:
        tags = []

    data = {
        "slug": plugin.slug,
        "name": plugin.name,
        "description": plugin.description,
        "category": plugin.category,
        "icon": plugin.icon,
        "tags": tags,
        "latest_version": plugin.latest_version,
        "total_downloads": plugin.total_downloads,
        "avg_rating": round(plugin.avg_rating, 2),
        "review_count": plugin.review_count,
        "is_featured": plugin.is_featured,
        "is_active": plugin.is_active,
        "created_at": plugin.created_at,
        "updated_at": plugin.updated_at,
        "developer": {
            "id": dev_user.id,
            "username": _dev_name(dev_user),
            "bio": getattr(dev_user, "developer_bio", ""),
        },
        "latest_version_info": {
            "version": latest_ver.version,
            "changelog": latest_ver.changelog,
            "file_size": latest_ver.file_size,
            "checksum": latest_ver.checksum,
            "signature": latest_ver.signature,
            "download_count": latest_ver.download_count,
            "created_at": latest_ver.created_at,
        } if latest_ver else None,
    }
    return {"code": 0, "message": "ok", "data": data}


@router.get("/api/v1/marketplace/plugins/{slug}/versions")
async def list_plugin_versions(slug: str):
    """插件版本历史列表。"""
    async with get_session_ctx() as session:
        plugin = (await session.execute(
            select(MarketplacePluginModel).where(MarketplacePluginModel.slug == slug)
        )).scalar_one_or_none()
        if plugin is None:
            return {"code": 1, "message": f"插件不存在: {slug}", "data": None}
        versions = (await session.execute(
            select(PluginVersionModel).where(PluginVersionModel.plugin_id == plugin.id)
            .order_by(desc(PluginVersionModel.created_at))
        )).scalars().all()

    data = [{"id": v.id, "version": v.version, "changelog": v.changelog, "file_size": v.file_size,
             "checksum": v.checksum, "signature": v.signature, "download_count": v.download_count,
             "created_at": v.created_at} for v in versions]
    return {"code": 0, "message": "ok", "data": data}


@router.get("/api/v1/marketplace/plugins/{slug}/download")
async def download_plugin(slug: str, version: str = Query("latest")):
    """下载插件 zip 包，增加下载计数。"""
    async with get_session_ctx() as session:
        plugin = (await session.execute(
            select(MarketplacePluginModel).where(MarketplacePluginModel.slug == slug)
        )).scalar_one_or_none()
        if plugin is None:
            return {"code": 1, "message": f"插件不存在: {slug}", "data": None}
        target_version = plugin.latest_version if version == "latest" else version
        ver = (await session.execute(
            select(PluginVersionModel).where(
                PluginVersionModel.plugin_id == plugin.id,
                PluginVersionModel.version == target_version,
            )
        )).scalar_one_or_none()
        if ver is None:
            return {"code": 1, "message": f"版本不存在: {target_version}", "data": None}
        file_path = ver.file_path
        plugin.total_downloads = (plugin.total_downloads or 0) + 1
        ver.download_count = (ver.download_count or 0) + 1
        await session.flush()

    abs_path = MARKETPLACE_STORAGE_DIR / file_path
    if not abs_path.is_file():
        logger.error(f"[Marketplace] 插件包文件丢失: {abs_path}")
        return {"code": 1, "message": "插件包文件不存在", "data": None}
    return FileResponse(path=str(abs_path), media_type="application/zip",
                        filename=f"{slug}-{target_version}.zip")


# 图标响应 Content-Type 白名单（防存储型 XSS：svg/html 一律 404，绝不按原扩展名推断）
_ICON_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


@router.get("/api/v1/marketplace/plugins/{slug}/icon")
async def get_plugin_icon(slug: str):
    """返回插件图标文件（未上传图标时返回 404）。

    安全：Content-Type 仅按扩展名白名单映射，非白名单文件 404；
    响应带 nosniff + CSP sandbox，防止图标文件被浏览器当作 HTML/脚本执行（存储型 XSS）。
    """
    async with get_session_ctx() as session:
        plugin = (await session.execute(
            select(MarketplacePluginModel).where(MarketplacePluginModel.slug == slug)
        )).scalar_one_or_none()
        if plugin is None or not plugin.icon:
            raise HTTPException(status_code=404, detail="插件未上传图标")
        icon_name = plugin.icon

    icon_path = MARKETPLACE_STORAGE_DIR / slug / icon_name
    if not icon_path.is_file():
        raise HTTPException(status_code=404, detail="图标文件不存在")
    media_type = _ICON_MIME_TYPES.get(icon_path.suffix.lower())
    if media_type is None:
        # 非白名单类型（svg/html 等）直接 404，防存储型 XSS
        raise HTTPException(status_code=404, detail="不支持的图标类型")
    return FileResponse(
        path=str(icon_path),
        media_type=media_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            # 禁止图标内容内的任何脚本/资源加载
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


# ==================== 评论 ====================

@router.get("/api/v1/marketplace/plugins/{slug}/reviews")
async def list_plugin_reviews(slug: str):
    """插件评论列表。"""
    async with get_session_ctx() as session:
        plugin = (await session.execute(
            select(MarketplacePluginModel).where(MarketplacePluginModel.slug == slug)
        )).scalar_one_or_none()
        if plugin is None:
            return {"code": 1, "message": f"插件不存在: {slug}", "data": None}
        reviews = (await session.execute(
            select(PluginReviewModel).where(PluginReviewModel.plugin_id == plugin.id)
            .order_by(desc(PluginReviewModel.created_at))
        )).scalars().all()

    data = [{"id": r.id, "user_id": r.user_id, "username": r.username,
             "rating": r.rating, "comment": r.comment, "created_at": r.created_at} for r in reviews]
    return {"code": 0, "message": "ok", "data": data}


@router.post("/api/v1/marketplace/plugins/{slug}/reviews")
async def create_plugin_review(
    slug: str,
    body: ReviewCreateReq,
    user: UserModel = Depends(get_current_user),
):
    """提交评论（JWT 认证，一人一评），更新插件 avg_rating。"""
    async with get_session_ctx() as session:
        plugin = (await session.execute(
            select(MarketplacePluginModel).where(MarketplacePluginModel.slug == slug).with_for_update()
        )).scalar_one_or_none()
        if plugin is None:
            return {"code": 1, "message": f"插件不存在: {slug}", "data": None}

        exists = await session.execute(
            select(PluginReviewModel.id).where(
                PluginReviewModel.plugin_id == plugin.id,
                PluginReviewModel.user_id == str(user.id),
            )
        )
        if exists.first() is not None:
            return {"code": 1, "message": "您已评论过该插件", "data": None}

        uname = _dev_name(user)
        review = PluginReviewModel(
            plugin_id=plugin.id, user_id=str(user.id), username=uname,
            rating=body.rating, comment=body.comment,
        )
        session.add(review)

        agg = (await session.execute(
            select(func.count(PluginReviewModel.id), func.avg(PluginReviewModel.rating))
            .where(PluginReviewModel.plugin_id == plugin.id)
        )).one()
        count, avg = agg
        new_count = (count or 0) + 1
        new_avg = float(body.rating) if avg is None else (float(avg) * (count or 0) + float(body.rating)) / new_count
        plugin.review_count = new_count
        plugin.avg_rating = round(new_avg, 4)
        await session.flush()
        review_id = review.id

    logger.info(f"[Marketplace] 评论: slug={slug} user={user.id} rating={body.rating}")
    return {"code": 0, "message": "ok", "data": {"review_id": review_id, "rating": body.rating,
            "avg_rating": round(new_avg, 2), "review_count": new_count}}


# ==================== 分类聚合 ====================

def _optional_category_keys(provides) -> set:
    """从可选插件的 provides 提取能力集合（仅 asr/llm/tts）。"""
    if isinstance(provides, dict):
        return {k for k in ("asr", "llm", "tts") if k in provides}
    return set()


def _count_optional_by_category(optional_plugins: list, category: str) -> int:
    """统计可选插件中属于指定分类的数量。"""
    cnt = 0
    for p in optional_plugins:
        keys = _optional_category_keys(p.get("provides"))
        if category == "ASR":
            if "asr" in keys:
                cnt += 1
        elif category == "LLM":
            if "llm" in keys:
                cnt += 1
        elif category == "TTS":
            if "tts" in keys:
                cnt += 1
        elif category == "其他工具":
            if not keys:
                cnt += 1
    return cnt


@router.get("/api/v1/marketplace/categories")
async def list_categories():
    """返回商店固定分类（ASR/LLM/TTS/其他工具）及插件数量（含内置可选插件）。"""
    async with get_session_ctx() as session:
        base = select(func.count(MarketplacePluginModel.id)).where(
            MarketplacePluginModel.is_active == True  # noqa: E712
        )
        data = []
        for cat in STORE_CATEGORIES:
            cond = _category_filter(cat["name"])
            cnt = 0
            if cond is not None:
                cnt = (await session.execute(base.where(cond))).scalar() or 0
            data.append({"name": cat["name"], "count": cnt})

    # 合并内置可选插件统计（商店页面同时展示市场插件与可选插件）
    from src.infrastructure.plugin_loader import get_optional_plugins_info
    optional = get_optional_plugins_info()
    for cat in data:
        cat["count"] += _count_optional_by_category(optional, cat["name"])

    return {"code": 0, "message": "ok", "data": data}


__all__ = [
    "router",
    "MAX_ZIP_MEMBER_SIZE",
    "MAX_ZIP_TOTAL_UNCOMPRESSED",
    "MAX_ZIP_MEMBERS",
    "create_zip_read_state",
    "read_zip_member_checked",
]
