"""同步兼容层

为 ``load_devices()``、``AuthService`` 等无法立即改为异步的同步调用点提供同步会话。

SQLite WAL 模式下，同步引擎和异步引擎可以安全地同时访问同一数据库文件。
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from src.infrastructure.config import get_settings
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)

_sync_engine: Optional[Engine] = None
_sync_session_factory: Optional[sessionmaker] = None


def _apply_sync_pragmas(dbapi_conn, _connection_record) -> None:
    """同步连接的 PRAGMA 设置（与异步引擎一致）"""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def get_sync_engine() -> Engine:
    """获取全局同步引擎单例"""
    global _sync_engine
    if _sync_engine is None:
        settings = get_settings()
        sync_url = settings.database.sync_url

        # 确保数据目录存在
        if ":///" in sync_url and not sync_url.startswith("sqlite:///:memory:"):
            db_file = sync_url.split("///")[-1]
            db_path = Path(db_file)
            db_path.parent.mkdir(parents=True, exist_ok=True)

        _sync_engine = create_engine(sync_url, echo=settings.database.echo, future=True)

        @event.listens_for(_sync_engine, "connect")
        def _on_connect(dbapi_conn, connection_record):
            _apply_sync_pragmas(dbapi_conn, connection_record)

        logger.info(f"[DB] 同步引擎已创建: {sync_url}")

    return _sync_engine


def get_sync_session_factory() -> sessionmaker:
    """获取全局同步会话工厂单例"""
    global _sync_session_factory
    if _sync_session_factory is None:
        _sync_session_factory = sessionmaker(
            bind=get_sync_engine(),
            class_=Session,
            expire_on_commit=False,
            autoflush=False,
        )
    return _sync_session_factory


@contextmanager
def get_sync_session() -> Iterator[Session]:
    """同步会话上下文管理器

    用法：
        with get_sync_session() as session:
            ...
    """
    factory = get_sync_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_sync_engine() -> None:
    """释放同步引擎资源（测试用）"""
    global _sync_engine, _sync_session_factory
    if _sync_engine is not None:
        _sync_engine.dispose()
        _sync_engine = None
        _sync_session_factory = None
        logger.info("[DB] 同步引擎已释放")


__all__ = ["get_sync_engine", "get_sync_session_factory", "get_sync_session", "dispose_sync_engine"]
