"""
Ports - 端口接口

定义Use Case的输入输出边界，实现依赖倒置

已清理未使用的接口，只保留实际需要的：
- ConfigPort / LoggerPort（横切关注点）
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


# ═══════════════════════════════════════════════
# 横切关注点接口
# ═══════════════════════════════════════════════

class ConfigPort(ABC):
    """配置端口 - 提供应用配置对象"""

    @abstractmethod
    def get_settings(self):
        """返回全局 Settings 对象"""
        pass


class LoggerPort(ABC):
    """日志端口 - 提供结构化日志记录能力"""

    @abstractmethod
    def info(self, msg: str, *args, **kwargs) -> None:
        pass

    @abstractmethod
    def warning(self, msg: str, *args, **kwargs) -> None:
        pass

    @abstractmethod
    def error(self, msg: str, *args, **kwargs) -> None:
        pass

    @abstractmethod
    def debug(self, msg: str, *args, **kwargs) -> None:
        pass


class MemoryRepository(ABC):
    """记忆仓储端口 - 提供对话记忆的持久化"""

    @abstractmethod
    def load(self, device_id: str) -> list[dict]:
        """加载指定设备的对话历史"""
        pass

    @abstractmethod
    def save(self, device_id: str, messages: list[dict]) -> None:
        """保存指定设备的对话历史"""
        pass

    @abstractmethod
    def delete(self, device_id: str) -> None:
        """删除指定设备的对话历史"""
        pass


__all__ = [
    "ConfigPort",
    "LoggerPort",
    "MemoryRepository",
]
