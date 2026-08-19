"""技能 ORM 模型（替代 SKILL.md 的 frontmatter + body）

frontmatter 拍平为列，body 存 Markdown 正文。
``file_path`` 和 ``directory`` 保留文件系统链接（过渡期双写）。
"""
from __future__ import annotations

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from src.infrastructure.db.base import Base, TimestampMixin


class SkillModel(Base, TimestampMixin):
    """技能表（替代 SKILL.md 的 frontmatter + body）"""
    __tablename__ = "skills"

    skill_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(128), default="")

    # 嵌套结构存 JSON
    cap_groups: Mapped[list] = mapped_column(JSON, default=list)
    category: Mapped[list] = mapped_column(JSON, default=list)
    peripherals: Mapped[list] = mapped_column(JSON, default=list)
    tags: Mapped[list] = mapped_column(JSON, default=list)

    manage_mode: Mapped[str] = mapped_column(String(32), default="readonly")

    # 所属设备（空=全局技能）
    device_id: Mapped[str] = mapped_column(String(128), default="", index=True)

    # Markdown 正文（frontmatter 之后的内容）
    body: Mapped[str] = mapped_column(Text, default="")

    # 文件系统链接（过渡期保留，用于子资源访问）
    file_path: Mapped[str] = mapped_column(String(512), default="")
    directory: Mapped[str] = mapped_column(String(512), default="")

    # 来源
    source: Mapped[str] = mapped_column(String(32), default="builtin")

    __table_args__ = (
        Index("idx_skills_name", "name"),
    )


__all__ = ["SkillModel"]
