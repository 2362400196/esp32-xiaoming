"""
OpenAILLMGateway 单元测试

覆盖范围：
- 构造函数与配置解析（_resolve_config）
- 重试机制（_retry）：成功 / 429 / 连接错误 / 超时 / 5xx / 4xx / 耗尽
- 工具参数构建（_get_tools_param / _build_kwargs）
- 流式与非流式生成（stream_chat / process_text / generate / generate_stream / stream_with_tools）
- 工具调用执行（call_tool / _execute_tool_calls）
- 工厂函数 create_llm_gateway
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openai import APIConnectionError, APIError, APITimeoutError, RateLimitError

from src.interfaces.llm_gateways import OpenAILLMGateway, create_llm_gateway
from src.use_cases.tools_system import StopPipeline


# ─── 辅助：构造 Mock settings / 流式响应 ───────────────────

def make_mock_settings(api_key="default-key", base_url="http://default", model="gpt-4",
                       system_prompt="you are helpful"):
    """构造一个模拟的 settings 对象，提供 llm 子配置"""
    settings = MagicMock()
    settings.llm.api_key = api_key
    settings.llm.base_url = base_url
    settings.llm.model = model
    settings.llm.system_prompt = system_prompt
    settings.llm.temperature = 0.7
    settings.llm.max_tokens = 2000
    return settings


class FakeDelta:
    """模拟 OpenAI 流式响应的 delta 对象"""

    def __init__(self, content=None, tool_calls=None, reasoning_content=None):
        self.content = content
        self.tool_calls = tool_calls
        self.reasoning_content = reasoning_content


class FakeChoice:
    def __init__(self, delta):
        self.delta = delta


class FakeChunk:
    """模拟流式响应中的一个 chunk"""

    def __init__(self, delta=None, usage=None):
        self.choices = [FakeChoice(delta)] if delta is not None else []
        self.usage = usage


class FakeStreamResponse:
    """模拟流式响应（异步迭代器）"""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        self._iter = iter(self._chunks)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class FakeFunction:
    def __init__(self, name=None, arguments=None):
        self.name = name
        self.arguments = arguments


class FakeDeltaToolCall:
    """模拟流式 delta 中的 tool_call"""

    def __init__(self, index=0, id="tc1", name=None, arguments=None):
        self.index = index
        self.id = id
        self.function = FakeFunction(name, arguments)


class FakeMessageToolCall:
    """模拟非流式 message.tool_calls 元素"""

    def __init__(self, id="tc1", name="get_weather", arguments='{"city":"sh"}'):
        self.id = id
        self.type = "function"
        self.function = FakeFunction(name, arguments)


class FakeMessage:
    def __init__(self, content="", tool_calls=None, reasoning_content=None):
        self.content = content
        self.tool_calls = tool_calls
        self.reasoning_content = reasoning_content


class FakeChoiceNonStream:
    def __init__(self, message):
        self.message = message


class FakeNonStreamResponse:
    """模拟非流式 chat completion 响应"""

    def __init__(self, content="", tool_calls=None):
        self.choices = [FakeChoiceNonStream(FakeMessage(content, tool_calls))]


def _mock_metric():
    """构造一个模拟的 prometheus 指标对象，支持链式 labels().observe()/inc()"""
    m = MagicMock()
    m.labels.return_value = m
    return m


@pytest.fixture
def patched_llm():
    """在整个测试期间 patch get_settings、AsyncOpenAI 与监控指标，并返回控制句柄"""
    settings = make_mock_settings()
    metrics_patches = {
        "LLM_COMPLETION_DURATION": _mock_metric(),
        "LLM_COMPLETION_TOTAL": _mock_metric(),
        "LLM_FIRST_TOKEN_LATENCY": _mock_metric(),
    }
    with patch("src.interfaces.llm_gateways.get_settings", return_value=settings) as m_settings, \
            patch("src.interfaces.llm_gateways.AsyncOpenAI") as m_openai, \
            patch.multiple("src.interfaces.llm_gateways", **metrics_patches):
        mock_client = MagicMock()
        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = AsyncMock()
        m_openai.return_value = mock_client
        yield {
            "settings": settings,
            "AsyncOpenAI": m_openai,
            "client": mock_client,
        }


# ─── 构造函数测试 ──────────────────────────────────────────

class TestOpenAILLMGatewayInit:
    """构造函数与配置初始化测试"""

    def test_init_with_config(self, patched_llm):
        # 通过 config 显式提供所有字段
        config = {
            "api_key": "abc",
            "base_url": "http://x",
            "model": "gpt-test",
            "system_prompt": "hi",
            "temperature": 0.3,
            "max_tokens": 500,
        }
        gw = OpenAILLMGateway(config=config)
        assert gw.api_key == "abc"
        assert gw.base_url == "http://x"
        assert gw.model == "gpt-test"
        assert gw.system_prompt == "hi"
        assert gw.temperature == 0.3
        assert gw.max_tokens == 500
        assert gw.client is not None
        # AsyncOpenAI 应以传入的 api_key 与 base_url 被调用
        patched_llm["AsyncOpenAI"].assert_called_with(api_key="abc", base_url="http://x")

    def test_init_falls_back_to_settings(self, patched_llm):
        # config 为空时回退到 settings
        gw = OpenAILLMGateway(config=None)
        assert gw.api_key == "default-key"
        assert gw.base_url == "http://default"
        assert gw.model == "gpt-4"
        assert gw.system_prompt == "you are helpful"
        assert gw.client is not None

    def test_init_no_api_key_no_client(self, patched_llm):
        # api_key 为空时不创建 client
        patched_llm["settings"].llm.api_key = ""
        gw = OpenAILLMGateway(config={})
        assert gw.api_key == ""
        assert gw.client is None

    def test_init_empty_config(self, patched_llm):
        gw = OpenAILLMGateway(config={})
        assert gw.api_key == "default-key"
        assert gw.temperature == 0.7
        assert gw.max_tokens == 2000

    def test_init_with_tool_manager(self, patched_llm):
        tm = MagicMock()
        gw = OpenAILLMGateway(config={"api_key": "k"}, tool_manager=tm)
        assert gw.tool_manager is tm


# ─── _resolve_config 测试 ──────────────────────────────────

class TestResolveConfig:
    """配置解析逻辑测试"""

    def test_resolve_no_user_config(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k", "base_url": "http://x", "model": "m"})
        client, model, system_prompt = gw._resolve_config(None, None)
        assert client is gw.client
        assert model == "m"
        assert system_prompt == "you are helpful"

    def test_resolve_dict_user_config(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        user_config = {"api_key": "new", "base_url": "http://new", "model": "gpt-new",
                       "system_prompt": "sp"}
        client, model, system_prompt = gw._resolve_config(user_config, None)
        # api_key 变化应触发新建 client
        assert client is not None
        assert model == "gpt-new"
        assert system_prompt == "sp"
        patched_llm["AsyncOpenAI"].assert_called_with(api_key="new", base_url="http://new")

    def test_resolve_dict_device_overrides(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        user_config = {
            "model": "base-model",
            "system_prompt": "base-sp",
            "device_overrides": {
                "dev1": {"model": "dev-model", "system_prompt": "dev-sp"},
            },
        }
        _, model, system_prompt = gw._resolve_config(user_config, "dev1")
        assert model == "dev-model"
        assert system_prompt == "dev-sp"

    def test_resolve_dict_device_overrides_partial(self, patched_llm):
        # 设备覆盖只覆盖 model，system_prompt 保持父级
        gw = OpenAILLMGateway(config={"api_key": "k"})
        user_config = {
            "model": "base-model",
            "system_prompt": "base-sp",
            "device_overrides": {"dev1": {"model": "dev-model"}},
        }
        _, model, system_prompt = gw._resolve_config(user_config, "dev1")
        assert model == "dev-model"
        assert system_prompt == "base-sp"

    def test_resolve_object_user_config(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        user_config = MagicMock()
        user_config.llm_api_key = "obj-key"
        user_config.llm_base_url = "http://obj"
        user_config.llm_model = "obj-model"
        user_config.llm_system_prompt = "obj-sp"
        user_config.get_effective_llm_model = lambda did: None
        user_config.get_effective_llm_system_prompt = lambda did: None
        client, model, system_prompt = gw._resolve_config(user_config, None)
        assert model == "obj-model"
        assert system_prompt == "obj-sp"
        # api_key 变化应新建 client
        assert client is not None

    def test_resolve_object_user_config_with_device_effective(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        user_config = MagicMock()
        user_config.llm_api_key = ""
        user_config.llm_base_url = ""
        user_config.llm_model = ""
        user_config.llm_system_prompt = ""
        user_config.get_effective_llm_model = lambda did: "eff-model" if did == "d1" else None
        user_config.get_effective_llm_system_prompt = lambda did: "eff-sp" if did == "d1" else None
        _, model, system_prompt = gw._resolve_config(user_config, "d1")
        assert model == "eff-model"
        assert system_prompt == "eff-sp"

    def test_resolve_same_api_key_reuses_client(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k", "base_url": "http://x"})
        original_client = gw.client
        # user_config 不改变 api_key/base_url，应复用 client
        client, _, _ = gw._resolve_config({"model": "other"}, None)
        assert client is original_client


# ─── _retry 测试 ───────────────────────────────────────────

class TestRetry:
    """重试机制测试"""

    async def test_retry_success_first_attempt(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        fn = AsyncMock(return_value="ok")
        result = await gw._retry(fn)
        assert result == "ok"
        fn.assert_awaited_once()

    async def test_retry_rate_limit_then_success(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        fn = AsyncMock(side_effect=[RateLimitError("429", response=MagicMock(), body=None), "ok"])
        with patch("src.interfaces.llm_gateways.asyncio.sleep", new=AsyncMock()):
            result = await gw._retry(fn)
        assert result == "ok"
        assert fn.await_count == 2

    async def test_retry_connection_error_then_success(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        fn = AsyncMock(side_effect=[APIConnectionError(request=MagicMock()), "ok"])
        with patch("src.interfaces.llm_gateways.asyncio.sleep", new=AsyncMock()):
            result = await gw._retry(fn)
        assert result == "ok"

    async def test_retry_timeout_then_success(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        fn = AsyncMock(side_effect=[APITimeoutError(request=MagicMock()), "ok"])
        with patch("src.interfaces.llm_gateways.asyncio.sleep", new=AsyncMock()):
            result = await gw._retry(fn)
        assert result == "ok"

    async def test_retry_server_error_5xx_then_success(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        err = APIError("server", request=MagicMock(), body=None)
        err.status_code = 500
        fn = AsyncMock(side_effect=[err, "ok"])
        with patch("src.interfaces.llm_gateways.asyncio.sleep", new=AsyncMock()):
            result = await gw._retry(fn)
        assert result == "ok"

    async def test_retry_client_error_4xx_raises_immediately(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        err = APIError("client", request=MagicMock(), body=None)
        err.status_code = 400
        fn = AsyncMock(side_effect=err)
        with patch("src.interfaces.llm_gateways.asyncio.sleep", new=AsyncMock()):
            with pytest.raises(APIError):
                await gw._retry(fn)
        # 4xx 不重试，只调用一次
        assert fn.await_count == 1

    async def test_retry_exhausted_raises_last(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        err = RateLimitError("429", response=MagicMock(), body=None)
        fn = AsyncMock(side_effect=err)
        with patch("src.interfaces.llm_gateways.asyncio.sleep", new=AsyncMock()):
            with pytest.raises(RateLimitError):
                await gw._retry(fn)
        # LLM_MAX_RETRIES 次
        assert fn.await_count == 3


# ─── 工具参数构建测试 ──────────────────────────────────────

class TestToolsParam:
    """_get_tools_param 与 _build_kwargs 测试"""

    def test_get_tools_param_no_manager(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        assert gw._get_tools_param() is None

    def test_get_tools_param_empty_schemas(self, patched_llm):
        tm = MagicMock()
        tm.get_all_tools_schema.return_value = []
        gw = OpenAILLMGateway(config={"api_key": "k"}, tool_manager=tm)
        assert gw._get_tools_param() is None

    def test_get_tools_param_with_schemas(self, patched_llm):
        tm = MagicMock()
        schemas = [{"type": "function", "function": {"name": "f"}}]
        tm.get_all_tools_schema.return_value = schemas
        gw = OpenAILLMGateway(config={"api_key": "k"}, tool_manager=tm)
        assert gw._get_tools_param() == schemas

    def test_build_kwargs_default(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k", "model": "m"})
        kwargs = gw._build_kwargs([{"role": "user", "content": "hi"}])
        assert kwargs["model"] == "m"
        assert kwargs["stream"] is True
        assert kwargs["messages"] == [{"role": "user", "content": "hi"}]
        assert "tools" not in kwargs

    def test_build_kwargs_with_explicit_model_and_tools(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        kwargs = gw._build_kwargs([], stream=False, model="other", tools_param=[{"x": 1}])
        assert kwargs["model"] == "other"
        assert kwargs["stream"] is False
        assert kwargs["tools"] == [{"x": 1}]


# ─── stream_chat 测试 ──────────────────────────────────────

class TestStreamChat:
    """stream_chat 流式对话测试"""

    async def test_stream_chat_no_client(self, patched_llm):
        patched_llm["settings"].llm.api_key = ""
        gw = OpenAILLMGateway(config={})
        results = []
        async for chunk in gw.stream_chat([{"role": "user", "content": "hi"}]):
            results.append(chunk)
        assert results == ["LLM not configured - this is a mock response"]

    async def test_stream_chat_simple_content(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        chunks = [FakeChunk(FakeDelta(content="hello")), FakeChunk(FakeDelta(content=" world"))]
        patched_llm["client"].chat.completions.create.return_value = FakeStreamResponse(chunks)
        results = []
        async for chunk in gw.stream_chat([{"role": "user", "content": "hi"}]):
            results.append(chunk)
        assert "".join(results) == "hello world"

    async def test_stream_chat_with_tool_calls(self, patched_llm):
        # 工具调用场景：第一轮返回工具调用，工具执行后第二轮返回最终文本
        tm = MagicMock()
        tm.channel = None  # 避免 send_json 路径
        tm.call_tool = AsyncMock(return_value="sunny")
        tm.get_all_tools_schema.return_value = [{"type": "function", "function": {"name": "get_weather"}}]
        gw = OpenAILLMGateway(config={"api_key": "k"}, tool_manager=tm)

        round1 = [FakeChunk(FakeDelta(content="let me check",
                                       tool_calls=[FakeDeltaToolCall(index=0, id="tc1",
                                                                      name="get_weather",
                                                                      arguments='{"city":"sh"}')]))]
        round2 = [FakeChunk(FakeDelta(content="final answer"))]
        patched_llm["client"].chat.completions.create.side_effect = [
            FakeStreamResponse(round1), FakeStreamResponse(round2),
        ]
        results = []
        async for chunk in gw.stream_chat([{"role": "user", "content": "weather?"}]):
            results.append(chunk)
        joined = "".join(results)
        assert "let me check" in joined
        assert "final answer" in joined
        tm.call_tool.assert_awaited()

    async def test_stream_chat_tool_call_stop_pipeline(self, patched_llm):
        tm = MagicMock()
        tm.channel = None
        tm.call_tool = AsyncMock(side_effect=StopPipeline())
        tm.get_all_tools_schema.return_value = [{"type": "function", "function": {"name": "f"}}]
        gw = OpenAILLMGateway(config={"api_key": "k"}, tool_manager=tm)

        round1 = [FakeChunk(FakeDelta(content="",
                                       tool_calls=[FakeDeltaToolCall(index=0, id="tc1",
                                                                      name="f", arguments="{}")]))]
        patched_llm["client"].chat.completions.create.return_value = FakeStreamResponse(round1)
        results = []
        async for chunk in gw.stream_chat([{"role": "user", "content": "hi"}]):
            results.append(chunk)
        assert "__STOP_PIPELINE__" in results

    async def test_stream_chat_exception_yields_error(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        patched_llm["client"].chat.completions.create.side_effect = RuntimeError("boom")
        results = []
        async for chunk in gw.stream_chat([{"role": "user", "content": "hi"}]):
            results.append(chunk)
        assert any("LLM error" in r for r in results)

    async def test_stream_chat_auto_read_skill_document(self, patched_llm):
        # 文本中出现 read_skill_document('diary') 应自动触发工具调用
        tm = MagicMock()
        tm.channel = None
        tm.call_tool = AsyncMock(return_value="doc content")
        tm.get_all_tools_schema.return_value = []
        gw = OpenAILLMGateway(config={"api_key": "k"}, tool_manager=tm)

        round1 = [FakeChunk(FakeDelta(content="read_skill_document('diary')"))]
        round2 = [FakeChunk(FakeDelta(content="done"))]
        patched_llm["client"].chat.completions.create.side_effect = [
            FakeStreamResponse(round1), FakeStreamResponse(round2),
        ]
        results = []
        async for chunk in gw.stream_chat([{"role": "user", "content": "hi"}]):
            results.append(chunk)
        tm.call_tool.assert_awaited()
        assert "done" in "".join(results)


# ─── process_text 测试 ─────────────────────────────────────

class TestProcessText:
    """process_text 非流式文本处理测试"""

    async def test_process_text_no_client(self, patched_llm):
        patched_llm["settings"].llm.api_key = ""
        gw = OpenAILLMGateway(config={})
        result = await gw.process_text("hello")
        assert "mock response" in result

    async def test_process_text_success(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        patched_llm["client"].chat.completions.create.return_value = FakeNonStreamResponse(content="hi there")
        result = await gw.process_text("hello")
        assert result == "hi there"

    async def test_process_text_exception(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        patched_llm["client"].chat.completions.create.side_effect = RuntimeError("boom")
        result = await gw.process_text("hello")
        assert "LLM request failed" in result


# ─── generate / generate_stream 测试 ───────────────────────

class TestGenerate:
    """generate / generate_stream 测试"""

    async def test_generate_no_client(self, patched_llm):
        patched_llm["settings"].llm.api_key = ""
        gw = OpenAILLMGateway(config={})
        result = await gw.generate([{"role": "user", "content": "hi"}])
        assert "mock response" in result

    async def test_generate_prepends_system(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k", "system_prompt": "sp"})
        patched_llm["client"].chat.completions.create.return_value = FakeNonStreamResponse(content="ok")
        await gw.generate([{"role": "user", "content": "hi"}])
        call_kwargs = patched_llm["client"].chat.completions.create.await_args.kwargs
        messages = call_kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "sp"

    async def test_generate_keeps_existing_system(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k", "system_prompt": "sp"})
        patched_llm["client"].chat.completions.create.return_value = FakeNonStreamResponse(content="ok")
        msgs = [{"role": "system", "content": "existing"}, {"role": "user", "content": "hi"}]
        await gw.generate(msgs)
        call_kwargs = patched_llm["client"].chat.completions.create.await_args.kwargs
        assert call_kwargs["messages"][0]["content"] == "existing"

    async def test_generate_stream_no_client(self, patched_llm):
        patched_llm["settings"].llm.api_key = ""
        gw = OpenAILLMGateway(config={})
        results = []
        async for chunk in gw.generate_stream([{"role": "user", "content": "hi"}]):
            results.append(chunk)
        assert results == ["LLM not configured - this is a mock response"]

    async def test_generate_stream_simple(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        chunks = [FakeChunk(FakeDelta(content="a")), FakeChunk(FakeDelta(content="b"))]
        patched_llm["client"].chat.completions.create.return_value = FakeStreamResponse(chunks)
        results = []
        async for chunk in gw.generate_stream([{"role": "user", "content": "hi"}]):
            results.append(chunk)
        assert "".join(results) == "ab"

    async def test_generate_stream_with_tool_calls(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        chunks = [FakeChunk(FakeDelta(content="hi",
                                       tool_calls=[FakeDeltaToolCall(index=0, id="tc1",
                                                                      name="f", arguments="{}")]))]
        patched_llm["client"].chat.completions.create.return_value = FakeStreamResponse(chunks)
        results = []
        async for chunk in gw.generate_stream([{"role": "user", "content": "hi"}]):
            results.append(chunk)
        # 应包含 content 与 tool_calls JSON
        joined = "".join(results)
        assert "hi" in joined
        assert any("tool_calls" in r for r in results)


# ─── stream_with_tools 测试 ────────────────────────────────

class TestStreamWithTools:
    """stream_with_tools 非流式工具循环测试"""

    async def test_stream_with_tools_no_client(self, patched_llm):
        patched_llm["settings"].llm.api_key = ""
        gw = OpenAILLMGateway(config={})
        results = []
        async for chunk in gw.stream_with_tools("hi"):
            results.append(chunk)
        assert results == ["LLM not configured - this is a mock response"]

    async def test_stream_with_tools_no_tool_call(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        patched_llm["client"].chat.completions.create.return_value = FakeNonStreamResponse(content="answer")
        results = []
        async for chunk in gw.stream_with_tools("hi"):
            results.append(chunk)
        assert results == ["answer"]

    async def test_stream_with_tools_with_tool_call(self, patched_llm):
        tm = MagicMock()
        tm.call_tool = AsyncMock(return_value="ok")
        tm.get_all_tools_schema.return_value = [{"type": "function", "function": {"name": "f"}}]
        gw = OpenAILLMGateway(config={"api_key": "k"}, tool_manager=tm)
        tc = FakeMessageToolCall(id="tc1", name="get_weather", arguments='{"city":"sh"}')
        round1 = FakeNonStreamResponse(content="", tool_calls=[tc])
        round2 = FakeNonStreamResponse(content="final")
        patched_llm["client"].chat.completions.create.side_effect = [round1, round2]
        results = []
        async for chunk in gw.stream_with_tools("weather?"):
            results.append(chunk)
        assert "final" in results


# ─── generate_response_stream 测试 ─────────────────────────

class TestGenerateResponseStream:
    """generate_response_stream 测试（含监控指标）"""

    async def test_generate_response_stream_no_client(self, patched_llm):
        patched_llm["settings"].llm.api_key = ""
        gw = OpenAILLMGateway(config={})
        results = []
        async for chunk in gw.generate_response_stream("hi"):
            results.append(chunk)
        assert results == ["LLM not configured - this is a mock response"]

    async def test_generate_response_stream_simple(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        chunks = [FakeChunk(FakeDelta(content="hello"))]
        patched_llm["client"].chat.completions.create.return_value = FakeStreamResponse(chunks)
        results = []
        async for chunk in gw.generate_response_stream("hi"):
            results.append(chunk)
        assert "".join(results) == "hello"

    async def test_generate_response_stream_error(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        patched_llm["client"].chat.completions.create.side_effect = RuntimeError("boom")
        results = []
        async for chunk in gw.generate_response_stream("hi"):
            results.append(chunk)
        assert any("LLM request failed" in r for r in results)


# ─── call_tool 测试 ────────────────────────────────────────

class TestCallTool:
    """call_tool 方法测试"""

    async def test_call_tool_with_manager_success(self, patched_llm):
        tm = MagicMock()
        tm.call_tool = AsyncMock(return_value="result")
        gw = OpenAILLMGateway(config={"api_key": "k"}, tool_manager=tm)
        result = await gw.call_tool("f", {"a": 1})
        assert result == "result"
        tm.call_tool.assert_awaited_with("f", {"a": 1})

    async def test_call_tool_with_manager_exception(self, patched_llm):
        tm = MagicMock()
        tm.call_tool = AsyncMock(side_effect=ValueError("bad"))
        gw = OpenAILLMGateway(config={"api_key": "k"}, tool_manager=tm)
        result = await gw.call_tool("f", {})
        assert "error" in result
        assert "bad" in result["error"]

    async def test_call_tool_with_manager_stop_pipeline(self, patched_llm):
        tm = MagicMock()
        tm.call_tool = AsyncMock(side_effect=StopPipeline())
        gw = OpenAILLMGateway(config={"api_key": "k"}, tool_manager=tm)
        with pytest.raises(StopPipeline):
            await gw.call_tool("f", {})

    async def test_call_tool_with_tool_gateway(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        tg = MagicMock()
        tg.execute_tool = AsyncMock(return_value="gw-result")
        result = await gw.call_tool("f", {}, tool_gateway=tg)
        assert result == "gw-result"

    async def test_call_tool_no_manager_no_gateway(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        result = await gw.call_tool("f", {})
        assert "error" in result


# ─── _execute_tool_calls 测试 ──────────────────────────────

class TestExecuteToolCalls:
    """_execute_tool_calls 测试"""

    async def test_execute_tool_calls_with_manager(self, patched_llm):
        tm = MagicMock()
        tm.call_tool = AsyncMock(return_value="ok")
        gw = OpenAILLMGateway(config={"api_key": "k"}, tool_manager=tm)
        tc = FakeMessageToolCall(id="tc1", name="f", arguments='{"x":1}')
        result = await gw._execute_tool_calls([tc])
        data = json.loads(result)
        assert data[0]["role"] == "tool"
        assert data[0]["content"] == "ok"

    async def test_execute_tool_calls_no_manager(self, patched_llm):
        gw = OpenAILLMGateway(config={"api_key": "k"})
        tc = FakeMessageToolCall(id="tc1", name="f", arguments="{}")
        result = await gw._execute_tool_calls([tc])
        data = json.loads(result)
        assert "not initialized" in data[0]["content"]

    async def test_execute_tool_calls_invalid_json_args(self, patched_llm):
        tm = MagicMock()
        tm.call_tool = AsyncMock(return_value="ok")
        gw = OpenAILLMGateway(config={"api_key": "k"}, tool_manager=tm)
        tc = FakeMessageToolCall(id="tc1", name="f", arguments="not-json")
        await gw._execute_tool_calls([tc])
        # 无效 JSON 时应回退为空 dict 调用
        tm.call_tool.assert_awaited_with("f", {})


# ─── 工厂函数测试 ──────────────────────────────────────────

class TestCreateLLMGateway:
    """create_llm_gateway 工厂函数测试"""

    def test_create_returns_openai_gateway(self, patched_llm):
        gw = create_llm_gateway(config={"api_key": "k"})
        assert isinstance(gw, OpenAILLMGateway)
        assert gw.api_key == "k"

    def test_create_with_tool_manager(self, patched_llm):
        tm = MagicMock()
        gw = create_llm_gateway(config={"api_key": "k"}, tool_manager=tm)
        assert gw.tool_manager is tm

    def test_create_no_config(self, patched_llm):
        gw = create_llm_gateway()
        assert isinstance(gw, OpenAILLMGateway)
        assert gw.api_key == "default-key"
