"""网站设置路由

公共接口：前端读取网站名称等公开信息（无需登录）。
管理员读写接口在 admin.py（/api/v1/admin/site-settings）。
"""
from __future__ import annotations

import json

from fastapi import APIRouter
from sqlalchemy import select

from src.infrastructure.db.models import SiteSettingModel
from src.infrastructure.db.session import get_session_ctx
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/site", tags=["site"])

# 网站设置默认值
SITE_SETTING_DEFAULTS = {
    "site_name": "ESP-AI",
    "site_subtitle": "智能语音助手",
    "site_logo": "",
    "site_footer": "",
    "site_icp": "",
    "login_welcome": "",
}

# 可编辑字段白名单
SITE_SETTING_KEYS = set(SITE_SETTING_DEFAULTS)


async def get_site_settings() -> dict:
    """读取网站设置（合并默认值）"""
    try:
        async with get_session_ctx() as session:
            result = await session.execute(
                select(SiteSettingModel).where(SiteSettingModel.id == 1)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return dict(SITE_SETTING_DEFAULTS)
            stored = json.loads(row.settings_json or "{}")
            merged = dict(SITE_SETTING_DEFAULTS)
            merged.update({k: v for k, v in stored.items() if k in SITE_SETTING_KEYS})
            return merged
    except Exception as e:
        logger.warning(f"[Site] 读取网站设置失败: {e}")
        return dict(SITE_SETTING_DEFAULTS)


async def save_site_settings(data: dict) -> dict:
    """保存网站设置（白名单过滤），返回合并后的完整设置"""
    async with get_session_ctx() as session:
        result = await session.execute(
            select(SiteSettingModel).where(SiteSettingModel.id == 1)
        )
        row = result.scalar_one_or_none()
        stored = json.loads(row.settings_json) if row and row.settings_json else {}
        for k, v in data.items():
            if k in SITE_SETTING_KEYS:
                stored[k] = str(v).strip() if v is not None else ""
        if row is None:
            row = SiteSettingModel(id=1, settings_json=json.dumps(stored, ensure_ascii=False))
            session.add(row)
        else:
            row.settings_json = json.dumps(stored, ensure_ascii=False)
        merged = dict(SITE_SETTING_DEFAULTS)
        merged.update({k: v for k, v in stored.items() if k in SITE_SETTING_KEYS})
        return merged


@router.get("/settings")
async def public_site_settings():
    """公开网站设置（无需登录）：供前端应用网站名称/标题/页脚等"""
    settings = await get_site_settings()
    return {"code": 0, "message": "ok", "data": settings}
