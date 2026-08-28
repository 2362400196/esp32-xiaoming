"""WebSocket Handler 全局并发控制接入测试

验证 handle_websocket 在鉴权通过后、创建 handler 之前接入全局并发控制：
- 插槽可用时：正常进入 handler 流程，退出时释放插槽
- 插槽不可用（try_acquire 返回 False）时：以 1013 关闭连接，不创建 handler
- handler 抛异常 / 客户端断开时：finally 仍释放插槽
- 缺 key（进入绑定模式）/ 鉴权失败时：不获取插槽（提前 return）
- 已绑定但无 key 连接：以 4004 拒绝（不得自动发 key 放行）
- 带 key 连接：封禁检查对 DB 中 is_banned 设备生效（4003）
"""
from __future__ import annotations

import asyncio
import inspect
import string
from contextlib import asynccontextmanager, contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.interfaces import websocket_handler


@pytest.fixture(autouse=True)
def fake_db_not_found():
    """默认隔离真实 DB：按 key / mac 查询设备一律返回 None（单个测试可自行覆盖）"""
    sync_result = MagicMock()
    sync_result.scalar_one_or_none.return_value = None
    sync_session = MagicMock()
    sync_session.execute = MagicMock(return_value=sync_result)
    sync_session.flush = MagicMock()
    sync_session.commit = MagicMock()

    @contextmanager
    def _sync_ctx():
        yield sync_session

    async_result = MagicMock()
    async_result.scalar_one_or_none.return_value = None
    async_session = MagicMock()
    async_session.execute = AsyncMock(return_value=async_result)
    async_session.commit = AsyncMock()
    async_session.flush = AsyncMock()
    async_session.delete = AsyncMock()

    @asynccontextmanager
    async def _async_ctx():
        yield async_session

    with patch("src.infrastructure.db.compat.sync_session.get_sync_session", _sync_ctx), \
         patch("src.infrastructure.db.session.get_session_ctx", _async_ctx):
        yield


@pytest.fixture(autouse=True)
def reset_concurrency_globals():
    """每个测试前后重置并发模块全局变量"""
    from src.infrastructure import concurrency
    concurrency._global_semaphore = None
    concurrency._global_semaphore_max = 30
    concurrency._available_count = 30
    concurrency._process_pool = None
    yield
    if concurrency._process_pool is not None:
        concurrency._process_pool.shutdown(wait=True)
        concurrency._process_pool = None
    concurrency._global_semaphore = None
    concurrency._global_semaphore_max = 30
    concurrency._available_count = 30


def _make_ws(query_key: str = "test-key", device_id: str = "AA:BB:CC"):
    """构造一个 mock WebSocket，记录 close 调用"""
    ws = MagicMock()
    ws.query_params = {
        "key": query_key,
        "mac": device_id,
        "version": "1.0",
        "AUDIO_BUFFER_SIZE": "10240",
    }
    ws.url.path = "/"
    ws.close = AsyncMock()
    return ws


@pytest.fixture
def stub_auth_ok():
    """鉴权通过：auth_service.verify_api_key 返回 True"""
    auth_service = MagicMock()
    auth_service.verify_api_key.return_value = True
    with patch("src.interfaces.websocket_handler.get_auth_service", return_value=auth_service):
        yield auth_service


@pytest.fixture
def stub_session_handler_cls():
    """mock WebSocketSessionHandler，返回可控的 handler 实例"""
    handler_inst = MagicMock()
    handler_inst.initialize = AsyncMock()
    handler_inst.run = AsyncMock()
    handler_inst.cleanup = AsyncMock()

    # patch 模块内的 WebSocketSessionHandler 引用
    with patch.object(websocket_handler, "WebSocketSessionHandler", return_value=handler_inst) as mock_cls:
        yield mock_cls, handler_inst


# ─── 正常流程：插槽可用 ─────────────────────────────────────

class TestHandleWebsocketConcurrency:
    """handle_websocket 全局并发控制接入测试"""

    async def test_acquires_slot_and_releases_on_normal_exit(
        self, stub_auth_ok, stub_session_handler_cls
    ):
        """正常退出时应释放全局并发插槽"""
        from src.infrastructure import concurrency

        # 启用全局并发限制，max=2
        concurrency._global_semaphore = asyncio.Semaphore(2)
        concurrency._global_semaphore_max = 2
        concurrency._available_count = 2

        ws = _make_ws()
        with patch("src.interfaces.websocket_handler.get_settings") as mock_settings:
            mock_settings.return_value.deploy_mode = "single"
            await websocket_handler.handle_websocket(ws)

        # 插槽被获取后又释放，计数器应恢复
        assert concurrency._available_count == 2
        # handler 应被创建并执行
        _, handler_inst = stub_session_handler_cls
        handler_inst.initialize.assert_called_once()
        handler_inst.run.assert_called_once()
        handler_inst.cleanup.assert_called_once()
        # 不应被 1013 关闭
        ws.close.assert_not_called()

    async def test_releases_slot_on_handler_exception(
        self, stub_auth_ok, stub_session_handler_cls
    ):
        """handler 抛异常时 finally 仍应释放插槽"""
        from src.infrastructure import concurrency

        concurrency._global_semaphore = asyncio.Semaphore(1)
        concurrency._global_semaphore_max = 1
        concurrency._available_count = 1

        _, handler_inst = stub_session_handler_cls
        handler_inst.run = AsyncMock(side_effect=RuntimeError("boom"))

        ws = _make_ws()
        with patch("src.interfaces.websocket_handler.get_settings") as mock_settings:
            mock_settings.return_value.deploy_mode = "single"
            # 异常被 handle_websocket 内部捕获，不向外抛
            await websocket_handler.handle_websocket(ws)

        # 插槽应被释放
        assert concurrency._available_count == 1
        # cleanup 仍应被调用
        handler_inst.cleanup.assert_called_once()

    async def test_releases_slot_on_websocket_disconnect(
        self, stub_auth_ok, stub_session_handler_cls
    ):
        """WebSocketDisconnect 时 finally 仍应释放插槽"""
        from starlette.websockets import WebSocketDisconnect
        from src.infrastructure import concurrency

        concurrency._global_semaphore = asyncio.Semaphore(1)
        concurrency._global_semaphore_max = 1
        concurrency._available_count = 1

        _, handler_inst = stub_session_handler_cls
        handler_inst.run = AsyncMock(side_effect=WebSocketDisconnect(code=1001))

        ws = _make_ws()
        with patch("src.interfaces.websocket_handler.get_settings") as mock_settings:
            mock_settings.return_value.deploy_mode = "single"
            await websocket_handler.handle_websocket(ws)

        # 插槽应被释放
        assert concurrency._available_count == 1
        handler_inst.cleanup.assert_called_once()


# ─── 过载拒绝：try_acquire 返回 False ───────────────────────

class TestHandleWebsocketOverload:
    """全局并发过载时 handle_websocket 应以 1013 拒绝连接"""

    async def test_overload_closes_with_1013_and_skips_handler(
        self, stub_auth_ok, stub_session_handler_cls
    ):
        """try_acquire_global_slot 返回 False 时应以 1013 关闭，不创建 handler"""
        _, handler_inst = stub_session_handler_cls

        async def _fake_try_acquire(timeout=0.0):
            return False

        ws = _make_ws()
        with patch("src.interfaces.websocket_handler.try_acquire_global_slot", new=_fake_try_acquire), \
             patch("src.interfaces.websocket_handler.get_settings") as mock_settings:
            mock_settings.return_value.deploy_mode = "single"
            await websocket_handler.handle_websocket(ws)

        # 应以 1013 关闭
        ws.close.assert_called_once()
        args, kwargs = ws.close.call_args
        assert kwargs.get("code") == 1013 or (args and args[0] == 1013)
        # handler 不应被创建
        handler_inst.initialize.assert_not_called()
        handler_inst.run.assert_not_called()
        handler_inst.cleanup.assert_not_called()

    async def test_overload_does_not_release_slot(
        self, stub_auth_ok, stub_session_handler_cls
    ):
        """过载拒绝时不应调用 release_global_slot（因为没获取到插槽）"""
        release_called = False

        async def _fake_try_acquire(timeout=0.0):
            return False

        def _fake_release():
            nonlocal release_called
            release_called = True

        ws = _make_ws()
        with patch("src.interfaces.websocket_handler.try_acquire_global_slot", new=_fake_try_acquire), \
             patch("src.interfaces.websocket_handler.release_global_slot", new=_fake_release), \
             patch("src.interfaces.websocket_handler.get_settings") as mock_settings:
            mock_settings.return_value.deploy_mode = "single"
            await websocket_handler.handle_websocket(ws)

        assert release_called is False


# ─── 鉴权失败 / 缺 key：不应获取插槽 ────────────────────────

class TestHandleWebsocketAuthBypass:
    """鉴权失败 / 缺 key 时应提前 return，不获取并发插槽"""

    async def test_missing_key_enters_bind_mode_without_acquiring_slot(
        self, stub_session_handler_cls
    ):
        """缺少 device key 且设备未绑定时：进入绑定模式（发送绑定码后关闭），不获取插槽"""
        acquire_called = False

        async def _fake_try_acquire(timeout=0.0):
            nonlocal acquire_called
            acquire_called = True
            return True

        ws = _make_ws(query_key="")
        with patch.object(
            websocket_handler, "_send_bind_code_and_close", new=AsyncMock()
        ) as mock_bind, \
             patch("src.interfaces.websocket_handler.try_acquire_global_slot", new=_fake_try_acquire), \
             patch("src.interfaces.websocket_handler.get_settings") as mock_settings:
            mock_settings.return_value.deploy_mode = "single"
            await websocket_handler.handle_websocket(ws)

        # 应进入绑定模式，而不是直接关闭
        mock_bind.assert_awaited_once()
        assert acquire_called is False

    async def test_auth_failure_closes_4003_without_acquiring_slot(
        self, stub_session_handler_cls
    ):
        """鉴权失败时应以 4003 关闭，不获取插槽"""
        acquire_called = False

        async def _fake_try_acquire(timeout=0.0):
            nonlocal acquire_called
            acquire_called = True
            return True

        auth_service = MagicMock()
        auth_service.verify_api_key.return_value = False
        ws = _make_ws()
        with patch("src.interfaces.websocket_handler.get_auth_service", return_value=auth_service), \
             patch("src.interfaces.websocket_handler.try_acquire_global_slot", new=_fake_try_acquire), \
             patch("src.interfaces.websocket_handler.get_settings") as mock_settings:
            mock_settings.return_value.deploy_mode = "single"
            await websocket_handler.handle_websocket(ws)

        ws.close.assert_called_once()
        args, kwargs = ws.close.call_args
        assert kwargs.get("code") == 4003 or (args and args[0] == 4003)
        assert acquire_called is False


# ─── 安全修复回归测试 ────────────────────────────────────────

def _make_sync_db(device):
    """构造假的同步 DB 会话（get_sync_session），execute 一律返回 device"""
    result = MagicMock()
    result.scalar_one_or_none.return_value = device
    session = MagicMock()
    session.execute = MagicMock(return_value=result)
    session.flush = MagicMock()
    session.commit = MagicMock()

    @contextmanager
    def _ctx():
        yield session

    return _ctx


def _make_async_db(device):
    """构造假的异步 DB 会话（get_session_ctx），execute 一律返回 device"""
    result = MagicMock()
    result.scalar_one_or_none.return_value = device
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.delete = AsyncMock()

    @asynccontextmanager
    async def _ctx():
        yield session

    return _ctx


class TestSecurityFixes:
    """安全漏洞修复回归测试"""

    async def test_key_connection_runs_ban_check(
        self, stub_auth_ok, stub_session_handler_cls
    ):
        """带 key 连接：device 记录按 device_key 查询，封禁检查正常执行（修复 UnboundLocalError）"""
        device = MagicMock()
        device.is_banned = False
        device.user_id = "user-1"
        device.device_key = "test-key"

        ws = _make_ws()
        with patch(
            "src.infrastructure.db.compat.sync_session.get_sync_session",
            _make_sync_db(device),
        ), \
             patch("src.interfaces.websocket_handler.get_settings") as mock_settings:
            mock_settings.return_value.deploy_mode = "single"
            await websocket_handler.handle_websocket(ws)

        # 不应被封禁拒绝，正常进入 handler 流程
        ws.close.assert_not_called()
        _, handler_inst = stub_session_handler_cls
        handler_inst.initialize.assert_called_once()

    async def test_banned_device_with_key_rejected_4003(
        self, stub_auth_ok, stub_session_handler_cls
    ):
        """带 key 连接且设备已封禁：应以 4003 拒绝，不创建 handler、不获取插槽"""
        acquire_called = False

        async def _fake_try_acquire(timeout=0.0):
            nonlocal acquire_called
            acquire_called = True
            return True

        device = MagicMock()
        device.is_banned = True
        device.ban_reason = "测试封禁"
        device.device_id = "dev-1"
        device.user_id = "user-1"
        device.device_key = "test-key"

        ws = _make_ws()
        with patch(
            "src.infrastructure.db.compat.sync_session.get_sync_session",
            _make_sync_db(device),
        ), \
             patch("src.interfaces.websocket_handler.try_acquire_global_slot", new=_fake_try_acquire), \
             patch("src.interfaces.websocket_handler.get_settings") as mock_settings:
            mock_settings.return_value.deploy_mode = "single"
            await websocket_handler.handle_websocket(ws)

        ws.close.assert_called_once()
        args, kwargs = ws.close.call_args
        code = kwargs.get("code", args[0] if args else None)
        reason = kwargs.get("reason", args[1] if len(args) > 1 else "")
        assert code == 4003
        assert "Device banned" in reason
        assert acquire_called is False
        _, handler_inst = stub_session_handler_cls
        handler_inst.initialize.assert_not_called()

    async def test_bound_device_without_key_rejected_4004(self, stub_session_handler_cls):
        """已绑定用户但无 key 连接：不得自动发 key 放行，应以 4004 拒绝（防 MAC 嗅探接管）"""
        acquire_called = False

        async def _fake_try_acquire(timeout=0.0):
            nonlocal acquire_called
            acquire_called = True
            return True

        device = MagicMock()
        device.user_id = "user-1"
        device.device_key = None
        device.mac_address = "AA:BB:CC:DD:EE:FF"
        device.device_id = "AA:BB:CC:DD:EE:FF"
        device.is_banned = False

        ws = _make_ws(query_key="")
        with patch(
            "src.infrastructure.db.session.get_session_ctx",
            _make_async_db(device),
        ), \
             patch.object(
                 websocket_handler, "_send_bind_code_and_close", new=AsyncMock()
             ) as mock_bind, \
             patch("src.interfaces.websocket_handler.try_acquire_global_slot", new=_fake_try_acquire), \
             patch("src.interfaces.websocket_handler.get_settings") as mock_settings:
            mock_settings.return_value.deploy_mode = "single"
            await websocket_handler.handle_websocket(ws)

        ws.close.assert_called_once()
        args, kwargs = ws.close.call_args
        code = kwargs.get("code", args[0] if args else None)
        assert code == 4004
        # 不应进入绑定模式，也不应获取插槽
        mock_bind.assert_not_called()
        assert acquire_called is False

    async def test_unbound_device_without_key_still_gets_bind_code(
        self, stub_session_handler_cls
    ):
        """未绑定用户（首次配网）且无 key 连接：保留自动发绑定码行为"""
        device = MagicMock()
        device.user_id = None
        device.device_key = None
        device.mac_address = "AA:BB:CC:DD:EE:FF"

        ws = _make_ws(query_key="", device_id="AA:BB:CC:DD:EE:FF")
        with patch(
            "src.infrastructure.db.session.get_session_ctx",
            _make_async_db(device),
        ), \
             patch.object(
                 websocket_handler, "_send_bind_code_and_close", new=AsyncMock()
             ) as mock_bind, \
             patch("src.interfaces.websocket_handler.get_settings") as mock_settings:
            mock_settings.return_value.deploy_mode = "single"
            await websocket_handler.handle_websocket(ws)

        mock_bind.assert_awaited_once()
        args, _ = mock_bind.call_args
        assert args[1] == "AA:BB:CC:DD:EE:FF"

    def test_device_key_not_derivable_from_mac(self):
        """自动注册的 device_key 不应由 MAC 推导（不应再出现 'auto_' + mac[-8:] 模式）"""
        src = inspect.getsource(websocket_handler)
        assert "device_mac[-8:]" not in src
        # 绑定码与自动 key 均应使用 secrets（密码学安全随机数）
        assert "secrets" in src
        assert "random.choices" not in src

    def test_bind_code_uses_secure_random(self):
        """绑定码使用 secrets 生成：6 位、字符集正确、多次生成不同"""
        code = websocket_handler._generate_bind_code()
        assert len(code) == 6
        assert all(c in string.ascii_uppercase + string.digits for c in code)
        codes = {websocket_handler._generate_bind_code() for _ in range(20)}
        assert len(codes) > 1
