"""表情包元数据仓储（SQL 实现，阶段 2：仓储层）

替代 ``emos/packs/{pack}/meta.json`` 的读写。GIF 文件仍存磁盘，DB 只存元数据。

设备激活表情包的读写通过 ``devices`` 表的 ``active_emo_pack`` 列实现，
替代 ``emos/devices/{device_id}/active_pack`` 文本文件。

替代项：
- ``src/infrastructure/emo_pack.py`` 中的 ``list_packs`` / ``create_pack`` /
  ``delete_pack`` / ``get_active_pack`` / ``set_active_pack`` 的元数据部分
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, select, update, or_
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from src.infrastructure.db.models.device import DeviceModel
from src.infrastructure.db.models.emo import EmoPackModel
from src.infrastructure.db.session import get_session_ctx
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)

# 设备未设置激活表情包时的默认值
_DEFAULT_PACK = "default"


# ============================================================
# 辅助函数
# ============================================================

def _now_ts() -> float:
    """当前 UTC 时间戳（秒）"""
    return datetime.now(timezone.utc).timestamp()


def _model_to_pack_dict(model: EmoPackModel) -> dict:
    """将 EmoPackModel 转换为表情包元数据 dict。"""
    return {
        "name": model.pack_name,
        "display_name": model.display_name or model.pack_name,
    }


# ============================================================
# EmoPackRepository
# ============================================================

class EmoPackRepository:
    """表情包元数据仓储（异步）

    替代 ``emos/packs/{pack}/meta.json`` 的读写。GIF 文件仍存磁盘。

    - ``list_packs`` / ``get_pack_meta`` / ``upsert_pack`` / ``delete_pack``：
      操作 ``emo_packs`` 表
    - ``get_active_pack`` / ``set_active_pack``：操作 ``devices`` 表的
      ``active_emo_pack`` 列
    """

    async def list_packs(self) -> list[dict]:
        """列出所有表情包元数据。

        返回 ``[{"name": str, "display_name": str}]``，按 ``pack_name`` 升序。
        """
        async with get_session_ctx() as session:
            result = await session.execute(
                select(EmoPackModel).order_by(EmoPackModel.pack_name.asc())
            )
            return [_model_to_pack_dict(m) for m in result.scalars().all()]

    async def get_pack_meta(self, pack_name: str) -> Optional[dict]:
        """获取单个表情包元数据。

        返回 ``{"name": str, "display_name": str}``，不存在返回 None。
        """
        if not pack_name:
            return None
        async with get_session_ctx() as session:
            result = await session.execute(
                select(EmoPackModel).where(EmoPackModel.pack_name == pack_name)
            )
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return _model_to_pack_dict(model)

    async def upsert_pack(self, pack_name: str, display_name: str) -> None:
        """插入或更新表情包元数据（SQLite ``INSERT ... ON CONFLICT DO UPDATE``）。

        - 新表情包：插入
        - 已存在：更新 ``display_name``，刷新 ``updated_at``
        """
        if not pack_name:
            return
        display_name = display_name or pack_name
        stmt = sqlite_insert(EmoPackModel).values(
            pack_name=pack_name,
            display_name=display_name,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["pack_name"],
            set_={
                "display_name": stmt.excluded.display_name,
                "updated_at": _now_ts(),
            },
        )
        async with get_session_ctx() as session:
            await session.execute(stmt)

    async def delete_pack(self, pack_name: str) -> bool:
        """删除表情包元数据。

        返回 True 表示存在并已删除，False 表示不存在。
        注意：不删除 default 表情包（由调用方保证，此处仅操作 DB）。
        """
        if not pack_name:
            return False
        async with get_session_ctx() as session:
            result = await session.execute(
                delete(EmoPackModel).where(EmoPackModel.pack_name == pack_name)
            )
            return (result.rowcount or 0) > 0

    async def get_active_pack(self, device_id: str) -> str:
        """获取设备当前激活的表情包目录名。

        从 ``devices`` 表的 ``active_emo_pack`` 列读取。
        支持 device_id / mac_address / device_key 多字段查找。
        设备不存在或未设置时返回 ``"default"``。
        """
        if not device_id:
            return _DEFAULT_PACK
        async with get_session_ctx() as session:
            result = await session.execute(
                select(DeviceModel.active_emo_pack).where(
                    or_(
                        DeviceModel.device_id == device_id,
                        DeviceModel.mac_address == device_id,
                        DeviceModel.device_key == device_id,
                    )
                )
            )
            value = result.scalar_one_or_none()
            if value is None:
                return _DEFAULT_PACK
            return value or _DEFAULT_PACK

    async def set_active_pack(self, device_id: str, pack_name: str) -> None:
        """设置设备激活的表情包。

        更新 ``devices`` 表的 ``active_emo_pack`` 列。
        支持 device_id / mac_address / device_key 多字段查找。
        设备不存在时无操作（不会创建新设备行）。
        """
        if not device_id or not pack_name:
            return
        async with get_session_ctx() as session:
            await session.execute(
                update(DeviceModel)
                .where(
                    or_(
                        DeviceModel.device_id == device_id,
                        DeviceModel.mac_address == device_id,
                        DeviceModel.device_key == device_id,
                    )
                )
                .values(
                    active_emo_pack=pack_name,
                    updated_at=_now_ts(),
                )
            )


__all__ = ["EmoPackRepository"]
