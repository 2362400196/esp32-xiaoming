"""异步数据库引擎 + 会话工厂

使用 SQLite WAL 模式，允许并发读 + 单写。配合 ``busy_timeout`` 处理写冲突。

关键配置：
- ``journal_mode=WAL``：Write-Ahead Logging，读不阻塞写
- ``synchronous=NORMAL``：WAL 模式下安全且高效
- ``foreign_keys=ON``：启用外键约束
- ``busy_timeout=5000``：写冲突时等待 5 秒
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from src.infrastructure.config import get_settings
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)

# 全局单例
_async_engine: Optional[AsyncEngine] = None
_async_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def _apply_sqlite_pragmas(dbapi_conn, _connection_record) -> None:
    """在 SQLite 连接建立时设置 PRAGMA"""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def get_engine() -> AsyncEngine:
    """获取全局异步引擎单例"""
    global _async_engine
    if _async_engine is None:
        settings = get_settings()
        db_url = settings.database.url

        # 确保数据目录存在（SQLite 相对路径）
        if ":///" in db_url and not db_url.startswith("sqlite:///:memory:"):
            db_file = db_url.split("///")[-1]
            db_path = Path(db_file)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"[DB] 数据库文件路径: {db_path.absolute()}")

        _async_engine = create_async_engine(
            db_url,
            echo=settings.database.echo,
            pool_size=settings.database.pool_size,
            max_overflow=settings.database.max_overflow,
        )

        # 为 SQLite 连接设置 PRAGMA
        @event.listens_for(_async_engine.sync_engine, "connect")
        def _on_connect(dbapi_conn, connection_record):
            _apply_sqlite_pragmas(dbapi_conn, connection_record)

        logger.info(f"[DB] 异步引擎已创建: {db_url}")

    return _async_engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """获取全局异步会话工厂单例"""
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,  # 异步会话禁止 lazy loading
            autoflush=False,
        )
    return _async_session_factory


async def dispose_engine() -> None:
    """释放引擎资源（测试用）"""
    global _async_engine, _async_session_factory
    if _async_engine is not None:
        await _async_engine.dispose()
        _async_engine = None
        _async_session_factory = None
        logger.info("[DB] 异步引擎已释放")


__all__ = ["get_engine", "get_session_factory", "dispose_engine"]
