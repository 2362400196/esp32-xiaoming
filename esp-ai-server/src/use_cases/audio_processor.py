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


class AudioProcessor:
    SUPPORTED_FORMATS = {"pcm", "mp3", "wav", "ogg", "opus"}

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.sample_rate = self.config.get("sample_rate", 16000)
        self.channels = self.config.get("channels", 1)
        self.bits_per_sample = self.config.get("bits_per_sample", 16)

    def decode_base64_audio(self, base64_data: str, format: str = "pcm") -> bytes:
        try:
            audio_bytes = base64.b64decode(base64_data)
            return audio_bytes
        except Exception as e:
            from src.domain.exceptions import AudioProcessingError
            raise AudioProcessingError(f"Failed to decode base64 audio: {e}")

    def encode_base64_audio(self, audio_data: bytes) -> str:
        return base64.b64encode(audio_data).decode("utf-8")

    def split_audio(self, audio_data: bytes, chunk_size: int = 6400) -> list[bytes]:
        chunks = []
        for i in range(0, len(audio_data), chunk_size):
            chunk = audio_data[i : i + chunk_size]
            chunks.append(chunk)
        return chunks

    def merge_audio_chunks(self, chunks: list[bytes]) -> bytes:
        return b"".join(chunks)

    def validate_format(self, format: str) -> bool:
        return format.lower() in self.SUPPORTED_FORMATS

    def calculate_duration(self, audio_data: bytes) -> float:
        bytes_per_sample = self.bits_per_sample // 8
        total_samples = len(audio_data) / (bytes_per_sample * self.channels)
        duration = total_samples / self.sample_rate
        return duration

    def reset(self):
        pass

    def process_audio_chunk(self, data: bytes):
        pass

