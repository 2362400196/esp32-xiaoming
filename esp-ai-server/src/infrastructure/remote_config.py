"""
RemoteConfigProvider - 远程配置提供者

从管理后台 HTTP API 拉取设备/用户配置

使用方式：
1. 配置管理后台 URL
2. 设备连接时自动拉取配置
3. 支持缓存和定时刷新
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, Optional
from dataclasses import dataclass

from src.infrastructure.logging import get_logger, warning, error, debug

logger = get_logger(__name__)


@dataclass
class RemoteConfig:
    """远程配置数据"""
    device_key: str
    config: Dict[str, Any]
    fetched_at: float
    ttl: int = 300


class RemoteConfigProvider:
    """
    远程配置提供者

    从管理后台 API 拉取配置，支持：
    - 设备级别配置
    - 用户级别配置
    - MCP 服务器配置
    - 缓存和 TTL
    - 定时刷新
    """

    def __init__(
        self,
        api_base_url: str = "",
        api_key: str = "",
        cache_ttl: int = 300,
        refresh_interval: int = 60,
        timeout: float = 10.0,
    ):
        self.api_base_url = api_base_url.rstrip("/")
        self.api_key = api_key
        self.cache_ttl = cache_ttl
        self.refresh_interval = refresh_interval
        self.timeout = timeout

        self._cache: Dict[str, RemoteConfig] = {}
        self._lock = asyncio.Lock()
        self._refresh_task: Optional[asyncio.Task] = None
        self._enabled = bool(api_base_url)

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def get_device_config(self, device_key: str) -> Optional[Dict[str, Any]]:
        """
        获取设备配置

        Args:
            device_key: 设备密钥

        Returns:
            设备配置字典，如果不存在则返回 None
        """
        if not self.is_enabled:
            return None

        cache_key = f"device:{device_key}"

        cached = self._cache.get(cache_key)
        if cached and time.time() - cached.fetched_at < cached.ttl:
            debug(f"[RemoteConfig] 使用缓存配置: {device_key}")
            return cached.config

        try:
            config = await self._fetch_config(f"{self.api_base_url}/api/v1/devices/{device_key}/config")
            if config:
                self._cache[cache_key] = RemoteConfig(
                    device_key=device_key,
                    config=config,
                    fetched_at=time.time(),
                    ttl=self.cache_ttl,
                )
                logger.info(f"[RemoteConfig] 已获取设备配置: {device_key}")
                return config
        except Exception as e:
            error(f"[RemoteConfig] 获取设备配置失败: {e}")

        if cached:
            warning(f"[RemoteConfig] 使用过期缓存: {device_key}")
            return cached.config

        return None

    async def get_user_config(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        获取用户配置

        Args:
            user_id: 用户ID

        Returns:
            用户配置字典，如果不存在则返回 None
        """
        if not self.is_enabled:
            return None

        cache_key = f"user:{user_id}"

        cached = self._cache.get(cache_key)
        if cached and time.time() - cached.fetched_at < cached.ttl:
            debug(f"[RemoteConfig] 使用缓存配置: {user_id}")
            return cached.config

        try:
            config = await self._fetch_config(f"{self.api_base_url}/api/v1/users/{user_id}/config")
            if config:
                self._cache[cache_key] = RemoteConfig(
                    device_key=user_id,
                    config=config,
                    fetched_at=time.time(),
                    ttl=self.cache_ttl,
                )
                logger.info(f"[RemoteConfig] 已获取用户配置: {user_id}")
                return config
        except Exception as e:
            error(f"[RemoteConfig] 获取用户配置失败: {e}")

        if cached:
            warning(f"[RemoteConfig] 使用过期缓存: {user_id}")
            return cached.config

        return None

    async def get_mcp_config(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        获取 MCP 服务器配置

        Args:
            user_id: 用户ID

        Returns:
            MCP 配置字典
        """
        if not self.is_enabled:
            return None

        cache_key = f"mcp:{user_id}"

        cached = self._cache.get(cache_key)
        if cached and time.time() - cached.fetched_at < cached.ttl:
            debug(f"[RemoteConfig] 使用缓存 MCP 配置: {user_id}")
            return cached.config

        try:
            config = await self._fetch_config(f"{self.api_base_url}/api/v1/users/{user_id}/mcp")
            if config:
                self._cache[cache_key] = RemoteConfig(
                    device_key=user_id,
                    config=config,
                    fetched_at=time.time(),
                    ttl=self.cache_ttl,
                )
                logger.info(f"[RemoteConfig] 已获取 MCP 配置: {user_id}")
                return config
        except Exception as e:
            error(f"[RemoteConfig] 获取 MCP 配置失败: {e}")

        if cached:
            warning(f"[RemoteConfig] 使用过期 MCP 缓存: {user_id}")
            return cached.config

        return None

    async def get_all_devices_config(self) -> Optional[Dict[str, Any]]:
        """
        获取所有设备配置列表（用于管理后台推送模式）

        Returns:
            所有设备配置字典
        """
        if not self.is_enabled:
            return None

        cache_key = "all_devices"

        cached = self._cache.get(cache_key)
        if cached and time.time() - cached.fetched_at < cached.ttl:
            debug("[RemoteConfig] 使用缓存的所有设备配置")
            return cached.config

        try:
            config = await self._fetch_config(f"{self.api_base_url}/api/v1/devices")
            if config:
                self._cache[cache_key] = RemoteConfig(
                    device_key="all",
                    config=config,
                    fetched_at=time.time(),
                    ttl=self.cache_ttl,
                )
                logger.info("[RemoteConfig] 已获取所有设备配置")
                return config
        except Exception as e:
            error(f"[RemoteConfig] 获取所有设备配置失败: {e}")

        if cached:
            warning("[RemoteConfig] 使用过期缓存")
            return cached.config

        return None

    async def report_device_status(
        self,
        device_key: str,
        status: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        上报设备状态到管理后台

        Args:
            device_key: 设备密钥
            status: 状态 (online/offline/error)
            metadata: 额外元数据

        Returns:
            是否成功
        """
        if not self.is_enabled:
            return False

        try:
            payload = {
                "device_key": device_key,
                "status": status,
                "timestamp": time.time(),
                "metadata": metadata or {},
            }
            success = await self._post_data(
                f"{self.api_base_url}/api/v1/devices/{device_key}/status",
                payload,
            )
            if success:
                debug(f"[RemoteConfig] 已上报设备状态: {device_key} -> {status}")
            return success
        except Exception as e:
            error(f"[RemoteConfig] 上报设备状态失败: {e}")
            return False

    async def _fetch_config(self, url: str) -> Optional[Dict[str, Any]]:
        """从远程 API 获取配置"""
        try:
            import aiohttp

            headers = {
                "Content-Type": "application/json",
            }
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 404:
                        debug(f"[RemoteConfig] 配置不存在: {url}")
                        return None
                    else:
                        error(f"[RemoteConfig] HTTP {response.status}: {url}")
                        return None

        except ImportError:
            warning("[RemoteConfig] aiohttp 未安装，使用 httpx")
            try:
                import httpx
                headers = {"Content-Type": "application/json"}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"

                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        url,
                        headers=headers,
                        timeout=self.timeout,
                    )
                    if response.status_code == 200:
                        return response.json()
            except ImportError:
                error("[RemoteConfig] 缺少 HTTP 客户端库 (aiohttp 或 httpx)")
                return None
            except Exception as e:
                error(f"[RemoteConfig] HTTP 请求失败: {e}")
                return None
        except Exception as e:
            error(f"[RemoteConfig] 获取配置异常: {e}")
            return None

    async def _post_data(self, url: str, data: Dict[str, Any]) -> bool:
        """POST 数据到远程 API"""
        try:
            import aiohttp

            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=data,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as response:
                    return response.status in (200, 201, 204)

        except ImportError:
            try:
                import httpx
                headers = {"Content-Type": "application/json"}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"

                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        url,
                        json=data,
                        headers=headers,
                        timeout=self.timeout,
                    )
                    return response.status_code in (200, 201, 204)
            except ImportError:
                return False
            except Exception as e:
                error(f"[RemoteConfig] POST 失败: {e}")
                return False
        except Exception as e:
            error(f"[RemoteConfig] POST 异常: {e}")
            return False

    async def start_background_refresh(self):
        """启动后台定时刷新任务"""
        if not self.is_enabled:
            return

        if self._refresh_task and not self._refresh_task.done():
            return

        self._refresh_task = asyncio.create_task(self._refresh_loop())
        logger.info("[RemoteConfig] 后台刷新任务已启动")

    async def _refresh_loop(self):
        """后台刷新循环"""
        while True:
            try:
                await asyncio.sleep(self.refresh_interval)
                await self._refresh_all()
            except asyncio.CancelledError:
                break
            except Exception as e:
                error(f"[RemoteConfig] 刷新循环异常: {e}")

    async def _refresh_all(self):
        """刷新所有缓存的配置"""
        async with self._lock:
            now = time.time()
            expired_keys = [
                key for key, config in self._cache.items()
                if now - config.fetched_at >= config.ttl
            ]

            for key in expired_keys:
                del self._cache[key]

            if expired_keys:
                debug(f"[RemoteConfig] 已清理 {len(expired_keys)} 个过期缓存")

    async def clear_cache(self):
        """清空所有缓存"""
        async with self._lock:
            self._cache.clear()
        logger.info("[RemoteConfig] 缓存已清空")

    def update_config(self, api_base_url: str = None, api_key: str = None):
        """更新配置"""
        if api_base_url is not None:
            self.api_base_url = api_base_url.rstrip("/")
        if api_key is not None:
            self.api_key = api_key
        self._enabled = bool(self.api_base_url)


_remote_config_provider: Optional[RemoteConfigProvider] = None


def get_remote_config_provider() -> RemoteConfigProvider:
    """获取全局远程配置提供者实例"""
    global _remote_config_provider
    if _remote_config_provider is None:
        from src.infrastructure.config import get_settings
        settings = get_settings()

        remote_url = getattr(settings, "remote_config_url", "")
        remote_api_key = getattr(settings, "remote_config_api_key", "")

        _remote_config_provider = RemoteConfigProvider(
            api_base_url=remote_url,
            api_key=remote_api_key,
        )

    return _remote_config_provider


def init_remote_config_provider(
    api_base_url: str,
    api_key: str = "",
    cache_ttl: int = 300,
    refresh_interval: int = 60,
) -> RemoteConfigProvider:
    """初始化远程配置提供者"""
    global _remote_config_provider
    _remote_config_provider = RemoteConfigProvider(
        api_base_url=api_base_url,
        api_key=api_key,
        cache_ttl=cache_ttl,
        refresh_interval=refresh_interval,
    )
    return _remote_config_provider


__all__ = [
    "RemoteConfigProvider",
    "RemoteConfig",
    "get_remote_config_provider",
    "init_remote_config_provider",
]
