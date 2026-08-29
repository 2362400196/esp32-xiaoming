"""WeChat 微信集成路由 - 设备绑定配对码管理

安全绑定流程：用户先在 Web 控制台（JWT 认证 + 设备归属校验）为设备生成
一次性配对码，然后在微信中发送「绑定 <配对码>」完成绑定（配对码为随机生成的 6 位数字），替代旧的
「未绑定自动绑到第一台设备」的不安全行为。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.infrastructure.logging import get_logger
from src.infrastructure.security_jwt import get_current_user
from src.infrastructure.db.models.user import UserModel
from src.infrastructure.routes._deps import check_device_owner, resolve_device_key
from src.use_cases.wechat_binding import create_pairing_code

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/wechat", tags=["wechat"])

PAIRING_CODE_TTL_SECONDS = 600  # 配对码有效期（秒）


class PairingCodeRequest(BaseModel):
    """生成配对码请求体"""
    device_id: str  # 设备 MAC / device_id / device_key 任一标识


@router.post("/pairing-code")
async def create_wechat_pairing_code(
    body: PairingCodeRequest,
    user: UserModel = Depends(get_current_user),
):
    """为指定设备生成微信绑定配对码（JWT 认证 + 设备归属校验）"""
    if not body.device_id:
        raise HTTPException(400, "device_id is required")
    if not await check_device_owner(body.device_id, user):
        raise HTTPException(403, "Device not bound to you")
    device_key = resolve_device_key(body.device_id) or body.device_id
    code = create_pairing_code(device_key, ttl_seconds=PAIRING_CODE_TTL_SECONDS)
    logger.info(f"[WeChat] 配对码已生成: device={device_key[:16]}, user={getattr(user, 'id', '')}")
    return {
        "code": 0,
        "message": "ok",
        "data": {"code": code, "expires_in": PAIRING_CODE_TTL_SECONDS},
    }
