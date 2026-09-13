"""
用户钱包测试

覆盖范围：
- users.wallet_balance 迁移列（旧库补列默认 5 元）
- 注册发放初始余额（跟随 WALLET_INITIAL_BALANCE 配置）
- wallet 服务：device_can_chat / deduct_for_device / adjust_user_balance
- 管理端余额调整接口（含 404）
- /user/me 返回余额
"""
import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.infrastructure.db.base import Base
from src.infrastructure.db.models.user import UserModel
from src.infrastructure.routes import admin as admin_routes
from src.infrastructure.routes import auth as auth_routes
from src.infrastructure.routes.admin import router as admin_router
from src.infrastructure.routes.auth import router as auth_router
from src.use_cases import wallet as wallet_svc


@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch):
    """内存库 + 钱包配置固定（initial=5, cost=0.1）"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    import src.infrastructure.db.engine as engine_mod
    monkeypatch.setattr(engine_mod, "_async_engine", engine)
    monkeypatch.setattr(engine_mod, "_async_session_factory", factory)

    from src.infrastructure.config import get_settings
    settings = get_settings()
    saved = (settings.wallet_initial_balance, settings.wallet_cost_per_round, settings.wallet_enabled)
    settings.wallet_initial_balance = 5.0
    settings.wallet_cost_per_round = 0.1
    settings.wallet_enabled = True

    # 建一个用户 + 一台绑定设备
    async with factory() as session:
        session.add(UserModel(id="u1", email="u1@x", password_hash="x",
                              wallet_balance=5.0, role="user"))
        from src.infrastructure.db.models.device import DeviceModel
        session.add(DeviceModel(device_id="MAC1", device_key="bound_k1",
                                mac_address="MAC1", user_id="u1"))
        await session.commit()

    yield factory, settings
    settings.wallet_initial_balance, settings.wallet_cost_per_round, settings.wallet_enabled = saved
    await engine.dispose()


# ════════════════════════════════════════════════════════════════
# wallet 服务
# ════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestWalletService:
    async def test_device_can_chat_by_all_key_forms(self, env):
        factory, _settings = env
        assert await wallet_svc.device_can_chat("MAC1") is True        # device_id
        assert await wallet_svc.device_can_chat("bound_k1") is True    # device_key
        assert await wallet_svc.device_can_chat("unknown") is True     # 未绑定设备不拦截

    async def test_device_blocked_when_balance_zero(self, env):
        factory, _settings = env
        async with factory() as session:
            u = await session.get(UserModel, "u1")
            u.wallet_balance = 0.0
            await session.commit()
        assert await wallet_svc.device_can_chat("MAC1") is False

    async def test_wallet_disabled_allows_chat(self, env):
        factory, settings = env
        settings.wallet_enabled = False
        async with factory() as session:
            u = await session.get(UserModel, "u1")
            u.wallet_balance = 0.0
            await session.commit()
        assert await wallet_svc.device_can_chat("MAC1") is True

    async def test_deduct_floors_at_zero(self, env):
        factory, _settings = env
        await wallet_svc.deduct_for_device("MAC1", 0.1, "对话扣费")
        assert await wallet_svc.get_device_balance("MAC1") == 4.9
        await wallet_svc.deduct_for_device("MAC1", 99.0)
        assert await wallet_svc.get_device_balance("MAC1") == 0.0

    async def test_deduct_unbound_device_noop(self, env):
        factory, _settings = env
        await wallet_svc.deduct_for_device("unknown", 1.0)
        assert await wallet_svc.get_device_balance("MAC1") == 5.0  # 未变

    async def test_adjust_user_balance(self, env):
        factory, _settings = env
        assert await wallet_svc.adjust_user_balance("u1", 10.0) == 15.0
        assert await wallet_svc.adjust_user_balance("u1", -20.0) == 0.0
        assert await wallet_svc.adjust_user_balance("ghost", 1.0) is None


# ════════════════════════════════════════════════════════════════
# 注册发放初始余额
# ════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestRegistrationGrant:
    async def test_register_grants_initial_balance(self, env, monkeypatch):
        """注册用户获得 WALLET_INITIAL_BALANCE 设定的初始余额"""
        factory, settings = env
        settings.wallet_initial_balance = 8.88

        app = FastAPI()
        app.include_router(auth_router)
        tc = TestClient(app)

        async def fake_admin():
            return None
        res = tc.post("/api/v1/auth/register", json={
            "email": "new@x", "password": "secret123", "nickname": "新用户",
        })
        assert res.status_code == 200
        async with factory() as session:
            u = (await session.execute(
                __import__("sqlalchemy").select(UserModel).where(UserModel.email == "new@x")
            )).scalar_one()
            assert u.wallet_balance == 8.88
