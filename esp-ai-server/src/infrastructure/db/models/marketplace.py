"""云市场 ORM 模型（Phase 2）

包含：
- ``MarketplacePluginModel``：市场插件主表（一个插件一条记录，slug 唯一）
- ``PluginVersionModel``：插件版本历史（每次上传创建一条，关联到插件）
- ``PluginReviewModel``：插件评论（普通用户 JWT 认证，一人一评）

设计说明：
- 开发者复用现有用户体系（UserModel.developer_api_key），无需单独注册。
- ``developer_id`` 引用 ``users.id``（字符串 UUID），与 device.user_id 类型一致。
- 时间戳复用 ``TimestampMixin``，与现有 device/user 等模型保持一致
  （created_at / updated_at 为 UNIX 浮点秒数，便于排序和跨时区比较）。
- ``tags`` 以 JSON 字符串存储（"[]"），避免引入 JSON 列类型依赖，读取时 ``json.loads``。
- 外键级联策略：删除用户时其插件一并删除；删除插件时其版本/评论一并删除。
"""
from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.db.base import Base, TimestampMixin


class MarketplacePluginModel(Base, TimestampMixin):
    """市场插件主表：一个 slug 对应一条记录"""
    __tablename__ = "marketplace_plugins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # URL 友好的 ID，如 "weather"；从 manifest.id 转小写获取
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 关联 users.id（字符串 UUID），开发者即普通用户
    developer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # general / weather / tools / media 等
    category: Mapped[str] = mapped_column(String(64), default="general", nullable=False, index=True)
    # JSON 数组字符串，如 '["weather","forecast"]'
    tags: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    latest_version: Mapped[str] = mapped_column(String(64), default="0.0.0", nullable=False)
    total_downloads: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_rating: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class PluginVersionModel(Base, TimestampMixin):
    """插件版本历史：每次上传创建一条"""
    __tablename__ = "marketplace_plugin_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plugin_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("marketplace_plugins.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    changelog: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 存储相对路径（相对 MARKETPLACE_STORAGE_DIR）
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    # SHA256 校验和
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    # 开发者签名（可选，预留验签）
    signature: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    download_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class PluginReviewModel(Base, TimestampMixin):
    """插件评论：普通用户 JWT 认证，一人一评"""
    __tablename__ = "marketplace_plugin_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plugin_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("marketplace_plugins.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 关联普通用户（users.id 为字符串 UUID）
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # 冗余存储用户名，避免跨表 join 提升查询性能
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)


__all__ = [
    "MarketplacePluginModel",
    "PluginVersionModel",
    "PluginReviewModel",
]
