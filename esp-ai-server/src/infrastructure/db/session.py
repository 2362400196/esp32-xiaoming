"""异步会话上下文管理

提供两种使用模式：
1. FastAPI 依赖注入：``Depends(get_session)``
2. 显式事务：``async with get_session_ctx() as session:``
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db.engine import get_session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖注入用的异步会话生成器

    用法：
        @app.get("/api/devices")
        async def list_devices(session: AsyncSession = Depends(get_session)):
            ...
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_session_ctx() -> AsyncIterator[AsyncSession]:
    """显式事务上下文管理器

    用法：
        async with get_session_ctx() as session:
            session.add(obj)
            await session.flush()
        # 退出上下文时自动 commit/rollback
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


__all__ = ["get_session", "get_session_ctx"]
