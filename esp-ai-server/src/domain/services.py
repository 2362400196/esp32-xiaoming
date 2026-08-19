"""
Domain Services - 领域服务接口

MemoryService: 对话记忆（session history）
LongTermMemoryService: 跨会话的长期记忆
AutoExtractService: 从用户消息自动提取耐久事实
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.domain.entities import Conversation, Message, MemoryItem
    from src.domain.value_objects import MemoryQuery


class MemoryService(ABC):
    """对话记忆服务接口（session history）"""

    @abstractmethod
    def get_conversation(self, session_id: str) -> Optional["Conversation"]:
        pass

    @abstractmethod
    def add_message(self, session_id: str, message: "Message") -> None:
        pass

    @abstractmethod
    def get_history(self, session_id: str, limit: int = 20) -> List["Message"]:
        pass

    @abstractmethod
    def clear(self, session_id: str) -> None:
        pass

    @abstractmethod
    def clear_all(self) -> None:
        pass


class LongTermMemoryService(ABC):
    """长期记忆服务接口 - 纯领域操作

    注意：auto_extract（自动提取）不属于领域层，
    它是 Use Case 层的编排逻辑，实现在 src/use_cases/memory.py 中。
    """

    @abstractmethod
    async def store(self, item: "MemoryItem") -> tuple[str, bool]:
        pass

    @abstractmethod
    async def recall(self, query: "MemoryQuery") -> list["MemoryItem"]:
        pass

    @abstractmethod
    async def list_all(self, device_id: str) -> list["MemoryItem"]:
        pass

    @abstractmethod
    async def update(self, memory_id: str, patch: dict,
                     device_id: str) -> bool:
        pass

    @abstractmethod
    async def forget(self, memory_id: str,
                     device_id: str) -> Optional["MemoryItem"]:
        pass

    @abstractmethod
    async def get_summary_catalog(self, device_id: str) -> str:
        pass


__all__ = [
    "MemoryService",
    "LongTermMemoryService",
]
