"""
微信绑定仓储（异步）
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, select

from src.infrastructure.db.models.wechat_binding import WeChatBindingModel
from src.infrastructure.db.session import get_session_ctx
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


class WeChatBindingRepository:

    async def get_all(self) -> list[dict]:
        """获取所有绑定"""
        async with get_session_ctx() as session:
            result = await session.execute(select(WeChatBindingModel))
            return [_model_to_dict(m) for m in result.scalars().all()]

    async def get_by_device_key(self, device_key: str) -> Optional[dict]:
        """通过设备 key 查找"""
        async with get_session_ctx() as session:
            result = await session.execute(
                select(WeChatBindingModel).where(
                    WeChatBindingModel.device_key == device_key
                )
            )
            m = result.scalar_one_or_none()
            return _model_to_dict(m) if m else None

    async def get_by_wechat(self, wechat_chat_id: str) -> Optional[dict]:
        """通过微信 ID 查找"""
        async with get_session_ctx() as session:
            result = await session.execute(
                select(WeChatBindingModel).where(
                    WeChatBindingModel.wechat_chat_id == wechat_chat_id
                )
            )
            m = result.scalar_one_or_none()
            return _model_to_dict(m) if m else None

    async def upsert(self, data: dict) -> None:
        """插入或更新绑定"""
        async with get_session_ctx() as session:
            existing = await session.execute(
                select(WeChatBindingModel).where(
                    WeChatBindingModel.wechat_chat_id == data["wechat_chat_id"]
                )
            )
            m = existing.scalar_one_or_none()
            if m:
                m.device_key = data.get("device_key", m.device_key)
                m.device_mac = data.get("device_mac", m.device_mac)
                m.wechat_user_id = data.get("wechat_user_id", m.wechat_user_id)
                m.bound_at = data.get("bound_at", m.bound_at)
                m.wechat_group_id = data.get("wechat_group_id", m.wechat_group_id)
                m.alias = data.get("alias", m.alias)
            else:
                session.add(WeChatBindingModel(
                    wechat_chat_id=data["wechat_chat_id"],
                    wechat_user_id=data.get("wechat_user_id", ""),
                    device_key=data.get("device_key", ""),
                    device_mac=data.get("device_mac", ""),
                    bound_at=data.get("bound_at", datetime.now(timezone.utc).timestamp()),
                    wechat_group_id=data.get("wechat_group_id", ""),
                    alias=data.get("alias", ""),
                ))
            await session.flush()

    async def delete_by_device(self, device_key: str) -> None:
        """删除设备的绑定"""
        async with get_session_ctx() as session:
            await session.execute(
                delete(WeChatBindingModel).where(
                    WeChatBindingModel.device_key == device_key
                )
            )


def _model_to_dict(m: WeChatBindingModel) -> dict:
    return {
        "wechat_chat_id": m.wechat_chat_id,
        "wechat_user_id": m.wechat_user_id,
        "device_key": m.device_key,
        "device_mac": m.device_mac,
        "bound_at": m.bound_at,
        "wechat_group_id": m.wechat_group_id,
        "alias": m.alias,
    }
