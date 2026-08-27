"""
用户画像服务 - 记录和管理用户的点点滴滴

阶段 3：业务层从 JSON 文件存储切换到数据库仓储。
- ``_profiles`` 内存字典保留为一级缓存
- ``UserProfileRepository`` 作为持久层（替代 ``user_profile.json``）
- DB 操作失败时记录日志，不中断业务流程
"""
from __future__ import annotations

import os
import re
import time
from typing import Optional

from src.infrastructure.db.repositories.growth_repositories import UserProfileRepository
from src.infrastructure.logging import get_logger
from .models import UserProfile
from .similarity import text_similarity

logger = get_logger(__name__)

# 模块级仓储单例（延迟使用全局异步会话工厂，构造时不连接 DB）
_profile_repo = UserProfileRepository()

# 画像兴趣条目上限（超出部分不再展示，控制提示词体积）
PROFILE_INTEREST_LIMIT = 30
# 兴趣条目合并前相似度阈值（LLM 常用不同措辞重复同一事实，需语义去重）
PROFILE_SIMILARITY_THRESHOLD = 0.6


class UserProfileService:
    """用户画像服务"""

    def __init__(self, data_dir: str):
        self._data_dir = data_dir
        self._profiles: dict[str, UserProfile] = {}

    def _get_profile_path(self, device_id: str) -> str:
        # 保留用于向后兼容（旧迁移/外部引用）；DB 切换后不再读写该文件
        return os.path.join(self._data_dir, "devices", device_id, "profile", "user_profile.json")

    async def get_profile(self, device_id: str) -> UserProfile:
        """获取用户画像"""
        if device_id in self._profiles:
            return self._profiles[device_id]

        # 从 DB 加载（持久层）
        profile: Optional[UserProfile] = None
        try:
            data = await _profile_repo.get(device_id)
            if data:
                # 仓储对不存在设备返回空 profile dict（created_at=0.0），
                # 这里统一用 from_dict 构造，保留已有记录的时间戳
                profile = UserProfile.from_dict(data)
        except Exception as e:
            logger.warning(f"[UserProfile] DB 加载画像失败: {e}")

        if profile is None:
            profile = UserProfile(device_id=device_id)
        self._dedup_interests(profile)
        self._profiles[device_id] = profile
        return profile

    async def save_profile(self, device_id: str) -> None:
        """保存用户画像"""
        profile = self._profiles.get(device_id)
        if not profile:
            return

        try:
            await _profile_repo.upsert(device_id, profile.to_dict())
            logger.info(f"[UserProfile] 已保存画像: {device_id}")
        except Exception as e:
            # DB 写入失败不中断业务流程（内存缓存仍可用）
            logger.warning(f"[UserProfile] DB 保存画像失败: {e}")

    async def update_from_analysis(self, device_id: str, analysis: dict) -> UserProfile:
        """从对话分析结果更新用户画像"""
        profile = await self.get_profile(device_id)

        user_info = analysis.get("user_info", {})

        new_facts = user_info.get("new_facts", [])
        for fact in new_facts:
            if "名字" in fact or "叫" in fact:
                profile.name = self._extract_name(fact)
            elif "生日" in fact:
                profile.birthday = self._extract_date(fact)
            elif "工作" in fact or "职业" in fact:
                profile.occupation = self._extract_occupation(fact)
            elif "家人" in fact or "老婆" in fact or "老公" in fact:
                self._update_family(profile, fact)

        preferences = user_info.get("preferences", [])
        for pref in preferences:
            if "喜欢" in pref:
                self._update_interests(profile, pref, "likes")
            elif "不喜欢" in pref or "讨厌" in pref:
                self._update_interests(profile, pref, "dislikes")
            elif "学习" in pref or "正在学" in pref:
                self._update_interests(profile, pref, "learning")

        concerns = user_info.get("concerns", [])
        if concerns:
            profile.current_state["concerns"] = concerns

        emotion = analysis.get("emotion", {})
        if emotion:
            profile.current_state["last_emotion"] = emotion.get("current", "neutral")
            profile.current_state["last_emotion_trigger"] = emotion.get("trigger", "")

        profile.updated_at = time.time()
        await self.save_profile(device_id)

        return profile

    def _extract_name(self, fact: str) -> str:
        import re
        patterns = [
            r"我(?:的?名字|叫|是)(.+?)(?:，|。|$)",
            r"称(?:呼|为|我)(?:为|叫)?(.+?)(?:，|。|$)",
            r"(?:都|大家|朋友|他们)(?:叫|称|管)(?:我|你)(?:叫)?(.+?)(?:，|。|$)",
            r"叫我(.+?)(?:就好|吧|，|。|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, fact)
            if match:
                return match.group(1).strip()
        return ""

    def _extract_date(self, fact: str) -> str:
        import re
        match = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}月\d{1,2}[日号])", fact)
        return match.group(1) if match else ""

    def _extract_occupation(self, fact: str) -> str:
        import re
        patterns = [
            r"(?:是|做|当)(.+?)(?:工作|的|，|。|$)",
            r"(?:我的|我)?(?:职业|工作|行业)是(.+?)(?:，|。|$)",
            r"在(.+?)工作(?:，|。|$)",
            r"从事(.+?)(?:行业|工作)(?:，|。|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, fact)
            if match:
                return match.group(1).strip()
        return ""

    def _update_family(self, profile: UserProfile, fact: str) -> None:
        import re
        relations = ["老婆", "老公", "妻子", "丈夫", "孩子", "儿子", "女儿", "爸爸", "妈妈", "父母"]
        for rel in relations:
            if rel in fact:
                match = re.search(f"{rel}(?:叫|是)(.+?)(?:，|。|$)", fact)
                name = match.group(1).strip() if match else ""
                existing = [f for f in profile.family if rel not in f]
                existing.append(f"{rel}:{name}" if name else rel)
                profile.family = existing
                break

    def _update_interests(self, profile: UserProfile, pref: str, category: str) -> None:
        if category not in profile.interests:
            profile.interests[category] = []

        if category == "likes":
            match = re.search(r"喜欢(.+?)(?:，|。|$)", pref)
        elif category == "dislikes":
            match = re.search(r"(?:不喜欢|讨厌)(.+?)(?:，|。|$)", pref)
        else:
            match = re.search(r"(?:学习|正在学|在学)(.+?)(?:，|。|$)", pref)

        if match:
            item = match.group(1).strip()
            if item and not self._is_duplicate_interest(profile.interests[category], item):
                profile.interests[category].append(item)

    def _is_duplicate_interest(self, items: list, item: str) -> bool:
        """判断新偏好是否与已有条目重复（子串命中或相似度过高）"""
        norm = re.sub(r"\s+", "", item)
        for existing in items:
            norm_existing = re.sub(r"\s+", "", existing)
            if norm and (norm in norm_existing or norm_existing in norm):
                return True
            if text_similarity(existing, item) >= PROFILE_SIMILARITY_THRESHOLD:
                return True
        return False

    def _dedup_interests(self, profile: UserProfile) -> None:
        """清理画像中语义重复的兴趣条目（含历史数据）"""
        for category in list(profile.interests.keys()):
            deduped = []
            for item in profile.interests[category]:
                if not item:
                    continue
                if not self._is_duplicate_interest(deduped, item):
                    deduped.append(item)
            profile.interests[category] = deduped

    async def get_profile_summary(self, device_id: str) -> str:
        """获取用户画像摘要（给LLM用）"""
        profile = await self.get_profile(device_id)

        parts = []
        if profile.name:
            parts.append(f"名字：{profile.name}")
        if profile.occupation:
            parts.append(f"职业：{profile.occupation}")
        if profile.family:
            parts.append(f"家人：{', '.join(profile.family)}")
        if profile.interests.get("likes"):
            parts.append(f"喜欢：{', '.join(profile.interests['likes'][:PROFILE_INTEREST_LIMIT])}")
        if profile.interests.get("dislikes"):
            parts.append(f"不喜欢：{', '.join(profile.interests['dislikes'][:PROFILE_INTEREST_LIMIT])}")
        if profile.interests.get("learning"):
            parts.append(f"正在学习：{', '.join(profile.interests['learning'][:PROFILE_INTEREST_LIMIT])}")
        if profile.current_state.get("concerns"):
            parts.append(f"最近关心：{', '.join(profile.current_state['concerns'])}")
        if profile.current_state.get("last_emotion"):
            parts.append(f"最近情绪：{profile.current_state['last_emotion']}")

        return "\n".join(parts) if parts else "暂无用户信息"
