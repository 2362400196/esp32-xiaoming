"""成长 / 表情包 / 技能 仓储单元测试

覆盖：
- ``UserProfileRepository``：get / upsert / update_partial + 边界条件
- ``EmotionHistoryRepository``：append / list_all / list_since + trim 100 + 设备隔离
- ``LearningLogRepository``：append / list_all + trim 100 + 设备隔离
- ``EmoPackRepository``：list_packs / get_pack_meta / upsert_pack / delete_pack /
  get_active_pack / set_active_pack + 边界条件
- ``SkillRepository``：get_skill / get_catalog / upsert_skill / delete_skill /
  list_skills_by_device / init_sync（同步扫描磁盘）+ 边界条件

使用内存 SQLite（sqlite+aiosqlite:///:memory: + StaticPool），
参考 ``tests/test_device_repository.py`` 的夹具模式（通过 monkeypatch 覆盖全局 session factory）。
"""
from __future__ import annotations

import json
import os
import time

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.infrastructure.db.base import Base
from src.infrastructure.db.models.device import DeviceModel
from src.infrastructure.db.models.emo import EmoPackModel
from src.infrastructure.db.models.growth import (
    EmotionHistoryModel,
    LearningLogModel,
    UserProfileModel,
)
from src.infrastructure.db.models.skill import SkillModel
from src.infrastructure.db.repositories.emo_repository import EmoPackRepository
from src.infrastructure.db.repositories.growth_repositories import (
    EmotionHistoryRepository,
    LearningLogRepository,
    UserProfileRepository,
)
from src.infrastructure.db.repositories.skill_repository import SkillRepository
from src.infrastructure.db.session import get_session_ctx


# ============================================================
# 辅助函数
# ============================================================

def _make_profile(
    device_id: str = "dev1",
    name: str = "张三",
    occupation: str = "工程师",
    **kwargs,
) -> dict:
    """构造 UserProfile dict（结构与 UserProfile.to_dict() 一致）"""
    profile = {
        "device_id": device_id,
        "name": name,
        "birthday": "1990-01-01",
        "occupation": occupation,
        "family": ["老婆:小李"],
        "personality": {"mbti": "INTJ"},
        "interests": {"likes": ["编程", "音乐"], "dislikes": ["加班"]},
        "habits": {"sleep": "23:00"},
        "important_dates": [{"date": "01-01", "label": "生日"}],
        "current_state": {"last_emotion": "happy"},
    }
    profile.update(kwargs)
    return profile


def _make_emotion_record(
    timestamp: float = 1000.0,
    emotion: str = "happy",
    intensity: float = 0.8,
    trigger: str = "收到礼物",
    context: str = "对话中",
    speaker: str = "user",
) -> dict:
    """构造情绪记录 dict（结构与 EmotionRecord.to_dict() 一致）"""
    return {
        "timestamp": timestamp,
        "emotion": emotion,
        "intensity": intensity,
        "trigger": trigger,
        "context": context,
        "speaker": speaker,
    }


def _make_learning_entry(
    timestamp: float = 1000.0,
    action: str = "create",
    skill_name: str = "python_tips",
    title: str = "Python技巧",
    category: str = "编程",
) -> dict:
    """构造学习日志条目 dict（与 SelfLearningService._log_learning 一致）"""
    return {
        "timestamp": timestamp,
        "action": action,
        "skill_name": skill_name,
        "title": title,
        "category": category,
    }


def _make_frontmatter(
    name: str = "test_skill",
    description: str = "A test skill",
    author: str = "tester",
    cap_groups: list | None = None,
    category: list | None = None,
    peripherals: list | None = None,
    tags: list | None = None,
    manage_mode: str = "readonly",
) -> dict:
    """构造 SKILL.md frontmatter dict"""
    return {
        "name": name,
        "description": description,
        "author": author,
        "metadata": {
            "cap_groups": cap_groups or [],
            "manage_mode": manage_mode,
            "category": category or [],
            "peripherals": peripherals or [],
            "tags": tags or [],
        },
    }


def _write_skill_md(skill_dir: str, frontmatter: dict, body: str) -> str:
    """在指定目录写入 SKILL.md 文件，返回文件路径"""
    os.makedirs(skill_dir, exist_ok=True)
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


# ============================================================
# 异步夹具（:memory: + StaticPool）
# ============================================================

@pytest_asyncio.fixture
async def async_engine():
    """内存 SQLite 异步引擎（StaticPool 确保 :memory: 单连接复用）"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def repos(async_engine, monkeypatch):
    """所有异步仓储（覆盖全局 async session factory）

    返回一个包含所有异步仓储实例的 dict，方便测试调用。
    """
    async_factory = async_sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    import src.infrastructure.db.engine as engine_mod
    monkeypatch.setattr(engine_mod, "_async_engine", async_engine)
    monkeypatch.setattr(engine_mod, "_async_session_factory", async_factory)
    yield {
        "profile": UserProfileRepository(),
        "emotion": EmotionHistoryRepository(),
        "learning": LearningLogRepository(),
        "emo": EmoPackRepository(),
        "skill": SkillRepository(),
    }


# ============================================================
# 同步夹具（独立 :memory: DB）
# ============================================================

@pytest.fixture
def sync_skill_repo(monkeypatch):
    """SkillRepository（同步，覆盖全局 sync session factory）

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
    yield SkillRepository()
    sync_engine.dispose()


# ============================================================
# 共享文件 DB 夹具（跨引擎：init_sync 写 + async 读）
# ============================================================

@pytest_asyncio.fixture
async def shared_db(tmp_path, monkeypatch):
    """文件 SQLite，同步和异步引擎共享同一 DB 文件。

    用于测试 ``init_sync``（同步写入）后通过异步方法读取。
    """
    db_file = tmp_path / "shared.db"

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
        "skill": SkillRepository(),
        "async_engine": async_engine,
        "sync_engine": sync_engine,
    }

    await async_engine.dispose()
    sync_engine.dispose()


# ============================================================
# UserProfileRepository 测试
# ============================================================

class TestUserProfileRepository:
    """用户画像仓储 CRUD + 边界条件"""

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_empty_profile(self, repos):
        """查询不存在的设备返回空 profile dict（非 None）"""
        profile = await repos["profile"].get("nonexistent")
        assert profile is not None
        assert profile["device_id"] == "nonexistent"
        assert profile["name"] == ""
        assert profile["family"] == []
        assert profile["interests"] == {}
        assert profile["created_at"] == 0.0
        assert profile["updated_at"] == 0.0

    @pytest.mark.asyncio
    async def test_get_empty_device_id(self, repos):
        """空 device_id 返回空 profile"""
        profile = await repos["profile"].get("")
        assert profile["name"] == ""
        assert profile["device_id"] == ""

    @pytest.mark.asyncio
    async def test_upsert_and_get(self, repos):
        """upsert 后能读取到完整数据"""
        await repos["profile"].upsert("dev1", _make_profile())
        profile = await repos["profile"].get("dev1")
        assert profile["name"] == "张三"
        assert profile["occupation"] == "工程师"
        assert profile["birthday"] == "1990-01-01"
        assert profile["family"] == ["老婆:小李"]
        assert profile["interests"] == {"likes": ["编程", "音乐"], "dislikes": ["加班"]}
        assert profile["personality"] == {"mbti": "INTJ"}
        assert profile["important_dates"] == [{"date": "01-01", "label": "生日"}]
        assert profile["current_state"] == {"last_emotion": "happy"}
        assert profile["created_at"] > 0
        assert profile["updated_at"] > 0

    @pytest.mark.asyncio
    async def test_upsert_idempotent(self, repos):
        """多次 upsert 同一设备不产生重复行"""
        await repos["profile"].upsert("dev1", _make_profile())
        await repos["profile"].upsert("dev1", _make_profile())
        await repos["profile"].upsert("dev1", _make_profile())

        async with get_session_ctx() as session:
            result = await session.execute(select(UserProfileModel))
            assert len(result.scalars().all()) == 1

    @pytest.mark.asyncio
    async def test_upsert_updates_existing(self, repos):
        """upsert 更新已存在画像（覆盖字段）"""
        await repos["profile"].upsert("dev1", _make_profile())
        await repos["profile"].upsert("dev1", _make_profile(
            name="李四", occupation="设计师",
            interests={"likes": ["画画"]},
        ))
        profile = await repos["profile"].get("dev1")
        assert profile["name"] == "李四"
        assert profile["occupation"] == "设计师"
        assert profile["interests"] == {"likes": ["画画"]}

    @pytest.mark.asyncio
    async def test_upsert_preserves_created_at(self, repos):
        """upsert 更新时 created_at 不变，updated_at 刷新"""
        await repos["profile"].upsert("dev1", _make_profile())
        profile_before = await repos["profile"].get("dev1")
        created_before = profile_before["created_at"]
        updated_before = profile_before["updated_at"]

        time.sleep(0.02)
        await repos["profile"].upsert("dev1", _make_profile(name="新名字"))

        profile_after = await repos["profile"].get("dev1")
        assert profile_after["created_at"] == created_before
        assert profile_after["updated_at"] > updated_before

    @pytest.mark.asyncio
    async def test_upsert_empty_device_id(self, repos):
        """空 device_id 不执行操作"""
        await repos["profile"].upsert("", _make_profile())
        async with get_session_ctx() as session:
            result = await session.execute(select(UserProfileModel))
            assert len(result.scalars().all()) == 0

    @pytest.mark.asyncio
    async def test_upsert_minimal_profile(self, repos):
        """最小 profile（仅 name）也能正常往返"""
        await repos["profile"].upsert("dev1", {"name": "小明"})
        profile = await repos["profile"].get("dev1")
        assert profile["name"] == "小明"
        assert profile["family"] == []
        assert profile["interests"] == {}

    @pytest.mark.asyncio
    async def test_update_partial(self, repos):
        """部分更新只修改指定字段"""
        await repos["profile"].upsert("dev1", _make_profile())
        await repos["profile"].update_partial("dev1", {
            "name": "王五",
            "occupation": "老师",
        })
        profile = await repos["profile"].get("dev1")
        assert profile["name"] == "王五"
        assert profile["occupation"] == "老师"
        # 未更新的字段保持不变
        assert profile["birthday"] == "1990-01-01"
        assert profile["interests"] == {"likes": ["编程", "音乐"], "dislikes": ["加班"]}

    @pytest.mark.asyncio
    async def test_update_partial_nested_json(self, repos):
        """部分更新 JSON 字段（整体替换）"""
        await repos["profile"].upsert("dev1", _make_profile())
        await repos["profile"].update_partial("dev1", {
            "interests": {"likes": ["新爱好"]},
        })
        profile = await repos["profile"].get("dev1")
        assert profile["interests"] == {"likes": ["新爱好"]}
        # 其他字段不变
        assert profile["name"] == "张三"

    @pytest.mark.asyncio
    async def test_update_partial_nonexistent(self, repos):
        """对不存在的设备做部分更新（无操作，不报错）"""
        await repos["profile"].update_partial("nonexistent", {"name": "x"})
        # 验证没有创建新行
        profile = await repos["profile"].get("nonexistent")
        assert profile["name"] == ""  # 仍然是空 profile

    @pytest.mark.asyncio
    async def test_update_partial_empty_updates(self, repos):
        """空 updates 不执行操作"""
        await repos["profile"].upsert("dev1", _make_profile())
        await repos["profile"].update_partial("dev1", {})
        profile = await repos["profile"].get("dev1")
        assert profile["name"] == "张三"  # 不变

    @pytest.mark.asyncio
    async def test_update_partial_ignores_unknown_keys(self, repos):
        """部分更新忽略未知字段"""
        await repos["profile"].upsert("dev1", _make_profile())
        await repos["profile"].update_partial("dev1", {
            "name": "新名",
            "unknown_field": "xxx",
            "device_id": "hacked",  # 不应被更新
        })
        profile = await repos["profile"].get("dev1")
        assert profile["name"] == "新名"
        assert profile["device_id"] == "dev1"  # 主键未被修改


# ============================================================
# EmotionHistoryRepository 测试
# ============================================================

class TestEmotionHistoryRepository:
    """情绪历史仓储 CRUD + trim + 边界条件"""

    @pytest.mark.asyncio
    async def test_append_and_list_all(self, repos):
        """追加一条记录后能列出"""
        await repos["emotion"].append("dev1", _make_emotion_record(timestamp=1.0))
        records = await repos["emotion"].list_all("dev1")
        assert len(records) == 1
        assert records[0]["emotion"] == "happy"
        assert records[0]["intensity"] == 0.8
        assert records[0]["trigger"] == "收到礼物"
        assert records[0]["speaker"] == "user"

    @pytest.mark.asyncio
    async def test_list_all_empty(self, repos):
        """空设备返回空列表"""
        assert await repos["emotion"].list_all("dev1") == []

    @pytest.mark.asyncio
    async def test_list_all_empty_device_id(self, repos):
        """空 device_id 返回空列表"""
        assert await repos["emotion"].list_all("") == []

    @pytest.mark.asyncio
    async def test_append_multiple_ordered(self, repos):
        """多条记录按时间升序返回"""
        for i in range(5):
            await repos["emotion"].append("dev1", _make_emotion_record(
                timestamp=float(i), emotion=f"emo_{i}",
            ))
        records = await repos["emotion"].list_all("dev1")
        assert len(records) == 5
        for i, r in enumerate(records):
            assert r["emotion"] == f"emo_{i}"
            assert r["timestamp"] == float(i)

    @pytest.mark.asyncio
    async def test_list_since(self, repos):
        """list_since 按 timestamp 过滤"""
        for i in range(10):
            await repos["emotion"].append("dev1", _make_emotion_record(
                timestamp=float(i * 100),
            ))
        records = await repos["emotion"].list_since("dev1", 300.0)
        assert len(records) == 7  # 300, 400, ..., 900
        assert records[0]["timestamp"] == 300.0
        assert records[-1]["timestamp"] == 900.0

    @pytest.mark.asyncio
    async def test_list_since_boundary(self, repos):
        """list_since 包含等于 since_timestamp 的记录"""
        await repos["emotion"].append("dev1", _make_emotion_record(timestamp=100.0))
        await repos["emotion"].append("dev1", _make_emotion_record(timestamp=200.0))
        records = await repos["emotion"].list_since("dev1", 100.0)
        assert len(records) == 2  # 100.0 和 200.0 都包含

    @pytest.mark.asyncio
    async def test_list_since_empty_result(self, repos):
        """list_since 无匹配记录返回空列表"""
        await repos["emotion"].append("dev1", _make_emotion_record(timestamp=100.0))
        assert await repos["emotion"].list_since("dev1", 200.0) == []

    @pytest.mark.asyncio
    async def test_trim_to_100(self, repos):
        """插入 105 条后修剪到 100 条（保留最新的）"""
        for i in range(105):
            await repos["emotion"].append("dev1", _make_emotion_record(
                timestamp=float(i), emotion=f"emo_{i}",
            ))
        records = await repos["emotion"].list_all("dev1")
        assert len(records) == 100
        # 最新的 100 条是 timestamp 5..104
        assert records[0]["timestamp"] == 5.0
        assert records[-1]["timestamp"] == 104.0

    @pytest.mark.asyncio
    async def test_trim_keeps_latest(self, repos):
        """修剪后保留的是最新的记录"""
        for i in range(102):
            await repos["emotion"].append("dev1", _make_emotion_record(
                timestamp=float(i), emotion=f"emo_{i}",
            ))
        records = await repos["emotion"].list_all("dev1")
        assert len(records) == 100
        # 最老的 2 条被删除
        assert "emo_0" not in [r["emotion"] for r in records]
        assert "emo_1" not in [r["emotion"] for r in records]
        assert "emo_2" in [r["emotion"] for r in records]
        assert "emo_101" in [r["emotion"] for r in records]

    @pytest.mark.asyncio
    async def test_device_isolation(self, repos):
        """不同设备的情绪记录相互隔离"""
        await repos["emotion"].append("dev1", _make_emotion_record(
            timestamp=1.0, emotion="happy",
        ))
        await repos["emotion"].append("dev2", _make_emotion_record(
            timestamp=2.0, emotion="sad",
        ))
        assert len(await repos["emotion"].list_all("dev1")) == 1
        assert len(await repos["emotion"].list_all("dev2")) == 1
        assert (await repos["emotion"].list_all("dev1"))[0]["emotion"] == "happy"
        assert (await repos["emotion"].list_all("dev2"))[0]["emotion"] == "sad"

    @pytest.mark.asyncio
    async def test_append_empty_device_id(self, repos):
        """空 device_id 不执行操作"""
        await repos["emotion"].append("", _make_emotion_record())
        assert await repos["emotion"].list_all("") == []

    @pytest.mark.asyncio
    async def test_append_empty_record(self, repos):
        """空 record 不执行操作"""
        await repos["emotion"].append("dev1", {})
        # 不应报错，也不应插入
        assert await repos["emotion"].list_all("dev1") == []

    @pytest.mark.asyncio
    async def test_record_dict_structure(self, repos):
        """返回的 dict 结构与 EmotionRecord.to_dict() 一致"""
        await repos["emotion"].append("dev1", _make_emotion_record())
        records = await repos["emotion"].list_all("dev1")
        assert set(records[0].keys()) == {
            "timestamp", "emotion", "intensity", "trigger", "context", "speaker",
        }


# ============================================================
# LearningLogRepository 测试
# ============================================================

class TestLearningLogRepository:
    """自学习日志仓储 CRUD + trim + 边界条件"""

    @pytest.mark.asyncio
    async def test_append_and_list_all(self, repos):
        """追加一条日志后能列出"""
        await repos["learning"].append("dev1", _make_learning_entry())
        logs = await repos["learning"].list_all("dev1")
        assert len(logs) == 1
        assert logs[0]["action"] == "create"
        assert logs[0]["skill_name"] == "python_tips"
        assert logs[0]["title"] == "Python技巧"
        assert logs[0]["category"] == "编程"

    @pytest.mark.asyncio
    async def test_list_all_empty(self, repos):
        """空设备返回空列表"""
        assert await repos["learning"].list_all("dev1") == []

    @pytest.mark.asyncio
    async def test_list_all_empty_device_id(self, repos):
        """空 device_id 返回空列表"""
        assert await repos["learning"].list_all("") == []

    @pytest.mark.asyncio
    async def test_append_multiple_ordered(self, repos):
        """多条日志按时间升序返回"""
        for i in range(5):
            await repos["learning"].append("dev1", _make_learning_entry(
                timestamp=float(i), action=f"action_{i}",
            ))
        logs = await repos["learning"].list_all("dev1")
        assert len(logs) == 5
        for i, log in enumerate(logs):
            assert log["action"] == f"action_{i}"

    @pytest.mark.asyncio
    async def test_trim_to_100(self, repos):
        """插入 105 条后修剪到 100 条"""
        for i in range(105):
            await repos["learning"].append("dev1", _make_learning_entry(
                timestamp=float(i), skill_name=f"skill_{i}",
            ))
        logs = await repos["learning"].list_all("dev1")
        assert len(logs) == 100
        # 最新的 100 条是 timestamp 5..104
        assert logs[0]["timestamp"] == 5.0
        assert logs[-1]["timestamp"] == 104.0

    @pytest.mark.asyncio
    async def test_trim_keeps_latest(self, repos):
        """修剪后保留的是最新的记录"""
        for i in range(102):
            await repos["learning"].append("dev1", _make_learning_entry(
                timestamp=float(i), skill_name=f"skill_{i}",
            ))
        logs = await repos["learning"].list_all("dev1")
        assert len(logs) == 100
        names = [l["skill_name"] for l in logs]
        assert "skill_0" not in names
        assert "skill_1" not in names
        assert "skill_2" in names
        assert "skill_101" in names

    @pytest.mark.asyncio
    async def test_device_isolation(self, repos):
        """不同设备的学习日志相互隔离"""
        await repos["learning"].append("dev1", _make_learning_entry(skill_name="a"))
        await repos["learning"].append("dev2", _make_learning_entry(skill_name="b"))
        assert len(await repos["learning"].list_all("dev1")) == 1
        assert len(await repos["learning"].list_all("dev2")) == 1
        assert (await repos["learning"].list_all("dev1"))[0]["skill_name"] == "a"
        assert (await repos["learning"].list_all("dev2"))[0]["skill_name"] == "b"

    @pytest.mark.asyncio
    async def test_append_empty_device_id(self, repos):
        """空 device_id 不执行操作"""
        await repos["learning"].append("", _make_learning_entry())
        assert await repos["learning"].list_all("") == []

    @pytest.mark.asyncio
    async def test_append_empty_entry(self, repos):
        """空 entry 不执行操作"""
        await repos["learning"].append("dev1", {})
        assert await repos["learning"].list_all("dev1") == []

    @pytest.mark.asyncio
    async def test_entry_dict_structure(self, repos):
        """返回的 dict 结构与 _log_learning 条目一致"""
        await repos["learning"].append("dev1", _make_learning_entry())
        logs = await repos["learning"].list_all("dev1")
        assert set(logs[0].keys()) == {
            "timestamp", "action", "skill_name", "title", "category",
        }


# ============================================================
# EmoPackRepository 测试
# ============================================================

class TestEmoPackRepository:
    """表情包元数据仓储 CRUD + 激活包 + 边界条件"""

    @pytest.mark.asyncio
    async def test_list_packs_empty(self, repos):
        """空数据库返回空列表"""
        assert await repos["emo"].list_packs() == []

    @pytest.mark.asyncio
    async def test_upsert_and_get_meta(self, repos):
        """upsert 后能获取元数据"""
        await repos["emo"].upsert_pack("default", "默认")
        meta = await repos["emo"].get_pack_meta("default")
        assert meta is not None
        assert meta["name"] == "default"
        assert meta["display_name"] == "默认"

    @pytest.mark.asyncio
    async def test_upsert_and_list_packs(self, repos):
        """upsert 后 list_packs 返回含 display_name"""
        await repos["emo"].upsert_pack("default", "默认")
        await repos["emo"].upsert_pack("pack_1", "可爱表情")
        packs = await repos["emo"].list_packs()
        assert len(packs) == 2
        # 按 pack_name 升序
        assert packs[0]["name"] == "default"
        assert packs[0]["display_name"] == "默认"
        assert packs[1]["name"] == "pack_1"
        assert packs[1]["display_name"] == "可爱表情"

    @pytest.mark.asyncio
    async def test_upsert_updates_existing(self, repos):
        """upsert 更新已存在表情包的 display_name"""
        await repos["emo"].upsert_pack("pack_1", "旧名称")
        await repos["emo"].upsert_pack("pack_1", "新名称")
        meta = await repos["emo"].get_pack_meta("pack_1")
        assert meta["display_name"] == "新名称"
        # 不应产生重复行
        packs = await repos["emo"].list_packs()
        assert len(packs) == 1

    @pytest.mark.asyncio
    async def test_upsert_idempotent(self, repos):
        """多次 upsert 同一表情包不产生重复"""
        await repos["emo"].upsert_pack("default", "默认")
        await repos["emo"].upsert_pack("default", "默认")
        await repos["emo"].upsert_pack("default", "默认")
        assert len(await repos["emo"].list_packs()) == 1

    @pytest.mark.asyncio
    async def test_upsert_empty_display_name_falls_back(self, repos):
        """display_name 为空时回退到 pack_name"""
        await repos["emo"].upsert_pack("default", "")
        meta = await repos["emo"].get_pack_meta("default")
        assert meta["display_name"] == "default"

    @pytest.mark.asyncio
    async def test_upsert_empty_pack_name(self, repos):
        """空 pack_name 不执行操作"""
        await repos["emo"].upsert_pack("", "测试")
        assert await repos["emo"].list_packs() == []

    @pytest.mark.asyncio
    async def test_get_pack_meta_nonexistent(self, repos):
        """获取不存在的表情包返回 None"""
        assert await repos["emo"].get_pack_meta("nonexistent") is None

    @pytest.mark.asyncio
    async def test_get_pack_meta_empty_name(self, repos):
        """空 pack_name 返回 None"""
        assert await repos["emo"].get_pack_meta("") is None

    @pytest.mark.asyncio
    async def test_delete_pack(self, repos):
        """删除存在的表情包返回 True"""
        await repos["emo"].upsert_pack("pack_1", "测试")
        assert await repos["emo"].delete_pack("pack_1") is True
        assert await repos["emo"].get_pack_meta("pack_1") is None

    @pytest.mark.asyncio
    async def test_delete_pack_nonexistent(self, repos):
        """删除不存在的表情包返回 False"""
        assert await repos["emo"].delete_pack("nonexistent") is False

    @pytest.mark.asyncio
    async def test_delete_pack_empty_name(self, repos):
        """空 pack_name 返回 False"""
        assert await repos["emo"].delete_pack("") is False

    @pytest.mark.asyncio
    async def test_get_active_pack_no_device(self, repos):
        """设备不存在时返回 'default'"""
        assert await repos["emo"].get_active_pack("nonexistent") == "default"

    @pytest.mark.asyncio
    async def test_get_active_pack_empty_device_id(self, repos):
        """空 device_id 返回 'default'"""
        assert await repos["emo"].get_active_pack("") == "default"

    @pytest.mark.asyncio
    async def test_get_active_pack_default_column(self, repos):
        """设备存在但未设置 active_emo_pack 时返回 'default'"""
        # 创建设备（device_key NOT NULL）
        async with get_session_ctx() as session:
            session.add(DeviceModel(device_id="dev1", device_key="key1", name="测试"))
        result = await repos["emo"].get_active_pack("dev1")
        assert result == "default"

    @pytest.mark.asyncio
    async def test_set_and_get_active_pack(self, repos):
        """设置并获取激活表情包"""
        async with get_session_ctx() as session:
            session.add(DeviceModel(device_id="dev1", device_key="key1", name="测试"))
        await repos["emo"].set_active_pack("dev1", "pack_1")
        assert await repos["emo"].get_active_pack("dev1") == "pack_1"

    @pytest.mark.asyncio
    async def test_set_active_pack_overwrites(self, repos):
        """重复设置激活表情包覆盖旧值"""
        async with get_session_ctx() as session:
            session.add(DeviceModel(device_id="dev1", device_key="key1", name="测试"))
        await repos["emo"].set_active_pack("dev1", "pack_1")
        await repos["emo"].set_active_pack("dev1", "pack_2")
        assert await repos["emo"].get_active_pack("dev1") == "pack_2"

    @pytest.mark.asyncio
    async def test_set_active_pack_nonexistent_device(self, repos):
        """对不存在的设备设置激活包（无操作，不报错）"""
        await repos["emo"].set_active_pack("nonexistent", "pack_1")
        # 不应报错，设备不存在所以 get 返回 default
        assert await repos["emo"].get_active_pack("nonexistent") == "default"

    @pytest.mark.asyncio
    async def test_set_active_pack_empty_args(self, repos):
        """空参数不执行操作"""
        await repos["emo"].set_active_pack("", "pack_1")
        await repos["emo"].set_active_pack("dev1", "")


# ============================================================
# SkillRepository 异步测试
# ============================================================

class TestSkillRepositoryAsync:
    """技能仓储异步 CRUD + 边界条件"""

    @pytest.mark.asyncio
    async def test_upsert_and_get_skill(self, repos):
        """upsert 后能获取完整 skill（frontmatter + body）"""
        fm = _make_frontmatter(
            name="weather",
            description="天气查询",
            author="espai",
            cap_groups=[["weather"]],
            category=["生活"],
            tags=["天气", "查询"],
        )
        await repos["skill"].upsert_skill("weather", fm, "## 天气查询技能\n\n使用工具查询天气。")

        skill = await repos["skill"].get_skill("weather")
        assert skill is not None
        assert skill["skill_id"] == "weather"
        assert skill["frontmatter"]["name"] == "weather"
        assert skill["frontmatter"]["description"] == "天气查询"
        assert skill["frontmatter"]["author"] == "espai"
        assert skill["frontmatter"]["metadata"]["cap_groups"] == [["weather"]]
        assert skill["frontmatter"]["metadata"]["category"] == ["生活"]
        assert skill["frontmatter"]["metadata"]["tags"] == ["天气", "查询"]
        assert skill["frontmatter"]["metadata"]["manage_mode"] == "readonly"
        assert "天气查询技能" in skill["body"]
        assert skill["device_id"] == ""
        assert skill["source"] == "builtin"

    @pytest.mark.asyncio
    async def test_get_skill_nonexistent(self, repos):
        """获取不存在的技能返回 None"""
        assert await repos["skill"].get_skill("nonexistent") is None

    @pytest.mark.asyncio
    async def test_get_skill_empty_id(self, repos):
        """空 skill_id 返回 None"""
        assert await repos["skill"].get_skill("") is None

    @pytest.mark.asyncio
    async def test_upsert_idempotent(self, repos):
        """多次 upsert 同一技能不产生重复"""
        fm = _make_frontmatter()
        await repos["skill"].upsert_skill("test_skill", fm, "body")
        await repos["skill"].upsert_skill("test_skill", fm, "body")
        await repos["skill"].upsert_skill("test_skill", fm, "body")

        async with get_session_ctx() as session:
            result = await session.execute(select(SkillModel))
            assert len(result.scalars().all()) == 1

    @pytest.mark.asyncio
    async def test_upsert_updates_existing(self, repos):
        """upsert 更新已存在技能的 frontmatter + body"""
        fm1 = _make_frontmatter(description="旧描述")
        await repos["skill"].upsert_skill("skill1", fm1, "旧 body")

        fm2 = _make_frontmatter(description="新描述", tags=["new_tag"])
        await repos["skill"].upsert_skill("skill1", fm2, "新 body")

        skill = await repos["skill"].get_skill("skill1")
        assert skill["frontmatter"]["description"] == "新描述"
        assert skill["frontmatter"]["metadata"]["tags"] == ["new_tag"]
        assert skill["body"] == "新 body"

    @pytest.mark.asyncio
    async def test_upsert_preserves_file_path(self, repos):
        """upsert_skill 不覆盖 file_path / directory / source / device_id"""
        # 先通过 init_sync 设置 file_path（模拟）
        async with get_session_ctx() as session:
            session.add(SkillModel(
                skill_id="skill1",
                name="skill1",
                description="原始",
                body="原始 body",
                file_path="/path/to/SKILL.md",
                directory="/path/to",
                source="builtin",
                device_id="dev1",
            ))

        # 通过 upsert_skill 更新
        fm = _make_frontmatter(name="skill1", description="更新后")
        await repos["skill"].upsert_skill("skill1", fm, "新 body")

        skill = await repos["skill"].get_skill("skill1")
        assert skill["frontmatter"]["description"] == "更新后"
        assert skill["body"] == "新 body"
        # file_path / directory / source / device_id 不被覆盖
        assert skill["file_path"] == "/path/to/SKILL.md"
        assert skill["directory"] == "/path/to"
        assert skill["source"] == "builtin"
        assert skill["device_id"] == "dev1"

    @pytest.mark.asyncio
    async def test_upsert_empty_skill_id(self, repos):
        """空 skill_id 不执行操作"""
        await repos["skill"].upsert_skill("", _make_frontmatter(), "body")
        assert await repos["skill"].get_skill("") is None

    @pytest.mark.asyncio
    async def test_delete_skill(self, repos):
        """删除存在的技能返回 True"""
        await repos["skill"].upsert_skill("skill1", _make_frontmatter(), "body")
        assert await repos["skill"].delete_skill("skill1") is True
        assert await repos["skill"].get_skill("skill1") is None

    @pytest.mark.asyncio
    async def test_delete_skill_nonexistent(self, repos):
        """删除不存在的技能返回 False"""
        assert await repos["skill"].delete_skill("nonexistent") is False

    @pytest.mark.asyncio
    async def test_delete_skill_empty_id(self, repos):
        """空 skill_id 返回 False"""
        assert await repos["skill"].delete_skill("") is False

    @pytest.mark.asyncio
    async def test_get_catalog_all(self, repos):
        """get_catalog 无过滤返回所有全局技能"""
        await repos["skill"].upsert_skill("skill_a", _make_frontmatter(description="A"), "body_a")
        await repos["skill"].upsert_skill("skill_b", _make_frontmatter(description="B"), "body_b")
        catalog = await repos["skill"].get_catalog()
        assert len(catalog) == 2
        ids = {e["id"] for e in catalog}
        assert ids == {"skill_a", "skill_b"}

    @pytest.mark.asyncio
    async def test_get_catalog_with_filter(self, repos):
        """get_catalog 按 skills_filter 过滤"""
        await repos["skill"].upsert_skill("skill_a", _make_frontmatter(), "body")
        await repos["skill"].upsert_skill("skill_b", _make_frontmatter(), "body")
        await repos["skill"].upsert_skill("skill_c", _make_frontmatter(), "body")
        catalog = await repos["skill"].get_catalog(skills_filter=["skill_a", "skill_c"])
        assert len(catalog) == 2
        ids = {e["id"] for e in catalog}
        assert ids == {"skill_a", "skill_c"}

    @pytest.mark.asyncio
    async def test_get_catalog_empty_filter(self, repos):
        """get_catalog 空过滤列表返回空（无设备自学习技能时）"""
        await repos["skill"].upsert_skill("skill_a", _make_frontmatter(), "body")
        catalog = await repos["skill"].get_catalog(skills_filter=[])
        assert catalog == []

    @pytest.mark.asyncio
    async def test_get_catalog_by_device(self, repos):
        """get_catalog 包含设备自学习技能"""
        # 全局技能
        await repos["skill"].upsert_skill("global_skill", _make_frontmatter(), "body")
        # 设备自学习技能（直接插入带 device_id 的行）
        async with get_session_ctx() as session:
            session.add(SkillModel(
                skill_id="device_skill",
                name="device_skill",
                description="设备技能",
                body="body",
                device_id="dev1",
                source="self_learning",
            ))

        # 设备 dev1 的目录应包含全局技能 + 设备技能
        catalog = await repos["skill"].get_catalog(device_id="dev1")
        ids = {e["id"] for e in catalog}
        assert "global_skill" in ids
        assert "device_skill" in ids

    @pytest.mark.asyncio
    async def test_get_catalog_device_with_empty_filter(self, repos):
        """get_catalog 设备 + 空过滤列表：只返回设备自学习技能"""
        await repos["skill"].upsert_skill("global_skill", _make_frontmatter(), "body")
        async with get_session_ctx() as session:
            session.add(SkillModel(
                skill_id="device_skill",
                name="device_skill",
                description="设备技能",
                body="body",
                device_id="dev1",
                source="self_learning",
            ))

        catalog = await repos["skill"].get_catalog(device_id="dev1", skills_filter=[])
        ids = {e["id"] for e in catalog}
        assert "device_skill" in ids
        assert "global_skill" not in ids  # 空过滤排除了全局技能

    @pytest.mark.asyncio
    async def test_get_catalog_device_filter_combined(self, repos):
        """get_catalog 设备 + 技能列表：设备技能自动包含 + 列表中的全局技能"""
        await repos["skill"].upsert_skill("skill_a", _make_frontmatter(), "body")
        await repos["skill"].upsert_skill("skill_b", _make_frontmatter(), "body")
        async with get_session_ctx() as session:
            session.add(SkillModel(
                skill_id="device_skill",
                name="device_skill",
                description="设备技能",
                body="body",
                device_id="dev1",
                source="self_learning",
            ))

        catalog = await repos["skill"].get_catalog(
            device_id="dev1", skills_filter=["skill_a"],
        )
        ids = {e["id"] for e in catalog}
        assert "skill_a" in ids       # 在过滤列表中
        assert "device_skill" in ids  # 设备自学习自动包含
        assert "skill_b" not in ids   # 不在过滤列表中

    @pytest.mark.asyncio
    async def test_list_skills_by_device(self, repos):
        """list_skills_by_device 返回指定设备的全部技能"""
        async with get_session_ctx() as session:
            session.add(SkillModel(
                skill_id="dev1_skill_1", name="s1", description="d1",
                body="b", device_id="dev1",
            ))
            session.add(SkillModel(
                skill_id="dev1_skill_2", name="s2", description="d2",
                body="b", device_id="dev1",
            ))
            session.add(SkillModel(
                skill_id="dev2_skill", name="s3", description="d3",
                body="b", device_id="dev2",
            ))

        result = await repos["skill"].list_skills_by_device("dev1")
        assert len(result) == 2
        ids = {e["id"] for e in result}
        assert ids == {"dev1_skill_1", "dev1_skill_2"}

    @pytest.mark.asyncio
    async def test_list_skills_by_device_empty(self, repos):
        """list_skills_by_device 无匹配返回空列表"""
        assert await repos["skill"].list_skills_by_device("nonexistent") == []

    @pytest.mark.asyncio
    async def test_list_skills_by_device_empty_id(self, repos):
        """空 device_id 返回空列表"""
        assert await repos["skill"].list_skills_by_device("") == []

    @pytest.mark.asyncio
    async def test_catalog_entry_structure(self, repos):
        """catalog 条目结构验证"""
        await repos["skill"].upsert_skill("skill1", _make_frontmatter(
            description="desc", category=["cat"], tags=["t1"],
        ), "body")
        catalog = await repos["skill"].get_catalog()
        assert set(catalog[0].keys()) == {"id", "description", "category", "tags", "device_id"}


# ============================================================
# SkillRepository init_sync 同步测试
# ============================================================

class TestSkillRepositoryInitSync:
    """init_sync 同步扫描磁盘 SKILL.md → DB"""

    def test_init_sync_global_skills(self, sync_skill_repo, tmp_path):
        """扫描全局技能目录并同步到 DB"""
        skills_root = tmp_path / "skills"
        _write_skill_md(
            str(skills_root / "weather"),
            _make_frontmatter(name="weather", description="天气查询", category=["生活"]),
            "## 天气查询\n\n使用工具查询天气。",
        )
        _write_skill_md(
            str(skills_root / "joke"),
            _make_frontmatter(name="joke", description="讲笑话", tags=["搞笑"]),
            "## 讲笑话\n\n讲一个笑话。",
        )

        sync_skill_repo.init_sync(str(skills_root))

        # 通过 sync session 验证
        from src.infrastructure.db.compat.sync_session import get_sync_session_factory
        factory = get_sync_session_factory()
        with factory() as session:
            result = session.execute(select(SkillModel))
            skills = result.scalars().all()
            assert len(skills) == 2
            skill_ids = {s.skill_id for s in skills}
            assert skill_ids == {"weather", "joke"}

            weather = next(s for s in skills if s.skill_id == "weather")
            assert weather.name == "weather"
            assert weather.description == "天气查询"
            assert weather.category == ["生活"]
            assert "天气查询" in weather.body
            assert weather.device_id == ""  # 全局技能
            assert weather.source == "builtin"
            assert weather.file_path.endswith("SKILL.md")
            assert weather.directory.endswith("weather")

    def test_init_sync_skips_dirs_without_skill_md(self, sync_skill_repo, tmp_path):
        """跳过没有 SKILL.md 的目录"""
        skills_root = tmp_path / "skills"
        _write_skill_md(
            str(skills_root / "valid"),
            _make_frontmatter(name="valid"),
            "body",
        )
        # 创建一个没有 SKILL.md 的目录
        (skills_root / "invalid").mkdir(parents=True)

        sync_skill_repo.init_sync(str(skills_root))

        from src.infrastructure.db.compat.sync_session import get_sync_session_factory
        factory = get_sync_session_factory()
        with factory() as session:
            result = session.execute(select(SkillModel))
            skills = result.scalars().all()
            assert len(skills) == 1
            assert skills[0].skill_id == "valid"

    def test_init_sync_skips_invalid_frontmatter(self, sync_skill_repo, tmp_path):
        """跳过 frontmatter 解析失败的 SKILL.md"""
        skills_root = tmp_path / "skills"
        _write_skill_md(
            str(skills_root / "good"),
            _make_frontmatter(name="good"),
            "good body",
        )
        # 写入一个 frontmatter 格式错误的 SKILL.md
        bad_dir = skills_root / "bad"
        bad_dir.mkdir(parents=True)
        with open(str(bad_dir / "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("---\n{invalid json}\n---\n\nbody")

        sync_skill_repo.init_sync(str(skills_root))

        from src.infrastructure.db.compat.sync_session import get_sync_session_factory
        factory = get_sync_session_factory()
        with factory() as session:
            result = session.execute(select(SkillModel))
            skills = result.scalars().all()
            assert len(skills) == 1
            assert skills[0].skill_id == "good"

    def test_init_sync_with_device_skills(self, sync_skill_repo, tmp_path):
        """扫描设备自学习技能目录"""
        skills_root = tmp_path / "skills"
        _write_skill_md(
            str(skills_root / "global_skill"),
            _make_frontmatter(name="global_skill"),
            "global body",
        )

        data_dir = tmp_path / "data"
        device_skills = data_dir / "devices" / "dev1" / "skills"
        _write_skill_md(
            str(device_skills / "learned_skill"),
            _make_frontmatter(name="learned_skill", description="学到的技能"),
            "learned body",
        )

        sync_skill_repo.init_sync(str(skills_root), str(data_dir))

        from src.infrastructure.db.compat.sync_session import get_sync_session_factory
        factory = get_sync_session_factory()
        with factory() as session:
            result = session.execute(select(SkillModel))
            skills = result.scalars().all()
            assert len(skills) == 2

            global_s = next(s for s in skills if s.skill_id == "global_skill")
            assert global_s.device_id == ""
            assert global_s.source == "builtin"

            device_s = next(s for s in skills if s.skill_id == "learned_skill")
            assert device_s.device_id == "dev1"
            assert device_s.source == "self_learning"
            assert device_s.description == "学到的技能"

    def test_init_sync_nonexistent_dir(self, sync_skill_repo, tmp_path):
        """不存在的目录不报错"""
        # 不应抛出异常
        sync_skill_repo.init_sync(str(tmp_path / "nonexistent"))
        sync_skill_repo.init_sync("", "")

    def test_init_sync_upsert_updates_existing(self, sync_skill_repo, tmp_path):
        """init_sync 幂等：多次同步不产生重复，且更新内容"""
        skills_root = tmp_path / "skills"
        skill_dir = skills_root / "my_skill"
        _write_skill_md(
            str(skill_dir),
            _make_frontmatter(name="my_skill", description="v1"),
            "body v1",
        )

        sync_skill_repo.init_sync(str(skills_root))

        # 修改 SKILL.md 后再次同步
        _write_skill_md(
            str(skill_dir),
            _make_frontmatter(name="my_skill", description="v2"),
            "body v2",
        )
        sync_skill_repo.init_sync(str(skills_root))

        from src.infrastructure.db.compat.sync_session import get_sync_session_factory
        factory = get_sync_session_factory()
        with factory() as session:
            result = session.execute(select(SkillModel))
            skills = result.scalars().all()
            assert len(skills) == 1  # 不重复
            assert skills[0].description == "v2"
            assert skills[0].body == "body v2"


# ============================================================
# SkillRepository 跨引擎测试（init_sync 写 + async 读）
# ============================================================

class TestSkillRepositoryCrossEngine:
    """init_sync（同步）写入后通过异步方法读取"""

    @pytest.mark.asyncio
    async def test_init_sync_then_async_get(self, shared_db, tmp_path):
        """init_sync 同步写入 → get_skill 异步读取"""
        skills_root = tmp_path / "skills"
        _write_skill_md(
            str(skills_root / "weather"),
            _make_frontmatter(
                name="weather",
                description="天气查询",
                category=["生活"],
                tags=["天气"],
            ),
            "## 天气查询技能\n\n使用工具查询天气。",
        )

        # 同步写入
        shared_db["skill"].init_sync(str(skills_root))

        # 异步读取
        skill = await shared_db["skill"].get_skill("weather")
        assert skill is not None
        assert skill["skill_id"] == "weather"
        assert skill["frontmatter"]["name"] == "weather"
        assert skill["frontmatter"]["description"] == "天气查询"
        assert skill["frontmatter"]["metadata"]["category"] == ["生活"]
        assert skill["frontmatter"]["metadata"]["tags"] == ["天气"]
        assert "天气查询技能" in skill["body"]
        assert skill["source"] == "builtin"

    @pytest.mark.asyncio
    async def test_init_sync_then_async_catalog(self, shared_db, tmp_path):
        """init_sync 同步写入 → get_catalog 异步读取"""
        skills_root = tmp_path / "skills"
        _write_skill_md(
            str(skills_root / "skill_a"),
            _make_frontmatter(name="skill_a", description="A"),
            "body a",
        )
        _write_skill_md(
            str(skills_root / "skill_b"),
            _make_frontmatter(name="skill_b", description="B"),
            "body b",
        )

        shared_db["skill"].init_sync(str(skills_root))

        catalog = await shared_db["skill"].get_catalog()
        assert len(catalog) == 2
        ids = {e["id"] for e in catalog}
        assert ids == {"skill_a", "skill_b"}

    @pytest.mark.asyncio
    async def test_init_sync_device_skill_then_async_list(self, shared_db, tmp_path):
        """init_sync 同步写入设备技能 → list_skills_by_device 异步读取"""
        skills_root = tmp_path / "skills"
        _write_skill_md(
            str(skills_root / "global"),
            _make_frontmatter(name="global"),
            "global body",
        )

        data_dir = tmp_path / "data"
        device_skills = data_dir / "devices" / "dev1" / "skills"
        _write_skill_md(
            str(device_skills / "learned"),
            _make_frontmatter(name="learned", description="学到的"),
            "learned body",
        )

        shared_db["skill"].init_sync(str(skills_root), str(data_dir))

        # 异步读取设备技能
        result = await shared_db["skill"].list_skills_by_device("dev1")
        assert len(result) == 1
        assert result[0]["id"] == "learned"
        assert result[0]["description"] == "学到的"
        assert result[0]["device_id"] == "dev1"

    @pytest.mark.asyncio
    async def test_init_sync_then_async_delete(self, shared_db, tmp_path):
        """init_sync 同步写入 → delete_skill 异步删除"""
        skills_root = tmp_path / "skills"
        _write_skill_md(
            str(skills_root / "deletable"),
            _make_frontmatter(name="deletable"),
            "body",
        )

        shared_db["skill"].init_sync(str(skills_root))

        # 异步删除
        assert await shared_db["skill"].delete_skill("deletable") is True
        assert await shared_db["skill"].get_skill("deletable") is None
