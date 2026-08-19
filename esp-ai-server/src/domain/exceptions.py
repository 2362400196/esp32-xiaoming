"""
Domain Exceptions - 领域异常

定义领域层专用的异常类型
"""


class DomainError(Exception):
    """领域异常基类"""

    def __init__(self, message: str, code: str = "", details: dict = None):
        super().__init__(message)
        self.message = message
        self.code = code or self.__class__.__name__
        self.details = details or {}

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "error": self.code,
            "message": self.message,
            "details": self.details,
        }


# ── Session 异常 ──

class SessionError(Exception):
    pass


class SessionNotFoundError(DomainError):
    """会话未找到"""
    def __init__(self, session_id: str = ""):
        super().__init__(
            message=f"Session not found: {session_id}",
            code="SESSION_NOT_FOUND",
            details={"session_id": session_id}
        )


class SessionAlreadyExistsError(DomainError):
    """会话已存在"""
    def __init__(self, device_id: str = ""):
        super().__init__(
            message=f"Session already exists for device: {device_id}",
            code="SESSION_ALREADY_EXISTS",
            details={"device_id": device_id}
        )


class InvalidStateTransitionError(DomainError):
    """无效的状态转换"""
    def __init__(self, current: str, target: str):
        super().__init__(
            message=f"Invalid state transition from {current} to {target}",
            code="INVALID_STATE_TRANSITION",
            details={"current_state": current, "target_state": target}
        )


class SessionClosedError(DomainError):
    """会话已关闭"""
    def __init__(self, session_id: str = ""):
        super().__init__(
            message=f"Session is closed: {session_id}",
            code="SESSION_CLOSED",
            details={"session_id": session_id}
        )


# ── Device 异常 ──

class DeviceNotFoundError(DomainError):
    """设备未找到"""
    def __init__(self, device_id: str = ""):
        super().__init__(
            message=f"Device not found: {device_id}",
            code="DEVICE_NOT_FOUND",
            details={"device_id": device_id}
        )


class DeviceAuthenticationError(DomainError):
    """设备认证失败"""
    def __init__(self, device_key: str = ""):
        super().__init__(
            message=f"Device authentication failed: {device_key}",
            code="DEVICE_AUTH_FAILED",
            details={"device_key": device_key[:8] if device_key else ""}
        )


class DeviceOfflineError(DomainError):
    """设备离线"""
    def __init__(self, device_id: str = ""):
        super().__init__(
            message=f"Device is offline: {device_id}",
            code="DEVICE_OFFLINE",
            details={"device_id": device_id}
        )


class DeviceLimitExceededError(DomainError):
    """设备数量超限"""
    def __init__(self, message: str = "Device limit exceeded", max_devices: int = 0):
        super().__init__(
            message=message,
            code="DEVICE_LIMIT_EXCEEDED",
            details={"max_devices": max_devices}
        )


# ── Session 异常（续） ──

class SessionLimitExceededError(DomainError):
    """会话数量超限"""
    def __init__(self, message: str = "Session limit exceeded", max_sessions: int = 0):
        super().__init__(
            message=message,
            code="SESSION_LIMIT_EXCEEDED",
            details={"max_sessions": max_sessions}
        )


# ── ASR 异常 ──

class ASRError(DomainError):
    """ASR通用错误"""
    def __init__(self, message: str, provider: str = ""):
        super().__init__(
            message=message,
            code="ASR_ERROR",
            details={"provider": provider}
        )


class ASRConnectionError(ASRError):
    """ASR连接错误"""
    def __init__(self, provider: str = "", reason: str = ""):
        super().__init__(
            message=f"ASR connection error: {reason}",
            provider=provider
        )
        self.code = "ASR_CONNECTION_ERROR"


class ASRTimeoutError(ASRError):
    """ASR超时错误"""
    def __init__(self, provider: str = "", timeout: float = 0.0):
        super().__init__(
            message=f"ASR timeout after {timeout}s",
            provider=provider
        )
        self.code = "ASR_TIMEOUT"
        self.details["timeout"] = timeout


class ASRNoSpeechError(ASRError):
    """无语音输入错误"""
    def __init__(self, provider: str = ""):
        super().__init__(
            message="No speech detected",
            provider=provider
        )
        self.code = "ASR_NO_SPEECH"


# ── LLM 异常 ──

class LLMError(DomainError):
    """LLM通用错误"""
    def __init__(self, message: str, provider: str = ""):
        super().__init__(
            message=message,
            code="LLM_ERROR",
            details={"provider": provider}
        )


class LLMConnectionError(LLMError):
    """LLM连接错误"""
    def __init__(self, provider: str = "", reason: str = ""):
        super().__init__(
            message=f"LLM connection error: {reason}",
            provider=provider
        )
        self.code = "LLM_CONNECTION_ERROR"


class LLMTokenLimitError(LLMError):
    """Token超限错误"""
    def __init__(self, provider: str = "", limit: int = 0, actual: int = 0):
        super().__init__(
            message=f"Token limit exceeded: {actual}/{limit}",
            provider=provider
        )
        self.code = "LLM_TOKEN_LIMIT_EXCEEDED"
        self.details.update({"limit": limit, "actual": actual})


class LLMStreamingError(LLMError):
    """流式输出错误"""
    def __init__(self, provider: str = "", reason: str = ""):
        super().__init__(
            message=f"LLM streaming error: {reason}",
            provider=provider
        )
        self.code = "LLM_STREAMING_ERROR"


class LLMTimeoutError(LLMError):
    """LLM超时错误"""
    def __init__(self, provider: str = "", timeout: float = 0.0):
        super().__init__(
            message=f"LLM timeout after {timeout}s",
            provider=provider
        )
        self.code = "LLM_TIMEOUT"
        self.details["timeout"] = timeout


# ── TTS 异常 ──

class TTSError(DomainError):
    """TTS通用错误"""
    def __init__(self, message: str, provider: str = ""):
        super().__init__(
            message=message,
            code="TTS_ERROR",
            details={"provider": provider}
        )


class TTSConnectionError(TTSError):
    """TTS连接错误"""
    def __init__(self, provider: str = "", reason: str = ""):
        super().__init__(
            message=f"TTS connection error: {reason}",
            provider=provider
        )
        self.code = "TTS_CONNECTION_ERROR"


class TTSSynthesisError(TTSError):
    """TTS合成错误"""
    def __init__(self, provider: str = "", text: str = "", reason: str = ""):
        super().__init__(
            message=f"TTS synthesis failed: {reason}",
            provider=provider
        )
        self.code = "TTS_SYNTHESIS_ERROR"
        self.details["text_preview"] = text[:100]


class TTSTimeoutError(TTSError):
    """TTS超时错误"""
    def __init__(self, provider: str = "", timeout: float = 0.0):
        super().__init__(
            message=f"TTS timeout after {timeout}s",
            provider=provider
        )
        self.code = "TTS_TIMEOUT"
        self.details["timeout"] = timeout


# ── Audio 异常 ──

class AudioProcessingError(DomainError):
    """音频处理错误"""
    def __init__(self, message: str = "", operation: str = ""):
        super().__init__(
            message=message or f"Audio processing error in {operation}",
            code="AUDIO_PROCESSING_ERROR",
            details={"operation": operation}
        )


# ── WebSocket 异常 ──

class WebSocketError(DomainError):
    """WebSocket通用错误"""
    def __init__(self, message: str = "", code: str = "WS_ERROR"):
        super().__init__(
            message=message or "WebSocket error",
            code=code
        )


# ── Pipeline 异常 ──

class PipelineError(DomainError):
    """Pipeline通用错误"""
    def __init__(self, message: str, stage: str = ""):
        super().__init__(
            message=message,
            code="PIPELINE_ERROR",
            details={"stage": stage}
        )


class PipelineInterruptedError(PipelineError):
    """Pipeline被中断"""
    def __init__(self, stage: str = ""):
        super().__init__(
            message="Pipeline was interrupted",
            stage=stage
        )
        self.code = "PIPELINE_INTERRUPTED"


class PipelineStageError(PipelineError):
    """Pipeline阶段错误"""
    def __init__(self, stage: str, reason: str = ""):
        super().__init__(
            message=f"Pipeline stage '{stage}' failed: {reason}",
            stage=stage
        )
        self.code = "PIPELINE_STAGE_ERROR"


# ── Tool 异常 ──

class ToolError(DomainError):
    """工具通用错误"""
    def __init__(self, message: str, tool_name: str = ""):
        super().__init__(
            message=message,
            code="TOOL_ERROR",
            details={"tool_name": tool_name}
        )


class ToolNotFoundError(ToolError):
    """工具未找到"""
    def __init__(self, tool_name: str = ""):
        super().__init__(
            message=f"Tool not found: {tool_name}",
            tool_name=tool_name
        )
        self.code = "TOOL_NOT_FOUND"


class ToolExecutionError(ToolError):
    """工具执行错误"""
    def __init__(self, tool_name: str = "", reason: str = ""):
        super().__init__(
            message=f"Tool execution failed: {reason}",
            tool_name=tool_name
        )
        self.code = "TOOL_EXECUTION_ERROR"


class ToolTimeoutError(ToolError):
    """工具超时错误"""
    def __init__(self, tool_name: str = "", timeout: float = 0.0):
        super().__init__(
            message=f"Tool execution timeout after {timeout}s",
            tool_name=tool_name
        )
        self.code = "TOOL_TIMEOUT"
        self.details["timeout"] = timeout


# ── Auth 异常 ──

class AuthenticationError(DomainError):
    """认证错误"""
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(
            message=message,
            code="AUTHENTICATION_ERROR"
        )


class RateLimitExceededError(DomainError):
    """速率限制超限"""
    def __init__(self, limit: int = 0, window: str = "minute"):
        super().__init__(
            message=f"Rate limit exceeded: {limit} requests per {window}",
            code="RATE_LIMIT_EXCEEDED",
            details={"limit": limit, "window": window}
        )


# ── 配置异常 ──

class ConfigurationError(DomainError):
    """配置错误"""
    def __init__(self, message: str, key: str = ""):
        super().__init__(
            message=message,
            code="CONFIGURATION_ERROR",
            details={"key": key}
        )


class MissingConfigurationError(ConfigurationError):
    """缺少必要配置"""
    def __init__(self, key: str = ""):
        super().__init__(
            message=f"Missing required configuration: {key}",
            key=key
        )
        self.code = "MISSING_CONFIGURATION"


__all__ = [
    # Base
    "DomainError",
    # Session
    "SessionError",
    "SessionNotFoundError",
    "SessionAlreadyExistsError",
    "InvalidStateTransitionError",
    "SessionClosedError",
    "SessionLimitExceededError",
    # Device
    "DeviceNotFoundError",
    "DeviceAuthenticationError",
    "DeviceOfflineError",
    "DeviceLimitExceededError",
    # ASR
    "ASRError",
    "ASRConnectionError",
    "ASRTimeoutError",
    "ASRNoSpeechError",
    # LLM
    "LLMError",
    "LLMConnectionError",
    "LLMTimeoutError",
    "LLMTokenLimitError",
    "LLMStreamingError",
    # TTS
    "TTSError",
    "TTSConnectionError",
    "TTSTimeoutError",
    "TTSSynthesisError",
    # Audio
    "AudioProcessingError",
    # WebSocket
    "WebSocketError",
    # Pipeline
    "PipelineError",
    "PipelineInterruptedError",
    "PipelineStageError",
    # Tool
    "ToolError",
    "ToolNotFoundError",
    "ToolExecutionError",
    "ToolTimeoutError",
    # Auth
    "AuthenticationError",
    "RateLimitExceededError",
    # Config
    "ConfigurationError",
    "MissingConfigurationError",
]
