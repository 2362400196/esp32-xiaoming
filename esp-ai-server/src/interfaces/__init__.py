"""
Interfaces - External service gateways and adapters

This module contains implementations for external service integrations:
- ASR gateways (Tencent, VolcEngine, Aliyun, Xunfei)
- TTS gateways (VolcEngine)
- LLM gateways (OpenAI compatible)
- WebSocket protocol handler
"""

__all__ = [
    "BaseASRGateway",
    "TencentASRGateway",
    "VolcEngineASRGateway",
    "AliYunASRGateway",
    "XunfeiASRGateway",
    "create_asr_gateway",
    "VolcEngineTTSGateway",
    "TTSSession",
    "VoiceGenerator",
    "create_tts_gateway",
    "OpenAILLMGateway",
    "create_llm_gateway",
    "SessionState",
    "SessionFSM",
    "WSChannel",
]


def __getattr__(name):
    if name in (
        "BaseASRGateway", "TencentASRGateway", "VolcEngineASRGateway",
        "AliYunASRGateway", "XunfeiASRGateway", "create_asr_gateway",
    ):
        from src.interfaces import gateways
        return getattr(gateways, name)
    if name in ("VolcEngineTTSGateway", "TTSSession", "VoiceGenerator", "create_tts_gateway"):
        from src.interfaces import tts_gateways
        return getattr(tts_gateways, name)
    if name in ("OpenAILLMGateway", "create_llm_gateway"):
        from src.interfaces import llm_gateways
        return getattr(llm_gateways, name)
    if name in ("SessionState", "SessionFSM", "WSChannel"):
        from src.use_cases import session_fsm
        return getattr(session_fsm, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
