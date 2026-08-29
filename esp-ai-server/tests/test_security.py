"""REST API 鉴权测试

验证：
- 管理 REST API 接受 ADMIN_API_KEY 或每设备独立 api_key
- WS 密钥（AUTH_API_KEY / device key）不能访问管理 API（严格分离）
- 多设备模式下，每设备 api_key 可访问管理 API
- 向后兼容：未启用认证或未配置任何密钥时放行
- 认证失败返回正确的 HTTP 状态码
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from src.infrastructure.security import (
    _extract_api_key,
    _get_valid_keys,
    reset_auth_warned_flag,
    verify_admin_api_key,
)


def _make_settings(*, enabled: bool, api_key: str = "", admin_api_key: str = "") -> SimpleNamespace:
    """构造一个轻量 settings mock，避免 pydantic-settings 从 .env 加载覆盖字段"""
    return SimpleNamespace(auth=SimpleNamespace(
        enabled=enabled, api_key=api_key, admin_api_key=admin_api_key
    ))


def _mock_no_devices():
    """模拟无多设备配置（单设备模式）"""
    return SimpleNamespace(has_users=lambda: False, devices={})


def _mock_multi_devices():
    """模拟多设备配置（有 management_api_key）"""
    dev1 = SimpleNamespace(key="ws-key-001", api_key="api-key-001")  # 有 management_api_key
    dev2 = SimpleNamespace(key="ws-key-002", api_key="")             # 无 management_api_key
    dev3 = SimpleNamespace(key="ws-key-003", api_key="api-key-003")  # 有 management_api_key
    return SimpleNamespace(
        has_users=lambda: True,
        devices={
            "MAC:AA:BB:CC:DD:01": dev1,
            "MAC:AA:BB:CC:DD:02": dev2,
            "MAC:AA:BB:CC:DD:03": dev3,
        }
    )


# ============================================================
# _extract_api_key
# ============================================================

class TestExtractApiKey:
    def test_x_api_key_takes_priority(self):
        assert _extract_api_key("admin-key", "Bearer other") == "admin-key"

    def test_bearer_token(self):
        assert _extract_api_key(None, "Bearer my-token") == "my-token"

    def test_bearer_token_with_extra_spaces(self):
        assert _extract_api_key(None, "Bearer   spaced-token  ") == "spaced-token"

    def test_raw_authorization_fallback(self):
        assert _extract_api_key(None, "raw-token") == "raw-token"

    def test_empty_authorization(self):
        assert _extract_api_key(None, "") is None

    def test_both_none(self):
        assert _extract_api_key(None, None) is None

    def test_empty_x_api_key_falls_through(self):
        assert _extract_api_key("", "Bearer fallback") == "fallback"


# ============================================================
# _get_valid_keys - 密钥集合测试
# ============================================================

class TestGetValidKeys:
    @patch("src.use_cases.device_config.load_devices", _mock_no_devices)
    def test_admin_key_only_included(self, monkeypatch):
        """valid_keys 只含 admin_api_key，不含 WS key (api_key)"""
        settings = _make_settings(enabled=True, api_key="ws-key-123", admin_api_key="admin-key-456")
        monkeypatch.setattr("src.infrastructure.security.get_settings", lambda: settings)
        keys = _get_valid_keys()
        assert keys == {"admin-key-456"}
        assert "ws-key-123" not in keys

    @patch("src.use_cases.device_config.load_devices", _mock_no_devices)
    def test_only_admin_key(self, monkeypatch):
        settings = _make_settings(enabled=True, api_key="", admin_api_key="admin-only")
        monkeypatch.setattr("src.infrastructure.security.get_settings", lambda: settings)
        assert _get_valid_keys() == {"admin-only"}

    @patch("src.use_cases.device_config.load_devices", _mock_no_devices)
    def test_no_keys_returns_empty(self, monkeypatch):
        settings = _make_settings(enabled=False, api_key="", admin_api_key="")
        monkeypatch.setattr("src.infrastructure.security.get_settings", lambda: settings)
        assert _get_valid_keys() == set()

    @patch("src.use_cases.device_config.load_devices", _mock_multi_devices)
    def test_include_device_api_keys_from_db(self, monkeypatch):
        """多设备模式下，每设备 api_key 被加入，但 WS key 不加入"""
        settings = _make_settings(enabled=True, api_key="ws-global", admin_api_key="admin-key")
        monkeypatch.setattr("src.infrastructure.security.get_settings", lambda: settings)
        keys = _get_valid_keys()
        assert "admin-key" in keys
        assert "api-key-001" in keys
        assert "api-key-003" in keys
        # WS key 严格分离，不加入
        assert "ws-key-001" not in keys
        assert "ws-key-002" not in keys
        assert "ws-key-003" not in keys
        # 空的 api_key 不加入
        assert "" not in keys

    @patch("src.use_cases.device_config.load_devices", _mock_multi_devices)
    def test_no_api_key_device_not_included(self, monkeypatch):
        """无 management_api_key 的设备不加入"""
        settings = _make_settings(enabled=True, api_key="", admin_api_key="admin-key")
        monkeypatch.setattr("src.infrastructure.security.get_settings", lambda: settings)
        keys = _get_valid_keys()
        # dev2 无 api_key，不加
        assert "ws-key-002" not in keys
        assert "admin-key" in keys


# ============================================================
# verify_admin_api_key - 鉴权行为测试
# ============================================================

class TestVerifyAdminApiKey:
    @pytest.fixture(autouse=True)
    def _reset_warn_flag(self):
        reset_auth_warned_flag()
        yield
        reset_auth_warned_flag()

    @patch("src.use_cases.device_config.load_devices", _mock_no_devices)
    async def test_admin_key_accepted(self, monkeypatch):
        settings = _make_settings(enabled=True, api_key="ws-key", admin_api_key="admin-key")
        monkeypatch.setattr("src.infrastructure.security.get_settings", lambda: settings)
        assert await verify_admin_api_key(x_api_key="admin-key") is True

    @patch("src.use_cases.device_config.load_devices", _mock_no_devices)
    async def test_admin_key_via_bearer(self, monkeypatch):
        settings = _make_settings(enabled=True, api_key="ws-key", admin_api_key="admin-key")
        monkeypatch.setattr("src.infrastructure.security.get_settings", lambda: settings)
        assert await verify_admin_api_key(x_api_key=None, authorization="Bearer admin-key") is True

    @patch("src.use_cases.device_config.load_devices", _mock_no_devices)
    async def test_ws_key_rejected(self, monkeypatch):
        """WS 密钥不能访问管理 API —— 严格分离"""
        settings = _make_settings(enabled=True, api_key="ws-key", admin_api_key="admin-key")
        monkeypatch.setattr("src.infrastructure.security.get_settings", lambda: settings)
        with pytest.raises(HTTPException) as exc_info:
            await verify_admin_api_key(x_api_key="ws-key")
        assert exc_info.value.status_code == 403

    @patch("src.use_cases.device_config.load_devices", _mock_no_devices)
    async def test_ws_key_via_bearer_rejected(self, monkeypatch):
        settings = _make_settings(enabled=True, api_key="ws-key", admin_api_key="admin-key")
        monkeypatch.setattr("src.infrastructure.security.get_settings", lambda: settings)
        with pytest.raises(HTTPException) as exc_info:
            await verify_admin_api_key(x_api_key=None, authorization="Bearer ws-key")
        assert exc_info.value.status_code == 403

    @patch("src.use_cases.device_config.load_devices", _mock_no_devices)
    async def test_unknown_key_rejected(self, monkeypatch):
        settings = _make_settings(enabled=True, api_key="ws-key", admin_api_key="admin-key")
        monkeypatch.setattr("src.infrastructure.security.get_settings", lambda: settings)
        with pytest.raises(HTTPException) as exc_info:
            await verify_admin_api_key(x_api_key="totally-unknown")
        assert exc_info.value.status_code == 403

    @patch("src.use_cases.device_config.load_devices", _mock_no_devices)
    async def test_missing_key_returns_401(self, monkeypatch):
        settings = _make_settings(enabled=True, api_key="ws-key", admin_api_key="admin-key")
        monkeypatch.setattr("src.infrastructure.security.get_settings", lambda: settings)
        with pytest.raises(HTTPException) as exc_info:
            await verify_admin_api_key(x_api_key=None, authorization=None)
        assert exc_info.value.status_code == 401

    @patch("src.use_cases.device_config.load_devices", _mock_no_devices)
    async def test_auth_disabled_allows(self, monkeypatch):
        settings = _make_settings(enabled=False, api_key="ws-key", admin_api_key="admin-key")
        monkeypatch.setattr("src.infrastructure.security.get_settings", lambda: settings)
        assert await verify_admin_api_key(x_api_key=None, authorization=None) is True

    @patch("src.use_cases.device_config.load_devices", _mock_no_devices)
    async def test_no_keys_allows_with_warning(self, monkeypatch):
        """未配置任何密钥时放行+WARNING"""
        settings = _make_settings(enabled=True, api_key="", admin_api_key="")
        monkeypatch.setattr("src.infrastructure.security.get_settings", lambda: settings)
        assert await verify_admin_api_key(x_api_key=None, authorization=None) is True

    @patch("src.use_cases.device_config.load_devices", _mock_multi_devices)
    async def test_device_api_key_accepted(self, monkeypatch):
        """每设备 management_api_key 可访问管理 API"""
        settings = _make_settings(enabled=True, api_key="ws-global", admin_api_key="admin-key")
        monkeypatch.setattr("src.infrastructure.security.get_settings", lambda: settings)
        assert await verify_admin_api_key(x_api_key="api-key-001") is True
        assert await verify_admin_api_key(x_api_key="api-key-003") is True

    @patch("src.use_cases.device_config.load_devices", _mock_multi_devices)
    async def test_device_ws_key_rejected(self, monkeypatch):
        """WS key 严格分离，不能访问管理 API"""
        settings = _make_settings(enabled=True, api_key="ws-global", admin_api_key="admin-key")
        monkeypatch.setattr("src.infrastructure.security.get_settings", lambda: settings)
        with pytest.raises(HTTPException) as exc_info:
            await verify_admin_api_key(x_api_key="ws-key-001")
        assert exc_info.value.status_code == 403

    @patch("src.use_cases.device_config.load_devices", _mock_multi_devices)
    async def test_unknown_key_rejected_in_multi_mode(self, monkeypatch):
        settings = _make_settings(enabled=True, api_key="ws-global", admin_api_key="admin-key")
        monkeypatch.setattr("src.infrastructure.security.get_settings", lambda: settings)
        with pytest.raises(HTTPException) as exc_info:
            await verify_admin_api_key(x_api_key="nonexistent-key")
        assert exc_info.value.status_code == 403


# ============================================================
# Refresh token 查库校验 + token_version 吊销
# ============================================================

import jwt as _pyjwt
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import jwt
import pytest_asyncio
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.infrastructure.db.base import Base
from src.infrastructure.db.models.user import UserModel
from src.infrastructure import security_jwt
from src.infrastructure.routes import admin as admin_routes
from src.infrastructure.routes import auth as auth_routes


@pytest_asyncio.fixture
async def user_db():
    """内存 SQLite（含 users 表），并把 auth/admin/security_jwt 的会话上下文
    替换为指向该库，隔离真实 DB"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def _ctx():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    with patch("src.infrastructure.security_jwt.get_session_ctx", _ctx), \
         patch("src.infrastructure.routes.auth.get_session_ctx", _ctx), \
         patch("src.infrastructure.routes.admin.get_session_ctx", _ctx):
        yield factory
    await engine.dispose()


async def _add_user(factory, *, is_active: bool = True, token_version: int = 0) -> UserModel:
    """插入一个测试用户（默认密码 oldpass123）"""
    user = UserModel(
        id="11111111-1111-1111-1111-111111111111",
        email="rev@example.com",
        password_hash=security_jwt.hash_password("oldpass123"),
        nickname="rev",
        role="user",
        is_active=is_active,
        token_version=token_version,
    )
    async with factory() as session:
        session.add(user)
        await session.commit()
    return user


@pytest.mark.asyncio
class TestRefreshTokenDbValidation:
    """/auth/refresh 必须查库：禁用用户与版本不匹配的 refresh token 拒绝续签"""

    async def test_refresh_rejects_disabled_user(self, user_db):
        """安全修复：被禁用用户即使持有有效 refresh_token 也不能续期"""
        user = await _add_user(user_db, is_active=False, token_version=0)
        token = security_jwt.create_refresh_token(user.id, 0)
        with pytest.raises(HTTPException) as ei:
            await auth_routes.refresh(auth_routes.RefreshReq(refresh_token=token))
        assert ei.value.status_code == 401

    async def test_refresh_rejects_stale_token_version(self, user_db):
        """token_version 不匹配（改密码后已吊销）→ 401"""
        user = await _add_user(user_db, is_active=True, token_version=2)
        stale = security_jwt.create_refresh_token(user.id, 0)  # 旧版本 token
        with pytest.raises(HTTPException) as ei:
            await auth_routes.refresh(auth_routes.RefreshReq(refresh_token=stale))
        assert ei.value.status_code == 401

    async def test_refresh_ok_issues_latest_version(self, user_db):
        """活跃用户 + 版本匹配 → 正常续签，且新 access_token 带最新 token_version"""
        user = await _add_user(user_db, is_active=True, token_version=1)
        token = security_jwt.create_refresh_token(user.id, 1)
        resp = await auth_routes.refresh(auth_routes.RefreshReq(refresh_token=token))
        assert resp["code"] == 0
        payload = security_jwt.decode_token(resp["data"]["access_token"])
        assert payload["type"] == "access"
        assert payload["token_version"] == 1


@pytest.mark.asyncio
class TestTokenVersionRevocation:
    """token_version 吊销语义：get_current_user 校验版本 + 吊销触发点 +1"""

    async def test_get_current_user_rejects_old_version(self, user_db):
        """改密码/停用后版本号已递增，旧 access_token 校验 → 401"""
        user = await _add_user(user_db, is_active=True, token_version=3)
        old_token = security_jwt.create_access_token(user.id, 2)  # 版本落后
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=old_token)
        with pytest.raises(HTTPException) as ei:
            await security_jwt.get_current_user(creds)
        assert ei.value.status_code == 401
        assert "revoked" in str(ei.value.detail).lower()

    async def test_get_current_user_accepts_matching_version(self, user_db):
        """版本匹配时正常通过并返回用户"""
        user = await _add_user(user_db, is_active=True, token_version=3)
        token = security_jwt.create_access_token(user.id, 3)
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        got = await security_jwt.get_current_user(creds)
        assert got.id == user.id

    async def test_change_password_bumps_token_version(self, user_db):
        """用户修改密码后 token_version +1，旧 access_token 全部失效"""
        user = await _add_user(user_db, is_active=True, token_version=0)
        old_token = security_jwt.create_access_token(user.id, 0)
        await auth_routes.change_password(
            auth_routes.PasswordChangeReq(old_password="oldpass123", new_password="newpass456"),
            user=user,
        )
        async with user_db() as session:
            from sqlalchemy import select
            row = (await session.execute(
                select(UserModel).where(UserModel.id == user.id)
            )).scalar_one()
        assert row.token_version == 1
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=old_token)
        with pytest.raises(HTTPException) as ei:
            await security_jwt.get_current_user(creds)
        assert ei.value.status_code == 401

    async def test_admin_reset_password_bumps_token_version(self, user_db):
        """管理员重置用户密码后 token_version +1"""
        user = await _add_user(user_db, is_active=True, token_version=0)
        await admin_routes.admin_reset_password(
            user.id, admin_routes.ResetPasswordReq(new_password="brandnew123")
        )
        async with user_db() as session:
            from sqlalchemy import select
            row = (await session.execute(
                select(UserModel).where(UserModel.id == user.id)
            )).scalar_one()
        assert row.token_version == 1
        assert security_jwt.verify_password("brandnew123", row.password_hash)

    async def test_admin_disable_user_bumps_token_version(self, user_db):
        """管理员停用用户后 token_version +1（即使重新启用，旧 token 也已失效）"""
        admin = UserModel(
            id="22222222-2222-2222-2222-222222222222",
            email="root@example.com",
            password_hash=security_jwt.hash_password("adminpass123"),
            nickname="root",
            role="admin",
            is_active=True,
            token_version=0,
        )
        user = await _add_user(user_db, is_active=True, token_version=0)
        await admin_routes.update_user(
            user.id, admin_routes.UserUpdateReq(is_active=False), admin=admin
        )
        async with user_db() as session:
            from sqlalchemy import select
            row = (await session.execute(
                select(UserModel).where(UserModel.id == user.id)
            )).scalar_one()
        assert row.is_active is False
        assert row.token_version == 1
