"""External service gateways and adapters.

ASR 网关已按 provider 拆分到 ``src.interfaces.asr`` 子包，此处重新导出以保持向后兼容。
LLM、TTS 网关分别在 ``llm_gateways.py``、``tts_gateways.py``（历史上的本文件副本已删除，
避免出现两套同名网关实现导致误导入）。
"""
from __future__ import annotations

from src.interfaces.asr import (
    AliYunASRGateway,
    BaseASRGateway,
    TencentASRGateway,
    VolcEngineASRConnectionPool,
    VolcEngineASRGateway,
    XunfeiASRGateway,
    create_asr_gateway,
)

__all__ = [
    "BaseASRGateway",
    "TencentASRGateway",
    "VolcEngineASRGateway",
    "AliYunASRGateway",
    "XunfeiASRGateway",
    "VolcEngineASRConnectionPool",
    "create_asr_gateway",
]
