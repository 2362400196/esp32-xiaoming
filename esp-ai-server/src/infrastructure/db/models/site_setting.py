"""网站设置 ORM 模型

单行（id=1）JSON 存储全部网站设置字段，供管理员后台编辑、前端公开读取。
"""
from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.db.base import Base, TimestampMixin


class SiteSettingModel(Base, TimestampMixin):
    """网站设置表：固定单行 id=1，settings_json 存全部字段"""
    __tablename__ = "site_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    settings_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
