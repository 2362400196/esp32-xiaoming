"""
Device Management API - 设备管理 API

提供以下功能：
- 获取在线设备列表
- 广播/单播 TTS 播放
- 广播/单播唤醒
- 设备统计和对话历史
- 设备配置管理
- 设备音量控制
- 系统配置和状态

认证方式：
- 外部调用使用 X-API-Key Header
- 设备连接使用 URL ?key= 参数
"""

from __future__ import annotations

import time
import asyncio
import json
import struct
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter, HTTPException, Header, Query, Form, UploadFile, Request
from fastapi import Depends
from src.infrastructure.security_jwt import get_current_user, require_admin
from src.infrastructure.db.models.user import UserModel
from pydantic import BaseModel

from src.infrastructure.logging import get_logger, info, warning, error
from src.infrastructure.config import get_settings

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["devices"])

sdk_router = APIRouter(tags=["devices"])


class DeviceInfo(BaseModel):
    mac: str
    device_key: str
    name: str
    state: str
    connected: bool
    tts_playing: bool = False
    session_id: str = ""


class DeviceListResponse(BaseModel):
    code: int
    message: str
    data: Optional[Dict[str, Any]] = None


class DeviceControlResponse(BaseModel):
    code: int
    message: str
    data: Optional[Dict[str, Any]] = None


class SpeakToDeviceRequest(BaseModel):
    text: str


class SpeakAllDevicesRequest(BaseModel):
    text: str


class SetVolumeRequest(BaseModel):
    volume: float


class SetBrightnessRequest(BaseModel):
    brightness: int


class SendEmotionRequest(BaseModel):
    emotion: str


async def verify_api_key(request: Request) -> bool:
    """验证 JWT Bearer Token"""
    auth_header = request.headers.get("authorization", "") or ""
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing valid Bearer token")
    token = auth_header[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing valid Bearer token")
    try:
        from src.infrastructure.security_jwt import decode_token
        payload = decode_token(token)
        if payload.get("type") == "access" and payload.get("sub"):
            return True
    except Exception:
        raise HTTPException(status_code=403, detail="Invalid or expired token")


async def require_device_owner(request: Request, device_ref: str) -> str:
    """校验 JWT 用户是该设备 owner（防串台：任何登录用户不得操作他人设备）。
    返回 DB 真实 device_id；未找到设备 404，非本人设备 403。
    兼容 mac_address / device_key / device_id 三种引用。"""
    auth_header = request.headers.get("authorization", "") or ""
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    if not token:
        raise HTTPException(status_code=401, detail="Missing valid Bearer token")
    from src.infrastructure.security_jwt import decode_token
    payload = decode_token(token) or {}
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=403, detail="Invalid or expired token")

    from src.infrastructure.db.repositories.device_repository import DeviceRepository
    from src.infrastructure.db.session import get_session_ctx
    from src.infrastructure.db.models.device import DeviceModel
    from sqlalchemy import select

    repo = DeviceRepository()
    found = await repo.find_by_mac(device_ref)
    if found is None:
        found = await repo.find_by_key(device_ref)
    if found is None:
        raise HTTPException(status_code=404, detail="Device not found")
    device_id, _ = found
    async with get_session_ctx() as session:
        result = await session.execute(
            select(DeviceModel.user_id).where(DeviceModel.device_id == device_id)
        )
        owner = result.scalar_one_or_none()
    if owner != user_id:
        raise HTTPException(status_code=403, detail="Device not bound to you")
    return device_id


def get_device_registry():
    from src.infrastructure.web import get_app
    app = get_app()
    if app is None:
        return None
    return getattr(app.state, 'device_registry', None)


def get_speaker():
    from src.infrastructure.web import get_app
    app = get_app()
    if app is None:
        return None
    return getattr(app.state, 'speaker', None)


def resolve_device_id(device_id: str):
    """解析设备标识符，返回 device_key

    查找顺序：
    1. 注册表 _mac_index（设备在线时）
    2. 注册表 _devices（device_id 即为 device_key）
    3. DB 回退（设备不在线时，按 mac_address / device_key / device_id 查找）
    4. 截断 MAC 回退（旧版缓冲区 18 字节截断为 17 字符的迁移场景）
    """
    registry = get_device_registry()

    if registry:
        device = registry.get_by_mac(device_id)
        if device:
            api_key = registry._mac_index.get(device_id)
            if api_key:
                return api_key
            return device_id

        device = registry.resolve(device_id)
        if device:
            return device_id

    # DB 回退：设备不在线或注册表为空时，从数据库查找
    try:
        from src.infrastructure.db.compat.sync_session import get_sync_session
        from src.infrastructure.db.models.device import DeviceModel
        from sqlalchemy import select, or_

        with get_sync_session() as session:
            result = session.execute(
                select(DeviceModel).where(
                    or_(
                        DeviceModel.mac_address == device_id,
                        DeviceModel.device_key == device_id,
                        DeviceModel.device_id == device_id,
                    )
                )
            )
            model = result.scalar_one_or_none()
            if model:
                return model.device_key

            # 截断 MAC 回退（旧版缓冲区 18 字节截断为 17 字符）
            if len(device_id) > 17:
                truncated = device_id[:17]
                result = session.execute(
                    select(DeviceModel).where(
                        or_(
                            DeviceModel.mac_address == truncated,
                            DeviceModel.device_id == truncated,
                        )
                    )
                )
                model = result.scalar_one_or_none()
                if model:
                    return model.device_key
    except Exception as e:
        logger.debug(f"[DeviceAPI] DB 回退解析设备 ID 失败: {e}")

    return None


def get_device_details(device_key: str) -> Optional[Dict[str, Any]]:
    """获取设备详细信息"""
    registry = get_device_registry()
    if not registry:
        return None

    device = registry.resolve(device_key)
    if not device:
        return None

    channel = device.get("channel")
    session = device.get("session")
    fsm = device.get("fsm")
    user_config = device.get("user_config")

    connected = False
    state = "unknown"
    session_id = ""
    tts_playing = False

    if channel and hasattr(channel, "connected"):
        connected = channel.connected

    if session:
        session_id = getattr(session, "session_id", "")
        tts_playing = getattr(session, "tts_playing", False)

    if fsm:
        try:
            current_state = fsm.get()
            state = current_state.value if hasattr(current_state, "value") else str(current_state)
        except Exception as e:
            logger.debug(f"[DeviceAPI] Failed to get FSM state: {e}")
            state = "unknown"

    name = ""
    if user_config:
        name = getattr(user_config, "name", "") or ""

    mac_addr = device.get("mac", "")

    uptime = 0
    if session and hasattr(session, "session_start_time"):
        uptime = round(time.time() - session.session_start_time, 1)

    messages_count = 0
    if session and hasattr(session, "conversation_memory"):
        memory = session.conversation_memory
        if memory and hasattr(memory, "message_count"):
            messages_count = memory.message_count

    return {
        "mac": mac_addr,
        "device_key": device_key,
        "name": name,
        "state": state,
        "connected": connected,
        "tts_playing": tts_playing,
        "session_id": session_id,
        "uptime": uptime,
        "messages_count": messages_count,
    }


# ═══════════════════════════════════════════════════════════════════
# 注意：设备列表 / 详情 / 控制（speak / wakeup / stop）路由已统一迁移至
#       routes/devices.py，统一使用 /api/v1/ 前缀。本文件仅保留设备
#       统计、历史、配置、音量、固件、OTA 等管理类路由。
# ═══════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════
# 设备统计和对话历史 API
# ═══════════════════════════════════════════════════════════════════

class DeviceStats(BaseModel):
    mac: str
    device_key: str
    uptime: float
    messages_count: int
    conversations_count: int
    last_activity: Optional[float] = None
    last_speak_time: Optional[float] = None
    last_wakeup_time: Optional[float] = None


@router.api_route("/devices/{mac}/stats", methods=["GET", "POST"], response_model=DeviceListResponse)
async def get_device_stats(mac: str, request: Request) -> DeviceListResponse:
    """获取设备统计信息"""
    await verify_api_key(request)
    await require_device_owner(request, mac)

    device_key = resolve_device_id(mac)
    if not device_key:
        return DeviceListResponse(code=1, message=f"Device not found: {mac}", data=None)

    device = get_device_details(device_key)
    if not device:
        return DeviceListResponse(code=1, message=f"Device not found: {mac}", data=None)

    session = None
    registry = get_device_registry()
    if registry:
        d = registry.resolve(device_key)
        if d:
            session = d.get("session")

    stats = DeviceStats(
        mac=mac,
        device_key=device_key,
        uptime=device.get("uptime", 0),
        messages_count=device.get("messages_count", 0),
        conversations_count=getattr(session, "conversations_count", 0) if session else 0,
        last_activity=getattr(session, "last_activity_time", None) if session else None,
        last_speak_time=getattr(session, "last_speak_time", None) if session else None,
        last_wakeup_time=getattr(session, "last_wakeup_time", None) if session else None,
    )

    return DeviceListResponse(code=0, message="ok", data=stats.model_dump())


class MessageHistory(BaseModel):
    role: str
    content: str
    timestamp: float


@router.get("/devices/{mac}/history", response_model=DeviceListResponse)
async def get_device_history(
    mac: str,
    request: Request,
    limit: int = Query(20, ge=1, le=100),
) -> DeviceListResponse:
    """获取设备对话历史（在线时从内存读，离线时从 DB 回退）"""
    await verify_api_key(request)
    db_device_id = await require_device_owner(request, mac)

    device_key = resolve_device_id(mac) or mac

    # 1. 优先从在线会话内存读取（最新消息）
    messages = []
    registry = get_device_registry()
    if registry:
        d = registry.resolve(device_key)
        if d:
            session = d.get("session")
            memory = getattr(session, "conversation_memory", None) if session else None
            if memory and hasattr(memory, "messages"):
                for msg in memory.messages[-limit:]:
                    messages.append(MessageHistory(
                        role=msg.get("role", "user"),
                        content=msg.get("content", ""),
                        timestamp=msg.get("timestamp", 0),
                    ).model_dump())

    # 2. 内存无数据时从 DB 回退（设备离线也能读到历史）
    if not messages:
        try:
            from src.infrastructure.db.repositories.short_term_memory_repo import SqlShortTermMemoryRepository
            repo = SqlShortTermMemoryRepository()
            # 短期记忆以 device_key 为键存储，回退尝试 device_key / db_device_id / mac
            for key in (device_key, db_device_id, mac):
                if not key:
                    continue
                db_msgs = repo.load(key)
                if db_msgs:
                    for msg in db_msgs[-limit:]:
                        messages.append(MessageHistory(
                            role=msg.get("role", "user"),
                            content=msg.get("content", ""),
                            timestamp=msg.get("timestamp", 0),
                        ).model_dump())
                    break
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"[API] DB 回退读取历史失败 mac={mac}: {e}")

    return DeviceListResponse(code=0, message="ok", data={"mac": mac, "messages": messages, "count": len(messages)})


@router.post("/devices/{mac}/history", response_model=DeviceControlResponse)
async def clear_device_history(mac: str, request: Request) -> DeviceControlResponse:
    """清空设备对话历史"""
    await verify_api_key(request)
    await require_device_owner(request, mac)

    device_key = resolve_device_id(mac)
    if not device_key:
        return DeviceControlResponse(code=1, message=f"Device not found: {mac}", data=None)

    registry = get_device_registry()
    if not registry:
        return DeviceControlResponse(code=1, message="Device registry not available", data=None)

    d = registry.resolve(device_key)
    if not d:
        return DeviceControlResponse(code=1, message=f"Device not found: {mac}", data=None)

    session = d.get("session")
    if not session:
        return DeviceControlResponse(code=1, message="Session not available", data=None)

    memory = getattr(session, "conversation_memory", None)
    if memory and hasattr(memory, "clear"):
        memory.clear()
        logger.info(f"[DeviceAPI] Cleared history for {mac}")
        return DeviceControlResponse(code=0, message="History cleared", data={"mac": mac})

    return DeviceControlResponse(code=1, message="Memory not available", data=None)


# ═══════════════════════════════════════════════════════════════════
# 设备配置管理 API
# ═══════════════════════════════════════════════════════════════════

class DeviceConfig(BaseModel):
    """设备配置更新模型 — 覆盖 devices 表中所有字段"""

    # ── 顶层标量字段 ──
    name: Optional[str] = None
    key: Optional[str] = None
    asr_provider: Optional[str] = None
    llm_type: Optional[str] = None
    tts_type: Optional[str] = None
    rate_limit_rpm: Optional[int] = None
    proactive_max_pushes: Optional[int] = None
    disabled_tools: Optional[list[str]] = None
    disabled_skills: Optional[list[str]] = None
    # 设备级插件白名单：配置后只启用列出的插件（空/None = 全部启用）
    enabled_plugins: Optional[list[str]] = None
    # 设备是否有屏幕（C3 headless=False，S3=True）；决定屏幕类插件工具是否可用
    has_display: Optional[bool] = None

    # ── LLM 子字段（映射到 llm.xxx）──
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_model: Optional[str] = None
    llm_system_prompt: Optional[str] = None
    memory_enabled: Optional[bool] = None
    memory_max_messages: Optional[int] = None

    # ── TTS 子字段（映射到 tts_config.xxx）──
    tts_api_key: Optional[str] = None
    tts_resource_id: Optional[str] = None
    voice_type: Optional[str] = None
    speed_ratio: Optional[float] = None
    volume_ratio: Optional[float] = None
    pitch_ratio: Optional[float] = None
    tts_volume: Optional[float] = None
    # 火山 OpenAPI 凭据(tts_config.volc_openapi):设备级 AK/SK/项目名,用于查询复刻音色列表
    tts_volc_openapi: Optional[dict] = None
    # ── TTS 连接池参数（映射到 tts_config.xxx）──
    tts_enable_pool: Optional[bool] = None
    tts_pool_max_size: Optional[int] = None
    tts_pool_min_size: Optional[int] = None
    tts_pool_heartbeat_interval: Optional[int] = None
    tts_pool_idle_timeout: Optional[int] = None
    tts_pool_connection_timeout: Optional[int] = None

    # ── TTS 整体替换 ──
    tts_config: Optional[dict] = None

    # ── ASR 子字段（映射到 asr_config.volcengine.xxx）──
    asr_api_key: Optional[str] = None
    asr_resource_id: Optional[str] = None
    asr_model: Optional[str] = None

    # ── ASR 整体替换 ──
    asr_config: Optional[dict] = None

    # ── Music 子字段（映射到 music.xxx）──
    music_api_url: Optional[str] = None
    music_lyrics_offset: Optional[int] = None

    # ── Music 整体替换 ──
    music: Optional[dict] = None

    # ── Wakeup 子字段（映射到 wakeup.xxx）──
    wakeup_text: Optional[str] = None
    wakeup_enable_audio: Optional[bool] = None
    wakeup_cache_enabled: Optional[bool] = None
    wakeup_play_enabled: Optional[bool] = None
    wakeup_audio_source: Optional[str] = None
    wakeup_play_on_next_round: Optional[bool] = None

    # ── Wakeup 整体替换 ──
    wakeup: Optional[dict] = None

    # ── MCP Servers 整体替换 ──
    mcp_servers: Optional[dict] = None


# ── 平面字段 → 嵌套路径映射 ──
# 用于将 DeviceConfig 的平面字段名写入 devices 表的正确嵌套位置
_CONFIG_FIELD_MAP: dict[str, list[str]] = {
    # 顶层标量
    "name": ["name"],
    "key": ["key"],
    "asr_provider": ["asr_provider"],
    "llm_type": ["llm_type"],
    "tts_type": ["tts_type"],
    "rate_limit_rpm": ["rate_limit_rpm"],
    "disabled_tools": ["disabled_tools"],
    "disabled_skills": ["disabled_skills"],
    "enabled_plugins": ["enabled_plugins"],
    "has_display": ["has_display"],
    # llm.*
    "llm_api_key": ["llm", "api_key"],
    "llm_base_url": ["llm", "base_url"],
    "llm_model": ["llm", "model"],
    "llm_system_prompt": ["llm", "system_prompt"],
    "memory_enabled": ["llm", "memory_enabled"],
    "memory_max_messages": ["llm", "memory_max_messages"],
    # tts_config.*
    "tts_api_key": ["tts_config", "api_key"],
    "tts_resource_id": ["tts_config", "resource_id"],
    "voice_type": ["tts_config", "voice_type"],
    "tts_volc_openapi": ["tts_config", "volc_openapi"],
    "speed_ratio": ["tts_config", "speed_ratio"],
    "volume_ratio": ["tts_config", "volume_ratio"],
    "pitch_ratio": ["tts_config", "pitch_ratio"],
    "tts_volume": ["tts_config", "volume"],
    # tts_config 连接池参数
    "tts_enable_pool": ["tts_config", "enable_pool"],
    "tts_pool_max_size": ["tts_config", "pool_max_size"],
    "tts_pool_min_size": ["tts_config", "pool_min_size"],
    "tts_pool_heartbeat_interval": ["tts_config", "pool_heartbeat_interval"],
    "tts_pool_idle_timeout": ["tts_config", "pool_idle_timeout"],
    "tts_pool_connection_timeout": ["tts_config", "pool_connection_timeout"],
    # 主动推送配置（存在 wakeup 配置中）
    "proactive_max_pushes": ["wakeup", "proactive_max_pushes"],
    # wakeup 子字段
    "wakeup_text": ["wakeup", "text"],
    "wakeup_enable_audio": ["wakeup", "enable_audio"],
    "wakeup_cache_enabled": ["wakeup", "cache_enabled"],
    "wakeup_play_enabled": ["wakeup", "play_enabled"],
    "wakeup_audio_source": ["wakeup", "source"],
    "wakeup_play_on_next_round": ["wakeup", "play_on_next_round"],
    # asr_config.volcengine.*
    "asr_api_key": ["asr_config", "volcengine", "api_key"],
    "asr_resource_id": ["asr_config", "volcengine", "resource_id"],
    "asr_model": ["asr_config", "volcengine", "model"],
    # music.*
    "music_api_url": ["music", "api_url"],
    "music_lyrics_offset": ["music", "lyrics_offset"],
}

# ── 需要整体替换的 dict 字段（不深度合并，直接覆盖）──
_CONFIG_DICT_FIELDS = {"tts_config", "asr_config", "music", "wakeup", "mcp_servers"}


def _apply_config_update(device_cfg: dict, flat_key: str, value: Any) -> None:
    """将平面字段名及其值写入 device_cfg 的正确嵌套位置"""
    if value is None:
        return

    # 整块 dict 替换
    if flat_key in _CONFIG_DICT_FIELDS:
        device_cfg[flat_key] = value
        return

    # 通过路径映射写入
    path = _CONFIG_FIELD_MAP.get(flat_key)
    if not path:
        return

    target = device_cfg
    for i, segment in enumerate(path):
        if i == len(path) - 1:
            target[segment] = value
        else:
            target = target.setdefault(segment, {})


@router.get("/devices/{mac}/config", response_model=DeviceListResponse)
async def get_device_config(mac: str, request: Request) -> DeviceListResponse:
    """获取设备配置（阶段 3：从 DB 读取完整数据）"""
    await verify_api_key(request)
    await require_device_owner(request, mac)

    # mac 参数可能是 WiFi MAC 或 device_key，先尝试通过注册表解析
    device_key = resolve_device_id(mac)
    if not device_key:
        device_key = mac  # 设备未连接时，直接用传入值作为 device_key 尝试

    try:
        from src.infrastructure.db.repositories.device_repository import DeviceRepository
        repo = DeviceRepository()
        # 优先按 MAC 查询，其次按 device_key 查询，最后直接按传入值查找
        found = await repo.find_by_mac(mac)
        if found is None:
            found = await repo.find_by_key(device_key)
        if found is None and device_key != mac:
            found = await repo.find_by_key(mac)
        if found is None:
            return DeviceListResponse(code=1, message=f"Device {mac} not found in DB", data=None)

        device_id_in_db, raw_config = found
        config = {
            "mac": mac,
            "device_key": device_key,
            **raw_config,
        }
        return DeviceListResponse(code=0, message="ok", data=config)
    except Exception as e:
        logger.warning(f"[DeviceAPI] DB 读取设备配置失败: {e}")
        return DeviceListResponse(code=1, message=f"Failed to read device config: {e}", data=None)


@router.post("/devices/{mac}/config", response_model=DeviceControlResponse)
async def update_device_config(
    mac: str,
    config_data: DeviceConfig,
    request: Request,
) -> DeviceControlResponse:
    """更新设备配置（阶段 3：保存到 DB 并热更新）"""
    await verify_api_key(request)
    await require_device_owner(request, mac)

    device_key = resolve_device_id(mac)
    if not device_key:
        device_key = mac

    updates = config_data.model_dump(exclude_none=True)
    if not updates:
        return DeviceControlResponse(code=1, message="No config to update", data=None)

    logger.info(f"[DeviceAPI] Updating config for {mac}: {updates}")

    # 阶段 3：通过 DeviceRepository 写入 DB
    try:
        from src.infrastructure.db.repositories.device_repository import DeviceRepository
        repo = DeviceRepository()
        # 优先按 MAC 查找设备，其次按 device_key
        found = await repo.find_by_mac(mac)
        if found is None:
            found = await repo.find_by_key(device_key)
        if found is None:
            return DeviceControlResponse(code=1, message=f"Device {mac} not found in DB", data=None)

        device_id_in_db = found[0]
        # 将平面字段名映射到嵌套结构后，整体更新到 DB
        nested_updates: dict = {}
        for key, value in updates.items():
            _apply_config_update(nested_updates, key, value)
        updated = await repo.update_device_partial(device_id_in_db, nested_updates)
        if updated is None:
            return DeviceControlResponse(code=1, message=f"Device {mac} not found in DB", data=None)
        logger.info(f"[DeviceAPI] Saved config for {mac} to DB")
    except Exception as e:
        logger.warning(f"[DeviceAPI] DB 写入设备配置失败: {e}")
        return DeviceControlResponse(code=1, message=f"Failed to write device config: {e}", data=None)

    # 重新加载 auth 配置，使新配置对后续设备连接生效
    try:
        from src.infrastructure.web import get_app
        _app = get_app()
        if _app:
            auth = getattr(_app.state, 'auth_service', None)
            if auth and hasattr(auth, 'reload_users_config'):
                auth.reload_users_config()
                logger.info(f"[DeviceAPI] Reloaded auth config for {mac}")
    except Exception as e:
        logger.warning(f"[DeviceAPI] Failed to reload auth config: {e}")

    registry = get_device_registry()
    if registry:
        d = registry.resolve(device_key)
        if d:
            # ── ③ 热重载：更新在线的 DeviceConfig 对象 ──
            try:
                from src.use_cases.auxiliary_services import load_devices
                dm = load_devices()
                fresh_config = dm.resolve(device_key)
                if fresh_config:
                    d["user_config"] = fresh_config
                    # 更新 tool_manager 的引用
                    if d.get("tool_manager"):
                        d["tool_manager"].user_config = fresh_config
                    # 更新 session 的引用（session 在连接时存了一份 user_config）
                    if d.get("session"):
                        d["session"].user_config = fresh_config
                    logger.info(f"[DeviceAPI] Hot-reloaded DeviceConfig for {mac}")
            except Exception as e:
                logger.warning(f"[DeviceAPI] Failed to hot-reload DeviceConfig: {e}")

            # ── ⑤ 唤醒配置变更时清除缓存 ──
            if "wakeup" in updates:
                try:
                    from src.infrastructure.web import get_app
                    _app = get_app()
                    wam = getattr(_app.state, 'wake_audio_manager', None)
                    if wam:
                        wam.clear_cache()
                        logger.info(f"[DeviceAPI] Cleared wake audio cache for {mac} due to wakeup config change")
                except Exception as e:
                    logger.warning(f"[DeviceAPI] Failed to clear wake audio cache: {e}")

            # ── ④ 推送运行时变更到硬件设备 ──
            # 注意：llm_system_prompt / voice_type / speed 等是服务端消费的配置
            # （LLM/TTS 网关在会话中读取），esp-ai-idf-client 固件本地不读取它们，
            # 下发 update_config 只会触发设备写 NVS 的无效操作（llm_system_prompt
            # 超过 NVS 15 字符键名限制还会刷日志）。因此这里不再推送这些服务端专用键。
            # 设备真正需要即时生效的参数（如音量）走独立的 /volume、OTA 等指令通道。

            # ── ⑥ 配置变更 → 通知设备自动重连(热更新) ──
            # ASR/TTS 网关是连接级(会话建立时按配置创建),配置改了必须重连才刷新。
            # 设备收到 config_updated 后会自动重连 WS,重新握手/初始化使全部新配置生效。
            try:
                registry.set_pending_instruct(device_key, {
                    "type": "instruct",
                    "command_id": "config_updated",
                    "data": {"reason": "config changed"},
                })
                logger.info(f"[DeviceAPI] 已推送 config_updated 给 {mac},设备将自动重连应用新配置")
            except Exception as e:
                logger.warning(f"[DeviceAPI] 推送 config_updated 失败: {e}")

    return DeviceControlResponse(
        code=0,
        message="Config updated",
        data={"mac": mac, "config": updates}
    )


@router.post("/devices/{mac}/unbind", response_model=DeviceControlResponse)
async def unbind_device(
    mac: str,
    request: Request,
) -> DeviceControlResponse:
    """解绑设备：清空所有配置（恢复出厂设置）"""
    await verify_api_key(request)
    await require_device_owner(request, mac)

    device_key = resolve_device_id(mac)
    if not device_key:
        device_key = mac

    logger.warning(f"[DeviceAPI] 解绑设备 {mac}，将清空所有配置")

    try:
        from src.infrastructure.db.repositories.device_repository import DeviceRepository
        repo = DeviceRepository()
        found = await repo.find_by_mac(mac)
        if found is None:
            found = await repo.find_by_key(device_key)
        if found is None:
            return DeviceControlResponse(code=1, message=f"Device {mac} not found in DB", data=None)
        device_id_in_db = found[0]
        ok = await repo.reset_device(device_id_in_db)
        if not ok:
            return DeviceControlResponse(code=1, message="Reset failed", data=None)
    except Exception as e:
        logger.error(f"[DeviceAPI] 解绑设备失败: {e}")
        return DeviceControlResponse(code=1, message=f"Unbind failed: {e}", data=None)

    # 断开在线设备的连接
    try:
        registry = get_device_registry()
        if registry:
            d = registry.resolve(device_key)
            if d:
                logger.info(f"[DeviceAPI] 向在线设备 {mac} 发送 factory_reset 指令")
                import json as _json
                factory_instruct = {
                    "type": "instruct",
                    "command_id": "factory_reset",
                    "data": "{}",
                }
                channel = d.get("channel")
                if channel and channel.connected:
                    # 先发 factory_reset，设备收到后会清 NVS + 重启
                    await channel.send_json(factory_instruct)
                    logger.info(f"[DeviceAPI] factory_reset 已发送到设备 {mac}")
                    # 等待一小段时间让消息送达
                    await asyncio.sleep(0.5)
                # 然后关闭会话
                from src.use_cases.auxiliary_services import create_speaker
                speaker = get_speaker()
                if speaker:
                    await speaker.stop(device_key)
    except Exception as e:
        logger.warning(f"[DeviceAPI] 断开设备失败: {e}")

    # 清除 wake 音频缓存
    try:
        from src.infrastructure.web import get_app
        _app = get_app()
        wam = getattr(_app.state, 'wake_audio_manager', None)
        if wam:
            wam.clear_cache()
    except Exception as e:
        pass

    logger.info(f"[DeviceAPI] 设备 {mac} 解绑完成")
    return DeviceControlResponse(code=0, message="设备已解绑，所有配置已清空", data={"mac": mac})


# ═══════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════
# 火山复刻音色查询 API
# ═══════════════════════════════════════════════════════════════════

@router.get("/tts/clone-voices", response_model=DeviceControlResponse)
async def list_clone_voices(request: Request, mac: str = Query("")) -> DeviceControlResponse:
    """查询火山账号下已有的复刻音色列表(供 App"声音复刻"模型下拉选择)。

    凭据优先级:设备配置(tts_config.volc_openapi,存数据库)> 环境变量
    (VOLC_ACCESS_KEY_ID / VOLC_SECRET_ACCESS_KEY / VOLC_PROJECT_NAME)。
    """
    await verify_api_key(request)
    if mac:
        await require_device_owner(request, mac)
    try:
        from src.infrastructure.volc_openapi import get_clone_voices_cached
        credentials = await _get_device_volc_credentials(mac) if mac else None
        # state 传空 = 返回全部状态(Success/Active/Unknown 等),避免 Active 过滤导致列表为空
        voices = await get_clone_voices_cached(credentials=credentials)
        return DeviceControlResponse(code=0, message="OK", data={"voices": voices})
    except Exception as e:
        logger.warning(f"[DeviceAPI] 查询复刻音色列表失败: {e}")
        return DeviceControlResponse(code=1, message=str(e), data=None)


async def _get_device_volc_credentials(mac: str) -> dict | None:
    """从设备配置读取火山 OpenAPI 凭据(tts_config.volc_openapi)。

    数据库(设备配置)优先;设备未配置时返回 None,由调用方回退环境变量。
    返回 {access_key_id, secret_access_key, project_name}
    """
    try:
        from src.infrastructure.db.repositories.device_repository import DeviceRepository
        repo = DeviceRepository()
        found = await repo.find_by_mac(mac)
        if found is None:
            found = await repo.find_by_key(mac)
        if not found:
            return None
        _, raw_config = found
        tts_cfg = (raw_config or {}).get("tts_config") or {}
        vo = tts_cfg.get("volc_openapi") or {}
        ak = (vo.get("access_key_id") or "").strip()
        sk = (vo.get("secret_access_key") or "").strip()
        if not ak or not sk:
            return None
        return {
            "access_key_id": ak,
            "secret_access_key": sk,
            "project_name": (vo.get("project_name") or "").strip() or "default",
        }
    except Exception as e:
        logger.warning(f"[DeviceAPI] 读取设备火山 OpenAPI 凭据失败: {e}")
        return None


def _fix_wav_header(data: bytes) -> bytes:
    """修复火山试听音频的流式 WAV 头。

    火山的 demo_audio 是 RIFF/data chunk size 均为 0xFFFFFFFF 的流式 WAV
    (文件大小未知标记),Android 等播放器无法解析(MediaError -99)。
    这里把 RIFF 大小与 data chunk 大小改为实际值,生成标准 WAV。

    按 RIFF chunk 结构遍历定位 data chunk(而非字节搜索,避免误匹配),
    仅当 data chunk 的 size 为 0xFFFFFFFF(流式,数据延伸到文件尾)时重写。
    """
    if len(data) < 12 or data[:4] != b"RIFF":
        return data
    buf = bytearray(data)
    buf[4:8] = struct.pack("<I", len(data) - 8)
    # 遍历 chunk(RIFF 头后,对齐到 2 字节边界)
    pos = 12
    data_pos = -1
    while pos + 8 <= len(buf):
        cid = bytes(buf[pos : pos + 4])
        csize = struct.unpack("<I", bytes(buf[pos + 4 : pos + 8]))[0]
        if cid == b"data":
            data_pos = pos
            break
        if csize == 0xFFFFFFFF or csize > len(buf) - (pos + 8):
            break  # 流式或越界,无法继续
        pos += 8 + csize + (csize & 1)
    if data_pos > 0 and data_pos + 8 <= len(buf):
        cur = struct.unpack("<I", bytes(buf[data_pos + 4 : data_pos + 8]))[0]
        if cur == 0xFFFFFFFF:
            buf[data_pos + 4 : data_pos + 8] = struct.pack("<I", len(buf) - (data_pos + 8))
    return bytes(buf)


@router.get("/tts/clone-voices/preview")
async def preview_clone_voice(request: Request, speaker_id: str = Query(...), mac: str = Query("")):
    """试听复刻音色:服务端拉取火山的 demo_audio 试听音频并转发为标准 audio/wav。

    火山返回的 demo_audio 是带签名的临时 URL(约 1 小时有效),且无文件扩展名、
    Content-Type 为 audio/wave,App 播放器直接播放容易失败。这里由服务端代理
    拉取后以同源 audio/wav 返回,App 播放服务端地址即可。

    注意:失败时返回非 200 状态码(404/502/500),避免 App 把 JSON 错误当音频播放。
    """
    await verify_api_key(request)
    if mac:
        await require_device_owner(request, mac)
    try:
        from fastapi.responses import Response
        import httpx
        from src.infrastructure.volc_openapi import get_clone_voices_cached

        credentials = await _get_device_volc_credentials(mac) if mac else None
        voices = await get_clone_voices_cached(credentials=credentials)
        voice = next((v for v in voices if v["speaker_id"] == speaker_id), None)
        if not voice or not voice.get("demo_audio"):
            logger.warning(f"[DeviceAPI] 试听: 未找到音色或无可试听音频 speaker_id={speaker_id}")
            raise HTTPException(status_code=404, detail="未找到该音色或无可试听音频")
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(voice["demo_audio"])
            if resp.status_code != 200:
                logger.warning(f"[DeviceAPI] 试听: 火山拉取失败 HTTP {resp.status_code} speaker_id={speaker_id}")
                raise HTTPException(status_code=502, detail="试听音频拉取失败(链接可能已过期)")
            logger.info(f"[DeviceAPI] 试听: {speaker_id} 音频 {len(resp.content)} bytes")
            return Response(
                content=_fix_wav_header(resp.content),
                media_type="audio/wav",
                headers={"Content-Disposition": 'inline; filename="preview.wav"'},
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[DeviceAPI] 试听复刻音色异常 speaker_id={speaker_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="试听音频获取失败")


# 设备音量控制 API
# ═══════════════════════════════════════════════════════════════════

@router.post("/devices/{mac}/volume", response_model=DeviceControlResponse)
async def set_device_volume(
    mac: str,
    body: SetVolumeRequest,
    request: Request,
) -> DeviceControlResponse:
    """设置设备音量"""
    await verify_api_key(request)
    await require_device_owner(request, mac)
    volume = body.volume
    if volume < 0.0 or volume > 1.0:
        return DeviceControlResponse(code=1, message="Volume must be between 0.0 and 1.0", data=None)

    device_key = resolve_device_id(mac)
    if not device_key:
        return DeviceControlResponse(code=1, message=f"Device not found: {mac}", data=None)

    registry = get_device_registry()
    if not registry:
        return DeviceControlResponse(code=1, message="Device registry not available", data=None)

    d = registry.resolve(device_key)
    if not d:
        return DeviceControlResponse(code=1, message=f"Device not found: {mac}", data=None)

    channel = d.get("channel")
    if not channel:
        return DeviceControlResponse(code=1, message="Channel not available", data=None)

    try:
        # 通过 WebSocket 推送音量指令到设备
        instruct = {
            "type": "instruct",
            "command_id": "set_volume",
            "data": str(volume),
        }
        await channel.send_json(instruct)

        # 缓存音量值（WSChannel.__init__ 已初始化 _volume=1.0）
        channel._volume = volume

        logger.info(f"[DeviceAPI] Set volume for {mac}: {volume}")
        return DeviceControlResponse(code=0, message="Volume set", data={"mac": mac, "volume": volume})
    except Exception as e:
        return DeviceControlResponse(code=1, message=f"Failed to set volume: {str(e)}", data=None)


@router.get("/devices/{mac}/volume", response_model=DeviceListResponse)
async def get_device_volume(mac: str, request: Request) -> DeviceListResponse:
    """获取设备音量

    设备在线时通过 WebSocket 主动查询真实音量（get_volume 指令），
    设备回复 device_state_result 格式 "volume=XX"（百分比整数）；
    超时或离线时回退到 channel._volume 缓存值。
    """
    await verify_api_key(request)
    await require_device_owner(request, mac)

    device_key = resolve_device_id(mac)
    if not device_key:
        return DeviceListResponse(code=1, message=f"Device not found: {mac}", data=None)

    registry = get_device_registry()
    if not registry:
        return DeviceListResponse(code=1, message="Device registry not available", data=None)

    d = registry.resolve(device_key)
    if not d:
        return DeviceListResponse(code=1, message=f"Device not found: {mac}", data=None)

    channel = d.get("channel")
    # 回退缓存值（WSChannel.__init__ 已初始化 _volume=1.0）
    volume = getattr(channel, "_volume", 1.0) if channel else 1.0

    # 设备在线时主动查询真实音量
    tool_mgr = d.get("tool_manager")
    if channel and channel.connected and tool_mgr is not None:
        from src.use_cases._plugin_helpers import request_device_result
        raw, status, _ = await request_device_result(
            tool_mgr, "get_volume", "_pending_device_state_future", timeout=3.0, if_busy="busy",
        )
        if status == "ok" and isinstance(raw, str) and raw.startswith("volume="):
            pct = int(raw[len("volume="):].strip())
            volume = max(0.0, min(1.0, pct / 100.0))
            channel._volume = volume
            logger.info(f"[DeviceAPI] Queried volume for {mac}: {volume} ({pct}%)")
        elif status == "busy":
            logger.debug(f"[DeviceAPI] Volume query skipped, future busy for {mac}")
        elif status == "timeout":
            logger.warning(f"[DeviceAPI] Volume query timeout for {mac}, using cached: {volume}")
        else:
            logger.warning(f"[DeviceAPI] Volume query failed for {mac}: {status}, using cached: {volume}")

    return DeviceListResponse(code=0, message="ok", data={"mac": mac, "volume": volume})


# ═══════════════════════════════════════════════════════════════════
# 设备亮度控制 API
# ═══════════════════════════════════════════════════════════════════

@router.post("/devices/{mac}/brightness", response_model=DeviceControlResponse)
async def set_device_brightness(
    mac: str,
    body: SetBrightnessRequest,
    request: Request,
) -> DeviceControlResponse:
    """设置设备屏幕亮度（0-100 整数百分比）"""
    await verify_api_key(request)
    await require_device_owner(request, mac)
    brightness = body.brightness
    if brightness < 0 or brightness > 100:
        return DeviceControlResponse(code=1, message="Brightness must be between 0 and 100", data=None)

    device_key = resolve_device_id(mac)
    if not device_key:
        return DeviceControlResponse(code=1, message=f"Device not found: {mac}", data=None)

    registry = get_device_registry()
    if not registry:
        return DeviceControlResponse(code=1, message="Device registry not available", data=None)

    d = registry.resolve(device_key)
    if not d:
        return DeviceControlResponse(code=1, message=f"Device not found: {mac}", data=None)

    channel = d.get("channel")
    if not channel:
        return DeviceControlResponse(code=1, message="Channel not available", data=None)

    try:
        # 通过 WebSocket 推送亮度指令到设备（设备端接收 0-100 整数）
        from src.use_cases._plugin_helpers import send_instruct
        await send_instruct(channel, "set_brightness", str(brightness))

        # 缓存亮度值（WSChannel.__init__ 已初始化 _brightness=100）
        channel._brightness = brightness

        logger.info(f"[DeviceAPI] Set brightness for {mac}: {brightness}")
        return DeviceControlResponse(code=0, message="Brightness set", data={"mac": mac, "brightness": brightness})
    except Exception as e:
        return DeviceControlResponse(code=1, message=f"Failed to set brightness: {str(e)}", data=None)


@router.get("/devices/{mac}/brightness", response_model=DeviceListResponse)
async def get_device_brightness(mac: str, request: Request) -> DeviceListResponse:
    """获取设备屏幕亮度

    设备在线时通过 WebSocket 主动查询真实亮度（get_brightness 指令），
    设备回复 device_state_result 格式 "brightness=XX"（百分比整数）；
    超时或离线时回退到 channel._brightness 缓存值。
    """
    await verify_api_key(request)
    await require_device_owner(request, mac)

    device_key = resolve_device_id(mac)
    if not device_key:
        return DeviceListResponse(code=1, message=f"Device not found: {mac}", data=None)

    registry = get_device_registry()
    if not registry:
        return DeviceListResponse(code=1, message="Device registry not available", data=None)

    d = registry.resolve(device_key)
    if not d:
        return DeviceListResponse(code=1, message=f"Device not found: {mac}", data=None)

    channel = d.get("channel")
    brightness = getattr(channel, "_brightness", 100) if channel else 100

    # 设备在线时主动查询真实亮度
    tool_mgr = d.get("tool_manager")
    if channel and channel.connected and tool_mgr is not None:
        from src.use_cases._plugin_helpers import request_device_result
        raw, status, _ = await request_device_result(
            tool_mgr, "get_brightness", "_pending_device_state_future", timeout=3.0, if_busy="busy",
        )
        if status == "ok" and isinstance(raw, str) and raw.startswith("brightness="):
            val = int(raw[len("brightness="):].strip())
            brightness = max(0, min(100, val))
            channel._brightness = brightness
            logger.info(f"[DeviceAPI] Queried brightness for {mac}: {brightness}%")
        elif status == "busy":
            logger.debug(f"[DeviceAPI] Brightness query skipped, future busy for {mac}")
        elif status == "timeout":
            logger.warning(f"[DeviceAPI] Brightness query timeout for {mac}, using cached: {brightness}")
        else:
            logger.warning(f"[DeviceAPI] Brightness query failed for {mac}: {status}, using cached: {brightness}")

    return DeviceListResponse(code=0, message="ok", data={"mac": mac, "brightness": brightness})


@router.post("/devices/{mac}/emotion", response_model=DeviceControlResponse)
async def send_device_emotion(
    mac: str,
    body: SendEmotionRequest,
    request: Request,
) -> DeviceControlResponse:
    """发送情绪表情到设备屏幕

    通过 WebSocket 推送 {"type":"emotion","data":"快乐"} 到设备，
    设备收到后调用 display_show_emotion() 渲染对应 GIF。
    """
    await verify_api_key(request)
    await require_device_owner(request, mac)

    emotion = body.emotion.strip()
    if not emotion:
        return DeviceControlResponse(code=1, message="emotion cannot be empty", data=None)

    device_key = resolve_device_id(mac)
    if not device_key:
        return DeviceControlResponse(code=1, message=f"Device not found: {mac}", data=None)

    registry = get_device_registry()
    if not registry:
        return DeviceControlResponse(code=1, message="Device registry not available", data=None)

    d = registry.resolve(device_key)
    if not d:
        return DeviceControlResponse(code=1, message=f"Device not found: {mac}", data=None)

    channel = d.get("channel")
    if not channel or not getattr(channel, "connected", False):
        return DeviceControlResponse(code=1, message="Device offline", data=None)

    try:
        msg = {"type": "emotion", "data": emotion}
        await channel.send_json(msg)
        logger.info(f"[DeviceAPI] Sent emotion '{emotion}' to {mac}")
        return DeviceControlResponse(code=0, message="Emotion sent", data={"mac": mac, "emotion": emotion})
    except Exception as e:
        return DeviceControlResponse(code=1, message=f"Failed to send emotion: {str(e)}", data=None)


# ═══════════════════════════════════════════════════════════════════
# 系统配置和状态 API
# ═══════════════════════════════════════════════════════════════════



# ═══════════════════════════════════════════════════════════════════
# 固件管理 API
# ═══════════════════════════════════════════════════════════════════

import os
import shutil
from pathlib import Path
from typing import List


FIRMWARE_DIR = Path(__file__).parent.parent / "firmware"
FIRMWARE_DIR.mkdir(parents=True, exist_ok=True)


class FirmwareInfo(BaseModel):
    filename: str
    size: int
    created_time: float
    version: Optional[str] = None
    download_url: str


class FirmwareListResponse(BaseModel):
    code: int
    message: str
    data: Optional[Dict[str, Any]] = None


def get_firmware_base_url() -> str:
    """获取固件下载基础 URL"""
    host = "localhost"
    port = 8088
    try:
        settings = get_settings()
        host = settings.server.host
        port = settings.server.port
    except Exception as e:
        logger.debug(f"[DeviceAPI] 读取固件服务器配置失败: {e}")
    if host == "0.0.0.0":
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            host = s.getsockname()[0]
            s.close()
        except Exception:
            host = "localhost"
    return f"http://{host}:{port}/firmware"


def get_firmware_info(filename: str) -> Optional[FirmwareInfo]:
    """获取固件文件信息"""
    filepath = FIRMWARE_DIR / filename
    if not filepath.exists():
        return None
    stat = filepath.stat()
    return FirmwareInfo(
        filename=filename,
        size=stat.st_size,
        created_time=stat.st_mtime,
        version="",
        download_url=f"{get_firmware_base_url()}/{filename}",
    )


def list_firmwares() -> List[FirmwareInfo]:
    """列出所有固件"""
    firmwares = []
    for f in FIRMWARE_DIR.iterdir():
        if f.is_file() and f.suffix in (".bin", ".elf", ".hex"):
            info = get_firmware_info(f.name)
            if info:
                firmwares.append(info)
    return sorted(firmwares, key=lambda x: x.created_time, reverse=True)


@router.post("/firmware/upload", response_model=FirmwareListResponse)
async def upload_firmware(
    file: UploadFile,
    request: Request,
    _admin: UserModel = Depends(require_admin),
    version: Optional[str] = Form(None),
) -> FirmwareListResponse:
    """
    上传固件文件
    
    - file: 固件文件 (.bin, .elf, .hex)
    - version: (可选) 版本号
    """
    await verify_api_key(request)

    if not file.filename:
        return FirmwareListResponse(code=1, message="No file provided", data=None)

    allowed_extensions = {".bin", ".elf", ".hex"}
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed_extensions:
        return FirmwareListResponse(
            code=1,
            message=f"Invalid file type. Allowed: {', '.join(allowed_extensions)}",
            data=None
        )

    safe_filename = "".join(c for c in file.filename if c.isalnum() or c in "._-")
    filepath = FIRMWARE_DIR / safe_filename

    try:
        with open(filepath, "wb") as f:
            shutil.copyfileobj(file.file, f)

        info = get_firmware_info(safe_filename)
        if info and version:
            info.version = version

        logger.info(f"[Firmware] Uploaded: {safe_filename}, size: {info.size if info else 0} bytes")
        return FirmwareListResponse(
            code=0,
            message="Firmware uploaded successfully",
            data=info.model_dump() if info else {"filename": safe_filename}
        )
    except Exception as e:
        logger.error(f"[Firmware] Upload failed: {e}")
        return FirmwareListResponse(code=1, message=f"Upload failed: {str(e)}", data=None)


@router.get("/firmware", response_model=FirmwareListResponse)
async def list_firmwares_api(request: Request, _admin: UserModel = Depends(require_admin)) -> FirmwareListResponse:
    """获取固件列表"""
    await verify_api_key(request)

    firmwares = list_firmwares()
    return FirmwareListResponse(
        code=0,
        message="ok",
        data={
            "count": len(firmwares),
            "firmwares": [f.model_dump() for f in firmwares],
            "base_url": get_firmware_base_url(),
        }
    )


@router.post("/firmware/{filename}", response_model=FirmwareListResponse)
async def delete_firmware(
    filename: str,
    request: Request,
    _admin: UserModel = Depends(require_admin),
) -> FirmwareListResponse:
    """删除固件文件"""
    await verify_api_key(request)

    safe_filename = "".join(c for c in filename if c.isalnum() or c in "._-")
    filepath = FIRMWARE_DIR / safe_filename

    if not filepath.exists():
        return FirmwareListResponse(code=1, message="Firmware not found", data=None)

    try:
        filepath.unlink()
        logger.info(f"[Firmware] Deleted: {safe_filename}")
        return FirmwareListResponse(
            code=0,
            message="Firmware deleted",
            data={"filename": safe_filename}
        )
    except Exception as e:
        return FirmwareListResponse(code=1, message=f"Delete failed: {str(e)}", data=None)


@router.get("/firmware/{filename}", response_model=FirmwareListResponse)
async def get_firmware_info_api(
    filename: str,
    request: Request,
    _admin: UserModel = Depends(require_admin),
) -> FirmwareListResponse:
    """获取固件信息"""
    await verify_api_key(request)

    safe_filename = "".join(c for c in filename if c.isalnum() or c in "._-")
    info = get_firmware_info(safe_filename)

    if not info:
        return FirmwareListResponse(code=1, message="Firmware not found", data=None)

    return FirmwareListResponse(code=0, message="ok", data=info.model_dump())


@router.post("/firmware/default", response_model=FirmwareListResponse)
async def set_default_firmware(
    filename: str,
    request: Request,
    _admin: UserModel = Depends(require_admin),
    version: Optional[str] = Form(None),
) -> FirmwareListResponse:
    """
    设置默认固件（用于 OTA 升级）
    
    - filename: 固件文件名
    - version: (可选) 版本号
    """
    await verify_api_key(request)

    safe_filename = "".join(c for c in filename if c.isalnum() or c in "._-")
    info = get_firmware_info(safe_filename)

    if not info:
        return FirmwareListResponse(code=1, message="Firmware not found", data=None)

    from src.infrastructure.config import get_settings, OTAConfig
    settings = get_settings()
    settings.ota.bin_url = info.download_url
    if version:
        settings.ota.version = version
    settings.ota.bin_id = safe_filename

    logger.info(f"[Firmware] Set default: {safe_filename}, URL: {info.download_url}")
    return FirmwareListResponse(
        code=0,
        message="Default firmware set",
        data={
            "filename": safe_filename,
            "url": info.download_url,
            "version": version or "",
            "size": info.size,
        }
    )


# ═══════════════════════════════════════════════════════════════════
# OTA 固件升级 API
# ═══════════════════════════════════════════════════════════════════

class OTARequest(BaseModel):
    url: Optional[str] = None
    version: Optional[str] = None
    bin_id: Optional[str] = None
    is_official: Optional[str] = None


class OTAResponse(BaseModel):
    code: int
    message: str
    data: Optional[Dict[str, Any]] = None


async def _send_ota_to_device(device_key: str, url: str, version: str = "", user_config=None) -> Dict[str, Any]:
    """向指定设备发送 OTA 升级命令（通过 pending_ota 机制）"""
    registry = get_device_registry()
    if not registry:
        return {"success": False, "error": "Device registry not available"}

    device = registry.resolve(device_key)
    if not device:
        return {"success": False, "error": "Device not found"}

    channel = device.get("channel")
    if not channel:
        return {"success": False, "error": "Channel not available"}

    if not channel.connected:
        return {"success": False, "error": "Channel not connected"}

    import json as _json
    ota_data = {"url": url}
    if version:
        ota_data["version"] = version

    ota_command = {
        "type": "instruct",
        "command_id": "ota_update",
        "data": _json.dumps(ota_data, ensure_ascii=False),
    }

    registry.set_pending_ota(device_key, ota_command)
    logger.info(f"[OTA] 已设置 pending_ota: device_key={device_key}, command={ota_command}")
    return {"success": True, "device_key": device_key, "method": "pending_ota"}


def _get_ota_config() -> Dict[str, Any]:
    """获取全局 OTA 配置"""
    settings = get_settings()
    ota = getattr(settings, 'ota', None)
    if not ota:
        return {
            "enabled": True,
            "bin_url": "",
            "version": "",
            "bin_id": "",
            "is_official": "0",
        }
    return {
        "enabled": getattr(ota, 'enabled', True),
        "bin_url": getattr(ota, 'bin_url', ""),
        "version": getattr(ota, 'version', ""),
        "bin_id": getattr(ota, 'bin_id', ""),
        "is_official": getattr(ota, 'is_official', "0"),
        "query_url": getattr(ota, 'query_url', ""),
    }


@router.post("/devices/{mac}/ota", response_model=OTAResponse)
async def push_ota_to_device(
    mac: str,
    request: Request,
    ota_request: OTARequest = OTARequest(),
) -> OTAResponse:
    """
    向指定设备推送 OTA 固件升级
    
    - mac: 设备 MAC 地址
    - url: (可选) 固件下载 URL，不填则使用设备配置 > 全局配置的 URL
    - version: (可选) 固件版本号
    - bin_id: (可选) bin ID
    - is_official: (可选) 是否官方版本 "0" 或 "1"
    """
    await verify_api_key(request)
    await require_device_owner(request, mac)

    device_key = resolve_device_id(mac)
    logger.info(f"[OTA] push_ota_to_device: mac={mac}, resolved_key={device_key}")
    if not device_key:
        return OTAResponse(code=1, message=f"Device not found: {mac}", data=None)

    registry = get_device_registry()
    if not registry:
        return OTAResponse(code=1, message="Device registry not available", data=None)

    device = registry.resolve(device_key)
    if not device:
        logger.warning(f"[OTA] registry.resolve({device_key}) returned None")
        return OTAResponse(code=1, message=f"Device not found: {mac}", data=None)

    user_config = device.get("user_config")
    device_ota_config = {}
    if user_config and hasattr(user_config, 'get_ota_config'):
        device_ota_config = user_config.get_ota_config()

    global_ota_config = _get_ota_config()

    device_ota_enabled = device_ota_config.get("enabled", True) if device_ota_config else True
    global_ota_enabled = global_ota_config.get("enabled", True)
    if not device_ota_enabled or not global_ota_enabled:
        return OTAResponse(code=1, message="OTA upgrade is disabled for this device", data=None)

    url = ota_request.url or device_ota_config.get("bin_url", "") or global_ota_config.get("bin_url", "")
    if not url:
        firmwares = list_firmwares()
        if firmwares:
            url = firmwares[0].download_url
            logger.info(f"[OTA] 使用本地固件: {firmwares[0].filename} -> {url}")

    if not url:
        logger.warning("[OTA] 未配置固件 URL，且本地无固件文件")
        return OTAResponse(code=1, message="OTA URL not configured and no local firmware found. Upload firmware first via /api/v1/firmware/upload", data=None)

    version = ota_request.version or device_ota_config.get("version", "") or global_ota_config.get("version", "")
    bin_id = ota_request.bin_id or device_ota_config.get("bin_id", "") or global_ota_config.get("bin_id", "")
    is_official = ota_request.is_official or device_ota_config.get("is_official", "") or global_ota_config.get("is_official", "0")

    current_firmware = device.get("firmware_version", "")
    if current_firmware and version and current_firmware == version:
        return OTAResponse(
            code=1,
            message=f"Device already on version {version}",
            data={"mac": mac, "current_version": current_firmware, "target_version": version}
        )

    if device.get("ota_updating", False):
        return OTAResponse(
            code=1,
            message="Device is already upgrading",
            data={"mac": mac, "progress": device.get("ota_progress", 0)}
        )

    logger.info(f"[OTA] 发送升级命令: device_key={device_key}, url={url}, version={version}")
    result = await _send_ota_to_device(device_key, url, version, user_config)

    if result.get("success"):
        return OTAResponse(
            code=0,
            message="OTA upgrade command sent",
            data={
                "mac": mac,
                "url": url,
                "version": version,
                "bin_id": bin_id,
                "is_official": is_official,
                "current_firmware": current_firmware,
            }
        )
    else:
        return OTAResponse(code=1, message=f"Failed to send OTA: {result.get('error')}", data=None)


@router.post("/devices/{mac}/ota/force", response_model=OTAResponse)
async def force_ota_to_device(
    mac: str,
    request: Request,
    ota_request: OTARequest = OTARequest(),
) -> OTAResponse:
    """
    强制向指定设备推送 OTA 固件升级（跳过版本检查）
    
    - mac: 设备 MAC 地址
    - url: (可选) 固件下载 URL，不填则使用设备配置 > 全局配置的 URL
    - version: (可选) 固件版本号
    - bin_id: (可选) bin ID
    - is_official: (可选) 是否官方版本 "0" 或 "1"
    """
    await verify_api_key(request)
    await require_device_owner(request, mac)

    device_key = resolve_device_id(mac)
    logger.info(f"[OTA] force_ota_to_device: mac={mac}, resolved_key={device_key}")
    if not device_key:
        return OTAResponse(code=1, message=f"Device not found: {mac}", data=None)

    registry = get_device_registry()
    if not registry:
        return OTAResponse(code=1, message="Device registry not available", data=None)

    device = registry.resolve(device_key)
    if not device:
        logger.warning(f"[OTA] registry.resolve({device_key}) returned None")
        return OTAResponse(code=1, message=f"Device not found: {mac}", data=None)

    user_config = device.get("user_config")
    device_ota_config = {}
    if user_config and hasattr(user_config, 'get_ota_config'):
        device_ota_config = user_config.get_ota_config()

    global_ota_config = _get_ota_config()

    url = ota_request.url or device_ota_config.get("bin_url", "") or global_ota_config.get("bin_url", "")
    if not url:
        firmwares = list_firmwares()
        if firmwares:
            url = firmwares[0].download_url
            logger.info(f"[OTA] 强制升级使用本地固件: {firmwares[0].filename} -> {url}")

    if not url:
        logger.warning("[OTA] 未配置固件 URL，且本地无固件文件")
        return OTAResponse(code=1, message="OTA URL not configured and no local firmware found. Upload firmware first via /api/v1/firmware/upload", data=None)

    version = ota_request.version or device_ota_config.get("version", "") or global_ota_config.get("version", "")
    bin_id = ota_request.bin_id or device_ota_config.get("bin_id", "") or global_ota_config.get("bin_id", "")
    is_official = ota_request.is_official or device_ota_config.get("is_official", "") or global_ota_config.get("is_official", "0")

    current_firmware = device.get("firmware_version", "")

    logger.info(f"[OTA] 强制升级: device_key={device_key}, url={url}, version={version}")
    result = await _send_ota_to_device(device_key, url, version, user_config)

    if result.get("success"):
        return OTAResponse(
            code=0,
            message="Force OTA upgrade command sent",
            data={
                "mac": mac,
                "url": url,
                "version": version,
                "bin_id": bin_id,
                "is_official": is_official,
                "current_firmware": current_firmware,
            }
        )
    else:
        return OTAResponse(code=1, message=f"Failed to send OTA: {result.get('error')}", data=None)


class WifiConfigRequest(BaseModel):
    ssid: str
    password: str = ""


@router.post("/devices/{mac}/wifi", response_model=OTAResponse)
async def set_device_wifi(
    mac: str,
    wifi_req: WifiConfigRequest,
    request: Request,
) -> OTAResponse:
    """
    远程修改设备 WiFi 配置
    
    - mac: 设备 MAC 地址
    - ssid: 新的 WiFi 名称
    - password: 新的 WiFi 密码（可选）
    """
    await verify_api_key(request)
    await require_device_owner(request, mac)

    device_key = resolve_device_id(mac)
    logger.info(f"[Wifi] set_device_wifi: mac={mac}, resolved_key={device_key}, ssid={wifi_req.ssid}")
    if not device_key:
        return OTAResponse(code=1, message=f"Device not found: {mac}", data=None)

    registry = get_device_registry()
    if not registry:
        return OTAResponse(code=1, message="Device registry not available", data=None)

    device = registry.resolve(device_key)
    if not device:
        logger.warning(f"[Wifi] registry.resolve({device_key}) returned None")
        return OTAResponse(code=1, message=f"Device not found: {mac}", data=None)

    channel = device.get("channel")
    if not channel or not channel.connected:
        return OTAResponse(code=1, message="Device not connected", data=None)

    configs = {
        "wifi_name": wifi_req.ssid,
        "wifi_pwd": wifi_req.password,
    }

    wifi_command = {
        "type": "set_wifi_config",
        "configs": configs,
    }

    registry.set_pending_wifi_config(device_key, wifi_command)
    logger.info(f"[Wifi] 已设置待推送WiFi配置: device_key={device_key}, ssid={wifi_req.ssid}")

    return OTAResponse(
        code=0,
        message="WiFi config command sent, device will restart to apply",
        data={"mac": mac, "ssid": wifi_req.ssid}
    )


class MicPinsRequest(BaseModel):
    bck: int
    ws: int
    data: int


class SpeakerPinsRequest(BaseModel):
    bck: int
    ws: int
    data: int


@router.post("/devices/{mac}/pins/mic", response_model=OTAResponse)
async def set_mic_pins(
    mac: str,
    pins: MicPinsRequest,
    request: Request,
) -> OTAResponse:
    """
    远程设置麦克风 (INMP441) I2S 引脚
    
    - mac: 设备 MAC 地址
    - bck: BCK 引脚 (位时钟)
    - ws: WS 引脚 (字选择/左右时钟)
    - data: SD/DIN 引脚 (数据输入)
    
    设备会自动重启以应用新配置
    """
    await verify_api_key(request)
    await require_device_owner(request, mac)

    device_key = resolve_device_id(mac)
    logger.info(f"[Pins] set_mic_pins: mac={mac}, bck={pins.bck}, ws={pins.ws}, data={pins.data}")
    if not device_key:
        return OTAResponse(code=1, message=f"Device not found: {mac}", data=None)

    registry = get_device_registry()
    if not registry:
        return OTAResponse(code=1, message="Device registry not available", data=None)

    device = registry.resolve(device_key)
    if not device:
        return OTAResponse(code=1, message=f"Device not found: {mac}", data=None)

    channel = device.get("channel")
    if not channel or not channel.connected:
        return OTAResponse(code=1, message="Device not connected", data=None)

    import json as _json
    instruct = {
        "type": "instruct",
        "command_id": "set_mic_pins",
        "data": _json.dumps({"bck": pins.bck, "ws": pins.ws, "data": pins.data}, ensure_ascii=False),
    }
    registry.set_pending_instruct(device_key, instruct)

    return OTAResponse(
        code=0,
        message="Mic pin config command sent, device will restart to apply",
        data={"mac": mac, "bck": pins.bck, "ws": pins.ws, "data": pins.data}
    )


@router.post("/devices/{mac}/pins/speaker", response_model=OTAResponse)
async def set_speaker_pins(
    mac: str,
    pins: SpeakerPinsRequest,
    request: Request,
) -> OTAResponse:
    """
    远程设置扬声器 (MAX98357A) I2S 引脚
    
    - mac: 设备 MAC 地址
    - bck: BCLK 引脚 (位时钟)
    - ws: LRC 引脚 (左右时钟)
    - data: DIN 引脚 (数据输入)
    
    设备会自动重启以应用新配置
    """
    await verify_api_key(request)
    await require_device_owner(request, mac)

    device_key = resolve_device_id(mac)
    logger.info(f"[Pins] set_speaker_pins: mac={mac}, bck={pins.bck}, ws={pins.ws}, data={pins.data}")
    if not device_key:
        return OTAResponse(code=1, message=f"Device not found: {mac}", data=None)

    registry = get_device_registry()
    if not registry:
        return OTAResponse(code=1, message="Device registry not available", data=None)

    device = registry.resolve(device_key)
    if not device:
        return OTAResponse(code=1, message=f"Device not found: {mac}", data=None)

    channel = device.get("channel")
    if not channel or not channel.connected:
        return OTAResponse(code=1, message="Device not connected", data=None)

    import json as _json
    instruct = {
        "type": "instruct",
        "command_id": "set_speaker_pins",
        "data": _json.dumps({"bck": pins.bck, "ws": pins.ws, "data": pins.data}, ensure_ascii=False),
    }
    registry.set_pending_instruct(device_key, instruct)

    return OTAResponse(
        code=0,
        message="Speaker pin config command sent, device will restart to apply",
        data={"mac": mac, "bck": pins.bck, "ws": pins.ws, "data": pins.data}
    )


@router.post("/devices/ota/all", response_model=OTAResponse)
async def push_ota_to_all_devices(
    request: Request,
    ota_request: OTARequest = OTARequest(),
    _admin: UserModel = Depends(require_admin),
) -> OTAResponse:
    """
    向所有在线设备推送 OTA 固件升级
    
    - url: (可选) 固件下载 URL，不填则使用设备配置 > 全局配置的 URL
    - version: (可选) 固件版本号
    - bin_id: (可选) bin ID
    - is_official: (可选) 是否官方版本 "0" 或 "1"
    """
    await verify_api_key(request)

    registry = get_device_registry()
    if not registry or registry.count() == 0:
        return OTAResponse(code=0, message="No online devices", data={"total": 0, "succeeded": 0, "failed": 0, "devices": []})

    global_ota_config = _get_ota_config()
    if not global_ota_config.get("enabled", True):
        return OTAResponse(code=1, message="Global OTA upgrade is disabled", data=None)

    fallback_url = ota_request.url or global_ota_config.get("bin_url", "")
    if not fallback_url:
        firmwares = list_firmwares()
        if firmwares:
            fallback_url = firmwares[0].download_url
            logger.info(f"[OTA] 批量升级使用本地固件: {firmwares[0].filename} -> {fallback_url}")

    device_keys = list(registry._devices.keys())
    results = []
    succeeded = 0
    failed = 0
    skipped = 0

    for device_key in device_keys:
        device = registry.resolve(device_key)
        if not device:
            continue

        user_config = device.get("user_config")
        device_ota_config = {}
        if user_config and hasattr(user_config, 'get_ota_config'):
            device_ota_config = user_config.get_ota_config()

        device_ota_enabled = device_ota_config.get("enabled", True) if device_ota_config else True
        if not device_ota_enabled:
            results.append({
                "device_key": device_key,
                "mac": device.get("mac", ""),
                "success": False,
                "error": "OTA disabled for this device",
            })
            skipped += 1
            continue

        if device.get("ota_updating", False):
            results.append({
                "device_key": device_key,
                "mac": device.get("mac", ""),
                "success": False,
                "error": "Already upgrading",
            })
            failed += 1
            continue

        url = ota_request.url or device_ota_config.get("bin_url", "") or global_ota_config.get("bin_url", "") or fallback_url
        if not url:
            results.append({
                "device_key": device_key,
                "mac": device.get("mac", ""),
                "success": False,
                "error": "OTA URL not configured",
            })
            failed += 1
            continue

        version = ota_request.version or device_ota_config.get("version", "") or global_ota_config.get("version", "")
        current_firmware = device.get("firmware_version", "")
        if current_firmware and version and current_firmware == version:
            results.append({
                "device_key": device_key,
                "mac": device.get("mac", ""),
                "success": False,
                "error": f"Already on version {version}",
            })
            failed += 1
            continue

        result = await _send_ota_to_device(device_key, url, version, user_config)
        if result.get("success"):
            succeeded += 1
            results.append({
                "device_key": device_key,
                "success": True,
                "mac": device.get("mac", ""),
            })
        else:
            failed += 1
            results.append({
                "device_key": device_key,
                "success": False,
                "error": result.get("error", "Unknown error"),
            })

    logger.info(f"[OTA] Batch upgrade: {succeeded} succeeded, {failed} failed, {skipped} skipped out of {len(device_keys)} devices")

    return OTAResponse(
        code=0,
        message=f"OTA upgrade pushed to {succeeded}/{len(device_keys)} devices",
        data={
            "total": len(device_keys),
            "succeeded": succeeded,
            "failed": failed,
            "skipped": skipped,
            "devices": results,
        }
    )


@router.get("/devices/ota/status", response_model=OTAResponse)
async def get_ota_status(request: Request) -> OTAResponse:
    """获取所有设备 OTA 升级状态"""
    await verify_api_key(request)

    registry = get_device_registry()
    if not registry:
        return OTAResponse(code=1, message="Device registry not available", data=None)

    ota_config = _get_ota_config()

    devices = []
    upgrading_count = 0
    for device_key in list(registry._devices.keys()):
        device = registry.resolve(device_key)
        if device:
            devices.append({
                "device_key": device_key,
                "mac": device.get("mac", ""),
                "firmware_version": device.get("firmware_version", ""),
                "ota_updating": device.get("ota_updating", False),
                "ota_progress": device.get("ota_progress", 0),
            })
            if device.get("ota_updating", False):
                upgrading_count += 1

    return OTAResponse(
        code=0,
        message="ok",
        data={
            "total_devices": len(devices),
            "upgrading_count": upgrading_count,
            "global_version": ota_config.get("version", ""),
            "devices": devices,
        }
    )


@router.get("/devices/{mac}/ota/status", response_model=OTAResponse)
async def get_device_ota_status(mac: str, request: Request) -> OTAResponse:
    """获取指定设备 OTA 升级状态"""
    await verify_api_key(request)
    await require_device_owner(request, mac)

    device_key = resolve_device_id(mac)
    if not device_key:
        return OTAResponse(code=1, message=f"Device not found: {mac}", data=None)

    registry = get_device_registry()
    if not registry:
        return OTAResponse(code=1, message="Device registry not available", data=None)

    device = registry.resolve(device_key)
    if not device:
        return OTAResponse(code=1, message=f"Device not found: {mac}", data=None)

    return OTAResponse(
        code=0,
        message="ok",
        data={
            "mac": mac,
            "firmware_version": device.get("firmware_version", ""),
            "ota_updating": device.get("ota_updating", False),
            "ota_progress": device.get("ota_progress", 0),
        }
    )


@router.post("/devices/{mac}/ota/reset", response_model=OTAResponse)
async def reset_device_ota(mac: str, request: Request) -> OTAResponse:
    """重置设备 OTA 状态（当升级卡住时使用）"""
    await verify_api_key(request)
    await require_device_owner(request, mac)

    device_key = resolve_device_id(mac)
    if not device_key:
        return OTAResponse(code=1, message=f"Device not found: {mac}", data=None)

    registry = get_device_registry()
    if not registry:
        return OTAResponse(code=1, message="Device registry not available", data=None)

    registry.set_ota_updating(device_key, False)
    logger.info(f"[OTA] 重置设备 OTA 状态: {mac}")

    return OTAResponse(code=0, message="OTA status reset", data={"mac": mac})


@router.post("/devices/{mac}/test", response_model=OTAResponse)
async def test_device_ws(mac: str, request: Request) -> OTAResponse:
    """测试设备 WebSocket 通信（通过 pending_ota 机制）"""
    await verify_api_key(request)
    await require_device_owner(request, mac)

    device_key = resolve_device_id(mac)
    if not device_key:
        return OTAResponse(code=1, message=f"Device not found: {mac}", data=None)

    registry = get_device_registry()
    if not registry:
        return OTAResponse(code=1, message="Device registry not available", data=None)

    device = registry.resolve(device_key)
    if not device:
        return OTAResponse(code=1, message=f"Device not found: {mac}", data=None)

    channel = device.get("channel")
    if not channel:
        return OTAResponse(code=1, message="No channel", data=None)

    ws = channel.websocket
    diag = {
        "connected": channel.connected,
        "queue_size": channel.send_queue.qsize(),
        "send_loop_alive": not channel._send_task.done() if channel._send_task else False,
        "ws_client_state": ws.client_state.name if ws and hasattr(ws, 'client_state') else "no_ws",
    }

    if not channel.connected:
        return OTAResponse(code=1, message="Channel not connected", data=diag)

    test_command = {"type": "set_volume", "volume": 80}
    registry.set_pending_ota(device_key, test_command)
    diag["pending_ota_set"] = True
    diag["pending_ota_command"] = test_command
    logger.info(f"[TEST] 已设置 pending_ota: {test_command}")

    return OTAResponse(code=0, message="Test command queued via pending_ota (will be sent on next keepalive)", data=diag)


# ═══════════════════════════════════════════════════════════════════
# SDK OTA 查询接口（设备主动拉取更新）
# ═══════════════════════════════════════════════════════════════════

@sdk_router.get("/sdk/query_new_ota")
async def sdk_query_new_ota(
    version: str = Query(""),
    bin_id: str = Query(""),
    is_official: str = Query("0"),
    mac: str = Query(""),
):
    """
    设备 OTA 更新查询接口

    ESP 客户端 auto_update() 调用此接口检查是否有新固件。
    请求: GET /sdk/query_new_ota?version=1.0.0&bin_id=xxx&is_official=0&mac=xx:xx:xx:xx
    响应: {"success": true, "data": {"latest": false, "bin_url": "http://..."}}

    判断优先级（从高到低）：
      1. 设备级 ota_bin_id（数据库中每设备独立）与客户端 bin_id 比对
      2. 全局 ota_bin_id 与客户端 bin_id 比对
      3. 版本号比对（设备级 > 全局）
    """
    settings = get_settings()
    ota = getattr(settings, 'ota', None)

    global_ota_enabled = getattr(ota, 'enabled', True) if ota else True
    if not global_ota_enabled:
        return {"success": False, "message": "OTA disabled"}

    # ── 1. 从数据库查询设备级 OTA 配置 ──
    device_ota = {}
    device_ota_enabled = True
    if mac:
        try:
            from src.infrastructure.db.compat.sync_session import get_sync_session
            from src.infrastructure.db.models.device import DeviceModel
            from sqlalchemy import select, or_

            def _query_device():
                with get_sync_session() as session:
                    result = session.execute(
                        select(DeviceModel).where(
                            or_(
                                DeviceModel.mac_address == mac,
                                DeviceModel.device_id == mac,
                                DeviceModel.device_key == mac,
                            )
                        )
                    )
                    model = result.scalar_one_or_none()
                    if not model:
                        return None
                    return {
                        "ota_enabled": model.ota_enabled,
                        "ota_bin_url": model.ota_bin_url or "",
                        "ota_version": model.ota_version or "",
                        "ota_bin_id": model.ota_bin_id or "",
                        "ota_is_official": model.ota_is_official or "0",
                    }

            import asyncio
            device_ota = await asyncio.to_thread(_query_device)
            if device_ota:
                device_ota_enabled = device_ota.get("ota_enabled", True)
                logger.info(f"[SDK OTA] 设备 {mac} 级配置: "
                            f"bin_id='{device_ota.get('ota_bin_id', '')}', "
                            f"version='{device_ota.get('ota_version', '')}', "
                            f"bin_url='{device_ota.get('ota_bin_url', '')}'")
            else:
                logger.info(f"[SDK OTA] 设备 {mac} 未在数据库中找到，使用全局配置")
        except Exception as e:
            logger.warning(f"[SDK OTA] 查询设备 {mac} OTA 配置失败: {e}，使用全局配置")

    if not device_ota_enabled:
        return {"success": True, "data": {"latest": True, "bin_url": ""}}

    # ── 2. 合并配置：设备级优先，全局回退 ──
    global_bin_id = getattr(ota, 'bin_id', '') if ota else ''
    global_bin_url = getattr(ota, 'bin_url', '') if ota else ''
    global_version = getattr(ota, 'version', '') if ota else ''

    effective_bin_id = device_ota.get("ota_bin_id", "") or global_bin_id
    effective_bin_url = device_ota.get("ota_bin_url", "") or global_bin_url
    effective_version = device_ota.get("ota_version", "") or global_version

    # 回退到本地上传的固件
    if not effective_bin_url:
        firmwares = list_firmwares()
        if firmwares:
            effective_bin_url = firmwares[0].download_url
            logger.info(f"[SDK OTA] 使用本地固件: {firmwares[0].filename} -> {effective_bin_url}")

    if not effective_bin_url:
        logger.info(f"[SDK OTA] 无可用固件, version={version}, bin_id={bin_id}, mac={mac}")
        return {"success": True, "data": {"latest": True, "bin_url": ""}}

    # ── 3. 最高优先级：bin_id 比对 ──
    # 设备传的 bin_id 与服务端 effective_bin_id 相同 → 已是最新
    if effective_bin_id and bin_id and effective_bin_id == bin_id:
        logger.info(f"[SDK OTA] bin_id 相同, 已是最新: "
                    f"device_bin_id={bin_id}, effective_bin_id={effective_bin_id}, mac={mac}")
        return {"success": True, "data": {"latest": True, "bin_url": ""}}

    # 服务端配置了 bin_id 但与设备不同 → 需要更新
    if effective_bin_id and bin_id and effective_bin_id != bin_id:
        logger.info(f"[SDK OTA] bin_id 不同, 需要更新: "
                    f"device_bin_id={bin_id}, effective_bin_id={effective_bin_id}, mac={mac}")
        return {"success": True, "data": {"latest": False, "bin_url": effective_bin_url}}

    # 服务端未配置 bin_id → 安全防护：不触发升级（避免无限循环）
    if not effective_bin_id and bin_id:
        logger.warning(f"[SDK OTA] 服务端未配置 bin_id 但设备传了 bin_id={bin_id}, mac={mac}，"
                       f"配置不完整，跳过升级避免无限循环")
        return {"success": True, "data": {"latest": True, "bin_url": ""}}

    # ── 4. 次优先级：版本号比对 ──
    if not effective_version:
        logger.info(f"[SDK OTA] 未配置目标版本号, 视为已是最新: version={version}, mac={mac}")
        return {"success": True, "data": {"latest": True, "bin_url": ""}}

    if version:
        try:
            from packaging.version import Version
            if Version(effective_version) <= Version(version):
                logger.info(f"[SDK OTA] 已是最新版本: current={version}, configured={effective_version}, mac={mac}")
                return {"success": True, "data": {"latest": True, "bin_url": ""}}
        except Exception:
            if effective_version == version:
                logger.info(f"[SDK OTA] 已是最新版本: current={version}, configured={effective_version}, mac={mac}")
                return {"success": True, "data": {"latest": True, "bin_url": ""}}

    logger.info(f"[SDK OTA] 发现新版本: current={version}, new={effective_version}, "
                f"device_bin_id={bin_id}, effective_bin_id={effective_bin_id}, mac={mac}")
    return {"success": True, "data": {"latest": False, "bin_url": effective_bin_url}}


# ═══════════════════════════════════════════════════════════════════
# 路由注册
# ═══════════════════════════════════════════════════════════════════

def register_device_routes(app):
    """注册设备管理路由"""
    app.include_router(router)
    app.include_router(sdk_router)
    from src.infrastructure.device_system_routes import router as system_router
    app.include_router(system_router)
    logger.info("[DeviceAPI] Device management routes registered")


__all__ = [
    "router",
    "sdk_router",
    "register_device_routes",
    "DeviceInfo",
    "DeviceListResponse",
    "DeviceControlResponse",
    "DeviceStats",
    "DeviceConfig",
    "MessageHistory",
    "OTARequest",
    "OTAResponse",
    "FirmwareInfo",
    "FirmwareListResponse",
]
