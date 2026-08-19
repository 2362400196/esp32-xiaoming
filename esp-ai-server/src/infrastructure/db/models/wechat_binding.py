"""
微信绑定 ORM 模型
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.db.base import Base


class WeChatBindingModel(Base):
    """微信绑定表（替代 wechat_bindings.json）"""
    __tablename__ = "wechat_bindings"

    wechat_chat_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    wechat_user_id: Mapped[str] = mapped_column(String(128), default="")
    device_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    device_mac: Mapped[str] = mapped_column(String(64), default="")
    bound_at: Mapped[float] = mapped_column(
        Float, default=lambda: datetime.now(timezone.utc).timestamp(), nullable=False
    )
    wechat_group_id: Mapped[str] = mapped_column(String(64), default="")
    alias: Mapped[str] = mapped_column(Text, default="")
