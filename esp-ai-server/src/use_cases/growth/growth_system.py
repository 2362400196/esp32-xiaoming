"""
AI自我成长系统 - 核心协调器
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime
from typing import Awaitable, Callable, Optional

from src.infrastructure.logging import get_logger
from .user_profile import UserProfileService
from .emotion_analyzer import EmotionAnalyzer
from .diary_service import DiaryService
from .self_learning import SelfLearningService
from .models import ConversationAnalysis, SkillCandidate

logger = get_logger(__name__)


class GrowthSystem:
    """AI自我成长系统

    职责：
    - 协调各个子系统（用户画像、情绪分析、日记、自学习）
    - 在对话结束后触发后台成长任务
    - 管理设备的diary skill
    """

    def __init__(
        self,
        data_dir: str,
        llm_call_func: Callable[[str, str], Awaitable[str]],
        memory_service=None,
    ):
        self._data_dir = data_dir
        self._llm_call = llm_call_func
        self._memory_service = memory_service

        self.user_profile = UserProfileService(data_dir)
        self.emotion = EmotionAnalyzer(data_dir)
        self.diary = DiaryService(data_dir, llm_call_func)
        self.learning = SelfLearningService(data_dir, llm_call_func)

        self._pending_tasks: dict[str, asyncio.Task] = {}

    async def on_conversation_end(
        self,
        device_id: str,
        messages: list[dict],
    ) -> None:
        """对话结束时调用，启动后台成长任务"""
        if device_id in self._pending_tasks:
            task = self._pending_tasks[device_id]
            if not task.done():
                logger.info(f"[Growth] 已有成长任务在运行: {device_id}")
                return

        task = asyncio.create_task(
            self._growth_task(device_id, messages)
        )
        self._pending_tasks[device_id] = task

    async def _growth_task(
        self,
        device_id: str,
        messages: list[dict],
    ) -> None:
        """后台成长任务"""
        try:
            logger.info(f"[Growth] 开始成长任务: {device_id}")

            analysis = await self.learning.analyze_conversation(messages)
            if not analysis:
                logger.warning(f"[Growth] 对话分析失败: {device_id}")
                return

            profile = await self.user_profile.update_from_analysis(device_id, analysis)

            if analysis.get("emotion"):
                await self.emotion.record_emotion(
                    device_id,
                    analysis["emotion"],
                    analysis.get("conversation_summary", ""),
                )

            if self._memory_service and analysis.get("memories"):
                await self._store_memories(device_id, analysis["memories"])

            if analysis.get("skill_candidate", {}).get("title"):
                decision = await self.learning.evaluate_skill_creation(
                    device_id,
                    analysis["skill_candidate"],
                )
                if decision:
                    await self.learning.create_or_merge_skill(
                        device_id,
                        analysis["skill_candidate"],
                        decision,
                    )

            await self._write_diary_if_needed(device_id, messages, analysis)

            logger.info(f"[Growth] 成长任务完成: {device_id}")

        except Exception as e:
            logger.error(f"[Growth] 成长任务失败: {e}", exc_info=True)

    async def _write_diary_if_needed(
        self,
        device_id: str,
        messages: list[dict],
        analysis: dict,
    ) -> None:
        """写日记（追加模式：每次对话都追加到今天的日记）"""
        # 获取用户画像和名字
        profile = await self.user_profile.get_profile(device_id)
        profile_summary = await self.user_profile.get_profile_summary(device_id)

        # 优先从画像中找名字，没有再从记忆中找
        user_name = profile.name if profile.name else ""
        if not user_name:
            user_name = await self._find_user_name_from_memory(device_id)

        # 检查今天是否已有日记（决定是首次写入还是续写）
        today_entry = await self.diary.get_today_entry(device_id)
        is_continuation = today_entry is not None

        # 续写模式下只传最新的对话（最多5条），避免LLM重复写之前已写过的内容
        conversations = self._format_conversations(
            messages,
            max_messages=5 if is_continuation else 15,
        )

        emotion_timeline = await self.emotion.get_emotion_timeline(device_id)

        understanding = await self._get_user_understanding(device_id)

        diary_content = await self.diary.write_daily_entry(
            device_id=device_id,
            user_profile=profile_summary,
            conversations=conversations,
            emotion_timeline=emotion_timeline,
            understanding=understanding,
            user_name=user_name,
            is_continuation=is_continuation,
        )

        if diary_content:
            logger.info(f"[Growth] 日记已{'追加' if is_continuation else '写入'}: {device_id}")

    async def _find_user_name_from_memory(self, device_id: str) -> str:
        """从长期记忆中查找用户称呼"""
        if not self._memory_service:
            return ""

        try:
            # 获取所有记忆
            all_memories = await self._memory_service.list_all(device_id)

            # 查找包含"名字"、"叫"、"称呼"等关键词的记忆
            name_keywords = ["名字", "叫", "称呼", "我叫", "叫我", "是"]

            for mem in all_memories:
                content = mem.content if hasattr(mem, 'content') else ""
                if not content:
                    continue

                # 检查是否包含名字相关的关键词
                for keyword in name_keywords:
                    if keyword in content:
                        # 尝试提取名字
                        name = self._extract_name_from_text(content, keyword)
                        if name:
                            logger.info(f"[Growth] 从记忆中找到用户称呼: {name}")
                            return name

        except Exception as e:
            logger.warning(f"[Growth] 从记忆查找用户名字失败: {e}")

        return ""

    def _extract_name_from_text(self, text: str, keyword: str) -> str:
        """从文本中提取名字"""
        import re

        # 匹配模式：我叫xxx、名字是xxx、叫我xxx、称呼xxx
        patterns = [
            rf"{keyword}(.+?)(?:，|。|，|！|？|\s|$)",
            rf"{keyword}(.+?)(?:就好|吧|啊|哦|呢)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                name = match.group(1).strip()
                # 过滤掉太长的（不是名字）
                if 1 <= len(name) <= 10:
                    return name

        return ""

    def _format_conversations(self, messages: list[dict], max_messages: int = 15) -> str:
        """格式化对话内容（只取今天的对话）

        Args:
            messages: 对话消息列表
            max_messages: 最多取最近多少条消息（续写模式下减少数量，避免重复写已写过的内容）
        """
        if not messages:
            return "今天还没有对话"

        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")

        lines = []
        for msg in messages[-max_messages:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            datetime_str = msg.get("datetime", "")

            # 只取今天的对话
            if datetime_str and not datetime_str.startswith(today):
                continue

            # 提取时间（HH:MM格式）
            time_str = ""
            if datetime_str and " " in datetime_str:
                time_str = datetime_str.split(" ")[1][:5]  # 取 HH:MM

            if role == "user":
                if time_str:
                    lines.append(f"[{time_str}] 用户: {content}")
                else:
                    lines.append(f"用户: {content}")
            elif role == "assistant":
                if time_str:
                    lines.append(f"[{time_str}] AI: {content}")
                else:
                    lines.append(f"AI: {content}")

        return "\n".join(lines) if lines else "今天还没有对话"

    async def _get_user_understanding(self, device_id: str) -> str:
        """获取对用户的理解"""
        profile = await self.user_profile.get_profile(device_id)

        parts = []
        if profile.name:
            parts.append(f"- 用户叫{profile.name}")
        if profile.occupation:
            parts.append(f"- 用户是{profile.occupation}")
        if profile.family:
            parts.append(f"- 用户的家人: {', '.join(profile.family)}")
        if profile.interests.get("likes"):
            parts.append(f"- 用户喜欢: {', '.join(profile.interests['likes'])}")
        if profile.interests.get("dislikes"):
            parts.append(f"- 用户不喜欢: {', '.join(profile.interests['dislikes'])}")
        if profile.interests.get("learning"):
            parts.append(f"- 用户正在学习: {', '.join(profile.interests['learning'])}")
        if profile.current_state.get("concerns"):
            parts.append(f"- 用户最近关心: {', '.join(profile.current_state['concerns'])}")

        emotions = await self.emotion.get_recent_emotions(device_id, days=7)
        if emotions:
            from collections import Counter
            emotion_counts = Counter(e.emotion for e in emotions)
            top_emotions = emotion_counts.most_common(3)
            emotion_str = ", ".join([f"{e}({c}次)" for e, c in top_emotions])
            parts.append(f"- 用户最近情绪: {emotion_str}")

        return "\n".join(parts) if parts else "还不太了解用户"

    async def _store_memories(self, device_id: str, memories: list[dict]) -> None:
        """存入长期记忆"""
        if not self._memory_service:
            return

        from src.domain.entities import MemoryItem

        for mem in memories:
            content = mem.get("content", "")
            if not content:
                continue

            try:
                item = MemoryItem(
                    device_id=device_id,
                    content=content,
                    tags=mem.get("tags", []),
                    keywords=mem.get("keywords", []),
                    source="growth_system",
                )
                await self._memory_service.store(item)
            except Exception as e:
                logger.warning(f"[Growth] 存储记忆失败: {e}")

    async def get_device_growth_summary(self, device_id: str) -> dict:
        """获取设备的成长摘要"""
        profile = await self.user_profile.get_profile(device_id)
        emotion_summary = await self.emotion.get_emotion_summary(device_id)
        diary_entries = await self.diary.get_all_entries(device_id)

        return {
            "user_name": profile.name,
            "diary_count": len(diary_entries),
            "emotion_summary": emotion_summary,
            "interests": profile.interests,
            "current_state": profile.current_state,
        }
