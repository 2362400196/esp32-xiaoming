from __future__ import annotations

import asyncio
import inspect
import importlib
import json
import os
import pkgutil
import sys
import time
from enum import Enum
from pathlib import Path
import typing
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from src.infrastructure.logging import get_logger

# 从独立模块导入 StopPipeline 和 ToolCache（保持向后兼容，重新导出）
from src.use_cases.stop_pipeline import StopPipeline  # noqa: F401
from src.use_cases.tool_cache import ToolCache  # noqa: F401

logger = get_logger(__name__)


class ToolDefinition:
    def __init__(self, name: str, description: str, func: Callable, parameters: dict,
                 cache: bool = True, builtin: bool = False):
        self.name = name
        self.description = description
        self.func = func
        self.parameters = parameters
        self.cache = cache  # 结果缓存开关：False 时每次调用都执行函数（如含屏幕显示的查询工具）
        self.builtin = builtin  # True=系统/内置工具（插件不可覆盖）；False=插件工具

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


_registry: dict[str, ToolDefinition] = {}

# 系统/内置工具名集合（auto_discover 发现的系统工具 + 通过 builtin=True 注册的工具）。
# 插件注册的工具（builtin=False）永远不能覆盖这些核心工具。
_builtin_tool_names: set[str] = set()


def _is_plugin_module_path(module_file: str | None) -> bool:
    """判断工具定义所在的模块是否属于插件目录（src/plugins 或 data/plugins）。

    用于在工具注册时区分系统工具与插件工具（插件工具不允许覆盖系统工具）。
    """
    if not module_file:
        return False
    try:
        parts = Path(module_file).resolve().parts
    except (OSError, ValueError):
        return False
    for i, part in enumerate(parts):
        if part == "plugins" and i >= 1 and parts[i - 1] in ("src", "installed"):
            return True
        if part == "plugins" and i >= 1 and parts[i - 1] == "data":
            return True
    return False


def tool(name: str | None = None, description: str | None = None, cache: bool = True):
    """工具装饰器。
    Args:
        name: 工具名（默认函数名）
        description: 工具描述（默认 docstring）
        cache: 结果缓存开关。默认 True（相同参数 300 秒内复用结果）；
              含屏幕显示/设备指令等副作用的工具应设 cache=False，
              否则缓存命中会跳过整个函数（如天气卡片不再显示）。
    """
    def decorator(func: Callable):
        tool_name = name or func.__name__
        tool_desc = description or (func.__doc__ or "").strip() or tool_name

        sig = inspect.signature(func)
        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls", "tool_manager", "channel", "ctx", "fsm"):
                continue

            prop = {"type": "string"}

            ann = param.annotation
            if ann is inspect.Parameter.empty:
                pass
            elif ann is int:
                prop["type"] = "integer"
            elif ann is float:
                prop["type"] = "number"
            elif ann is bool:
                prop["type"] = "boolean"
            elif ann is list:
                prop["type"] = "array"
            elif ann is dict:
                prop["type"] = "object"

            if param.default is inspect.Parameter.empty:
                required.append(param_name)
            else:
                prop["default"] = param.default

            properties[param_name] = prop

        parameters_schema = {
            "type": "object",
            "properties": properties,
        }
        if required:
            parameters_schema["required"] = required

        # 判断来源：系统工具 vs 插件工具（插件工具不允许覆盖系统工具）
        module_file = None
        try:
            module = sys.modules.get(func.__module__)
            module_file = getattr(module, "__file__", None)
        except Exception:
            module_file = None
        # plugin_loader 以合成模块名（esp_ai_plugins_*）加载内置插件，
        # 模块名即身份：无法从 sys.modules 解析路径时按模块名兜底判定
        is_builtin = (
            not _is_plugin_module_path(module_file)
            and not (func.__module__ or "").startswith("esp_ai_plugins_")
        )

        definition = ToolDefinition(
            name=tool_name,
            description=tool_desc,
            func=func,
            parameters=parameters_schema,
            cache=cache,
            builtin=is_builtin,
        )
        _register(definition)
        return func

    return decorator


def _register(td: ToolDefinition) -> None:
    """统一注册入口：维护系统/插件工具集合 + 覆盖保护。"""
    existing = _registry.get(td.name)
    if existing is not None and existing.builtin and not td.builtin:
        raise ValueError(
            f"工具 {td.name} 是系统/内置工具，插件不允许覆盖"
        )
    _registry[td.name] = td
    if td.builtin:
        _builtin_tool_names.add(td.name)
    else:
        _builtin_tool_names.discard(td.name)


def register_tool(td: ToolDefinition) -> None:
    """注册一个已构造好的 ToolDefinition（热加载回滚时恢复旧工具）。"""
    if not isinstance(td, ToolDefinition):
        raise TypeError("register_tool 需要 ToolDefinition 实例")
    _register(td)


def get_all_tools() -> dict[str, ToolDefinition]:
    return dict(_registry)


def unregister_tool(name: str) -> bool:
    """注销工具（插件热加载/卸载时使用）。返回是否成功移除。"""
    if name in _registry:
        _builtin_tool_names.discard(name)
        del _registry[name]
        return True
    return False


def is_builtin_tool(name: str) -> bool:
    """判断工具是否为系统/内置工具（插件不得覆盖）。"""
    return name in _builtin_tool_names


def get_openai_tools_schema() -> list[dict]:
    return [t.to_openai_schema() for t in _registry.values()]


def get_tool(name: str) -> ToolDefinition | None:
    return _registry.get(name)


_disabled_global: set[str] = set()


def get_disabled_tools() -> set[str]:
    return set(_disabled_global)


def set_disabled_tools(tools: set[str]) -> None:
    _disabled_global.clear()
    _disabled_global.update(tools)


def disable_tool(name: str) -> None:
    _disabled_global.add(name)


def enable_tool(name: str) -> None:
    _disabled_global.discard(name)


def auto_discover():
    _SKIP_MODULES = {
        "__init__", "pipeline", "session", "session_fsm", "session_management",
        "queues", "voice_generator", "dtos", "ports", "auxiliary_services",
        "tools_system",
    }

    tools_dir = os.path.dirname(__file__)

    discover_count = 0

    def _scan(directory: str, prefix: str, skip: set = None):
        nonlocal discover_count
        _skip = skip or set()
        for _, module_name, _ in pkgutil.iter_modules([directory]):
            if module_name.startswith("_") or module_name in _skip:
                continue
            try:
                importlib.import_module(f"{prefix}.{module_name}")
                discover_count += 1
            except Exception as e:
                logger.error(f"[Tools] 加载工具模块 {module_name} 失败: {e}")

    _scan(tools_dir, "src.use_cases", skip=_SKIP_MODULES)
    custom_dir = os.path.join(tools_dir, "custom")
    if os.path.isdir(custom_dir):
        _scan(custom_dir, "src.use_cases.custom")

    tool_count = len(_registry)
    if tool_count > 0:
        logger.info(f"[Tools] 已自动发现 {tool_count} 个工具: {list(_registry.keys())}")
    else:
        logger.info("[Tools] 未发现任何工具")


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


def _state_to_number(state: CircuitState) -> int:
    if state == CircuitState.CLOSED:
        return 0
    elif state == CircuitState.HALF_OPEN:
        return 1
    else:
        return 2


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        half_open_max_calls: int = 3,
        expected_exceptions: tuple = (Exception,),
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.expected_exceptions = expected_exceptions

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_calls = 0
        self._lock = asyncio.Lock()

        self._stats = {
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
            "rejected_calls": 0,
            "state_changes": 0,
        }

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def is_closed(self) -> bool:
        return self._state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        return self._state == CircuitState.OPEN

    @property
    def is_half_open(self) -> bool:
        return self._state == CircuitState.HALF_OPEN

    async def _can_execute(self) -> bool:
        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.OPEN:
            if self._last_failure_time and time.time() - self._last_failure_time >= self.recovery_timeout:
                await self._transition_to_half_open()
                return True
            return False

        if self._state == CircuitState.HALF_OPEN:
            if self._half_open_calls < self.half_open_max_calls:
                return True
            return False

        return False

    async def _transition_to_half_open(self):
        async with self._lock:
            if self._state != CircuitState.OPEN:
                return
            self._state = CircuitState.HALF_OPEN
            self._half_open_calls = 0
            self._stats["state_changes"] += 1
            logger.info(f"[CircuitBreaker] {self.name} OPEN -> HALF_OPEN (恢复超时已过)")

    async def _record_success(self):
        async with self._lock:
            self._stats["successful_calls"] += 1

            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.half_open_max_calls:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    self._half_open_calls = 0
                    self._stats["state_changes"] += 1
                    logger.info(f"[CircuitBreaker] {self.name} HALF_OPEN -> CLOSED (恢复成功)")

    async def _record_failure(self):
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            self._stats["failed_calls"] += 1

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._success_count = 0
                self._half_open_calls = 0
                self._stats["state_changes"] += 1
                logger.error(f"[CircuitBreaker] {self.name} HALF_OPEN -> OPEN (试探失败)")
                return

            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._stats["state_changes"] += 1
                logger.error(f"[CircuitBreaker] {self.name} CLOSED -> OPEN (失败次数: {self._failure_count})")

    async def call(
        self,
        func: Callable,
        *args,
        fallback: Optional[Callable] = None,
        **kwargs,
    ) -> Any:
        self._stats["total_calls"] += 1

        if not await self._can_execute():
            self._stats["rejected_calls"] += 1
            if self._state == CircuitState.OPEN:
                logger.warning(f"[CircuitBreaker] {self.name} OPEN，拒绝调用")
            if fallback:
                try:
                    if asyncio.iscoroutinefunction(fallback):
                        return await fallback(*args, **kwargs)
                    return fallback(*args, **kwargs)
                except Exception as e:
                    logger.error(f"[CircuitBreaker] {self.name} fallback 执行失败: {e}")
            return None

        if self._state == CircuitState.HALF_OPEN:
            async with self._lock:
                self._half_open_calls += 1

        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            await self._record_success()
            return result

        except self.expected_exceptions as e:
            await self._record_failure()
            if fallback:
                try:
                    if asyncio.iscoroutinefunction(fallback):
                        return await fallback(*args, **kwargs)
                    return fallback(*args, **kwargs)
                except Exception as fallback_error:
                    logger.error(f"[CircuitBreaker] {self.name} fallback 执行失败: {fallback_error}")
            return None

        except Exception as e:
            await self._record_failure()
            logger.error(f"[CircuitBreaker] {self.name} 非预期异常: {e}")
            if fallback:
                try:
                    if asyncio.iscoroutinefunction(fallback):
                        return await fallback(*args, **kwargs)
                    return fallback(*args, **kwargs)
                except Exception as e:
                    logger.debug(f"[CircuitBreaker] {self.name} fallback 异常被忽略: {e}")
            return None

    async def reset(self):
        async with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
            self._last_failure_time = None
            self._stats["state_changes"] += 1
            logger.info(f"[CircuitBreaker] {self.name} 已重置")

    def get_stats(self) -> dict:
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "stats": dict(self._stats),
        }


class CircuitBreakerManager:
    _instance: Optional["CircuitBreakerManager"] = None
    _breakers: dict[str, CircuitBreaker] = {}
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    async def get_breaker(
        cls,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        half_open_max_calls: int = 3,
    ) -> CircuitBreaker:
        async with cls._lock:
            if name not in cls._breakers:
                cls._breakers[name] = CircuitBreaker(
                    name=name,
                    failure_threshold=failure_threshold,
                    recovery_timeout=recovery_timeout,
                    half_open_max_calls=half_open_max_calls,
                )
                logger.info(f"[CircuitBreakerManager] 创建熔断器: {name}")
            return cls._breakers[name]

    @classmethod
    async def get_all_stats(cls) -> dict:
        return {
            name: breaker.get_stats()
            for name, breaker in cls._breakers.items()
        }

    @classmethod
    async def reset_all(cls):
        async with cls._lock:
            for breaker in cls._breakers.values():
                await breaker.reset()
            logger.info("[CircuitBreakerManager] 所有熔断器已重置")

    @classmethod
    async def remove_breaker(cls, name: str):
        async with cls._lock:
            if name in cls._breakers:
                del cls._breakers[name]
                logger.info(f"[CircuitBreakerManager] 移除熔断器: {name}")


class MCPClient:
    def __init__(
        self,
        server_url: str,
        name: str = "",
        headers: dict[str, str] | None = None,
        auth: str | None = None,
    ):
        self.server_url = server_url
        self.name = name or server_url
        self.headers = headers
        self.auth = auth
        self._client = None
        self._tools_cache: list[dict] = []
        self._connected = False

    async def connect(self) -> bool:
        try:
            from fastmcp import Client
            from fastmcp.client.transports import StreamableHttpTransport
        except ImportError:
            logger.error("[MCP Client] fastmcp 包未安装，请运行: uv add fastmcp")
            return False

        try:
            if self.headers or self.auth:
                transport = StreamableHttpTransport(
                    url=self.server_url,
                    headers=self.headers,
                    auth=self.auth,
                )
                self._client = Client(transport)
            else:
                self._client = Client(self.server_url)

            # 添加 10 秒连接超时，避免 MCP 服务器不可达时长时间阻塞
            await asyncio.wait_for(self._client.__aenter__(), timeout=10.0)
            self._connected = True

            await self._refresh_tools()
            logger.info(f"[MCP Client] 已连接 {self.name}，发现 {len(self._tools_cache)} 个工具")
            return True
        except asyncio.TimeoutError:
            logger.warning(f"[MCP Client] 连接 {self.name} 超时（10s），URL: {self.server_url}")
            await self.disconnect()
            return False
        except Exception as e:
            logger.error(f"[MCP Client] 连接 {self.name} 失败: {e}")
            await self.disconnect()
            return False

    async def _refresh_tools(self):
        if not self._client:
            return
        try:
            # 添加 10 秒超时，防止 list_tools() 无限等待
            result = await asyncio.wait_for(self._client.list_tools(), timeout=10.0)
            self._tools_cache = []
            tools = result if isinstance(result, list) else result.tools
            for t in tools:
                schema = {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description or "",
                        "parameters": t.inputSchema or {"type": "object", "properties": {}},
                    },
                }
                self._tools_cache.append(schema)
        except asyncio.TimeoutError:
            logger.warning(f"[MCP Client] 获取 {self.name} 工具列表超时（10s）")
        except Exception as e:
            logger.error(f"[MCP Client] 获取工具列表失败: {e}")

    def get_tools_schema(self) -> list[dict]:
        return list(self._tools_cache)

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        if not self._client or not self._connected:
            logger.info(f"[MCP Client] {self.name} 未连接，尝试连接...")
            success = await self.connect()
            if not success:
                return f"错误: MCP Server {self.name} 连接失败"

        import time as _time
        _start = _time.time()
        logger.info(f"[MCP Client] {self.name} 调用工具 {tool_name} 参数={arguments}")

        try:
            # 内部超时 14 秒（比外层 15s 稍短，留 1s 余量给重连逻辑）
            result = await asyncio.wait_for(
                self._client.call_tool(tool_name, arguments),
                timeout=14.0
            )
            _elapsed = _time.time() - _start
            logger.info(f"[MCP Client] {self.name} 工具 {tool_name} 返回 ({_elapsed:.1f}s)")

            is_error = getattr(result, "is_error", getattr(result, "isError", False))

            if is_error:
                error_texts = []
                for c in result.content:
                    if hasattr(c, "text"):
                        error_texts.append(c.text)
                return f"工具执行失败: {'; '.join(error_texts)}"

            texts = []
            for c in result.content:
                if hasattr(c, "text"):
                    texts.append(c.text)
            return "\n".join(texts) if texts else "工具执行成功，无文本输出"
        except asyncio.TimeoutError:
            _elapsed = _time.time() - _start
            logger.error(f"[MCP Client] {self.name} 工具 {tool_name} 内部超时 ({_elapsed:.1f}s)")
            # 超时后连接可能已失效，主动断开
            await self.disconnect()
            return f"工具 {tool_name} 调用超时 ({_elapsed:.0f}s)"
        except Exception as e:
            _elapsed = _time.time() - _start
            error_msg = str(e)
            if "not connected" in error_msg.lower():
                logger.info(f"[MCP Client] {self.name} 连接已断开，尝试重连... ({_elapsed:.1f}s)")
                await self.disconnect()
                success = await self.connect()
                if success:
                    try:
                        result = await asyncio.wait_for(
                            self._client.call_tool(tool_name, arguments),
                            timeout=14.0
                        )
                        _elapsed2 = _time.time() - _start
                        logger.info(f"[MCP Client] {self.name} 重连后工具 {tool_name} 返回 ({_elapsed2:.1f}s)")
                        is_error = getattr(result, "is_error", getattr(result, "isError", False))
                        if is_error:
                            error_texts = [c.text for c in result.content if hasattr(c, "text")]
                            return f"工具执行失败: {'; '.join(error_texts)}"
                        texts = [c.text for c in result.content if hasattr(c, "text")]
                        return "\n".join(texts) if texts else "工具执行成功，无文本输出"
                    except asyncio.TimeoutError:
                        _elapsed2 = _time.time() - _start
                        logger.error(f"[MCP Client] {self.name} 重连后工具 {tool_name} 仍超时 ({_elapsed2:.1f}s)")
                        return f"工具 {tool_name} 调用超时"
                    except Exception as e2:
                        logger.error(f"[MCP Client] 重连后调用工具 {tool_name} 仍失败: {e2}")
                        return f"工具调用异常: {e2}"
                return f"MCP Server {self.name} 重连失败"
            logger.error(f"[MCP Client] 调用工具 {tool_name} 异常: {e} ({_elapsed:.1f}s)")
            return f"工具调用异常: {e}"

    async def disconnect(self):
        self._connected = False
        self._tools_cache = []
        if self._client:
            try:
                await self._client.__aexit__(None, None, None)
            except Exception as e:
                logger.debug(f"[MCP Client] 断开 {self.name} 异常: {e}")
        self._client = None
        logger.info(f"[MCP Client] 已断开 {self.name}")

    @property
    def connected(self) -> bool:
        return self._connected

    async def health_check(self) -> bool:
        if not self._client or not self._connected:
            return False
        try:
            await asyncio.wait_for(self._client.list_tools(), timeout=5.0)
            return True
        except Exception:
            self._connected = False
            return False


class MCPPool:
    def __init__(
        self,
        server_url: str,
        server_name: str,
        headers: Optional[dict] = None,
        auth: Optional[dict] = None,
        max_size: int = 5,
        min_size: int = 2,
    ):
        self._server_url = server_url
        self._server_name = server_name
        self._headers = headers
        self._auth = auth
        self._max_size = max_size
        self._min_size = min_size

        self._pool: asyncio.Queue = asyncio.Queue(maxsize=max_size)
        self._active_count = 0
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self):
        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return

            for _ in range(self._min_size):
                if self._active_count >= self._max_size:
                    break
                client = await self._create_client()
                if client:
                    await self._pool.put(client)
                    self._active_count += 1

            self._initialized = True
            logger.info(f"[MCPPool] {self._server_name} 连接池已预热: {self._active_count}/{self._max_size}")

    async def _create_client(self) -> Optional[MCPClient]:
        try:
            client = MCPClient(self._server_url, self._server_name, headers=self._headers, auth=self._auth)
            success = await client.connect()
            if success:
                return client
            await client.disconnect()
            return None
        except Exception as e:
            logger.error(f"[MCPPool] 创建客户端失败 {self._server_name}: {e}")
            return None

    async def acquire(self) -> Optional[MCPClient]:
        async with self._lock:
            if not self._pool.empty():
                try:
                    client = self._pool.get_nowait()
                    if client and client.connected:
                        return client
                    self._active_count -= 1
                except asyncio.QueueEmpty:
                    pass

            if self._active_count < self._max_size:
                client = await self._create_client()
                if client:
                    self._active_count += 1
                    return client

            try:
                return await asyncio.wait_for(self._pool.get(), timeout=30)
            except asyncio.TimeoutError:
                logger.warning(f"[MCPPool] 获取连接超时 {self._server_name}")
                return None

    async def release(self, client: Optional[MCPClient]) -> None:
        if not client:
            return

        async with self._lock:
            if client.connected:
                try:
                    self._pool.put_nowait(client)
                    return
                except asyncio.QueueFull:
                    pass

            await client.disconnect()
            self._active_count -= 1

    async def close(self):
        async with self._lock:
            while not self._pool.empty():
                try:
                    client = self._pool.get_nowait()
                    await client.disconnect()
                except asyncio.QueueEmpty:
                    break
            self._active_count = 0
            self._initialized = False

    def get_stats(self) -> dict:
        return {
            "server": self._server_name,
            "url": self._server_url,
            "active_count": self._active_count,
            "idle_count": self._pool.qsize(),
            "max_size": self._max_size,
        }


class ToolRetriever:
    """工具检索器：根据用户查询语义匹配最相关的 Top-K 个工具，减少 LLM 的选择空间。

    原理：LLM 工具选择准确率随工具数量增长而下降（>12 个后显著退化）。
    本检索器在发给 LLM 之前，用关键词匹配预筛选出最相关的子集。

    匹配策略：
    - 中文：2-3 字滑动窗口 n-gram（无需 jieba 分词）
    - 英文：整词提取
    - 评分：TF 归一化 + 命中绝对数加权
    - 安全降级：匹配不足 3 个或查询为空时回退全部工具
    """

    # 核心工具白名单：无论用户说什么都始终可用（对话必备能力）
    # 注意：execute_lua 属高危工具，不常驻 LLM schema（按意图检索时仍可被选中）
    CORE_TOOLS = frozenset({
        "standby",
        "get_current_time",
        "get_current_date",
        "clear_screen",
        "stop_lua",
    })

    def __init__(self, top_k: int = 12, min_result: int = 3):
        self._top_k = top_k
        self._min_result = min_result
        self._keyword_index: dict[str, set[str]] = {}
        self._index_ready = False

    def update_index(self, schemas: list[dict]) -> None:
        """从 OpenAI 格式的 schema 列表重建关键词索引。"""
        import re

        self._keyword_index.clear()
        for schema in schemas:
            func = schema.get("function", {})
            name = func.get("name", "")
            desc = func.get("description", "")
            if not name:
                continue

            keywords: set[str] = set()

            # 英文单词（2+ 字符），含下划线
            for m in re.finditer(r"[a-zA-Z_]{2,}", desc.lower()):
                keywords.add(m.group())

            # 中文 n-gram：2-3 字滑动窗口
            for segment in re.findall(r"[\u4e00-\u9fff]+", desc):
                if len(segment) <= 3:
                    keywords.add(segment)
                else:
                    for i in range(len(segment) - 1):
                        keywords.add(segment[i : i + 2])
                    for i in range(len(segment) - 2):
                        keywords.add(segment[i : i + 3])

            self._keyword_index[name] = keywords

        self._index_ready = len(self._keyword_index) > 0
        logger.info(
            f"[ToolRetriever] 索引已重建: {len(self._keyword_index)} 个工具, "
            f"核心工具白名单 {len(self.CORE_TOOLS)} 个"
        )

    @staticmethod
    def _extract_query_keywords(text: str) -> set[str]:
        """从用户查询中提取关键词。"""
        import re

        keywords: set[str] = set()

        for m in re.finditer(r"[a-zA-Z_]{2,}", text.lower()):
            keywords.add(m.group())

        for segment in re.findall(r"[\u4e00-\u9fff]+", text):
            if len(segment) <= 3:
                keywords.add(segment)
            else:
                for i in range(len(segment) - 1):
                    keywords.add(segment[i : i + 2])
                for i in range(len(segment) - 2):
                    keywords.add(segment[i : i + 3])

        return keywords

    def retrieve(self, query: str, all_tool_names: set[str]) -> set[str]:
        """根据用户查询检索最相关的工具名集合。

        Returns:
            包含核心工具 + Top-K 匹配工具的集合。
            匹配不足时回退到全部工具（安全降级）。
        """
        if not self._index_ready:
            return all_tool_names

        if not query or not query.strip():
            return all_tool_names

        query_keywords = self._extract_query_keywords(query)
        if not query_keywords:
            return all_tool_names

        # 计算每个工具的匹配分数
        scores: list[tuple[str, float]] = []
        for name in all_tool_names:
            if name in self.CORE_TOOLS:
                scores.append((name, 999.0))
                continue

            tool_kws = self._keyword_index.get(name, set())
            if not tool_kws:
                scores.append((name, 0.0))
                continue

            overlap = query_keywords & tool_kws
            if not overlap:
                scores.append((name, 0.0))
                continue

            # TF 归一化（命中数 / 工具关键词总数）+ 绝对命中数加权
            tf = len(overlap) / max(len(tool_kws), 1)
            score = tf * 2.0 + len(overlap) * 0.3
            scores.append((name, score))

        scores.sort(key=lambda x: x[1], reverse=True)

        # 取分数 > 0 的工具
        matched = [name for name, score in scores if score > 0]

        # 不足 top_k 时补充未匹配工具（避免遗漏）
        if len(matched) < self._top_k:
            for name, _ in scores:
                if name not in matched:
                    matched.append(name)
                    if len(matched) >= self._top_k:
                        break

        result = set(matched[: self._top_k])

        # 始终包含核心工具
        result |= self.CORE_TOOLS & all_tool_names

        # 安全降级：结果太少则回退全部
        if len(result) < self._min_result:
            logger.info(
                f"[ToolRetriever] 匹配结果仅 {len(result)} 个 (< {self._min_result})，回退全部工具"
            )
            return all_tool_names

        logger.info(
            f"[ToolRetriever] 检索完成: {len(all_tool_names)} → {len(result)} "
            f"(query: {query[:40]})"
        )
        return result


class ToolManager:
    def __init__(self):
        self._discovered = False
        self._tools_schema_cache: Optional[list] = None
        self._schema_cache_time = 0
        self._schema_cache_ttl = 3600

    def ensure_discovered(self):
        if self._discovered:
            return
        auto_discover()
        self._discovered = True
        builtin_count = len(get_all_tools())
        logger.info(f"[ToolManager] 内置工具: {builtin_count} 个")

    def get_all_tools_schema(self) -> list:
        now = time.time()
        if self._tools_schema_cache is not None:
            if now - self._schema_cache_time < self._schema_cache_ttl:
                return self._tools_schema_cache

        self.ensure_discovered()
        self._tools_schema_cache = get_openai_tools_schema()
        self._schema_cache_time = now
        return self._tools_schema_cache

    def invalidate_schema_cache(self):
        self._tools_schema_cache = None
        self._schema_cache_time = 0


_shared_tool_manager = ToolManager()


# 高危工具集合：可在创建通道时整体禁用（如开放 API / 不可信通道）
DANGEROUS_TOOLS: set[str] = {"execute_lua"}


class PerUserToolManager:
    def __init__(
        self,
        shared: ToolManager,
        channel=None,
        ctx=None,
        fsm=None,
        cache_ttl: int = 300,
        cache_max_size: int = 1000,
        tool_timeout: int = 15,
        tool_max_retries: int = 1,
        mcp_pool_max_size: int = 5,
        mcp_pool_min_size: int = 2,
        circuit_failure_threshold: int = 5,
        circuit_recovery_timeout: int = 60,
        disabled_tools: list[str] = None,
        enabled_plugins: list[str] = None,
        device_has_display: bool = True,
        device_id: str = "",  # 绑定设备 ID，用于 KV 按设备隔离存储
        dangerous_tools_enabled: bool = True,  # 高危工具开关（False 时 DANGEROUS_TOOLS 内的工具调用被拒绝）
    ):
        self._shared = shared
        self.channel = channel
        self.ctx = ctx
        self.fsm = fsm
        self.device_id = device_id  # 设备 ID，供 KV 存储等按设备隔离
        # 高危工具门禁：False 时 DANGEROUS_TOOLS 中的工具在 call_tool 入口被直接拒绝
        self.dangerous_tools_enabled = dangerous_tools_enabled
        self._disabled_tools = set(disabled_tools) if disabled_tools else set()
        # 设备级插件白名单：None/空 = 无白名单限制（插件全部启用）；
        # 非空集合 = 仅白名单内插件生效（插件商店语义）
        self._enabled_plugins: set[str] | None = (
            set(enabled_plugins) if enabled_plugins else None
        )
        # 设备能力：无屏设备（C3 headless）自动隐藏 requires=display 插件的工具
        self.device_has_display = device_has_display
        # 插件配置：{插件名: {配置项: 值}}（设备级，注入自 user_config.plugin_configs）
        self.plugin_configs: dict = {}
        self.active_skills: set[str] = set()  # 当前 session 激活的 Skill ID
        self.user_config = None

        self._cache = ToolCache(ttl=cache_ttl, max_size=cache_max_size)
        self._tool_timeout = tool_timeout
        self._tool_max_retries = tool_max_retries

        self._mcp_clients: list[MCPClient] = []
        self._mcp_tool_map: dict[str, MCPClient | tuple[str, MCPPool]] = {}
        self._mcp_pools: dict[str, MCPPool] = {}
        self._mcp_tool_schemas: dict[str, list[dict]] = {}
        # 是否共享全局 startup_tool_mgr 的 MCP 池（ws_session_handler 复用全局池时置 True）。
        # 共享时 cleanup 只清空引用、不 close 池，否则会误杀其他在线设备的 MCP 连接。
        self._shares_global_mcp: bool = False
        self._mcp_pool_max_size = mcp_pool_max_size
        self._mcp_pool_min_size = mcp_pool_min_size

        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._circuit_failure_threshold = circuit_failure_threshold
        self._circuit_recovery_timeout = circuit_recovery_timeout

        self._use_cache = True
        self._use_pool = True
        self._use_circuit_breaker = True

        # 性能优化：缓存合并后的 schema 列表，避免每次 get_all_tools_schema() 重建
        self._merged_schema_cache: list[dict] | None = None
        self._schema_cache_valid: bool = False

        # 工具检索器：根据用户查询预筛选相关工具，减少 LLM 选择空间
        self._retriever: ToolRetriever = ToolRetriever()
        self._retriever_index_valid: bool = False

        # Lua 执行结果等待：工具发送代码后 await 这个 Future，设备上报时 set_result
        self._pending_lua_future: asyncio.Future = None
        # 设备状态查询等待（get_volume/get_brightness 工具）：设备上报 device_state_result 时 set_result
        self._pending_device_state_future: asyncio.Future = None
        # 设备指令 ack 等待（send_device_command_ack 工具）：设备回发 instruct_ack 时 set_result
        self._pending_command_ack_future: asyncio.Future = None

    def get_plugin_config(self, plugin: str, key: str, default: str = "") -> str:
        """读取设备级插件配置项（如天气插件的高德 Key）。"""
        return str((self.plugin_configs.get(plugin) or {}).get(key) or default)

    async def initialize_mcp(self, mcp_servers: dict | None = None, disabled_servers: list | None = None, disabled_tools: dict | None = None):
        if not mcp_servers:
            return
        disabled_servers = disabled_servers or []
        disabled_tools = disabled_tools or {}
        
        # 调试日志
        logger.info(f"[MCP] initialize_mcp called: servers={list(mcp_servers.keys())}, disabled_servers={disabled_servers}, disabled_tools={disabled_tools}")

        servers = []
        if isinstance(mcp_servers, dict):
            for name, cfg in mcp_servers.items():
                if name in disabled_servers:
                    logger.info(f"[MCP] 跳过禁用的服务器: {name}")
                    continue
                if isinstance(cfg, dict) and cfg.get("url"):
                    server = {"name": name, "url": cfg["url"]}
                    if cfg.get("headers"):
                        server["headers"] = cfg["headers"]
                    if cfg.get("auth"):
                        server["auth"] = cfg["auth"]
                    servers.append(server)

        # 性能优化：并行初始化多个 MCP 服务器，将串行 N*200-800ms 降为 max(200-800ms)
        async def _init_single_server(server_config: dict) -> None:
            url = server_config.get("url", "")
            name = server_config.get("name", url)
            headers = server_config.get("headers")
            auth = server_config.get("auth")
            if not url:
                return

            if self._use_pool:
                pool = MCPPool(
                    url, name, headers=headers, auth=auth,
                    max_size=self._mcp_pool_max_size,
                    min_size=self._mcp_pool_min_size,
                )
                await pool.initialize()
                self._mcp_pools[name] = pool
                logger.info(f"[ToolManager] MCP 连接池已初始化: {name}")

                if self._use_circuit_breaker:
                    self._circuit_breakers[name] = await CircuitBreakerManager.get_breaker(
                        name=f"mcp_{name}",
                        failure_threshold=self._circuit_failure_threshold,
                        recovery_timeout=self._circuit_recovery_timeout,
                    )
                    logger.info(f"[ToolManager] MCP 熔断器已创建: {name}")

                client = await pool.acquire()
                if client:
                    all_schemas = client.get_tools_schema()
                    server_disabled = set(disabled_tools.get(name, []) or [])
                    if server_disabled:
                        all_schemas = [s for s in all_schemas if s["function"]["name"] not in server_disabled]
                        logger.info(f"[MCP] 服务器 {name} 过滤掉 {len(server_disabled)} 个禁用工具")
                    self._mcp_tool_schemas[name] = all_schemas
                    for schema in self._mcp_tool_schemas[name]:
                        func_name = schema["function"]["name"]
                        self._mcp_tool_map[func_name] = (name, pool)
                    await pool.release(client)
            else:
                client = MCPClient(url, name, headers=headers, auth=auth)
                success = await client.connect()
                if success:
                    self._mcp_clients.append(client)
                    all_schemas = client.get_tools_schema()
                    server_disabled = set(disabled_tools.get(name, []) or [])
                    if server_disabled:
                        all_schemas = [s for s in all_schemas if s["function"]["name"] not in server_disabled]
                        logger.info(f"[MCP] 服务器 {name} 过滤掉 {len(server_disabled)} 个禁用工具")
                    self._mcp_tool_schemas[name] = all_schemas
                    for schema in self._mcp_tool_schemas[name]:
                        func_name = schema["function"]["name"]
                        self._mcp_tool_map[func_name] = client

                    if self._use_circuit_breaker:
                        self._circuit_breakers[name] = await CircuitBreakerManager.get_breaker(
                            name=f"mcp_{name}",
                            failure_threshold=self._circuit_failure_threshold,
                            recovery_timeout=self._circuit_recovery_timeout,
                        )

        # 并行初始化所有服务器
        if servers:
            await asyncio.gather(*[_init_single_server(s) for s in servers], return_exceptions=True)

        mcp_count = len(self._mcp_tool_map)
        builtin_count = len(self._shared.get_all_tools_schema())
        circuit_count = len(self._circuit_breakers)
        # MCP 初始化后 schema 已变化，使缓存失效
        self._schema_cache_valid = False
        logger.info(f"[ToolManager] 总工具数: 内置 {builtin_count} + MCP {mcp_count}, 熔断器: {circuit_count}")

    def invalidate_schema_cache(self):
        """使工具 schema 缓存失效（插件安装/卸载、能力配置变化后调用，下次会话重建）。"""
        self._schema_cache_valid = False
        self._merged_schema_cache = None
        self._retriever_index_valid = False

    def get_active_skills(self) -> list[str]:
        return list(self.active_skills)

    def is_skill_active(self, skill_id: str) -> bool:
        return skill_id in self.active_skills

    def get_all_tools_schema(self) -> list[dict]:
        # 性能优化：使用缓存，避免每次调用都重建列表
        if self._schema_cache_valid and self._merged_schema_cache is not None:
            return self._merged_schema_cache

        schemas = list(self._shared.get_all_tools_schema())

        for schema_list in self._mcp_tool_schemas.values():
            schemas.extend(schema_list)

        # 设备级过滤：黑名单 + 插件白名单（enabled_plugins）+ 能力适配（无屏设备隐藏屏幕类工具）
        schemas = [
            s for s in schemas
            if self._device_tool_allowed(s.get("function", {}).get("name", ""))
        ]

        self._merged_schema_cache = schemas
        self._schema_cache_valid = True
        return schemas

    def get_relevant_tools_schema(self, user_query: str = "") -> list[dict]:
        """根据用户查询检索最相关的工具 schema（减少 LLM 选择空间）。

        工作流程：
        1. 获取全部设备可用 schema（含设备级过滤）
        2. 如果工具总数 <= top_k，直接返回全部（无需检索）
        3. 用 ToolRetriever 做关键词匹配，选出最相关的 Top-K
        4. 匹配不足或查询为空时安全降级到全部工具
        """
        all_schemas = self.get_all_tools_schema()

        # 工具数量不多时不需要检索
        if len(all_schemas) <= self._retriever._top_k:
            return all_schemas

        # 确保检索索引就绪（schema 缓存重建时同步更新）
        if not self._retriever_index_valid:
            self._retriever.update_index(all_schemas)
            self._retriever_index_valid = True

        # 检索相关工具名
        all_names = {s.get("function", {}).get("name", "") for s in all_schemas}
        relevant_names = self._retriever.retrieve(user_query, all_names)

        # 过滤 schema
        relevant_schemas = [
            s for s in all_schemas
            if s.get("function", {}).get("name", "") in relevant_names
        ]

        return relevant_schemas if relevant_schemas else all_schemas

    def _device_tool_allowed(self, tool_name: str) -> bool:
        """设备级工具可见性/可执行性判断（插件商店语义）：
        1. 黑名单 disabled_tools → 禁用
        2. 插件白名单 enabled_plugins：None = 无限制（仅非可选插件工具启用）；
           非空集合 = 插件必须在该白名单内才生效（内置工具不受影响）
        3. MCP 服务器视为虚拟插件（mcp:<server>），纳入同一白名单语义
        4. 能力适配：插件声明 requires=display 且设备无屏（device_has_display=False）→ 隐藏
        """
        if tool_name in self._disabled_tools:
            return False
        # MCP 工具：映射到虚拟插件名 mcp:<server>，参与白名单过滤
        if tool_name in self._mcp_tool_map:
            if self._enabled_plugins is not None:
                server = self._mcp_server_of_tool(tool_name)
                if server and f"mcp:{server}" not in self._enabled_plugins:
                    logger.info(f"[ToolManager] 设备未启用 MCP 服务器 {server}，隐藏工具 {tool_name}")
                    return False
            return True
        # 延迟导入避免与 plugin_loader 循环依赖（plugin_loader 依赖本模块）
        from src.infrastructure.plugin_loader import (
            get_plugin_of_tool,
            get_plugin_requires,
            is_optional_plugin,
            is_system_plugin,
        )
        plugin = get_plugin_of_tool(tool_name)
        if plugin:
            # 商店语义：enabled_plugins 白名单仅控制可选插件
            # - 系统插件（核心服务）：始终可用，不受白名单影响（等同内置插件）
            # - 非可选插件：始终可用（不受白名单影响）
            # - 可选插件：需在白名单中才可用
            if is_optional_plugin(plugin) and not is_system_plugin(plugin):
                if self._enabled_plugins is None or plugin not in self._enabled_plugins:
                    logger.info(f"[ToolManager] 可选插件「{plugin}」未安装，隐藏工具 {tool_name}")
                    return False
            if not self.device_has_display and "display" in get_plugin_requires(plugin):
                logger.info(f"[ToolManager] 设备无屏幕，隐藏工具 {tool_name}（插件「{plugin}」需 display）")
                return False
        return True

    def _mcp_server_of_tool(self, tool_name: str) -> str | None:
        """工具名 → 所属 MCP 服务器名（用于白名单过滤）。"""
        pool_info = self._mcp_tool_map.get(tool_name)
        if pool_info is None:
            return None
        if isinstance(pool_info, tuple):
            return str(pool_info[0])
        return getattr(pool_info, "server_name", None) or "mcp"

    async def _call_mcp_with_circuit_breaker(
        self,
        tool_name: str,
        pool_name: str,
        pool: MCPPool,
        arguments: dict,
    ) -> str:
        breaker = self._circuit_breakers.get(pool_name)

        if breaker and self._use_circuit_breaker:
            async def _do_call():
                client = await pool.acquire()
                if not client:
                    return f"MCP Server {pool_name} 获取连接失败"
                try:
                    return await client.call_tool(tool_name, arguments)
                finally:
                    await pool.release(client)

            return await breaker.call(_do_call, fallback=None)
        else:
            client = await pool.acquire()
            if not client:
                return f"MCP Server {pool_name} 获取连接失败"
            try:
                return await client.call_tool(tool_name, arguments)
            finally:
                await pool.release(client)

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict,
        use_cache: bool = True,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
    ) -> str:
        timeout = timeout or self._tool_timeout
        max_retries = max_retries or self._tool_max_retries

        # 高危工具熔断：通道禁用高危工具时直接拒绝（在权限检查之前，避免任何执行路径）
        if tool_name in DANGEROUS_TOOLS and not self.dangerous_tools_enabled:
            logger.warning(f"[ToolManager] 高危工具 {tool_name} 已在当前通道禁用，拒绝调用")
            return "该工具已在当前通道禁用"

        # 权限检查前置：无论缓存命中还是执行，未安装/禁用的工具一律拒绝
        # （否则缓存命中会绕过 _device_tool_allowed——卸载插件后缓存期内仍可使用，付费插件会被白嫖）
        if not self._device_tool_allowed(tool_name):
            logger.warning(f"[ToolManager] 工具 {tool_name} 已被设备级配置禁用（缓存路径拦截）")
            return f"工具 {tool_name} 在当前设备上不可用"

        # 参数校验前置：按工具声明 schema 校验 LLM 传入参数（jsonschema）
        validation_error = self._validate_arguments(tool_name, arguments)
        if validation_error:
            logger.warning(f"[ToolManager] 工具 {tool_name} 参数校验失败: {validation_error}")
            return f"工具 {tool_name} 参数校验失败: {validation_error}"

        # 工具可声明 cache=False（@tool(cache=False)）禁用结果缓存：
        # 缓存命中会跳过整个函数，含屏幕显示/设备指令副作用的工具会因此失效
        # （如天气卡片：相同城市第二次问不再显示）
        _def = get_tool(tool_name)
        if _def is not None and not _def.cache:
            use_cache = False

        for attempt in range(max_retries + 1):
            try:
                if use_cache and self._use_cache:
                    cached = await self._cache.get(tool_name, arguments)
                    if cached is not None:
                        return cached

                result = await asyncio.wait_for(
                    self._call_tool_internal(tool_name, arguments),
                    timeout=timeout
                )

                if use_cache and self._use_cache:
                    await self._cache.set(tool_name, arguments, result)

                return result

            except asyncio.TimeoutError:
                if attempt < max_retries:
                    await asyncio.sleep(2**attempt)
                else:
                    return f"工具 {tool_name} 调用超时"
            except StopPipeline:
                raise
            except Exception as e:
                if attempt < max_retries:
                    await asyncio.sleep(1)
                else:
                    return f"工具 {tool_name} 调用失败: {e}"

    def _coerce_args(self, func: Callable, arguments: dict) -> dict:
        kwargs = dict(arguments)
        try:
            hints = typing.get_type_hints(func)
        except Exception:
            return kwargs
        for param_name, ann in hints.items():
            if param_name not in kwargs or param_name in ("self", "cls", "tool_manager", "channel", "ctx", "fsm"):
                continue
            val = kwargs[param_name]
            if isinstance(val, ann):
                continue
            try:
                if ann is int:
                    kwargs[param_name] = int(float(val))
                elif ann is float:
                    kwargs[param_name] = float(val)
                elif ann is bool:
                    if isinstance(val, str):
                        kwargs[param_name] = val.lower() in ("true", "1", "yes")
                    else:
                        kwargs[param_name] = bool(val)
            except (ValueError, TypeError):
                pass
        return kwargs

    def _validate_arguments(self, tool_name: str, arguments: dict) -> str | None:
        """按工具声明的参数 schema 校验 LLM 传入参数（jsonschema）。

        Args:
            tool_name: 工具名
            arguments: LLM 传入的参数（dict）

        Returns:
            None 表示校验通过；字符串表示校验失败原因。
        """
        # MCP 工具：schema 由远端声明，跳过本地校验（避免误拦）
        if tool_name in self._mcp_tool_map:
            return None

        td = get_tool(tool_name)
        if td is None:
            return None
        schema = td.parameters
        if not isinstance(schema, dict) or not schema.get("properties"):
            return None

        try:
            import jsonschema
            jsonschema.validate(instance=arguments, schema=schema)
        except jsonschema.ValidationError as e:
            return f"{e.message}"
        except Exception as e:
            logger.debug(f"[ToolManager] 参数校验异常（放行）: {e}")
            return None
        return None

    async def _call_tool_internal(self, tool_name: str, arguments: dict) -> str:
        self._shared.ensure_discovered()

        if not self._device_tool_allowed(tool_name):
            logger.warning(f"[ToolManager] 工具 {tool_name} 已被设备级配置禁用（黑名单/插件白名单/设备能力）")
            return f"工具 {tool_name} 在当前设备上不可用"

        builtin = get_tool(tool_name)
        if builtin:
            try:
                sig = inspect.signature(builtin.func)
                kwargs = self._coerce_args(builtin.func, arguments)
                if "tool_manager" in sig.parameters:
                    kwargs["tool_manager"] = self
                if self.channel and "channel" in sig.parameters:
                    kwargs["channel"] = self.channel
                if self.ctx and "ctx" in sig.parameters:
                    kwargs["ctx"] = self.ctx
                if self.fsm and "fsm" in sig.parameters:
                    kwargs["fsm"] = self.fsm
                result = await self._call_with_plugin_context(builtin, tool_name, kwargs)
                return str(result)
            except StopPipeline:
                raise
            except PermissionError as e:
                logger.error(f"[ToolManager] 插件工具 {tool_name} 权限被拒: {e}")
                return f"权限不足: {e}"
            except Exception as e:
                logger.error(f"[ToolManager] 内置工具 {tool_name} 执行异常: {e}")
                return f"工具执行异常: {e}"

        if tool_name in self._mcp_tool_map:
            pool_info = self._mcp_tool_map[tool_name]

            if self._use_pool and isinstance(pool_info, tuple):
                pool_name, pool = pool_info
                return await self._call_mcp_with_circuit_breaker(
                    tool_name, pool_name, pool, arguments
                )
            else:
                client = pool_info
                return await client.call_tool(tool_name, arguments)

        logger.warning(f"[ToolManager] 未找到工具: {tool_name}")
        return f"未找到工具: {tool_name}"

    async def _call_with_plugin_context(self, td, tool_name: str, kwargs: dict):
        """在插件权限上下文中执行工具函数（运行时守卫的数据源）。

        非插件工具（内置/系统工具）不设上下文 → SDK 权限检查放行。
        """
        plugin = None
        try:
            from src.infrastructure.plugin_loader import get_plugin_of_tool
            plugin = get_plugin_of_tool(tool_name)
        except Exception:
            plugin = None

        if plugin is None:
            # 同步函数放到线程池执行，避免阻塞事件循环（协程函数照旧直接 await）
            if asyncio.iscoroutinefunction(td.func):
                return await td.func(**kwargs)
            return await asyncio.to_thread(td.func, **kwargs)

        # 插件工具：注入权限上下文（permissions 来自 manifest）
        from src.infrastructure.plugin_security import reset_plugin_context, set_plugin_context

        permissions = []
        try:
            from src.infrastructure.plugin_loader import get_plugin_manifest
            manifest = get_plugin_manifest(plugin)
            if manifest is not None:
                permissions = list(getattr(manifest, "permissions", []) or [])
        except Exception:
            permissions = []
        token = set_plugin_context(plugin, permissions)
        try:
            if asyncio.iscoroutinefunction(td.func):
                return await td.func(**kwargs)
            # 同步函数放到线程池执行，避免阻塞事件循环
            return await asyncio.to_thread(td.func, **kwargs)
        finally:
            reset_plugin_context(token)

    async def call_tools_batch(
        self,
        tool_calls: list[tuple[str, dict]],
        parallel: bool = True,
    ) -> list[Any]:
        if not tool_calls:
            return []

        if parallel and len(tool_calls) > 1:
            tasks = []
            for tool_name, arguments in tool_calls:
                task = self.call_tool(tool_name, arguments, use_cache=True)
                tasks.append(task)

            results = await asyncio.gather(*tasks, return_exceptions=True)

            final_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    tool_name, _ = tool_calls[i]
                    final_results.append(f"工具 {tool_name} 调用失败: {result}")
                else:
                    final_results.append(result)
            return final_results
        else:
            results = []
            for tool_name, arguments in tool_calls:
                result = await self.call_tool(tool_name, arguments)
                results.append(result)
            return results

    async def call_tool_with_cache(
        self,
        tool_name: str,
        arguments: dict,
        use_cache: bool = True,
    ) -> str:
        return await self.call_tool(tool_name, arguments, use_cache=use_cache)

    async def clear_cache(self):
        await self._cache.clear()



    def get_cache_stats(self) -> dict:
        return self._cache.get_stats()

    def get_pool_stats(self) -> list[dict]:
        return [pool.get_stats() for pool in self._mcp_pools.values()]

    def get_circuit_breaker_stats(self) -> dict:
        return {name: breaker.get_stats() for name, breaker in self._circuit_breakers.items()}

    async def reset_circuit_breaker(self, name: str):
        if name in self._circuit_breakers:
            await self._circuit_breakers[name].reset()
            logger.info(f"[ToolManager] 熔断器已重置: {name}")

    async def cleanup(self):
        # 共享全局 MCP 池时只清空本对象的引用，不关闭池/断开客户端——
        # 池的生命周期由 app.state 全局管理，close 会误杀其他在线设备的 MCP 连接
        if self._shares_global_mcp:
            self._mcp_pools = {}
            self._mcp_tool_schemas = {}
            self._circuit_breakers = {}
            self._mcp_clients = []
            self._mcp_tool_map = {}
            return

        for pool in self._mcp_pools.values():
            await pool.close()
        self._mcp_pools.clear()
        self._mcp_tool_schemas.clear()
        self._circuit_breakers.clear()

        for client in self._mcp_clients:
            await client.disconnect()
        self._mcp_clients.clear()
        self._mcp_tool_map.clear()


def create_tool_manager(config: dict = None) -> PerUserToolManager:
    return PerUserToolManager(
        shared=_shared_tool_manager,
        **(config or {}),
    )


__all__ = [
    "StopPipeline",
    "ToolDefinition",
    "tool",
    "register_tool",
    "get_all_tools",
    "get_openai_tools_schema",
    "get_tool",
    "get_disabled_tools",
    "set_disabled_tools",
    "disable_tool",
    "enable_tool",
    "auto_discover",
    "ToolCache",
    "CircuitBreaker",
    "CircuitBreakerManager",
    "MCPClient",
    "MCPPool",
    "ToolManager",
    "ToolRetriever",
    "PerUserToolManager",
    "create_tool_manager",
]
