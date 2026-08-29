"""
AI自我成长系统

模块组成：
- user_profile: 用户画像
- emotion_analyzer: 情绪分析
- diary_service: 日记服务
- self_learning: 自学习skill生成
- growth_system: 核心协调器
"""

from .growth_system import GrowthSystem
from .diary_service import DiaryService
from .emotion_analyzer import EmotionAnalyzer
from .user_profile import UserProfileService
from .self_learning import SelfLearningService

__all__ = [
    "GrowthSystem",
    "DiaryService",
    "EmotionAnalyzer",
    "UserProfileService",
    "SelfLearningService",
]
