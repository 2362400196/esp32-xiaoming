"""
Domain Layer - 领域层

包含：
- Entities: 核心业务实体（Session, Device, Conversation等）
- Value Objects: 值对象（AudioData, EmotionType等）
- Services: 领域服务接口（MemoryService被实际实现了）
- Exceptions: 领域异常

依赖规则：Domain层不依赖任何外层，只依赖Python标准库和typing
"""

__all__ = [
    "Session",
    "Device",
    "Conversation",
    "Message",
    "ToolCall",
    "AudioChunk",
    "SessionState",
    "SessionError",
    "EmotionType",
    "ASRProvider",
    "LLMProvider",
    "TTSProvider",
    "AudioFormat",
    "MemoryService",
    "ToolConfigRepository",
    "DomainError",
    "ConfigurationError",
    "AuthenticationError",
    "RateLimitExceededError",
]


def __getattr__(name):
    _ENTITY_MAP = {
        "Session": "Session",
        "Device": "Device",
        "Conversation": "Conversation",
        "Message": "Message",
        "ToolCall": "ToolCall",
        "AudioChunk": "AudioChunk",
        "SessionState": "SessionState",
        "SessionError": "SessionError",
    }
    if name in _ENTITY_MAP:
        from src.domain import entities
        return getattr(entities, name)

    _EXCEPTION_MAP = {
        "DomainError": "DomainError",
        "SessionError": "SessionError",
        "ConfigurationError": "ConfigurationError",
        "AuthenticationError": "AuthenticationError",
        "RateLimitExceededError": "RateLimitExceededError",
    }
    if name in _EXCEPTION_MAP:
        from src.domain import exceptions
        return getattr(exceptions, name)

    _VO_MAP = {
        "EmotionType": "EmotionType",
        "ASRProvider": "ASRProvider",
        "LLMProvider": "LLMProvider",
        "TTSProvider": "TTSProvider",
        "AudioFormat": "AudioFormat",
    }
    if name in _VO_MAP:
        from src.domain import value_objects
        return getattr(value_objects, name)

    _SERVICE_MAP = {
        "MemoryService": "MemoryService",
        "ToolConfigRepository": "ToolConfigRepository",
    }
    if name in _SERVICE_MAP:
        from src.domain import repositories
        return getattr(repositories, name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
