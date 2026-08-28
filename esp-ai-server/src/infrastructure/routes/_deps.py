"""路由层公共依赖：设备归属校验与 device_key 解析。

历史背景：devices.py / plugins.py / skills.py / emos.py / growth.py 各持有
一份逐字复制的 ``_check_device_owner``；growth.py 与 alarm.py 各持有一份
``_resolve_device_key``。本模块收敛为单一实现。

语义统一说明（取各副本的并集）：
- ``check_device_owner``：管理员（role == "admin"）直接放行（原 alarm.py
  ``_check_device_access`` 的语义）；否则要求设备（按 device_id /
  mac_address / device_key 任一标识匹配）绑定到当前用户（其余四份副本的
  语义）。
- ``resolve_device_key``：通过同步 DB 会话把 device_id（MAC / device_id /
  device_key）解析为规范 device_key；查询失败时记录错误日志并返回空字符串
  （growth.py 与 alarm.py 副本行为一致，仅日志前缀不同，统一为一个前缀）。
"""
from __future__ import annotations

from sqlalchemy import or_, select

from src.infrastructure.db.models.device import DeviceModel
from src.infrastructure.db.session import get_session_ctx
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


async def check_device_owner(device_id: str, user) -> bool:
    """校验请求者可访问该设备：必须是设备绑定用户或管理员。

    兼容 device_id / mac_address / device_key 三种标识查找。
    """
    if getattr(user, "role", None) == "admin":
        return True
    async with get_session_ctx() as session:
        result = await session.execute(
            select(DeviceModel).where(
                or_(
                    DeviceModel.device_id == device_id,
                    DeviceModel.mac_address == device_id,
                    DeviceModel.device_key == device_id,
                ),
                DeviceModel.user_id == user.id,
            )
        )
        return result.scalar_one_or_none() is not None


def resolve_device_key(device_id: str) -> str:
    """根据 device_id（MAC 或 key）从 DB 解析出规范 device_key。

    通过同步会话查询 DeviceModel；DB 查询失败时记录错误日志并返回空字符串。
    """
    try:
        from src.infrastructure.db.compat.sync_session import get_sync_session

        with get_sync_session() as session:
            result = session.execute(
                select(DeviceModel).where(
                    or_(
                        DeviceModel.device_id == device_id,
                        DeviceModel.device_key == device_id,
                        DeviceModel.mac_address == device_id,
                    )
                )
            )
            model = result.scalars().first()
            if model is not None and model.device_key:
                return model.device_key
    except Exception as e:
        logger.error(f"[Routes] DB 解析 device_key 失败: {e}")

    return ""
