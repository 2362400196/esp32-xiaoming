"""设备路由

设备列表查询、设备详情、创建设备、唤醒/播放/停止控制、工具查询。

所有业务 API 统一使用 ``/api/v1/`` 前缀。
原无版本路径（``/api/devices``、``/api/wakeup`` 等）保留为 deprecated 别名，
响应中携带 ``Deprecation`` HTTP 头以提示客户端迁移。
"""
from __future__ import annotations

import asyncio
import os
import secrets
import shutil
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Body
from pydantic import BaseModel, Field

from src.infrastructure.logging import get_logger
from src.infrastructure.security_jwt import get_current_user
from src.infrastructure.db.models.user import UserModel
from src.infrastructure.db.session import get_session_ctx
from src.infrastructure.db.models.device import DeviceModel
from sqlalchemy import select, update
from datetime import datetime, timezone
from src.infrastructure.routes._deps import check_device_owner as _check_device_owner
from src.infrastructure.web import get_device_registry, get_speaker

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["devices"])

# 保持后台 Pipeline 任务引用，防止被 GC 回收
_bg_tasks: set = set()


def _remove_device_kv_dir(mac: str) -> None:
    """删除设备的插件 KV 目录 data/plugins/kv/{mac}/（解绑时清除前用户的插件数据）。

    路径规则与 sdk/storage.py 的 _get_kv_store_path 保持一致（设备级隔离目录），
    此处直接复用其路径构造辅助函数。KV 可能含前用户的 token/账号配置，必须清除。
    """
    try:
        from src.use_cases.sdk.storage import _get_project_root, _sanitize_device_id

        kv_dir = os.path.join(
            _get_project_root(), "data", "plugins", "kv", _sanitize_device_id(mac)
        )
        if os.path.isdir(kv_dir):
            shutil.rmtree(kv_dir, ignore_errors=True)
            logger.info(f"[Devices] 已删除设备 {mac} 的插件 KV 目录: {kv_dir}")
        else:
            logger.debug(f"[Devices] 设备 {mac} 无插件 KV 目录，跳过删除")
    except Exception as e:
        # 清理失败不阻塞解绑主流程，但必须留下告警便于人工排查
        logger.warning(f"[Devices] 删除设备 {mac} 插件 KV 目录失败: {e}")


class WakeupRequest(BaseModel):
    device_id: str = Field(max_length=64)


class SpeakRequest(BaseModel):
    device_id: str = Field(max_length=64)
    text: str = Field(max_length=500)


class SpeakAllRequest(BaseModel):
    text: str = Field(max_length=500)


class StopRequest(BaseModel):
    device_id: str = Field(max_length=64)


class DeviceActionRequest(BaseModel):
    """快捷指令：真实执行功能（weather/music/alarm/diary/chat），chat 时 text 为对话内容"""
    action: str = Field(max_length=32)
    text: str = Field(default="", max_length=500)


class BindRequest(BaseModel):
    device_id: str = Field(max_length=128)
    bind_code: str = Field(min_length=6, max_length=6)


class BindByCodeRequest(BaseModel):
    bind_code: str = Field(min_length=6, max_length=6)
    name: Optional[str] = Field(default=None, max_length=64)


class UnbindRequest(BaseModel):
    device_id: str = Field(max_length=128)


class CreateDeviceRequest(BaseModel):
    """创建新设备请求"""

    mac: str = Field(..., min_length=1, max_length=64, description="设备 MAC 地址（作为设备唯一 ID）")
    key: str = Field(..., min_length=1, max_length=128, description="设备连接密钥（WebSocket ?key= 参数）")
    name: str = Field(..., min_length=1, max_length=64, description="设备显示名称")

    # 可选配置（不填则继承 .env 全局默认）
    asr_provider: Optional[str] = Field(default=None, description="ASR 提供商（volcengine / tencent）")
    llm_api_key: Optional[str] = Field(default=None, description="LLM API Key")
    llm_base_url: Optional[str] = Field(default=None, description="LLM Base URL")
    llm_model: Optional[str] = Field(default=None, description="LLM 模型名")
    llm_system_prompt: Optional[str] = Field(default=None, description="LLM 系统提示词")
    tts_voice_type: Optional[str] = Field(default=None, description="TTS 音色 ID")
    rate_limit_rpm: Optional[int] = Field(default=None, ge=0, description="设备独立限流（RPM）")
    mcp_servers: Optional[dict] = Field(default=None, description="MCP 服务器配置")


def _set_deprecation_headers(response: Response, successor: str) -> None:
    """为 deprecated 路由设置废弃相关的 HTTP 头。

    - ``Deprecation``: 标记该资源已废弃（RFC 草案）
    - ``Link``: 指向替代版本路径（``rel="successor-version"``）
    """
    response.headers["Deprecation"] = "true"
    response.headers["Link"] = f'<{successor}>; rel="successor-version"'


# ============================================================
#  业务逻辑函数（供 v1 路由和 deprecated 别名共享）
# ============================================================

async def _get_devices() -> dict:
    registry = get_device_registry()
    if not registry:
        return {"code": 1, "message": "Device registry not available", "data": None}

    device_ids = registry.get_all_ids()
    devices = []
    for did in device_ids:
        d = registry.get(did)
        if d:
            session = d.get("session")
            fsm = d.get("fsm")
            channel = d.get("channel")
            mac = d.get("mac", did)
            user_config = d.get("user_config")
            devices.append({
                "device_id": mac,
                "name": getattr(user_config, "name", "") if user_config else "",
                "connected": getattr(channel, "connected", False) if channel else False,
                "state": fsm.get() if fsm and hasattr(fsm, "get") else "unknown",
                "session_id": getattr(session, "session_id", "") if session else "",
            })
    return {"code": 0, "message": "ok", "data": {"count": len(devices), "devices": devices}}


async def _create_device(body: CreateDeviceRequest) -> dict:
    """创建新设备（多用户模式）"""
    from src.infrastructure.db.repositories.device_repository import DeviceRepository

    repo = DeviceRepository()

    if await repo.find_by_mac(body.mac):
        return {"code": 1, "message": f"设备 MAC 已存在: {body.mac}", "data": None}

    if await repo.find_by_key(body.key):
        return {"code": 1, "message": f"设备密钥已存在: {body.key[:4]}***", "data": None}

    config: dict = {
        "name": body.name,
        "key": body.key,
        "mac": body.mac,
        "asr_provider": body.asr_provider or "",
        "llm_type": "openai",
        "tts_type": "volcengine",
        "rate_limit_rpm": body.rate_limit_rpm or 0,
        "disabled_tools": [],
        "disabled_mcp_servers": [],
        "disabled_mcp_tools": {},
        "disabled_skills": [],
        "skills": [],
    }

    llm: dict = {}
    if body.llm_api_key:
        llm["api_key"] = body.llm_api_key
    if body.llm_base_url:
        llm["base_url"] = body.llm_base_url
    if body.llm_model:
        llm["model"] = body.llm_model
    if body.llm_system_prompt:
        llm["system_prompt"] = body.llm_system_prompt
    if llm:
        config["llm"] = llm

    if body.tts_voice_type:
        config["tts_config"] = {"voice_type": body.tts_voice_type}

    if body.mcp_servers:
        config["mcp_servers"] = body.mcp_servers

    await repo.upsert_device(body.mac, config)

    logger.info(f"[API] 新设备已创建: MAC={body.mac}, name={body.name}")

    logger.info(f"[API] 新设备已创建: MAC={body.mac}, name={body.name}")

    try:
        from src.infrastructure.web import get_app
        _app = get_app()
        if _app:
            auth = getattr(_app.state, "auth_service", None)
            if auth and hasattr(auth, "reload_users_config"):
                auth.reload_users_config()
                logger.info("[API] auth 配置已热重载")
    except Exception as e:
        logger.warning(f"[API] 热重载 auth 配置失败（不影响已写入的数据）: {e}")

    key_masked = body.key[:4] + "***" + body.key[-4:] if len(body.key) >= 8 else "***"
    return {
        "code": 0,
        "message": "设备创建成功",
        "data": {
            "device_id": body.mac,
            "mac": body.mac,
            "key_masked": key_masked,
            "name": body.name,
        },
    }


async def _get_device(device_id: str) -> dict:
    registry = get_device_registry()
    if not registry:
        return {"code": 1, "message": "Device registry not available", "data": None}

    d = registry.resolve(device_id)
    if not d:
        return {"code": 1, "message": f"Device not found: {device_id}", "data": None}

    session = d.get("session")
    fsm = d.get("fsm")
    channel = d.get("channel")
    mac = d.get("mac", device_id)
    user_config = d.get("user_config")

    return {
        "code": 0, "message": "ok",
        "data": {
            "device_id": mac,
            "name": getattr(user_config, "name", "") if user_config else "",
            "connected": getattr(channel, "connected", False) if channel else False,
            "state": fsm.get() if fsm and hasattr(fsm, "get") else "unknown",
            "session_id": getattr(session, "session_id", "") if session else "",
            "tts_playing": getattr(session, "tts_playing", False) if session else False,
        },
    }


async def _wakeup(device_id: str) -> dict:
    logger.info(f"[API] wakeup device_id={device_id}")
    speaker = get_speaker()
    if not speaker:
        return {"code": 1, "message": "Speaker not available", "data": None}
    # 后台执行完整唤醒流程（session_start → 音频 → iat_start），
    # API 立即返回，避免 App 转圈卡住
    asyncio.create_task(speaker.wakeup(device_id))
    return {"code": 0, "message": "Wakeup command sent", "data": {"device_id": device_id}}


async def _wakeup_all() -> dict:
    speaker = get_speaker()
    if not speaker:
        return {"code": 1, "message": "Speaker not available", "data": None}
    registry = get_device_registry()
    if not registry or registry.count() == 0:
        return {"code": 0, "message": "No online devices", "data": {"count": 0, "devices": []}}
    await speaker.wakeup_all()
    device_ids = registry.get_all_ids()
    return {"code": 0, "message": f"Woken up {len(device_ids)} devices", "data": {"count": len(device_ids), "devices": device_ids}}


async def _speak(device_id: str, text: str) -> dict:
    logger.info(f"[API] speak device_id={device_id} text={text[:30]}...")
    speaker = get_speaker()
    if not speaker:
        return {"code": 1, "message": "Speaker not available", "data": None}
    success = await speaker.speak(device_id, text, need_wakeup=False)
    if not success:
        return {"code": 1, "message": "Speak failed, device not connected", "data": None}
    return {"code": 0, "message": "Play success", "data": {"device_id": device_id, "text": text[:100]}}


async def _speak_all(text: str) -> dict:
    logger.info(f"[API] speak/all text={text[:30]}...")
    speaker = get_speaker()
    if not speaker:
        return {"code": 1, "message": "Speaker not available", "data": None}
    registry = get_device_registry()
    if not registry or registry.count() == 0:
        return {"code": 0, "message": "No online devices", "data": {"count": 0, "devices": []}}
    await speaker.speak_all(text, need_wakeup=False)
    device_ids = registry.get_all_ids()
    return {"code": 0, "message": f"Played to {len(device_ids)} devices", "data": {"count": len(device_ids), "devices": device_ids, "text": text[:100]}}


async def _stop(device_id: str) -> dict:
    speaker = get_speaker()
    if not speaker:
        return {"code": 1, "message": "Speaker not available", "data": None}
    success = await speaker.stop(device_id)
    if not success:
        return {"code": 1, "message": "Stop failed, device not connected", "data": None}
    return {"code": 0, "message": "Device entered standby", "data": {"device_id": device_id}}


async def _stop_all() -> dict:
    speaker = get_speaker()
    if not speaker:
        return {"code": 1, "message": "Speaker not available", "data": None}
    registry = get_device_registry()
    if not registry or registry.count() == 0:
        return {"code": 0, "message": "No online devices", "data": {"count": 0, "devices": []}}
    await speaker.stop_all()
    device_ids = registry.get_all_ids()
    return {"code": 0, "message": f"Stopped {len(device_ids)} devices", "data": {"count": len(device_ids), "devices": device_ids}}


async def _device_action(device_id: str, action: str, text: str) -> dict:
    """执行设备快捷指令：直接调用插件工具/完整对话，真实生效（非仅播报）。"""
    logger.info(f"[ACTION] 开始: device_id={device_id}, action={action}, text={text[:30] if text else ''}")
    registry = get_device_registry()
    if not registry:
        logger.error("[ACTION] Device registry 不可用")
        return {"code": 1, "message": "Device registry not available", "data": None}
    # device_id 可能是 mac，解析为 device_key
    from src.infrastructure.device_api import resolve_device_id
    device_key = resolve_device_id(device_id) or device_id
    d = registry.resolve(device_key)
    if not d:
        logger.error(f"[ACTION] 设备不在线: device_key={device_key}")
        return {"code": 1, "message": "设备不在线，请确认设备已连接", "data": None}

    fsm = d.get("fsm")
    session = d.get("session")
    tool_mgr = d.get("tool_manager")
    channel = d.get("channel")
    speaker = get_speaker()

    fsm_state = fsm.get() if fsm else "无FSM"
    logger.info(f"[ACTION] 设备在线, fsm={fsm_state}, session={'有' if session else '无'}, channel={'有' if channel else '无'}")

    # chat 动作允许打断当前对话（TTS/播放中 → 先 interrupt 再继续）
    if action == "chat" and fsm and getattr(fsm, "get", lambda: "")() in ("TTS", "LISTENING", "ASR", "THINKING"):
        if session and hasattr(session, "interrupt"):
            logger.info(f"[API] chat 打断当前 Pipeline (fsm={fsm.get()})")
            await session.interrupt()
            await asyncio.sleep(0.3)  # 等待清理完成
    elif fsm and getattr(fsm, "get", lambda: "")() in ("TTS", "LISTENING", "ASR", "THINKING"):
        return {"code": 1, "message": "设备正在对话中，请稍后再试", "data": None}

    # 完整对话：文本注入会话 Pipeline（LLM + 工具 + TTS，真正执行）
    if action == "chat":
        if not text:
            return {"code": 1, "message": "缺少对话内容", "data": None}
        if not session or not hasattr(session, "run_pipeline"):
            logger.error(f"[ACTION] session 不可用: session={session}, has_run={hasattr(session, 'run_pipeline') if session else 'N/A'}")
            return {"code": 1, "message": "设备会话不可用", "data": None}
        mem = getattr(session, "conversation_memory", None)
        if mem:
            await mem.ensure_loaded()
        import time as _time
        pre_time = _time.time()  # 用时间戳而非消息计数（避免 max 裁剪导致计数不变）
        logger.info(f"[ACTION] chat 开始, pre_time={pre_time:.3f}, mem={'有' if mem else '无'}")

        # 非阻塞启动 Pipeline（LLM + TTS + 播放在后台运行）
        pipeline_task = asyncio.create_task(session.run_pipeline(text))
        _bg_tasks.add(pipeline_task)
        pipeline_task.add_done_callback(_bg_tasks.discard)
        logger.info("[ACTION] Pipeline 后台任务已创建")

        # 轮询等待 LLM 回复写入 memory（LLM 先于 TTS 完成，提前返回文本）
        reply_text = ""
        for _ in range(100):  # 100 × 0.3s = 30s 上限
            await asyncio.sleep(0.3)
            if mem:
                # 用时间戳检测新消息（不受 max_messages 裁剪影响）
                for m in reversed(mem.messages):
                    if m.get("role") == "assistant" and m.get("timestamp", 0) >= pre_time:
                        reply_text = m.get("content", "")
                        break
                if reply_text:
                    break
            # Pipeline 已结束（成功或失败）且无新回复
            if pipeline_task.done():
                if mem:
                    for m in reversed(mem.messages):
                        if m.get("role") == "assistant" and m.get("timestamp", 0) >= pre_time:
                            reply_text = m.get("content", "")
                            break
                break

        if reply_text:
            logger.info(f"[ACTION] chat 成功, reply={reply_text[:50]}")
            return {"code": 0, "message": reply_text, "data": {"reply": reply_text}}
        if pipeline_task.done() and pipeline_task.exception():
            logger.error(f"[ACTION] Pipeline 异常: {pipeline_task.exception()}")
            return {"code": 1, "message": f"对话执行失败: {pipeline_task.exception()}", "data": None}
        logger.info("[ACTION] 30s 超时，未检测到 LLM 回复")
        return {"code": 0, "message": "已发送", "data": {"reply": ""}}

    # 纯功能动作：调用设备会话的工具管理器（插件权限/配置自动生效）
    if action == "music":
        if not tool_mgr:
            return {"code": 1, "message": "设备会话不可用", "data": None}
        # 白名单检查：设备未启用 media_player 插件时直接返回友好错误，
        # 不再绕过设备工具白名单直调插件方法（安全修复）
        checker = getattr(tool_mgr, "_device_tool_allowed", None)
        if callable(checker) and not checker("play_music"):
            return {"code": 1, "message": "音乐插件未启用", "data": None}
        # 走正规工具调用（等价随机播放：song/artist 留空即随机推荐）；
        # play_music 成功发送音频后抛 StopPipeline 接管音频通道，视为成功；
        # 正常返回字符串说明音乐未成功发出（未配置/搜索失败/发送失败）
        from src.use_cases.tools_system import StopPipeline
        try:
            result = await tool_mgr.call_tool("play_music", {"song": "", "artist": ""})
            if isinstance(result, str) and result:
                logger.warning(f"[ACTION] music 未成功播放: {result}")
                return {"code": 1, "message": "音乐服务不可用", "data": None}
            return {"code": 0, "message": "正在播放随机音乐", "data": None}
        except StopPipeline:
            return {"code": 0, "message": "正在播放随机音乐", "data": None}
        except Exception as e:
            logger.error(f"[ACTION] music 调用失败: {e}")
            return {"code": 1, "message": "音乐服务不可用", "data": None}

    action_args = {
        "weather": ("get_weather", {}),
        "alarm": ("set_alarm", {"time": "07:00"}),
        "diary": ("read_diary", {"days": 1}),
    }
    if action not in action_args:
        return {"code": 1, "message": f"未知动作: {action}", "data": None}
    tool_name, args = action_args[action]
    if not tool_mgr:
        return {"code": 1, "message": "设备会话不可用", "data": None}
    result = await tool_mgr.call_tool(tool_name, args)
    # 播报工具执行结果
    if speaker and result:
        await speaker.speak(device_id, str(result), need_wakeup=False)
    return {"code": 0, "message": "执行完成", "data": None}


# ============================================================
#  设备列表 / 绑定 / 创建 / 详情
# ============================================================


@router.get("/devices")
async def api_get_devices(user: UserModel = Depends(get_current_user)):
    """获取当前用户绑定的所有设备"""
    async with get_session_ctx() as session:
        result = await session.execute(
            select(DeviceModel).where(DeviceModel.user_id == user.id)
        )
        devices = result.scalars().all()
    registry = get_device_registry()
    device_list = []
    for d in devices:
        online = False
        state = "idle"
        if registry:
            # 依次尝试 device_id / mac_address / device_key 查找在线状态
            info = registry.resolve(d.device_id)
            if not info and d.mac_address:
                info = registry.get_by_mac(d.mac_address)
            if not info and d.device_key:
                info = registry.resolve(d.device_key)
            if info:
                channel = info.get("channel")
                online = getattr(channel, "connected", False) if channel else False
                fsm = info.get("fsm")
                if fsm and hasattr(fsm, "get"):
                    state = fsm.get().value
        device_list.append({
            "device_id": d.device_id,
            "name": d.name,
            "mac": d.mac_address,
            "device_key": d.device_key,
            "online": online,
            "state": state,
            "bound_at": d.bound_at,
        })
    return {"code": 0, "message": "ok", "data": {"devices": device_list}}


@router.post("/devices")
async def api_create_device(body: CreateDeviceRequest, user: UserModel = Depends(get_current_user)):
    """创建新设备（自动绑定到当前用户）"""
    result = await _create_device(body)
    if result.get("code") == 0:
        device_id = body.mac
        async with get_session_ctx() as session:
            dev = await session.execute(
                select(DeviceModel).where(DeviceModel.device_id == device_id)
            )
            device = dev.scalar_one_or_none()
            if device:
                device.user_id = user.id
                device.bound_at = datetime.now(timezone.utc).timestamp()
                session.add(device)
    return result


@router.post("/devices/{device_id}/bind")
async def api_bind_device(device_id: str, body: BindRequest, user: UserModel = Depends(get_current_user)):
    """绑定设备到当前用户"""
    async with get_session_ctx() as session:
        result = await session.execute(
            select(DeviceModel).where(DeviceModel.device_id == body.device_id)
        )
        device = result.scalar_one_or_none()
        if not device:
            raise HTTPException(404, "Device not found")
        if device.user_id is not None:
            raise HTTPException(400, "Device already bound to another user")
        if device.bind_code != body.bind_code:
            raise HTTPException(400, "Invalid bind code")
        if device.bind_code_expires is None or datetime.now(timezone.utc).timestamp() > device.bind_code_expires:
            raise HTTPException(400, "Bind code expired")

        # 检查用户设备数上限
        count_result = await session.execute(
            select(DeviceModel).where(DeviceModel.user_id == user.id)
        )
        device_count = len(count_result.scalars().all())
        if device_count >= user.max_devices:
            raise HTTPException(400, f"Device limit reached ({user.max_devices})")

        # 原子占用设备：仅当 user_id 仍为空时更新，防止并发绑定的 TOCTOU 竞态双绑
        result = await session.execute(
            update(DeviceModel)
            .where(
                DeviceModel.device_id == body.device_id,
                DeviceModel.user_id.is_(None),
            )
            .values(
                user_id=user.id,
                bound_at=datetime.now(timezone.utc).timestamp(),
                bind_code=None,
                bind_code_expires=None,
            )
        )
        if result.rowcount != 1:
            raise HTTPException(400, "Device already bound to another user")

    return {"code": 0, "message": "Device bound successfully"}


@router.post("/bind")
async def api_bind_by_code(body: BindByCodeRequest, user: UserModel = Depends(get_current_user)):
    """通过绑定码绑定设备（无需知道 device_id）"""
    async with get_session_ctx() as session:
        result = await session.execute(
            select(DeviceModel).where(DeviceModel.bind_code == body.bind_code)
        )
        device = result.scalar_one_or_none()
        if not device:
            raise HTTPException(404, "Device not found or bind code invalid")
        if device.user_id is not None:
            raise HTTPException(400, "Device already bound to another user")
        if device.bind_code_expires is None or datetime.now(timezone.utc).timestamp() > device.bind_code_expires:
            raise HTTPException(400, "Bind code expired")

        count_result = await session.execute(
            select(DeviceModel).where(DeviceModel.user_id == user.id)
        )
        device_count = len(count_result.scalars().all())
        if device_count >= user.max_devices:
            raise HTTPException(400, f"Device limit reached ({user.max_devices})")

        # 原子占用设备：仅当 user_id 仍为空时更新，防止并发绑定的 TOCTOU 竞态双绑。
        # 绑定成功即清空 bind_code（一次性使用），避免残留被复用
        bind_values = {
            "user_id": user.id,
            "bind_code": None,
            "bind_code_expires": None,
            "device_key": "bound_" + secrets.token_hex(8),
        }
        # 绑定时可指定设备名称
        if body.name:
            bind_values["name"] = body.name
        result = await session.execute(
            update(DeviceModel)
            .where(
                DeviceModel.device_id == device.device_id,
                DeviceModel.user_id.is_(None),
            )
            .values(**bind_values)
        )
        if result.rowcount != 1:
            raise HTTPException(400, "Device already bound to another user")

    return {"code": 0, "message": "Device bound successfully", "device_id": device.device_id}


@router.post("/devices/{device_id}/unbind")
async def api_unbind_device(device_id: str, user: UserModel = Depends(get_current_user)):
    """解绑设备"""
    async with get_session_ctx() as session:
        result = await session.execute(
            select(DeviceModel).where(
                DeviceModel.device_id == device_id,
                DeviceModel.user_id == user.id,
            )
        )
        device = result.scalar_one_or_none()
        if not device:
            raise HTTPException(404, "Device not found or not yours")
        device.user_id = None
        device.bound_at = None
        # 解绑同时清空绑定码，避免残留的绑定码/哨兵被复用
        device.bind_code = None
        device.bind_code_expires = None
        # 解绑即轮换 device_key：旧 key 立即失效，防止解绑后用旧 key 连接继承前用户的对话上下文
        # （设备重新连接会走配网绑定流程，这是预期行为）
        device.device_key = "orphan_" + secrets.token_hex(16)

        # 清理该设备的插件 KV 目录：KV 可能含前用户的 token/账号配置，必须清除
        mac = device.mac_address or ""
        if mac:
            _remove_device_kv_dir(mac)

        session.add(device)
    return {"code": 0, "message": "Device unbound"}


@router.get("/devices/{device_id}")
async def api_get_device(device_id: str, user: UserModel = Depends(get_current_user)):
    """获取设备详情（需校验归属）"""
    if not await _check_device_owner(device_id, user):
        raise HTTPException(403, "Device not bound to you")
    return await _get_device(device_id)


# ============================================================
#  唤醒 / 播放 / 停止 控制 API（需校验设备归属）
# ============================================================

@router.post("/wakeup")
async def api_wakeup(body: WakeupRequest, user: UserModel = Depends(get_current_user)):
    if not await _check_device_owner(body.device_id, user):
        raise HTTPException(403, "Device not bound to you")
    return await _wakeup(body.device_id)


@router.post("/devices/{device_id}/wakeup")
async def api_device_wakeup(device_id: str, user: UserModel = Depends(get_current_user)):
    """兼容路由：/api/v1/devices/{mac}/wakeup"""
    if not await _check_device_owner(device_id, user):
        raise HTTPException(403, "Device not bound to you")
    return await _wakeup(device_id)


@router.post("/speak")
async def api_speak(body: SpeakRequest, user: UserModel = Depends(get_current_user)):
    if not await _check_device_owner(body.device_id, user):
        raise HTTPException(403, "Device not bound to you")
    return await _speak(body.device_id, body.text)


@router.post("/devices/{device_id}/speak")
async def api_device_speak(device_id: str, body: dict = Body(...), user: UserModel = Depends(get_current_user)):
    """兼容路由：/api/v1/devices/{mac}/speak"""
    if not await _check_device_owner(device_id, user):
        raise HTTPException(403, "Device not bound to you")
    text = body.get("text", "") if body else ""
    if not text:
        raise HTTPException(422, "text is required")
    return await _speak(device_id, text)


@router.post("/devices/{device_id}/action")
async def api_device_action(device_id: str, body: DeviceActionRequest, user: UserModel = Depends(get_current_user)):
    """执行设备快捷指令（真实功能：天气/音乐/闹钟/日记/自由对话）"""
    if not await _check_device_owner(device_id, user):
        raise HTTPException(403, "Device not bound to you")
    return await _device_action(device_id, body.action, body.text)


@router.post("/stop")
async def api_stop(body: StopRequest, user: UserModel = Depends(get_current_user)):
    if not await _check_device_owner(body.device_id, user):
        raise HTTPException(403, "Device not bound to you")
    return await _stop(body.device_id)


# ============================================================
#  设备配置 API（机器人模式等）
# ============================================================
@router.post("/devices/{mac}/robot_mode")
async def api_set_robot_mode(mac: str, body: dict = Body(...), user: UserModel = Depends(get_current_user)):
    """设置设备机器人模式（只显示表情，隐藏所有文字/图标/横条）"""
    if not await _check_device_owner(mac, user):
        raise HTTPException(403, "Device not bound to you")

    enabled = bool(body.get("enabled", False))
    from src.infrastructure.db.repositories.device_repository import DeviceRepository
    repo = DeviceRepository()
    result = await repo.update_device_partial(mac, {"robot_mode": "true" if enabled else "false"})
    if result is None:
        logger.warning(f"[API] robot_mode 设置失败，设备 {mac} 未找到")
        return {"code": 1, "message": "Device not found", "data": None}

    # 通过 WebSocket 下发 update_config 指令，设备立即生效
    try:
        registry = get_device_registry()
        if registry:
            d = registry.resolve(mac)
            if not d:
                d = registry.get_by_mac(mac)
            if d:
                tool_mgr = d.get("tool_manager")
                if tool_mgr:
                    from src.use_cases._plugin_helpers import send_device_command
                    await send_device_command(tool_mgr, "update_config", {"robot_mode": "true" if enabled else "false"})
    except Exception as e:
        logger.warning(f"[API] 下发 robot_mode 指令失败: {e}")

    return {"code": 0, "message": "ok", "data": {"robot_mode": enabled}}


# ============================================================
#  设备显示配置 API（机器人模式 + 屏保）
# ============================================================
@router.post("/devices/{mac}/display_config")
async def api_set_display_config(mac: str, body: dict = Body(...), user: UserModel = Depends(get_current_user)):
    """设置设备显示配置（机器人模式、屏保开关、屏保超时）"""
    if not await _check_device_owner(mac, user):
        raise HTTPException(403, "Device not bound to you")

    from src.infrastructure.db.repositories.device_repository import DeviceRepository
    repo = DeviceRepository()

    # 构建要更新的字段
    updates = {}
    commands = {}

    if "robot_mode" in body:
        val = "true" if body["robot_mode"] else "false"
        updates["robot_mode"] = val
        commands["robot_mode"] = val

    if "screensaver_enabled" in body:
        val = "true" if body["screensaver_enabled"] else "false"
        updates["screensaver_enabled"] = val
        commands["screensaver_enabled"] = val

    if "screensaver_timeout" in body:
        timeout = int(body["screensaver_timeout"])
        if timeout < 5:
            timeout = 5
        elif timeout > 600:
            timeout = 600
        updates["screensaver_timeout"] = str(timeout)
        commands["screensaver_timeout"] = str(timeout)

    if not updates:
        return {"code": 1, "message": "No config to update", "data": None}

    result = await repo.update_device_partial(mac, updates)
    if result is None:
        logger.warning(f"[API] display_config 更新失败，设备 {mac} 未找到")
        return {"code": 1, "message": "Device not found", "data": None}

    # 通过 WebSocket 下发 update_config 指令，设备立即生效
    if commands:
        try:
            registry = get_device_registry()
            if registry:
                d = registry.resolve(mac)
                if not d:
                    d = registry.get_by_mac(mac)
                if d:
                    tool_mgr = d.get("tool_manager")
                    if tool_mgr:
                        from src.use_cases._plugin_helpers import send_device_command
                        await send_device_command(tool_mgr, "update_config", commands)
        except Exception as e:
            logger.warning(f"[API] 下发 display_config 指令失败: {e}")

    return {"code": 0, "message": "ok", "data": updates}


# ============================================================
#  工具查询 API
# ============================================================
@router.get("/tools")
async def list_tools(request: Request, user: UserModel = Depends(get_current_user)):
    """列出所有可用工具的名称和描述（含 MCP）"""
    from src.use_cases.tools_system import get_openai_tools_schema
    all_tools = list(get_openai_tools_schema())
    seen = set()
    result = []

    # 全局内置工具
    for t in all_tools:
        fn = t.get("function", {})
        name = fn.get("name", "")
        if name and name not in seen:
            seen.add(name)
            result.append({"type": "global", "name": name, "description": fn.get("description", ""), "parameters": fn.get("parameters", {})})

    # MCP 工具：从 app.state 获取
    for _attempt in range(2):
        tm = getattr(request.app.state, 'tool_manager', None)
        if (_attempt == 1 or not tm):
            from src.infrastructure.web import get_app as _gapp
            _a = _gapp()
            if _a:
                tm = getattr(_a.state, 'tool_manager', None)
        if tm:
            try:
                mcp_schemas = getattr(tm, '_mcp_tool_schemas', {})
                for schema_list in mcp_schemas.values():
                    for t in schema_list:
                        name = t.get("function", {}).get("name", "")
                        if name and name not in seen:
                            seen.add(name)
                            result.append({"type": "mcp", "name": name, "description": t.get("function", {}).get("description", ""), "parameters": t.get("function", {}).get("parameters", {})})
            except Exception as e:
                logger.debug(f"[Tools] 收集 MCP 工具列表异常: {e}")
        break

    return {"code": 0, "message": "ok", "data": result}