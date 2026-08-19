"""
tools_system.py 单元测试

覆盖类：
- ToolCache：缓存命中/过期/淘汰/统计
- CircuitBreaker：CLOSED / OPEN / HALF_OPEN 状态流转 + fallback
- MCPClient：connect / call_tool / disconnect / health_check（通过 mock 避免真实网络）
- MCPPool：initialize / acquire / release / close
- PerUserToolManager：call_tool（内置 + MCP）、缓存、禁用、批量、coerce_args 等
- 装饰器 tool()、模块级 disable/enable/get_all_tools 等
"""
# 注意：不要使用 `from __future__ import annotations`，否则 @tool 装饰器
# 通过 inspect.signature 拿到的是字符串注解（如 "int"），无法与 int 类型做 is 比较。
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.use_cases import tools_system
from src.use_cases.tools_system import (
    CircuitBreaker,
    CircuitBreakerManager,
    CircuitState,
    MCPClient,
    MCPPool,
    PerUserToolManager,
    StopPipeline,
    ToolCache,
    ToolDefinition,
    ToolManager,
    create_tool_manager,
    disable_tool,
    enable_tool,
    get_all_tools,
    get_disabled_tools,
    get_openai_tools_schema,
    get_tool,
    set_disabled_tools,
    tool,
)


# ============================================================
# ToolDefinition 与 @tool 装饰器
# ============================================================


class TestToolDefinition:
    """ToolDefinition 实体与 to_openai_schema 序列化"""

    def test_to_openai_schema(self):
        # 验证 schema 结构符合 OpenAI function-calling 规范
        def fn(x: int):
            return x

        td = ToolDefinition("foo", "描述", fn, {"type": "object", "properties": {}})
        schema = td.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "foo"
        assert schema["function"]["description"] == "描述"
        assert schema["function"]["parameters"] == {"type": "object", "properties": {}}


class TestToolDecorator:
    """@tool 装饰器与全局注册表"""

    def setup_method(self):
        # 每个测试前清空注册表，避免互相干扰
        tools_system._registry.clear()
        tools_system._disabled_global.clear()

    def test_register_simple_tool(self):
        @tool()
        def my_tool(x: int):
            """简单工具"""
            return x

        assert "my_tool" in get_all_tools()
        td = get_tool("my_tool")
        assert td is not None
        assert td.description == "简单工具"
        assert td.func(3) == 3

    def test_register_with_custom_name_and_desc(self):
        @tool(name="custom_name", description="自定义描述")
        def some_func():
            return 1

        assert "custom_name" in get_all_tools()
        assert "some_func" not in get_all_tools()
        td = get_tool("custom_name")
        assert td.description == "自定义描述"

    def test_register_without_docstring_uses_name_as_desc(self):
        @tool()
        def no_doc_tool():
            return None

        td = get_tool("no_doc_tool")
        assert td.description == "no_doc_tool"

    def test_schema_infers_types_and_required(self):
        @tool()
        def typed_tool(a: int, b: str, c: float = 1.0, d: bool = False):
            return a

        td = get_tool("typed_tool")
        props = td.parameters["properties"]
        assert props["a"]["type"] == "integer"
        assert props["b"]["type"] == "string"
        assert props["c"]["type"] == "number"
        assert props["c"]["default"] == 1.0
        assert props["d"]["type"] == "boolean"
        assert set(td.parameters["required"]) == {"a", "b"}

    def test_schema_skips_self_cls_tool_manager(self):
        @tool()
        def method_tool(self, x: int, tool_manager=None):  # noqa: N805
            return x

        td = get_tool("method_tool")
        props = td.parameters["properties"]
        assert "self" not in props
        assert "tool_manager" not in props
        assert "x" in props

    def test_get_openai_tools_schema_returns_list(self):
        @tool()
        def t1():
            return 1

        @tool()
        def t2():
            return 2

        schemas = get_openai_tools_schema()
        names = [s["function"]["name"] for s in schemas]
        assert set(names) == {"t1", "t2"}

    def test_disable_enable_tools(self):
        @tool()
        def t1():
            return 1

        disable_tool("t1")
        assert "t1" in get_disabled_tools()

        enable_tool("t1")
        assert "t1" not in get_disabled_tools()

    def test_set_disabled_tools_replaces_set(self):
        disable_tool("a")
        set_disabled_tools({"b", "c"})
        assert get_disabled_tools() == {"b", "c"}


# ============================================================
# ToolCache
# ============================================================


class TestToolCache:
    """ToolCache：异步缓存 + TTL + LRU 淘汰 + 统计"""

    def test_generate_key_stable(self):
        cache = ToolCache()
        # 参数顺序不同但内容相同应产生相同 key（sort_keys=True）
        k1 = cache._generate_key("t", {"a": 1, "b": 2})
        k2 = cache._generate_key("t", {"b": 2, "a": 1})
        assert k1 == k2

    async def test_get_miss(self):
        cache = ToolCache()
        result = await cache.get("t", {"a": 1})
        assert result is None
        stats = cache.get_stats()
        assert stats["misses"] == 1
        assert stats["hits"] == 0

    async def test_set_and_get_hit(self):
        cache = ToolCache()
        await cache.set("t", {"a": 1}, "result")
        result = await cache.get("t", {"a": 1})
        assert result == "result"
        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 0
        assert stats["size"] == 1

    async def test_get_expired_returns_none(self):
        cache = ToolCache(ttl=1)
        await cache.set("t", {}, "v")
        # 篡改时间戳模拟过期
        key = cache._generate_key("t", {})
        cache._cache[key] = (time.time() - 2, "v")
        result = await cache.get("t", {})
        assert result is None
        # 过期后应从缓存中删除
        assert key not in cache._cache
        stats = cache.get_stats()
        assert stats["misses"] == 1

    async def test_lru_eviction_on_max_size(self):
        cache = ToolCache(ttl=300, max_size=2)
        await cache.set("t1", {}, "v1")
        await asyncio.sleep(0.01)
        await cache.set("t2", {}, "v2")
        await asyncio.sleep(0.01)
        # 第三条应触发淘汰最早的 t1
        await cache.set("t3", {}, "v3")
        assert cache.get_stats()["size"] == 2
        assert await cache.get("t1", {}) is None
        # t2 仍然存在
        assert await cache.get("t2", {}) == "v2"

    async def test_clear_resets(self):
        cache = ToolCache()
        await cache.set("t", {}, "v")
        await cache.get("t", {})
        await cache.clear()
        stats = cache.get_stats()
        assert stats["size"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0

    def test_get_stats_hit_rate(self):
        cache = ToolCache()
        # 空缓存：hit_rate=0
        assert cache.get_stats()["hit_rate"] == 0
        cache._hits = 3
        cache._misses = 1
        assert cache.get_stats()["hit_rate"] == 0.75


# ============================================================
# CircuitBreaker
# ============================================================


class TestCircuitBreaker:
    """CircuitBreaker：三态流转 + fallback + 统计"""

    async def test_initial_state_closed(self):
        cb = CircuitBreaker("test")
        assert cb.state == CircuitState.CLOSED
        assert cb.is_closed is True
        assert cb.is_open is False
        assert cb.is_half_open is False

    async def test_call_success_records_stats(self):
        cb = CircuitBreaker("test")

        async def ok():
            return "ok"

        result = await cb.call(ok)
        assert result == "ok"
        stats = cb.get_stats()
        assert stats["stats"]["successful_calls"] == 1
        assert stats["stats"]["total_calls"] == 1

    async def test_call_sync_function(self):
        cb = CircuitBreaker("test")
        result = await cb.call(lambda x: x * 2, 5)
        assert result == 10

    async def test_failures_open_circuit(self):
        cb = CircuitBreaker("test", failure_threshold=3)

        async def fail():
            raise RuntimeError("boom")

        for _ in range(3):
            await cb.call(fail)
        assert cb.is_open is True
        stats = cb.get_stats()
        assert stats["stats"]["failed_calls"] == 3

    async def test_open_rejects_calls(self):
        cb = CircuitBreaker("test", failure_threshold=1)

        async def fail():
            raise RuntimeError("boom")

        await cb.call(fail)
        assert cb.is_open is True

        async def ok():
            return "ok"

        # 断路器打开时应拒绝并返回 None
        result = await cb.call(ok)
        assert result is None
        assert cb.get_stats()["stats"]["rejected_calls"] == 1

    async def test_open_with_fallback(self):
        cb = CircuitBreaker("test", failure_threshold=1)

        async def fail():
            raise RuntimeError("boom")

        await cb.call(fail)

        def fallback():
            return "fallback"

        result = await cb.call(fail, fallback=fallback)
        assert result == "fallback"

    async def test_open_with_async_fallback(self):
        cb = CircuitBreaker("test", failure_threshold=1)

        async def fail():
            raise RuntimeError("boom")

        await cb.call(fail)

        async def fallback():
            return "async_fallback"

        result = await cb.call(fail, fallback=fallback)
        assert result == "async_fallback"

    async def test_fallback_exception_swallowed(self):
        cb = CircuitBreaker("test", failure_threshold=1)

        async def fail():
            raise RuntimeError("boom")

        await cb.call(fail)

        def bad_fallback():
            raise ValueError("bad fallback")

        # fallback 抛异常时应被吞掉并返回 None
        result = await cb.call(fail, fallback=bad_fallback)
        assert result is None

    async def test_recovery_to_half_open_then_closed(self):
        cb = CircuitBreaker(
            "test",
            failure_threshold=1,
            recovery_timeout=1,
            half_open_max_calls=2,
        )

        async def fail():
            raise RuntimeError("boom")

        await cb.call(fail)
        assert cb.is_open is True

        # 等待恢复超时
        await asyncio.sleep(1.1)

        async def ok():
            return "ok"

        # 第一次成功调用 -> HALF_OPEN
        r1 = await cb.call(ok)
        assert r1 == "ok"
        assert cb.is_half_open is True

        # 第二次成功调用 -> HALF_OPEN 成功数达到阈值 -> CLOSED
        r2 = await cb.call(ok)
        assert r2 == "ok"
        assert cb.is_closed is True

    async def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(
            "test",
            failure_threshold=1,
            recovery_timeout=1,
            half_open_max_calls=2,
        )

        async def fail():
            raise RuntimeError("boom")

        await cb.call(fail)
        await asyncio.sleep(1.1)

        # 试探失败 -> 直接回到 OPEN
        result = await cb.call(fail)
        assert result is None
        assert cb.is_open is True

    async def test_expected_exceptions_filter(self):
        cb = CircuitBreaker("test", failure_threshold=1, expected_exceptions=(ValueError,))

        async def raise_type_error():
            raise TypeError("not expected")

        # 不在 expected_exceptions 内的异常会走通用 except 分支，也记录失败
        await cb.call(raise_type_error)
        assert cb._failure_count == 1

    async def test_reset(self):
        cb = CircuitBreaker("test", failure_threshold=1)

        async def fail():
            raise RuntimeError("boom")

        await cb.call(fail)
        assert cb.is_open is True

        await cb.reset()
        assert cb.is_closed is True
        assert cb._failure_count == 0

    def test_get_stats_structure(self):
        cb = CircuitBreaker("test", failure_threshold=4, recovery_timeout=30)
        stats = cb.get_stats()
        assert stats["name"] == "test"
        assert stats["state"] == "closed"
        assert stats["failure_threshold"] == 4
        assert stats["recovery_timeout"] == 30
        assert "stats" in stats


# ============================================================
# CircuitBreakerManager
# ============================================================


class TestCircuitBreakerManager:
    """CircuitBreakerManager 单例 + get_breaker / reset_all / remove_breaker"""

    def setup_method(self):
        # 重置单例状态
        CircuitBreakerManager._instance = None
        CircuitBreakerManager._breakers = {}

    async def test_get_breaker_creates_once(self):
        b1 = await CircuitBreakerManager.get_breaker("svc")
        b2 = await CircuitBreakerManager.get_breaker("svc")
        assert b1 is b2

    async def test_get_all_stats(self):
        await CircuitBreakerManager.get_breaker("a")
        await CircuitBreakerManager.get_breaker("b")
        stats = await CircuitBreakerManager.get_all_stats()
        assert set(stats.keys()) == {"a", "b"}

    async def test_reset_all(self):
        b = await CircuitBreakerManager.get_breaker("a", failure_threshold=1)

        async def fail():
            raise RuntimeError("x")

        await b.call(fail)
        assert b.is_open is True
        await CircuitBreakerManager.reset_all()
        assert b.is_closed is True

    async def test_remove_breaker(self):
        await CircuitBreakerManager.get_breaker("a")
        await CircuitBreakerManager.remove_breaker("a")
        assert "a" not in CircuitBreakerManager._breakers
        # 不存在的不会报错
        await CircuitBreakerManager.remove_breaker("nonexistent")


# ============================================================
# MCPClient
# ============================================================


def _make_tool(name="t", description="d", input_schema=None):
    """构造一个模拟 fastmcp 返回的 tool 对象"""
    t = MagicMock()
    t.name = name
    t.description = description
    t.inputSchema = input_schema or {"type": "object", "properties": {}}
    return t


def _make_call_result(texts, is_error=False):
    """构造一个模拟 fastmcp call_tool 返回结果"""
    result = MagicMock()
    result.is_error = is_error
    result.isError = is_error
    content = []
    for txt in texts:
        c = MagicMock()
        c.text = txt
        content.append(c)
    result.content = content
    return result


async def _fake_connect_success(self):
    """模拟 MCPClient.connect 成功：设置 _connected=True 并填充空工具列表"""
    self._connected = True
    self._tools_cache = []
    return True


async def _fake_connect_success_with_tools(self, tools=None):
    """模拟 MCPClient.connect 成功并填充指定工具 schema"""
    self._connected = True
    self._tools_cache = tools or []
    return True


class TestMCPClient:
    """MCPClient：connect / disconnect / call_tool / health_check"""

    def test_init_defaults(self):
        client = MCPClient("http://x", name="srv")
        assert client.server_url == "http://x"
        assert client.name == "srv"
        assert client.connected is False
        assert client.get_tools_schema() == []

    def test_name_falls_back_to_url(self):
        client = MCPClient("http://x")
        assert client.name == "http://x"

    async def test_connect_success_plain(self):
        """无 headers/auth 时走 Client(url) 分支"""
        client = MCPClient("http://x", name="srv")
        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=None)
        fake_client.list_tools = AsyncMock(return_value=[_make_tool("foo")])

        with patch("fastmcp.Client", return_value=fake_client) as mock_client_cls:
            ok = await client.connect()
        assert ok is True
        assert client.connected is True
        assert len(client.get_tools_schema()) == 1
        mock_client_cls.assert_called_once_with("http://x")

    async def test_connect_success_with_headers(self):
        """有 headers/auth 时走 StreamableHttpTransport 分支"""
        client = MCPClient("http://x", name="srv", headers={"k": "v"}, auth="token")
        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=None)
        fake_client.list_tools = AsyncMock(return_value=[])

        with patch("fastmcp.Client", return_value=fake_client) as mock_client_cls, \
                patch("fastmcp.client.transports.StreamableHttpTransport") as mock_transport:
            ok = await client.connect()
        assert ok is True
        mock_transport.assert_called_once()
        mock_client_cls.assert_called_once()

    async def test_connect_returns_tools_with_schema(self):
        client = MCPClient("http://x", name="srv")
        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=None)
        # 测试 result.tools 分支（非 list）
        tools_obj = MagicMock()
        tools_obj.tools = [_make_tool("a", "desc", {"type": "object"})]
        fake_client.list_tools = AsyncMock(return_value=tools_obj)

        with patch("fastmcp.Client", return_value=fake_client):
            ok = await client.connect()
        assert ok is True
        schemas = client.get_tools_schema()
        assert schemas[0]["function"]["name"] == "a"
        assert schemas[0]["function"]["description"] == "desc"

    async def test_connect_failure_returns_false(self):
        client = MCPClient("http://x", name="srv")
        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(side_effect=RuntimeError("connect fail"))
        fake_client.__aexit__ = AsyncMock(return_value=None)

        with patch("fastmcp.Client", return_value=fake_client):
            ok = await client.connect()
        assert ok is False
        assert client.connected is False

    async def test_refresh_tools_failure_does_not_raise(self):
        client = MCPClient("http://x", name="srv")
        client._client = MagicMock()
        client._client.list_tools = AsyncMock(side_effect=RuntimeError("err"))
        # 不应抛出
        await client._refresh_tools()
        assert client.get_tools_schema() == []

    async def test_disconnect(self):
        client = MCPClient("http://x", name="srv")
        fake_client = MagicMock()
        fake_client.__aexit__ = AsyncMock(return_value=None)
        client._client = fake_client
        client._connected = True
        client._tools_cache = [{"x": 1}]

        await client.disconnect()
        assert client._client is None
        assert client.connected is False
        assert client.get_tools_schema() == []

    async def test_disconnect_swallows_exception(self):
        client = MCPClient("http://x", name="srv")
        fake_client = MagicMock()
        fake_client.__aexit__ = AsyncMock(side_effect=RuntimeError("exit fail"))
        client._client = fake_client
        # 不应抛出
        await client.disconnect()
        assert client._client is None

    async def test_call_tool_not_connected_attempts_reconnect(self):
        client = MCPClient("http://x", name="srv")
        # connect 失败
        with patch.object(client, "connect", AsyncMock(return_value=False)):
            result = await client.call_tool("t", {})
        assert "连接失败" in result

    async def test_call_tool_success(self):
        client = MCPClient("http://x", name="srv")
        client._connected = True
        client._client = MagicMock()
        client._client.call_tool = AsyncMock(return_value=_make_call_result(["hello"]))

        result = await client.call_tool("t", {"a": 1})
        assert result == "hello"

    async def test_call_tool_multiple_texts_joined(self):
        client = MCPClient("http://x", name="srv")
        client._connected = True
        client._client = MagicMock()
        client._client.call_tool = AsyncMock(return_value=_make_call_result(["a", "b"]))

        result = await client.call_tool("t", {})
        assert result == "a\nb"

    async def test_call_tool_no_text_returns_default(self):
        client = MCPClient("http://x", name="srv")
        client._connected = True
        client._client = MagicMock()
        # content 没有 text 属性
        empty_result = MagicMock()
        empty_result.is_error = False
        empty_result.isError = False
        c = MagicMock()
        del c.text  # 删除 text 属性
        empty_result.content = [c]
        client._client.call_tool = AsyncMock(return_value=empty_result)

        result = await client.call_tool("t", {})
        assert result == "工具执行成功，无文本输出"

    async def test_call_tool_is_error(self):
        client = MCPClient("http://x", name="srv")
        client._connected = True
        client._client = MagicMock()
        client._client.call_tool = AsyncMock(
            return_value=_make_call_result(["err msg"], is_error=True)
        )

        result = await client.call_tool("t", {})
        assert "工具执行失败" in result
        assert "err msg" in result

    async def test_call_tool_timeout_disconnects(self):
        client = MCPClient("http://x", name="srv")
        client._connected = True
        client._client = MagicMock()

        async def slow_call(*a, **kw):
            await asyncio.sleep(20)
            return _make_call_result(["x"])

        client._client.call_tool = slow_call
        with patch.object(client, "disconnect", AsyncMock()) as mock_disconnect:
            # 把内部 wait_for 超时调小，避免真实等待 14 秒
            with patch("asyncio.wait_for", AsyncMock(side_effect=asyncio.TimeoutError())):
                result = await client.call_tool("t", {})
        assert "超时" in result
        mock_disconnect.assert_awaited()

    async def test_call_tool_reconnects_on_not_connected_error(self):
        client = MCPClient("http://x", name="srv")
        client._connected = True
        client._client = MagicMock()

        call_count = {"n": 0}

        async def call_then_ok(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("Client not connected yet")
            return _make_call_result(["recovered"])

        client._client.call_tool = call_then_ok
        with patch.object(client, "disconnect", AsyncMock()), \
                patch.object(client, "connect", AsyncMock(return_value=True)):
            result = await client.call_tool("t", {})
        assert result == "recovered"

    async def test_call_tool_generic_exception(self):
        client = MCPClient("http://x", name="srv")
        client._connected = True
        client._client = MagicMock()
        client._client.call_tool = AsyncMock(side_effect=RuntimeError("some other error"))

        result = await client.call_tool("t", {})
        assert "工具调用异常" in result

    async def test_health_check_not_connected(self):
        client = MCPClient("http://x", name="srv")
        assert await client.health_check() is False

    async def test_health_check_ok(self):
        client = MCPClient("http://x", name="srv")
        client._connected = True
        client._client = MagicMock()
        client._client.list_tools = AsyncMock(return_value=[])
        assert await client.health_check() is True

    async def test_health_check_failure_sets_disconnected(self):
        client = MCPClient("http://x", name="srv")
        client._connected = True
        client._client = MagicMock()
        client._client.list_tools = AsyncMock(side_effect=RuntimeError("down"))
        assert await client.health_check() is False
        assert client.connected is False


# ============================================================
# MCPPool
# ============================================================


class TestMCPPool:
    """MCPPool：连接池预热 / acquire / release / close / stats"""

    async def test_initialize_creates_min_clients(self):
        pool = MCPPool("http://x", "srv", max_size=5, min_size=2)
        with patch.object(MCPClient, "connect", AsyncMock(return_value=True)):
            await pool.initialize()
        assert pool._active_count == 2
        assert pool._initialized is True
        # 再次 initialize 应幂等
        await pool.initialize()
        assert pool._active_count == 2

    async def test_initialize_skips_on_max_size(self):
        pool = MCPPool("http://x", "srv", max_size=1, min_size=3)
        with patch.object(MCPClient, "connect", AsyncMock(return_value=True)):
            await pool.initialize()
        assert pool._active_count == 1

    async def test_initialize_failed_client_skipped(self):
        pool = MCPPool("http://x", "srv", max_size=5, min_size=2)
        with patch.object(MCPClient, "connect", AsyncMock(return_value=False)):
            await pool.initialize()
        assert pool._active_count == 0

    async def test_acquire_from_pool(self):
        pool = MCPPool("http://x", "srv", max_size=5, min_size=1)
        with patch.object(MCPClient, "connect", _fake_connect_success):
            await pool.initialize()
        client = await pool.acquire()
        assert client is not None
        assert client.connected is True

    async def test_acquire_creates_new_when_below_max(self):
        pool = MCPPool("http://x", "srv", max_size=5, min_size=0)
        # 池空且未达上限，创建新连接
        with patch.object(MCPClient, "connect", AsyncMock(return_value=True)):
            client = await pool.acquire()
        assert client is not None

    async def test_acquire_returns_none_on_create_fail_and_empty_pool(self):
        pool = MCPPool("http://x", "srv", max_size=5, min_size=0)
        # 池空、未达上限但创建失败；后续 wait_for(30) 会一直等 -> 用 patch 触发 TimeoutError
        with patch.object(MCPClient, "connect", AsyncMock(return_value=False)), \
                patch("asyncio.wait_for", AsyncMock(side_effect=asyncio.TimeoutError())):
            client = await pool.acquire()
        assert client is None

    async def test_release_connected_client_back_to_pool(self):
        pool = MCPPool("http://x", "srv", max_size=5, min_size=1)
        with patch.object(MCPClient, "connect", _fake_connect_success):
            await pool.initialize()
        client = await pool.acquire()
        assert client is not None
        await pool.release(client)
        # 池里应该又有一个空闲
        assert pool._pool.qsize() == 1

    async def test_release_disconnected_client(self):
        pool = MCPPool("http://x", "srv", max_size=5, min_size=0)
        fake = MagicMock()
        fake.connected = False
        fake.disconnect = AsyncMock()
        await pool.release(fake)
        fake.disconnect.assert_awaited()

    async def test_release_none_is_noop(self):
        pool = MCPPool("http://x", "srv")
        # 不应抛异常
        await pool.release(None)

    async def test_close_drains_pool(self):
        pool = MCPPool("http://x", "srv", max_size=5, min_size=2)
        with patch.object(MCPClient, "connect", AsyncMock(return_value=True)):
            await pool.initialize()
        with patch.object(MCPClient, "disconnect", AsyncMock()):
            await pool.close()
        assert pool._active_count == 0
        assert pool._initialized is False

    def test_get_stats(self):
        pool = MCPPool("http://x", "srv", max_size=5, min_size=1)
        stats = pool.get_stats()
        assert stats["server"] == "srv"
        assert stats["url"] == "http://x"
        assert stats["max_size"] == 5
        assert stats["active_count"] == 0
        assert stats["idle_count"] == 0


# ============================================================
# ToolManager (shared)
# ============================================================


class TestToolManager:
    """ToolManager：自动发现 + schema 缓存"""

    def setup_method(self):
        tools_system._registry.clear()

    def test_ensure_discovered_idempotent(self):
        tm = ToolManager()
        tm.ensure_discovered()
        assert tm._discovered is True
        # 第二次不应再扫描
        tm.ensure_discovered()

    def test_get_all_tools_schema_caches(self):
        tm = ToolManager()

        @tool()
        def t1():
            return 1

        s1 = tm.get_all_tools_schema()
        assert len(s1) >= 1
        # 第二次应返回缓存（不重新计算）
        s2 = tm.get_all_tools_schema()
        assert s1 is s2

    def test_invalidate_schema_cache(self):
        tm = ToolManager()

        @tool()
        def t1():
            return 1

        tm.get_all_tools_schema()
        tm.invalidate_schema_cache()
        assert tm._tools_schema_cache is None


# ============================================================
# PerUserToolManager
# ============================================================


class TestPerUserToolManager:
    """PerUserToolManager：工具调用编排、缓存、禁用、批量、coerce_args"""

    def setup_method(self):
        tools_system._registry.clear()
        tools_system._disabled_global.clear()

    def _make_manager(self, **kwargs):
        shared = ToolManager()
        return PerUserToolManager(shared=shared, **kwargs)

    def test_default_config(self):
        m = self._make_manager()
        # tool_timeout 默认 15，tool_max_retries 默认 1
        assert m._tool_timeout == 15
        assert m._tool_max_retries == 1
        assert m._use_cache is True
        assert m._use_pool is True
        assert m._use_circuit_breaker is True
        assert m._pending_lua_future is None

    def test_disabled_tools_from_constructor(self):
        m = self._make_manager(disabled_tools=["a", "b"])
        assert m._disabled_tools == {"a", "b"}

    def test_get_all_tools_schema_merges_builtin_and_mcp(self):
        m = self._make_manager()

        @tool()
        def builtin_one():
            return 1

        m._mcp_tool_schemas = {"srv": [{"type": "function", "function": {"name": "mcp_one"}}]}
        schemas = m.get_all_tools_schema()
        names = [s["function"]["name"] for s in schemas]
        assert "builtin_one" in names
        assert "mcp_one" in names

    def test_get_all_tools_schema_filters_disabled(self):
        m = self._make_manager(disabled_tools=["hidden"])

        @tool(name="hidden")
        def hidden():
            return 1

        @tool()
        def visible():
            return 2

        schemas = m.get_all_tools_schema()
        names = [s["function"]["name"] for s in schemas]
        assert "hidden" not in names
        assert "visible" in names

    async def test_call_tool_builtin(self):
        m = self._make_manager()

        @tool()
        def echo(x: int):
            return f"echo:{x}"

        result = await m.call_tool("echo", {"x": 42}, use_cache=False)
        assert result == "echo:42"

    async def test_call_tool_builtin_async(self):
        m = self._make_manager()

        @tool()
        async def aecho(x: int):
            return f"aecho:{x}"

        result = await m.call_tool("aecho", {"x": 1}, use_cache=False)
        assert result == "aecho:1"

    async def test_call_tool_injects_tool_manager(self):
        m = self._make_manager()

        @tool()
        def needs_tm(x: int, tool_manager=None):
            return "has_tm" if tool_manager is not None else "no_tm"

        result = await m.call_tool("needs_tm", {"x": 1}, use_cache=False)
        assert result == "has_tm"

    async def test_call_tool_injects_channel_ctx_fsm(self):
        channel = MagicMock()
        ctx = MagicMock()
        fsm = MagicMock()
        m = self._make_manager(channel=channel, ctx=ctx, fsm=fsm)

        @tool()
        def needs_deps(x: int, channel=None, ctx=None, fsm=None):
            parts = []
            if channel:
                parts.append("c")
            if ctx:
                parts.append("x")
            if fsm:
                parts.append("f")
            return "".join(parts)

        result = await m.call_tool("needs_deps", {"x": 1}, use_cache=False)
        assert result == "cxf"

    async def test_call_tool_disabled_returns_message(self):
        m = self._make_manager(disabled_tools=["blocked"])

        @tool(name="blocked")
        def blocked():
            return 1

        result = await m.call_tool("blocked", {}, use_cache=False)
        assert "在当前设备上不可用" in result

    async def test_call_tool_not_found(self):
        m = self._make_manager()
        result = await m.call_tool("nonexistent", {}, use_cache=False)
        assert "未找到工具" in result

    async def test_call_tool_caches_result(self):
        m = self._make_manager()
        call_count = {"n": 0}

        @tool()
        def counter(x: int):
            call_count["n"] += 1
            return f"r{x}"

        r1 = await m.call_tool("counter", {"x": 1}, use_cache=True)
        r2 = await m.call_tool("counter", {"x": 1}, use_cache=True)
        assert r1 == r2 == "r1"
        assert call_count["n"] == 1

    async def test_call_tool_builtin_exception_returns_message(self):
        m = self._make_manager()

        @tool()
        def boom(x: int):
            raise ValueError("kaboom")

        result = await m.call_tool("boom", {"x": 1}, use_cache=False)
        assert "工具执行异常" in result

    async def test_call_tool_propagates_stop_pipeline(self):
        m = self._make_manager()

        @tool()
        def stopper():
            raise StopPipeline()

        with pytest.raises(StopPipeline):
            await m.call_tool("stopper", {}, use_cache=False)

    async def test_call_tool_mcp_client_direct(self):
        """非 pool 模式：_mcp_tool_map 直接映射到 MCPClient"""
        m = self._make_manager()
        m._use_pool = False
        fake_client = MagicMock()
        fake_client.call_tool = AsyncMock(return_value="mcp_result")
        m._mcp_tool_map["mcp_t"] = fake_client

        result = await m.call_tool("mcp_t", {"a": 1}, use_cache=False)
        assert result == "mcp_result"

    async def test_call_tool_mcp_via_pool_with_breaker(self):
        """pool 模式 + 熔断器：_call_mcp_with_circuit_breaker"""
        m = self._make_manager()
        fake_pool = MagicMock()
        fake_client = MagicMock()
        fake_client.call_tool = AsyncMock(return_value="pool_result")
        fake_pool.acquire = AsyncMock(return_value=fake_client)
        fake_pool.release = AsyncMock()
        m._mcp_tool_map["mcp_t"] = ("srv", fake_pool)
        # 提供一个已关闭的熔断器（直接放行）
        m._circuit_breakers["srv"] = CircuitBreaker("srv")

        result = await m.call_tool("mcp_t", {"a": 1}, use_cache=False)
        assert result == "pool_result"
        fake_pool.release.assert_awaited()

    async def test_call_tool_mcp_via_pool_acquire_fails(self):
        m = self._make_manager()
        fake_pool = MagicMock()
        fake_pool.acquire = AsyncMock(return_value=None)
        fake_pool.release = AsyncMock()
        m._mcp_tool_map["mcp_t"] = ("srv", fake_pool)
        m._circuit_breakers["srv"] = CircuitBreaker("srv")

        result = await m.call_tool("mcp_t", {}, use_cache=False)
        assert "获取连接失败" in result

    async def test_call_tool_mcp_via_pool_without_breaker(self):
        m = self._make_manager()
        m._use_circuit_breaker = False
        fake_pool = MagicMock()
        fake_client = MagicMock()
        fake_client.call_tool = AsyncMock(return_value="ok")
        fake_pool.acquire = AsyncMock(return_value=fake_client)
        fake_pool.release = AsyncMock()
        m._mcp_tool_map["mcp_t"] = ("srv", fake_pool)

        result = await m.call_tool("mcp_t", {}, use_cache=False)
        assert result == "ok"

    async def test_call_tool_timeout_returns_message(self):
        m = self._make_manager(tool_timeout=1)

        @tool()
        async def slow():
            await asyncio.sleep(5)
            return "done"

        result = await m.call_tool("slow", {}, use_cache=False, max_retries=0)
        assert "超时" in result

    async def test_call_tool_retries_on_exception(self):
        """直接 mock _call_tool_internal 抛异常，验证 call_tool 的重试逻辑。
        注意：内置工具异常被 _call_tool_internal 内部捕获返回字符串，
        不会触发 call_tool 的重试；只有 _call_tool_internal 抛出的异常才触发重试。
        """
        m = self._make_manager(tool_max_retries=2)
        attempts = {"n": 0}

        async def fake_internal(tool_name, arguments):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise RuntimeError("retry me")
            return "finally"

        with patch.object(m, "_call_tool_internal", side_effect=fake_internal), \
                patch("asyncio.sleep", AsyncMock()):
            result = await m.call_tool("flaky", {}, use_cache=False, max_retries=2)
        assert result == "finally"
        assert attempts["n"] == 3

    async def test_call_tool_retries_exhausted_returns_failure(self):
        m = self._make_manager(tool_max_retries=1)

        async def always_fail(tool_name, arguments):
            raise RuntimeError("nope")

        with patch.object(m, "_call_tool_internal", side_effect=always_fail), \
                patch("asyncio.sleep", AsyncMock()):
            result = await m.call_tool("always_fail", {}, use_cache=False, max_retries=1)
        assert "调用失败" in result

    async def test_call_tool_with_cache_noop_when_cache_disabled(self):
        m = self._make_manager()
        m._use_cache = False
        call_count = {"n": 0}

        @tool()
        def counter(x: int):
            call_count["n"] += 1
            return f"r{x}"

        await m.call_tool("counter", {"x": 1}, use_cache=True)
        await m.call_tool("counter", {"x": 1}, use_cache=True)
        assert call_count["n"] == 2

    async def test_call_tools_batch_empty(self):
        m = self._make_manager()
        assert await m.call_tools_batch([]) == []

    async def test_call_tools_batch_parallel(self):
        m = self._make_manager()

        @tool()
        def t(x: int):
            return f"r{x}"

        results = await m.call_tools_batch(
            [("t", {"x": 1}), ("t", {"x": 2})], parallel=True
        )
        assert set(results) == {"r1", "r2"}

    async def test_call_tools_batch_sequential(self):
        m = self._make_manager()

        @tool()
        def t(x: int):
            return f"r{x}"

        results = await m.call_tools_batch(
            [("t", {"x": 1}), ("t", {"x": 2})], parallel=False
        )
        assert results == ["r1", "r2"]

    async def test_call_tools_batch_handles_exception(self):
        m = self._make_manager()

        @tool()
        def boom(x: int):
            raise RuntimeError("x")

        # 注意：内置工具异常被 _call_tool_internal 捕获并返回字符串
        # 这里测试 parallel 路径对 Exception 返回的处理
        results = await m.call_tools_batch([("boom", {"x": 1})], parallel=True)
        assert len(results) == 1

    async def test_call_tool_with_cache_alias(self):
        m = self._make_manager()

        @tool()
        def t(x: int):
            return f"r{x}"

        r = await m.call_tool_with_cache("t", {"x": 1}, use_cache=False)
        assert r == "r1"

    async def test_clear_cache(self):
        m = self._make_manager()
        await m._cache.set("t", {}, "v")
        assert m.get_cache_stats()["size"] == 1
        await m.clear_cache()
        assert m.get_cache_stats()["size"] == 0

    def test_get_cache_stats(self):
        m = self._make_manager()
        stats = m.get_cache_stats()
        assert "size" in stats
        assert "hit_rate" in stats

    def test_get_pool_stats(self):
        m = self._make_manager()
        # 无池时应返回空列表
        assert m.get_pool_stats() == []

    def test_get_circuit_breaker_stats(self):
        m = self._make_manager()
        assert m.get_circuit_breaker_stats() == {}

    async def test_reset_circuit_breaker_existing(self):
        m = self._make_manager()
        cb = CircuitBreaker("srv")
        m._circuit_breakers["srv"] = cb
        await m.reset_circuit_breaker("srv")
        assert cb.is_closed is True

    async def test_reset_circuit_breaker_nonexistent_is_noop(self):
        m = self._make_manager()
        # 不存在不应抛异常
        await m.reset_circuit_breaker("nope")

    def test_active_skills_management(self):
        m = self._make_manager()
        assert m.get_active_skills() == []
        assert m.is_skill_active("x") is False
        m.active_skills.add("x")
        assert m.is_skill_active("x") is True
        assert "x" in m.get_active_skills()

    def test_coerce_args_int_float_bool(self):
        m = self._make_manager()

        def fn(a: int, b: float, c: bool):
            return None

        coerced = m._coerce_args(fn, {"a": "3", "b": "1.5", "c": "true"})
        assert coerced["a"] == 3
        assert coerced["b"] == 1.5
        assert coerced["c"] is True

    def test_coerce_args_skips_self_and_special(self):
        m = self._make_manager()

        def fn(self, x: int, tool_manager=None, channel=None):
            return None

        coerced = m._coerce_args(fn, {"self": "obj", "x": "5", "tool_manager": "tm"})
        # self / tool_manager 等不应被转换
        assert coerced["self"] == "obj"
        assert coerced["x"] == 5
        assert coerced["tool_manager"] == "tm"

    def test_coerce_args_keeps_correct_type(self):
        m = self._make_manager()

        def fn(a: int):
            return None

        coerced = m._coerce_args(fn, {"a": 5})
        assert coerced["a"] == 5

    def test_coerce_args_invalid_value_kept_as_is(self):
        m = self._make_manager()

        def fn(a: int):
            return None

        coerced = m._coerce_args(fn, {"a": "not_a_number"})
        # 转换失败时保留原值
        assert coerced["a"] == "not_a_number"

    async def test_initialize_mcp_no_servers_returns(self):
        m = self._make_manager()
        # 无 mcp_servers 应直接返回
        await m.initialize_mcp(None)
        assert m._mcp_pools == {}

    async def test_initialize_mcp_with_disabled_server(self):
        m = self._make_manager()
        await m.initialize_mcp(
            mcp_servers={"a": {"url": "http://a"}},
            disabled_servers=["a"],
        )
        assert "a" not in m._mcp_pools

    async def test_initialize_mcp_with_pool_success(self):
        m = self._make_manager()
        # mock pool.initialize / acquire / release / client.get_tools_schema
        fake_client = MagicMock()
        fake_client.get_tools_schema.return_value = [
            {"type": "function", "function": {"name": "mcp_tool"}}
        ]
        fake_client.connected = True

        with patch.object(MCPPool, "initialize", AsyncMock()) as mock_init, \
                patch.object(MCPPool, "acquire", AsyncMock(return_value=fake_client)), \
                patch.object(MCPPool, "release", AsyncMock()), \
                patch.object(CircuitBreakerManager, "get_breaker", AsyncMock(return_value=CircuitBreaker("a"))):
            await m.initialize_mcp(
                mcp_servers={"a": {"url": "http://a"}},
            )
        mock_init.assert_awaited()
        assert "mcp_tool" in m._mcp_tool_map
        assert "a" in m._mcp_pools

    async def test_initialize_mcp_with_disabled_tools_filter(self):
        m = self._make_manager()
        fake_client = MagicMock()
        fake_client.get_tools_schema.return_value = [
            {"type": "function", "function": {"name": "keep"}},
            {"type": "function", "function": {"name": "drop"}},
        ]
        fake_client.connected = True

        with patch.object(MCPPool, "initialize", AsyncMock()), \
                patch.object(MCPPool, "acquire", AsyncMock(return_value=fake_client)), \
                patch.object(MCPPool, "release", AsyncMock()), \
                patch.object(CircuitBreakerManager, "get_breaker", AsyncMock(return_value=CircuitBreaker("a"))):
            await m.initialize_mcp(
                mcp_servers={"a": {"url": "http://a"}},
                disabled_tools={"a": ["drop"]},
            )
        # drop 应被过滤掉
        assert "drop" not in m._mcp_tool_map
        assert "keep" in m._mcp_tool_map

    async def test_initialize_mcp_no_pool_mode(self):
        m = self._make_manager()
        m._use_pool = False
        fake_schemas = [{"type": "function", "function": {"name": "t1"}}]

        with patch.object(MCPClient, "connect", _fake_connect_success), \
                patch.object(MCPClient, "get_tools_schema", return_value=fake_schemas), \
                patch.object(CircuitBreakerManager, "get_breaker", AsyncMock(return_value=CircuitBreaker("a"))):
            await m.initialize_mcp(mcp_servers={"a": {"url": "http://a"}})
        assert "t1" in m._mcp_tool_map

    async def test_cleanup(self):
        m = self._make_manager()
        fake_pool = MagicMock()
        fake_pool.close = AsyncMock()
        m._mcp_pools["a"] = fake_pool
        fake_client = MagicMock()
        fake_client.disconnect = AsyncMock()
        m._mcp_clients.append(fake_client)
        m._mcp_tool_map["x"] = fake_client

        await m.cleanup()
        fake_pool.close.assert_awaited()
        fake_client.disconnect.assert_awaited()
        assert m._mcp_pools == {}
        assert m._mcp_clients == []
        assert m._mcp_tool_map == {}


# ============================================================
# create_tool_manager 工厂
# ============================================================


class TestCreateToolManager:
    """create_tool_manager 工厂函数"""

    def test_create_with_default_config(self):
        m = create_tool_manager()
        assert isinstance(m, PerUserToolManager)
        assert m._tool_timeout == 15
        assert m._tool_max_retries == 1

    def test_create_with_custom_config(self):
        m = create_tool_manager({"tool_timeout": 30, "tool_max_retries": 3})
        assert m._tool_timeout == 30
        assert m._tool_max_retries == 3
