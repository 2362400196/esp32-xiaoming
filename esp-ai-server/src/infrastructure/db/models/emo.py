"""表情包元数据 ORM 模型（替代 emos/packs/{pack}/meta.json）

GIF 文件仍存磁盘，DB 只存元数据。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.db.base import Base, TimestampMixin


class EmoPackModel(Base, TimestampMixin):
    """表情包元数据表（替代 emos/packs/{pack}/meta.json）

    - ``owner_user_id``：表情包归属用户；NULL 表示公共包（default、管理员创建的包），
      所有用户可见可用；非空时仅归属用户本人和管理员可见。
    - ``cover``：封面 GIF 文件名（包内文件）；为空时按默认规则自动挑选。
    """
    __tablename__ = "emo_packs"

    pack_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    owner_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    cover: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)


__all__ = ["EmoPackModel"]
