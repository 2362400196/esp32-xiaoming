"""短期记忆仓储（SQL 实现，阶段 2：仓储层）

替代 ``JsonMemoryRepository``，使用 SQLAlchemy 同步会话。

- 每条消息一行，按 ``(device_id, seq)`` 查询排序
- ``save`` 在事务内 DELETE + batch INSERT，保证原子性
- 返回的消息格式与原 JSON 实现一致：``[{role, content, timestamp, datetime}]``

替代项：
- ``src/infrastructure/memory_repository.py`` 中的 ``JsonMemoryRepository``
"""
from __future__ import annotations

import time

from sqlalchemy import delete, select

from src.infrastructure.db.compat.sync_session import get_sync_session
from src.infrastructure.db.models.memory import ShortTermMemoryModel
from src.infrastructure.logging import get_logger
from src.use_cases.ports import MemoryRepository

logger = get_logger(__name__)


class SqlShortTermMemoryRepository(MemoryRepository):
    """短期记忆 SQL 仓储（同步）

    实现 ``MemoryRepository`` 接口，使用同步会话（``get_sync_session``）。
    供 ``ConversationMemory`` 等同步调用点使用。

    消息格式：
        ``{"role": str, "content": str, "timestamp": float, "datetime": str}``
    """

    def load(self, device_id: str) -> list[dict]:
        """加载指定设备的对话历史，按 seq 升序排列。

        返回 ``[{role, content, timestamp, datetime}]`` 列表，与原 JSON 格式一致。
        """
        if not device_id:
            return []
        with get_sync_session() as session:
            result = session.execute(
                select(ShortTermMemoryModel)
                .where(ShortTermMemoryModel.device_id == device_id)
                .order_by(ShortTermMemoryModel.seq)
            )
            rows = result.scalars().all()
            return [
                {
                    "role": row.role,
                    "content": row.content,
                    "timestamp": row.timestamp,
                    "datetime": row.datetime_str,
                }
                for row in rows
            ]

    def save(self, device_id: str, messages: list[dict]) -> None:
        """保存指定设备的对话历史（事务内 DELETE + batch INSERT）。

        - 先删除该设备的所有旧消息
        - 再按列表顺序批量插入新消息（seq = 列表索引）
        - 整个操作在一个事务内完成，保证原子性
        """
        if not device_id:
            return
        with get_sync_session() as session:
            # 先删除旧消息
            session.execute(
                delete(ShortTermMemoryModel).where(
                    ShortTermMemoryModel.device_id == device_id
                )
            )
            # 批量插入新消息
            now_ts = time.time()
            now_str = time.strftime("%Y-%m-%d %H:%M:%S")
            for seq, msg in enumerate(messages):
                ts = msg.get("timestamp")
                if not isinstance(ts, (int, float)):
                    ts = now_ts
                dt = msg.get("datetime")
                if not dt:
                    dt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
                session.add(
                    ShortTermMemoryModel(
                        device_id=device_id,
                        role=msg.get("role", "user"),
                        content=msg.get("content", ""),
                        timestamp=float(ts),
                        datetime_str=dt,
                        seq=seq,
                    )
                )

    def delete(self, device_id: str) -> None:
        """删除指定设备的全部对话历史。"""
        if not device_id:
            return
        with get_sync_session() as session:
            session.execute(
                delete(ShortTermMemoryModel).where(
                    ShortTermMemoryModel.device_id == device_id
                )
            )


__all__ = ["SqlShortTermMemoryRepository"]
