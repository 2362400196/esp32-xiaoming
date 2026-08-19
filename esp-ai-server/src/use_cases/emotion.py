from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import socket
import uuid
from dataclasses import dataclass, field
from typing import Any, List, Optional

from src.infrastructure.config import get_settings, SID_TTS, SID_CONNECTED, SCREEN_WIDTH, SCREEN_HEIGHT
from src.infrastructure.logging import get_logger
from src.interfaces.tts_gateways import create_tts_gateway, VoiceGenerator
from src.domain.services import MemoryService
from src.domain.entities import Conversation, Message
from src.use_cases.session_fsm import SessionState

logger = get_logger(__name__)

_CHUNK_SIZE = 2048


class EmotionDetector:
    EMOTION_KEYWORDS: dict[str, list[str]] = {
        "快乐": ["哈哈", "开心", "高兴", "太好了", "棒", "妙", "不错", "喜欢", "爱", "谢谢", "恭喜", "nice", "good", "很好", "太棒了", "真不错", "赞"],
        "伤心": ["难过", "伤心", "哭", "难过死了", "糟糕", "惨", "绝望", "失落", "抑郁", "呜呜", "可怜", "悲伤", "心痛", "泪"],
        "愤怒": ["生气", "愤怒", "气死", "讨厌", "滚", "烦", "恶心", "无语", "扯淡", "胡扯", "滚开", "岂有此理", "惹", "火大", "暴怒", "恼火", "不爽"],
        "意外": ["真的假的", "不可能", "居然", "竟然", "天哪", "我的天", "没想到", "出乎意料", "哇塞"],
        "否定": ["拒绝", "否认"],
    }

    def detect_emotion(self, text: str, device_id: str = "") -> str:
        text_lower = text.lower()
        scores: dict[str, int] = {}
        for emotion, keywords in self.EMOTION_KEYWORDS.items():
            score = 0
            for kw in keywords:
                if kw.lower() in text_lower:
                    score += len(kw)
            if score > 0:
                scores[emotion] = score
        if not scores:
            return ""
        return max(scores, key=scores.get)

class EmotionRenderer:
    EMOTION_COLORS: dict[str, tuple[int, int, int]] = {
        "快乐": (255, 215, 0),
        "伤心": (100, 149, 237),
        "愤怒": (220, 38, 38),
        "意外": (147, 112, 219),
        "否定": (255, 165, 0),
        "无情绪": (180, 180, 180),
    }

    EMOTION_ZH: dict[str, str] = {
        "快乐": "😊 快乐",
        "伤心": "😢 伤心",
        "愤怒": "😡 愤怒",
        "意外": "😲 意外",
        "否定": "🙅 否定",
        "无情绪": "",
    }

    @staticmethod
    def _rgb_to_565(r: int, g: int, b: int) -> int:
        return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)

    def get_emotion_gif_path(self, emotion: str) -> str | None:
        settings = get_settings()
        gif_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "app", "emotion", settings.emotion.gif_dir,
        )
        gif_path = os.path.join(gif_dir, f"{emotion}.gif")
        if os.path.isfile(gif_path):
            return gif_path
        return None

    def render_emotion_rgb565_b64(
        self,
        emotion: str,
        width: int = SCREEN_WIDTH,
        height: int = SCREEN_HEIGHT,
    ) -> str | None:
        gif_path = self.get_emotion_gif_path(emotion)
        if gif_path:
            try:
                with open(gif_path, "rb") as f:
                    gif_data = f.read()
                from PIL import Image
                img = Image.open(io.BytesIO(gif_data))
                resized = img.resize((width, height), Image.LANCZOS)
                if resized.mode != "RGB":
                    resized = resized.convert("RGB")
                pixels = resized.load()
                rgb565 = bytearray(width * height * 2)
                idx = 0
                for y in range(height):
                    for x in range(width):
                        r, g, b = pixels[x, y]
                        val = self._rgb_to_565(r, g, b)
                        rgb565[idx] = (val >> 8) & 0xFF
                        rgb565[idx + 1] = val & 0xFF
                        idx += 2
                return base64.b64encode(bytes(rgb565)).decode()
            except Exception as e:
                logger.warning(f"[Emotion] GIF 渲染失败，回退到纯色: {e}")

        try:
            from PIL import Image, ImageDraw, ImageFont

            color = self.EMOTION_COLORS.get(emotion, (180, 180, 180))
            label = self.EMOTION_ZH.get(emotion, emotion)

            img = Image.new("RGB", (width, height), color)
            if label:
                draw = ImageDraw.Draw(img)
                font_size = 36
                try:
                    font = ImageFont.truetype("simhei.ttf", font_size)
                except OSError:
                    try:
                        font = ImageFont.truetype("arial.ttf", font_size)
                    except OSError:
                        font = ImageFont.load_default()

                bbox = draw.textbbox((0, 0), label, font=font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                tx = (width - tw) // 2
                ty = (height - th) // 2
                draw.text((tx, ty), label, fill=(255, 255, 255), font=font)

            pixels = img.load()
            rgb565 = bytearray(width * height * 2)
            idx = 0
            for y in range(height):
                for x in range(width):
                    r, g, b = pixels[x, y]
                    val = self._rgb_to_565(r, g, b)
                    rgb565[idx] = (val >> 8) & 0xFF
                    rgb565[idx + 1] = val & 0xFF
                    idx += 2

            return base64.b64encode(bytes(rgb565)).decode()
        except Exception as e:
            logger.error(f"[Emotion] 渲染失败: {e}")
            return None

