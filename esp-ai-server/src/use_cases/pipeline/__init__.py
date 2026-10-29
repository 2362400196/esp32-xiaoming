"""对话流水线（4-Worker 并发架构）。

原 ``src.use_cases.pipeline`` 模块已按职责拆分到本子包，导入路径保持不变：
- signals: 流内控制信号与错误 token 约定
- prompt_cache: prompt 组装素材的模块级缓存
- mp3: MP3 时长解析与字级时间戳估算
- splitter: 流式 token 句子分割器
- types: PipelineState / PipelineConfig / PipelineResult
- emotion: 情绪标签解析与表情下发
- runner: 主流程 run()
- workers: LLM / Splitter / TTS / Sender 四个 Worker
- core: 类组装与 create_pipeline 工厂
"""
from __future__ import annotations

from src.use_cases.pipeline.core import ConversationPipeline, create_pipeline
from src.use_cases.pipeline.mp3 import _estimate_word_timestamps, mp3_duration_ms
from src.use_cases.pipeline.prompt_cache import PROMPT_CACHE_TTL, prewarm_prompt_caches
from src.use_cases.pipeline.signals import (
    DEFAULT_MEMORY_SEARCH_KEYWORDS,
    LLM_ERROR_PREFIX,
    LLM_INSUFFICIENT_BALANCE_REPLY,
    STOP_PIPELINE_SENTINEL,
    llm_stream_error_token,
)
from src.use_cases.pipeline.splitter import SentenceSplitter
from src.use_cases.pipeline.types import PipelineConfig, PipelineResult, PipelineState

__all__ = [
    "ConversationPipeline",
    "SentenceSplitter",
    "PipelineConfig",
    "PipelineResult",
    "PipelineState",
    "STOP_PIPELINE_SENTINEL",
    "LLM_ERROR_PREFIX",
    "LLM_INSUFFICIENT_BALANCE_REPLY",
    "llm_stream_error_token",
    "DEFAULT_MEMORY_SEARCH_KEYWORDS",
    "PROMPT_CACHE_TTL",
    "prewarm_prompt_caches",
    "mp3_duration_ms",
    "_estimate_word_timestamps",
    "create_pipeline",
]
