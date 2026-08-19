"""用户认证路由：注册、登录、刷新 Token、获取当前用户信息

新增端点（替换旧的 X-API-Key 认证）：
- POST /api/v1/auth/register  - 注册
- POST /api/v1/auth/login     - 登录，返回 JWT
- POST /api/v1/auth/refresh   - 刷新 Token
- GET  /api/v1/user/me        - 获取当前用户信息
- PUT  /api/v1/user/me        - 更新个人信息
- PUT  /api/v1/user/password  - 修改密码
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select

from src.infrastructure.db.session import get_session_ctx
from src.infrastructure.db.models.user import UserModel
from src.infrastructure.logging import get_logger
from src.infrastructure.security_jwt import (
    get_current_user,
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
)

logger = get_logger(__name__)
router = APIRouter(tags=["auth"])


# ==================== Pydantic 模型 ====================

class RegisterReq(BaseModel):
    email: str
    password: str
    nickname: str = ""

    @field_validator("password")
    @classmethod
    def password_length(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters")
        return v


class LoginReq(BaseModel):
    email: str
    password: str


class LoginResp(BaseModel):
    access_token: str
    refresh_token: str
    user_id: str
    email: str
    nickname: str
    role: str
    max_devices: int


class RefreshReq(BaseModel):
    refresh_token: str


class UserUpdateReq(BaseModel):
    nickname: str = ""
    email: str = ""


class PasswordChangeReq(BaseModel):
    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_length(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("New password must be at least 6 characters")
        return v


class UserResp(BaseModel):
    user_id: str
    email: str
    nickname: str
    role: str
    max_devices: int
    created_at: float


# ==================== 路由 ====================

@router.post("/api/v1/auth/register")
async def register(req: RegisterReq):
    """用户注册。**系统中第一个注册的用户自动成为管理员**（role=admin），其余为普通用户。"""
    async with get_session_ctx() as session:
        existing = await session.execute(
            select(UserModel).where(UserModel.email == req.email)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(400, "Email already registered")

        # 首个用户自动成为管理员（系统初始化：固件管理/批量 OTA/全局插件重载等仅管理员可用）
        from sqlalchemy import func
        user_count = await session.execute(select(func.count()).select_from(UserModel))
        is_first_user = (user_count.scalar_one() or 0) == 0

        user = UserModel(
            id=str(uuid.uuid4()),
            email=req.email,
            password_hash=hash_password(req.password),
            nickname=req.nickname or req.email.split("@")[0],
            role="admin" if is_first_user else "user",
        )
        session.add(user)
        await session.flush()

    return {"code": 0, "message": "ok", "data": {"user_id": user.id, "role": user.role}}


@router.post("/api/v1/auth/login")
async def login(req: LoginReq):
    """用户登录，返回 access_token + refresh_token"""
    async with get_session_ctx() as session:
        result = await session.execute(
            select(UserModel).where(UserModel.email == req.email)
        )
        user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(403, "User disabled")

    # 更新登录时间
    user.last_login = datetime.now(timezone.utc).timestamp()
    async with get_session_ctx() as session:
        session.add(user)

    return {
        "code": 0, "message": "ok",
        "data": {
            "access_token": create_access_token(user.id),
            "refresh_token": create_refresh_token(user.id),
            "user_id": user.id,
            "email": user.email,
            "nickname": user.nickname,
              "role": user.role,
              "max_devices": user.max_devices,
        },
    }


@router.post("/api/v1/auth/refresh")
async def refresh(req: RefreshReq):
    """刷新 access_token"""
    try:
        payload = decode_token(req.refresh_token)
    except Exception:
        raise HTTPException(401, "Invalid or expired refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(401, "Invalid token type")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(401, "Invalid token payload")

    return {
        "code": 0, "message": "ok",
        "data": {"access_token": create_access_token(user_id)},
    }


@router.get("/api/v1/user/me")
async def get_me(user: UserModel = Depends(get_current_user)):
    """获取当前用户信息"""
    return {
        "code": 0, "message": "ok",
        "data": UserResp(
            user_id=user.id,
            email=user.email,
            nickname=user.nickname,
            role=user.role,
            max_devices=user.max_devices,
            created_at=user.created_at,
        ),
    }


@router.put("/api/v1/user/me")
async def update_me(req: UserUpdateReq, user: UserModel = Depends(get_current_user)):
    """更新个人信息"""
    if req.nickname:
        user.nickname = req.nickname
    if req.email and req.email != user.email:
        async with get_session_ctx() as session:
            existing = await session.execute(
                __import__("sqlalchemy").select(UserModel).where(UserModel.email == req.email)
            )
            if existing.scalar_one_or_none():
                raise HTTPException(400, "Email already in use")
        user.email = req.email

    async with get_session_ctx() as session:
        session.add(user)

    return {"code": 0, "message": "ok"}


@router.put("/api/v1/user/password")
async def change_password(req: PasswordChangeReq, user: UserModel = Depends(get_current_user)):
    """修改密码"""
    if not verify_password(req.old_password, user.password_hash):
        raise HTTPException(400, "Old password is incorrect")

    user.password_hash = hash_password(req.new_password)
    async with get_session_ctx() as session:
        session.add(user)

    return {"code": 0, "message": "ok"}
