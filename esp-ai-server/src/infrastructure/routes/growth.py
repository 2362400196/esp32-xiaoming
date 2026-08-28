"""AI 成长系统路由

设备日记、用户画像、情绪历史等成长系统路由。

设备配置数据源为 DB（DeviceRepository）。
认证方式：JWT 用户认证 + 设备归属校验。
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException

from src.infrastructure.logging import get_logger
from src.infrastructure.security_jwt import get_current_user
from src.infrastructure.db.models.user import UserModel
from src.infrastructure.routes._deps import check_device_owner as _check_device_owner
from src.infrastructure.routes._deps import resolve_device_key as _resolve_device_key

logger = get_logger(__name__)

router = APIRouter(tags=["growth"])


def _get_data_dir() -> str:
    """获取 data 目录路径（src/data）"""
    return os.path.join(os.path.dirname(__file__), "..", "..", "data")


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
        raise HTTPException(403, "Device not bound to you")
    from src.use_cases.growth import DiaryService

    data_dir = _get_data_dir()
    diary_service = DiaryService(data_dir)

    device_key = _resolve_device_key(device_id)

    # 获取指定日期的日记
    if date:
        content = await diary_service.get_diary_content(device_key, date)
        if content:
            # 兼容 {"日记":"..."} JSON 格式
            import json as _json
            try:
                parsed = _json.loads(content)
                if isinstance(parsed, dict):
                    content = parsed.get("日记") or parsed.get("content") or content
            except Exception:
                pass
            return {"code": 0, "message": "ok", "data": {"date": date, "content": content}}
        else:
            return {"code": 0, "message": "ok", "data": {"date": date, "content": None, "message": "该日期无日记"}}

    # 获取所有日记列表
    entries = await diary_service.get_all_entries(device_key)
    diary_list = []
    for entry in entries[:limit]:
        # 提取日记正文（兼容 {"日记":"..."} JSON 格式）
        raw_text = entry.content
        import json as _json
        try:
            parsed = _json.loads(raw_text)
            if isinstance(parsed, dict):
                raw_text = parsed.get("日记") or parsed.get("content") or raw_text
        except Exception:
            pass
        summary = (raw_text[:200] + "...") if len(raw_text) > 200 else raw_text
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


@router.get("/api/v1/growth/diary/{device_id}/{date}")
async def get_device_diary_by_date(device_id: str, date: str, user: UserModel = Depends(get_current_user)):
    """获取设备指定日期的日记（快捷方式）"""
    return await get_device_diary(device_id, date=date, limit=30, user=user)


@router.get("/api/v1/growth/profile/{device_id}")
async def get_device_growth_profile(device_id: str, user: UserModel = Depends(get_current_user)):
    """获取设备的用户画像和成长信息"""
    if not await _check_device_owner(device_id, user):
        raise HTTPException(403, "Device not bound to you")
    data_dir = _get_data_dir()
    device_key = _resolve_device_key(device_id)

    # 获取用户画像
    from src.use_cases.growth.user_profile import UserProfileService
    profile_service = UserProfileService(data_dir)
    profile = await profile_service.get_profile(device_key)
    profile_dict = profile.to_dict()

    # 获取情绪摘要
    from src.use_cases.growth.emotion_analyzer import EmotionAnalyzer
    emotion_service = EmotionAnalyzer(data_dir)
    emotion_summary = await emotion_service.get_emotion_summary(device_key)

    # 统计自学习技能数（扫描 skills 目录）
    learned_skills_count = 0
    try:
        import os as _os
        skills_dir = _os.path.join(data_dir, "devices", device_key, "skills")
        if _os.path.exists(skills_dir):
            learned_skills_count = len([d for d in _os.scandir(skills_dir) if d.is_dir()])
    except Exception:
        pass

    # 统计活跃天数（有日记的天数）
    active_days = 0
    try:
        from src.use_cases.growth.diary_service import DiaryService
        diary_svc = DiaryService(data_dir)
        entries = await diary_svc.get_all_entries(device_key)
        if entries:
            active_days = len(set(e.date for e in entries))
    except Exception:
        pass

    profile_dict["learned_skills_count"] = learned_skills_count
    profile_dict["active_days"] = active_days

    # 前端兼容：将 interests dict 展平为字符串数组
    # interests 原始格式: {"likes": ["游泳"], "dislikes": [], "learning": ["编程"]}
    flat_interests = []
    interests_map = profile_dict.get("interests", {})
    if isinstance(interests_map, dict):
        for category, items in interests_map.items():
            if items and isinstance(items, list):
                category_label = {"likes": "喜欢", "dislikes": "不喜欢", "learning": "学习"}.get(category, category)
                for item in items:
                    if item:
                        flat_interests.append(f"{category_label}: {item}")
    profile_dict["interests"] = flat_interests

    # 前端兼容：personality_traits（从 personality dict 提取）
    personality = profile_dict.get("personality", {})
    if isinstance(personality, dict):
        profile_dict["personality_traits"] = list(personality.keys())
    else:
        profile_dict["personality_traits"] = []

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "device_id": device_id,
            "device_key": device_key,
            "profile": profile_dict,
            "emotion_summary": emotion_summary,
        },
    }


@router.get("/api/v1/growth/emotions/{device_id}")
async def get_device_emotions(device_id: str, days: int = 7, user: UserModel = Depends(get_current_user)):
    """获取设备的情绪历史"""
    if not await _check_device_owner(device_id, user):
        raise HTTPException(403, "Device not bound to you")
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