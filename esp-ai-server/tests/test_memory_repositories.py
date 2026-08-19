"""记忆仓储 SQL 实现单元测试

覆盖：
- ``SqlShortTermMemoryRepository``：CRUD + 排序 + 批量保存 + 设备隔离
- ``SqlLongTermMemoryRepository``：save + find_by_labels + find_all + find_by_id +
  mark_deleted + increment_access + get_summary_labels + 索引重建 + 并发保存

使用内存 SQLite（sqlite+aiosqlite:///:memory: + StaticPool），
参考 ``tests/test_device_repository.py`` 的夹具模式（通过 monkeypatch 覆盖全局 session factory）。
"""
from __future__ import annotations

import asyncio
import time

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.domain.entities import MemoryItem
from src.infrastructure.db.base import Base
from src.infrastructure.db.models.memory import (
    LongTermMemoryKeywordIndexModel,
    LongTermMemoryRecordModel,
    LongTermMemorySummaryLabelModel,
    ShortTermMemoryModel,
)
from src.infrastructure.db.repositories.ltm_repository import SqlLongTermMemoryRepository
from src.infrastructure.db.repositories.short_term_memory_repo import (
    SqlShortTermMemoryRepository,
)
from src.infrastructure.db.session import get_session_ctx


# ============================================================
# 辅助函数
# ============================================================

def _make_item(
    memory_id: str = "mem-1",
    device_id: str = "dev1",
    content: str = "hello",
    tags: list[str] | None = None,
    keywords: list[str] | None = None,
    access_count: int = 0,
    deleted: bool = False,
    source: str = "manual",
) -> MemoryItem:
    """构造 MemoryItem 辅助函数"""
    return MemoryItem(
        memory_id=memory_id,
        device_id=device_id,
        content=content,
        tags=tags or [],
        keywords=keywords or [],
        access_count=access_count,
        deleted=deleted,
        source=source,
    )


def _make_message(
    role: str = "user",
    content: str = "hello",
    timestamp: float | None = None,
    datetime_str: str | None = None,
) -> dict:
    """构造短期记忆消息 dict（格式与 ConversationMemory.add_message 一致）"""
    ts = timestamp if timestamp is not None else time.time()
    dt = datetime_str or time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    return {
        "role": role,
        "content": content,
        "timestamp": ts,
        "datetime": dt,
    }


# ============================================================
# 短期记忆夹具（同步）
# ============================================================

@pytest.fixture
def stm_repo(monkeypatch):
    """SqlShortTermMemoryRepository（同步，覆盖全局 sync session factory）

    使用 :memory: + StaticPool，单连接复用保证写入与读取在同一内存 DB。
    """
    sync_engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        future=True,
        poolclass=StaticPool,
    )
    Base.metadata.create_all(sync_engine)
    sync_factory = sessionmaker(
        bind=sync_engine, class_=Session, expire_on_commit=False, autoflush=False,
    )
    import src.infrastructure.db.compat.sync_session as sync_mod
    monkeypatch.setattr(sync_mod, "_sync_engine", sync_engine)
    monkeypatch.setattr(sync_mod, "_sync_session_factory", sync_factory)
    yield SqlShortTermMemoryRepository()
    sync_engine.dispose()


# ============================================================
# 长期记忆夹具（异步）
# ============================================================

@pytest_asyncio.fixture
async def ltm_repo(monkeypatch):
    """SqlLongTermMemoryRepository（异步，覆盖全局 async session factory）"""
    async_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        poolclass=StaticPool,
    )
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_factory = async_sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    import src.infrastructure.db.engine as engine_mod
    monkeypatch.setattr(engine_mod, "_async_engine", async_engine)
    monkeypatch.setattr(engine_mod, "_async_session_factory", async_factory)
    yield SqlLongTermMemoryRepository()
    await async_engine.dispose()


# ============================================================
# 短期记忆测试：CRUD + 排序 + 批量保存
# ============================================================

class TestShortTermMemoryCRUD:
    """SqlShortTermMemoryRepository 基本 CRUD"""

    def test_load_empty(self, stm_repo):
        """加载不存在的设备返回空列表"""
        assert stm_repo.load("dev1") == []

    def test_load_empty_device_id(self, stm_repo):
        """空 device_id 返回空列表"""
        assert stm_repo.load("") == []

    def test_save_and_load(self, stm_repo):
        """保存后能加载"""
        messages = [
            _make_message("user", "hello", timestamp=1.0, datetime_str="2025-01-01 00:00:01"),
            _make_message("assistant", "hi", timestamp=2.0, datetime_str="2025-01-01 00:00:02"),
        ]
        stm_repo.save("dev1", messages)
        loaded = stm_repo.load("dev1")
        assert len(loaded) == 2
        assert loaded[0]["role"] == "user"
        assert loaded[0]["content"] == "hello"
        assert loaded[0]["timestamp"] == 1.0
        assert loaded[0]["datetime"] == "2025-01-01 00:00:01"
        assert loaded[1]["role"] == "assistant"
        assert loaded[1]["content"] == "hi"

    def test_save_preserves_message_format(self, stm_repo):
        """返回的消息格式与原 JSON 一致：[{role, content, timestamp, datetime}]"""
        messages = [
            _make_message("user", "test", timestamp=123.456, datetime_str="2025-06-01 12:00:00")
        ]
        stm_repo.save("dev1", messages)
        loaded = stm_repo.load("dev1")
        assert len(loaded) == 1
        msg = loaded[0]
        assert set(msg.keys()) == {"role", "content", "timestamp", "datetime"}
        assert msg["role"] == "user"
        assert msg["content"] == "test"
        assert msg["timestamp"] == 123.456
        assert msg["datetime"] == "2025-06-01 12:00:00"

    def test_save_empty_messages(self, stm_repo):
        """保存空消息列表"""
        stm_repo.save("dev1", [])
        assert stm_repo.load("dev1") == []

    def test_save_empty_device_id(self, stm_repo):
        """空 device_id 不执行操作"""
        stm_repo.save("", [_make_message()])
        # 不应报错

    def test_save_overwrites_existing(self, stm_repo):
        """保存会覆盖旧消息（DELETE + INSERT）"""
        stm_repo.save("dev1", [_make_message("user", "old", timestamp=1.0)])
        stm_repo.save("dev1", [_make_message("user", "new", timestamp=2.0)])
        loaded = stm_repo.load("dev1")
        assert len(loaded) == 1
        assert loaded[0]["content"] == "new"

    def test_save_replaces_all_messages(self, stm_repo):
        """保存完全替换旧消息（不是追加）"""
        stm_repo.save("dev1", [
            _make_message("user", "msg1", timestamp=1.0),
            _make_message("assistant", "msg2", timestamp=2.0),
            _make_message("user", "msg3", timestamp=3.0),
        ])
        # 保存更短的列表
        stm_repo.save("dev1", [_make_message("user", "only", timestamp=4.0)])
        loaded = stm_repo.load("dev1")
        assert len(loaded) == 1
        assert loaded[0]["content"] == "only"

    def test_delete(self, stm_repo):
        """删除设备所有消息"""
        stm_repo.save("dev1", [_make_message("user", "hello", timestamp=1.0)])
        stm_repo.delete("dev1")
        assert stm_repo.load("dev1") == []

    def test_delete_nonexistent_no_error(self, stm_repo):
        """删除不存在的设备不报错"""
        stm_repo.delete("never-existed")

    def test_delete_empty_device_id(self, stm_repo):
        """空 device_id 不执行删除"""
        stm_repo.delete("")

    def test_save_load_roundtrip(self, stm_repo):
        """保存 → 加载往返保持数据完整"""
        messages = [
            _make_message("system", "system prompt", timestamp=1.0,
                          datetime_str="2025-01-01 00:00:01"),
            _make_message("user", "你好", timestamp=2.0,
                          datetime_str="2025-01-01 00:00:02"),
            _make_message("assistant", "你好！", timestamp=3.0,
                          datetime_str="2025-01-01 00:00:03"),
        ]
        stm_repo.save("dev1", messages)
        loaded = stm_repo.load("dev1")
        assert loaded == messages

    def test_save_messages_without_timestamp(self, stm_repo):
        """保存不含 timestamp 的消息时使用默认值"""
        messages = [{"role": "user", "content": "no-ts"}]
        stm_repo.save("dev1", messages)
        loaded = stm_repo.load("dev1")
        assert len(loaded) == 1
        assert loaded[0]["role"] == "user"
        assert loaded[0]["content"] == "no-ts"
        assert loaded[0]["timestamp"] > 0
        assert len(loaded[0]["datetime"]) > 0

    def test_save_messages_without_datetime(self, stm_repo):
        """保存不含 datetime 的消息时从 timestamp 生成"""
        messages = [{"role": "user", "content": "no-dt", "timestamp": 1000.0}]
        stm_repo.save("dev1", messages)
        loaded = stm_repo.load("dev1")
        assert len(loaded) == 1
        assert loaded[0]["datetime"] == time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(1000.0))


class TestShortTermMemoryOrdering:
    """短期记忆排序测试"""

    def test_ordering_by_seq(self, stm_repo):
        """消息按 seq（插入顺序）排序，不是按 timestamp"""
        messages = [
            _make_message("user", "first", timestamp=3.0),
            _make_message("assistant", "second", timestamp=1.0),
            _make_message("user", "third", timestamp=2.0),
        ]
        stm_repo.save("dev1", messages)
        loaded = stm_repo.load("dev1")
        # 按 seq（列表索引）排序
        assert loaded[0]["content"] == "first"
        assert loaded[1]["content"] == "second"
        assert loaded[2]["content"] == "third"


class TestShortTermMemoryBatch:
    """短期记忆批量保存测试"""

    def test_batch_save_large(self, stm_repo):
        """批量保存大量消息"""
        messages = [
            _make_message("user", f"msg-{i}", timestamp=float(i)) for i in range(100)
        ]
        stm_repo.save("dev1", messages)
        loaded = stm_repo.load("dev1")
        assert len(loaded) == 100
        for i, msg in enumerate(loaded):
            assert msg["content"] == f"msg-{i}"
            assert msg["timestamp"] == float(i)

    def test_batch_save_then_overwrite_with_smaller(self, stm_repo):
        """批量保存后用更小的列表覆盖"""
        stm_repo.save("dev1", [
            _make_message("user", f"msg-{i}", timestamp=float(i)) for i in range(50)
        ])
        stm_repo.save("dev1", [
            _make_message("user", "new", timestamp=99.0)
        ])
        loaded = stm_repo.load("dev1")
        assert len(loaded) == 1
        assert loaded[0]["content"] == "new"


class TestShortTermMemoryIsolation:
    """短期记忆设备隔离测试"""

    def test_device_isolation(self, stm_repo):
        """不同设备的消息隔离"""
        stm_repo.save("dev1", [_make_message("user", "dev1-msg", timestamp=1.0)])
        stm_repo.save("dev2", [_make_message("user", "dev2-msg", timestamp=2.0)])
        assert len(stm_repo.load("dev1")) == 1
        assert len(stm_repo.load("dev2")) == 1
        assert stm_repo.load("dev1")[0]["content"] == "dev1-msg"
        assert stm_repo.load("dev2")[0]["content"] == "dev2-msg"

    def test_delete_one_device_preserves_others(self, stm_repo):
        """删除一个设备的消息不影响其他设备"""
        stm_repo.save("dev1", [_make_message("user", "dev1-msg", timestamp=1.0)])
        stm_repo.save("dev2", [_make_message("user", "dev2-msg", timestamp=2.0)])
        stm_repo.delete("dev1")
        assert stm_repo.load("dev1") == []
        assert len(stm_repo.load("dev2")) == 1

    def test_save_one_device_preserves_others(self, stm_repo):
        """保存一个设备的消息不影响其他设备"""
        stm_repo.save("dev1", [_make_message("user", "dev1-msg", timestamp=1.0)])
        stm_repo.save("dev2", [_make_message("user", "dev2-msg", timestamp=2.0)])
        # 重新保存 dev1
        stm_repo.save("dev1", [_make_message("user", "dev1-new", timestamp=3.0)])
        assert len(stm_repo.load("dev1")) == 1
        assert stm_repo.load("dev1")[0]["content"] == "dev1-new"
        # dev2 不受影响
        assert len(stm_repo.load("dev2")) == 1
        assert stm_repo.load("dev2")[0]["content"] == "dev2-msg"


# ============================================================
# 长期记忆测试：save + find_by_id + find_all
# ============================================================

class TestLongTermMemorySave:
    """SqlLongTermMemoryRepository save + find 测试"""

    async def test_save_and_find_by_id(self, ltm_repo):
        """保存后能按 ID 查找"""
        item = _make_item(
            memory_id="mem-1", content="fact A", tags=["work"], keywords=["k1"]
        )
        await ltm_repo.save(item)
        found = await ltm_repo.find_by_id("mem-1", "dev1")
        assert found is not None
        assert found.memory_id == "mem-1"
        assert found.content == "fact A"
        assert found.tags == ["work"]
        assert found.keywords == ["k1"]
        assert found.deleted is False

    async def test_find_by_id_not_found(self, ltm_repo):
        """查找不存在的记忆返回 None"""
        assert await ltm_repo.find_by_id("nope", "dev1") is None

    async def test_find_by_id_empty_args(self, ltm_repo):
        """空参数返回 None"""
        assert await ltm_repo.find_by_id("", "dev1") is None
        assert await ltm_repo.find_by_id("m1", "") is None

    async def test_find_by_id_excludes_deleted(self, ltm_repo):
        """find_by_id 不返回已删除的记忆"""
        await ltm_repo.save(_make_item(memory_id="mem-1", content="fact A"))
        await ltm_repo.mark_deleted("mem-1", "dev1")
        assert await ltm_repo.find_by_id("mem-1", "dev1") is None

    async def test_save_upsert(self, ltm_repo):
        """save 同一 memory_id 执行 UPSERT（更新而非插入）"""
        item1 = _make_item(memory_id="mem-1", content="v1", access_count=0)
        await ltm_repo.save(item1)
        item2 = _make_item(memory_id="mem-1", content="v2", access_count=5)
        await ltm_repo.save(item2)
        found = await ltm_repo.find_by_id("mem-1", "dev1")
        assert found is not None
        assert found.content == "v2"
        assert found.access_count == 5
        # 只有一行记录
        all_items = await ltm_repo.find_all("dev1")
        assert len(all_items) == 1

    async def test_save_preserves_created_at_on_update(self, ltm_repo):
        """UPSERT 更新时 created_at 保留原值"""
        item1 = _make_item(memory_id="mem-1", content="v1")
        item1.created_at = 1000.0
        item1.updated_at = 1000.0
        await ltm_repo.save(item1)

        time.sleep(0.02)
        item2 = _make_item(memory_id="mem-1", content="v2")
        item2.created_at = 2000.0  # 尝试覆盖
        await ltm_repo.save(item2)

        found = await ltm_repo.find_by_id("mem-1", "dev1")
        assert found is not None
        # created_at 保留原值（1000.0），不被覆盖
        assert found.created_at == 1000.0
        # updated_at 被刷新
        assert found.updated_at > 1000.0

    async def test_save_empty_memory_id_skipped(self, ltm_repo):
        """空 memory_id 或 device_id 不执行操作"""
        item = _make_item(memory_id="", content="x")
        await ltm_repo.save(item)
        assert await ltm_repo.find_all("dev1") == []

    async def test_find_all_returns_active_sorted(self, ltm_repo):
        """find_all 返回活跃记忆，按 access_count 降序"""
        await ltm_repo.save(_make_item(memory_id="m1", access_count=1))
        await ltm_repo.save(_make_item(memory_id="m2", access_count=5))
        await ltm_repo.save(_make_item(memory_id="m3", access_count=3))
        results = await ltm_repo.find_all("dev1")
        assert len(results) == 3
        assert results[0].memory_id == "m2"
        assert results[1].memory_id == "m3"
        assert results[2].memory_id == "m1"

    async def test_find_all_excludes_deleted(self, ltm_repo):
        """find_all 不返回已删除的记忆"""
        await ltm_repo.save(_make_item(memory_id="m1"))
        await ltm_repo.save(_make_item(memory_id="m2"))
        await ltm_repo.mark_deleted("m1", "dev1")
        results = await ltm_repo.find_all("dev1")
        assert len(results) == 1
        assert results[0].memory_id == "m2"

    async def test_find_all_empty(self, ltm_repo):
        """空设备返回空列表"""
        assert await ltm_repo.find_all("dev1") == []

    async def test_find_all_empty_device_id(self, ltm_repo):
        """空 device_id 返回空列表"""
        assert await ltm_repo.find_all("") == []

    async def test_find_all_device_isolation(self, ltm_repo):
        """不同设备的记忆隔离"""
        await ltm_repo.save(_make_item(memory_id="m1", device_id="dev1"))
        await ltm_repo.save(_make_item(memory_id="m2", device_id="dev2"))
        assert len(await ltm_repo.find_all("dev1")) == 1
        assert len(await ltm_repo.find_all("dev2")) == 1


# ============================================================
# 长期记忆测试：find_by_labels
# ============================================================

class TestLongTermMemoryFindByLabels:
    """find_by_labels 测试"""

    async def test_find_by_labels_filters_by_tag(self, ltm_repo):
        """按标签过滤"""
        await ltm_repo.save(_make_item(memory_id="m1", tags=["work"]))
        await ltm_repo.save(_make_item(memory_id="m2", tags=["home"]))
        await ltm_repo.save(_make_item(memory_id="m3", tags=["work", "urgent"]))
        results = await ltm_repo.find_by_labels("dev1", ("work",), limit=10)
        ids = {r.memory_id for r in results}
        assert ids == {"m1", "m3"}

    async def test_find_by_labels_empty_returns_all_active(self, ltm_repo):
        """空标签返回所有活跃记忆"""
        await ltm_repo.save(_make_item(memory_id="m1", tags=["work"]))
        await ltm_repo.save(_make_item(memory_id="m2", tags=["home"]))
        results = await ltm_repo.find_by_labels("dev1", (), limit=10)
        assert len(results) == 2

    async def test_find_by_labels_limit(self, ltm_repo):
        """limit 限制返回数量，按 access_count 降序"""
        for i in range(5):
            await ltm_repo.save(
                _make_item(memory_id=f"m{i}", tags=["work"], access_count=i)
            )
        results = await ltm_repo.find_by_labels("dev1", ("work",), limit=2)
        assert len(results) == 2
        assert results[0].memory_id == "m4"
        assert results[1].memory_id == "m3"

    async def test_find_by_labels_limit_zero_uses_default_8(self, ltm_repo):
        """limit=0 时取默认 8"""
        for i in range(10):
            await ltm_repo.save(_make_item(memory_id=f"m{i}", tags=["work"]))
        results = await ltm_repo.find_by_labels("dev1", ("work",), limit=0)
        assert len(results) == 8

    async def test_find_by_labels_excludes_deleted(self, ltm_repo):
        """find_by_labels 不返回已删除的记忆"""
        await ltm_repo.save(_make_item(memory_id="m1", tags=["work"]))
        await ltm_repo.save(_make_item(memory_id="m2", tags=["work"]))
        await ltm_repo.mark_deleted("m1", "dev1")
        results = await ltm_repo.find_by_labels("dev1", ("work",), limit=10)
        ids = {r.memory_id for r in results}
        assert ids == {"m2"}

    async def test_find_by_labels_matches_any_tag(self, ltm_repo):
        """标签匹配记录的任意 tag（不仅是前 3 个，与 JSON 实现一致）"""
        await ltm_repo.save(_make_item(memory_id="m1", tags=["a", "b", "c", "d"]))
        # 按 "d" 查询应能找到（即使 d 不在 summary_labels 中）
        results = await ltm_repo.find_by_labels("dev1", ("d",), limit=10)
        assert len(results) == 1
        assert results[0].memory_id == "m1"

    async def test_find_by_labels_sorted_by_access_count(self, ltm_repo):
        """结果按 access_count 降序"""
        await ltm_repo.save(_make_item(memory_id="m1", tags=["work"], access_count=1))
        await ltm_repo.save(_make_item(memory_id="m2", tags=["work"], access_count=10))
        await ltm_repo.save(_make_item(memory_id="m3", tags=["work"], access_count=5))
        results = await ltm_repo.find_by_labels("dev1", ("work",), limit=10)
        assert [r.memory_id for r in results] == ["m2", "m3", "m1"]

    async def test_find_by_labels_empty_device_id(self, ltm_repo):
        """空 device_id 返回空列表"""
        assert await ltm_repo.find_by_labels("", ("work",), limit=10) == []

    async def test_find_by_labels_multiple_labels(self, ltm_repo):
        """多个标签取并集"""
        await ltm_repo.save(_make_item(memory_id="m1", tags=["work"]))
        await ltm_repo.save(_make_item(memory_id="m2", tags=["home"]))
        await ltm_repo.save(_make_item(memory_id="m3", tags=["other"]))
        results = await ltm_repo.find_by_labels("dev1", ("work", "home"), limit=10)
        ids = {r.memory_id for r in results}
        assert ids == {"m1", "m2"}


# ============================================================
# 长期记忆测试：mark_deleted + increment_access
# ============================================================

class TestLongTermMemoryDeleteAndAccess:
    """mark_deleted + increment_access 测试"""

    async def test_mark_deleted(self, ltm_repo):
        """软删除记忆"""
        await ltm_repo.save(_make_item(memory_id="m1"))
        await ltm_repo.mark_deleted("m1", "dev1")
        assert await ltm_repo.find_by_id("m1", "dev1") is None
        assert await ltm_repo.find_all("dev1") == []

    async def test_mark_deleted_nonexistent_no_error(self, ltm_repo):
        """删除不存在的记忆不报错"""
        await ltm_repo.mark_deleted("nope", "dev1")

    async def test_mark_deleted_empty_args(self, ltm_repo):
        """空参数不执行操作"""
        await ltm_repo.mark_deleted("", "dev1")
        await ltm_repo.mark_deleted("m1", "")

    async def test_mark_deleted_rebuilds_index(self, ltm_repo):
        """删除后重建索引（标签消失）"""
        await ltm_repo.save(_make_item(memory_id="m1", tags=["work"]))
        labels_before = await ltm_repo.get_summary_labels("dev1")
        assert "work" in labels_before
        await ltm_repo.mark_deleted("m1", "dev1")
        labels_after = await ltm_repo.get_summary_labels("dev1")
        assert "work" not in labels_after

    async def test_mark_deleted_preserves_other_records(self, ltm_repo):
        """删除一条记忆不影响其他记忆"""
        await ltm_repo.save(_make_item(memory_id="m1", content="fact A"))
        await ltm_repo.save(_make_item(memory_id="m2", content="fact B"))
        await ltm_repo.mark_deleted("m1", "dev1")
        results = await ltm_repo.find_all("dev1")
        assert len(results) == 1
        assert results[0].memory_id == "m2"

    async def test_increment_access(self, ltm_repo):
        """增加访问计数"""
        await ltm_repo.save(_make_item(memory_id="m1", access_count=2))
        await ltm_repo.increment_access("m1", "dev1")
        found = await ltm_repo.find_by_id("m1", "dev1")
        assert found.access_count == 3

    async def test_increment_access_nonexistent_no_error(self, ltm_repo):
        """增加不存在的记忆的访问计数不报错"""
        await ltm_repo.increment_access("nope", "dev1")

    async def test_increment_access_empty_args(self, ltm_repo):
        """空参数不执行操作"""
        await ltm_repo.increment_access("", "dev1")
        await ltm_repo.increment_access("m1", "")

    async def test_increment_access_skips_deleted(self, ltm_repo):
        """已删除的记忆不增加访问计数"""
        await ltm_repo.save(_make_item(memory_id="m1", access_count=2))
        await ltm_repo.mark_deleted("m1", "dev1")
        await ltm_repo.increment_access("m1", "dev1")
        # 直接查询 DB 验证 access_count 未变（find_by_id 返回 None 因为已删除）
        async with get_session_ctx() as session:
            result = await session.execute(
                select(LongTermMemoryRecordModel).where(
                    LongTermMemoryRecordModel.memory_id == "m1"
                )
            )
            model = result.scalar_one()
            assert model.access_count == 2

    async def test_increment_access_multiple(self, ltm_repo):
        """多次增加访问计数"""
        await ltm_repo.save(_make_item(memory_id="m1", access_count=0))
        for _ in range(5):
            await ltm_repo.increment_access("m1", "dev1")
        found = await ltm_repo.find_by_id("m1", "dev1")
        assert found.access_count == 5

    async def test_increment_access_affects_sort_order(self, ltm_repo):
        """增加访问计数后影响 find_all 排序"""
        await ltm_repo.save(_make_item(memory_id="m1", access_count=1))
        await ltm_repo.save(_make_item(memory_id="m2", access_count=0))
        # m1 access_count=1, m2 access_count=0 → m1 在前
        results = await ltm_repo.find_all("dev1")
        assert results[0].memory_id == "m1"
        # 增加 m2 的访问计数 3 次
        for _ in range(3):
            await ltm_repo.increment_access("m2", "dev1")
        # m2 access_count=3 > m1 access_count=1 → m2 在前
        results = await ltm_repo.find_all("dev1")
        assert results[0].memory_id == "m2"


# ============================================================
# 长期记忆测试：索引重建
# ============================================================

class TestLongTermMemoryIndex:
    """索引重建测试（summary_labels + keyword_index）"""

    async def test_summary_labels_built_on_save(self, ltm_repo):
        """保存时自动构建摘要标签"""
        await ltm_repo.save(_make_item(memory_id="m1", tags=["work", "urgent"]))
        await ltm_repo.save(_make_item(memory_id="m2", tags=["home"]))
        labels = await ltm_repo.get_summary_labels("dev1")
        assert set(labels) == {"work", "urgent", "home"}

    async def test_summary_labels_ref_count(self, ltm_repo):
        """摘要标签的 ref_count 正确（多个记忆共享同一标签）"""
        await ltm_repo.save(_make_item(memory_id="m1", tags=["work"]))
        await ltm_repo.save(_make_item(memory_id="m2", tags=["work"]))
        await ltm_repo.save(_make_item(memory_id="m3", tags=["home"]))
        async with get_session_ctx() as session:
            result = await session.execute(
                select(LongTermMemorySummaryLabelModel).where(
                    LongTermMemorySummaryLabelModel.device_id == "dev1"
                )
            )
            labels = {r.label: r.ref_count for r in result.scalars().all()}
        assert labels.get("work") == 2
        assert labels.get("home") == 1

    async def test_summary_labels_tags_capped_at_three(self, ltm_repo):
        """摘要标签只取 tags 前 3 个"""
        await ltm_repo.save(
            _make_item(memory_id="m1", tags=["a", "b", "c", "d", "e"])
        )
        labels = await ltm_repo.get_summary_labels("dev1")
        assert set(labels) == {"a", "b", "c"}

    async def test_summary_labels_empty(self, ltm_repo):
        """无记忆时标签为空"""
        assert await ltm_repo.get_summary_labels("dev1") == []

    async def test_summary_labels_empty_device_id(self, ltm_repo):
        """空 device_id 返回空列表"""
        assert await ltm_repo.get_summary_labels("") == []

    async def test_summary_labels_device_isolation(self, ltm_repo):
        """不同设备的标签隔离"""
        await ltm_repo.save(_make_item(memory_id="m1", device_id="dev1", tags=["work"]))
        await ltm_repo.save(_make_item(memory_id="m2", device_id="dev2", tags=["home"]))
        assert set(await ltm_repo.get_summary_labels("dev1")) == {"work"}
        assert set(await ltm_repo.get_summary_labels("dev2")) == {"home"}

    async def test_keyword_index_built_on_save(self, ltm_repo):
        """保存时自动构建关键词倒排索引"""
        await ltm_repo.save(_make_item(memory_id="m1", keywords=["k1", "k2"]))
        await ltm_repo.save(_make_item(memory_id="m2", keywords=["k1", "k3"]))
        async with get_session_ctx() as session:
            result = await session.execute(
                select(LongTermMemoryKeywordIndexModel).where(
                    LongTermMemoryKeywordIndexModel.device_id == "dev1"
                )
            )
            entries = result.scalars().all()
        # 构建 keyword -> set(memory_id) 映射
        kw_map: dict[str, set[str]] = {}
        for e in entries:
            kw_map.setdefault(e.keyword, set()).add(e.memory_id)
        assert kw_map["k1"] == {"m1", "m2"}
        assert kw_map["k2"] == {"m1"}
        assert kw_map["k3"] == {"m2"}

    async def test_keyword_index_dedup_per_record(self, ltm_repo):
        """同一记忆的重复关键词去重（避免唯一约束冲突）"""
        await ltm_repo.save(_make_item(memory_id="m1", keywords=["k1", "k1", "k2"]))
        # 只要没报错就说明去重生效
        async with get_session_ctx() as session:
            result = await session.execute(
                select(LongTermMemoryKeywordIndexModel).where(
                    LongTermMemoryKeywordIndexModel.device_id == "dev1",
                    LongTermMemoryKeywordIndexModel.memory_id == "m1",
                )
            )
            entries = result.scalars().all()
        # k1 只出现一次（去重），k2 一次
        kws = {e.keyword for e in entries}
        assert kws == {"k1", "k2"}

    async def test_index_rebuilt_on_mark_deleted(self, ltm_repo):
        """删除记忆后索引重建（标签和关键词消失）"""
        await ltm_repo.save(
            _make_item(memory_id="m1", tags=["work"], keywords=["k1"])
        )
        await ltm_repo.save(
            _make_item(memory_id="m2", tags=["home"], keywords=["k2"])
        )
        await ltm_repo.mark_deleted("m1", "dev1")
        # 标签 work 应消失
        labels = await ltm_repo.get_summary_labels("dev1")
        assert "work" not in labels
        assert "home" in labels
        # 关键词 k1 应消失
        async with get_session_ctx() as session:
            result = await session.execute(
                select(LongTermMemoryKeywordIndexModel).where(
                    LongTermMemoryKeywordIndexModel.device_id == "dev1"
                )
            )
            entries = result.scalars().all()
        kws = {e.keyword for e in entries}
        assert "k1" not in kws
        assert "k2" in kws

    async def test_index_rebuilt_on_upsert(self, ltm_repo):
        """UPSERT 更新时索引重建（旧标签消失，新标签出现）"""
        item = _make_item(memory_id="m1", tags=["work"], keywords=["k1"])
        await ltm_repo.save(item)
        assert "work" in await ltm_repo.get_summary_labels("dev1")

        # 更新为不同标签
        item2 = _make_item(memory_id="m1", tags=["home"], keywords=["k2"])
        await ltm_repo.save(item2)
        labels = await ltm_repo.get_summary_labels("dev1")
        assert "work" not in labels
        assert "home" in labels

        # 关键词也重建
        async with get_session_ctx() as session:
            result = await session.execute(
                select(LongTermMemoryKeywordIndexModel).where(
                    LongTermMemoryKeywordIndexModel.device_id == "dev1"
                )
            )
            entries = result.scalars().all()
        kws = {e.keyword for e in entries}
        assert "k1" not in kws
        assert "k2" in kws

    async def test_index_ref_count_decreases_on_delete(self, ltm_repo):
        """删除一条记忆后，共享标签的 ref_count 递减"""
        await ltm_repo.save(_make_item(memory_id="m1", tags=["work"]))
        await ltm_repo.save(_make_item(memory_id="m2", tags=["work"]))
        # work 的 ref_count = 2
        async with get_session_ctx() as session:
            result = await session.execute(
                select(LongTermMemorySummaryLabelModel).where(
                    LongTermMemorySummaryLabelModel.device_id == "dev1",
                    LongTermMemorySummaryLabelModel.label == "work",
                )
            )
            assert result.scalar_one().ref_count == 2

        await ltm_repo.mark_deleted("m1", "dev1")
        # work 的 ref_count = 1
        async with get_session_ctx() as session:
            result = await session.execute(
                select(LongTermMemorySummaryLabelModel).where(
                    LongTermMemorySummaryLabelModel.device_id == "dev1",
                    LongTermMemorySummaryLabelModel.label == "work",
                )
            )
            assert result.scalar_one().ref_count == 1

    async def test_index_no_tags_no_keywords(self, ltm_repo):
        """无 tags 和 keywords 的记忆不产生索引条目"""
        await ltm_repo.save(_make_item(memory_id="m1", tags=[], keywords=[]))
        assert await ltm_repo.get_summary_labels("dev1") == []
        async with get_session_ctx() as session:
            result = await session.execute(
                select(LongTermMemoryKeywordIndexModel).where(
                    LongTermMemoryKeywordIndexModel.device_id == "dev1"
                )
            )
            assert result.scalars().all() == []


# ============================================================
# 长期记忆测试：get_storage_dir
# ============================================================

class TestLongTermMemoryStorageDir:
    """get_storage_dir 测试"""

    async def test_get_storage_dir_returns_string(self, ltm_repo):
        """返回非空字符串"""
        result = await ltm_repo.get_storage_dir()
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_get_storage_dir_memory_db(self, ltm_repo):
        """内存数据库返回 URL（包含 :memory:）"""
        result = await ltm_repo.get_storage_dir()
        assert ":memory:" in result or "sqlite" in result


# ============================================================
# 长期记忆测试：并发保存
# ============================================================

class TestLongTermMemoryConcurrent:
    """并发保存测试"""

    async def test_concurrent_saves_different_ids(self, ltm_repo):
        """并发保存不同 memory_id 的记忆，全部成功"""
        items = [
            _make_item(memory_id=f"m{i}", content=f"fact-{i}", tags=["work"])
            for i in range(5)
        ]
        await asyncio.gather(*[ltm_repo.save(item) for item in items])
        all_items = await ltm_repo.find_all("dev1")
        assert len(all_items) == 5
        ids = {item.memory_id for item in all_items}
        assert ids == {f"m{i}" for i in range(5)}

    async def test_concurrent_saves_same_id(self, ltm_repo):
        """并发保存同一 memory_id（不报错，最终只有一条记录）"""
        items = [
            _make_item(memory_id="m1", content=f"v{i}")
            for i in range(3)
        ]
        await asyncio.gather(*[ltm_repo.save(item) for item in items])
        all_items = await ltm_repo.find_all("dev1")
        assert len(all_items) == 1
        assert all_items[0].memory_id == "m1"
        assert all_items[0].content.startswith("v")

    async def test_concurrent_save_and_find(self, ltm_repo):
        """并发保存 + 查询不报错"""
        await ltm_repo.save(_make_item(memory_id="m1", content="initial"))

        async def save_and_check():
            await ltm_repo.save(_make_item(memory_id="m1", content="updated"))
            return await ltm_repo.find_by_id("m1", "dev1")

        results = await asyncio.gather(*[save_and_check() for _ in range(3)])
        for r in results:
            assert r is not None
            assert r.memory_id == "m1"

    async def test_concurrent_saves_different_devices(self, ltm_repo):
        """并发保存到不同设备"""
        items = [
            _make_item(memory_id=f"m{i}", device_id=f"dev{i}", content=f"fact-{i}")
            for i in range(4)
        ]
        await asyncio.gather(*[ltm_repo.save(item) for item in items])
        for i in range(4):
            results = await ltm_repo.find_all(f"dev{i}")
            assert len(results) == 1
            assert results[0].memory_id == f"m{i}"

    async def test_concurrent_increment_access(self, ltm_repo):
        """并发增加访问计数"""
        await ltm_repo.save(_make_item(memory_id="m1", access_count=0))
        await asyncio.gather(
            *[ltm_repo.increment_access("m1", "dev1") for _ in range(5)]
        )
        found = await ltm_repo.find_by_id("m1", "dev1")
        assert found.access_count == 5

    async def test_concurrent_save_then_find_all(self, ltm_repo):
        """并发保存后 find_all 返回全部"""
        # 先保存 5 条
        items = [
            _make_item(memory_id=f"m{i}", content=f"fact-{i}", tags=["work"])
            for i in range(5)
        ]
        await asyncio.gather(*[ltm_repo.save(item) for item in items])
        # 再并发保存 5 条
        items2 = [
            _make_item(memory_id=f"n{i}", content=f"fact-{i}", tags=["home"])
            for i in range(5)
        ]
        await asyncio.gather(*[ltm_repo.save(item) for item in items2])
        all_items = await ltm_repo.find_all("dev1")
        assert len(all_items) == 10
        # 索引也正确
        labels = set(await ltm_repo.get_summary_labels("dev1"))
        assert labels == {"work", "home"}
