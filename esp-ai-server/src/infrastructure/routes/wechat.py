"""
WeChat Routes — 微信集成 API 路由

提供微信扫码登录、设备绑定、状态查询等 API。
"""

from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi import Depends
from src.infrastructure.security_jwt import get_current_user
from pydantic import BaseModel

from src.infrastructure.config import get_settings
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)

# 最近活跃的群聊列表（用于 App 端展示可选群聊）
_recent_groups: list[dict] = []
MAX_RECENT_GROUPS = 20


def add_recent_group(group_id: str, msg: dict) -> None:
    """记录最近活跃的群聊"""
    import time
    # 去重更新
    for g in _recent_groups:
        if g["group_id"] == group_id:
            g["last_active"] = time.time()
            g["name"] = msg.get("chatroom_name", msg.get("group_name", group_id)) or group_id
            return
    _recent_groups.append({
        "group_id": group_id,
        "name": msg.get("chatroom_name", msg.get("group_name", group_id)) or group_id,
        "last_active": time.time(),
    })
    if len(_recent_groups) > MAX_RECENT_GROUPS:
        _recent_groups[:] = sorted(_recent_groups, key=lambda x: x["last_active"], reverse=True)[:MAX_RECENT_GROUPS]

router = APIRouter(prefix="/api/v1/wechat", tags=["wechat"])


# ── 请求/响应模型 ──────────────────────────

class QRStartResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: dict | None = None


class QRStatusResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: dict | None = None


class BindRequest(BaseModel):
    wechat_chat_id: str
    wechat_user_id: str
    device_key: str
    device_mac: str = ""
    wechat_group_id: str = ""
    alias: str = ""


class BindResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: dict | None = None


class UnbindRequest(BaseModel):
    device_key: str


class UnbindResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: dict | None = None


class BindingsResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: list | None = None


# ── 依赖注入辅助 ──────────────────────────

def _ensure_bot(request: Request):
    """确保 app.state 中有 WeChatBot 实例（懒创建）并注册消息回调"""
    # 懒创建 Bot
    bot = getattr(request.app.state, 'wechat_bot', None)
    if bot is None:
        from src.use_cases.wechat_bot import WeChatBot, WeChatClientConfig
        settings = get_settings()
        cfg = settings.wechat_bot
        bot_config = WeChatClientConfig(
            token=cfg.token,
            base_url=cfg.base_url,
            cdn_base_url=cfg.cdn_base_url,
            account_id=cfg.account_id,
            app_id=cfg.app_id,
            client_version=cfg.client_version,
        )
        bot = WeChatBot(bot_config)
        request.app.state.wechat_bot = bot

    # 确保消息回调已注册（每次调用都重新设置，避免生命周期问题）
    # 注意：只在不覆盖已有回调的情况下注册，web.py lifespan 中的回调包含 LLM 处理逻辑
    if bot.on_message is None:
        from src.use_cases.wechat_binding import get_wechat_binding_manager
        bind_mgr = get_wechat_binding_manager()
        request.app.state.wechat_binding_manager = bind_mgr

        async def _on_wechat_message(bot_, chat_id, sender_id, message_id, text, context_token):
            binding = bind_mgr.get_by_wechat(chat_id)
            if not binding:
                # 自动绑定到第一个可用的设备
                from src.infrastructure.web import get_device_registry
                registry = get_device_registry()
                if registry:
                    device_ids = registry.get_all_ids()
                    if device_ids:
                        first_id = device_ids[0]
                        entry = registry.resolve(first_id)
                        if entry:
                            mac = entry.get("mac", "") or entry.get("device_id", "") or first_id
                            device_key = first_id
                            bind_mgr.bind(chat_id, sender_id, device_key, device_mac=mac)
                            binding = bind_mgr.get_by_wechat(chat_id)
                            try:
                                await bot_.send_text(chat_id, "已自动绑定设备，现在可以开始对话了")
                            except Exception:
                                pass
                            logger.info(f"[WeChat] 自动绑定: wechat={chat_id[:16]} → device={device_key[:16]}")
                if not binding:
                    logger.info(f"[WeChat] 未绑定的微信消息: {chat_id[:16]}, 无在线设备可绑定")
                    return
            await bind_mgr.send_wechat_message_to_device(
                binding.device_key, chat_id, sender_id, text
            )
            logger.info(f"[WeChat] 微信消息已转发给设备 {binding.device_key[:16]}: {text[:60]}")

        bot.on_message = _on_wechat_message

    # 如果从文件恢复了 token，自动启动轮询
    if bot.state.configured and not bot.state.poll_task:
        import asyncio
        asyncio.create_task(bot.start())
        # logger.info("[WeChat] 从文件恢复 token，自动启动轮询")

    return bot


def _get_binding_mgr(request: Request):
    """从 app state 获取 WeChatBindingManager 实例"""
    mgr = getattr(request.app.state, 'wechat_binding_manager', None)
    if not mgr:
        from src.use_cases.wechat_binding import get_wechat_binding_manager
        mgr = get_wechat_binding_manager()
        request.app.state.wechat_binding_manager = mgr
    return mgr


# ── 二维码登录 ────────────────────────────

@router.post("/qr-start", response_model=QRStartResponse)
async def qr_login_start(request: Request, user=Depends(get_current_user)):
    """启动微信扫码登录"""
    bot = _ensure_bot(request)
    try:
        state = await bot.qr_login_start()
        # 记录原始 API 返回，方便调试
        logger.info(f"[WeChat] QR API raw: qrcode={state.qrcode[:40] if state.qrcode else 'N/A'}..., "
                     f"qr_data_url_len={len(state.qr_data_url)}, "
                     f"qr_data_url_preview={state.qr_data_url[:80] if state.qr_data_url else 'N/A'}")

        qr_image = ""
        if state.qr_data_url:
            if state.qr_data_url.startswith("data:image/"):
                # 已经是图片数据 URL，直接使用
                qr_image = state.qr_data_url
            else:
                # 是二维码内容（URL或文本），服务端生成二维码图片
                try:
                    import qrcode
                    from io import BytesIO
                    import base64
                    img = qrcode.make(state.qr_data_url)
                    buf = BytesIO()
                    img.save(buf, format="PNG")
                    qr_image = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
                    logger.info(f"[WeChat] 已从内容生成二维码图片 ({len(qr_image)} bytes)")
                except Exception as e:
                    logger.warning(f"[WeChat] 生成二维码失败，返回原文: {e}")
                    qr_image = state.qr_data_url
        elif state.qrcode:
            # 只有 qrcode ID，从 ID 生成二维码
            try:
                import qrcode
                from io import BytesIO
                import base64
                img = qrcode.make(state.qrcode)
                buf = BytesIO()
                img.save(buf, format="PNG")
                qr_image = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
            except Exception as e:
                logger.warning(f"[WeChat] 从 qrcode ID 生成二维码失败: {e}")

        return QRStartResponse(data={
            "status": state.status,
            "message": state.message,
            "qr_data_url": qr_image,
            "session_key": state.session_key,
        })
    except Exception as e:
        logger.error(f"[WeChat] 二维码启动失败: {e}", exc_info=True)
        return QRStartResponse(code=-1, message=f"启动失败: {e}")


@router.get("/qr-status", response_model=QRStatusResponse)
async def qr_login_status(request: Request, user=Depends(get_current_user)):
    """查询二维码登录状态"""
    bot = _ensure_bot(request)
    state = await bot.qr_login_get_status()
    return QRStatusResponse(data={
        "active": state.active,
        "completed": state.completed,
        "status": state.status,
        "message": state.message,
        "bot_token": state.bot_token if state.completed else "",
        "ilink_bot_id": state.ilink_bot_id if state.completed else "",
        "ilink_user_id": state.ilink_user_id if state.completed else "",
        "base_url": state.base_url if state.completed else "",
        "configured": bot.state.configured,
        "token_invalid": bot.state.token_invalid,
    })


@router.post("/apply-token")
async def apply_token_and_start(request: Request, user=Depends(get_current_user)):
    """应用 QR 登录获取的 token 并启动消息轮询"""
    bot = _ensure_bot(request)
    ok = await bot.apply_qr_token_and_start()
    if ok:
        return {"code": 0, "message": "token 已应用，轮询已启动"}
    return {"code": -1, "message": "无可用 token，请先完成扫码登录"}


@router.post("/qr-cancel", response_model=QRStartResponse)
async def qr_login_cancel(request: Request, user=Depends(get_current_user)):
    """取消二维码登录"""
    bot = _ensure_bot(request)
    await bot.qr_login_cancel()
    return QRStartResponse(message="已取消")


# ── 绑定管理 ──────────────────────────────

@router.post("/bind", response_model=BindResponse)
async def bind_device(request: Request, body: BindRequest, user=Depends(get_current_user)):
    """绑定微信用户到设备"""
    mgr = _get_binding_mgr(request)
    try:
        binding = mgr.bind(
            wechat_chat_id=body.wechat_chat_id,
            wechat_user_id=body.wechat_user_id,
            device_key=body.device_key,
            device_mac=body.device_mac,
            wechat_group_id=body.wechat_group_id,
            alias=body.alias,
        )
        return BindResponse(data=vars(binding))
    except Exception as e:
        return BindResponse(code=-1, message=f"绑定失败: {e}")


@router.post("/unbind", response_model=UnbindResponse)
async def unbind_device(request: Request, body: UnbindRequest, user=Depends(get_current_user)):
    """解绑设备"""
    mgr = _get_binding_mgr(request)
    ok = mgr.unbind(body.device_key)
    if ok:
        return UnbindResponse(message="解绑成功")
    return UnbindResponse(code=-1, message="设备未绑定")


@router.get("/bindings", response_model=BindingsResponse)
async def list_bindings(request: Request, user=Depends(get_current_user)):
    """获取所有绑定关系"""
    mgr = _get_binding_mgr(request)
    bindings = mgr.get_all_bindings()
    return BindingsResponse(data=[vars(b) for b in bindings])


@router.post("/send-to-device")
async def send_to_device(request: Request, body: dict, user=Depends(get_current_user)):
    """通过微信向设备发送指令（仅限自己绑定的设备，防串台）"""
    mgr = _get_binding_mgr(request)
    device_key = body.get("device_key", "")
    command_id = body.get("command_id", "")
    data = body.get("data", "")
    if not device_key or not command_id:
        return {"code": -1, "message": "缺少 device_key 或 command_id"}
    # 归属校验：只能向属于自己的设备发送指令（查 DB 设备 owner，防串台）
    from src.infrastructure.db.repositories.device_repository import DeviceRepository
    from src.infrastructure.db.session import get_session_ctx
    from src.infrastructure.db.models.device import DeviceModel
    from sqlalchemy import select
    found = await DeviceRepository().find_by_key(device_key)
    if found is None:
        return {"code": -1, "message": "设备不存在"}
    _device_id, _ = found
    async with get_session_ctx() as session:
        result = await session.execute(
            select(DeviceModel.user_id).where(DeviceModel.device_id == _device_id)
        )
        owner = result.scalar_one_or_none()
    if owner != getattr(user, "id", None):
        return {"code": -1, "message": "无权操作该设备"}
    ok = await mgr.send_instruct_to_device(device_key, command_id, data)
    return {"code": 0 if ok else -1, "message": "ok" if ok else "设备不在线"}


@router.get("/recent-groups")
async def recent_groups(user=Depends(get_current_user)):
    """获取最近活跃的群聊列表（群聊绑定用）"""
    return {"code": 0, "data": _recent_groups}
