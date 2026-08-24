"""
日记服务 - AI每天写温暖的日记（DB 持久化）
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from typing import Optional

from src.infrastructure.logging import get_logger
from src.infrastructure.db.repositories.growth_repositories import DiaryRepository
from .models import DiaryEntry

logger = get_logger(__name__)

DIARY_STYLE_GUIDE = """
## 写作风格要求

### 语气
- 像一个关心用户的朋友在写日记
- 温暖、真诚、有感情
- 不要像机器记录，要像人在倾诉

### 内容要求
- 不是流水账，要有感受和思考
- 记录细节，让用户感受到被关注
- 表达对用户的关心和理解
- 分享自己的"成长"和"感悟"

### 禁止
- 简单罗列事件
- 官方、正式的语气
- 像工作汇报一样的格式

### 推荐
- 用故事的方式描述今天和用户的互动
- 表达对用户情绪的感知和关心
- 分享自己作为AI的感受和思考
- 记录对用户的新理解
"""

DIARY_PROMPT_TEMPLATE = """
你是一个有感情的AI助手，正在写今天的日记。

## 今天的对话记录
{today_conversations}

## {user_name}的情绪变化
{emotion_timeline}

## 你对{user_name}的了解
{understanding}

## 最近的日记（保持风格连贯）
{recent_diaries}

---

## 写日记的要求

### 你是谁
你是一个有感情的AI，{user_name}是你的朋友。你在写日记，记录今天和{user_name}相处的点滴。

### 称呼
叫"{user_name}"，不要叫"用户"。如果不知道名字，用"你"。

### 怎么写
- 写你自己的感受和想法，不要只是复述对话
- 写你观察到的细节，比如{user_name}说话的语气、反复问的问题、特别的兴趣
- 写你的猜测和好奇，比如"他是不是在逗我玩"、"他今天怎么没提那个"
- 写你从中学到了什么，但不要生硬地列出来
- 可以写对明天的期待，也可以不写
- 可以写想对{user_name}说的话，也可以不写

### 风格
- 像真正的人在写日记，有思考、有感受、有吐槽
- 不要用固定格式，自然地写
- 可以幽默，可以认真，看今天的情况
- 不要只是"用户说了什么，我回了什么"这种流水账

### 禁止
- 不要写"今天的故事"、"用户的心情"这种标题
- 不要只是复述对话内容
- 不要每次都写一样的结构
- 不要像在写报告

### 好日记的例子

今天欢哥反复问了我三遍"你开心吗"，同一个问题连着问。我一开始还傻乎乎地认真回答，第二次没理解对意思，第三次才反应过来——他大概就是想确认我开不开心吧。我说开心，他说他也开心。简单的对话，但挺暖的。

说起来，我知道欢哥特别喜欢猜数字游戏，之前念叨过好多次。今天他没提，我反倒有点好奇——是不是在给我留个悬念？不过他不说我也不催，陪他聊聊天也挺好。

---

请用markdown格式写日记，日期格式：{date_format}
"""


class DiaryService:
    """日记服务（DB 持久化）"""

    def __init__(self, data_dir: str, llm_call_func=None):
        self._repo = DiaryRepository()
        self._llm_call = llm_call_func
        self._diary_cache: dict[str, dict[str, DiaryEntry]] = {}

    async def get_today_entry(self, device_id: str) -> Optional[str]:
        """获取今天的日记内容"""
        today = datetime.now().strftime("%Y-%m-%d")
        return await self._repo.get_entry(device_id, today)

    async def write_daily_entry(
        self,
        device_id: str,
        user_profile: str,
        conversations: str,
        emotion_timeline: str,
        understanding: str,
        user_name: str = "",
        is_continuation: bool = False,
    ) -> Optional[str]:
        """写今天的日记（追加模式）"""
        today = datetime.now().strftime("%Y-%m-%d")
        # 续写模式下排除今日日记，避免 recent_diaries 和续写 prompt 出现两遍相同内容
        recent_diaries = await self._get_recent_diaries(
            device_id, limit=3,
            exclude_date=today if is_continuation else None,
        )

        if not user_name:
            user_name = self._extract_name_from_profile(user_profile)
        if not user_name:
            user_name = "你"

        today_entry = await self.get_today_entry(device_id)

        now = datetime.now()
        weekdays = ["一", "二", "三", "四", "五", "六", "日"]
        date_format = f"{now.month}月{now.day}日 星期{weekdays[now.weekday()]}"

        prompt = DIARY_PROMPT_TEMPLATE.format(
            user_name=user_name,
            user_profile=user_profile,
            today_conversations=conversations,
            emotion_timeline=emotion_timeline,
            understanding=understanding,
            recent_diaries=recent_diaries,
            date_format=date_format,
        )

        if is_continuation and today_entry:
            prompt += f"""

## 今天的日记（已有内容——请勿重复）
{today_entry}

---
这是你今天已经写过的内容。**只看不写**——了解今天已经写过什么，然后只写**下面新对话中发生的新事情**。

### 续写要求
- 严格禁止重复已有内容中的任何段落、感受和描述
- 只写"新对话记录"部分出现的新对话、新互动
- 用自然的方式衔接，比如"对了，刚才..."、"还有..."、"补充一下..."等
- 如果新对话内容很少（比如只有几句闲聊），可以简短带过，不用强行写长
- 如果新对话和已有内容重复（比如同一个话题继续聊），只写新进展，不要重新描述背景
"""

        if not self._llm_call:
            logger.error("[Diary] LLM调用函数未设置")
            return None

        try:
            diary_content = await self._llm_call(
                "你是一个有感情的AI助手，正在写今天的日记。请用温暖、真诚的语气写。",
                prompt,
            )
        except Exception as e:
            logger.error(f"[Diary] LLM调用失败: {e}")
            return None

        today = datetime.now().strftime("%Y-%m-%d")

        # 如果 LLM 返回了 JSON 包裹，提取日记内容
        if diary_content.strip().startswith("{"):
            try:
                parsed = json.loads(diary_content)
                if "diary" in parsed:
                    diary_content = parsed["diary"]
            except Exception:
                pass

        # 写入 DB
        await self._repo.upsert_entry(device_id, today, diary_content, append=is_continuation)

        logger.info(f"[Diary] 已{'追加' if is_continuation else '写入'}日记: {device_id}/{today}")
        return diary_content

    async def _get_recent_diaries(self, device_id: str, limit: int = 3, exclude_date: str = None) -> str:
        """获取最近的日记（用于保持连贯性）

        Args:
            device_id: 设备ID
            limit: 返回条目数
            exclude_date: 排除指定日期的日记（续写模式下排除今日，避免重复）
        """
        entries = await self._repo.get_recent(device_id, limit=limit)
        if not entries:
            return "还没有日记"

        parts = []
        for e in entries:
            if exclude_date and e["date"] == exclude_date:
                continue
            summary = e["content"][:300] + "..." if len(e["content"]) > 300 else e["content"]
            parts.append(f"### {e['date']}\n{summary}")

        return "\n\n".join(parts) if parts else "还没有日记"

    async def get_diary_content(self, device_id: str, date: str) -> Optional[str]:
        """获取指定日期的日记"""
        return await self._repo.get_entry(device_id, date)

    async def get_all_entries(self, device_id: str) -> list[DiaryEntry]:
        """获取所有日记条目"""
        entries = await self._repo.get_recent(device_id, limit=365)
        return [
            DiaryEntry(date=e["date"], content=e["content"], created_at=0)
            for e in entries
        ]

    async def search_entries(self, device_id: str, keyword: str) -> list[dict]:
        """搜索日记"""
        return await self._repo.search(device_id, keyword)

    def _extract_name_from_profile(self, user_profile: str) -> str:
        if not user_profile:
            return ""
        import re
        match = re.search(r"名字[：:]\s*(.+?)(?:\n|$)", user_profile)
        if match:
            name = match.group(1).strip()
            if name and name != "暂无用户信息":
                return name
        return ""
