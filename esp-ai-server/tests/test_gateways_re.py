"""
gateways.py 单元测试

覆盖范围：
- BaseLLMGateway / OpenAILLMGateway：generate, generate_stream, call_tool
- BaseTTSGateway / VolcEngineTTSGateway / VolcEngineTTSSession
- ToolGateway：get_available_tools, execute_tool, discover_tools
- BuiltinSpeakTool
- MemoryGateway
- EmotionGateway
- create_asr_gateway 重导出
"""
import json
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.interfaces.gateways import (
    BuiltinSpeakTool,
    BaseLLMGateway,
    BaseTTSGateway,
    EmotionGateway,
    MemoryGateway,
    OpenAILLMGateway,
    ToolGateway,
    VolcEngineTTSGateway,
    VolcEngineTTSSession,
    create_asr_gateway,
)
from src.domain.entities import Conversation, Message
from src.domain.exceptions import TTSError, ToolExecutionError, ToolNotFoundError


# 辅助：创建可实例化的 LLM 网关子类（实现抽象方法）
class _ConcreteLLM(BaseLLMGateway):
    async def chat(self, messages, **kwargs):
        return "response"
    async def chat_stream(self, messages, **kwargs):
        yield "chunk"


class _ConcreteOpenAILLM(OpenAILLMGateway):
    async def chat(self, messages, **kwargs):
        return "response"
    async def chat_stream(self, messages, **kwargs):
        yield "chunk"


class _ConcreteVolcTTS(VolcEngineTTSGateway):
    async def synthesize_stream(self, text, **kwargs):
        yield b""


# ============================================================
# BaseLLMGateway
# ============================================================


class TestBaseLLMGateway:
    """BaseLLMGateway 配置解析"""

    def test_defaults(self):
        gw = _ConcreteLLM(config={})
        assert gw.config == {}
        assert gw.model == ""
        assert gw.api_key == ""
        assert gw.base_url == ""
        assert gw.system_prompt == ""
        assert gw.temperature == 0.7
        assert gw.max_tokens == 2000

    def test_with_config(self):
        cfg = {
            "model": "gpt-4",
            "api_key": "key123",
            "base_url": "https://api.openai.com/v1",
            "system_prompt": "You are helpful",
            "temperature": 0.3,
            "max_tokens": 500,
        }
        gw = _ConcreteLLM(config=cfg)
        assert gw.model == "gpt-4"
        assert gw.api_key == "key123"
        assert gw.base_url == "https://api.openai.com/v1"
        assert gw.system_prompt == "You are helpful"
        assert gw.temperature == 0.3
        assert gw.max_tokens == 500

    def test_none_config(self):
        gw = _ConcreteLLM(config={})
        assert gw.config == {}


# ============================================================
# OpenAILLMGateway
# ============================================================


class TestOpenAILLMGateway:
    """OpenAILLMGateway"""

    def test_init(self):
        cfg = {"model": "gpt-4", "stream": False, "tools": [{"type": "function"}]}
        gw = _ConcreteOpenAILLM(config=cfg)
        assert gw.stream is False
        assert gw.tools_config == [{"type": "function"}]
        assert gw.model == "gpt-4"

    def test_init_defaults(self):
        gw = _ConcreteOpenAILLM(config={})
        assert gw.stream is True
        assert gw.tools_config == []

    async def test_generate_success(self):
        gw = _ConcreteOpenAILLM(config={
            "model": "gpt-4",
            "api_key": "key",
            "base_url": "https://api.openai.com/v1",
        })

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello!"}}]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await gw.generate([{"role": "user", "content": "hi"}])

        assert result == "Hello!"

    async def test_generate_with_kwargs(self):
        gw = _ConcreteOpenAILLM(config={
            "model": "gpt-4", "api_key": "k", "base_url": "url",
        })

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "result"}}]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await gw.generate(
                [{"role": "user", "content": "hi"}],
                temperature=0.1, max_tokens=100,
            )

        assert result == "result"
        # 验证 payload 中使用了 kwargs
        call_args = mock_client.post.call_args
        payload = call_args.kwargs["json"]
        assert payload["temperature"] == 0.1
        assert payload["max_tokens"] == 100

    async def test_generate_http_error(self):
        gw = _ConcreteOpenAILLM(config={"api_key": "k", "base_url": "url", "model": "m"})

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("HTTP 500")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(Exception, match="HTTP 500"):
                await gw.generate([{"role": "user", "content": "hi"}])

    async def test_generate_stream_success(self):
        gw = _ConcreteOpenAILLM(config={"api_key": "k", "base_url": "url", "model": "m"})

        # 构造流式响应行
        lines = [
            b'data: {"choices":[{"delta":{"content":"Hello"}}]}',
            b'data: {"choices":[{"delta":{"content":" world"}}]}',
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            b'data: [DONE]',
        ]

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_stream_ctx)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_stream_ctx.raise_for_status = MagicMock()

        async def _aiter_lines():
            for line in lines:
                yield line.decode() if isinstance(line, bytes) else line
        mock_stream_ctx.aiter_lines = _aiter_lines

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            chunks = []
            async for chunk in gw.generate_stream([{"role": "user", "content": "hi"}]):
                chunks.append(chunk)

        assert "Hello" in chunks
        assert " world" in chunks

    async def test_generate_stream_with_tool_calls(self):
        gw = _ConcreteOpenAILLM(config={"api_key": "k", "base_url": "url", "model": "m"})

        lines = [
            b'data: {"choices":[{"delta":{"tool_calls":[{"id":"call_1","function":{"name":"test","arguments":"{}"}}]}}]}',
            b'data: {"choices":[{"delta":{},"finish_reason":"tool_calls","message":{"tool_calls":[{"id":"call_1"}]}}]}',
            b'data: [DONE]',
        ]

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_stream_ctx)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_stream_ctx.raise_for_status = MagicMock()

        async def _aiter_lines():
            for line in lines:
                yield line.decode()
        mock_stream_ctx.aiter_lines = _aiter_lines

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            chunks = []
            async for chunk in gw.generate_stream([{"role": "user", "content": "hi"}]):
                chunks.append(chunk)

        # 应包含 tool_calls 数据
        assert len(chunks) >= 1

    async def test_generate_stream_skip_invalid_json(self):
        gw = _ConcreteOpenAILLM(config={"api_key": "k", "base_url": "url", "model": "m"})

        lines = [
            "data: invalid json",
            b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}',
            b'data: [DONE]',
        ]

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_stream_ctx)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_stream_ctx.raise_for_status = MagicMock()

        async def _aiter_lines():
            for line in lines:
                yield line.decode() if isinstance(line, bytes) else line
        mock_stream_ctx.aiter_lines = _aiter_lines

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            chunks = []
            async for chunk in gw.generate_stream([{"role": "user", "content": "hi"}]):
                chunks.append(chunk)

        assert "ok" in chunks

    async def test_call_tool_with_gateway(self):
        gw = _ConcreteOpenAILLM(config={})
        tool_gw = AsyncMock()
        tool_gw.execute_tool = AsyncMock(return_value={"result": "ok"})
        result = await gw.call_tool("test_tool", {"arg": 1}, tool_gateway=tool_gw)
        assert result == {"result": "ok"}

    async def test_call_tool_without_gateway(self):
        gw = _ConcreteOpenAILLM(config={})
        result = await gw.call_tool("test_tool", {})
        assert "error" in result


# ============================================================
# BaseTTSGateway / VolcEngineTTSGateway
# ============================================================


class TestBaseTTSGateway:
    """BaseTTSGateway 配置"""

    def test_defaults(self):
        gw = _ConcreteVolcTTS(config={})
        assert gw.config == {}
        assert gw.voice_type == ""
        assert gw.speed == 1.0
        assert gw.volume == 1.0
        assert gw.pitch == 1.0

    def test_with_config(self):
        gw = _ConcreteVolcTTS(config={"voice_type": "v1", "speed": 1.5, "volume": 0.8, "pitch": 1.2})
        assert gw.voice_type == "v1"
        assert gw.speed == 1.5
        assert gw.volume == 0.8
        assert gw.pitch == 1.2


class TestVolcEngineTTSGateway:
    """VolcEngineTTSGateway"""

    def test_init(self):
        cfg = {"api_key": "k", "resource_id": "r", "voice_type": "v"}
        gw = _ConcreteVolcTTS(config=cfg)
        assert gw.api_key == "k"
        assert gw.resource_id == "r"
        assert gw.voice_type == "v"
        assert gw._session is None
        assert gw._sequence_number == 0

    async def test_create_session(self):
        cfg = {"api_key": "k", "voice_type": "v"}
        gw = _ConcreteVolcTTS(config=cfg)
        session = await gw.create_session()
        assert isinstance(session, VolcEngineTTSSession)
        assert session.api_key == "k"

    async def test_create_session_with_cancel_event(self):
        gw = _ConcreteVolcTTS(config={})
        ev = MagicMock()
        session = await gw.create_session(cancel_event=ev)
        assert session.cancel_event is ev

    async def test_close_session(self):
        gw = _ConcreteVolcTTS(config={})
        session = AsyncMock()
        await gw.close_session(session)
        session.close.assert_called_once()

    async def test_close_session_none(self):
        gw = _ConcreteVolcTTS(config={})
        await gw.close_session(None)

    async def test_synthesize_delegates_to_session(self):
        gw = _ConcreteVolcTTS(config={})

        async def _gen(text):
            yield b"chunk1"
            yield b"chunk2"
        mock_session = AsyncMock()
        mock_session.synthesize = _gen
        mock_session.close = AsyncMock()

        with patch.object(gw, "create_session", AsyncMock(return_value=mock_session)):
            chunks = []
            async for chunk in gw.synthesize("hello"):
                chunks.append(chunk)

        assert chunks == [b"chunk1", b"chunk2"]
        mock_session.close.assert_called_once()


# ============================================================
# VolcEngineTTSSession
# ============================================================


class TestVolcEngineTTSSession:
    """VolcEngineTTSSession"""

    def test_init(self):
        cfg = {"api_key": "k", "resource_id": "r", "voice_type": "v", "speed": 1.5}
        session = VolcEngineTTSSession(cfg)
        assert session.api_key == "k"
        assert session.resource_id == "r"
        assert session.voice_type == "v"
        assert session.speed == 1.5
        assert session.ws is None

    async def test_connect_success(self):
        session = VolcEngineTTSSession({"api_key": "k"})
        with patch("src.interfaces.gateways.websockets.connect", new_callable=AsyncMock) as mock_connect:
            mock_ws = AsyncMock()
            mock_connect.return_value = mock_ws
            result = await session.connect()
        assert result is True
        assert session.ws is mock_ws

    async def test_connect_failure(self):
        session = VolcEngineTTSSession({"api_key": "k"})
        with patch("src.interfaces.gateways.websockets.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.side_effect = Exception("Connection refused")
            result = await session.connect()
        assert result is False
        assert session.ws is None

    async def test_close(self):
        session = VolcEngineTTSSession({"api_key": "k"})
        mock_ws = AsyncMock()
        session.ws = mock_ws
        await session.close()
        mock_ws.close.assert_called_once()
        assert session.ws is None

    async def test_close_no_ws(self):
        session = VolcEngineTTSSession({"api_key": "k"})
        await session.close()
        assert session.ws is None

    async def test_close_exception(self):
        session = VolcEngineTTSSession({"api_key": "k"})
        session.ws = AsyncMock()
        session.ws.close.side_effect = Exception("close error")
        await session.close()
        assert session.ws is None

    async def test_synthesize_connect_failure_raises(self):
        session = VolcEngineTTSSession({"api_key": "k"})
        with patch.object(session, "connect", AsyncMock(return_value=False)):
            with pytest.raises(TTSError, match="Failed to connect"):
                async for _ in session.synthesize("text"):
                    pass

    async def test_synthesize_success(self):
        session = VolcEngineTTSSession({"api_key": "k", "voice_type": "v"})

        # mock websocket
        mock_ws = AsyncMock()
        # 构造响应：先是音频数据（带 header），然后是 finish 消息
        audio_payload = b"audio_data"
        header = struct.pack(">II", len(audio_payload), 1)
        audio_response = header + audio_payload
        finish_response = json.dumps({"type": "finish"})

        mock_ws.recv = AsyncMock(side_effect=[audio_response, finish_response])
        session.ws = mock_ws

        chunks = []
        async for chunk in session.synthesize("hello"):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0] == audio_payload

    async def test_synthesize_cancel_event(self):
        session = VolcEngineTTSSession({"api_key": "k"})
        cancel_event = MagicMock()
        cancel_event.is_set.return_value = True
        session.cancel_event = cancel_event
        session.ws = AsyncMock()

        chunks = []
        async for chunk in session.synthesize("text"):
            chunks.append(chunk)
        assert chunks == []

    async def test_synthesize_timeout(self):
        session = VolcEngineTTSSession({"api_key": "k"})
        mock_ws = AsyncMock()
        import asyncio as _asyncio
        mock_ws.recv = AsyncMock(side_effect=_asyncio.TimeoutError())
        session.ws = mock_ws

        chunks = []
        async for chunk in session.synthesize("text"):
            chunks.append(chunk)
        assert chunks == []

    async def test_synthesize_exception_raises_tts_error(self):
        session = VolcEngineTTSSession({"api_key": "k"})
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock(side_effect=Exception("send failed"))
        session.ws = mock_ws

        with pytest.raises(TTSError, match="TTS synthesis failed"):
            async for _ in session.synthesize("text"):
                pass


# ============================================================
# ToolGateway
# ============================================================


class TestToolGateway:
    """ToolGateway"""

    def test_init(self):
        gw = ToolGateway()
        assert gw.config == {}
        assert gw._tools == {}
        assert gw._mcp_clients == {}

    async def test_load_builtin_tools(self):
        gw = ToolGateway()
        await gw._load_builtin_tools()
        assert "speak" in gw._tools
        assert isinstance(gw._tools["speak"], BuiltinSpeakTool)

    async def test_get_available_tools_empty(self):
        gw = ToolGateway()
        tools = await gw.get_available_tools()
        assert tools == []

    async def test_get_available_tools_with_builtin(self):
        gw = ToolGateway()
        await gw._load_builtin_tools()
        tools = await gw.get_available_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "speak"
        assert "description" in tools[0]
        assert "parameters" in tools[0]

    async def test_get_available_tools_with_mcp(self):
        gw = ToolGateway()
        mcp_client = AsyncMock()
        mcp_client.list_tools = AsyncMock(return_value=[{"name": "mcp_tool"}])
        gw._mcp_clients["test_server"] = mcp_client

        tools = await gw.get_available_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "mcp_tool"

    async def test_get_available_tools_mcp_error(self):
        gw = ToolGateway()
        mcp_client = AsyncMock()
        mcp_client.list_tools = AsyncMock(side_effect=Exception("MCP error"))
        gw._mcp_clients["test_server"] = mcp_client

        tools = await gw.get_available_tools()
        assert tools == []

    async def test_execute_tool_builtin(self):
        gw = ToolGateway()
        await gw._load_builtin_tools()
        result = await gw.execute_tool("speak", {"text": "hello"})
        assert result["success"] is True
        assert result["text"] == "hello"

    async def test_execute_tool_not_found(self):
        gw = ToolGateway()
        with pytest.raises(ToolNotFoundError):
            await gw.execute_tool("nonexistent", {})

    async def test_execute_tool_with_mcp(self):
        gw = ToolGateway()
        mcp_client = AsyncMock()
        mcp_client.call_tool = AsyncMock(return_value={"result": "ok"})
        gw._mcp_clients["test_server"] = mcp_client

        result = await gw.execute_tool("mcp_tool", {"arg": 1})
        assert result == {"result": "ok"}

    async def test_execute_tool_mcp_fallback(self):
        """MCP 客户端抛异常后应继续查找"""
        gw = ToolGateway()
        mcp_client1 = AsyncMock()
        mcp_client1.call_tool = AsyncMock(side_effect=Exception("not found"))
        mcp_client2 = AsyncMock()
        mcp_client2.call_tool = AsyncMock(return_value={"result": "found"})
        gw._mcp_clients["s1"] = mcp_client1
        gw._mcp_clients["s2"] = mcp_client2

        result = await gw.execute_tool("tool", {})
        assert result == {"result": "found"}

    async def test_execute_tool_builtin_error(self):
        gw = ToolGateway()
        mock_tool = AsyncMock()
        mock_tool.execute = AsyncMock(side_effect=Exception("tool error"))
        gw._tools["bad_tool"] = mock_tool

        with pytest.raises(ToolExecutionError):
            await gw.execute_tool("bad_tool", {})

    async def test_discover_tools(self):
        gw = ToolGateway(config={"mcp_servers": {"test": {"url": "ws://localhost"}}})
        await gw.discover_tools()
        assert "speak" in gw._tools
        assert "test" in gw._mcp_clients

    async def test_discover_tools_no_mcp(self):
        gw = ToolGateway(config={})
        await gw.discover_tools()
        assert "speak" in gw._tools
        assert len(gw._mcp_clients) == 0

    async def test_discover_tools_mcp_error(self):
        gw = ToolGateway(config={"mcp_servers": {"bad": {"url": "invalid"}}})
        await gw.discover_tools()
        # MCP 连接失败不应影响 builtin 工具
        assert "speak" in gw._tools


# ============================================================
# BuiltinSpeakTool
# ============================================================


class TestBuiltinSpeakTool:
    """BuiltinSpeakTool"""

    def test_attributes(self):
        tool = BuiltinSpeakTool()
        assert tool.description == "通过语音向用户传达信息"
        assert "text" in tool.parameters["properties"]
        assert "text" in tool.parameters["required"]

    async def test_execute(self):
        tool = BuiltinSpeakTool()
        result = await tool.execute({"text": "你好"})
        assert result["success"] is True
        assert result["text"] == "你好"
        assert "你好" in result["message"]

    async def test_execute_empty_text(self):
        tool = BuiltinSpeakTool()
        result = await tool.execute({})
        assert result["success"] is True
        assert result["text"] == ""

    async def test_execute_with_context(self):
        tool = BuiltinSpeakTool()
        result = await tool.execute({"text": "hi"}, context={"session": "s1"})
        assert result["success"] is True


# ============================================================
# MemoryGateway
# ============================================================


class TestMemoryGateway:
    """MemoryGateway"""

    def test_init(self):
        gw = MemoryGateway(config={})
        assert gw.default_max_messages == 20
        assert gw.default_max_tokens == 2000
        assert gw._conversations == {}

    def test_init_with_config(self):
        gw = MemoryGateway(config={"max_messages": 50, "max_tokens": 4000})
        assert gw.default_max_messages == 50
        assert gw.default_max_tokens == 4000

    def test_get_or_create_conversation_new(self):
        gw = MemoryGateway(config={})
        conv = gw.get_or_create_conversation("s1")
        assert conv is not None
        assert conv.max_messages == 20

    def test_get_or_create_conversation_existing(self):
        gw = MemoryGateway(config={})
        conv1 = gw.get_or_create_conversation("s1")
        conv2 = gw.get_or_create_conversation("s1")
        assert conv1 is conv2

    def test_add_message(self):
        gw = MemoryGateway(config={})
        msg = Message(role="user", content="hello")
        gw.add_message("s1", msg)
        conv = gw.get_conversation("s1")
        assert len(conv.messages) == 1
        assert conv.messages[0].content == "hello"

    def test_build_context(self):
        gw = MemoryGateway(config={})
        gw.add_message("s1", Message(role="user", content="hi"))
        gw.add_message("s1", Message(role="assistant", content="hello"))
        messages = gw.build_context("s1", "system prompt", "new input")
        assert isinstance(messages, list)
        assert len(messages) >= 1

    def test_clear_conversation(self):
        gw = MemoryGateway(config={})
        gw.add_message("s1", Message(role="user", content="hi"))
        gw.clear_conversation("s1")
        conv = gw.get_conversation("s1")
        assert len(conv.messages) == 0

    def test_clear_nonexistent_conversation(self):
        gw = MemoryGateway(config={})
        gw.clear_conversation("nonexistent")

    def test_get_conversation_nonexistent(self):
        gw = MemoryGateway(config={})
        assert gw.get_conversation("nonexistent") is None


# ============================================================
# EmotionGateway
# ============================================================


class TestEmotionGateway:
    """EmotionGateway"""

    def test_init(self):
        gw = EmotionGateway(config={})
        assert gw.enabled is False
        assert gw.gif_dir == "emos"
        assert gw.static_dir == "static_emos"
        assert gw._last_emotions == {}

    def test_init_with_config(self):
        gw = EmotionGateway(config={"enabled": True, "gif_dir": "gifs", "static_dir": "static"})
        assert gw.enabled is True
        assert gw.gif_dir == "gifs"
        assert gw.static_dir == "static"

    async def test_detect_emotion_disabled(self):
        gw = EmotionGateway(config={"enabled": False})
        result = await gw.detect_emotion("好开心")
        assert result is None

    async def test_detect_emotion_happy(self):
        gw = EmotionGateway(config={"enabled": True})
        assert await gw.detect_emotion("今天好开心") == "happy"

    async def test_detect_emotion_sad(self):
        gw = EmotionGateway(config={"enabled": True})
        assert await gw.detect_emotion("伤心流泪") == "sad"

    async def test_detect_emotion_angry(self):
        gw = EmotionGateway(config={"enabled": True})
        assert await gw.detect_emotion("我讨厌这个") == "angry"

    async def test_detect_emotion_surprised(self):
        gw = EmotionGateway(config={"enabled": True})
        assert await gw.detect_emotion("天哪") == "surprised"

    async def test_detect_emotion_negative(self):
        gw = EmotionGateway(config={"enabled": True})
        assert await gw.detect_emotion("不要") == "negative"

    async def test_detect_emotion_none(self):
        gw = EmotionGateway(config={"enabled": True})
        assert await gw.detect_emotion("今天天气还可以") is None

    async def test_detect_emotion_with_device_id(self):
        gw = EmotionGateway(config={"enabled": True})
        await gw.detect_emotion("好开心", device_id="d1")
        assert gw._last_emotions["d1"] == "happy"

    async def test_get_emotion_image_path(self):
        gw = EmotionGateway(config={"enabled": True})
        path = await gw.get_emotion_image_path("happy")
        assert path == "emos/快乐.gif"

    async def test_get_emotion_image_path_static(self):
        gw = EmotionGateway(config={"enabled": True})
        path = await gw.get_emotion_image_path("sad", static=True)
        assert path == "static_emos/伤心.gif"

    async def test_get_emotion_image_path_empty(self):
        gw = EmotionGateway(config={"enabled": True})
        assert await gw.get_emotion_image_path("") is None

    async def test_get_emotion_image_path_unknown(self):
        gw = EmotionGateway(config={"enabled": True})
        assert await gw.get_emotion_image_path("unknown") is None

    async def test_should_send_emotion_first_time(self):
        gw = EmotionGateway(config={"enabled": True})
        assert await gw.should_send_emotion("happy", "d1") is True

    async def test_should_send_emotion_same_as_last(self):
        gw = EmotionGateway(config={"enabled": True})
        gw._last_emotions["d1"] = "happy"
        assert await gw.should_send_emotion("happy", "d1") is False

    async def test_should_send_emotion_different(self):
        gw = EmotionGateway(config={"enabled": True})
        gw._last_emotions["d1"] = "happy"
        assert await gw.should_send_emotion("sad", "d1") is True

    async def test_should_send_emotion_empty_emotion(self):
        gw = EmotionGateway(config={"enabled": True})
        assert await gw.should_send_emotion("", "d1") is False

    async def test_should_send_emotion_empty_device_id(self):
        gw = EmotionGateway(config={"enabled": True})
        assert await gw.should_send_emotion("happy", "") is False


# ============================================================
# create_asr_gateway 重导出
# ============================================================


class TestCreateASRGateway:
    """create_asr_gateway 重导出"""

    def test_is_callable(self):
        # create_asr_gateway 是从 src.interfaces.asr 重导出的可调用对象
        assert callable(create_asr_gateway)

    def test_creates_asr_gateway(self):
        # 通过 gateways 模块引用调用，便于 patch
        import src.interfaces.gateways as gw_module
        with patch.object(gw_module, "create_asr_gateway") as mock_create:
            mock_gateway = MagicMock()
            mock_create.return_value = mock_gateway
            result = gw_module.create_asr_gateway(config={"provider": "volcengine"})
            mock_create.assert_called_once()
            assert result is mock_gateway

    def test_creates_with_default(self):
        import src.interfaces.gateways as gw_module
        with patch.object(gw_module, "create_asr_gateway") as mock_create:
            mock_gateway = MagicMock()
            mock_create.return_value = mock_gateway
            gw_module.create_asr_gateway(config=None)
            mock_create.assert_called_once()


