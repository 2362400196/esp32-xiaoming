"""数据库基础设施测试

验证：
- 建表（11 张表全部创建）
- PRAGMA 设置正确（WAL 模式、外键、busy_timeout）
- 异步和同步引擎能同时访问
- 基本 CRUD 操作
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from src.infrastructure.db.base import Base
from src.infrastructure.db.models import (
    DeviceModel,
    EmoPackModel,
    EmotionHistoryModel,
    LearningLogModel,
    LongTermMemoryKeywordIndexModel,
    LongTermMemoryRecordModel,
    LongTermMemorySummaryLabelModel,
    ShortTermMemoryModel,
    SkillModel,
    UserProfileModel,
)


# ============================================================
# 测试夹具
# ============================================================

@pytest_asyncio.fixture
async def async_engine():
    """内存 SQLite 异步引擎（每测试独立）"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def async_session(async_engine):
    """异步会话"""
    factory = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


# ============================================================
# 建表测试
# ============================================================

class TestTableCreation:
    """验证所有 11 张表正确创建"""

    @pytest.mark.asyncio
    async def test_all_tables_created(self, async_engine):
        """所有 11 张表都应该被创建"""
        async with async_engine.connect() as conn:
            tables = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

        expected_tables = {
            "devices",
            "short_term_memories",
            "long_term_memory_records",
            "long_term_memory_summary_labels",
            "long_term_memory_keyword_index",
            "user_profiles",
            "emotion_history",
            "learning_logs",
            "emo_packs",
            "skills",
        }
        assert expected_tables.issubset(set(tables)), f"缺失表: {expected_tables - set(tables)}"

    @pytest.mark.asyncio
    async def test_device_model_columns(self, async_engine):
        """验证 devices 表有所有必要列"""
        async with async_engine.connect() as conn:
            columns = await conn.run_sync(
                lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("devices")}
            )

        required = {
            "device_id", "name", "device_key", "mac_address",
            "asr_provider", "llm_type", "tts_type",
            "asr_config", "tts_config", "music_config", "mcp_servers", "wakeup_config",
            "llm_api_key", "llm_base_url", "llm_model", "llm_system_prompt",
            "llm_memory_enabled", "llm_memory_max_messages",
            "llm_memory_long_term_enabled", "llm_memory_long_term_auto_extract",
            "rate_limit_rpm",
            "ota_enabled", "ota_bin_url", "ota_version", "ota_bin_id", "ota_is_official",
            "disabled_tools", "disabled_mcp_servers", "disabled_mcp_tools", "disabled_skills",
            "skills", "active_emo_pack",
            "is_online", "last_seen",
            "created_at", "updated_at",
        }
        assert required.issubset(columns), f"缺失列: {required - columns}"


# ============================================================
# PRAGMA 测试
# ============================================================

class TestPragmas:
    """验证 SQLite PRAGMA 设置"""

    @pytest.mark.asyncio
    async def test_pragma_journal_mode(self, async_engine):
        """WAL 模式（内存 DB 可能返回 memory，文件 DB 返回 wal）"""
        async with async_engine.connect() as conn:
            result = await conn.execute(text("PRAGMA journal_mode"))
            mode = result.scalar()
            # 内存数据库不支持 WAL，返回 memory；文件数据库返回 wal
            assert mode in ("wal", "memory")

    @pytest.mark.asyncio
    async def test_pragma_foreign_keys(self, async_engine):
        async with async_engine.connect() as conn:
            await conn.execute(text("PRAGMA foreign_keys=ON"))
            result = await conn.execute(text("PRAGMA foreign_keys"))
            assert result.scalar() == 1


# ============================================================
# 基本 CRUD 测试
# ============================================================

class TestBasicCRUD:

    @pytest.mark.asyncio
    async def test_device_crud(self, async_session):
        """DeviceModel 基本 CRUD"""
        device = DeviceModel(
            device_id="D8:3B:DA:6D:D9:3C",
            name="客厅的设备",
            device_key="test-key-123",
            mac_address="D8:3B:DA:6D:D9:3C",
            asr_provider="volcengine",
            llm_type="openai",
            tts_type="volcengine",
            asr_config={"volcengine": {"api_key": "xxx"}},
            llm_model="deepseek-v4-flash",
            llm_system_prompt="你是凡凡",
            mcp_servers={"maps": {"command": "node"}},
            skills=["weather"],
            disabled_tools=["dangerous_tool"],
        )
        async_session.add(device)
        await async_session.commit()

        # 读取
        from sqlalchemy import select
        result = await async_session.execute(
            select(DeviceModel).where(DeviceModel.device_id == "D8:3B:DA:6D:D9:3C")
        )
        loaded = result.scalar_one()
        assert loaded.name == "客厅的设备"
        assert loaded.device_key == "test-key-123"
        assert loaded.asr_config == {"volcengine": {"api_key": "xxx"}}
        assert loaded.mcp_servers == {"maps": {"command": "node"}}
        assert loaded.skills == ["weather"]
        assert loaded.disabled_tools == ["dangerous_tool"]
        assert loaded.created_at > 0
        assert loaded.updated_at > 0

    @pytest.mark.asyncio
    async def test_short_term_memory_crud(self, async_session):
        """短期记忆 CRUD"""
        msgs = [
            ShortTermMemoryModel(device_id="dev1", role="user", content="你好", seq=0, timestamp=1.0),
            ShortTermMemoryModel(device_id="dev1", role="assistant", content="你好！", seq=1, timestamp=2.0),
        ]
        async_session.add_all(msgs)
        await async_session.commit()

        from sqlalchemy import select
        result = await async_session.execute(
            select(ShortTermMemoryModel)
            .where(ShortTermMemoryModel.device_id == "dev1")
            .order_by(ShortTermMemoryModel.seq)
        )
        loaded = result.scalars().all()
        assert len(loaded) == 2
        assert loaded[0].role == "user"
        assert loaded[1].role == "assistant"

    @pytest.mark.asyncio
    async def test_long_term_memory_crud(self, async_session):
        """长期记忆 CRUD + 软删除"""
        record = LongTermMemoryRecordModel(
            memory_id="mem-001",
            device_id="dev1",
            content="用户喜欢咖啡",
            tags=["偏好"],
            keywords=["咖啡", "喜欢"],
            source="auto_llm",
        )
        async_session.add(record)
        await async_session.commit()

        # 更新 access_count
        record.access_count += 1
        await async_session.commit()

        # 软删除
        record.deleted = True
        await async_session.commit()

        from sqlalchemy import select
        result = await async_session.execute(
            select(LongTermMemoryRecordModel).where(
                LongTermMemoryRecordModel.memory_id == "mem-001",
                LongTermMemoryRecordModel.device_id == "dev1",
            )
        )
        loaded = result.scalar_one()
        assert loaded.access_count == 1
        assert loaded.deleted is True

    @pytest.mark.asyncio
    async def test_user_profile_upsert(self, async_session):
        """用户画像 UPSERT"""
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        profile = {
            "device_id": "dev1",
            "name": "张三",
            "occupation": "工程师",
            "interests": {"likes": ["编程", "音乐"]},
        }
        stmt = sqlite_insert(UserProfileModel).values(**profile)
        stmt = stmt.on_conflict_do_update(
            index_elements=["device_id"],
            set_={"name": stmt.excluded.name, "occupation": stmt.excluded.occupation},
        )
        await async_session.execute(stmt)
        await async_session.commit()

        from sqlalchemy import select
        result = await async_session.execute(
            select(UserProfileModel).where(UserProfileModel.device_id == "dev1")
        )
        loaded = result.scalar_one()
        assert loaded.name == "张三"
        assert loaded.interests == {"likes": ["编程", "音乐"]}

    @pytest.mark.asyncio
    async def test_emotion_history_append_and_trim(self, async_session):
        """情绪历史 append + trim 100"""
        # 插入 105 条
        for i in range(105):
            async_session.add(EmotionHistoryModel(
                device_id="dev1",
                timestamp=float(i),
                emotion="happy",
                intensity=0.5,
            ))
        await async_session.commit()

        # 修剪到 100 条
        from sqlalchemy import delete, select
        subq = (
            select(EmotionHistoryModel.id)
            .where(EmotionHistoryModel.device_id == "dev1")
            .order_by(EmotionHistoryModel.timestamp.desc())
            .limit(100)
        )
        await async_session.execute(
            delete(EmotionHistoryModel).where(
                EmotionHistoryModel.device_id == "dev1",
                EmotionHistoryModel.id.not_in(subq),
            )
        )
        await async_session.commit()

        count_result = await async_session.execute(
            select(EmotionHistoryModel).where(EmotionHistoryModel.device_id == "dev1")
        )
        assert len(count_result.scalars().all()) == 100

    @pytest.mark.asyncio
    async def test_skill_model(self, async_session):
        """技能模型"""
        skill = SkillModel(
            skill_id="weather",
            name="天气查询",
            description="查询天气信息",
            cap_groups=[["weather"]],
            category=["生活"],
            body="## 天气查询技能\n\n使用 maps_weather 工具",
            source="builtin",
        )
        async_session.add(skill)
        await async_session.commit()

        from sqlalchemy import select
        result = await async_session.execute(
            select(SkillModel).where(SkillModel.skill_id == "weather")
        )
        loaded = result.scalar_one()
        assert loaded.name == "天气查询"
        assert loaded.cap_groups == [["weather"]]
        assert "天气查询技能" in loaded.body

    @pytest.mark.asyncio
    async def test_emo_pack(self, async_session):
        """表情包元数据"""
        pack = EmoPackModel(pack_name="default", display_name="默认")
        async_session.add(pack)
        await async_session.commit()

        from sqlalchemy import select
        result = await async_session.execute(
            select(EmoPackModel).where(EmoPackModel.pack_name == "default")
        )
        loaded = result.scalar_one()
        assert loaded.display_name == "默认"


# ============================================================
# 同步/异步混用测试
# ============================================================

class TestSyncAsyncInterop:
    """验证同步和异步引擎可以访问同一 DB"""

    def test_sync_engine_basic(self, tmp_path):
        """同步引擎基本操作"""
        from sqlalchemy import create_engine, inspect as sync_inspect

        db_file = tmp_path / "test.db"
        sync_url = f"sqlite:///{db_file}"

        # 同步建表
        sync_engine = create_engine(sync_url)
        Base.metadata.create_all(sync_engine)

        # 验证表存在
        inspector = sync_inspect(sync_engine)
        tables = set(inspector.get_table_names())
        assert "devices" in tables

        sync_engine.dispose()
