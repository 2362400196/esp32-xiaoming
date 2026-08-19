"""SQLAlchemy 2.0 声明式基类 + 通用 Mixin

所有 ORM 模型继承 ``Base``。``TimestampMixin`` 提供 ``created_at`` / ``updated_at``
两个字段，用于热重载版本检测和审计。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Float, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 声明式基类"""
    pass


class TimestampMixin:
    """通用时间戳 Mixin

    - ``created_at``：记录创建时间（UNIX 时间戳，秒）
    - ``updated_at``：记录最后更新时间，每次 UPDATE 自动刷新
      热重载机制通过对比 ``updated_at`` 判断是否需要刷新内存配置
    """
    created_at: Mapped[float] = mapped_column(
        Float, default=lambda: datetime.now(timezone.utc).timestamp(), nullable=False
    )
    updated_at: Mapped[float] = mapped_column(
        Float,
        default=lambda: datetime.now(timezone.utc).timestamp(),
        onupdate=lambda: datetime.now(timezone.utc).timestamp(),
        nullable=False,
    )


__all__ = ["Base", "TimestampMixin"]
