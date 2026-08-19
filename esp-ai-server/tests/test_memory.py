"""
memory.py 单元测试

覆盖类：
- LongTermMemoryServiceImpl：store / recall / list_all / update / forget /
  get_summary_catalog / auto_extract / _normalize_tags / _normalize_keywords /
  _parse_llm_json
- ConversationMemory：基础消息管理（补充现有测试）
- 辅助函数：_normalize_memory_key / _items_semantically_match

通过自定义 FakeLTMRepository（实现 LongTermMemoryRepository 接口）
避免真实文件 IO，所有测试可在内存中完成。
"""
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.entities import MemoryItem
from src.domain.value_objects import MemoryQuery
from src.use_cases.memory import (
    ConversationMemory,
    LongTermMemoryServiceImpl,
    _items_semantically_match,
    _normalize_memory_key,
)


# ============================================================
# FakeLTMRepository：内存版仓储实现
# ============================================================


class FakeLTMRepository:
    """实现 LongTermMemoryRepository 接口的内存仓储，便于测试"""

    def __init__(self):
        self._storage: dict[str, list[MemoryItem]] = {}  # device_id -> items
        self._access_counts: dict[str, int] = {}  # memory_id -> count

    async def save(self, item: MemoryItem) -> None:
        self._storage.setdefault(item.device_id, []).append(item)

    async def find_by_labels(self, device_id, summary_labels, limit):
        items = [i for i in self._storage.get(device_id, []) if not i.deleted]
        matched = []
        for item in items:
            if any(lb in item.tags for lb in summary_labels):
                matched.append(item)
        # 按 access_count 降序
        matched.sort(key=lambda i: self._access_counts.get(i.memory_id, 0), reverse=True)
        return matched[:limit]

    async def find_all(self, device_id):
        return [i for i in self._storage.get(device_id, []) if not i.deleted]

    async def find_by_id(self, memory_id, device_id):
        for item in self._storage.get(device_id, []):
            if item.memory_id == memory_id:
                return item
        return None

    async def mark_deleted(self, memory_id, device_id):
        for item in self._storage.get(device_id, []):
            if item.memory_id == memory_id:
                item.deleted = True

    async def get_summary_labels(self, device_id):
        labels = set()
        for item in self._storage.get(device_id, []):
            if not item.deleted:
                labels.update(item.tags[:3])
        return list(labels)

    async def increment_access(self, memory_id, device_id):
        self._access_counts[memory_id] = self._access_counts.get(memory_id, 0) + 1

    async def get_storage_dir(self):
        return "/tmp/fake"


# ============================================================
# 辅助函数测试
# ============================================================


class TestNormalizeMemoryKey:
    """_normalize_memory_key：归一化记忆内容为语义 key"""

    def test_empty_text(self):
        assert _normalize_memory_key("") == ""

    def test_basic_normalization(self):
        # 去标点、小写
        assert _normalize_memory_key("Hello, World!") == "hello world"

    def test_chinese_text(self):
        # 中文标点应被去除
        key = _normalize_memory_key("你好，世界。")
        assert "你好" in key
        assert "，" not in key

    def test_truncation_to_36_chars(self):
        long_text = "a" * 100
        assert len(_normalize_memory_key(long_text)) == 36

    def test_whitespace_stripped(self):
        assert _normalize_memory_key("  hello  ") == "hello"

    def test_mixed_case(self):
        assert _normalize_memory_key("HeLLo") == "hello"


class TestItemsSemanticallyMatch:
    """_items_semantically_match：语义去重检测"""

    def test_identical_content_matches(self):
        a = MemoryItem(content="我喜欢吃苹果")
        b = MemoryItem(content="我喜欢吃苹果")
        assert _items_semantically_match(a, b) is True

    def test_different_content_no_match(self):
        a = MemoryItem(content="我喜欢吃苹果")
        b = MemoryItem(content="我喜欢打篮球")
        assert _items_semantically_match(a, b) is False

    def test_empty_content_no_match(self):
        a = MemoryItem(content="")
        b = MemoryItem(content="hello")
        assert _items_semantically_match(a, b) is False

    def test_substring_match_long_enough(self):
        # 长度 >= 12 时检查子串包含（用英文确保字符数 >= 12）
        a = MemoryItem(content="the user likes eating apples and bananas")
        b = MemoryItem(content="the user likes eating apples")
        # key_b 是 key_a 的子串，且两者长度均 >= 12
        assert _items_semantically_match(a, b) is True

    def test_substring_match_long_enough_chinese(self):
        # 中文也需要归一化后长度 >= 12 才检查子串
        a = MemoryItem(content="用户非常喜欢吃红色的苹果和黄色的香蕉还有西瓜")
        b = MemoryItem(content="用户非常喜欢吃红色的苹果和黄色的香蕉")
        assert _items_semantically_match(a, b) is True

    def test_short_content_no_substring_check(self):
        # 长度 < 12 时不检查子串
        a = MemoryItem(content="短文本")
        b = MemoryItem(content="短文本a")
        # 归一化后 key 不同，且长度不足 12，不检查子串
        assert _items_semantically_match(a, b) is False

    def test_punctuation_normalized_for_match(self):
        a = MemoryItem(content="Hello, World!")
        b = MemoryItem(content="hello world")
        assert _items_semantically_match(a, b) is True


# ============================================================
# LongTermMemoryServiceImpl
# ============================================================


class TestLongTermMemoryStore:
    """store：存储 + 去重 + ID 生成"""

    async def test_store_new_item(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        item = MemoryItem(device_id="d1", content="我喜欢蓝色", tags=["颜色偏好"])
        memory_id, changed = await svc.store(item)
        assert changed is True
        assert memory_id.startswith("mem-")
        assert item.memory_id == memory_id
        assert item.source == "manual"

    async def test_store_assigns_memory_id_if_missing(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        item = MemoryItem(device_id="d1", content="test", tags=["t"])
        memory_id, _ = await svc.store(item)
        assert memory_id  # 非空
        assert item.memory_id == memory_id

    async def test_store_preserves_existing_memory_id(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        item = MemoryItem(memory_id="custom-id", device_id="d1", content="test", tags=["t"])
        memory_id, _ = await svc.store(item)
        assert memory_id == "custom-id"

    async def test_store_empty_content_raises(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        item = MemoryItem(device_id="d1", content="")
        with pytest.raises(ValueError, match="content is required"):
            await svc.store(item)

    async def test_store_dedup_returns_existing(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        item1 = MemoryItem(device_id="d1", content="我喜欢蓝色", tags=["颜色"])
        id1, changed1 = await svc.store(item1)

        # 语义相同的内容应去重
        item2 = MemoryItem(device_id="d1", content="我喜欢蓝色", tags=["颜色"])
        id2, changed2 = await svc.store(item2)

        assert id1 == id2
        assert changed2 is False

    async def test_store_normalizes_tags_dedup_and_limit(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        # 重复 tag + 超过 3 个
        item = MemoryItem(
            device_id="d1", content="test",
            tags=["a", "a", "b", "c", "d"],
        )
        await svc.store(item)
        assert item.tags == ["a", "b", "c"]  # 去重 + 限制 3 个

    async def test_store_normalizes_keywords_from_content(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        item = MemoryItem(
            device_id="d1", content="我喜欢吃苹果",
            tags=["饮食"], keywords=["苹果", "香蕉"],
        )
        # "香蕉" 不在 content 也不在 tags，应被过滤；"苹果" 在 content 保留
        await svc.store(item)
        assert "苹果" in item.keywords
        assert "香蕉" not in item.keywords

    async def test_store_keywords_fallback_to_tags_when_empty(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        item = MemoryItem(
            device_id="d1", content="测试内容", tags=["标签1", "标签2"],
            keywords=[],
        )
        await svc.store(item)
        # keywords 为空时回退到 tags 前 3 个
        assert item.keywords == ["标签1", "标签2"]

    async def test_store_sets_source_default(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        item = MemoryItem(device_id="d1", content="test", tags=["t"])
        item.source = ""
        await svc.store(item)
        assert item.source == "manual"

    async def test_store_sets_timestamps(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        item = MemoryItem(device_id="d1", content="test", tags=["t"])
        before = time.time()
        await svc.store(item)
        assert item.created_at >= before - 1
        assert item.updated_at >= before - 1


class TestLongTermMemoryRecall:
    """recall：按标签召回 + 访问计数"""

    async def test_recall_returns_matching_items(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        await svc.store(MemoryItem(device_id="d1", content="苹果", tags=["水果"]))
        await svc.store(MemoryItem(device_id="d1", content="香蕉", tags=["水果"]))
        await svc.store(MemoryItem(device_id="d1", content="篮球", tags=["运动"]))

        query = MemoryQuery(device_id="d1", summary_labels=("水果",))
        items = await svc.recall(query)
        assert len(items) == 2

    async def test_recall_respects_limit(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        for i in range(5):
            await svc.store(MemoryItem(device_id="d1", content=f"item{i}", tags=["t"]))

        query = MemoryQuery(device_id="d1", summary_labels=("t",), limit=2)
        items = await svc.recall(query)
        assert len(items) == 2

    async def test_recall_default_limit(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        query = MemoryQuery(device_id="d1", summary_labels=("t",))
        # 无 limit 时使用 RECALL_DEFAULT_LIMIT=8
        items = await svc.recall(query)
        assert isinstance(items, list)

    async def test_recall_increments_access_count(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        await svc.store(MemoryItem(device_id="d1", content="x", tags=["t"]))

        query = MemoryQuery(device_id="d1", summary_labels=("t",))
        await svc.recall(query)
        # 访问计数应增加
        assert len(repo._access_counts) >= 1

    async def test_recall_no_matches_returns_empty(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        await svc.store(MemoryItem(device_id="d1", content="x", tags=["a"]))
        query = MemoryQuery(device_id="d1", summary_labels=("nonexistent",))
        items = await svc.recall(query)
        assert items == []


class TestLongTermMemoryListAll:
    """list_all：列出设备全部记忆"""

    async def test_list_all_returns_items(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        await svc.store(MemoryItem(device_id="d1", content="a", tags=["t"]))
        await svc.store(MemoryItem(device_id="d1", content="b", tags=["t"]))

        items = await svc.list_all("d1")
        assert len(items) == 2

    async def test_list_all_empty_device(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        items = await svc.list_all("empty")
        assert items == []


class TestLongTermMemoryUpdate:
    """update：先删除再存储"""

    async def test_update_existing(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        item = MemoryItem(device_id="d1", content="旧内容", tags=["t"])
        memory_id, _ = await svc.store(item)

        changed = await svc.update(memory_id, {"content": "新内容"}, "d1")
        assert changed is True
        # 旧条目被标记删除，新条目被创建
        all_items = await svc.list_all("d1")
        contents = [i.content for i in all_items]
        assert "新内容" in contents

    async def test_update_nonexistent_returns_false(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        changed = await svc.update("nonexistent", {"content": "x"}, "d1")
        assert changed is False

    async def test_update_keeps_old_fields_when_not_in_patch(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        item = MemoryItem(device_id="d1", content="原内容", tags=["原标签"])
        memory_id, _ = await svc.store(item)

        # patch 只含 content，tags 应保持
        await svc.update(memory_id, {"content": "新内容"}, "d1")
        all_items = await svc.list_all("d1")
        new_item = [i for i in all_items if i.content == "新内容"][0]
        assert "原标签" in new_item.tags


class TestLongTermMemoryForget:
    """forget：软删除"""

    async def test_forget_existing(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        item = MemoryItem(device_id="d1", content="test", tags=["t"])
        memory_id, _ = await svc.store(item)

        deleted = await svc.forget(memory_id, "d1")
        assert deleted is not None
        assert deleted.memory_id == memory_id

    async def test_forget_nonexistent_returns_none(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        result = await svc.forget("nonexistent", "d1")
        assert result is None

    async def test_forget_marks_deleted(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        item = MemoryItem(device_id="d1", content="test", tags=["t"])
        memory_id, _ = await svc.store(item)

        await svc.forget(memory_id, "d1")
        all_items = await svc.list_all("d1")
        assert all_items == []


class TestGetSummaryCatalog:
    """get_summary_catalog：获取标签目录"""

    async def test_empty_catalog(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        catalog = await svc.get_summary_catalog("d1")
        assert catalog == ""

    async def test_catalog_with_labels(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        await svc.store(MemoryItem(device_id="d1", content="a", tags=["水果", "饮食"]))
        await svc.store(MemoryItem(device_id="d1", content="b", tags=["运动"]))

        catalog = await svc.get_summary_catalog("d1")
        assert "水果" in catalog
        assert "饮食" in catalog
        assert "运动" in catalog
        assert "memory_recall" in catalog  # 提示语


class TestAutoExtract:
    """auto_extract：从用户消息自动提取耐久事实"""

    async def test_empty_message_returns_empty(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        result = await svc.auto_extract("d1", "", AsyncMock())
        assert result == []

    async def test_whitespace_message_returns_empty(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        result = await svc.auto_extract("d1", "   ", AsyncMock())
        assert result == []

    async def test_llm_failure_returns_empty(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)

        async def failing_llm(sys_prompt, user_prompt):
            raise RuntimeError("LLM down")

        result = await svc.auto_extract("d1", "我喜欢蓝色", failing_llm)
        assert result == []

    async def test_intent_forget_returns_empty(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)

        async def llm_func(sys_prompt, user_prompt):
            return json.dumps({"intent": "forget", "memories": []})

        result = await svc.auto_extract("d1", "忘掉我的名字", llm_func)
        assert result == []

    async def test_intent_none_with_memories(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)

        async def llm_func(sys_prompt, user_prompt):
            return json.dumps({
                "intent": "none",
                "memories": [
                    {"content": "用户喜欢蓝色", "tags": ["颜色偏好"], "keywords": ["蓝色"]},
                ],
            })

        result = await svc.auto_extract("d1", "我喜欢蓝色", llm_func)
        assert len(result) == 1
        assert "蓝色" in result[0]
        # 应实际存储
        all_items = await svc.list_all("d1")
        assert len(all_items) == 1

    async def test_multiple_memories_capped_at_max(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)

        async def llm_func(sys_prompt, user_prompt):
            return json.dumps({
                "intent": "none",
                "memories": [
                    {"content": f"fact{i}", "tags": ["t"], "keywords": ["k"]}
                    for i in range(10)
                ],
            })

        result = await svc.auto_extract("d1", "msg", llm_func)
        # MAX_AUTO_EXTRACT_ITEMS = 3
        assert len(result) == 3

    async def test_empty_content_skipped(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)

        async def llm_func(sys_prompt, user_prompt):
            return json.dumps({
                "intent": "none",
                "memories": [
                    {"content": "", "tags": ["t"], "keywords": ["k"]},
                    {"content": "valid", "tags": ["t"], "keywords": ["k"]},
                ],
            })

        result = await svc.auto_extract("d1", "msg", llm_func)
        assert len(result) == 1

    async def test_dedup_skips_existing(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)
        # 预存一条
        await svc.store(MemoryItem(device_id="d1", content="用户喜欢蓝色", tags=["颜色"]))

        async def llm_func(sys_prompt, user_prompt):
            return json.dumps({
                "intent": "none",
                "memories": [
                    {"content": "用户喜欢蓝色", "tags": ["颜色"], "keywords": ["蓝色"]},
                ],
            })

        # 去重，不应新增
        result = await svc.auto_extract("d1", "我喜欢蓝色", llm_func)
        assert result == []

    async def test_invalid_json_returns_empty(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)

        async def llm_func(sys_prompt, user_prompt):
            return "not a json at all"

        result = await svc.auto_extract("d1", "msg", llm_func)
        assert result == []

    async def test_json_in_code_block(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)

        async def llm_func(sys_prompt, user_prompt):
            return '```json\n{"intent": "none", "memories": [{"content": "test", "tags": ["t"], "keywords": ["t"]}]}\n```'

        result = await svc.auto_extract("d1", "msg", llm_func)
        assert len(result) == 1

    async def test_store_failure_in_loop_continues(self):
        repo = FakeLTMRepository()
        svc = LongTermMemoryServiceImpl(repo)

        async def llm_func(sys_prompt, user_prompt):
            return json.dumps({
                "intent": "none",
                "memories": [
                    {"content": "good", "tags": ["t"], "keywords": ["t"]},
                ],
            })

        # mock store 让它抛异常
        with patch.object(svc, "store", AsyncMock(side_effect=RuntimeError("store fail"))):
            result = await svc.auto_extract("d1", "msg", llm_func)
        # 存储失败应跳过，返回空
        assert result == []


class TestParseLlmJson:
    """_parse_llm_json：从 LLM 回复解析 JSON

    注意：源文件中 _parse_llm_json 被定义了两次，第二个定义（实例方法）
    覆盖了第一个 @staticmethod，因此必须通过实例调用。
    """

    def _make_svc(self):
        return LongTermMemoryServiceImpl(FakeLTMRepository())

    def test_direct_json(self):
        text = '{"intent": "none", "memories": []}'
        result = self._make_svc()._parse_llm_json(text)
        assert result["intent"] == "none"

    def test_empty_text_raises(self):
        with pytest.raises(ValueError, match="empty response"):
            self._make_svc()._parse_llm_json("")

    def test_json_in_code_block(self):
        text = '```json\n{"key": "value"}\n```'
        result = self._make_svc()._parse_llm_json(text)
        assert result["key"] == "value"

    def test_json_in_plain_code_block(self):
        text = '```\n{"key": "val"}\n```'
        result = self._make_svc()._parse_llm_json(text)
        assert result["key"] == "val"

    def test_json_embedded_in_text(self):
        text = 'Here is the result: {"key": "val"} done.'
        result = self._make_svc()._parse_llm_json(text)
        assert result["key"] == "val"

    def test_invalid_json_raises(self):
        with pytest.raises((ValueError, json.JSONDecodeError)):
            self._make_svc()._parse_llm_json("no json here")


class TestNormalizeTags:
    """_normalize_tags：标签去重 + strip"""

    def test_dedup_and_strip(self):
        svc = LongTermMemoryServiceImpl(FakeLTMRepository())
        result = svc._normalize_tags([" a ", "a", "b", "  b  ", "c"])
        assert result == ["a", "b", "c"]

    def test_empty_tags(self):
        svc = LongTermMemoryServiceImpl(FakeLTMRepository())
        assert svc._normalize_tags([]) == []

    def test_filters_empty_strings(self):
        svc = LongTermMemoryServiceImpl(FakeLTMRepository())
        result = svc._normalize_tags(["", "  ", "valid"])
        assert result == ["valid"]


class TestNormalizeKeywords:
    """_normalize_keywords：关键词归一化"""

    def test_empty_keywords_fallback_to_tags(self):
        svc = LongTermMemoryServiceImpl(FakeLTMRepository())
        item = MemoryItem(content="test", tags=["tag1", "tag2"])
        result = svc._normalize_keywords([], item)
        assert result == ["tag1", "tag2"]

    def test_filters_keywords_not_in_content(self):
        svc = LongTermMemoryServiceImpl(FakeLTMRepository())
        item = MemoryItem(content="我喜欢苹果", tags=["水果"])
        result = svc._normalize_keywords(["苹果", "香蕉"], item)
        assert "苹果" in result
        assert "香蕉" not in result

    def test_keyword_matching_tag(self):
        svc = LongTermMemoryServiceImpl(FakeLTMRepository())
        item = MemoryItem(content="内容", tags=["标签"])
        # keyword 与 tag 匹配（大小写不敏感）
        result = svc._normalize_keywords(["标签"], item)
        assert "标签" in result

    def test_all_keywords_filtered_falls_back_to_tags(self):
        svc = LongTermMemoryServiceImpl(FakeLTMRepository())
        item = MemoryItem(content="内容", tags=["标签"])
        # 没有匹配的 keyword，回退到 tags
        result = svc._normalize_keywords(["不匹配"], item)
        assert result == ["标签"]

    def test_dedup_keywords(self):
        svc = LongTermMemoryServiceImpl(FakeLTMRepository())
        item = MemoryItem(content="苹果", tags=[])
        result = svc._normalize_keywords(["苹果", "苹果"], item)
        assert result == ["苹果"]


# ============================================================
# ConversationMemory 基础测试（补充现有 test_memory.py）
# ============================================================


class TestConversationMemoryBasic:
    """ConversationMemory 基础功能补充测试"""

    def test_add_message_truncates_long_content(self):
        mem = ConversationMemory(max_messages=10)
        long_text = "x" * (ConversationMemory.MAX_CHARS_PER_MESSAGE + 100)
        mem.add_user_message(long_text)
        assert len(mem.messages[0]["content"]) == ConversationMemory.MAX_CHARS_PER_MESSAGE

    def test_add_message_skips_empty_content(self):
        mem = ConversationMemory(max_messages=10)
        mem.add_user_message("")
        assert len(mem.messages) == 0

    def test_add_message_skips_whitespace_only(self):
        mem = ConversationMemory(max_messages=10)
        mem.add_user_message("   ")
        assert len(mem.messages) == 0

    def test_build_messages_truncates_current_user_message(self):
        mem = ConversationMemory(max_messages=10)
        long_text = "y" * (ConversationMemory.MAX_CHARS_PER_MESSAGE + 100)
        msgs = mem.build_messages("system", long_text)
        user_msg = msgs[-1]["content"]
        assert len(user_msg) == ConversationMemory.MAX_CHARS_PER_MESSAGE

    def test_trim_removes_old_messages_on_token_limit(self):
        # 构造超过 MAX_TOKENS_ESTIMATE 的场景
        mem = ConversationMemory(max_messages=100)
        # 每条消息 ~500 tokens（1000 字符），4 条就超 2000
        big = "z" * 1000
        for _ in range(5):
            mem.add_user_message(big)
        # 应被 token 限制裁剪
        total_chars = sum(len(m["content"]) for m in mem.messages)
        assert total_chars <= ConversationMemory.MAX_TOKENS_ESTIMATE * 2 + 100

    async def test_with_repository_loads_on_init(self):
        repo = MagicMock()
        repo.load.return_value = [{"role": "user", "content": "loaded"}]
        mem = ConversationMemory(device_id="d1", repository=repo)
        # 性能优化：现在使用异步延迟加载
        await mem.ensure_loaded()
        assert len(mem.messages) == 1
        repo.load.assert_called_once_with("d1")

    def test_with_repository_saves_on_add(self):
        repo = MagicMock()
        repo.load.return_value = []
        mem = ConversationMemory(device_id="d1", repository=repo)
        mem.add_user_message("hello")
        repo.save.assert_called_once()

    def test_clear_with_repository_deletes(self):
        repo = MagicMock()
        repo.load.return_value = [{"role": "user", "content": "x"}]
        mem = ConversationMemory(device_id="d1", repository=repo)
        mem.clear()
        repo.delete.assert_called_once_with("d1")

    def test_estimate_tokens(self):
        mem = ConversationMemory()
        assert mem._estimate_tokens("ab") == 1  # max(1, 2//2)
        assert mem._estimate_tokens("") == 1  # max(1, 0)
        assert mem._estimate_tokens("abcd") == 2
