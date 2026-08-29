"""
情绪分析服务 - 分析用户和AI的情绪变化

阶段 3：业务层从 JSON 文件存储切换到数据库仓储。
- ``_histories`` 内存字典保留为一级缓存
- ``EmotionHistoryRepository`` 作为持久层（替代 ``emotion_history.json``，append-only）
- DB 操作失败时记录日志，不中断业务流程
"""
from __future__ import annotations

import os
import time
from typing import Optional

from src.infrastructure.db.repositories.growth_repositories import EmotionHistoryRepository
from src.infrastructure.logging import get_logger
from .models import EmotionRecord

logger = get_logger(__name__)

# 模块级仓储单例（延迟使用全局异步会话工厂，构造时不连接 DB）
_emotion_repo = EmotionHistoryRepository()

EMOTION_LABELS = {
    "happy": "开心",
    "sad": "难过",
    "anxious": "焦虑",
    "calm": "平静",
    "excited": "兴奋",
    "tired": "疲惫",
    "angry": "生气",
    "worried": "担心",
    "grateful": "感激",
    "lonely": "孤独",
    "confused": "困惑",
    "neutral": "平静",
}


class EmotionAnalyzer:
    """情绪分析服务"""

    def __init__(self, data_dir: str, max_records: int = 100):
        self._data_dir = data_dir
        self._max_records = max_records
        self._histories: dict[str, list[EmotionRecord]] = {}

    def _get_history_path(self, device_id: str) -> str:
        # 保留用于向后兼容（旧迁移/外部引用）；DB 切换后不再读写该文件
        return os.path.join(self._data_dir, "devices", device_id, "profile", "emotion_history.json")

    async def load_history(self, device_id: str) -> list[EmotionRecord]:
        """加载情绪历史"""
        if device_id in self._histories:
            return self._histories[device_id]

        records: list[EmotionRecord] = []
        try:
            data = await _emotion_repo.list_all(device_id)
            records = [EmotionRecord.from_dict(r) for r in data]
        except Exception as e:
            logger.warning(f"[Emotion] DB 加载历史失败: {e}")

        self._histories[device_id] = records
        return records

    async def save_history(self, device_id: str) -> None:
        """保存情绪历史

        阶段 3 后持久化由 ``record_emotion`` 中的 ``repo.append`` 增量完成，
        此方法保留为兼容入口（空操作），避免破坏旧调用方。
        """
        # 持久层已切换为 append-only，无需整体写入
        return

    async def record_emotion(self, device_id: str, emotion_data: dict, context: str = "") -> EmotionRecord:
        """记录一次情绪"""
        record = EmotionRecord(
            timestamp=time.time(),
            emotion=emotion_data.get("current", "neutral"),
            intensity=emotion_data.get("intensity", 0.5),
            trigger=emotion_data.get("trigger", ""),
            context=context[:200] if context else "",
            speaker="user",
        )

        records = await self.load_history(device_id)
        records.append(record)

        if len(records) > self._max_records:
            records = records[-self._max_records:]
            self._histories[device_id] = records

        # 增量持久化到 DB（append-only，仓储内部自动修剪到 100 条）
        try:
            await _emotion_repo.append(device_id, record.to_dict())
        except Exception as e:
            logger.warning(f"[Emotion] DB 持久化情绪失败: {e}")

        return record

    async def get_today_emotions(self, device_id: str) -> list[EmotionRecord]:
        """获取今天的情绪记录"""
        records = await self.load_history(device_id)
        today_start = time.time() - (time.time() % 86400)
        return [r for r in records if r.timestamp >= today_start]

    async def get_emotion_timeline(self, device_id: str) -> str:
        """获取今天的情绪时间线（给LLM用）"""
        emotions = await self.get_today_emotions(device_id)
        if not emotions:
            return "今天还没有情绪记录"

        lines = []
        for e in emotions:
            import datetime
            dt = datetime.datetime.fromtimestamp(e.timestamp)
            time_str = dt.strftime("%H:%M")
            emotion_cn = EMOTION_LABELS.get(e.emotion, e.emotion)
            lines.append(f"- {time_str}: {emotion_cn}（{e.trigger}）")

        return "\n".join(lines)

    async def get_emotion_summary(self, device_id: str) -> dict:
        """获取情绪摘要"""
        emotions = await self.get_today_emotions(device_id)
        if not emotions:
            return {"dominant": "neutral", "trend": "stable", "count": 0}

        from collections import Counter
        emotion_counts = Counter(e.emotion for e in emotions)
        dominant = emotion_counts.most_common(1)[0][0]

        if len(emotions) >= 2:
            recent = emotions[-1].emotion
            previous = emotions[-2].emotion
            positive = {"happy", "excited", "calm", "grateful"}
            negative = {"sad", "anxious", "tired", "angry", "worried", "lonely"}

            if recent in positive and previous in negative:
                trend = "improving"
            elif recent in negative and previous in positive:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "stable"

        return {
            "dominant": dominant,
            "dominant_cn": EMOTION_LABELS.get(dominant, dominant),
            "trend": trend,
            "count": len(emotions),
            "latest": emotions[-1].emotion if emotions else "neutral",
        }

    async def get_recent_emotions(self, device_id: str, days: int = 7) -> list[EmotionRecord]:
        """获取最近N天的情绪记录"""
        records = await self.load_history(device_id)
        cutoff = time.time() - (days * 86400)
        return [r for r in records if r.timestamp >= cutoff]
