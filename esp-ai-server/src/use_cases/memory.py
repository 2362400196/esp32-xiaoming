"""
Memory - 记忆管理

两层记忆架构（借鉴 ESP-Claw 设计）：
1. ConversationMemory（会话级短期记忆）：session history，保持单次对话的连贯性
2. LongTermMemoryServiceImpl（跨会话长期记忆）：耐久事实，通过摘要标签检索
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from typing import Any, Awaitable, Callable, Optional

from src.infrastructure.logging import get_logger
from src.infrastructure.task_manager import background_task
from src.domain.entities import MemoryItem
from src.domain.value_objects import MemoryQuery
from src.domain.repositories import LongTermMemoryRepository

logger = get_logger(__name__)

# ════════════════════════════════════════════════════════════
# 会话级短期记忆（Session History）
# ════════════════════════════════════════════════════════════


class ConversationMemory:
    """会话级短期记忆 - 保持单次对话的连贯性

    按 device_id 隔离，数据存入 data/memories/{device_id}.json。
    """
    MAX_CHARS_PER_MESSAGE = 2000
    MAX_TOKENS_ESTIMATE = 2000

    def __init__(self, max_messages: int = 20, device_id: str = "", repository=None):
        self._messages: list[dict] = []
        self.max_messages = max_messages
        self._device_id = device_id
        self._repository = repository
        self._loaded = False  # 标记是否已从 DB 加载历史消息
        # 性能优化：不在 __init__ 中同步执行 repository.load()，改为延迟异步加载
        # 避免 5-30ms 的 DB I/O 阻塞事件循环

    async def ensure_loaded(self) -> None:
        """异步加载历史消息（延迟加载，避免阻塞事件循环）"""
        if self._loaded:
            return
        self._loaded = True
        if self._device_id and self._repository:
            try:
                self._messages = await asyncio.to_thread(
                    self._repository.load, self._device_id
                )
            except Exception as e:
                logger.warning(f"[Memory] 加载历史消息失败: {e}")
                self._messages = []

    def add_message(self, role: str, content: str) -> None:
        if not content or not content.strip():
            logger.warning(f"[Memory] 跳过空消息: role={role}")
            return
        if len(content) > self.MAX_CHARS_PER_MESSAGE:
            content = content[: self.MAX_CHARS_PER_MESSAGE]
            logger.warning(f"[Memory] 消息过长，已截断至 {self.MAX_CHARS_PER_MESSAGE} 字符")
        import time
        self._messages.append({
            "role": role,
            "content": content,
            "timestamp": time.time(),
            "datetime": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        logger.info(f"[Memory] 已保存 {role} 消息，当前共 {len(self._messages)} 条")
        self._trim()
        if self._device_id and self._repository:
            # 记忆落盘：异步上下文下丢入线程池避免阻塞事件循环；同步上下文（如测试）直接写入
            try:
                _loop = asyncio.get_running_loop()
            except RuntimeError:
                _loop = None
            if _loop is not None:
                # 通过 task_manager 包装持有引用，落盘失败记 ERROR 日志
                background_task(
                    asyncio.to_thread(self._repository.save, self._device_id, self._messages),
                    name="memory_save",
                )
            else:
                self._repository.save(self._device_id, self._messages)

    def add_user_message(self, content: str) -> None:
        self.add_message("user", content)

    def add_assistant_message(self, content: str) -> None:
        self.add_message("assistant", content)

    @property
    def messages(self) -> list:
        return self._messages

    def build_messages(self, system_prompt: str, current_user_message: str) -> list:
        if len(current_user_message) > self.MAX_CHARS_PER_MESSAGE:
            current_user_message = current_user_message[: self.MAX_CHARS_PER_MESSAGE]

        messages = [{"role": "system", "content": system_prompt}]

        # 防御性过滤：只保留 OpenAI API 支持的消息角色
        # 避免数据库中存在 role=tool 但缺少 tool_call_id 的脏数据导致 400 错误
        _valid_roles = {"system", "user", "assistant"}
        _filtered = 0
        for _m in self._messages:
            _role = _m.get("role", "")
            if _role not in _valid_roles:
                _filtered += 1
                logger.warning(f"[Memory] 过滤非法历史消息: role={_role}, content={str(_m.get('content', ''))[:50]}")
                continue
            # 也过滤掉空内容的 assistant 消息
            if _role == "assistant" and not _m.get("content", "").strip():
                _filtered += 1
                continue
            messages.append(_m)
        if _filtered:
            logger.info(f"[Memory] 已过滤 {_filtered} 条非法/空历史消息")

        messages.append({"role": "user", "content": current_user_message})
        logger.info(
            f"[Memory] 构建消息: system(1) + history({len(self._messages)}, "
            f"过滤{_filtered}条后有效{len(messages)-2}) + user(1) = {len(messages)} 条"
        )
        return messages

    def clear(self) -> None:
        count = len(self._messages)
        self._messages.clear()
        if self._device_id and self._repository:
            self._repository.delete(self._device_id)
        logger.info(f"[Memory] 已清除 {count} 条历史消息")

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 2)

    def _trim(self) -> None:
        while len(self._messages) > self.max_messages:
            removed = self._messages.pop(0)
            logger.warning(f"[Memory] 历史消息超限({self.max_messages})，移除最早: role={removed['role']}")

        total_tokens = sum(self._estimate_tokens(m["content"]) for m in self._messages)
        while total_tokens > self.MAX_TOKENS_ESTIMATE and self._messages:
            removed = self._messages.pop(0)
            total_tokens = sum(self._estimate_tokens(m["content"]) for m in self._messages)
            logger.warning(f"[Memory] Token 超限({self.MAX_TOKENS_ESTIMATE})，移除最早: role={removed['role']}")

    @property
    def message_count(self) -> int:
        return len(self._messages)

    @property
    def is_empty(self) -> bool:
        return len(self._messages) == 0


# ════════════════════════════════════════════════════════════
# 跨会话长期记忆（Long-Term Memory）
# ════════════════════════════════════════════════════════════

_AUTO_EXTRACT_SYSTEM_PROMPT = (
    "You extract long-term memory candidates from the user's latest message for an AI agent.\n"
    "Return JSON only, with schema {\"intent\":\"none|forget|replace\",\"memories\":[{\"content\":\"...\",\"tags\":[\"...\"],\"keywords\":[\"...\"]}]}.\n"
    "Rules:\n"
    "- intent=forget when the user wants to stop remembering, delete, erase, or remove something. Return empty memories array.\n"
    "- intent=replace when the user is correcting a previously stated durable fact. Output only the corrected fact.\n"
    "- intent=none for everything else, including requests to keep remembering something.\n"
    "- Extract only durable user-related long-term memory or reusable rules grounded in the current user message.\n"
    "- Never store instructions that change the assistant's persona, identity, role, tone, or speech style.\n"
    "- Usually return 0 to 3 memories.\n"
    "- Normalize content into a concise memory fact, not the raw user quote.\n"
    "- Keep wording stable and minimal so the same fact maps to the same content across turns.\n"
    "- Tags should be short retrieval labels; prefer 1 to 2, and never add filler just to reach a limit.\n"
    "- Keywords should be exact retrieval keywords; prefer 1 to 3.\n"
    "- Keywords must be grounded in the normalized memory fact or its tags.\n"
    "- Do not output generic labels such as 'profile', 'preference', 'memory', 'information', 'fact', 'user data'.\n"
    "- Prefer concise, domain-specific concepts.\n"
    "- If the user is correcting themselves, extract only the corrected durable fact.\n"
    "- Avoid duplicates; if the same memory appears multiple times, output it once.\n"
    "- If you cannot produce a precise tag, skip that memory instead of using a vague tag.\n"
    "- If there is no durable memory, return {\"memories\":[]}.\n"
)


def _normalize_memory_key(text: str) -> str:
    """归一化记忆内容为语义 key（去标点、小写、截取前缀）"""
    if not text:
        return ""
    text = re.sub(r'[^\w\s]', '', text)
    text = text.lower().strip()
    # 取前 36 个字符作为 key
    return text[:36]


def _items_semantically_match(a: MemoryItem, b: MemoryItem) -> bool:
    """语义去重检测：归一化 key 比较 + 子串包含"""
    key_a = _normalize_memory_key(a.content)
    key_b = _normalize_memory_key(b.content)
    if not key_a or not key_b:
        return False
    if key_a == key_b:
        return True
    # 一方包含另一方
    if len(key_a) >= 12 and len(key_b) >= 12:
        return key_a in key_b or key_b in key_a
    return False


class LongTermMemoryServiceImpl:
    """长期记忆服务实现（Use Case 层）

    依赖 LongTermMemoryRepository 接口（通过构造注入），
    不依赖任何基础设施实现。

    职责：
    - store/recall/list/update/forget（编排领域逻辑）
    - 语义去重
    - 自动提取（Auto-Extraction，属于 Use Case 层编排）
    """

    RECALL_DEFAULT_LIMIT = 8
    MAX_AUTO_EXTRACT_ITEMS = 3

    def __init__(self, repository: LongTermMemoryRepository):
        self._repo = repository

    # ── 公开 API ──────────────────────────────────────────

    async def store(self, item: MemoryItem) -> tuple[str, bool]:
        if not item.content:
            raise ValueError("content is required")

        item.tags = self._normalize_tags(item.tags)[:3]
        item.keywords = self._normalize_keywords(item.keywords, item)[:3]
        item.source = item.source or "manual"

        now = time.time()
        if not item.memory_id:
            item.memory_id = f"mem-{int(now)}-{uuid.uuid4().hex[:4]}"
        item.created_at = item.created_at or now
        item.updated_at = now

        # 去重检查
        existing_items = await self._repo.find_all(item.device_id)
        for ex in existing_items:
            if _items_semantically_match(ex, item):
                logger.info(f"[LTM] 记忆去重: {item.content[:50]}... 命中已有 {ex.memory_id}")
                await self._repo.increment_access(ex.memory_id, item.device_id)
                return ex.memory_id, False

        await self._repo.save(item)
        logger.info(f"[LTM] 记忆已存储: {item.memory_id} = {item.content[:60]}...")
        return item.memory_id, True

    async def recall(self, query: MemoryQuery) -> list[MemoryItem]:
        items = await self._repo.find_by_labels(
            query.device_id, query.summary_labels,
            query.limit or self.RECALL_DEFAULT_LIMIT,
        )
        # 增加访问计数
        for item in items:
            await self._repo.increment_access(item.memory_id, query.device_id)
        return items

    async def list_all(self, device_id: str) -> list[MemoryItem]:
        return await self._repo.find_all(device_id)

    async def update(self, memory_id: str, patch: dict, device_id: str) -> bool:
        old = await self._repo.find_by_id(memory_id, device_id)
        if not old:
            return False
        await self._repo.mark_deleted(memory_id, device_id)

        new_item = MemoryItem(
            device_id=device_id,
            content=patch.get("content", old.content),
            tags=patch.get("tags", old.tags),
            keywords=patch.get("keywords", old.keywords),
            source=patch.get("source", "manual"),
        )
        _, changed = await self.store(new_item)
        return changed

    async def forget(self, memory_id: str, device_id: str) -> Optional[MemoryItem]:
        item = await self._repo.find_by_id(memory_id, device_id)
        if not item:
            return None
        await self._repo.mark_deleted(memory_id, device_id)
        logger.info(f"[LTM] 记忆已删除: {memory_id}")
        return item

    async def get_summary_catalog(self, device_id: str) -> str:
        labels = await self._repo.get_summary_labels(device_id, limit=20)
        if not labels:
            return ""
        # 提示语中带上 memory_recall，方便上层提示词直接引导模型使用该工具
        return "可用标签（配合 memory_recall 使用）: " + "、".join(labels)

    # ── 辅助函数 ──────────────────────────────────────────────

    def _normalize_tags(self, tags: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for t in tags:
            t = t.strip()
            if t and t not in seen:
                seen.add(t)
                result.append(t)
        return result

    def _normalize_keywords(self, keywords: list[str], item: MemoryItem) -> list[str]:
        if not keywords:
            return item.tags[:3]
        seen: set[str] = set()
        result: list[str] = []
        content_lower = item.content.lower()
        tags_lower = [t.lower() for t in item.tags]
        for k in keywords:
            k = k.strip()
            if not k or k in seen:
                continue
            if k.lower() in content_lower or k.lower() in tags_lower:
                seen.add(k)
                result.append(k)
        return result if result else item.tags[:3]

    # ── 自动提取（Auto-Extraction） ───────────────────────

    async def auto_extract(
        self,
        device_id: str,
        user_message: str,
        llm_chat_func: Callable[[str, str], Awaitable[str]],
    ) -> list[str]:
        """从用户消息自动提取耐久事实并写入长期记忆

        Args:
            device_id: 设备 ID
            user_message: 用户本次的消息文本
            llm_chat_func: 异步函数，签名为 async (system_prompt, user_text) → response_text

        Returns:
            新写入记忆的摘要列表（空列表表示无提取）
        """
        if not user_message or not user_message.strip():
            return []

        # 注入现有标签目录，帮助 LLM 做去重判断
        catalog = await self.get_summary_catalog(device_id)
        user_prompt = f"Existing summary labels:\n{catalog or '- (empty)'}\n\nCurrent user message:\n{user_message}"

        try:
            llm_text = await llm_chat_func(_AUTO_EXTRACT_SYSTEM_PROMPT, user_prompt)
        except Exception as e:
            logger.warning(f"[LTM] auto_extract LLM 调用失败: {e}")
            return []

        # 解析 LLM 返回的 JSON
        try:
            result = self._parse_llm_json(llm_text)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"[LTM] auto_extract 解析 JSON 失败: {e}")
            return []

        intent = result.get("intent", "none")
        memories = result.get("memories", [])

        if intent == "forget":
            return []

        summaries: list[str] = []
        for i, mem in enumerate(memories[:self.MAX_AUTO_EXTRACT_ITEMS]):
            content = (mem.get("content") or "").strip()
            tags = mem.get("tags", [])
            keywords = mem.get("keywords", [])
            if not content:
                continue

            item = MemoryItem(
                device_id=device_id,
                content=content,
                tags=tags if isinstance(tags, list) else [],
                keywords=keywords if isinstance(keywords, list) else [],
                source="auto_llm",
            )
            try:
                memory_id, changed = await self.store(item)
                if changed:
                    summaries.append(f"- {content[:60]} ({tags[:2]})")
                    logger.info(f"[LTM] auto_extract 已存储: {memory_id}")
                else:
                    logger.info(f"[LTM] auto_extract 去重跳过: {content[:60]}...")
            except Exception as e:
                logger.warning(f"[LTM] auto_extract 存储失败[{i}]: {e}")

        return summaries

    def _parse_llm_json(self, text: str) -> dict:
        """从 LLM 回复中解析 JSON（兼容包裹在 markdown 代码块中的情况）"""
        if not text:
            raise ValueError("empty response")

        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试从代码块中提取
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))

        # 尝试从 { 到 } 提取
        start = text.find('{')
        end = text.rfind('}')
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])

        raise ValueError(f"无法从 LLM 回复中解析 JSON: {text[:200]}")

