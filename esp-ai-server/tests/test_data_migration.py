"""数据迁移脚本单元测试

覆盖 ``src/infrastructure/db/migrations/data_migration.py``：
- 空数据迁移（无 JSON 文件）
- users.json → devices 表
- 短期记忆迁移（memories/{id}.json → short_term_memories）
- 长期记忆迁移（memories/{id}/records.jsonl → long_term_memory_records，含合并逻辑）
- 用户画像 / 情绪历史 / 学习日志 / 表情包 / 技能迁移
- 幂等性（重复迁移不重复插入）
- ``--dry-run`` 模式（只报告不执行）
- ``--force`` 模式（强制重新迁移）

使用文件 SQLite（同步 + 异步引擎共享同一 DB 文件），
因为 ``SqlShortTermMemoryRepository.save()`` 使用同步会话。
"""
from __future__ import annotations

import json
import os
import time

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from src.infrastructure.db.base import Base
from src.infrastructure.db.models.device import DeviceModel
from src.infrastructure.db.models.emo import EmoPackModel
from src.infrastructure.db.models.growth import (
    EmotionHistoryModel,
    LearningLogModel,
    UserProfileModel,
)
from src.infrastructure.db.models.memory import (
    LongTermMemoryRecordModel,
    ShortTermMemoryModel,
)
from src.infrastructure.db.models.skill import SkillModel
from src.infrastructure.db.migrations.data_migration import (
    MigrationContext,
    MigrationReport,
    format_report,
    run_migration,
)


# ============================================================
# 辅助函数
# ============================================================


def _write_json(path: str, data: dict | list) -> None:
    """写入 JSON 文件（自动创建父目录）"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _write_jsonl(path: str, records: list[dict]) -> None:
    """写入 JSONL 文件（每行一个 JSON 对象）"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _write_skill_md(skill_dir: str, name: str, body: str = "skill body", **extra) -> str:
    """在指定目录写入 SKILL.md 文件，返回文件路径"""
    os.makedirs(skill_dir, exist_ok=True)
    frontmatter = {
        "name": name,
        "description": extra.get("description", f"{name} skill"),
        "author": extra.get("author", "tester"),
        "metadata": {
            "cap_groups": extra.get("cap_groups", []),
            "manage_mode": extra.get("manage_mode", "readonly"),
            "category": extra.get("category", []),
            "peripherals": extra.get("peripherals", []),
            "tags": extra.get("tags", []),
        },
    }
    if "source" in extra:
        frontmatter["metadata"]["source"] = extra["source"]
    content = (
        "---\n"
        + json.dumps(frontmatter, ensure_ascii=False, indent=2)
        + "\n---\n\n"
        + body
    )
    path = os.path.join(skill_dir, "SKILL.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _make_device_config(
    name: str = "测试设备",
    key: str = "test-key-123",
    **kwargs,
) -> dict:
    """构造设备配置 dict（与 users.json 中的格式一致）"""
    config = {
        "name": name,
        "key": key,
        "llm_type": "openai",
        "llm": {
            "api_key": "sk-test",
            "base_url": "https://api.test.com/v1",
            "model": "gpt-4",
            "system_prompt": "你是一个助手",
        },
        "tts_type": "volcengine",
        "tts_config": {"api_key": "tts-key", "voice_type": "zh_female_test"},
        "skills": ["test_ping"],
    }
    config.update(kwargs)
    return config


def _make_message(
    role: str = "user",
    content: str = "你好",
    timestamp: float | None = None,
) -> dict:
    """构造短期记忆消息 dict"""
    if timestamp is None:
        timestamp = time.time()
    return {
        "role": role,
        "content": content,
        "timestamp": timestamp,
        "datetime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp)),
    }


def _make_ltm_record(
    memory_id: str = "mem-test-001",
    device_id: str = "AA:BB:CC:DD:EE:FF",
    content: str = "用户喜欢咖啡",
    tags: list | None = None,
    keywords: list | None = None,
    source: str = "manual",
    access_count: int = 0,
    deleted: bool = False,
    updated_at: float | None = None,
) -> dict:
    """构造长期记忆记录 dict（与 records.jsonl 格式一致）"""
    if updated_at is None:
        updated_at = time.time()
    return {
        "memory_id": memory_id,
        "device_id": device_id,
        "content": content,
        "tags": tags or ["饮食偏好"],
        "keywords": keywords or ["咖啡"],
        "source": source,
        "created_at": updated_at,
        "updated_at": updated_at,
        "access_count": access_count,
        "deleted": deleted,
        "_timestamp": updated_at,
    }


# ============================================================
# DB 夹具（文件 SQLite，同步 + 异步共享）
# ============================================================


@pytest_asyncio.fixture
async def migration_db(tmp_path, monkeypatch):
    """文件 SQLite，同步和异步引擎共享同一 DB 文件。

    因为 ``SqlShortTermMemoryRepository.save()`` 使用同步会话，
    必须确保同步和异步引擎指向同一数据库文件。
    """
    db_file = tmp_path / "migration_test.db"

    # 同步引擎
    sync_engine = create_engine(
        f"sqlite:///{db_file}",
        echo=False,
        future=True,
    )
    Base.metadata.create_all(sync_engine)
    sync_factory = sessionmaker(
        bind=sync_engine, class_=Session, expire_on_commit=False, autoflush=False,
    )

    # 异步引擎（指向同一文件）
    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_file}",
        echo=False,
    )
    async_factory = async_sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )

    # 覆盖全局
    import src.infrastructure.db.engine as engine_mod
    monkeypatch.setattr(engine_mod, "_async_engine", async_engine)
    monkeypatch.setattr(engine_mod, "_async_session_factory", async_factory)

    import src.infrastructure.db.compat.sync_session as sync_mod
    monkeypatch.setattr(sync_mod, "_sync_engine", sync_engine)
    monkeypatch.setattr(sync_mod, "_sync_session_factory", sync_factory)

    yield {
        "async_engine": async_engine,
        "sync_engine": sync_engine,
        "db_file": db_file,
    }

    await async_engine.dispose()
    sync_engine.dispose()


# ============================================================
# 数据目录夹具
# ============================================================


@pytest.fixture
def empty_data_root(tmp_path):
    """空的项目根目录（无任何 JSON 数据文件）"""
    return tmp_path


@pytest.fixture
def full_data_root(tmp_path):
    """包含完整测试数据的项目根目录

    结构：
        {root}/
            users.json
            src/
                data/
                    memories/
                        dev1.json                      ← 短期记忆
                        dev1/records.jsonl             ← 长期记忆（含合并）
                    devices/
                        dev1_key/
                            profile/
                                user_profile.json
                                emotion_history.json
                            growth/
                                learning_log.json
                            skills/
                                custom_skill/SKILL.md
                emos/
                    packs/
                        test_pack/meta.json
                skills/
                    builtin_skill/SKILL.md
    """
    root = tmp_path

    # users.json（device_key="dev1_key" → mac="AA:BB:CC:DD:EE:FF"）
    _write_json(
        str(root / "users.json"),
        {
            "devices": {
                "AA:BB:CC:DD:EE:FF": _make_device_config(
                    name="测试设备1",
                    key="dev1_key",
                ),
            }
        },
    )

    # 短期记忆
    _write_json(
        str(root / "src" / "data" / "memories" / "dev1.json"),
        {
            "device_id": "AA:BB:CC:DD:EE:FF",
            "messages": [
                _make_message("user", "你好", 1000.0),
                _make_message("assistant", "你好呀", 1001.0),
                _make_message("user", "今天天气如何", 1002.0),
            ],
        },
    )

    # 长期记忆 records.jsonl（同一 memory_id 多条记录，测试合并）
    _write_jsonl(
        str(root / "src" / "data" / "memories" / "dev1" / "records.jsonl"),
        [
            _make_ltm_record(
                memory_id="mem-001",
                device_id="AA:BB:CC:DD:EE:FF",
                content="用户喜欢咖啡",
                keywords=["咖啡"],
                access_count=0,
                updated_at=1000.0,
            ),
            # 同一 memory_id 的更新记录（access_count 增加）
            _make_ltm_record(
                memory_id="mem-001",
                device_id="AA:BB:CC:DD:EE:FF",
                content="用户喜欢咖啡",
                keywords=["咖啡"],
                access_count=2,
                updated_at=2000.0,
            ),
            # 另一条记忆
            _make_ltm_record(
                memory_id="mem-002",
                device_id="AA:BB:CC:DD:EE:FF",
                content="用户的名字叫小明",
                tags=["用户信息"],
                keywords=["小明", "名字"],
                access_count=0,
                updated_at=1500.0,
            ),
        ],
    )

    # 用户画像
    _write_json(
        str(root / "src" / "data" / "devices" / "dev1_key" / "profile" / "user_profile.json"),
        {
            "device_id": "AA:BB:CC:DD:EE:FF",
            "name": "小明",
            "birthday": "1995-06-15",
            "occupation": "设计师",
            "family": ["老婆:小红"],
            "personality": {"mbti": "ENFP"},
            "interests": {"likes": ["咖啡", "音乐"], "dislikes": ["加班"]},
            "habits": {"sleep": "23:30"},
            "important_dates": [{"date": "06-15", "label": "生日"}],
            "current_state": {"last_emotion": "happy"},
        },
    )

    # 情绪历史
    _write_json(
        str(root / "src" / "data" / "devices" / "dev1_key" / "profile" / "emotion_history.json"),
        [
            {"timestamp": 1000.0, "emotion": "happy", "intensity": 0.8, "trigger": "收到礼物", "context": "对话中", "speaker": "user"},
            {"timestamp": 2000.0, "emotion": "sad", "intensity": 0.5, "trigger": "下雨", "context": "闲聊", "speaker": "user"},
        ],
    )

    # 学习日志
    _write_json(
        str(root / "src" / "data" / "devices" / "dev1_key" / "growth" / "learning_log.json"),
        [
            {"timestamp": 1000.0, "action": "create", "skill_name": "python_tips", "title": "Python技巧", "category": "编程"},
            {"timestamp": 2000.0, "action": "update", "skill_name": "python_tips", "title": "Python技巧v2", "category": "编程"},
        ],
    )

    # 表情包
    _write_json(
        str(root / "src" / "emos" / "packs" / "test_pack" / "meta.json"),
        {"display_name": "测试表情包", "version": "1.0"},
    )

    # 全局技能
    _write_skill_md(
        str(root / "src" / "skills" / "builtin_skill"),
        name="builtin_skill",
        body="这是一个内置技能",
    )

    # 设备自学习技能
    _write_skill_md(
        str(root / "src" / "data" / "devices" / "dev1_key" / "skills" / "custom_skill"),
        name="custom_skill",
        body="这是一个自定义技能",
        source="self_learning",
    )

    return root


# ============================================================
# 测试：空数据迁移
# ============================================================


class TestEmptyMigration:
    """测试空数据迁移（无 JSON 文件）"""

    @pytest.mark.asyncio
    async def test_empty_migration_no_errors(self, migration_db, empty_data_root):
        """空目录迁移不报错，所有表行数为 0"""
        reports = await run_migration(project_root=empty_data_root)

        assert len(reports) == 8  # 8 张表
        for r in reports:
            assert r.rows_before == 0
            assert r.rows_after == 0
            assert r.inserted == 0
            assert not r.skipped  # 空表不跳过

    @pytest.mark.asyncio
    async def test_empty_migration_warnings(self, migration_db, empty_data_root):
        """空目录迁移应产生 users.json 不存在的警告"""
        reports = await run_migration(project_root=empty_data_root)
        devices_report = next(r for r in reports if r.table == "devices")
        assert any("users.json" in w for w in devices_report.warnings)


# ============================================================
# 测试：devices 表迁移
# ============================================================


class TestDevicesMigration:
    """测试 users.json → devices 表"""

    @pytest.mark.asyncio
    async def test_devices_migrated(self, migration_db, full_data_root):
        """users.json 中的设备配置被正确迁移到 devices 表"""
        reports = await run_migration(project_root=full_data_root)

        devices_report = next(r for r in reports if r.table == "devices")
        assert devices_report.inserted == 1
        assert devices_report.rows_after == 1
        assert not devices_report.skipped

        # 验证数据内容
        async with migration_db["async_engine"].begin() as conn:
            result = await conn.execute(select(DeviceModel))
            rows = result.fetchall()
            assert len(rows) == 1
            device = rows[0]
            assert device.device_id == "AA:BB:CC:DD:EE:FF"
            assert device.name == "测试设备1"
            assert device.llm_type == "openai"

    @pytest.mark.asyncio
    async def test_devices_no_users_json(self, migration_db, empty_data_root):
        """users.json 不存在时，devices 表迁移产生警告但不报错"""
        reports = await run_migration(project_root=empty_data_root)
        devices_report = next(r for r in reports if r.table == "devices")
        assert devices_report.inserted == 0
        assert len(devices_report.warnings) > 0


# ============================================================
# 测试：短期记忆迁移
# ============================================================


class TestShortTermMemoriesMigration:
    """测试 memories/{id}.json → short_term_memories 表"""

    @pytest.mark.asyncio
    async def test_short_term_memories_migrated(self, migration_db, full_data_root):
        """短期记忆消息被正确迁移"""
        reports = await run_migration(project_root=full_data_root)

        stm_report = next(r for r in reports if r.table == "short_term_memories")
        assert stm_report.inserted == 3  # 3 条消息
        assert stm_report.rows_after == 3

        # 验证数据内容
        async with migration_db["async_engine"].begin() as conn:
            result = await conn.execute(
                select(ShortTermMemoryModel).order_by(ShortTermMemoryModel.seq)
            )
            rows = result.fetchall()
            assert len(rows) == 3
            assert rows[0].role == "user"
            assert rows[0].content == "你好"
            assert rows[1].role == "assistant"
            assert rows[2].content == "今天天气如何"


# ============================================================
# 测试：长期记忆迁移（含合并逻辑）
# ============================================================


class TestLongTermMemoriesMigration:
    """测试 memories/{id}/records.jsonl → long_term_memory_records 表"""

    @pytest.mark.asyncio
    async def test_ltm_merged_by_memory_id(self, migration_db, full_data_root):
        """同一 memory_id 的多条记录合并为一条（取最新状态）"""
        reports = await run_migration(project_root=full_data_root)

        ltm_report = next(r for r in reports if r.table == "long_term_memory_records")
        # records.jsonl 有 3 行，但 mem-001 出现 2 次 → 合并后 2 条
        assert ltm_report.inserted == 2
        assert ltm_report.rows_after == 2

        # 验证合并后的 access_count 取最新值
        async with migration_db["async_engine"].begin() as conn:
            result = await conn.execute(
                select(LongTermMemoryRecordModel).where(
                    LongTermMemoryRecordModel.memory_id == "mem-001"
                )
            )
            row = result.fetchone()
            assert row is not None
            assert row.access_count == 2  # 取最后一条记录的 access_count
            assert row.content == "用户喜欢咖啡"

    @pytest.mark.asyncio
    async def test_ltm_keywords_migrated(self, migration_db, full_data_root):
        """长期记忆的 keywords 被正确迁移"""
        await run_migration(project_root=full_data_root)

        async with migration_db["async_engine"].begin() as conn:
            result = await conn.execute(
                select(LongTermMemoryRecordModel).where(
                    LongTermMemoryRecordModel.memory_id == "mem-002"
                )
            )
            row = result.fetchone()
            assert row is not None
            assert "小明" in (row.keywords or [])
            assert "名字" in (row.keywords or [])


# ============================================================
# 测试：用户画像 / 情绪 / 学习日志迁移
# ============================================================


class TestProfileEmotionLearningMigration:
    """测试 user_profiles / emotion_history / learning_logs 迁移"""

    @pytest.mark.asyncio
    async def test_user_profile_migrated(self, migration_db, full_data_root):
        """用户画像被正确迁移"""
        reports = await run_migration(project_root=full_data_root)

        profile_report = next(r for r in reports if r.table == "user_profiles")
        assert profile_report.inserted == 1
        assert profile_report.rows_after == 1

        async with migration_db["async_engine"].begin() as conn:
            result = await conn.execute(select(UserProfileModel))
            row = result.fetchone()
            assert row is not None
            assert row.device_id == "AA:BB:CC:DD:EE:FF"
            assert row.name == "小明"
            assert row.occupation == "设计师"

    @pytest.mark.asyncio
    async def test_emotion_history_migrated(self, migration_db, full_data_root):
        """情绪历史被正确迁移"""
        reports = await run_migration(project_root=full_data_root)

        emotion_report = next(r for r in reports if r.table == "emotion_history")
        assert emotion_report.inserted == 2
        assert emotion_report.rows_after == 2

        async with migration_db["async_engine"].begin() as conn:
            result = await conn.execute(
                select(EmotionHistoryModel).order_by(EmotionHistoryModel.timestamp)
            )
            rows = result.fetchall()
            assert len(rows) == 2
            assert rows[0].emotion == "happy"
            assert rows[1].emotion == "sad"

    @pytest.mark.asyncio
    async def test_learning_logs_migrated(self, migration_db, full_data_root):
        """学习日志被正确迁移"""
        reports = await run_migration(project_root=full_data_root)

        learning_report = next(r for r in reports if r.table == "learning_logs")
        assert learning_report.inserted == 2
        assert learning_report.rows_after == 2

        async with migration_db["async_engine"].begin() as conn:
            result = await conn.execute(
                select(LearningLogModel).order_by(LearningLogModel.timestamp)
            )
            rows = result.fetchall()
            assert len(rows) == 2
            assert rows[0].action == "create"
            assert rows[1].action == "update"
            assert rows[0].skill_name == "python_tips"


# ============================================================
# 测试：表情包迁移
# ============================================================


class TestEmoPacksMigration:
    """测试 emos/packs/*/meta.json → emo_packs 表"""

    @pytest.mark.asyncio
    async def test_emo_packs_migrated(self, migration_db, full_data_root):
        """表情包元数据被正确迁移"""
        reports = await run_migration(project_root=full_data_root)

        emo_report = next(r for r in reports if r.table == "emo_packs")
        assert emo_report.inserted == 1
        assert emo_report.rows_after == 1

        async with migration_db["async_engine"].begin() as conn:
            result = await conn.execute(select(EmoPackModel))
            row = result.fetchone()
            assert row is not None
            assert row.pack_name == "test_pack"
            assert row.display_name == "测试表情包"


# ============================================================
# 测试：技能迁移
# ============================================================


class TestSkillsMigration:
    """测试 SKILL.md → skills 表"""

    @pytest.mark.asyncio
    async def test_skills_migrated(self, migration_db, full_data_root):
        """全局技能和设备自学习技能都被迁移"""
        reports = await run_migration(project_root=full_data_root)

        skill_report = next(r for r in reports if r.table == "skills")
        assert skill_report.inserted == 2  # 1 个全局 + 1 个设备
        assert skill_report.rows_after == 2

        async with migration_db["async_engine"].begin() as conn:
            result = await conn.execute(select(SkillModel))
            rows = {r.skill_id: r for r in result.fetchall()}

            # 全局技能
            assert "builtin_skill" in rows
            builtin = rows["builtin_skill"]
            assert builtin.source == "builtin"
            assert builtin.device_id == ""
            assert "builtin_skill" in builtin.file_path

            # 设备自学习技能（device_id 应为 MAC 地址）
            assert "custom_skill" in rows
            custom = rows["custom_skill"]
            assert custom.source == "self_learning"
            assert custom.device_id == "AA:BB:CC:DD:EE:FF"


# ============================================================
# 测试：完整迁移
# ============================================================


class TestFullMigration:
    """测试完整迁移流程"""

    @pytest.mark.asyncio
    async def test_full_migration_all_tables(self, migration_db, full_data_root):
        """完整迁移后所有表都有数据"""
        reports = await run_migration(project_root=full_data_root)

        assert len(reports) == 8
        for r in reports:
            assert not r.skipped, f"{r.table} 不应被跳过"
            assert r.rows_after > 0, f"{r.table} 应有数据"

        # 验证报告格式化输出
        output = format_report(reports, dry_run=False)
        assert "数据迁移报告" in output
        assert "devices" in output
        assert "skills" in output

    @pytest.mark.asyncio
    async def test_migration_report_structure(self, migration_db, full_data_root):
        """迁移报告包含完整字段"""
        reports = await run_migration(project_root=full_data_root)

        for r in reports:
            d = r.to_dict()
            assert "table" in d
            assert "rows_before" in d
            assert "rows_after" in d
            assert "inserted" in d
            assert "skipped" in d
            assert "elapsed_seconds" in d
            assert "warnings" in d


# ============================================================
# 测试：幂等性
# ============================================================


class TestIdempotency:
    """测试幂等性（重复迁移不重复插入）"""

    @pytest.mark.asyncio
    async def test_second_run_skips_all(self, migration_db, full_data_root):
        """第二次迁移时，所有表已有数据 → 全部跳过"""
        # 第一次迁移
        reports1 = await run_migration(project_root=full_data_root)
        for r in reports1:
            assert not r.skipped

        # 第二次迁移（应全部跳过）
        reports2 = await run_migration(project_root=full_data_root)
        report_map1 = {r.table: r for r in reports1}
        for r in reports2:
            assert r.skipped, f"{r.table} 第二次迁移应被跳过"
            assert r.inserted == 0
            # 行数不变
            r1 = report_map1[r.table]
            assert r.rows_after == r1.rows_after, (
                f"{r.table} 行数不一致: first={r1.rows_after}, second={r.rows_after}"
            )

    @pytest.mark.asyncio
    async def test_second_run_no_duplicate_rows(self, migration_db, full_data_root):
        """第二次迁移后行数不变（无重复插入）"""
        await run_migration(project_root=full_data_root)

        # 记录第一次迁移后的行数
        async with migration_db["async_engine"].begin() as conn:
            tables = [
                DeviceModel,
                ShortTermMemoryModel,
                LongTermMemoryRecordModel,
                UserProfileModel,
                EmotionHistoryModel,
                LearningLogModel,
                EmoPackModel,
                SkillModel,
            ]
            counts_before = {}
            for model in tables:
                result = await conn.execute(select(func.count()).select_from(model))
                counts_before[model.__tablename__] = int(result.scalar_one() or 0)

        # 第二次迁移
        await run_migration(project_root=full_data_root)

        # 验证行数不变
        async with migration_db["async_engine"].begin() as conn:
            for model in tables:
                result = await conn.execute(select(func.count()).select_from(model))
                count_after = int(result.scalar_one() or 0)
                assert count_after == counts_before[model.__tablename__], (
                    f"{model.__tablename__} 行数不一致: "
                    f"before={counts_before[model.__tablename__]}, after={count_after}"
                )


# ============================================================
# 测试：--dry-run 模式
# ============================================================


class TestDryRun:
    """测试 --dry-run 模式（只报告不执行）"""

    @pytest.mark.asyncio
    async def test_dry_run_no_data_written(self, migration_db, full_data_root):
        """dry-run 模式下不写入任何数据"""
        reports = await run_migration(
            project_root=full_data_root, dry_run=True
        )

        # 报告 inserted 数量（预期值），但 rows_after 不变（仍为 0）
        devices_report = next(r for r in reports if r.table == "devices")
        assert devices_report.inserted == 1  # 预期 1 条
        assert devices_report.rows_after == 0  # 实际未写入

        stm_report = next(r for r in reports if r.table == "short_term_memories")
        assert stm_report.inserted == 3  # 预期 3 条
        assert stm_report.rows_after == 0

        # 验证数据库确实为空
        async with migration_db["async_engine"].begin() as conn:
            for model in [
                DeviceModel, ShortTermMemoryModel, LongTermMemoryRecordModel,
                UserProfileModel, EmotionHistoryModel, LearningLogModel,
                EmoPackModel, SkillModel,
            ]:
                result = await conn.execute(select(func.count()).select_from(model))
                count = int(result.scalar_one() or 0)
                assert count == 0, f"{model.__tablename__} 应为空，实际 {count}"

    @pytest.mark.asyncio
    async def test_dry_run_report_format(self, migration_db, full_data_root):
        """dry-run 报告包含 [DRY-RUN] 标记"""
        reports = await run_migration(
            project_root=full_data_root, dry_run=True
        )
        output = format_report(reports, dry_run=True)
        assert "[DRY-RUN]" in output

    @pytest.mark.asyncio
    async def test_dry_run_then_real_migration(self, migration_db, full_data_root):
        """dry-run 后执行真实迁移，数据应正确写入"""
        # dry-run
        dry_reports = await run_migration(
            project_root=full_data_root, dry_run=True
        )
        # 验证 dry-run 未写入
        async with migration_db["async_engine"].begin() as conn:
            result = await conn.execute(select(func.count()).select_from(DeviceModel))
            assert int(result.scalar_one() or 0) == 0

        # 真实迁移
        real_reports = await run_migration(project_root=full_data_root)
        devices_real = next(r for r in real_reports if r.table == "devices")
        assert devices_real.rows_after == 1


# ============================================================
# 测试：--force 模式
# ============================================================


class TestForceMigration:
    """测试 --force 模式（强制重新迁移）"""

    @pytest.mark.asyncio
    async def test_force_re_migrates(self, migration_db, full_data_root):
        """--force 模式下，已有数据的表也会重新迁移"""
        # 第一次迁移
        await run_migration(project_root=full_data_root)

        # 第二次迁移（--force）
        reports = await run_migration(project_root=full_data_root, force=True)

        for r in reports:
            assert not r.skipped, f"{r.table} --force 下不应跳过"
            assert r.inserted > 0, f"{r.table} --force 下应有迁移记录"

    @pytest.mark.asyncio
    async def test_force_no_duplicate_rows(self, migration_db, full_data_root):
        """--force 重新迁移后行数不变（UPSERT 不产生重复）"""
        # 第一次迁移
        await run_migration(project_root=full_data_root)

        # 记录行数
        async with migration_db["async_engine"].begin() as conn:
            result = await conn.execute(select(func.count()).select_from(DeviceModel))
            count_before = int(result.scalar_one() or 0)

        # --force 重新迁移
        await run_migration(project_root=full_data_root, force=True)

        # 验证行数不变
        async with migration_db["async_engine"].begin() as conn:
            result = await conn.execute(select(func.count()).select_from(DeviceModel))
            count_after = int(result.scalar_one() or 0)
            assert count_after == count_before


# ============================================================
# 测试：MigrationContext
# ============================================================


class TestMigrationContext:
    """测试 MigrationContext 路径解析"""

    def test_from_root_resolves_paths(self, tmp_path):
        """from_root 正确解析所有路径"""
        ctx = MigrationContext.from_root(tmp_path)
        assert ctx.project_root == tmp_path.resolve()
        assert ctx.users_json_path == tmp_path.resolve() / "users.json"
        assert ctx.memories_dir == tmp_path.resolve() / "src" / "data" / "memories"
        assert ctx.devices_dir == tmp_path.resolve() / "src" / "data" / "devices"
        assert ctx.emos_packs_dir == tmp_path.resolve() / "src" / "emos" / "packs"
        assert ctx.skills_root_dir == tmp_path.resolve() / "src" / "skills"


# ============================================================
# 测试：MigrationReport
# ============================================================


class TestMigrationReport:
    """测试 MigrationReport 数据类"""

    def test_to_dict(self):
        """to_dict 返回完整字段"""
        r = MigrationReport(
            table="devices",
            rows_before=0,
            rows_after=1,
            inserted=1,
            elapsed_seconds=0.123,
            warnings=["test warning"],
        )
        d = r.to_dict()
        assert d["table"] == "devices"
        assert d["rows_before"] == 0
        assert d["rows_after"] == 1
        assert d["inserted"] == 1
        assert d["skipped"] is False
        assert d["elapsed_seconds"] == 0.123
        assert d["warnings"] == ["test warning"]

    def test_default_values(self):
        """默认值正确"""
        r = MigrationReport(table="test")
        assert r.rows_before == 0
        assert r.rows_after == 0
        assert r.inserted == 0
        assert r.skipped is False
        assert r.skip_reason == ""
        assert r.elapsed_seconds == 0.0
        assert r.warnings == []
