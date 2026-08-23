"""AI 成长系统路由

设备日记、用户画像、情绪历史等成长系统路由。

设备配置数据源为 DB（DeviceRepository）。
认证方式：JWT 用户认证 + 设备归属校验。
"""
from __future__ import annotations

import os

from fastapi import Depends, APIRouter
from sqlalchemy import select, or_

from src.infrastructure.logging import get_logger
from src.infrastructure.security_jwt import get_current_user
from src.infrastructure.db.models.user import UserModel
from src.infrastructure.db.models.device import DeviceModel
from src.infrastructure.db.session import get_session_ctx

logger = get_logger(__name__)

router = APIRouter(tags=["growth"])


def _get_data_dir() -> str:
    """获取 data 目录路径（src/data）"""
    return os.path.join(os.path.dirname(__file__), "..", "..", "data")


def _resolve_device_key(device_id: str) -> str:
    """根据 device_id（MAC 或 key）从 DB 解析出 device_key。

    通过同步会话查询 DeviceModel，返回 device_key。
    DB 查询失败时记录错误日志并返回空字符串。
    """
    try:
        from src.infrastructure.db.compat.sync_session import get_sync_session

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
        logger.error(f"[Growth] DB 解析 device_key 失败: {e}")

    return ""


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


# ============================================================
#  AI成长系统 - 日记 API（JWT 用户认证 + 设备归属校验）
# ============================================================

@router.get("/api/v1/growth/diary/{device_id}")
async def get_device_diary(device_id: str, date: str = "", limit: int = 30, user: UserModel = Depends(get_current_user)):
    """获取设备的日记列表或指定日期的日记

    Args:
        device_id: 设备ID（MAC地址或key）
        date: 指定日期（格式：2026-05-29），不填则返回所有日记列表
        limit: 返回日记数量限制，默认30
    """
    if not await _check_device_owner(device_id, user):
        from fastapi import HTTPException
        raise HTTPException(403, "Device not bound to you")
    try:
        from src.use_cases.growth import DiaryService

        data_dir = _get_data_dir()
        diary_service = DiaryService(data_dir)

        device_key = _resolve_device_key(device_id)

        # 获取指定日期的日记
        if date:
            content = await diary_service.get_diary_content(device_key, date)
            if content:
                return {"code": 0, "message": "ok", "data": {"date": date, "content": content}}
            else:
                return {"code": 0, "message": "ok", "data": {"date": date, "content": None, "message": "该日期无日记"}}

        # 获取所有日记列表
        entries = await diary_service.get_all_entries(device_key)
        diary_list = []
        for entry in entries[:limit]:
            # 提取日记摘要（前200字）
            summary = entry.content[:200] + "..." if len(entry.content) > 200 else entry.content
            diary_list.append({
                "date": entry.date,
                "summary": summary,
                "created_at": entry.created_at,
            })

        return {
            "code": 0,
            "message": "ok",
            "data": {
                "device_id": device_id,
                "device_key": device_key,
                "count": len(diary_list),
                "diaries": diary_list,
            },
        }
    except Exception as e:
        logger.error(f"获取日记失败: {e}")
        return {"code": 1, "message": f"获取日记失败: {e}", "data": None}


@router.get("/api/v1/growth/diary/{device_id}/{date}")
async def get_device_diary_by_date(device_id: str, date: str, user: UserModel = Depends(get_current_user)):
    """获取设备指定日期的日记（快捷方式）"""
    return await get_device_diary(device_id, date=date, limit=30, user=user)


@router.get("/api/v1/growth/profile/{device_id}")
async def get_device_growth_profile(device_id: str, user: UserModel = Depends(get_current_user)):
    """获取设备的用户画像和成长信息"""
    if not await _check_device_owner(device_id, user):
        from fastapi import HTTPException
        raise HTTPException(403, "Device not bound to you")
    try:
        data_dir = _get_data_dir()
        device_key = _resolve_device_key(device_id)

        # 获取用户画像
        from src.use_cases.growth.user_profile import UserProfileService
        profile_service = UserProfileService(data_dir)
        profile = await profile_service.get_profile(device_key)

        # 获取情绪摘要
        from src.use_cases.growth.emotion_analyzer import EmotionAnalyzer
        emotion_service = EmotionAnalyzer(data_dir)
        emotion_summary = await emotion_service.get_emotion_summary(device_key)

        return {
            "code": 0,
            "message": "ok",
            "data": {
                "device_id": device_id,
                "device_key": device_key,
                "profile": profile.to_dict(),
                "emotion_summary": emotion_summary,
            },
        }
    except Exception as e:
        logger.error(f"获取成长信息失败: {e}")
        return {"code": 1, "message": f"获取成长信息失败: {e}", "data": None}


@router.get("/api/v1/growth/emotions/{device_id}")
async def get_device_emotions(device_id: str, days: int = 7, user: UserModel = Depends(get_current_user)):
    """获取设备的情绪历史"""
    if not await _check_device_owner(device_id, user):
        from fastapi import HTTPException
        raise HTTPException(403, "Device not bound to you")
    try:
        from src.use_cases.growth.emotion_analyzer import EmotionAnalyzer

        data_dir = _get_data_dir()
        device_key = _resolve_device_key(device_id)

        emotion_service = EmotionAnalyzer(data_dir)
        emotions = await emotion_service.get_recent_emotions(device_key, days=days)

        emotion_list = []
        for e in emotions:
            emotion_list.append({
                "timestamp": e.timestamp,
                "emotion": e.emotion,
                "intensity": e.intensity,
                "trigger": e.trigger,
                "context": e.context,
            })

        return {
            "code": 0,
            "message": "ok",
            "data": {
                "device_id": device_id,
                "device_key": device_key,
                "days": days,
                "count": len(emotion_list),
                "emotions": emotion_list,
            },
        }
    except Exception as e:
        logger.error(f"获取情绪历史失败: {e}")
        return {"code": 1, "message": f"获取情绪历史失败: {e}", "data": None}