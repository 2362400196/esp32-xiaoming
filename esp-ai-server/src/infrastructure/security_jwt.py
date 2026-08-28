"""Security - JWT 工具函数

提供密码哈希、JWT 创建/验证、当前用户获取等认证基础设施。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import pbkdf2_hmac
import hashlib
import hmac
import os
import secrets
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from src.infrastructure.config import get_settings
from src.infrastructure.db.session import get_session_ctx
from src.infrastructure.db.models.user import UserModel
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)

# 使用 PBKDF2-HMAC-SHA256 替代 passlib/bcrypt（避免版本兼容问题）
_PBKDF2_ITERATIONS = 600000
_PBKDF2_HASH_ALGO = "sha256"
_PBKDF2_SALT_LEN = 16
# 密码哈希格式: pbkdf2$iterations$salt_hex$hash_hex
_PBKDF2_PREFIX = "pbkdf2"

security_scheme = HTTPBearer(auto_error=False)

ALGORITHM = "HS256"


_TEMP_SECRET: Optional[str] = None


def _get_secret() -> str:
    """获取 JWT 签名密钥

    注意：fallback 临时密钥必须缓存（模块级变量），否则每次签发/校验都会生成
    不同的随机密钥，导致登录签发的 token 在下一个请求校验时直接 401。
    """
    global _TEMP_SECRET
    settings = get_settings()
    secret = settings.jwt_secret
    if not secret:
        # 开发环境 fallback：从 admin_api_key 派生专用 JWT 密钥。
        # 不能直接用 admin_api_key 本身——两个安全用途共用同一秘密，
        # 任一泄露即全线失守；SHA-256 派生后泄露 JWT 密钥不会暴露 admin_api_key。
        admin_key = settings.auth.admin_api_key
        if admin_key:
            secret = hashlib.sha256(f"espai-jwt:{admin_key}".encode("utf-8")).hexdigest()
        else:
            # 既未配置 jwt_secret 也未配置 admin_api_key：进程内缓存随机临时密钥
            # 避免硬编码 fallback 被攻击者利用伪造任意身份 token
            if _TEMP_SECRET is None:
                _TEMP_SECRET = secrets.token_hex(32)
                logger.warning(
                    "未配置 JWT_SECRET 或 ADMIN_API_KEY，已生成进程内临时 JWT 签名密钥。"
                    "请在环境变量中配置 JWT_SECRET 以保证重启后 token 依然有效且不被伪造。"
                )
            secret = _TEMP_SECRET
    return secret


def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 哈希密码（标准库实现，无外部依赖）"""
    salt = os.urandom(_PBKDF2_SALT_LEN)
    pwd_bytes = password.encode("utf-8")[:72]  # 截断到 72 字节（兼容 bcrypt 限制）
    dk = pbkdf2_hmac(_PBKDF2_HASH_ALGO, pwd_bytes, salt, _PBKDF2_ITERATIONS)
    return f"{_PBKDF2_PREFIX}${_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(plain: str, hashed: str) -> bool:
    """验证密码"""
    try:
        parts = hashed.split("$")
        if parts[0] == _PBKDF2_PREFIX:
            iterations = int(parts[1])
            salt = bytes.fromhex(parts[2])
            expected = parts[3]
            pwd_bytes = plain.encode("utf-8")[:72]
            dk = pbkdf2_hmac(_PBKDF2_HASH_ALGO, pwd_bytes, salt, iterations)
            return hmac.compare_digest(dk.hex(), expected)
        # 兼容旧格式（如果有）
        return False
    except Exception:
        return False


def create_access_token(user_id: str) -> str:
    """创建 access_token（有效期 24h）"""
    secret = _get_secret()
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=24),
        "type": "access",
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    """创建 refresh_token（有效期 30 天）"""
    secret = _get_secret()
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=30),
        "type": "refresh",
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """解码 JWT，过期或无效时抛出异常"""
    secret = _get_secret()
    return jwt.decode(token, secret, algorithms=[ALGORITHM])


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
) -> UserModel:
    """FastAPI 依赖项：从 Bearer Token 解析当前用户

    所有需要用户认证的路由注入此依赖：
        @router.get("/devices")
        async def list_devices(user: UserModel = Depends(get_current_user)):
            ...
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization: Bearer token",
        )

    try:
        payload = decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type, use access_token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    async with get_session_ctx() as session:
        result = await session.execute(select(UserModel).where(UserModel.id == user_id))
        user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User disabled")

    return user


async def require_admin(user: UserModel = Depends(get_current_user)) -> UserModel:
    """限制只有 admin 角色能访问"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
) -> UserModel | None:
    """可选的用户认证依赖：有 Token 返回用户，无 Token 返回 None。"""
    if not credentials:
        return None
    try:
        payload = decode_token(credentials.credentials)
    except Exception:
        return None
    if payload.get("type") != "access":
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    async with get_session_ctx() as session:
        result = await session.execute(select(UserModel).where(UserModel.id == user_id))
        user = result.scalar_one_or_none()
    if not user or not user.is_active:
        return None
    return user
