"""流水线状态、配置与结果数据结构。"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


class PipelineState(Enum):
    IDLE = auto()
    RUNNING = auto()
    STOPPING = auto()
    STOPPED = auto()
    ERROR = auto()


@dataclass
class PipelineConfig:
    max_queue_size: int = 100
    llm_timeout: float = 30.0
    tts_timeout: float = 20.0
    enable_tts_session_reuse: bool = True
    tts_session_id: str = "0010"
    text_send_delay: int = 1
    client_max_buffer: int = 10240


@dataclass
class PipelineResult:
    state: PipelineState
    duration: float = 0.0
    total_sentences: int = 0
    total_audio_chunks: int = 0
    full_text: str = ""
    error: Optional[str] = None
    stop_pipeline: bool = False
    total_duration_ms: float = 0.0  # 总音频时长（毫秒）
