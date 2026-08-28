"""表情包路由

表情包的查询、上传、删除、设备激活表情包等管理路由。

认证策略：
- 设备端兼容接口（GET /api/v1/emos, GET /api/v1/emos/{device_id}）无需认证
- 管理类接口（CRUD、上传、激活）使用 JWT 用户认证
"""
from __future__ import annotations

import json

from fastapi import Depends, APIRouter, Form, Request, UploadFile, File, HTTPException, Response

from src.infrastructure.logging import get_logger
from src.infrastructure.security_jwt import get_current_user
from src.infrastructure.db.models.user import UserModel
from src.infrastructure.routes._deps import check_device_owner as _check_device_owner
from src.infrastructure.emo_pack import (
    list_packs, get_pack_dir, create_pack, delete_pack,
    get_active_pack, set_active_pack, list_pack_emos,
    get_or_create_pack_dir, _validate_pack_name, PACKS_DIR,
)
from src.infrastructure.gif_processor import (
    process_gif, validate_size,
    describe_sources, build_emo_gif, MAX_SOURCES,
)

logger = get_logger(__name__)

# 上传 GIF 体积上限（与制作器共用）
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB

router = APIRouter(tags=["emos"])


# ── 兼容旧接口：GET /api/v1/emos/{device_id} ──
# 客户端启动时仍用此接口获取表情列表，现在返回设备激活的表情包内容
# 这些接口设备端使用，无需认证
@router.get("/api/v1/emos")
async def list_emos_compat(request: Request):
    host = request.headers.get("host", "localhost:8088")
    scheme = request.headers.get("x-forwarded-proto", "http")
    emos = list_pack_emos("default", scheme, host)
    return {"code": 0, "message": "ok", "data": emos}


@router.get("/api/v1/emos/{device_id}")
async def list_device_emos(device_id: str, request: Request):
    from src.infrastructure.device_api import resolve_device_id
    device_key = resolve_device_id(device_id)
    did = device_key if device_key and device_key != device_id else device_id
    pack_name = await get_active_pack(did)
    host = request.headers.get("host", "localhost:8088")
    scheme = request.headers.get("x-forwarded-proto", "http")
    emos = list_pack_emos(pack_name, scheme, host)
    if not emos:
        emos = list_pack_emos("default", scheme, host)
    return {"code": 0, "message": "ok", "data": emos, "active_pack": pack_name}


# ── 表情包 CRUD（JWT 用户认证）──

@router.get("/api/v1/emos/packs/list")
async def api_list_packs(user: UserModel = Depends(get_current_user)):
    return {"code": 0, "message": "ok", "data": await list_packs()}


@router.get("/api/v1/emos/packs/{pack_name}")
async def api_get_pack(pack_name: str, request: Request, user: UserModel = Depends(get_current_user)):
    host = request.headers.get("host", "localhost:8088")
    scheme = request.headers.get("x-forwarded-proto", "http")
    emos = list_pack_emos(pack_name, scheme, host)
    if emos is None:
        return {"code": 1, "message": f"表情包 '{pack_name}' 不存在", "data": None}
    return {"code": 0, "message": "ok", "data": emos}


@router.post("/api/v1/emos/packs/create")
async def api_create_pack(name: str = "", user: UserModel = Depends(get_current_user)):
    if not name:
        return {"code": 1, "message": "请提供表情包名称", "data": None}
    result = await create_pack(name)
    code = 0 if result["ok"] else 1
    data = {"name": result.get("name"), "display_name": result.get("display_name")} if result["ok"] else None
    return {"code": code, "message": result["message"], "data": data}


@router.delete("/api/v1/emos/packs/{pack_name}")
async def api_delete_pack(pack_name: str, user: UserModel = Depends(get_current_user)):
    result = await delete_pack(pack_name)
    code = 0 if result["ok"] else 1
    return {"code": code, "message": result["message"], "data": None}


@router.post("/api/v1/emos/packs/{pack_name}/upload")
async def api_upload_to_pack(pack_name: str, file: UploadFile = File(...), name: str = "", size: int = 0, user: UserModel = Depends(get_current_user)):
    # 校验 pack_name，防止路径遍历
    if not _validate_pack_name(pack_name):
        return {"code": 1, "message": "无效的表情包名称"}
    # 优先检查 name 参数的扩展名，其次检查原始文件名
    check_name = name if name else (file.filename or "")
    if not check_name or not check_name.lower().endswith(".gif"):
        return {"code": 1, "message": "仅支持 .gif 文件"}
    if file.size is not None and file.size > MAX_UPLOAD_SIZE:
        return {"code": 1, "message": f"文件过大，最大支持 {MAX_UPLOAD_SIZE // 1024 // 1024}MB"}
    target_dir = get_or_create_pack_dir(pack_name)
    if target_dir is None:
        return {"code": 1, "message": "无效的表情包名称"}
    # 优先使用客户端指定的文件名（与标准表情槽位名匹配）
    if name:
        save_filename = name if name.lower().endswith(".gif") else name + ".gif"
    else:
        save_filename = file.filename
    # 安全处理：只保留文件名部分，去除任何路径分隔符，防止路径遍历
    save_filename = str(save_filename).replace("\\", "/").split("/")[-1]
    if not save_filename or ".." in save_filename:
        return {"code": 1, "message": "无效的文件名"}
    save_path = target_dir / save_filename
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        return {"code": 1, "message": f"文件过大，最大支持 {MAX_UPLOAD_SIZE // 1024 // 1024}MB"}

    # 按用户选择的尺寸裁剪+缩放+压缩 GIF
    target_size = validate_size(size)
    if target_size > 0:
        content = process_gif(content, target_size)

    with open(str(save_path), "wb") as f:
        f.write(content)
    emo_name = save_filename.replace(".gif", "")
    return {
        "code": 0,
        "message": "ok",
        "data": {"name": emo_name, "filename": save_filename, "size": len(content), "pack": pack_name, "resize": target_size},
    }


# ── 兼容旧上传接口 ──
@router.post("/api/v1/emos/upload")
async def upload_emo_compat(file: UploadFile = File(...), device_key: str = "", size: int = 0, user: UserModel = Depends(get_current_user)):
    if not file.filename or not file.filename.lower().endswith(".gif"):
        return {"code": 1, "message": "仅支持 .gif 文件"}
    if file.size is not None and file.size > MAX_UPLOAD_SIZE:
        return {"code": 1, "message": f"文件过大，最大支持 {MAX_UPLOAD_SIZE // 1024 // 1024}MB"}
    target_dir = get_or_create_pack_dir("default")
    if target_dir is None:
        return {"code": 1, "message": "无效的表情包名称"}
    # 安全处理：只保留文件名部分，去除任何路径分隔符，防止路径遍历
    save_filename = str(file.filename).replace("\\", "/").split("/")[-1]
    if not save_filename or ".." in save_filename:
        return {"code": 1, "message": "无效的文件名"}
    save_path = target_dir / save_filename
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        return {"code": 1, "message": f"文件过大，最大支持 {MAX_UPLOAD_SIZE // 1024 // 1024}MB"}

    # 按用户选择的尺寸裁剪+缩放+压缩 GIF
    target_size = validate_size(size)
    if target_size > 0:
        content = process_gif(content, target_size)

    with open(str(save_path), "wb") as f:
        f.write(content)
    emo_name = save_filename.replace(".gif", "")
    return {
        "code": 0,
        "message": "ok",
        "data": {"name": emo_name, "filename": save_filename, "size": len(content), "pack": "default", "resize": target_size},
    }


# ── GIF 制作器：素材解析 + 合成（JWT 用户认证）──
# 前端把素材文件与帧参数发给服务端，由 Pillow 完成抽帧/合并/裁剪/缩放/压缩。
# 制作器接口无状态：素材每次随请求上传，处理完成后不落盘。

@router.post("/api/v1/emos/maker/sources")
async def api_maker_sources(
    files: list[UploadFile] = File(...),
    max_frames: int = Form(200),
    thumb_size: int = Form(64),
    user: UserModel = Depends(get_current_user),
):
    """解析上传素材，返回每帧缩略图与元数据（供帧编辑器使用）。"""
    if not files or len(files) > MAX_SOURCES:
        return {"code": 1, "message": f"一次最多上传 {MAX_SOURCES} 个素材"}
    if max_frames < 0 or max_frames > 500:
        max_frames = 200
    contents: list[tuple[str, bytes]] = []
    for f in files:
        data = await f.read()
        if len(data) > MAX_UPLOAD_SIZE:
            return {"code": 1, "message": f"单个素材最大 {MAX_UPLOAD_SIZE // 1024 // 1024}MB"}
        name = str(f.filename or "素材").replace("\\", "/").split("/")[-1]
        contents.append((name, data))
    sources = describe_sources(contents, max_frames, thumb_size)
    if not any(s.get("valid") for s in sources):
        return {"code": 1, "message": "无法解析任何素材，请上传 GIF/PNG/JPG/WebP 图片"}
    return {"code": 0, "message": "ok", "data": {"sources": sources}}


@router.post("/api/v1/emos/maker/process")
async def api_maker_process(
    files: list[UploadFile] = File(...),
    params: str = Form("{}"),
    user: UserModel = Depends(get_current_user),
):
    """按帧序列合成 GIF，直接返回 GIF 字节（Content-Type: image/gif）。

    params JSON::
        {"frames": [{"src":0,"frame":2}, {"src":1,"frame":0}],  # 有序帧序列
         "size": 240,        # 目标正方形边长（0=原尺寸）
         "delay": 100,       # 统一帧延迟 ms（缺省=保留原延迟）
         "loop": 0,          # 循环次数（0=无限）
         "fit": "crop"}      # crop=居中裁正方形 / fit=等比适配
    """
    try:
        p = json.loads(params) if params else {}
    except (ValueError, TypeError):
        return {"code": 1, "message": "参数格式错误"}
    frame_order = p.get("frames")
    if not isinstance(frame_order, list) or not frame_order:
        return {"code": 1, "message": "未选择任何帧"}
    if len(files) > MAX_SOURCES:
        return {"code": 1, "message": "素材过多"}
    contents: list[bytes] = []
    for f in files:
        data = await f.read()
        if len(data) > MAX_UPLOAD_SIZE:
            return {"code": 1, "message": f"单个素材最大 {MAX_UPLOAD_SIZE // 1024 // 1024}MB"}
        contents.append(data)

    try:
        size = int(p.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    delay = p.get("delay")
    try:
        delay = int(delay) if delay else None
    except (TypeError, ValueError):
        delay = None
    try:
        loop = int(p.get("loop") or 0)
    except (TypeError, ValueError):
        loop = 0
    fit = p.get("fit") if p.get("fit") in ("crop", "fit") else "crop"

    gif = build_emo_gif(contents, frame_order, target_size=size, delay=delay, loop=loop, fit=fit)
    if not gif:
        return {"code": 1, "message": "合成失败：帧索引无效或素材不可解码"}
    return Response(
        content=gif,
        media_type="image/gif",
        headers={
            "Content-Disposition": 'inline; filename="emo.gif"',
            "X-Gif-Frames": str(len(frame_order)),
            "X-Gif-Bytes": str(len(gif)),
        },
    )


# ── 设备激活表情包 ──

@router.get("/api/v1/emos/active/{device_id}")
async def api_get_active_pack(device_id: str):
    # 设备端获取激活表情包，无需认证
    from src.infrastructure.device_api import resolve_device_id
    device_key = resolve_device_id(device_id)
    did = device_key if device_key and device_key != device_id else device_id
    pack = await get_active_pack(did)
    return {"code": 0, "message": "ok", "data": {"device_id": did, "active_pack": pack}}


@router.post("/api/v1/emos/active/{device_id}")
async def api_set_active_pack(device_id: str, pack: str = "", user: UserModel = Depends(get_current_user)):
    # app 端设置激活表情包，需 JWT 认证 + 设备归属校验
    if not await _check_device_owner(device_id, user):
        raise HTTPException(403, "Device not bound to you")
    from src.infrastructure.device_api import resolve_device_id, get_device_registry
    device_key = resolve_device_id(device_id)
    did = device_key if device_key and device_key != device_id else device_id
    if not pack:
        return {"code": 1, "message": "请提供表情包名称", "data": None}
    result = await set_active_pack(did, pack)
    if not result["ok"]:
        return {"code": 1, "message": result["message"], "data": None}
    # 通知设备重新下载表情包
    try:
        registry = get_device_registry()
        if registry:
            d = registry.resolve(did)
            if d:
                channel = d.get("channel")
                if channel:
                    instruct = {"type": "instruct", "command_id": "refresh_emo", "data": ""}
                    await channel.send_json(instruct)
    except Exception as e:
        logger.debug(f"[EmoPack] 通知设备刷新表情包失败: {e}")
    return {"code": 0, "message": result["message"], "data": {"device_id": did, "active_pack": pack}}