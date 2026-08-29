"""
growth/ 目录单元测试

覆盖范围：
- models：UserProfile / EmotionRecord / DiaryEntry / SkillCandidate / ConversationAnalysis 数据类
- emotion_analyzer：EmotionAnalyzer 情绪记录、历史加载/保存、时间线、摘要
- user_profile：UserProfileService 画像加载/保存、从分析更新、摘要
- diary_service：DiaryService 日记写入、读取、索引、技能创建
- self_learning：SelfLearningService 对话分析、技能评估、创建/合并、JSON解析
- growth_system：GrowthSystem 协调器、对话结束处理、格式化、记忆查找
"""
import asyncio
import json
import os
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.infrastructure.db.base import Base
from src.plugins.growth.engine.models import (
    ConversationAnalysis,
    DiaryEntry,
    EmotionRecord,
    SkillCandidate,
    UserProfile,
)
from src.plugins.growth.engine.diary_service import DiaryService
from src.plugins.growth.engine.emotion_analyzer import EmotionAnalyzer, EMOTION_LABELS
from src.plugins.growth.engine.growth_system import GrowthSystem
from src.plugins.growth.engine.self_learning import SelfLearningService
from src.plugins.growth.engine.user_profile import UserProfileService


# ============================================================
# 阶段 3：业务层已切换到 DB 仓储，这里用 AsyncMock 替换模块级仓储单例，
# 避免单测依赖真实数据库。需要预置数据的用例直接覆盖对应 mock 的返回值。
# ============================================================


@pytest.fixture(autouse=True)
def _mock_growth_repos(monkeypatch):
    from src.plugins.growth.engine import user_profile as _up
    from src.plugins.growth.engine import emotion_analyzer as _ea
    from src.plugins.growth.engine import self_learning as _sl

    prof = MagicMock()
    prof.get = AsyncMock(return_value={})
    prof.upsert = AsyncMock()

    emo = MagicMock()
    emo.list_all = AsyncMock(return_value=[])
    emo.append = AsyncMock()

    learn = MagicMock()
    learn.append = AsyncMock()

    monkeypatch.setattr(_up, "_profile_repo", prof)
    monkeypatch.setattr(_ea, "_emotion_repo", emo)
    monkeypatch.setattr(_sl, "_learning_log_repo", learn)


# ============================================================
# models 数据类（同步测试）
# ============================================================


class TestUserProfile:
    """UserProfile 数据类"""

    def test_defaults(self):
        p = UserProfile(device_id="d1")
        assert p.device_id == "d1"
        assert p.name == ""
        assert p.family == []
        assert p.interests == {}

    def test_to_dict_roundtrip(self):
        p = UserProfile(device_id="d1", name="张三", occupation="工程师")
        p.interests["likes"] = ["音乐"]
        d = p.to_dict()
        assert d["device_id"] == "d1"
        assert d["name"] == "张三"
        p2 = UserProfile.from_dict(d)
        assert p2.name == "张三"
        assert p2.interests["likes"] == ["音乐"]

    def test_from_dict_ignores_unknown_keys(self):
        p = UserProfile.from_dict({"device_id": "d1", "unknown_key": "x"})
        assert p.device_id == "d1"


class TestEmotionRecord:
    """EmotionRecord 数据类"""

    def test_defaults(self):
        r = EmotionRecord(timestamp=1.0, emotion="happy", intensity=0.5, trigger="t", context="c")
        assert r.speaker == "user"

    def test_to_dict_roundtrip(self):
        r = EmotionRecord(timestamp=1.0, emotion="happy", intensity=0.8, trigger="t", context="c")
        d = r.to_dict()
        r2 = EmotionRecord.from_dict(d)
        assert r2.emotion == "happy"
        assert r2.intensity == 0.8


class TestDiaryEntry:
    """DiaryEntry 数据类"""

    def test_to_dict_roundtrip(self):
        e = DiaryEntry(date="2026-01-01", content="内容")
        d = e.to_dict()
        e2 = DiaryEntry.from_dict(d)
        assert e2.date == "2026-01-01"
        assert e2.content == "内容"


class TestSkillCandidate:
    """SkillCandidate 数据类"""

    def test_to_dict_roundtrip(self):
        c = SkillCandidate(title="t", content="c", category="cat")
        d = c.to_dict()
        c2 = SkillCandidate.from_dict(d)
        assert c2.title == "t"


class TestConversationAnalysis:
    """ConversationAnalysis 数据类"""

    def test_defaults(self):
        a = ConversationAnalysis()
        assert a.user_info == {}
        assert a.skill_candidate is None

    def test_to_dict_with_skill_candidate(self):
        sc = SkillCandidate(title="t", content="c", category="cat")
        a = ConversationAnalysis(skill_candidate=sc, conversation_summary="摘要")
        d = a.to_dict()
        assert d["skill_candidate"]["title"] == "t"
        assert d["conversation_summary"] == "摘要"

    def test_to_dict_without_skill_candidate(self):
        a = ConversationAnalysis()
        d = a.to_dict()
        assert d["skill_candidate"] is None


# ============================================================
# EmotionAnalyzer（异步测试）
# ============================================================


async def _make_ea_with_history(tmp_path, device_id="d1", records_data=None):
    """创建 EmotionAnalyzer 并预置历史（通过 mock 仓储），确保缓存正确初始化。

    阶段 3 后历史持久化由 DB 仓储负责，这里通过覆盖 ``_emotion_repo.list_all``
    的返回值预置历史，再触发 ``load_history`` 填充缓存。
    """
    from src.plugins.growth.engine import emotion_analyzer as _ea
    if records_data is not None:
        _ea._emotion_repo.list_all = AsyncMock(return_value=list(records_data))
    ea = EmotionAnalyzer(str(tmp_path))
    await ea.load_history(device_id)
    return ea


class TestEmotionAnalyzer:
    """EmotionAnalyzer 情绪分析"""

    async def test_load_history_empty(self, tmp_path):
        ea = EmotionAnalyzer(str(tmp_path))
        records = await ea.load_history("d1")
        assert records == []

    async def test_load_history_from_file(self, tmp_path):
        from src.plugins.growth.engine import emotion_analyzer as _ea
        _ea._emotion_repo.list_all = AsyncMock(return_value=[
            {"timestamp": 1.0, "emotion": "happy", "intensity": 0.8, "trigger": "t", "context": "c"},
        ])
        ea = EmotionAnalyzer(str(tmp_path))
        records = await ea.load_history("d1")
        assert len(records) == 1
        assert records[0].emotion == "happy"

    async def test_load_history_uses_cache(self, tmp_path):
        # 从文件加载后缓存应生效（同一对象）
        ea = await _make_ea_with_history(tmp_path, records_data=[
            {"timestamp": 1.0, "emotion": "happy", "intensity": 0.5, "trigger": "", "context": ""},
        ])
        first = await ea.load_history("d1")
        second = await ea.load_history("d1")
        assert first is second

    async def test_load_history_db_empty(self, tmp_path):
        """DB 无记录时返回空列表"""
        ea = EmotionAnalyzer(str(tmp_path))
        records = await ea.load_history("d1")
        assert records == []

    async def test_record_emotion(self, tmp_path):
        ea = await _make_ea_with_history(tmp_path)
        record = await ea.record_emotion("d1", {"current": "happy", "intensity": 0.9, "trigger": "test"}, "context")
        assert record.emotion == "happy"
        assert record.intensity == 0.9
        # 阶段 3：持久化改为 DB 仓储（append），此处验证内存缓存已更新
        records = await ea.load_history("d1")
        assert len(records) >= 1

    async def test_record_emotion_truncates_context(self, tmp_path):
        ea = await _make_ea_with_history(tmp_path)
        long_ctx = "x" * 500
        record = await ea.record_emotion("d1", {"current": "sad"}, long_ctx)
        assert len(record.context) == 200

    async def test_record_emotion_max_records(self, tmp_path):
        ea = await _make_ea_with_history(tmp_path, device_id="d1")
        ea._max_records = 3
        for i in range(5):
            await ea.record_emotion("d1", {"current": "happy"})
        records = await ea.load_history("d1")
        assert len(records) <= 3

    async def test_save_history_no_records(self, tmp_path):
        ea = EmotionAnalyzer(str(tmp_path))
        await ea.save_history("d1")
        assert not os.path.exists(ea._get_history_path("d1"))

    async def test_get_today_emotions(self, tmp_path):
        ea = await _make_ea_with_history(tmp_path)
        await ea.record_emotion("d1", {"current": "happy"})
        today = await ea.get_today_emotions("d1")
        assert len(today) == 1

    async def test_get_emotion_timeline_empty(self, tmp_path):
        ea = EmotionAnalyzer(str(tmp_path))
        timeline = await ea.get_emotion_timeline("d1")
        assert "还没有情绪记录" in timeline

    async def test_get_emotion_timeline_with_records(self, tmp_path):
        ea = await _make_ea_with_history(tmp_path)
        await ea.record_emotion("d1", {"current": "happy", "trigger": "测试"}, "ctx")
        timeline = await ea.get_emotion_timeline("d1")
        assert "开心" in timeline
        assert "测试" in timeline

    async def test_get_emotion_summary_empty(self, tmp_path):
        ea = EmotionAnalyzer(str(tmp_path))
        summary = await ea.get_emotion_summary("d1")
        assert summary["dominant"] == "neutral"
        assert summary["count"] == 0

    async def test_get_emotion_summary_with_records(self, tmp_path):
        ea = await _make_ea_with_history(tmp_path)
        await ea.record_emotion("d1", {"current": "happy"})
        await ea.record_emotion("d1", {"current": "sad"})
        summary = await ea.get_emotion_summary("d1")
        assert summary["count"] == 2
        assert summary["trend"] == "declining"

    async def test_get_emotion_summary_improving(self, tmp_path):
        ea = await _make_ea_with_history(tmp_path)
        await ea.record_emotion("d1", {"current": "sad"})
        await ea.record_emotion("d1", {"current": "happy"})
        summary = await ea.get_emotion_summary("d1")
        assert summary["trend"] == "improving"

    async def test_get_emotion_summary_stable_single(self, tmp_path):
        ea = await _make_ea_with_history(tmp_path)
        await ea.record_emotion("d1", {"current": "happy"})
        summary = await ea.get_emotion_summary("d1")
        assert summary["trend"] == "stable"

    async def test_get_recent_emotions(self, tmp_path):
        ea = await _make_ea_with_history(tmp_path)
        await ea.record_emotion("d1", {"current": "happy"})
        recent = await ea.get_recent_emotions("d1", days=7)
        assert len(recent) == 1

    def test_emotion_labels(self):
        assert EMOTION_LABELS["happy"] == "开心"
        assert EMOTION_LABELS["sad"] == "难过"


# ============================================================
# UserProfileService
# ============================================================


class TestUserProfileService:
    """UserProfileService 用户画像"""

    async def test_get_profile_new(self, tmp_path):
        svc = UserProfileService(str(tmp_path))
        profile = await svc.get_profile("d1")
        assert profile.device_id == "d1"
        assert profile.name == ""

    async def test_get_profile_from_file(self, tmp_path):
        from src.plugins.growth.engine import user_profile as _up
        _up._profile_repo.get = AsyncMock(return_value={
            "device_id": "d1", "name": "张三", "occupation": "工程师",
        })
        svc = UserProfileService(str(tmp_path))
        profile = await svc.get_profile("d1")
        assert profile.name == "张三"

    async def test_get_profile_uses_cache(self, tmp_path):
        svc = UserProfileService(str(tmp_path))
        first = await svc.get_profile("d1")
        second = await svc.get_profile("d1")
        assert first is second

    async def test_get_profile_db_empty(self, tmp_path):
        """DB 无记录时返回默认空 profile"""
        svc = UserProfileService(str(tmp_path))
        profile = await svc.get_profile("d1")
        assert profile.device_id == "d1"

    async def test_save_profile(self, tmp_path):
        from src.plugins.growth.engine import user_profile as _up
        svc = UserProfileService(str(tmp_path))
        await svc.get_profile("d1")
        await svc.save_profile("d1")
        # 阶段 3：保存改为调用仓储 upsert，验证仓储被调用
        _up._profile_repo.upsert.assert_called_once()

    async def test_save_profile_no_profile(self, tmp_path):
        svc = UserProfileService(str(tmp_path))
        await svc.save_profile("d1")

    async def test_update_from_analysis_name(self, tmp_path):
        svc = UserProfileService(str(tmp_path))
        analysis = {"user_info": {"new_facts": ["我叫张三"]}}
        profile = await svc.update_from_analysis("d1", analysis)
        assert profile.name == "张三"

    async def test_update_from_analysis_birthday(self, tmp_path):
        svc = UserProfileService(str(tmp_path))
        analysis = {"user_info": {"new_facts": ["生日是2020-01-01"]}}
        profile = await svc.update_from_analysis("d1", analysis)
        assert profile.birthday == "2020-01-01"

    async def test_update_from_analysis_occupation(self, tmp_path):
        svc = UserProfileService(str(tmp_path))
        analysis = {"user_info": {"new_facts": ["我做程序员工作"]}}
        profile = await svc.update_from_analysis("d1", analysis)
        assert "程序员" in profile.occupation

    async def test_update_from_analysis_preferences(self, tmp_path):
        svc = UserProfileService(str(tmp_path))
        analysis = {"user_info": {"preferences": ["喜欢音乐", "讨厌噪音"]}}
        profile = await svc.update_from_analysis("d1", analysis)
        # "喜欢音乐" 应被识别为 likes
        assert "音乐" in profile.interests["likes"]
        # "讨厌噪音" 不含"喜欢"子串，应被识别为 dislikes
        assert "噪音" in profile.interests["dislikes"]

    async def test_update_from_analysis_concerns(self, tmp_path):
        svc = UserProfileService(str(tmp_path))
        analysis = {"user_info": {"concerns": ["工作压力"]}, "emotion": {"current": "anxious", "trigger": "加班"}}
        profile = await svc.update_from_analysis("d1", analysis)
        assert profile.current_state["concerns"] == ["工作压力"]
        assert profile.current_state["last_emotion"] == "anxious"

    async def test_get_profile_summary_empty(self, tmp_path):
        svc = UserProfileService(str(tmp_path))
        summary = await svc.get_profile_summary("d1")
        assert summary == "暂无用户信息"

    async def test_get_profile_summary_with_data(self, tmp_path):
        svc = UserProfileService(str(tmp_path))
        profile = await svc.get_profile("d1")
        profile.name = "张三"
        profile.occupation = "工程师"
        summary = await svc.get_profile_summary("d1")
        assert "张三" in summary
        assert "工程师" in summary

    def test_extract_name_patterns(self, tmp_path):
        svc = UserProfileService(str(tmp_path))
        assert svc._extract_name("我叫李四") == "李四"
        assert svc._extract_name("叫我小明就好") == "小明"

    def test_extract_date(self, tmp_path):
        svc = UserProfileService(str(tmp_path))
        assert svc._extract_date("生日2020-01-01") == "2020-01-01"

    def test_update_family(self, tmp_path):
        svc = UserProfileService(str(tmp_path))
        profile = UserProfile(device_id="d1")
        svc._update_family(profile, "我老婆叫小花")
        assert any("老婆" in f for f in profile.family)


# ============================================================
# DiaryService
# ============================================================


class TestDiaryService:
    """DiaryService 日记服务（DB 持久化，使用内存 SQLite）"""

    @pytest_asyncio.fixture
    async def diary_db(self, monkeypatch):
        """内存 SQLite（:memory: + StaticPool），覆盖全局异步 session factory

        参考 tests/test_growth_emo_skill_repos.py 的夹具模式。
        """
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            echo=False,
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async_factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
        )
        import src.infrastructure.db.engine as engine_mod
        monkeypatch.setattr(engine_mod, "_async_engine", engine)
        monkeypatch.setattr(engine_mod, "_async_session_factory", async_factory)
        yield
        await engine.dispose()

    async def _seed_entry(self, device_id: str, date: str, content: str):
        """直接通过仓储预置一条日记"""
        from src.infrastructure.db.repositories.growth_repositories import DiaryRepository
        await DiaryRepository().upsert_entry(device_id, date, content)

    async def test_device_isolation(self, tmp_path, diary_db):
        """日记按设备隔离（原 test_get_diary_dir：按设备分目录存储）"""
        ds = DiaryService(str(tmp_path))
        today = datetime.now().strftime("%Y-%m-%d")
        await self._seed_entry("d1", today, "d1的日记")
        assert await ds.get_today_entry("d1") == "d1的日记"
        assert await ds.get_today_entry("d2") is None

    async def test_get_today_entry_none(self, tmp_path, diary_db):
        ds = DiaryService(str(tmp_path))
        result = await ds.get_today_entry("d1")
        assert result is None

    async def test_get_today_entry_exists(self, tmp_path, diary_db):
        ds = DiaryService(str(tmp_path))
        today = datetime.now().strftime("%Y-%m-%d")
        await self._seed_entry("d1", today, "今天的日记")
        result = await ds.get_today_entry("d1")
        assert result == "今天的日记"

    async def test_write_daily_entry_no_llm(self, tmp_path, diary_db):
        ds = DiaryService(str(tmp_path))
        result = await ds.write_daily_entry("d1", "profile", "convs", "timeline", "understanding")
        assert result is None

    async def test_write_daily_entry_with_llm(self, tmp_path, diary_db):
        llm = AsyncMock(return_value="今天很开心的日记内容")
        ds = DiaryService(str(tmp_path), llm_call_func=llm)
        result = await ds.write_daily_entry("d1", "", "convs", "timeline", "")
        assert result == "今天很开心的日记内容"
        today = datetime.now().strftime("%Y-%m-%d")
        content = await ds.get_diary_content("d1", today)
        assert content == "今天很开心的日记内容"

    async def test_write_daily_entry_continuation(self, tmp_path, diary_db):
        llm = AsyncMock(return_value="追加的内容")
        ds = DiaryService(str(tmp_path), llm_call_func=llm)
        today = datetime.now().strftime("%Y-%m-%d")
        await self._seed_entry("d1", today, "已有内容")
        result = await ds.write_daily_entry("d1", "", "convs", "timeline", "", is_continuation=True)
        assert result == "追加的内容"
        content = await ds.get_diary_content("d1", today)
        assert "已有内容" in content
        assert "追加的内容" in content

    async def test_write_daily_entry_llm_fails(self, tmp_path, diary_db):
        llm = AsyncMock(side_effect=Exception("LLM error"))
        ds = DiaryService(str(tmp_path), llm_call_func=llm)
        result = await ds.write_daily_entry("d1", "", "convs", "timeline", "")
        assert result is None

    async def test_get_recent_diaries_empty(self, tmp_path, diary_db):
        ds = DiaryService(str(tmp_path))
        result = await ds._get_recent_diaries("d1")
        assert result == "还没有日记"

    async def test_get_recent_diaries_with_entries(self, tmp_path, diary_db):
        ds = DiaryService(str(tmp_path))
        await self._seed_entry("d1", "2026-01-01", "日记1")
        await self._seed_entry("d1", "2026-01-02", "日记2")
        result = await ds._get_recent_diaries("d1", limit=2)
        assert "日记1" in result or "日记2" in result

    async def test_get_diary_content(self, tmp_path, diary_db):
        ds = DiaryService(str(tmp_path))
        await self._seed_entry("d1", "2026-01-01", "内容")
        result = await ds.get_diary_content("d1", "2026-01-01")
        assert result == "内容"

    async def test_get_diary_content_not_found(self, tmp_path, diary_db):
        ds = DiaryService(str(tmp_path))
        result = await ds.get_diary_content("d1", "2026-01-01")
        assert result is None

    async def test_get_all_entries_empty(self, tmp_path, diary_db):
        ds = DiaryService(str(tmp_path))
        entries = await ds.get_all_entries("d1")
        assert entries == []

    async def test_get_all_entries_with_data(self, tmp_path, diary_db):
        ds = DiaryService(str(tmp_path))
        await self._seed_entry("d1", "2026-01-01", "a")
        await self._seed_entry("d1", "2026-01-02", "b")
        entries = await ds.get_all_entries("d1")
        assert len(entries) == 2

    def test_extract_name_from_profile(self, tmp_path):
        ds = DiaryService(str(tmp_path))
        assert ds._extract_name_from_profile("名字：张三\n其他") == "张三"
        assert ds._extract_name_from_profile("") == ""
        assert ds._extract_name_from_profile("暂无用户信息") == ""


# ============================================================
# SelfLearningService
# ============================================================


class TestSelfLearningService:
    """SelfLearningService 自学习"""

    async def test_analyze_no_llm(self, tmp_path):
        svc = SelfLearningService(str(tmp_path))
        result = await svc.analyze_conversation([{"role": "user", "content": "hi"}])
        assert result == {}

    async def test_analyze_empty_messages(self, tmp_path):
        llm = AsyncMock()
        svc = SelfLearningService(str(tmp_path), llm_call_func=llm)
        result = await svc.analyze_conversation([])
        assert result == {}
        llm.assert_not_called()

    async def test_analyze_with_llm(self, tmp_path):
        llm = AsyncMock(return_value='{"emotion": {"current": "happy"}}')
        svc = SelfLearningService(str(tmp_path), llm_call_func=llm)
        result = await svc.analyze_conversation([{"role": "user", "content": "hi"}])
        assert result["emotion"]["current"] == "happy"

    async def test_analyze_llm_returns_empty(self, tmp_path):
        llm = AsyncMock(return_value="")
        svc = SelfLearningService(str(tmp_path), llm_call_func=llm)
        result = await svc.analyze_conversation([{"role": "user", "content": "hi"}])
        assert result == {}

    def test_parse_json_valid(self):
        assert SelfLearningService._parse_json('{"a": 1}') == {"a": 1}

    def test_parse_json_empty(self):
        assert SelfLearningService._parse_json("") == {}

    def test_parse_json_invalid(self):
        assert SelfLearningService._parse_json("not json") == {}

    def test_parse_json_with_codeblock(self):
        text = '```json\n{"a": 1}\n```'
        assert SelfLearningService._parse_json(text) == {"a": 1}

    def test_parse_json_extracts_from_text(self):
        text = 'prefix {"a": 1} suffix'
        assert SelfLearningService._parse_json(text) == {"a": 1}

    async def test_evaluate_skill_creation_no_title(self, tmp_path):
        svc = SelfLearningService(str(tmp_path))
        result = await svc.evaluate_skill_creation("d1", {})
        assert result is None

    async def test_evaluate_skill_creation_skip(self, tmp_path):
        llm = AsyncMock(return_value='{"action": "skip", "reason": "no"}')
        svc = SelfLearningService(str(tmp_path), llm_call_func=llm)
        result = await svc.evaluate_skill_creation("d1", {"title": "t"})
        assert result is None

    async def test_evaluate_skill_creation_create(self, tmp_path):
        llm = AsyncMock(return_value='{"action": "create_new", "new_skill_name": "test_skill", "category": "cat"}')
        svc = SelfLearningService(str(tmp_path), llm_call_func=llm)
        result = await svc.evaluate_skill_creation("d1", {"title": "t"})
        assert result["action"] == "create_new"

    async def test_evaluate_skill_creation_llm_fails(self, tmp_path):
        llm = AsyncMock(side_effect=Exception("err"))
        svc = SelfLearningService(str(tmp_path), llm_call_func=llm)
        result = await svc.evaluate_skill_creation("d1", {"title": "t"})
        assert result is None

    async def test_create_or_merge_skip(self, tmp_path):
        svc = SelfLearningService(str(tmp_path))
        result = await svc.create_or_merge_skill("d1", {}, {"action": "skip"})
        assert result is None

    async def test_create_new_skill(self, tmp_path):
        llm = AsyncMock(return_value="生成的技能内容")
        svc = SelfLearningService(str(tmp_path), llm_call_func=llm)
        result = await svc._create_new_skill("d1", {"title": "t", "content": "c", "tags": []}, {"new_skill_name": "new_skill", "category": "cat"})
        assert result == "new_skill"
        skill_path = tmp_path / "devices" / "d1" / "skills" / "new_skill" / "SKILL.md"
        assert skill_path.exists()

    def test_generate_skill_name(self, tmp_path):
        svc = SelfLearningService(str(tmp_path))
        name = svc._generate_skill_name("Hello World!")
        assert name == "hello_world"

    def test_generate_skill_name_empty(self, tmp_path):
        svc = SelfLearningService(str(tmp_path))
        name = svc._generate_skill_name("")
        assert name.startswith("skill_")

    async def test_get_existing_skills_empty(self, tmp_path):
        svc = SelfLearningService(str(tmp_path))
        result = await svc._get_existing_skills("d1")
        assert result == []

    async def test_get_existing_skills_with_data(self, tmp_path):
        svc = SelfLearningService(str(tmp_path))
        skill_dir = tmp_path / "devices" / "d1" / "skills" / "test_skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            '---\n{"name": "test_skill", "description": "d"}\n---\n\nbody', encoding="utf-8"
        )
        result = await svc._get_existing_skills("d1")
        assert len(result) == 1
        assert result[0]["id"] == "test_skill"


# ============================================================
# GrowthSystem
# ============================================================


class TestGrowthSystem:
    """GrowthSystem 协调器"""

    def _make_system(self, tmp_path):
        llm = AsyncMock(return_value='{"user_info": {}, "emotion": {"current": "happy"}, "conversation_summary": "摘要"}')
        return GrowthSystem(data_dir=str(tmp_path), llm_call_func=llm)

    def test_init(self, tmp_path):
        gs = self._make_system(tmp_path)
        assert gs.user_profile is not None
        assert gs.emotion is not None
        assert gs.diary is not None
        assert gs.learning is not None

    def test_format_conversations_empty(self, tmp_path):
        gs = self._make_system(tmp_path)
        result = gs._format_conversations([])
        assert result == "今天还没有对话"

    def test_format_conversations_with_messages(self, tmp_path):
        gs = self._make_system(tmp_path)
        today = datetime.now().strftime("%Y-%m-%d")
        msgs = [
            {"role": "user", "content": "你好", "datetime": f"{today} 10:00:00"},
            {"role": "assistant", "content": "你好呀", "datetime": f"{today} 10:01:00"},
        ]
        result = gs._format_conversations(msgs)
        assert "用户: 你好" in result
        assert "AI: 你好呀" in result

    def test_format_conversations_old_date(self, tmp_path):
        gs = self._make_system(tmp_path)
        msgs = [{"role": "user", "content": "旧消息", "datetime": "2020-01-01 10:00:00"}]
        result = gs._format_conversations(msgs)
        assert result == "今天还没有对话"

    def test_extract_name_from_text(self, tmp_path):
        gs = self._make_system(tmp_path)
        name = gs._extract_name_from_text("我叫小明。", "我叫")
        assert name == "小明"

    def test_extract_name_too_long(self, tmp_path):
        gs = self._make_system(tmp_path)
        name = gs._extract_name_from_text("我叫这是一个很长的名字不是真正的名字", "我叫")
        assert name == ""

    async def test_find_user_name_from_memory_no_service(self, tmp_path):
        gs = self._make_system(tmp_path)
        gs._memory_service = None
        result = await gs._find_user_name_from_memory("d1")
        assert result == ""

    async def test_find_user_name_from_memory_with_service(self, tmp_path):
        gs = self._make_system(tmp_path)
        mem = MagicMock()
        mem_item = MagicMock()
        mem_item.content = "我叫张三"
        mem.list_all = AsyncMock(return_value=[mem_item])
        gs._memory_service = mem
        result = await gs._find_user_name_from_memory("d1")
        assert result == "张三"

    async def test_get_user_understanding_empty(self, tmp_path):
        gs = self._make_system(tmp_path)
        result = await gs._get_user_understanding("d1")
        assert "还不太了解" in result

    async def test_get_user_understanding_with_profile(self, tmp_path):
        gs = self._make_system(tmp_path)
        profile = await gs.user_profile.get_profile("d1")
        profile.name = "张三"
        profile.occupation = "工程师"
        result = await gs._get_user_understanding("d1")
        assert "张三" in result
        assert "工程师" in result

    async def test_on_conversation_end(self, tmp_path):
        gs = self._make_system(tmp_path)
        await gs.on_conversation_end("d1", [{"role": "user", "content": "hi"}])
        assert "d1" in gs._pending_tasks

    async def test_on_conversation_end_existing_running(self, tmp_path):
        gs = self._make_system(tmp_path)
        gs._pending_tasks["d1"] = MagicMock()
        gs._pending_tasks["d1"].done.return_value = False
        await gs.on_conversation_end("d1", [{"role": "user", "content": "hi"}])
        # 不应替换已有任务

    async def test_get_device_growth_summary(self, tmp_path):
        gs = self._make_system(tmp_path)
        summary = await gs.get_device_growth_summary("d1")
        assert "user_name" in summary
        assert "diary_count" in summary
        assert "emotion_summary" in summary
        assert "interests" in summary

    async def test_store_memories_no_service(self, tmp_path):
        gs = self._make_system(tmp_path)
        gs._memory_service = None
        await gs._store_memories("d1", [{"content": "x"}])
        # 不应抛异常

    async def test_store_memories_with_service(self, tmp_path):
        gs = self._make_system(tmp_path)
        mem = MagicMock()
        mem.store = AsyncMock()
        gs._memory_service = mem
        await gs._store_memories("d1", [{"content": "x", "tags": ["t"]}])
        mem.store.assert_called_once()

    async def test_store_memories_empty_content(self, tmp_path):
        gs = self._make_system(tmp_path)
        mem = MagicMock()
        mem.store = AsyncMock()
        gs._memory_service = mem
        await gs._store_memories("d1", [{"content": ""}])
        mem.store.assert_not_called()
