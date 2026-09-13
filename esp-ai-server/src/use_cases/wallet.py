"""
Wallet - 用户钱包

余额挂在用户（users.wallet_balance，元），设备通过绑定关系找到归属用户。
- 每轮对话结束按固定单次费用扣减（WALLET_COST_PER_ROUND，管理员可配置）
- 余额不足时拒绝对话并提示充值
- 管理员可手动调整余额（充值/扣减）
"""
from __future__ import annotations

import asyncio
from typing import Optional

from sqlalchemy import select, update

from src.infrastructure.db.models.device import DeviceModel
from src.infrastructure.db.models.user import UserModel
from src.infrastructure.db.session import get_session_ctx
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)

# 余额低于该值（元）视为不足，拒绝对话
WALLET_MIN_BALANCE = 0.0


async def _get_owner_id_by_device(device_id: str) -> Optional[str]:
    """设备 → 归属用户 ID（device_id / device_key / mac 任一匹配）"""
    if not device_id:
        return None
    async with get_session_ctx() as session:
        row = (await session.execute(
            select(DeviceModel.user_id).where(
                (DeviceModel.device_id == device_id)
                | (DeviceModel.device_key == device_id)
                | (DeviceModel.mac_address == device_id)
            )
        )).scalar_one_or_none()
    return row


async def get_user_balance(user_id: str) -> Optional[float]:
    async with get_session_ctx() as session:
        return (await session.get(UserModel, user_id)).wallet_balance if await session.get(UserModel, user_id) else None


async def get_device_balance(device_id: str) -> Optional[float]:
    """查询设备归属用户的余额（设备未绑定返回 None）"""
    owner = await _get_owner_id_by_device(device_id)
    if not owner:
        return None
    async with get_session_ctx() as session:
        user = await session.get(UserModel, owner)
        return user.wallet_balance if user else None


async def device_can_chat(device_id: str) -> bool:
    """该设备的归属用户余额是否足够发起一轮对话。

    - 设备未绑定用户 / 用户不存在 → 允许（不拦未绑定设备）
    - 钱包功能关闭 → 允许
    """
    from src.infrastructure.config import get_settings
    settings = get_settings()
    if not getattr(settings, "wallet_enabled", True):
        return True
    balance = await get_device_balance(device_id)
    if balance is None:
        return True
    return balance > WALLET_MIN_BALANCE


async def adjust_user_balance(user_id: str, delta: float, reason: str = "") -> Optional[float]:
    """调整用户余额（充值 delta>0 / 扣减 delta<0），返回调整后的余额。

    使用 SQL 原子自增，避免读-改-写竞态。用户不存在返回 None。
    """
    async with get_session_ctx() as session:
        user = await session.get(UserModel, user_id)
        if not user:
            return None
        new_balance = round(max(WALLET_MIN_BALANCE, user.wallet_balance + delta), 2)
        user.wallet_balance = new_balance
        session.add(user)
    logger.info(f"[Wallet] 用户 {user_id} 余额调整 {delta:+.2f} 元 -> {new_balance} 元"
                + (f"（{reason}）" if reason else ""))
    return new_balance


async def deduct_for_device(device_id: str, amount: float, reason: str = "") -> None:
    """按设备扣减归属用户余额（每轮对话结束调用）。

    设备未绑定 / 用户不存在 / 钱包关闭时静默跳过；扣费失败不阻断会话。
    """
    from src.infrastructure.config import get_settings
    settings = get_settings()
    if not getattr(settings, "wallet_enabled", True):
        return
    if amount <= 0:
        return
    owner = await _get_owner_id_by_device(device_id)
    if not owner:
        return
    try:
        async with get_session_ctx() as session:
            user = await session.get(UserModel, owner)
            if not user:
                return
            user.wallet_balance = round(max(WALLET_MIN_BALANCE, user.wallet_balance - amount), 2)
            session.add(user)
        logger.info(f"[Wallet] 设备 {device_id} 归属用户 {owner} 扣费 {amount:.2f} 元"
                    + (f"（{reason}）" if reason else ""))
    except Exception as e:
        logger.warning(f"[Wallet] 扣费失败（不影响会话）: {e}")


__all__ = [
    "get_user_balance",
    "get_device_balance",
    "device_can_chat",
    "adjust_user_balance",
    "deduct_for_device",
    "WALLET_MIN_BALANCE",
]
