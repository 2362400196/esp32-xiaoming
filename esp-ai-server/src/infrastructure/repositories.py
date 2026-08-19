"""
Repository Implementations - 仓储接口的内存实现

当前使用内存存储，未来可以替换为数据库实现。
只需替换工厂函数返回的实现类即可。

注意：UserRepository / DeviceRepository / SessionRepository / AuditLogRepository
的内存实现及对应的领域接口已清理（无任何使用点）。本模块仅保留仍在用的
ToolConfigRepository 内存实现。
"""

from __future__ import annotations
from typing import Dict, List, Optional, Any

from src.domain.repositories import ToolConfigRepository
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


class InMemoryToolConfigRepository(ToolConfigRepository):
    """内存工具配置仓储实现"""

    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._mcp_servers: Dict[str, List[Dict[str, Any]]] = {}

    async def get_tool_config(self, tool_name: str) -> Optional[Dict[str, Any]]:
        return self._tools.get(tool_name)

    async def list_tools(self) -> List[Dict[str, Any]]:
        return list(self._tools.values())

    async def save_tool_config(self, tool_name: str, config: Dict[str, Any]) -> bool:
        config["tool_name"] = tool_name
        self._tools[tool_name] = config.copy()
        return True

    async def delete_tool(self, tool_name: str) -> bool:
        if tool_name in self._tools:
            del self._tools[tool_name]
            return True
        return False

    async def get_mcp_servers(self, user_id: str) -> List[Dict[str, Any]]:
        return self._mcp_servers.get(user_id, [])

    async def save_mcp_server(self, user_id: str, server_name: str, config: Dict[str, Any]) -> bool:
        if user_id not in self._mcp_servers:
            self._mcp_servers[user_id] = []
        servers = self._mcp_servers[user_id]
        for i, s in enumerate(servers):
            if s.get("name") == server_name:
                servers[i] = config
                return True
        config["name"] = server_name
        servers.append(config)
        return True


def create_tool_config_repository() -> ToolConfigRepository:
    """创建工具配置仓储实例"""
    return InMemoryToolConfigRepository()


__all__ = [
    "InMemoryToolConfigRepository",
    "create_tool_config_repository",
]
