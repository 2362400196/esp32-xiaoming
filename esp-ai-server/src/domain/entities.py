"""
Domain Entities - 领域实体

核心业务对象，具有唯一标识和生命周期
"""
from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional


class SessionState(enum.Enum):
    """会话状态枚举"""
    IDLE = "idle"
    ASR = "asr"
    LLM = "llm"
    TTS = "tts"
    INTERRUPTED = "interrupted"
    CLOSED = "closed"


@dataclass
class Message:
    """对话消息实体"""
    role: str  # "system", "user", "assistant", "tool"
    content: str
    timestamp: float = field(default_factory=time.time)
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式（用于LLM API）"""
        return {
            "role": self.role,
            "content": self.content,
        }

    def __repr__(self) -> str:
        return f"Message(role={self.role}, content={self.content[:50]}...)"


@dataclass
class Conversation:
    """对话上下文实体"""
    conversation_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    messages: list[Message] = field(default_factory=list)
    max_messages: int = 20
    max_tokens: int = 2000
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def add_message(self, message: Message) -> None:
        """添加消息到对话历史"""
        self.messages.append(message)
        self.updated_at = time.time()
        self._trim_messages()

    def add_user_message(self, content: str) -> Message:
        """添加用户消息"""
        msg = Message(role="user", content=content)
        self.add_message(msg)
        return msg

    def add_assistant_message(self, content: str) -> Message:
        """添加助手回复"""
        msg = Message(role="assistant", content=content)
        self.add_message(msg)
        return msg

    def add_system_message(self, content: str) -> Message:
        """添加系统提示"""
        msg = Message(role="system", content=content)
        self.add_message(msg)
        return msg

    def _trim_messages(self) -> None:
        """裁剪超出限制的消息"""
        while len(self.messages) > self.max_messages:
            # 保留系统消息，删除最旧的非系统消息
            for i, msg in enumerate(self.messages):
                if msg.role != "system":
                    del self.messages[i]
                    break

    def build_messages_for_llm(
        self,
        system_prompt: str,
        user_input: str,
    ) -> list[dict[str, str]]:
        """
        构建用于LLM的消息列表

        Args:
            system_prompt: 系统提示词
            user_input: 当前用户输入

        Returns:
            格式化后的消息列表
        """
        messages = [{"role": "system", "content": system_prompt}]

        # 添加历史消息（排除系统消息）
        for msg in self.messages:
            if msg.role != "system":
                messages.append(msg.to_dict())

        # 添加当前用户输入
        messages.append({"role": "user", "content": user_input})

        return messages

    def clear(self) -> None:
        """清空对话历史"""
        self.messages.clear()
        self.updated_at = time.time()

    @property
    def message_count(self) -> int:
        return len(self.messages)


@dataclass
class ToolCall:
    """工具调用实体"""
    tool_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    result: Optional[Any] = None
    status: str = "pending"  # pending, running, completed, failed
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None

    def complete(self, result: Any) -> None:
        """标记工具调用完成"""
        self.result = result
        self.status = "completed"
        self.completed_at = time.time()

    def fail(self, error: str) -> None:
        """标记工具调用失败"""
        self.result = {"error": error}
        self.status = "failed"
        self.completed_at = time.time()


@dataclass
class AudioChunk:
    """音频数据块"""
    data: bytes
    format: str = "pcm"
    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2
    timestamp: float = field(default_factory=time.time)
    is_final: bool = False

    @property
    def duration_ms(self) -> float:
        """计算音频时长（毫秒）"""
        if self.sample_rate > 0 and self.sample_width > 0 and self.channels > 0:
            bytes_per_sample = self.sample_width * self.channels
            samples = len(self.data) / bytes_per_sample
            return (samples / self.sample_rate) * 1000
        return 0.0



@dataclass
class Session:
    """会话实体 - 核心业务对象"""
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    device_id: str = ""
    state: SessionState = SessionState.IDLE
    conversation: Conversation = field(default_factory=Conversation)
    trace_id: str = ""
    created_at: float = field(default_factory=time.time)
    closed: bool = False
    tts_playing: bool = False
    _cancel_event: Optional[Any] = None  # asyncio.Event

    def __post_init__(self):
        if not self.session_id:
            self.session_id = uuid.uuid4().hex[:8]

    @property
    def duration(self) -> float:
        """会话持续时间（秒）"""
        return time.time() - self.created_at

    @property
    def is_active(self) -> bool:
        """会话是否活跃"""
        return not self.closed and self.state != SessionState.CLOSED

    def transition_to(self, new_state: SessionState) -> None:
        """状态转换"""
        if self._is_valid_transition(new_state):
            old_state = self.state
            self.state = new_state
        else:
            raise ValueError(
                f"Invalid state transition from {self.state.value} to {new_state.value}"
            )

    def _is_valid_transition(self, new_state: SessionState) -> bool:
        """验证状态转换是否合法"""
        valid_transitions = {
            SessionState.IDLE: {SessionState.ASR},
            SessionState.ASR: {SessionState.LLM, SessionState.IDLE, SessionState.INTERRUPTED},
            SessionState.LLM: {SessionState.TTS, SessionState.INTERRUPTED},
            SessionState.TTS: {SessionState.ASR, SessionState.IDLE, SessionState.INTERRUPTED},
            SessionState.INTERRUPTED: {SessionState.ASR, SessionState.IDLE, SessionState.CLOSED},
            SessionState.CLOSED: set(),
        }
        return new_state in valid_transitions.get(self.state, set())

    def close(self) -> None:
        """关闭会话"""
        self.closed = True
        self.state = SessionState.CLOSED


class SessionError(Exception):
    pass


@dataclass
class Device:
    """设备实体"""
    device_id: str
    device_key: str = ""
    name: str = ""
    mac_address: str = ""
    api_key: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    is_online: bool = False
    last_seen: Optional[float] = None
    created_at: float = field(default_factory=time.time)

    @property
    def is_authenticated(self) -> bool:
        """设备是否已认证"""
        return bool(self.api_key)

    def update_last_seen(self) -> None:
        """更新最后活跃时间"""
        self.last_seen = time.time()
        self.is_online = True

    def go_offline(self) -> None:
        """设备离线"""
        self.is_online = False


@dataclass
class MemoryItem:
    """长期记忆条目实体

    每条记忆是一个归一化的耐久事实，通过 tags（摘要标签）和 keywords（关键词）检索。
    设计参考 ESP-Claw 的 claw_memory_item_t，适配服务端 Python 场景。
    """
    memory_id: str = ""                    # "mem-{timestamp}-{seq}"
    device_id: str = ""                    # 所属设备
    content: str = ""                      # 归一化记忆事实（核心）
    tags: list[str] = field(default_factory=list)      # 摘要标签（→ 构建 summary catalog）
    keywords: list[str] = field(default_factory=list)  # 关键词（→ keyword index）
    source: str = "manual"                # "manual" / "auto_llm"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    access_count: int = 0                 # 访问计数 → 排序优先级
    deleted: bool = False                 # 软删除标记

    def to_dict(self) -> dict:
        """转为可序列化的字典"""
        return {
            "memory_id": self.memory_id,
            "device_id": self.device_id,
            "content": self.content,
            "tags": self.tags,
            "keywords": self.keywords,
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "access_count": self.access_count,
            "deleted": self.deleted,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryItem":
        return cls(
            memory_id=data.get("memory_id", ""),
            device_id=data.get("device_id", ""),
            content=data.get("content", ""),
            tags=data.get("tags", []),
            keywords=data.get("keywords", []),
            source=data.get("source", "manual"),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            access_count=data.get("access_count", 0),
            deleted=data.get("deleted", False),
        )

    @property
    def summary_labels(self) -> list[str]:
        """取 tags 前 3 个作为摘要标签"""
        return self.tags[:3]


__all__ = [
    "SessionState",
    "Message",
    "Conversation",
    "ToolCall",
    "AudioChunk",
    "Session",
    "SessionError",
    "Device",
    "MemoryItem",
]
