"""长期记忆仓储（SQL 实现，阶段 2：仓储层）

替代 ``JsonLongTermMemoryRepository``，使用 SQLAlchemy 异步会话。

- CRUD 模式（UPDATE in place），替代 JSONL 的 Event-Sourcing
- ``save`` 使用 SQLite UPSERT（INSERT ... ON CONFLICT DO UPDATE）
- ``_rebuild_index`` 重建 ``summary_labels`` + ``keyword_index`` 两张索引表
- ``MemoryItem`` <-> ``LongTermMemoryRecordModel`` 相互转换

替代项：
- ``src/infrastructure/memory_repository.py`` 中的 ``JsonLongTermMemoryRepository``
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities import MemoryItem
from src.domain.repositories import LongTermMemoryRepository
from src.infrastructure.db.models.memory import (
    LongTermMemoryKeywordIndexModel,
    LongTermMemoryRecordModel,
    LongTermMemorySummaryLabelModel,
)
from src.infrastructure.db.session import get_session_ctx
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


# ============================================================
# MemoryItem <-> LongTermMemoryRecordModel 转换
# ============================================================

def _model_to_item(model: LongTermMemoryRecordModel) -> MemoryItem:
    """将 ORM 模型转换为 MemoryItem 实体。"""
    return MemoryItem(
        memory_id=model.memory_id,
        device_id=model.device_id,
        content=model.content,
        tags=list(model.tags or []),
        keywords=list(model.keywords or []),
        source=model.source or "manual",
        created_at=model.created_at,
        updated_at=model.updated_at,
        access_count=model.access_count,
        deleted=model.deleted,
    )


def _item_to_fields(item: MemoryItem) -> dict:
    """将 MemoryItem 实体转换为 ORM 字段字典（不含 memory_id 主键）。"""
    return {
        "device_id": item.device_id,
        "content": item.content,
        "tags": list(item.tags or []),
        "keywords": list(item.keywords or []),
        "source": item.source or "manual",
        "access_count": item.access_count,
        "deleted": item.deleted,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _now_ts() -> float:
    """当前 UTC 时间戳（秒）"""
    return datetime.now(timezone.utc).timestamp()


# ============================================================
# SqlLongTermMemoryRepository
# ============================================================

class SqlLongTermMemoryRepository(LongTermMemoryRepository):
    """长期记忆 SQL 仓储（异步）

    实现 ``LongTermMemoryRepository`` 接口，使用异步会话（``get_session_ctx``）。

    存储布局：
    - ``long_term_memory_records``：记忆主表（CRUD 模式，UPDATE in place）
    - ``long_term_memory_summary_labels``：摘要标签索引（tags[:3] 聚合）
    - ``long_term_memory_keyword_index``：关键词倒排索引
    """

    # ============================================================
    # 领域接口实现
    # ============================================================

    async def save(self, item: MemoryItem) -> None:
        """保存一条记忆条目（UPSERT + 索引重建）。

        - 新记忆：INSERT
        - 已存在记忆：UPDATE 所有字段（``created_at`` 保留，``updated_at`` 刷新）
        """
        if not item.memory_id or not item.device_id:
            return
        fields = _item_to_fields(item)
        # 构造 UPSERT 语句
        stmt = sqlite_insert(LongTermMemoryRecordModel).values(
            memory_id=item.memory_id, **fields
        )
        # ON CONFLICT DO UPDATE：更新所有字段，但保留 created_at
        update_cols = {
            k: getattr(stmt.excluded, k)
            for k in fields.keys()
            if k != "created_at"
        }
        update_cols["updated_at"] = _now_ts()
        stmt = stmt.on_conflict_do_update(
            index_elements=["memory_id"],
            set_=update_cols,
        )
        async with get_session_ctx() as session:
            await session.execute(stmt)
            await self._rebuild_index(session, item.device_id)

    async def find_by_labels(
        self,
        device_id: str,
        summary_labels: tuple[str, ...],
        limit: int,
    ) -> list[MemoryItem]:
        """按摘要标签查找记忆，按 access_count 降序。

        - ``summary_labels`` 为空时返回所有活跃记忆
        - 否则返回 tags 包含任一标签的活跃记忆
        - ``limit=0`` 时使用默认值 8
        """
        if not device_id:
            return []
        async with get_session_ctx() as session:
            result = await session.execute(
                select(LongTermMemoryRecordModel).where(
                    LongTermMemoryRecordModel.device_id == device_id,
                    LongTermMemoryRecordModel.deleted.is_(False),
                )
            )
            rows = result.scalars().all()
            # 按标签过滤（匹配记录的任意 tag，与 JSON 实现一致）
            if summary_labels:
                rows = [
                    r for r in rows
                    if any(lb in (r.tags or []) for lb in summary_labels)
                ]
            # 按 access_count 降序
            rows.sort(key=lambda r: -r.access_count)
            effective_limit = limit or 8
            return [_model_to_item(r) for r in rows[:effective_limit]]

    async def find_all(self, device_id: str) -> list[MemoryItem]:
        """列出设备全部活跃记忆，按 access_count 降序。"""
        if not device_id:
            return []
        async with get_session_ctx() as session:
            result = await session.execute(
                select(LongTermMemoryRecordModel).where(
                    LongTermMemoryRecordModel.device_id == device_id,
                    LongTermMemoryRecordModel.deleted.is_(False),
                )
            )
            rows = result.scalars().all()
            rows.sort(key=lambda r: -r.access_count)
            return [_model_to_item(r) for r in rows]

    async def find_by_id(
        self,
        memory_id: str,
        device_id: str,
    ) -> Optional[MemoryItem]:
        """查找单条活跃记忆，未找到返回 None。"""
        if not memory_id or not device_id:
            return None
        async with get_session_ctx() as session:
            result = await session.execute(
                select(LongTermMemoryRecordModel).where(
                    LongTermMemoryRecordModel.memory_id == memory_id,
                    LongTermMemoryRecordModel.device_id == device_id,
                    LongTermMemoryRecordModel.deleted.is_(False),
                )
            )
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return _model_to_item(model)

    async def mark_deleted(self, memory_id: str, device_id: str) -> None:
        """软删除一条记忆（UPDATE deleted=True + 索引重建）。"""
        if not memory_id or not device_id:
            return
        async with get_session_ctx() as session:
            result = await session.execute(
                select(LongTermMemoryRecordModel).where(
                    LongTermMemoryRecordModel.memory_id == memory_id,
                    LongTermMemoryRecordModel.device_id == device_id,
                )
            )
            model = result.scalar_one_or_none()
            if model is None:
                return
            model.deleted = True
            model.updated_at = _now_ts()
            # 刷新到 DB，使后续 _rebuild_index 的 SELECT 能看到删除状态
            await session.flush()
            await self._rebuild_index(session, device_id)

    async def get_summary_labels(self, device_id: str) -> list[str]:
        """获取设备的摘要标签列表。"""
        if not device_id:
            return []
        async with get_session_ctx() as session:
            result = await session.execute(
                select(LongTermMemorySummaryLabelModel.label).where(
                    LongTermMemorySummaryLabelModel.device_id == device_id,
                )
            )
            return list(result.scalars().all())

    async def increment_access(self, memory_id: str, device_id: str) -> None:
        """增加活跃记忆的访问计数（access_count + 1）。

        使用原子 ``UPDATE ... SET access_count = access_count + 1``，
        避免读-改-写竞态条件，支持并发调用。

        已删除的记忆不会被增加。
        """
        if not memory_id or not device_id:
            return
        async with get_session_ctx() as session:
            await session.execute(
                update(LongTermMemoryRecordModel)
                .where(
                    LongTermMemoryRecordModel.memory_id == memory_id,
                    LongTermMemoryRecordModel.device_id == device_id,
                    LongTermMemoryRecordModel.deleted.is_(False),
                )
                .values(
                    access_count=LongTermMemoryRecordModel.access_count + 1,
                    updated_at=_now_ts(),
                )
            )

    async def get_storage_dir(self) -> str:
        """返回记忆存储路径（兼容接口）。

        对于 SQLite，返回数据库文件路径；对于内存数据库或其他后端，返回连接 URL。
        """
        from src.infrastructure.db.engine import get_engine

        engine = get_engine()
        url = engine.url
        if url.get_backend_name() == "sqlite":
            db = url.database
            if db and db != ":memory:":
                return str(db)
        return str(url)

    # ============================================================
    # 内部：索引重建
    # ============================================================

    async def _rebuild_index(
        self,
        session: AsyncSession,
        device_id: str,
    ) -> None:
        """重建 summary_labels + keyword_index 两张索引表。

        1. 加载设备全部活跃记忆（deleted=False）
        2. 删除该设备的旧索引记录
        3. 从活跃记忆的 tags[:3] 重建 summary_labels（含 ref_count）
        4. 从活跃记忆的 keywords 重建 keyword_index（同条记忆内去重）
        """
        # 1. 加载活跃记忆
        result = await session.execute(
            select(LongTermMemoryRecordModel).where(
                LongTermMemoryRecordModel.device_id == device_id,
                LongTermMemoryRecordModel.deleted.is_(False),
            )
        )
        active = result.scalars().all()

        # 2. 删除旧索引
        await session.execute(
            delete(LongTermMemorySummaryLabelModel).where(
                LongTermMemorySummaryLabelModel.device_id == device_id
            )
        )
        await session.execute(
            delete(LongTermMemoryKeywordIndexModel).where(
                LongTermMemoryKeywordIndexModel.device_id == device_id
            )
        )

        # 3. 重建 summary_labels（tags[:3] 聚合 + ref_count）
        #    使用 Core INSERT ... ON CONFLICT DO UPDATE，避免并发重建时的唯一约束冲突
        label_counts: dict[str, int] = {}
        for rec in active:
            for tag in (rec.tags or [])[:3]:
                label_counts[tag] = label_counts.get(tag, 0) + 1
        for label, count in label_counts.items():
            stmt = sqlite_insert(LongTermMemorySummaryLabelModel).values(
                device_id=device_id,
                label=label,
                ref_count=count,
            ).on_conflict_do_update(
                index_elements=["device_id", "label"],
                set_={"ref_count": count},
            )
            await session.execute(stmt)

        # 4. 重建 keyword_index（同条记忆内关键词去重，避免唯一约束冲突）
        #    使用 Core INSERT ... ON CONFLICT DO NOTHING，并发时跳过已存在的条目
        for rec in active:
            seen: set[str] = set()
            for kw in (rec.keywords or []):
                if kw in seen:
                    continue
                seen.add(kw)
                stmt = sqlite_insert(LongTermMemoryKeywordIndexModel).values(
                    device_id=device_id,
                    keyword=kw,
                    memory_id=rec.memory_id,
                ).on_conflict_do_nothing(
                    index_elements=["device_id", "keyword", "memory_id"],
                )
                await session.execute(stmt)


__all__ = ["SqlLongTermMemoryRepository"]
