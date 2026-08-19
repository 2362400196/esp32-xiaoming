"""数据库建表脚本

幂等建表，在应用启动时调用 ``await init_db()``。
"""
from __future__ import annotations

from sqlalchemy import text

from src.infrastructure.db.base import Base
from src.infrastructure.db.engine import get_engine
from src.infrastructure.db.models import *  # noqa: F401,F403 — 确保所有模型被导入
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


async def init_db() -> None:
    """初始化数据库：创建所有表 + 执行 Schema 迁移（幂等）

    使用 ``Base.metadata.create_all`` 创建新表。
    ALTER TABLE 用 try/except 包裹，已存在的列不会重复添加。
    """
    engine = get_engine()
    async with engine.begin() as conn:
        # === Schema 迁移：市场插件表 developer_id 列类型修复 ===
        # 旧 schema 中 developer_id 为 INTEGER（引用 marketplace_developers.id），
        # 新 schema 改为 VARCHAR(36)（引用 users.id UUID 字符串）。
        # SQLite 的 create_all 不会 ALTER 已有表，需手动检测并重建。
        try:
            col_info = await conn.execute(text("PRAGMA table_info(marketplace_plugins)"))
            cols = col_info.fetchall()
            if cols:
                dev_col = [c for c in cols if c[1] == "developer_id"]
                if dev_col and "INTEGER" in str(dev_col[0][2]).upper():
                    logger.info("[DB] 迁移: marketplace 表 developer_id 列为旧 INTEGER 类型，重建市场表")
                    await conn.execute(text("DROP TABLE IF EXISTS marketplace_plugin_reviews"))
                    await conn.execute(text("DROP TABLE IF EXISTS marketplace_plugin_versions"))
                    await conn.execute(text("DROP TABLE IF EXISTS marketplace_plugins"))
                    await conn.execute(text("DROP TABLE IF EXISTS marketplace_developers"))
        except Exception as e:
            logger.debug(f"[DB] 迁移: 市场表检查跳过: {e}")

        await conn.run_sync(Base.metadata.create_all)

        # === Schema 迁移：management_api_key 列 ===
        # SQLite 不支持 IF NOT EXISTS，用 try 包裹幂等执行
        try:
            await conn.execute(text(
                "ALTER TABLE devices ADD COLUMN management_api_key VARCHAR(256) NOT NULL DEFAULT ''"
            ))
            logger.info("[DB] 迁移: devices 表增加 management_api_key 列")
        except Exception:
            logger.debug("[DB] 迁移: management_api_key 列已存在，跳过")

        # === Schema 迁移：user_id + bind_code 列（企业级架构） ===
        try:
            await conn.execute(text(
                "ALTER TABLE devices ADD COLUMN user_id VARCHAR(36) REFERENCES users(id)"
            ))
            logger.info("[DB] 迁移: devices 表增加 user_id 列")
        except Exception:
            logger.debug("[DB] 迁移: user_id 列已存在，跳过")

        try:
            await conn.execute(text(
                "ALTER TABLE devices ADD COLUMN bound_at FLOAT"
            ))
            logger.info("[DB] 迁移: devices 表增加 bound_at 列")
        except Exception:
            logger.debug("[DB] 迁移: bound_at 列已存在，跳过")

        try:
            await conn.execute(text(
                "ALTER TABLE devices ADD COLUMN bind_code VARCHAR(6)"
            ))
            logger.info("[DB] 迁移: devices 表增加 bind_code 列")
        except Exception:
            logger.debug("[DB] 迁移: bind_code 列已存在，跳过")

        try:
            await conn.execute(text(
                "ALTER TABLE devices ADD COLUMN bind_code_expires FLOAT"
            ))
            logger.info("[DB] 迁移: devices 表增加 bind_code_expires 列")
        except Exception:
            logger.debug("[DB] 迁移: bind_code_expires 列已存在，跳过")

        # === Schema 迁移：插件商店（enabled_plugins 已安装插件列表 + has_display 屏幕能力） ===
        try:
            await conn.execute(text(
                "ALTER TABLE devices ADD COLUMN enabled_plugins TEXT"
            ))
            logger.info("[DB] 迁移: devices 表增加 enabled_plugins 列（插件商店）")
        except Exception:
            logger.debug("[DB] 迁移: enabled_plugins 列已存在，跳过")

        try:
            await conn.execute(text(
                "ALTER TABLE devices ADD COLUMN has_display BOOLEAN"
            ))
            logger.info("[DB] 迁移: devices 表增加 has_display 列（屏幕能力）")
        except Exception:
            logger.debug("[DB] 迁移: has_display 列已存在，跳过")

        # === Schema 迁移：插件配置（plugin_configs，{插件名: {配置项: 值}}） ===
        try:
            await conn.execute(text(
                "ALTER TABLE devices ADD COLUMN plugin_configs TEXT"
            ))
            logger.info("[DB] 迁移: devices 表增加 plugin_configs 列（插件配置）")
        except Exception:
            logger.debug("[DB] 迁移: plugin_configs 列已存在，跳过")

        # === 权限引导：系统中没有管理员时，最早注册的用户自动提升为管理员 ===
        # （兼容已部署系统：首个用户注册时已是 admin 的逻辑只对新系统生效）
        try:
            admin_cnt = await conn.execute(text("SELECT COUNT(*) FROM users WHERE role='admin'"))
            if (admin_cnt.scalar() or 0) == 0:
                await conn.execute(text(
                    "UPDATE users SET role='admin' WHERE id = "
                    "(SELECT id FROM users ORDER BY created_at ASC LIMIT 1)"
                ))
                logger.info("[DB] 权限引导：系统中无管理员，最早注册的用户已提升为管理员")
        except Exception as e:
            logger.debug(f"[DB] 权限引导跳过（用户表未就绪）: {e}")

        # 建 users 表（Base.metadata.create_all 已处理，这里做幂等确认）
        logger.info("[DB] 迁移: 用户相关表迁移完成")

        # 安全说明：此处不再批量写入弱管理 API Key（如 '456'）。
        # 设备的 management_api_key 应在注册/绑定时由代码生成随机密钥，
        # 避免所有设备共享同一弱密钥带来的安全风险。

    logger.info("[DB] 数据库表初始化完成")


async def drop_all_tables() -> None:
    """删除所有表（仅用于测试）"""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    logger.info("[DB] 所有表已删除")


__all__ = ["init_db", "drop_all_tables"]
