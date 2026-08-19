"""
Use Cases - Application business rules and orchestration

This module contains:
- Pipeline: 4-worker concurrent processing pipeline
- Session management: Session lifecycle and FSM
- Tools system: Builtin tools, MCP, circuit breaker, cache
- Auxiliary services: Device, emotion, memory, wake audio
"""

__all__ = [
    "ConversationPipeline",
    "SentenceSplitter",
    "StopPipeline",
    "Session",
    "SessionFSM",
    "WSChannel",
    "SessionState",
    "ToolDefinition",
    "ToolManager",
    "PerUserToolManager",
    "ToolCache",
    "CircuitBreaker",
    "CircuitBreakerManager",
    "MCPClient",
    "MCPPool",
    "create_tool_manager",
    "get_all_tools",
    "get_openai_tools_schema",
    "get_tool",
    "DeviceRegistry",
    "DeviceConfig",
    "DeviceManager",
    "WakeAudioManager",
    "EmotionDetector",
    "EmotionRenderer",
    "ImageSender",
    "Speaker",
    "AuthService",
    "ConversationMemory",
    "AudioProcessor",
    "create_device_manager",
    "create_wake_audio_manager",
    "create_emotion_detection",
    "create_audio_processor",
    "create_memory_service",
    "create_speaker",
    "create_auth_service",
    "load_devices",
    "VoiceGenerator",
    "BackpressureQueues",
    "BackpressureQueue",
    "TextQueue",
    "AudioQueue",
    "SendQueue",
]


def __getattr__(name):
    if name in ("ConversationPipeline", "SentenceSplitter"):
        from src.use_cases import pipeline
        return getattr(pipeline, name)
    if name == "Session":
        from src.use_cases import session
        return getattr(session, name)
    if name in ("SessionFSM", "WSChannel"):
        from src.use_cases import session_fsm
        return getattr(session_fsm, name)
    if name == "SessionState":
        from src.domain.entities import SessionState
        return SessionState
    if name in (
        "ToolDefinition", "ToolManager", "PerUserToolManager", "ToolCache",
        "CircuitBreaker", "CircuitBreakerManager", "MCPClient", "MCPPool",
        "StopPipeline", "create_tool_manager", "get_all_tools",
        "get_openai_tools_schema", "get_tool",
    ):
        from src.use_cases import tools_system
        return getattr(tools_system, name)
    if name in ("DeviceRegistry",):
        from src.use_cases import device_registry
        return getattr(device_registry, name)
    if name in ("WakeAudioManager",):
        from src.use_cases import wake_audio
        return getattr(wake_audio, name)
    if name in ("EmotionDetector", "EmotionRenderer"):
        from src.use_cases import emotion
        return getattr(emotion, name)
    if name in ("ImageSender",):
        from src.use_cases import image_sender
        return getattr(image_sender, name)
    if name in ("DeviceConfig", "DeviceManager", "load_devices"):
        from src.use_cases import device_config
        return getattr(device_config, name)
    if name in ("ConversationMemory",):
        from src.use_cases import memory
        return getattr(memory, name)
    if name in ("AudioProcessor",):
        from src.use_cases import audio_processor
        return getattr(audio_processor, name)
    if name in ("Speaker",):
        from src.use_cases import speaker
        return getattr(speaker, name)
    if name in ("AuthService", "create_emotion_detection", "create_device_manager",
                "create_audio_processor", "create_memory_service",
                "create_wake_audio_manager", "create_speaker", "create_auth_service"):
        from src.use_cases import auth_service
        return getattr(auth_service, name)
    if name == "VoiceGenerator":
        from src.use_cases.voice_generator import VoiceGenerator
        return VoiceGenerator
    if name in ("BackpressureQueues", "BackpressureQueue", "TextQueue", "AudioQueue", "SendQueue"):
        from src.use_cases import queues
        return getattr(queues, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
