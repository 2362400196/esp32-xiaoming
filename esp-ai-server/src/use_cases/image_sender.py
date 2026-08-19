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


class ImageSender:
    def __init__(
        self,
        emotion_detector: EmotionDetector | None = None,
        emotion_renderer: EmotionRenderer | None = None,
    ):
        self._emotion_detector = emotion_detector or EmotionDetector()
        self._emotion_renderer = emotion_renderer or EmotionRenderer()
        self._url_cache: dict[str, tuple[str, int, int]] = {}

    async def send_image_to_device(
        self,
        channel,
        image_url: str,
        width: int = SCREEN_WIDTH,
        height: int = SCREEN_HEIGHT,
    ):
        try:
            await channel.send_json({
                "type": "show_image",
                "url": image_url,
                "width": width,
                "height": height,
            })
            logger.info(f"[ImageSender] 已发送图片 URL: {image_url}")
            return True
        except Exception as e:
            logger.error(f"[ImageSender] 发送失败: {e}")
            return False

    async def send_clear_image(self, channel):
        try:
            await channel.send_json({"type": "clear_image"})
            logger.info("[ImageSender] 已发送清除图片指令")
            return True
        except Exception as e:
            logger.error(f"[ImageSender] 清除失败: {e}")
            return False

    async def send_emotion_image(self, channel, text: str, device_id: str = ""):
        settings = get_settings()
        if not settings.emotion.enabled:
            return False

        emotion = self._emotion_detector.detect_emotion(text, device_id)
        if not emotion:
            return False

        try:
            await channel.send_json({
                "type": "emotion",
                "data": emotion,
            })
            logger.info(f"[ImageSender] 已发送情绪: {emotion}")
            return True
        except Exception as e:
            logger.error(f"[ImageSender] 发送情绪失败: {e}")
            return False

    async def send_custom_image(self, channel, image_bytes: bytes):
        emos_dir = self._ensure_emos_dir()
        filename = f"{uuid.uuid4().hex}.jpg"
        filepath = os.path.join(emos_dir, filename)

        try:
            from PIL import Image
            img = Image.open(io.BytesIO(image_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.save(filepath, "JPEG", quality=85)
            image_url = self._build_url(filename)

            width, height = img.size
            await self.send_image_to_device(channel, image_url, width, height)
            return image_url
        except Exception as e:
            logger.error(f"[ImageSender] 自定义图片保存失败: {e}")
            return None

    def _prepare_emotion_image(self, emotion: str) -> tuple[str, int, int] | None:
        filename = f"{emotion}.gif"
        dest_dir = self._ensure_emos_dir()
        dest_path = os.path.join(dest_dir, filename)

        if emotion in self._url_cache:
            cached_url, cached_w, cached_h = self._url_cache[emotion]
            if os.path.isfile(dest_path) and os.path.getsize(dest_path) > 0:
                try:
                    from PIL import Image
                    Image.open(dest_path).close()
                    return cached_url, cached_w, cached_h
                except Exception as e:
                    logger.debug(f"[ImageSender] 校验缓存图片失败: {e}")

        gif_path = self._emotion_renderer.get_emotion_gif_path(emotion)
        if not gif_path or not os.path.isfile(gif_path):
            logger.warning(f"[ImageSender] 情绪图片不存在: {emotion}, 跳过")
            return None

        if os.path.getsize(gif_path) == 0:
            logger.warning(f"[ImageSender] 情绪图片为空: {emotion}, 跳过")
            return None

        try:
            from PIL import Image
            img = Image.open(gif_path)
            width, height = img.size

            if img.format == "GIF":
                with open(gif_path, "rb") as src, open(dest_path, "wb") as dst:
                    dst.write(src.read())
            else:
                img.save(dest_path)

            img.close()
        except Exception as e:
            logger.warning(f"[ImageSender] 图片处理失败: {e}, 跳过")
            return None

        image_url = self._build_url(filename)
        self._url_cache[emotion] = (image_url, width, height)
        logger.info(f"[ImageSender] 已缓存情绪图片: {emotion} ({width}x{height}) -> {image_url}")
        return image_url, width, height

    def _build_url(self, filename: str) -> str:
        settings = get_settings()
        host = settings.server.host
        port = settings.server.port
        if host == "0.0.0.0":
            local_ip = self._get_local_ip()
            return f"http://{local_ip}:{port}/emos/{filename}"
        return f"http://{host}:{port}/emos/{filename}"

    @staticmethod
    def _get_local_ip() -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def _ensure_emos_dir(self) -> str:
        settings = get_settings()
        emos_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "app", "emotion", settings.emotion.static_dir,
        )
        os.makedirs(emos_dir, exist_ok=True)
        return emos_dir

