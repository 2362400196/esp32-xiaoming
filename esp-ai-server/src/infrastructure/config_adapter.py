"""Config Adapter - 实现 ConfigPort 接口"""
from __future__ import annotations

from src.use_cases.ports import ConfigPort
from src.infrastructure.config import get_settings as _get_settings


class SettingsConfigAdapter(ConfigPort):
    """通过 infrastructure.config.get_settings() 实现 ConfigPort"""

    def get_settings(self):
        return _get_settings()
