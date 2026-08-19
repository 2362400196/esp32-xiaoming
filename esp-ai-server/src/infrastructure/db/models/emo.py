"""表情包元数据 ORM 模型（替代 emos/packs/{pack}/meta.json）

GIF 文件仍存磁盘，DB 只存元数据。
"""
from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.db.base import Base, TimestampMixin


class EmoPackModel(Base, TimestampMixin):
    """表情包元数据表（替代 emos/packs/{pack}/meta.json）"""
    __tablename__ = "emo_packs"

    pack_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)


__all__ = ["EmoPackModel"]
