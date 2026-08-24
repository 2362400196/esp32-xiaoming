"""闹钟插件路由 - 为前端提供闹钟/提醒/睡眠定时器数据 API"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query
from sqlalchemy import select, or_

from src.infrastructure.logging import get_logger
from src.infrastructure.db.models.device import DeviceModel
from src.infrastructure.db.compat.sync_session import get_sync_session
from src.use_cases.alarm_manager import get_alarm_manager

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/alarm", tags=["alarm"])

TYPE_MAP = {"alarm": "闹钟", "reminder": "提醒", "sleep_timer": "睡眠定时器"}
REPEAT_MAP = {"once": "单次", "daily": "每天", "weekly": "每周", "monthly": "每月"}


def _resolve_device_key(device_id: str) -> str:
    """将 device_id（MAC/device_key）解析为统一的 device_key"""
    try:
        with get_sync_session() as session:
            result = session.execute(
                select(DeviceModel).where(
                    or_(
                        DeviceModel.device_id == device_id,
                        DeviceModel.device_key == device_id,
                        DeviceModel.mac_address == device_id,
                    )
                )
            )
            model = result.scalars().first()
            if model is not None and model.device_key:
                return model.device_key
    except Exception as e:
        logger.error(f"[Alarm] DB 解析 device_key 失败: {e}")
    return ""


@router.get("/list")
async def get_alarm_list(device_id: str = Query(..., description="设备MAC地址或device_key")):
    """获取设备的闹钟、提醒和睡眠定时器列表"""
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
async def cancel_alarm(alarm_id: str = Query(...)):
    """取消闹钟/提醒"""
    ok = get_alarm_manager().remove_alarm(alarm_id)
    return {"code": 0 if ok else 1, "message": "已取消" if ok else "未找到"}