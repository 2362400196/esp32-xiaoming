"""设备配置 ORM 模型（替代 users.json）

标量字段拍平为列，复杂嵌套对象（asr_config、tts_config、mcp_servers 等）存 JSON 列。
``updated_at`` 用于热重载版本检测。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from src.infrastructure.db.base import Base, TimestampMixin


class DeviceModel(Base, TimestampMixin):
    """设备配置表（替代 users.json 中的 devices 字典）"""

    __tablename__ = "devices"

    # 主键
    device_id: Mapped[str] = mapped_column(String(128), primary_key=True)

    # 用户绑定（企业级架构新增）
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    bound_at: Mapped[float | None] = mapped_column(nullable=True, default=None)
    bind_code: Mapped[str | None] = mapped_column(String(6), nullable=True, default=None)
    bind_code_expires: Mapped[float | None] = mapped_column(nullable=True, default=None)

    # 关系
    owner = relationship("UserModel", backref="devices", foreign_keys=[user_id])

    # 基本信息
    name: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    device_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    management_api_key: Mapped[str] = mapped_column(String(256), default="")
    mac_address: Mapped[str] = mapped_column(String(64), default="", index=True)

    # ASR/LLM/TTS 提供商
    asr_provider: Mapped[str] = mapped_column(String(32), default="")
    llm_type: Mapped[str] = mapped_column(String(32), default="")
    tts_type: Mapped[str] = mapped_column(String(32), default="")

    # 嵌套配置（JSON 列）
    asr_config: Mapped[dict] = mapped_column(JSON, default=dict)
    tts_config: Mapped[dict] = mapped_column(JSON, default=dict)
    music_config: Mapped[dict] = mapped_column(JSON, default=dict)
    mcp_servers: Mapped[dict] = mapped_column(JSON, default=dict)
    wakeup_config: Mapped[dict] = mapped_column(JSON, default=dict)

    # LLM 配置（拍平常用字段）
    llm_api_key: Mapped[str] = mapped_column(String(256), default="")
    llm_base_url: Mapped[str] = mapped_column(String(512), default="")
    llm_model: Mapped[str] = mapped_column(String(128), default="")
    llm_system_prompt: Mapped[str] = mapped_column(Text, default="")
    llm_memory_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    llm_memory_max_messages: Mapped[int] = mapped_column(Integer, default=20)
    llm_memory_long_term_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    llm_memory_long_term_auto_extract: Mapped[bool] = mapped_column(Boolean, default=True)

    # 限流
    rate_limit_rpm: Mapped[int] = mapped_column(Integer, default=0)

    # OTA 配置
    ota_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    ota_bin_url: Mapped[str] = mapped_column(String(1024), default="")
    ota_version: Mapped[str] = mapped_column(String(64), default="")
    ota_bin_id: Mapped[str] = mapped_column(String(128), default="")
    ota_is_official: Mapped[str] = mapped_column(String(8), default="0")

    # 禁用项（JSON 列）
    disabled_tools: Mapped[list] = mapped_column(JSON, default=list)
    disabled_mcp_servers: Mapped[list] = mapped_column(JSON, default=list)
    disabled_mcp_tools: Mapped[dict] = mapped_column(JSON, default=dict)
    disabled_skills: Mapped[list] = mapped_column(JSON, default=list)

    # 插件商店：设备已安装插件列表（null/空 = 未安装任何插件）
    enabled_plugins: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)
    # 插件配置：{插件名: {配置项: 值}}（天气插件的高德 Key 等）
    plugin_configs: Mapped[dict] = mapped_column(JSON, default=dict)
    # 设备屏幕能力（None = 未知，回退固件上报/默认有屏）
    has_display: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)

    # 技能列表
    skills: Mapped[list] = mapped_column(JSON, default=list)

    # 表情包
    active_emo_pack: Mapped[str] = mapped_column(String(128), default="default")

    # 屏幕显示配置
    robot_mode: Mapped[str] = mapped_column(String(8), default="false")
    screensaver_enabled: Mapped[str] = mapped_column(String(8), default="true")
    screensaver_timeout: Mapped[str] = mapped_column(String(8), default="30")

    # 运行时状态
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen: Mapped[float] = mapped_column(Float, default=0.0)
    # 封禁状态
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    banned_at: Mapped[float | None] = mapped_column(nullable=True, default=None)
    ban_reason: Mapped[str] = mapped_column(String(256), default="")

    __table_args__ = (
        Index("idx_devices_mac", "mac_address"),
        Index("idx_devices_updated_at", "updated_at"),
    )


__all__ = ["DeviceModel"]
