"""成长系统仓储（SQL 实现，阶段 2：仓储层）

替代以下 JSON 文件读写：
- ``user_profile.json`` → ``UserProfileRepository``（UPSERT 语义）
- ``emotion_history.json`` → ``EmotionHistoryRepository``（Append-only + trim 100）
- ``learning_log.json`` → ``LearningLogRepository``（Append-only + trim 100）

返回的 dict 结构与原 JSON 格式（``UserProfile.to_dict()`` / ``EmotionRecord.to_dict()``
/ 自学习日志条目）完全一致，保持向后兼容。

替代项：
- ``src/use_cases/growth/user_profile.py`` 中的 JSON 读写
- ``src/use_cases/growth/emotion_analyzer.py`` 中的 JSON 读写
- ``src/use_cases/growth/self_learning.py`` 中的 ``_log_learning`` 方法
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from src.infrastructure.db.models.growth import (
    AlarmModel,
    DiaryModel,
    EmotionHistoryModel,
    LearningLogModel,
    UserProfileModel,
)
from src.infrastructure.db.session import get_session_ctx
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


# ============================================================
# 辅助函数
# ============================================================

def _now_ts() -> float:
    """当前 UTC 时间戳（秒）"""
    return datetime.now(timezone.utc).timestamp()


# UserProfile dict 中可映射到模型列的字段名（排除 device_id 主键）
_PROFILE_FIELDS: set[str] = {
    "name", "birthday", "occupation",
    "family", "personality", "interests", "habits",
    "important_dates", "current_state",
}


def _empty_profile(device_id: str) -> dict:
    """构造空 profile dict（设备不存在时的默认返回）。

    结构与 ``UserProfile.to_dict()`` 一致，``created_at`` / ``updated_at`` 为 0.0。
    """
    return {
        "device_id": device_id,
        "name": "",
        "birthday": "",
        "occupation": "",
        "family": [],
        "personality": {},
        "interests": {},
        "habits": {},
        "important_dates": [],
        "current_state": {},
        "created_at": 0.0,
        "updated_at": 0.0,
    }


def _model_to_profile_dict(model: UserProfileModel) -> dict:
    """将 UserProfileModel 转换为 profile dict。

    结构与 ``UserProfile.to_dict()`` 一致。
    """
    return {
        "device_id": model.device_id,
        "name": model.name or "",
        "birthday": model.birthday or "",
        "occupation": model.occupation or "",
        "family": list(model.family or []),
        "personality": dict(model.personality or {}),
        "interests": dict(model.interests or {}),
        "habits": dict(model.habits or {}),
        "important_dates": list(model.important_dates or []),
        "current_state": dict(model.current_state or {}),
        "created_at": model.created_at,
        "updated_at": model.updated_at,
    }


def _profile_to_fields(profile: dict) -> dict:
    """将 profile dict 转换为模型字段字典（不含 device_id 主键）。"""
    return {
        "name": profile.get("name", "") or "",
        "birthday": profile.get("birthday", "") or "",
        "occupation": profile.get("occupation", "") or "",
        "family": profile.get("family") or [],
        "personality": profile.get("personality") or {},
        "interests": profile.get("interests") or {},
        "habits": profile.get("habits") or {},
        "important_dates": profile.get("important_dates") or [],
        "current_state": profile.get("current_state") or {},
    }


def _emotion_model_to_dict(model: EmotionHistoryModel) -> dict:
    """将 EmotionHistoryModel 转换为情绪记录 dict。

    结构与 ``EmotionRecord.to_dict()`` 一致。
    """
    return {
        "timestamp": model.timestamp,
        "emotion": model.emotion,
        "intensity": model.intensity,
        "trigger": model.trigger or "",
        "context": model.context or "",
        "speaker": model.speaker or "user",
    }


def _learning_model_to_dict(model: LearningLogModel) -> dict:
    """将 LearningLogModel 转换为学习日志条目 dict。

    结构与 ``SelfLearningService._log_learning`` 写入的条目一致。
    """
    return {
        "timestamp": model.timestamp,
        "action": model.action,
        "skill_name": model.skill_name or "",
        "title": model.title or "",
        "category": model.category or "",
    }


# ============================================================
# UserProfileRepository
# ============================================================

class UserProfileRepository:
    """用户画像仓储（异步）

    替代 ``user_profile.json`` 的读写。一设备一行，UPSERT 语义。
    嵌套对象（family、personality、interests 等）存 JSON 列。

    返回的 dict 结构与 ``UserProfile.to_dict()`` 一致。
    """

    async def get(self, device_id: str) -> dict:
        """获取用户画像。

        设备不存在时返回空 profile dict（所有字段为默认值），
        而非 None，方便调用方直接使用。
        """
        if not device_id:
            return _empty_profile("")
        async with get_session_ctx() as session:
            result = await session.execute(
                select(UserProfileModel).where(
                    UserProfileModel.device_id == device_id
                )
            )
            model = result.scalar_one_or_none()
            if model is None:
                return _empty_profile(device_id)
            return _model_to_profile_dict(model)

    async def upsert(self, device_id: str, profile: dict) -> None:
        """插入或更新用户画像（SQLite ``INSERT ... ON CONFLICT DO UPDATE``）。

        - 新设备：插入
        - 已存在设备：更新所有字段（``created_at`` 保留，``updated_at`` 刷新）
        """
        if not device_id:
            return
        fields = _profile_to_fields(profile or {})
        stmt = sqlite_insert(UserProfileModel).values(
            device_id=device_id, **fields
        )
        # ON CONFLICT DO UPDATE：更新所有非主键字段，并刷新 updated_at
        update_cols = {k: getattr(stmt.excluded, k) for k in fields.keys()}
        update_cols["updated_at"] = _now_ts()
        stmt = stmt.on_conflict_do_update(
            index_elements=["device_id"],
            set_=update_cols,
        )
        async with get_session_ctx() as session:
            await session.execute(stmt)

    async def update_partial(self, device_id: str, updates: dict) -> None:
        """部分更新用户画像（仅更新 ``updates`` 中提供的字段）。

        - 嵌套 JSON 字段（personality、interests 等）直接整体替换
        - 设备不存在时无操作（不创建新行）
        """
        if not device_id or not updates:
            return
        async with get_session_ctx() as session:
            result = await session.execute(
                select(UserProfileModel).where(
                    UserProfileModel.device_id == device_id
                )
            )
            model = result.scalar_one_or_none()
            if model is None:
                return
            for key, value in updates.items():
                if key in _PROFILE_FIELDS:
                    setattr(model, key, value)
            model.updated_at = _now_ts()
            await session.flush()


# ============================================================
# EmotionHistoryRepository
# ============================================================

class EmotionHistoryRepository:
    """情绪历史仓储（异步）

    替代 ``emotion_history.json`` 的读写。Append-only，插入后修剪到最近 100 条。

    返回的 dict 结构与 ``EmotionRecord.to_dict()`` 一致：
    ``{timestamp, emotion, intensity, trigger, context, speaker}``
    """

    _MAX_RECORDS = 100

    async def append(self, device_id: str, record: dict) -> None:
        """追加一条情绪记录，并修剪到最近 100 条。

        ``record`` 结构：``{timestamp, emotion, intensity, trigger, context, speaker}``
        """
        if not device_id or not record:
            return
        async with get_session_ctx() as session:
            session.add(EmotionHistoryModel(
                device_id=device_id,
                timestamp=float(record.get("timestamp", 0.0) or 0.0),
                emotion=record.get("emotion", "neutral") or "neutral",
                intensity=float(record.get("intensity", 0.0) or 0.0),
                trigger=(record.get("trigger", "") or "")[:512],
                context=(record.get("context", "") or "")[:256],
                speaker=record.get("speaker", "user") or "user",
            ))
            await session.flush()
            await self._trim(session, device_id)

    async def list_all(self, device_id: str) -> list[dict]:
        """获取设备的全部情绪记录，按时间升序排列。"""
        if not device_id:
            return []
        async with get_session_ctx() as session:
            result = await session.execute(
                select(EmotionHistoryModel)
                .where(EmotionHistoryModel.device_id == device_id)
                .order_by(
                    EmotionHistoryModel.timestamp.asc(),
                    EmotionHistoryModel.id.asc(),
                )
            )
            return [_emotion_model_to_dict(m) for m in result.scalars().all()]

    async def list_since(self, device_id: str, since_timestamp: float) -> list[dict]:
        """获取设备自 ``since_timestamp``（含）以来的情绪记录，按时间升序。"""
        if not device_id:
            return []
        async with get_session_ctx() as session:
            result = await session.execute(
                select(EmotionHistoryModel)
                .where(
                    EmotionHistoryModel.device_id == device_id,
                    EmotionHistoryModel.timestamp >= float(since_timestamp),
                )
                .order_by(
                    EmotionHistoryModel.timestamp.asc(),
                    EmotionHistoryModel.id.asc(),
                )
            )
            return [_emotion_model_to_dict(m) for m in result.scalars().all()]

    async def _trim(self, session, device_id: str) -> None:
        """修剪设备情绪记录到最近 ``_MAX_RECORDS`` 条（按时间倒序保留）。"""
        # 选取需要保留的 100 条（时间最新）
        subq = (
            select(EmotionHistoryModel.id)
            .where(EmotionHistoryModel.device_id == device_id)
            .order_by(
                EmotionHistoryModel.timestamp.desc(),
                EmotionHistoryModel.id.desc(),
            )
            .limit(self._MAX_RECORDS)
        )
        await session.execute(
            delete(EmotionHistoryModel).where(
                EmotionHistoryModel.device_id == device_id,
                EmotionHistoryModel.id.not_in(subq),
            )
        )


# ============================================================
# LearningLogRepository
# ============================================================

class LearningLogRepository:
    """自学习日志仓储（异步）

    替代 ``learning_log.json`` 的读写。Append-only，插入后修剪到最近 100 条。

    返回的 dict 结构与 ``SelfLearningService._log_learning`` 写入的条目一致：
    ``{timestamp, action, skill_name, title, category}``
    """

    _MAX_RECORDS = 100

    async def append(self, device_id: str, entry: dict) -> None:
        """追加一条学习日志，并修剪到最近 100 条。

        ``entry`` 结构：``{timestamp, action, skill_name, title, category}``
        """
        if not device_id or not entry:
            return
        async with get_session_ctx() as session:
            session.add(LearningLogModel(
                device_id=device_id,
                timestamp=float(entry.get("timestamp", 0.0) or 0.0),
                action=entry.get("action", "") or "",
                skill_name=(entry.get("skill_name", "") or "")[:128],
                title=(entry.get("title", "") or "")[:256],
                category=(entry.get("category", "") or "")[:128],
            ))
            await session.flush()
            await self._trim(session, device_id)

    async def list_all(self, device_id: str) -> list[dict]:
        """获取设备的全部学习日志，按时间升序排列。"""
        if not device_id:
            return []
        async with get_session_ctx() as session:
            result = await session.execute(
                select(LearningLogModel)
                .where(LearningLogModel.device_id == device_id)
                .order_by(
                    LearningLogModel.timestamp.asc(),
                    LearningLogModel.id.asc(),
                )
            )
            return [_learning_model_to_dict(m) for m in result.scalars().all()]

    async def _trim(self, session, device_id: str) -> None:
        """修剪设备学习日志到最近 ``_MAX_RECORDS`` 条（按时间倒序保留）。"""
        subq = (
            select(LearningLogModel.id)
            .where(LearningLogModel.device_id == device_id)
            .order_by(
                LearningLogModel.timestamp.desc(),
                LearningLogModel.id.desc(),
            )
            .limit(self._MAX_RECORDS)
        )
        await session.execute(
            delete(LearningLogModel).where(
                LearningLogModel.device_id == device_id,
                LearningLogModel.id.not_in(subq),
            )
        )


__all__ = [
    "UserProfileRepository",
    "EmotionHistoryRepository",
    "LearningLogRepository",
    "AlarmRepository",
    "DiaryRepository",
]


class AlarmRepository:
    """闹钟仓储（异步）"""

    async def list_by_device(self, device_key: str) -> list[dict]:
        """列出指定设备的所有闹钟"""
        if not device_key:
            return []
        async with get_session_ctx() as session:
            result = await session.execute(
                select(AlarmModel).where(AlarmModel.device_key == device_key)
            )
            return [_alarm_to_dict(m) for m in result.scalars().all()]

    async def list_all(self) -> list[dict]:
        """列出所有闹钟"""
        async with get_session_ctx() as session:
            result = await session.execute(select(AlarmModel))
            return [_alarm_to_dict(m) for m in result.scalars().all()]

    async def upsert(self, item: dict) -> None:
        """插入或更新闹钟"""
        stmt = sqlite_insert(AlarmModel).values(
            alarm_id=item["alarm_id"],
            device_key=item["device_key"],
            alarm_type=item["alarm_type"],
            trigger_at=item["trigger_at"],
            text=item.get("text", ""),
            repeat=item.get("repeat", "once"),
            created_at=item.get("created_at", _now_ts()),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["alarm_id"],
            set_={
                "trigger_at": stmt.excluded.trigger_at,
                "text": stmt.excluded.text,
                "repeat": stmt.excluded.repeat,
            },
        )
        async with get_session_ctx() as session:
            await session.execute(stmt)

    async def delete(self, alarm_id: str) -> None:
        """删除闹钟"""
        async with get_session_ctx() as session:
            await session.execute(
                delete(AlarmModel).where(AlarmModel.alarm_id == alarm_id)
            )


def _alarm_to_dict(model: AlarmModel) -> dict:
    return {
        "alarm_id": model.alarm_id,
        "device_key": model.device_key,
        "alarm_type": model.alarm_type,
        "trigger_at": model.trigger_at,
        "text": model.text,
        "repeat": model.repeat,
        "created_at": model.created_at,
    }


class DiaryRepository:
    """日记仓储（异步）"""

    async def get_entry(self, device_key: str, date: str) -> Optional[str]:
        """获取指定日期的日记内容"""
        async with get_session_ctx() as session:
            result = await session.execute(
                select(DiaryModel).where(
                    DiaryModel.device_key == device_key,
                    DiaryModel.date == date,
                )
            )
            model = result.scalar_one_or_none()
            return model.content if model else None

    async def upsert_entry(self, device_key: str, date: str, content: str, append: bool = False) -> None:
        """插入或追加日记"""
        async with get_session_ctx() as session:
            result = await session.execute(
                select(DiaryModel).where(
                    DiaryModel.device_key == device_key,
                    DiaryModel.date == date,
                )
            )
            model = result.scalar_one_or_none()
            if model:
                if append:
                    model.content += f"\n\n---\n\n{content}"
                else:
                    model.content = content
                model.created_at = _now_ts()
            else:
                session.add(DiaryModel(
                    device_key=device_key,
                    date=date,
                    content=content,
                ))
            await session.flush()

    async def get_recent(self, device_key: str, limit: int = 7) -> list[dict]:
        """获取最近的日记条目"""
        async with get_session_ctx() as session:
            result = await session.execute(
                select(DiaryModel)
                .where(DiaryModel.device_key == device_key)
                .order_by(DiaryModel.date.desc())
                .limit(limit)
            )
            return [
                {"date": m.date, "content": m.content}
                for m in result.scalars().all()
            ]

    async def search(self, device_key: str, keyword: str) -> list[dict]:
        """搜索包含关键词的日记（全文搜索，支持 SQLite LIKE）"""
        async with get_session_ctx() as session:
            result = await session.execute(
                select(DiaryModel)
                .where(
                    DiaryModel.device_key == device_key,
                    DiaryModel.content.like(f"%{keyword}%"),
                )
                .order_by(DiaryModel.date.desc())
            )
            return [
                {"date": m.date, "content": m.content[:500]}
                for m in result.scalars().all()
            ]

    async def delete_device(self, device_key: str) -> None:
        """删除设备的所有日记"""
        async with get_session_ctx() as session:
            await session.execute(
                delete(DiaryModel).where(DiaryModel.device_key == device_key)
            )
