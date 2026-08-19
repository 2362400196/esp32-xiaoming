"""
Repository Interfaces - 仓储接口定义

这些接口用于解耦业务逻辑和数据访问层。
未来集成数据库时，只需实现这些接口即可，无需修改业务逻辑代码。

使用方式：
1. 定义接口（如 ToolConfigRepository, LongTermMemoryRepository）
2. 创建具体实现（当前）/ 数据库实现（未来）
3. 通过依赖注入替换实现

注意：UserRepository / DeviceRepository / SessionRepository / AuditLogRepository
等未使用的接口已清理；ASR/LLM/TTS/Tool 仓储接口由各 Gateway 实现。
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional, Dict, Any

if TYPE_CHECKING:
    from src.domain.entities import MemoryItem


class ToolConfigRepository(ABC):
    """工具配置仓储接口 - 管理工具和MCP配置"""

    @abstractmethod
    async def get_tool_config(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """获取工具配置"""
        pass

    @abstractmethod
    async def list_tools(self) -> List[Dict[str, Any]]:
        """获取所有工具配置"""
        pass

    @abstractmethod
    async def save_tool_config(self, tool_name: str, config: Dict[str, Any]) -> bool:
        """保存工具配置"""
        pass

    @abstractmethod
    async def delete_tool(self, tool_name: str) -> bool:
        """删除工具配置"""
        pass

    @abstractmethod
    async def get_mcp_servers(self, user_id: str) -> List[Dict[str, Any]]:
        """获取用户的MCP服务器配置"""
        pass

    @abstractmethod
    async def save_mcp_server(self, user_id: str, server_name: str, config: Dict[str, Any]) -> bool:
        """保存MCP服务器配置"""
        pass


class ASRRepository(ABC):
    """ASR 语音识别仓储接口"""

    @abstractmethod
    async def recognize(self, audio_data: bytes) -> str:
        """识别音频数据，返回文本"""
        pass

    @abstractmethod
    async def recognize_stream(self, audio_stream: "AsyncIterator[bytes]") -> str:
        """流式识别音频数据"""
        pass


class TTSRepository(ABC):
    """TTS 语音合成仓储接口"""

    @abstractmethod
    async def synthesize(self, text: str) -> bytes:
        """合成文本为音频，返回音频数据"""
        pass

    @abstractmethod
    async def synthesize_stream(self, text: str) -> "AsyncIterator[bytes]":
        """流式合成文本为音频"""
        pass


class LongTermMemoryRepository(ABC):
    """长期记忆仓储接口 - 领域级操作

    接口表达"存什么、查什么"，不暴露"存在哪里、怎么存"。
    底层可以是 JSONL、SQLite、PostgreSQL，对调用方透明。
    """

    @abstractmethod
    async def save(self, item: "MemoryItem") -> None:
        """保存一条记忆条目（追加 + 索引重建）"""
        pass

    @abstractmethod
    async def find_by_labels(self, device_id: str,
                             summary_labels: tuple[str, ...],
                             limit: int) -> list["MemoryItem"]:
        """按摘要标签查找记忆，按 access_count 降序"""
        pass

    @abstractmethod
    async def find_all(self, device_id: str) -> list["MemoryItem"]:
        """列出设备全部活跃记忆"""
        pass

    @abstractmethod
    async def find_by_id(self, memory_id: str,
                         device_id: str) -> Optional["MemoryItem"]:
        """查找单条记忆"""
        pass

    @abstractmethod
    async def mark_deleted(self, memory_id: str, device_id: str) -> None:
        """软删除一条记忆"""
        pass

    @abstractmethod
    async def get_summary_labels(self, device_id: str) -> list[str]:
        """获取设备的摘要标签列表"""
        pass

    @abstractmethod
    async def increment_access(self, memory_id: str,
                               device_id: str) -> None:
        """增加记忆的访问计数"""
        pass

    @abstractmethod
    async def get_storage_dir(self) -> str:
        """返回记忆存储根目录"""
        pass


class LLMRepository(ABC):
    """LLM 大语言模型仓储接口"""

    @abstractmethod
    async def chat(self, messages: List[Dict[str, Any]], **kwargs) -> str:
        """聊天对话，返回回复文本"""
        pass

    @abstractmethod
    async def chat_stream(self, messages: List[Dict[str, Any]], **kwargs) -> "AsyncIterator[str]":
        """流式聊天对话"""
        pass


class ToolRepository(ABC):
    """工具仓储接口 - 管理工具和MCP配置"""

    @abstractmethod
    async def get_available_tools(self) -> list[dict]:
        """获取所有可用工具"""
        pass

    @abstractmethod
    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict,
        context: Optional[dict] = None
    ) -> Any:
        """执行工具"""
        pass

    @abstractmethod
    async def discover_tools(self) -> None:
        """发现并加载工具"""
        pass


__all__ = [
    "ToolConfigRepository",
    "ASRRepository",
    "TTSRepository",
    "LLMRepository",
    "ToolRepository",
    "LongTermMemoryRepository",
]
