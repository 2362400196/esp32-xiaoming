"""计费 ORM 模型

- BillingRecordModel: 每次会话的用量与费用记录（ASR 字数 / LLM tokens / TTS 字数）
- BillingConfigModel: 计费单价配置，固定单行 id=1 JSON 存储
"""
from __future__ import annotations

from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.db.base import Base, TimestampMixin


class BillingRecordModel(Base, TimestampMixin):
    """计费记录表：一次会话一条记录，记录 ASR/LLM/TTS 用量与费用"""

    __tablename__ = "billing_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False, default="")
    session_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False, default="")

    # 用量
    # ASR 按时长计费（分钟）；asr_chars 为历史字段（按字数计费时代遗留），新记录恒为 0
    asr_minutes: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    asr_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 输入 tokens 中命中缓存的部分（DeepSeek 缓存命中价低于未命中价）
    llm_cache_hit_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tts_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 费用（元）
    asr_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    llm_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tts_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # 峰谷计费：该会话 LLM 是否按谷时折扣计费（审计用）
    llm_offpeak: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class BillingConfigModel(Base, TimestampMixin):
    """计费配置表：固定单行 id=1，config_json 存全部单价"""

    __tablename__ = "billing_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


__all__ = ["BillingRecordModel", "BillingConfigModel"]
