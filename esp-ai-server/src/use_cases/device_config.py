from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, List

import asyncio
import base64
import io
import socket
import uuid
from dataclasses import dataclass, field
from typing import Any, List, Optional

from src.infrastructure.config import get_settings, SID_TTS, SID_CONNECTED, SCREEN_WIDTH, SCREEN_HEIGHT
from src.interfaces.tts_gateways import create_tts_gateway, VoiceGenerator
from src.domain.services import MemoryService
from src.domain.entities import Conversation, Message
from src.use_cases.session_fsm import SessionState

from src.infrastructure.logging import get_logger
logger = get_logger(__name__)

_CHUNK_SIZE = 2048


@dataclass
class DeviceConfig:
    device_id: str = ""
    name: str = ""
    key: str = ""
    api_key: str = ""  # 独立的管理 REST API 密钥（与 WS key 分离）
    asr_provider: str | None = None
    llm_type: str | None = None
    tts_type: str | None = None
    asr_config: dict | None = None
    tts_config: dict | None = None
    music_config: dict | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_system_prompt: str | None = None
    mcp_servers: dict | None = None
    rate_limit_rpm: int | None = None
    llm_memory_enabled: bool | None = None
    llm_memory_max_messages: int | None = None
    llm_memory_long_term_enabled: bool | None = None
    llm_memory_long_term_auto_extract: bool | None = None
    ota_enabled: bool = True
    ota_bin_url: str = ""
    ota_version: str = ""
    ota_bin_id: str = ""
    ota_is_official: str = "0"
    disabled_tools: list[str] = field(default_factory=list)
    disabled_mcp_servers: list[str] = field(default_factory=list)
    disabled_mcp_tools: dict = field(default_factory=dict)
    disabled_skills: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    # 插件商店：设备已安装插件列表（None/空 = 未安装任何插件）
    enabled_plugins: list[str] | None = None
    # 插件配置：{插件名: {配置项: 值}}
    plugin_configs: dict = field(default_factory=dict)
    # 设备屏幕能力（None = 未知，回退固件上报/默认有屏）
    has_display: bool | None = None
    wakeup_config: dict | None = None
    # 显示配置（机器人模式 / 屏保），字符串形式与 DB 列一致
    robot_mode: str = "false"
    screensaver_enabled: str = "true"
    screensaver_timeout: str = "30"

    def get_asr_config(self, provider: str) -> dict:
        if self.asr_config and provider in self.asr_config:
            return self.asr_config[provider]
        return {}

    def get_tts_config(self) -> dict:
        return self.tts_config or {}

    def get_effective_tts_config(self, device_id: str = None) -> dict:
        return self.get_tts_config()

    def get_effective_llm_model(self, device_id: str = None) -> str | None:
        return self.llm_model

    def get_effective_llm_system_prompt(self, device_id: str = None) -> str | None:
        return self.llm_system_prompt

    def get_effective_rate_limit(self, device_id: str = None) -> int | None:
        return self.rate_limit_rpm

    def get_ota_config(self) -> dict:
        return {
            "enabled": self.ota_enabled,
            "bin_url": self.ota_bin_url,
            "version": self.ota_version,
            "bin_id": self.ota_bin_id,
            "is_official": self.ota_is_official,
        }

@dataclass
class DeviceManager:
    devices: dict[str, DeviceConfig] = field(default_factory=dict)

    def resolve(self, key: str) -> DeviceConfig | None:
        if not key:
            return None
        for device_id, cfg in self.devices.items():
            if cfg.key == key:
                cfg.device_id = device_id
                return cfg
        return None

    def has_users(self) -> bool:
        return len(self.devices) > 0

    def has_devices(self) -> bool:
        return len(self.devices) > 0


def load_devices() -> DeviceManager:
    """加载所有设备配置，构建 DeviceManager。

    数据源为 DB（通过 DeviceRepository.load_all_devices_sync）。
    DB 不可用时记录错误日志并返回空 DeviceManager。
    """
    device_data: dict = {}
    try:
        from src.infrastructure.db.repositories.device_repository import DeviceRepository
        device_data = DeviceRepository().load_all_devices_sync() or {}
    except Exception as e:
        logger.error(f"从 DB 加载设备配置失败: {e}")
        device_data = {}

    devices = {}

    for device_id, raw in device_data.items():
        llm = raw.get("llm") or {}
        ota = raw.get("ota", {})

        devices[device_id] = DeviceConfig(
            device_id=device_id,
            name=raw.get("name", ""),
            key=raw.get("key", ""),
            api_key=raw.get("management_api_key", raw.get("api_key", "")),
            asr_provider=raw.get("asr_provider"),
            llm_type=raw.get("llm_type"),
            tts_type=raw.get("tts_type"),
            asr_config=raw.get("asr_config"),
            tts_config=raw.get("tts_config"),
            music_config=raw.get("music_config") or raw.get("music"),
            llm_api_key=llm.get("api_key"),
            llm_base_url=llm.get("base_url"),
            llm_model=llm.get("model"),
            llm_system_prompt=llm.get("system_prompt"),
            mcp_servers=raw.get("mcp_servers"),
            rate_limit_rpm=raw.get("rate_limit_rpm"),
            llm_memory_enabled=llm.get("memory_enabled"),
            llm_memory_max_messages=llm.get("memory_max_messages"),
            llm_memory_long_term_enabled=llm.get("memory_long_term_enabled"),
            llm_memory_long_term_auto_extract=llm.get("memory_long_term_auto_extract"),
            ota_enabled=ota.get("enabled", True),
            ota_bin_url=ota.get("bin_url", ""),
            ota_version=ota.get("version", ""),
            ota_bin_id=ota.get("bin_id", ""),
            ota_is_official=ota.get("is_official", "0"),
            disabled_tools=raw.get("disabled_tools", []),
            disabled_mcp_servers=raw.get("disabled_mcp_servers", []),
            disabled_mcp_tools=raw.get("disabled_mcp_tools", {}),
            disabled_skills=raw.get("disabled_skills", []),
            skills=raw.get("skills", []),
            enabled_plugins=raw.get("enabled_plugins"),
            plugin_configs=raw.get("plugin_configs") or {},
            has_display=raw.get("has_display"),
            wakeup_config=raw.get("wakeup") or raw.get("wakeup_config"),
            robot_mode=raw.get("robot_mode", "false"),
            screensaver_enabled=raw.get("screensaver_enabled", "true"),
            screensaver_timeout=raw.get("screensaver_timeout", "30"),
        )

    if devices:
        logger.info(f"加载了 {len(devices)} 个设备配置")
    return DeviceManager(devices=devices)

