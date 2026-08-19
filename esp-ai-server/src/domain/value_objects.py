"""
Value Objects - 值对象

不可变的、通过值来识别的对象
"""
from __future__ import annotations

import enum
from dataclasses import dataclass


class EmotionType(enum.Enum):
    """情感类型枚举"""
    HAPPY = "happy"  # 快乐
    SAD = "sad"      # 伤心
    ANGRY = "angry"   # 愤怒
    SURPRISED = "surprised"  # 意外
    NEUTRAL = "neutral"      # 无情绪
    NEGATIVE = "negative"    # 否定


class ASRProvider(enum.Enum):
    """ASR服务提供商"""
    TENCENT = "tencent"       # 腾讯云
    VOLCENGINE = "volcengine"  # 火山引擎
    ALIYUN = "aliyun"         # 阿里云
    XUNFEI = "xunfei"         # 讯飞


class LLMProvider(enum.Enum):
    """LLM服务提供商"""
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"


class TTSProvider(enum.Enum):
    """TTS服务提供商"""
    VOLCENGINE = "volcengine"  # 火山引擎
    ALIYUN = "aliyun"          # 阿里云
    TENCENT = "tencent"        # 腾讯云


class AudioFormat(enum.Enum):
    """音频格式"""
    PCM = "pcm"
    MP3 = "mp3"
    WAV = "wav"
    OPUS = "opus"


@dataclass(frozen=True)
class AudioConfig:
    """音频配置值对象"""
    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2  # bytes per sample
    format: AudioFormat = AudioFormat.PCM

    @property
    def bytes_per_frame(self) -> int:
        """每帧字节数"""
        return self.sample_width * self.channels

    @property
    def bits_per_second(self) -> int:
        """比特率"""
        return self.sample_rate * self.sample_width * self.channels * 8


@dataclass(frozen=True)
class ASRConfig:
    """ASR配置值对象"""
    provider: ASRProvider
    no_speech_timeout: int = 5  # seconds
    silence_timeout: int = 3     # seconds
    max_concurrency: int = 5
    enable_vad: bool = True
    language: str = "zh-CN"

    @classmethod
    def for_tencent(cls, **kwargs) -> ASRConfig:
        """创建腾讯云ASR配置"""
        return cls(provider=ASRProvider.TENCENT, **kwargs)

    @classmethod
    def for_volcengine(cls, **kwargs) -> ASRConfig:
        """创建火山引擎ASR配置"""
        return cls(provider=ASRProvider.VOLCENGINE, **kwargs)


@dataclass(frozen=True)
class LLMConfig:
    """LLM配置值对象"""
    provider: LLMProvider = LLMProvider.OPENAI
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    system_prompt: str = ""
    temperature: float = 0.7
    max_tokens: int = 2000
    stream: bool = True
    memory_enabled: bool = True
    memory_max_messages: int = 20
    memory_max_tokens: int = 2000


@dataclass(frozen=True)
class TTSConfig:
    """TTS配置值对象"""
    provider: TTSProvider = TTSProvider.VOLCENGINE
    voice_type: str = ""
    speed: float = 1.0
    volume: float = 1.0
    pitch: float = 1.0
    max_concurrency: int = 10
    audio_format: AudioFormat = AudioFormat.MP3


@dataclass(frozen=True)
class PoolConfig:
    """连接池配置值对象"""
    enabled: bool = True
    max_size: int = 10
    min_size: int = 3
    heartbeat_interval: int = 30  # seconds
    idle_timeout: int = 300       # seconds
    connection_timeout: int = 15  # seconds


@dataclass(frozen=True)
class WebSocketConfig:
    """WebSocket配置值对象"""
    max_size: int = 20 * 1024 * 1024  # 20MB
    ping_interval: int = 20             # seconds
    ping_timeout: int = 20              # seconds
    keepalive_interval: int = 3         # seconds


@dataclass(frozen=True)
class MemoryQuery:
    """长期记忆查询值对象"""
    device_id: str = ""                      # 所属设备
    summary_labels: tuple[str, ...] = ()     # 摘要标签过滤（精确匹配）
    keyword: str = ""                        # 关键词搜索
    limit: int = 8                           # 返回上限


__all__ = [
    "EmotionType",
    "ASRProvider",
    "LLMProvider",
    "TTSProvider",
    "AudioFormat",
    "AudioConfig",
    "ASRConfig",
    "LLMConfig",
    "TTSConfig",
    "PoolConfig",
    "WebSocketConfig",
    "MemoryQuery",
]
