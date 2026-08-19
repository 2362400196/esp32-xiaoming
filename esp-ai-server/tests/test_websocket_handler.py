"""WebSocket Handler 全局并发控制接入测试

验证 handle_websocket 在鉴权通过后、创建 handler 之前接入全局并发控制：
- 插槽可用时：正常进入 handler 流程，退出时释放插槽
- 插槽不可用（try_acquire 返回 False）时：以 1013 关闭连接，不创建 handler
- handler 抛异常 / 客户端断开时：finally 仍释放插槽
- 缺 key / 鉴权失败时：不获取插槽（提前 return）
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.interfaces import websocket_handler


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

    async def test_missing_key_closes_4001_without_acquiring_slot(self, stub_session_handler_cls):
        """缺少 device key 时应以 4001 关闭，不获取插槽"""
        acquire_called = False

        async def _fake_try_acquire(timeout=0.0):
            nonlocal acquire_called
            acquire_called = True
            return True

        ws = _make_ws(query_key="")
        with patch("src.interfaces.websocket_handler.try_acquire_global_slot", new=_fake_try_acquire), \
             patch("src.interfaces.websocket_handler.get_settings") as mock_settings:
            mock_settings.return_value.deploy_mode = "single"
            await websocket_handler.handle_websocket(ws)

        ws.close.assert_called_once()
        args, kwargs = ws.close.call_args
        assert kwargs.get("code") == 4001 or (args and args[0] == 4001)
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
