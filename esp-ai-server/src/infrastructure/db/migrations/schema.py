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


async def _existing_columns(conn, table: str) -> set[str]:
    """读取表的现有列名集合（PRAGMA table_info）。表不存在返回空集。"""
    rows = await conn.execute(text(f"PRAGMA table_info({table})"))
    return {r[1] for r in rows.fetchall()}


async def _ensure_column(conn, table: str, column: str, ddl: str, existing: set[str]) -> None:
    """表缺少指定列时执行 ALTER 添加。

    - 列已存在：静默跳过（正常幂等路径，不产生日志噪音）
    - ALTER 真正失败（锁超时、磁盘错误等）：记 WARNING，避免 schema 与模型静默漂移
    """
    if column in existing:
        return
    try:
        await conn.execute(text(ddl))
        logger.info(f"[DB] 迁移: {table} 表增加 {column} 列")
    except Exception as e:
        logger.warning(f"[DB] 迁移: {table}.{column} ALTER 失败: {e}")


async def init_db() -> None:
    """初始化数据库：创建所有表 + 执行 Schema 迁移（幂等）

    使用 ``Base.metadata.create_all`` 创建新表。
    ALTER 前先用 PRAGMA 检查列是否存在，只对缺失的列执行 ALTER。
    """
    engine = get_engine()
    async with engine.begin() as conn:
        # === Schema 检查：市场插件表 developer_id 列类型（只告警，不自动重建） ===
        # 旧 schema 中 developer_id 为 INTEGER（引用 marketplace_developers.id），
        # 新 schema 改为 VARCHAR(36)（引用 users.id UUID 字符串）。
        # 禁止启动时自动 DROP 重建：一次误判即会清空全部市场数据。
        # 检测到旧类型列时仅记录 ERROR 日志提示手动迁移，旧数据保留不动。
        try:
            col_info = await conn.execute(text("PRAGMA table_info(marketplace_plugins)"))
            cols = col_info.fetchall()
            if cols:
                dev_col = [c for c in cols if c[1] == "developer_id"]
                if dev_col and "INTEGER" in str(dev_col[0][2]).upper():
                    logger.error(
                        "[DB] 迁移: marketplace_plugins.developer_id 列为旧 INTEGER 类型，"
                        "需要手动执行迁移，启动流程已跳过自动重建（旧数据保留）。"
                        "涉及数据表：marketplace_plugins、marketplace_plugin_versions、"
                        "marketplace_plugin_reviews、marketplace_developers。"
                    )
        except Exception as e:
            logger.warning(f"[DB] 迁移: 市场表 developer_id 类型检查失败: {e}")

        await conn.run_sync(Base.metadata.create_all)

        # === Schema 迁移：先读取现有列，再只补缺失的列 ===
        devices_cols = await _existing_columns(conn, "devices")
        marketplace_cols = await _existing_columns(conn, "marketplace_plugins")
        users_cols = await _existing_columns(conn, "users")

        # token_version：JWT 吊销版本号（改密码/停用用户时 +1），旧库补列默认 0
        await _ensure_column(conn, "users", "token_version",
            "ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0",
            users_cols)

        await _ensure_column(conn, "devices", "management_api_key",
            "ALTER TABLE devices ADD COLUMN management_api_key VARCHAR(256) NOT NULL DEFAULT ''",
            devices_cols)
        await _ensure_column(conn, "devices", "user_id",
            "ALTER TABLE devices ADD COLUMN user_id VARCHAR(36) REFERENCES users(id)",
            devices_cols)
        await _ensure_column(conn, "devices", "bound_at",
            "ALTER TABLE devices ADD COLUMN bound_at FLOAT",
            devices_cols)
        await _ensure_column(conn, "devices", "bind_code",
            "ALTER TABLE devices ADD COLUMN bind_code VARCHAR(6)",
            devices_cols)
        await _ensure_column(conn, "devices", "bind_code_expires",
            "ALTER TABLE devices ADD COLUMN bind_code_expires FLOAT",
            devices_cols)
        await _ensure_column(conn, "devices", "enabled_plugins",
            "ALTER TABLE devices ADD COLUMN enabled_plugins TEXT",
            devices_cols)
        await _ensure_column(conn, "devices", "has_display",
            "ALTER TABLE devices ADD COLUMN has_display BOOLEAN",
            devices_cols)
        await _ensure_column(conn, "devices", "plugin_configs",
            "ALTER TABLE devices ADD COLUMN plugin_configs TEXT",
            devices_cols)
        await _ensure_column(conn, "devices", "robot_mode",
            "ALTER TABLE devices ADD COLUMN robot_mode VARCHAR(8) NOT NULL DEFAULT 'false'",
            devices_cols)
        await _ensure_column(conn, "devices", "screensaver_enabled",
            "ALTER TABLE devices ADD COLUMN screensaver_enabled VARCHAR(8) NOT NULL DEFAULT 'true'",
            devices_cols)
        await _ensure_column(conn, "devices", "screensaver_timeout",
            "ALTER TABLE devices ADD COLUMN screensaver_timeout VARCHAR(8) NOT NULL DEFAULT '30'",
            devices_cols)
        await _ensure_column(conn, "marketplace_plugins", "provides",
            "ALTER TABLE marketplace_plugins ADD COLUMN provides TEXT NOT NULL DEFAULT '[]'",
            marketplace_cols)
        await _ensure_column(conn, "marketplace_plugins", "icon",
            "ALTER TABLE marketplace_plugins ADD COLUMN icon VARCHAR(256) NOT NULL DEFAULT ''",
            marketplace_cols)

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
