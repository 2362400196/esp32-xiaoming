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
from src.use_cases.device_registry import DeviceRegistry
from src.use_cases.device_config import load_devices
from src.use_cases.wake_audio import WakeAudioManager
from src.use_cases.speaker import Speaker
from src.use_cases.audio_processor import AudioProcessor
from src.use_cases.memory import ConversationMemory
from src.use_cases.emotion import EmotionDetector

logger = get_logger(__name__)

_CHUNK_SIZE = 2048


class AuthService:
    def __init__(self, device_manager: DeviceManager | None = None):
        self._device_manager = device_manager or load_devices()

    def verify_api_key(self, key: str = None) -> bool:
        if self._device_manager.has_users():
            if not key:
                return False
            return self._device_manager.resolve(key) is not None
        else:
            settings = get_settings()
            if settings.auth.enabled:
                if not key:
                    return False
                return key == settings.auth.api_key
            return True

    def get_user_config(self, key: str = None):
        if not key:
            return None

        if self._device_manager:
            return self._device_manager.resolve(key)
        return None

    def require_auth(self, key: str = None) -> bool:
        if not self.verify_api_key(key):
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="Unauthorized")
        return True

    def reload_users_config(self):
        """重新加载设备配置（从数据库），使新配置对后续设备连接生效"""
        self._device_manager = load_devices()

def create_emotion_detection() -> EmotionDetector:
    return EmotionDetector()

def create_device_manager() -> DeviceManager:
    return load_devices()

def create_audio_processor(config: dict = None) -> AudioProcessor:
    return AudioProcessor(config=config)

def create_memory_service(max_messages: int = 20, device_id: str = "") -> ConversationMemory:
    from src.infrastructure.db.repositories.short_term_memory_repo import SqlShortTermMemoryRepository
    return ConversationMemory(max_messages=max_messages, device_id=device_id, repository=SqlShortTermMemoryRepository())

def create_wake_audio_manager(voice_generator: VoiceGenerator | None = None) -> WakeAudioManager:
    return WakeAudioManager(voice_generator=voice_generator)

def create_speaker(
    device_registry: DeviceRegistry | None = None,
    wake_audio_manager: WakeAudioManager | None = None,
) -> Speaker:
    registry = device_registry or DeviceRegistry()
    wake = wake_audio_manager or WakeAudioManager()
    return Speaker(registry, wake)

def create_auth_service(device_manager: DeviceManager | None = None) -> AuthService:
    return AuthService(device_manager=device_manager)

