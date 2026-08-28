"""闹钟插件路由 - 为前端提供闹钟/提醒/睡眠定时器数据 API"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from src.infrastructure.logging import get_logger
from src.infrastructure.security_jwt import get_current_user
from src.infrastructure.db.models.user import UserModel
from src.infrastructure.routes._deps import check_device_owner as _check_device_access
from src.infrastructure.routes._deps import resolve_device_key as _resolve_device_key
from src.use_cases.alarm_manager import get_alarm_manager

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/alarm", tags=["alarm"])

TYPE_MAP = {"alarm": "闹钟", "reminder": "提醒", "sleep_timer": "睡眠定时器"}
REPEAT_MAP = {"once": "单次", "daily": "每天", "weekly": "每周", "monthly": "每月"}


@router.get("/list")
async def get_alarm_list(
    device_id: str = Query(..., description="设备MAC地址或device_key"),
    user: UserModel = Depends(get_current_user),
):
    """获取设备的闹钟、提醒和睡眠定时器列表（JWT 认证 + 设备归属校验）"""
    if not await _check_device_access(device_id, user):
        raise HTTPException(403, "Device not bound to you")
    device_key = _resolve_device_key(device_id)
    if not device_key:
        return {"code": 1, "message": "设备未找到", "data": []}

    alarms = get_alarm_manager().list_alarms(device_key)
    now = datetime.now()

    items = []
    for a in alarms:
        trigger_at = a["trigger_at"]
        try:
            dt = datetime.fromisoformat(trigger_at)
        except Exception:
            dt = None

        remaining = ""
        if dt and dt > now:
            delta = dt - now
            days = delta.days
            seconds = delta.seconds
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            if days > 0:
                remaining = f"{days}天{hours}小时"
            elif hours > 0:
                remaining = f"{hours}小时{minutes}分"
            else:
                remaining = f"{minutes}分"
        elif dt and dt <= now:
            remaining = "已过期"

        song_text = a.get("text", "")
        if a["type"] == "alarm":
            detail = f"铃声: {song_text}" if song_text else "铃声: 随机"
        elif a["type"] == "reminder":
            detail = song_text
        else:
            detail = "睡眠定时器"

        items.append({
            "id": a["id"],
            "type": a["type"],
            "type_label": TYPE_MAP.get(a["type"], a["type"]),
            "trigger_at": trigger_at,
            "trigger_time": dt.strftime("%m-%d %H:%M") if dt else trigger_at,
            "remaining": remaining,
            "detail": detail,
            "repeat": REPEAT_MAP.get(a["repeat"], a["repeat"]),
            "repeat_key": a["repeat"],
        })

    return {"code": 0, "message": "ok", "data": items}


@router.post("/cancel")
async def cancel_alarm(alarm_id: str = Query(...), user: UserModel = Depends(get_current_user)):
    """取消闹钟/提醒（JWT 认证 + 设备归属校验）"""
    # 先通过 alarm_id 找到所属设备的 device_key，再校验归属
    alarm_item = get_alarm_manager()._alarms.get(alarm_id)
    if alarm_item is None:
        return {"code": 1, "message": "未找到"}
    if not await _check_device_access(alarm_item.device_key, user):
        raise HTTPException(403, "Device not bound to you")
    ok = get_alarm_manager().remove_alarm(alarm_id)
    return {"code": 0 if ok else 1, "message": "已取消" if ok else "未找到"}