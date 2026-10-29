"""流水线情绪标签解析与表情下发。"""
from __future__ import annotations

import asyncio
import re

from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


class EmotionMixin:
    """情绪标签解析、关键词兜底与表情下发。"""

    EMOTION_KEYWORDS: dict = {
        "快乐": ["哈哈", "开心", "高兴", "太好了", "棒", "妙", "不错", "喜欢", "爱", "谢谢", "恭喜", "nice", "good", "很好", "太棒了", "真不错", "赞"],
        "伤心": ["难过", "伤心", "哭", "难过死了", "糟糕", "惨", "绝望", "失落", "抑郁", "呜呜", "可怜", "悲伤", "心痛", "泪"],
        "愤怒": ["生气", "愤怒", "气死", "讨厌", "滚", "烦", "恶心", "无语", "扯淡", "胡扯", "滚开", "岂有此理", "惹", "火大", "暴怒", "恼火", "不爽"],
        "意外": ["真的假的", "不可能", "居然", "竟然", "天哪", "我的天", "没想到", "出乎意料", "哇塞"],
        "否定": ["拒绝", "否认"],
    }

    NEGATION_PREFIXES = ["不", "没", "别", "不太", "并不", "没有", "从未", "未必", "绝不", "从不"]

    EMOTION_TAG_RE = re.compile(r'\[e:([^\]]+)\]')

    @staticmethod
    def _parse_emotion_tag(text: str) -> tuple[str, str]:
        """从 LLM 回复解析 [e:情绪] 标签，返回 (纯文本, 情绪)"""
        m = EmotionMixin.EMOTION_TAG_RE.search(text)
        if m:
            emotion = m.group(1).strip()
            # 移除所有 [e:情绪] 标签（LLM 可能把标签放在开头/中间/末尾），保留其余文本。
            # 原实现只在标签位于末尾时正确：标签在开头时 text[:m.start()] 为空，
            # 调用方回退到原文，导致 "[e:无情绪]这回真调好了" 这类回复把标签念出来。
            clean = EmotionMixin.EMOTION_TAG_RE.sub('', text).strip()
            clean = clean.rstrip('，。！？；,')
            return clean, emotion
        return text, ""

    @staticmethod
    def _keyword_detect(text: str) -> str:
        """关键词兜底检测"""
        text_lower = text.lower()
        for emotion, keywords in EmotionMixin.EMOTION_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in text_lower:
                    return emotion
        return ""

    def _detect_and_send_emotion(self, sentence_text: str) -> str:
        """解析情绪标签发送，无标签时关键词兜底，都无则发无情绪"""
        clean_text, emotion = self._parse_emotion_tag(sentence_text)
        if not emotion:
            emotion = self._keyword_detect(sentence_text)
        if not emotion:
            emotion = "无情绪"
            # 无情绪不覆盖上次表情，避免打断当前情绪显示
        if emotion != self._last_emotion and emotion != "无情绪":
            self._last_emotion = emotion
            _t = asyncio.create_task(self._send_emotion_task(emotion))
            self._bg_tasks.add(_t)
            _t.add_done_callback(self._bg_tasks.discard)
        elif emotion == "无情绪" and self._last_emotion is None:
            self._last_emotion = emotion
        # 兜底：即使清理后为空（如回复只有标签），也返回去标签后的文本，
        # 避免回退原文把 [e:xxx] 念出来（后续 TTS 前有空文本过滤，不会合成空音频）
        return clean_text if clean_text else EmotionMixin.EMOTION_TAG_RE.sub('', sentence_text).strip()

    async def _send_emotion_task(self, emotion: str):
        try:
            await self.channel.send_json({
                "type": "emotion",
                "data": emotion
            })
            logger.info(f"[Pipeline] 已发送表情: {emotion}")
            # 同步推送情绪到 Web 前端（设备屏幕实时显示情绪表情）
            try:
                from src.infrastructure.web import get_web_state_hub
                hub = get_web_state_hub()
                if hub and self.device_id:
                    await hub.broadcast_device_state(self.device_id, True, "idle", emotion)
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"[Pipeline] 发送表情失败: {e}")
