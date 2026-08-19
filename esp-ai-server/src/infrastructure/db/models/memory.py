"""记忆系统 ORM 模型

- ``ShortTermMemoryModel``：短期会话记忆（替代 memories/{id}.json）
- ``LongTermMemoryRecordModel``：长期记忆记录（替代 records.jsonl，CRUD 模式）
- ``LongTermMemorySummaryLabelModel``：长期记忆摘要标签索引（替代 index.json 的 summaries）
- ``LongTermMemoryKeywordIndexModel``：长期记忆关键词倒排索引（替代 index.json 的 keyword_index）
"""
from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from src.infrastructure.db.base import Base, TimestampMixin


class ShortTermMemoryModel(Base):
    """短期会话记忆表（替代 memories/{id}.json）

    每条消息一行，按 (device_id, seq) 查询排序。
    """
    __tablename__ = "short_term_memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    datetime_str: Mapped[str] = mapped_column(String(32), default="")
    seq: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("idx_stm_device_seq", "device_id", "seq"),
    )


class LongTermMemoryRecordModel(Base, TimestampMixin):
    """长期记忆记录表（替代 records.jsonl）

    从 Event-Sourcing 改为 CRUD 模式，UPDATE in place。
    """
    __tablename__ = "long_term_memory_records"

    memory_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(32), default="manual")
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index("idx_ltm_device_deleted", "device_id", "deleted"),
        Index("idx_ltm_device_access", "device_id", "deleted", "access_count"),
        Index("idx_ltm_updated_at", "updated_at"),
    )


class LongTermMemorySummaryLabelModel(Base):
    """长期记忆摘要标签表（替代 index.json 的 summaries 数组）"""
    __tablename__ = "long_term_memory_summary_labels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    ref_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        # 同一设备同一标签唯一
        Index("idx_ltm_sl_device_label", "device_id", "label", unique=True),
    )


class LongTermMemoryKeywordIndexModel(Base):
    """长期记忆关键词倒排索引表（替代 index.json 的 keyword_index 字典）"""
    __tablename__ = "long_term_memory_keyword_index"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    keyword: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    memory_id: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        # 同一设备同一关键词同一记忆唯一
        Index("idx_ltm_kw_device_kw_mem", "device_id", "keyword", "memory_id", unique=True),
    )


__all__ = [
    "ShortTermMemoryModel",
    "LongTermMemoryRecordModel",
    "LongTermMemorySummaryLabelModel",
    "LongTermMemoryKeywordIndexModel",
]
