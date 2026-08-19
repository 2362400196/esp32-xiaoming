"""Security - REST API 认证中间件

提供 FastAPI 依赖项，用于保护 REST API 路由免受未授权访问。

认证策略（WS 密钥与管理 API 密钥严格分离）：
- 设备 WebSocket 鉴权使用 AUTH_API_KEY（或 devices 表中每设备独立 key 字段）
- 管理 REST API 鉴权**仅**接受 ADMIN_API_KEY 或每设备独立 api_key 字段
- 每设备 api_key 与 WS key 是两个不同的字段，互不通用
- 若 auth.enabled 为 False 或未配置任何管理密钥：记录 WARNING 日志后放行

支持的认证方式：
- X-API-Key 请求头
- Authorization: Bearer <key> 请求头
"""
from __future__ import annotations

from typing import Optional

from fastapi import Header, HTTPException, status

from src.infrastructure.config import get_settings
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)

# 模块级标志：未启用认证时只记录一次 WARNING，避免日志刷屏
_auth_disabled_warned: bool = False


def _extract_api_key(x_api_key: Optional[str], authorization: Optional[str]) -> Optional[str]:
    """从请求头提取 API key，优先 X-API-Key，其次 Authorization: Bearer"""
    if x_api_key:
        return x_api_key
    if authorization:
        # 支持 "Bearer <token>" 格式
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        # 兼容直接传入 token 的情况
        return authorization.strip() or None
    return None


def _get_valid_keys() -> set[str]:
    """获取管理 REST API 的有效密钥集合

    WS 密钥（AUTH_API_KEY 或设备 key 字段）不可访问管理 API，
    两者严格分离。
    """
    settings = get_settings()
    auth = settings.auth
    valid_keys: set[str] = set()

    # 1. ADMIN_API_KEY（全局管理密钥）
    admin_key = getattr(auth, "admin_api_key", "") or ""
    if admin_key:
        valid_keys.add(admin_key)

    # 2. 每设备独立 management_api_key（从 DB 读取）
    #    与 WS 密钥 (device_key) 严格分离：
    #    - 管理 REST API 仅接受 ADMIN_API_KEY 或 management_api_key
    #    - WS WebSocket 连接仅接受 device_key (AUTH_API_KEY)
    try:
        from src.use_cases.device_config import load_devices
        dm = load_devices()
        if dm.has_users():
            for device_id, cfg in dm.devices.items():
                if cfg.api_key:
                    valid_keys.add(cfg.api_key)
    except Exception as e:
        logger.debug(f"加载设备 API 密钥失败（可能是启动早期）: {e}")

    return valid_keys


async def verify_admin_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None),
) -> bool:
    """REST API 认证依赖项

    从 X-API-Key 或 Authorization: Bearer 头读取 API key 进行验证。
    接受 ADMIN_API_KEY 或每设备独立 api_key（与 WS key 严格分离）。
    向后兼容：未启用认证或未配置任何密钥时记录 WARNING 但放行。

    Returns:
        True 表示认证通过

    Raises:
        HTTPException 401: 未提供 API key
        HTTPException 403: API key 无效
    """
    global _auth_disabled_warned

    settings = get_settings()
    auth = settings.auth
    auth_enabled = getattr(auth, "enabled", False)
    valid_keys = _get_valid_keys()

    # 向后兼容：未启用认证或未配置任何密钥时放行（仅记录一次 WARNING）
    if not auth_enabled or not valid_keys:
        if not _auth_disabled_warned:
            reason = "auth.enabled=False" if not auth_enabled else "未配置任何管理 API key"
            logger.warning(
                f"[Security] REST API 认证未启用（{reason}），"
                f"所有 REST API 处于无保护状态。建议配置 AUTH_ENABLED=true 和 ADMIN_API_KEY。"
            )
            _auth_disabled_warned = True
        return True

    provided_key = _extract_api_key(x_api_key, authorization)

    if not provided_key:
        logger.warning("[Security] 请求缺少 API key（X-API-Key 或 Authorization: Bearer）")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Provide X-API-Key or Authorization: Bearer header.",
        )

    if provided_key not in valid_keys:
        # 安全日志：不输出任何 key 内容，避免泄露
        logger.warning("[Security] 无效的 API key，认证失败")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )

    logger.debug("[Security] API key 认证通过")
    return True


def reset_auth_warned_flag() -> None:
    """重置模块级 WARNING 标志（供测试使用）"""
    global _auth_disabled_warned
    _auth_disabled_warned = False


__all__ = ["verify_admin_api_key", "reset_auth_warned_flag"]
