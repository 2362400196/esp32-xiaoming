"""用户 ORM 模型

企业级架构：用户账户体系，每用户可绑定多台设备
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.db.base import Base, TimestampMixin


class UserModel(Base, TimestampMixin):
    """用户表：注册登录、账户管理"""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    nickname: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="user", nullable=False)  # admin / user
    max_devices: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login: Mapped[float | None] = mapped_column(nullable=True, default=None)
    # 开发者字段（复用用户体系，无需单独注册）
    developer_api_key: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True, index=True)
    developer_bio: Mapped[str] = mapped_column(String(256), default="", nullable=False)
