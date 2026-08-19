"""
Auxiliary Services - Re-export hub

为保持向后兼容，从拆分后的专用模块重新导出所有类。
新代码请直接 import 对应模块，不要从此文件导入。
"""

from src.use_cases.device_registry import DeviceRegistry
from src.use_cases.wake_audio import WakeAudioManager
from src.use_cases.emotion import EmotionDetector, EmotionRenderer
from src.use_cases.image_sender import ImageSender
from src.use_cases.device_config import DeviceConfig, DeviceManager, load_devices
from src.use_cases.memory import ConversationMemory
from src.use_cases.audio_processor import AudioProcessor
from src.use_cases.speaker import Speaker
from src.use_cases.auth_service import (
    AuthService,
    create_emotion_detection,
    create_device_manager,
    create_audio_processor,
    create_memory_service,
    create_wake_audio_manager,
    create_speaker,
    create_auth_service,
)

__all__ = [
    "DeviceRegistry",
    "WakeAudioManager",
    "EmotionDetector",
    "EmotionRenderer",
    "ImageSender",
    "DeviceConfig",
    "DeviceManager",
    "load_devices",
    "ConversationMemory",
    "AudioProcessor",
    "Speaker",
    "AuthService",
    "create_emotion_detection",
    "create_device_manager",
    "create_audio_processor",
    "create_memory_service",
    "create_wake_audio_manager",
    "create_speaker",
    "create_auth_service",
]
