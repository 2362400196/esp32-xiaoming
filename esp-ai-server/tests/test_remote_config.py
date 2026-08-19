"""
remote_config 远程配置提供者单元测试

覆盖范围：
- RemoteConfigProvider：初始化 / is_enabled / get_device_config / get_user_config /
  get_mcp_config / get_all_devices_config / report_device_status /
  _fetch_config（aiohttp / httpx / 无库）/ _post_data（aiohttp / httpx / 无库）/
  start_background_refresh / _refresh_loop / _refresh_all / clear_cache / update_config
- get_remote_config_provider / init_remote_config_provider 全局单例
"""
import asyncio
import sys
import time
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.remote_config import (
    RemoteConfig,
    RemoteConfigProvider,
    get_remote_config_provider,
    init_remote_config_provider,
)

# ── 注入 fake aiohttp 模块（环境中未安装 aiohttp）──
# 使源码中的 `import aiohttp` 成功，随后可 patch aiohttp.ClientSession
_fake_aiohttp = types.ModuleType("aiohttp")
_fake_aiohttp.ClientSession = MagicMock()
_fake_aiohttp.ClientTimeout = MagicMock()
sys.modules.setdefault("aiohttp", _fake_aiohttp)


# ════════════════════════════════════════════════════════════════
# RemoteConfig 数据类测试
# ════════════════════════════════════════════════════════════════

class TestRemoteConfigDataclass:
    """RemoteConfig 数据类测试"""

    def test_default_fields(self):
        cfg = RemoteConfig(device_key="dev1", config={"a": 1}, fetched_at=time.time())
        assert cfg.device_key == "dev1"
        assert cfg.config == {"a": 1}
        assert cfg.ttl == 300


# ════════════════════════════════════════════════════════════════
# RemoteConfigProvider 初始化与配置测试
# ════════════════════════════════════════════════════════════════

class TestRemoteConfigProviderInit:
    """初始化与配置管理测试"""

    def test_init_disabled_when_no_url(self):
        """无 api_base_url 时 is_enabled=False"""
        provider = RemoteConfigProvider()
        assert provider.is_enabled is False
        assert provider.api_base_url == ""
        assert provider.cache_ttl == 300
        assert provider.refresh_interval == 60
        assert provider.timeout == 10.0

    def test_init_enabled_with_url(self):
        """有 api_base_url 时 is_enabled=True"""
        provider = RemoteConfigProvider(api_base_url="http://example.com/", api_key="secret")
        assert provider.is_enabled is True
        # URL 应去除尾部斜杠
        assert provider.api_base_url == "http://example.com"
        assert provider.api_key == "secret"

    def test_update_config_enable(self):
        """update_config 启用"""
        provider = RemoteConfigProvider()
        provider.update_config(api_base_url="http://new.url", api_key="new_key")
        assert provider.is_enabled is True
        assert provider.api_base_url == "http://new.url"
        assert provider.api_key == "new_key"

    def test_update_config_disable(self):
        """update_config 禁用（空 URL）"""
        provider = RemoteConfigProvider(api_base_url="http://old.url")
        provider.update_config(api_base_url="")
        assert provider.is_enabled is False

    def test_update_config_partial(self):
        """update_config 部分更新"""
        provider = RemoteConfigProvider(api_base_url="http://x.com", api_key="k1")
        provider.update_config(api_key="k2")
        assert provider.api_key == "k2"
        assert provider.api_base_url == "http://x.com"


# ════════════════════════════════════════════════════════════════
# 禁用状态下各方法测试
# ════════════════════════════════════════════════════════════════

class TestDisabledProvider:
    """禁用状态下各方法应返回 None/False"""

    async def test_get_device_config_disabled(self):
        provider = RemoteConfigProvider()
        assert await provider.get_device_config("dev1") is None

    async def test_get_user_config_disabled(self):
        provider = RemoteConfigProvider()
        assert await provider.get_user_config("user1") is None

    async def test_get_mcp_config_disabled(self):
        provider = RemoteConfigProvider()
        assert await provider.get_mcp_config("user1") is None

    async def test_get_all_devices_config_disabled(self):
        provider = RemoteConfigProvider()
        assert await provider.get_all_devices_config() is None

    async def test_report_device_status_disabled(self):
        provider = RemoteConfigProvider()
        assert await provider.report_device_status("dev1", "online") is False

    async def test_start_background_refresh_disabled(self):
        """禁用时启动后台刷新应无操作"""
        provider = RemoteConfigProvider()
        await provider.start_background_refresh()
        assert provider._refresh_task is None


# ════════════════════════════════════════════════════════════════
# 缓存与获取测试（mock _fetch_config）
# ════════════════════════════════════════════════════════════════

class TestConfigFetching:
    """配置获取与缓存测试"""

    async def test_get_device_config_fetch_success(self):
        """首次获取应 fetch 并缓存"""
        provider = RemoteConfigProvider(api_base_url="http://x.com")
        provider._fetch_config = AsyncMock(return_value={"name": "dev1"})
        result = await provider.get_device_config("dev1")
        assert result == {"name": "dev1"}
        assert "device:dev1" in provider._cache

    async def test_get_device_config_from_cache(self):
        """缓存命中时不应 fetch"""
        provider = RemoteConfigProvider(api_base_url="http://x.com")
        provider._fetch_config = AsyncMock(return_value={"name": "dev1"})
        # 第一次获取
        await provider.get_device_config("dev1")
        # 第二次应命中缓存
        provider._fetch_config.reset_mock()
        result = await provider.get_device_config("dev1")
        assert result == {"name": "dev1"}
        provider._fetch_config.assert_not_called()

    async def test_get_device_config_fetch_returns_none(self):
        """fetch 返回 None 时应返回 None"""
        provider = RemoteConfigProvider(api_base_url="http://x.com")
        provider._fetch_config = AsyncMock(return_value=None)
        result = await provider.get_device_config("dev1")
        assert result is None

    async def test_get_device_config_fetch_exception_uses_expired_cache(self):
        """fetch 异常时应回退到过期缓存"""
        provider = RemoteConfigProvider(api_base_url="http://x.com")
        # 预填过期缓存
        provider._cache["device:dev1"] = RemoteConfig(
            device_key="dev1", config={"old": True}, fetched_at=0, ttl=1,
        )
        provider._fetch_config = AsyncMock(side_effect=RuntimeError("net error"))
        result = await provider.get_device_config("dev1")
        assert result == {"old": True}

    async def test_get_device_config_fetch_exception_no_cache(self):
        """fetch 异常且无缓存时返回 None"""
        provider = RemoteConfigProvider(api_base_url="http://x.com")
        provider._fetch_config = AsyncMock(side_effect=RuntimeError("net error"))
        result = await provider.get_device_config("dev1")
        assert result is None

    async def test_get_user_config_fetch_success(self):
        provider = RemoteConfigProvider(api_base_url="http://x.com")
        provider._fetch_config = AsyncMock(return_value={"role": "admin"})
        result = await provider.get_user_config("user1")
        assert result == {"role": "admin"}
        assert "user:user1" in provider._cache

    async def test_get_user_config_from_cache(self):
        provider = RemoteConfigProvider(api_base_url="http://x.com")
        provider._fetch_config = AsyncMock(return_value={"role": "admin"})
        await provider.get_user_config("user1")
        provider._fetch_config.reset_mock()
        result = await provider.get_user_config("user1")
        assert result == {"role": "admin"}
        provider._fetch_config.assert_not_called()

    async def test_get_mcp_config_fetch_success(self):
        provider = RemoteConfigProvider(api_base_url="http://x.com")
        provider._fetch_config = AsyncMock(return_value={"servers": {}})
        result = await provider.get_mcp_config("user1")
        assert result == {"servers": {}}
        assert "mcp:user1" in provider._cache

    async def test_get_mcp_config_from_cache(self):
        provider = RemoteConfigProvider(api_base_url="http://x.com")
        provider._fetch_config = AsyncMock(return_value={"servers": {}})
        await provider.get_mcp_config("user1")
        provider._fetch_config.reset_mock()
        result = await provider.get_mcp_config("user1")
        assert result == {"servers": {}}
        provider._fetch_config.assert_not_called()

    async def test_get_all_devices_config_fetch_success(self):
        provider = RemoteConfigProvider(api_base_url="http://x.com")
        provider._fetch_config = AsyncMock(return_value={"devices": []})
        result = await provider.get_all_devices_config()
        assert result == {"devices": []}
        assert "all_devices" in provider._cache

    async def test_get_all_devices_config_from_cache(self):
        provider = RemoteConfigProvider(api_base_url="http://x.com")
        provider._fetch_config = AsyncMock(return_value={"devices": []})
        await provider.get_all_devices_config()
        provider._fetch_config.reset_mock()
        result = await provider.get_all_devices_config()
        assert result == {"devices": []}
        provider._fetch_config.assert_not_called()


# ════════════════════════════════════════════════════════════════
# report_device_status 测试
# ════════════════════════════════════════════════════════════════

class TestReportStatus:
    """上报设备状态测试"""

    async def test_report_success(self):
        provider = RemoteConfigProvider(api_base_url="http://x.com")
        provider._post_data = AsyncMock(return_value=True)
        result = await provider.report_device_status("dev1", "online", metadata={"ip": "1.2.3.4"})
        assert result is True
        provider._post_data.assert_called_once()

    async def test_report_with_metadata_none(self):
        provider = RemoteConfigProvider(api_base_url="http://x.com")
        provider._post_data = AsyncMock(return_value=True)
        result = await provider.report_device_status("dev1", "offline")
        assert result is True

    async def test_report_failure(self):
        provider = RemoteConfigProvider(api_base_url="http://x.com")
        provider._post_data = AsyncMock(return_value=False)
        result = await provider.report_device_status("dev1", "error")
        assert result is False

    async def test_report_exception(self):
        provider = RemoteConfigProvider(api_base_url="http://x.com")
        provider._post_data = AsyncMock(side_effect=RuntimeError("boom"))
        result = await provider.report_device_status("dev1", "online")
        assert result is False


# ════════════════════════════════════════════════════════════════
# _fetch_config 测试（mock aiohttp / httpx）
# ════════════════════════════════════════════════════════════════

class TestFetchConfig:
    """_fetch_config HTTP 请求测试"""

    async def test_fetch_config_aiohttp_200(self):
        """aiohttp 返回 200"""
        provider = RemoteConfigProvider(api_base_url="http://x.com", api_key="key")

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"ok": True})

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.get = MagicMock(return_value=mock_response)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await provider._fetch_config("http://x.com/api")
        assert result == {"ok": True}

    async def test_fetch_config_aiohttp_404(self):
        """aiohttp 返回 404 -> None"""
        provider = RemoteConfigProvider(api_base_url="http://x.com")

        mock_response = AsyncMock()
        mock_response.status = 404

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.get = MagicMock(return_value=mock_response)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await provider._fetch_config("http://x.com/api")
        assert result is None

    async def test_fetch_config_aiohttp_500(self):
        """aiohttp 返回 500 -> None"""
        provider = RemoteConfigProvider(api_base_url="http://x.com")

        mock_response = AsyncMock()
        mock_response.status = 500

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.get = MagicMock(return_value=mock_response)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await provider._fetch_config("http://x.com/api")
        assert result is None

    async def test_fetch_config_aiohttp_exception(self):
        """aiohttp 请求异常 -> None"""
        provider = RemoteConfigProvider(api_base_url="http://x.com")
        with patch("aiohttp.ClientSession", side_effect=RuntimeError("conn failed")):
            result = await provider._fetch_config("http://x.com/api")
        assert result is None

    async def test_fetch_config_aiohttp_import_error_fallback_httpx(self):
        """aiohttp 不可用时回退到 httpx"""
        provider = RemoteConfigProvider(api_base_url="http://x.com", api_key="key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"ok": True})

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        # 让 import aiohttp 抛 ImportError
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "aiohttp":
                raise ImportError("no aiohttp")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await provider._fetch_config("http://x.com/api")
        assert result == {"ok": True}

    async def test_fetch_config_no_http_libraries(self):
        """既无 aiohttp 也无 httpx -> None"""
        provider = RemoteConfigProvider(api_base_url="http://x.com")

        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name in ("aiohttp", "httpx"):
                raise ImportError("no lib")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            result = await provider._fetch_config("http://x.com/api")
        assert result is None


# ════════════════════════════════════════════════════════════════
# _post_data 测试
# ════════════════════════════════════════════════════════════════

class TestPostData:
    """_post_data HTTP POST 测试"""

    async def test_post_data_aiohttp_success(self):
        provider = RemoteConfigProvider(api_base_url="http://x.com", api_key="key")
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.post = MagicMock(return_value=mock_response)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await provider._post_data("http://x.com/api", {"a": 1})
        assert result is True

    async def test_post_data_aiohttp_201(self):
        provider = RemoteConfigProvider(api_base_url="http://x.com")
        mock_response = AsyncMock()
        mock_response.status = 201
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.post = MagicMock(return_value=mock_response)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await provider._post_data("http://x.com/api", {"a": 1})
        assert result is True

    async def test_post_data_aiohttp_400(self):
        provider = RemoteConfigProvider(api_base_url="http://x.com")
        mock_response = AsyncMock()
        mock_response.status = 400
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.post = MagicMock(return_value=mock_response)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await provider._post_data("http://x.com/api", {"a": 1})
        assert result is False

    async def test_post_data_aiohttp_exception(self):
        provider = RemoteConfigProvider(api_base_url="http://x.com")
        with patch("aiohttp.ClientSession", side_effect=RuntimeError("conn failed")):
            result = await provider._post_data("http://x.com/api", {"a": 1})
        assert result is False

    async def test_post_data_fallback_httpx_success(self):
        provider = RemoteConfigProvider(api_base_url="http://x.com", api_key="key")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "aiohttp":
                raise ImportError("no aiohttp")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await provider._post_data("http://x.com/api", {"a": 1})
        assert result is True

    async def test_post_data_no_libraries(self):
        provider = RemoteConfigProvider(api_base_url="http://x.com")

        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name in ("aiohttp", "httpx"):
                raise ImportError("no lib")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            result = await provider._post_data("http://x.com/api", {"a": 1})
        assert result is False


# ════════════════════════════════════════════════════════════════
# 后台刷新与缓存清理测试
# ════════════════════════════════════════════════════════════════

class TestBackgroundRefresh:
    """后台刷新与缓存管理测试"""

    async def test_clear_cache(self):
        """clear_cache 应清空缓存"""
        provider = RemoteConfigProvider(api_base_url="http://x.com")
        provider._cache["device:dev1"] = RemoteConfig(
            device_key="dev1", config={"a": 1}, fetched_at=time.time(),
        )
        assert len(provider._cache) == 1
        await provider.clear_cache()
        assert len(provider._cache) == 0

    async def test_refresh_all_removes_expired(self):
        """_refresh_all 应移除过期缓存"""
        provider = RemoteConfigProvider(api_base_url="http://x.com")
        provider._cache["device:dev1"] = RemoteConfig(
            device_key="dev1", config={"a": 1}, fetched_at=0, ttl=1,
        )
        provider._cache["device:dev2"] = RemoteConfig(
            device_key="dev2", config={"b": 2}, fetched_at=time.time(), ttl=300,
        )
        await provider._refresh_all()
        assert "device:dev1" not in provider._cache
        assert "device:dev2" in provider._cache

    async def test_refresh_all_no_expired(self):
        """_refresh_all 无过期项时不改变缓存"""
        provider = RemoteConfigProvider(api_base_url="http://x.com")
        provider._cache["device:dev1"] = RemoteConfig(
            device_key="dev1", config={"a": 1}, fetched_at=time.time(), ttl=300,
        )
        await provider._refresh_all()
        assert len(provider._cache) == 1

    async def test_start_background_refresh_creates_task(self):
        """start_background_refresh 应创建后台任务"""
        provider = RemoteConfigProvider(api_base_url="http://x.com", refresh_interval=1)
        await provider.start_background_refresh()
        assert provider._refresh_task is not None
        assert not provider._refresh_task.done()
        # 取消任务避免泄漏
        provider._refresh_task.cancel()
        try:
            await provider._refresh_task
        except asyncio.CancelledError:
            pass

    async def test_start_background_refresh_already_running(self):
        """已有运行中的任务时不重复创建"""
        provider = RemoteConfigProvider(api_base_url="http://x.com", refresh_interval=1)
        await provider.start_background_refresh()
        task1 = provider._refresh_task
        await provider.start_background_refresh()
        assert provider._refresh_task is task1
        task1.cancel()
        try:
            await task1
        except asyncio.CancelledError:
            pass

    async def test_refresh_loop_handles_exception(self):
        """_refresh_loop 中 _refresh_all 异常不应中断循环"""
        provider = RemoteConfigProvider(api_base_url="http://x.com", refresh_interval=0.05)
        call_count = 0

        async def failing_refresh():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("refresh failed")

        provider._refresh_all = failing_refresh
        task = asyncio.create_task(provider._refresh_loop())
        await asyncio.sleep(0.15)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert call_count >= 1

    async def test_refresh_loop_cancelled(self):
        """_refresh_loop 被 cancel 时应正常退出"""
        provider = RemoteConfigProvider(api_base_url="http://x.com", refresh_interval=10)
        task = asyncio.create_task(provider._refresh_loop())
        await asyncio.sleep(0.01)
        task.cancel()
        # 不应抛异常
        try:
            await task
        except asyncio.CancelledError:
            pass


# ════════════════════════════════════════════════════════════════
# 全局单例函数测试
# ════════════════════════════════════════════════════════════════

class TestGlobalProvider:
    """get_remote_config_provider / init_remote_config_provider 测试"""

    def setup_method(self):
        """每个测试前重置全局单例"""
        import src.infrastructure.remote_config as rc_mod
        rc_mod._remote_config_provider = None

    def teardown_method(self):
        import src.infrastructure.remote_config as rc_mod
        rc_mod._remote_config_provider = None

    def test_get_remote_config_provider_creates_singleton(self):
        """get_remote_config_provider 应创建单例"""
        provider = get_remote_config_provider()
        assert provider is not None
        assert isinstance(provider, RemoteConfigProvider)

    def test_get_remote_config_provider_returns_same(self):
        """多次调用返回同一实例"""
        p1 = get_remote_config_provider()
        p2 = get_remote_config_provider()
        assert p1 is p2

    def test_init_remote_config_provider(self):
        """init_remote_config_provider 应创建配置好的实例"""
        provider = init_remote_config_provider(
            api_base_url="http://init.url",
            api_key="init_key",
            cache_ttl=600,
            refresh_interval=120,
        )
        assert provider.api_base_url == "http://init.url"
        assert provider.api_key == "init_key"
        assert provider.cache_ttl == 600
        assert provider.refresh_interval == 120
        assert provider.is_enabled is True

    def test_get_after_init_returns_init_instance(self):
        """init 后 get 应返回 init 的实例"""
        provider = init_remote_config_provider(api_base_url="http://init.url")
        assert get_remote_config_provider() is provider

    def test_get_provider_reads_settings(self):
        """get_remote_config_provider 从 settings 读取配置"""
        mock_settings = MagicMock()
        mock_settings.remote_config_url = "http://from-settings.com"
        mock_settings.remote_config_api_key = "settings-key"
        with patch("src.infrastructure.config.get_settings", return_value=mock_settings):
            provider = get_remote_config_provider()
        assert provider.api_base_url == "http://from-settings.com"
        assert provider.api_key == "settings-key"
