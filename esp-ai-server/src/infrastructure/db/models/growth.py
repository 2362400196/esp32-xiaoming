"""成长系统 ORM 模型

- ``UserProfileModel``：用户画像（替代 user_profile.json）
- ``EmotionHistoryModel``：情绪历史（替代 emotion_history.json）
- ``LearningLogModel``：自学习日志（替代 learning_log.json）
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from src.infrastructure.db.base import Base, TimestampMixin


class UserProfileModel(Base, TimestampMixin):
    """用户画像表（替代 user_profile.json）

    一设备一行，UPSERT 语义。嵌套对象（family、personality、interests 等）存 JSON 列。
    """
    __tablename__ = "user_profiles"

    device_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    birthday: Mapped[str] = mapped_column(String(32), default="")
    occupation: Mapped[str] = mapped_column(String(128), default="")

    # 嵌套结构存 JSON
    family: Mapped[list] = mapped_column(JSON, default=list)
    personality: Mapped[dict] = mapped_column(JSON, default=dict)
    interests: Mapped[dict] = mapped_column(JSON, default=dict)
    habits: Mapped[dict] = mapped_column(JSON, default=dict)
    important_dates: Mapped[list] = mapped_column(JSON, default=list)
    current_state: Mapped[dict] = mapped_column(JSON, default=dict)


class EmotionHistoryModel(Base):
    """情绪历史表（替代 emotion_history.json）

    Append-only，插入后修剪到最近 100 条。
    """
    __tablename__ = "emotion_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    timestamp: Mapped[float] = mapped_column(Float, nullable=False)
    emotion: Mapped[str] = mapped_column(String(32), nullable=False)
    intensity: Mapped[float] = mapped_column(Float, default=0.0)
    trigger: Mapped[str] = mapped_column(String(512), default="")
    context: Mapped[str] = mapped_column(String(256), default="")
    speaker: Mapped[str] = mapped_column(String(16), default="user")

    __table_args__ = (
        Index("idx_eh_device_time", "device_id", "timestamp"),
    )


class LearningLogModel(Base):
    """自学习日志表（替代 learning_log.json）

    Append-only，插入后修剪到最近 100 条。
    """
    __tablename__ = "learning_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    timestamp: Mapped[float] = mapped_column(Float, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    skill_name: Mapped[str] = mapped_column(String(128), default="")
    title: Mapped[str] = mapped_column(String(256), default="")
    category: Mapped[str] = mapped_column(String(128), default="")

    __table_args__ = (
        Index("idx_ll_device_time", "device_id", "timestamp"),
    )


__all__ = ["UserProfileModel", "EmotionHistoryModel", "LearningLogModel", "AlarmModel", "DiaryModel"]


class DiaryModel(Base):
    """日记表（替代 markdown 文件存储）"""
    __tablename__ = "diaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    date: Mapped[str] = mapped_column(String(16), nullable=False)  # YYYY-MM-DD
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[float] = mapped_column(
        Float, default=lambda: datetime.now(timezone.utc).timestamp(), nullable=False
    )

    __table_args__ = (
        Index("idx_diary_device_date", "device_key", "date"),
    )


class AlarmModel(Base):
    """闹钟/提醒表"""
    __tablename__ = "alarms"

    alarm_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    device_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    alarm_type: Mapped[str] = mapped_column(String(16), nullable=False)  # alarm / reminder
    trigger_at: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, default="")
    repeat: Mapped[str] = mapped_column(String(16), default="once")
    created_at: Mapped[float] = mapped_column(
        Float, default=lambda: datetime.now(timezone.utc).timestamp(), nullable=False
    )

    __table_args__ = (
        Index("idx_alarm_device", "device_key"),
    )
