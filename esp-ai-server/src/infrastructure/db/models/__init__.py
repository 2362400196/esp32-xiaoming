"""ORM 模型导出

导入所有模型，使 ``Base.metadata.create_all()`` 能发现全部表。
"""
from src.infrastructure.db.models.user import UserModel
from src.infrastructure.db.models.device import DeviceModel
from src.infrastructure.db.models.memory import (
    LongTermMemoryKeywordIndexModel,
    LongTermMemoryRecordModel,
    LongTermMemorySummaryLabelModel,
    ShortTermMemoryModel,
)
from src.infrastructure.db.models.growth import (
    AlarmModel,
    DiaryModel,
    EmotionHistoryModel,
    LearningLogModel,
    UserProfileModel,
)
from src.infrastructure.db.models.emo import EmoPackModel
from src.infrastructure.db.models.skill import SkillModel
from src.infrastructure.db.models.site_setting import SiteSettingModel
from src.infrastructure.db.models.billing import BillingConfigModel, BillingRecordModel
from src.infrastructure.db.models.marketplace import (
    MarketplacePluginModel,
    PluginReviewModel,
    PluginVersionModel,
    MarketplaceSkillModel,
)

__all__ = [
    "UserModel",
    "DeviceModel",
    "ShortTermMemoryModel",
    "LongTermMemoryRecordModel",
    "LongTermMemorySummaryLabelModel",
    "LongTermMemoryKeywordIndexModel",
    "AlarmModel",
    "DiaryModel",
    "UserProfileModel",
    "EmotionHistoryModel",
    "LearningLogModel",
    "EmoPackModel",
    "SkillModel",
    "SiteSettingModel",
    "BillingConfigModel",
    "BillingRecordModel",
    "MarketplacePluginModel",
    "PluginVersionModel",
    "PluginReviewModel",
    "MarketplaceSkillModel",
]
