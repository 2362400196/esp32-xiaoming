"""
AI自我成长系统 - 数据模型
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class UserProfile:
    """用户画像"""
    device_id: str
    name: str = ""
    birthday: str = ""
    occupation: str = ""
    family: list = field(default_factory=list)
    personality: dict = field(default_factory=dict)
    interests: dict = field(default_factory=dict)
    habits: dict = field(default_factory=dict)
    important_dates: list = field(default_factory=list)
    current_state: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "name": self.name,
            "birthday": self.birthday,
            "occupation": self.occupation,
            "family": self.family,
            "personality": self.personality,
            "interests": self.interests,
            "habits": self.habits,
            "important_dates": self.important_dates,
            "current_state": self.current_state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> UserProfile:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class EmotionRecord:
    """情绪记录"""
    timestamp: float
    emotion: str
    intensity: float
    trigger: str
    context: str
    speaker: str = "user"

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "emotion": self.emotion,
            "intensity": self.intensity,
            "trigger": self.trigger,
            "context": self.context,
            "speaker": self.speaker,
        }

    @classmethod
    def from_dict(cls, data: dict) -> EmotionRecord:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class DiaryEntry:
    """日记条目"""
    date: str
    content: str
    user_emotion_summary: str = ""
    ai_feeling: str = ""
    highlights: list = field(default_factory=list)
    learned_about_user: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "content": self.content,
            "user_emotion_summary": self.user_emotion_summary,
            "ai_feeling": self.ai_feeling,
            "highlights": self.highlights,
            "learned_about_user": self.learned_about_user,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DiaryEntry:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class SkillCandidate:
    """候选skill"""
    title: str
    content: str
    category: str
    tags: list = field(default_factory=list)
    source: str = "conversation"
    confidence: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "content": self.content,
            "category": self.category,
            "tags": self.tags,
            "source": self.source,
            "confidence": self.confidence,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SkillCandidate:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ConversationAnalysis:
    """对话分析结果"""
    user_info: dict = field(default_factory=dict)
    emotion: dict = field(default_factory=dict)
    memories: list = field(default_factory=list)
    skill_candidate: Optional[SkillCandidate] = None
    ai_feeling: str = ""
    highlights: list = field(default_factory=list)
    conversation_summary: str = ""

    def to_dict(self) -> dict:
        return {
            "user_info": self.user_info,
            "emotion": self.emotion,
            "memories": self.memories,
            "skill_candidate": self.skill_candidate.to_dict() if self.skill_candidate else None,
            "ai_feeling": self.ai_feeling,
            "highlights": self.highlights,
            "conversation_summary": self.conversation_summary,
        }
