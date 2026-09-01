"""插件 LLM 计费链路测试

覆盖：
- ``call_llm_chat`` 收集插件返回的 usage（prompt / completion / cache_hit tokens）
  并写入 ``usage_sink``（跨工具轮次累计）
- ``PluginLLMGateway.stream_chat`` 结束后暴露 ``last_*`` tokens 属性，
  供 pipeline 计费读取（与 OpenAILLMGateway 对齐）
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.interfaces.plugin_gateways import PluginLLMGateway
from src.interfaces.service_plugin_adapter import call_llm_chat


def _make_plugin_env(monkeypatch, get_next_results):
    """mock get_service_plugin 与 _call_plugin_tool，返回调用记录"""
    import src.interfaces.service_plugin_adapter as spa

    monkeypatch.setattr(spa, "get_service_plugin", lambda *a, **k: "llm_openai")
    calls = []
    seq = iter(get_next_results)

    async def fake_call_plugin_tool(plugin_name, tool_suffix, args, tool_manager=None):
        calls.append((tool_suffix, args))
        if tool_suffix == "start_chat":
            return {"chat_id": "c1", "error": None}
        if tool_suffix == "get_next":
            return next(seq, {"token": "", "done": True, "error": None})
        if tool_suffix == "end_chat":
            return {}
        return None

    monkeypatch.setattr(spa, "_call_plugin_tool", fake_call_plugin_tool)
    return calls


class TestCallLLMChatUsage:
    """call_llm_chat 的 usage 收集与 usage_sink 写入"""

    async def test_collects_usage_into_sink(self, monkeypatch):
        _make_plugin_env(monkeypatch, [
            {"token": "你", "done": False, "error": None},
            {"token": "好", "done": False, "error": None},
            {"token": "", "done": True, "error": None,
             "usage": {"prompt_tokens": 12, "completion_tokens": 34, "prompt_cache_hit_tokens": 5}},
        ])
        sink = {}
        tokens = []
        async for t in call_llm_chat([{"role": "user", "content": "hi"}], usage_sink=sink):
            tokens.append(t)
        assert "".join(tokens) == "你好"
        assert sink == {"input_tokens": 12, "output_tokens": 34, "cache_hit_tokens": 5}

    async def test_usage_sink_none_no_error(self, monkeypatch):
        _make_plugin_env(monkeypatch, [
            {"token": "ok", "done": False, "error": None},
            {"token": "", "done": True, "error": None,
             "usage": {"prompt_tokens": 3, "completion_tokens": 4}},
        ])
        tokens = []
        async for t in call_llm_chat([{"role": "user", "content": "hi"}]):
            tokens.append(t)
        assert "".join(tokens) == "ok"

    async def test_usage_missing_fields_default_zero(self, monkeypatch):
        _make_plugin_env(monkeypatch, [
            {"token": "", "done": True, "error": None, "usage": {}},
        ])
        sink = {}
        async for _ in call_llm_chat([{"role": "user", "content": "hi"}], usage_sink=sink):
            pass
        assert sink == {"input_tokens": 0, "output_tokens": 0, "cache_hit_tokens": 0}

    async def test_accumulates_across_tool_rounds(self, monkeypatch):
        """工具调用两轮：每轮 done 都返回 usage，应跨轮累计"""
        tm = MagicMock()
        tm.channel = None
        tm.call_tool = AsyncMock(return_value="tool result")
        _make_plugin_env(monkeypatch, [
            # 第一轮：工具调用
            {"token": "", "tool_calls": [{"index": 0, "id": "tc1", "function_name": "f", "arguments": "{}"}],
             "done": True, "error": None,
             "usage": {"prompt_tokens": 10, "completion_tokens": 20, "prompt_cache_hit_tokens": 3}},
            # 第二轮：最终文本
            {"token": "最终", "done": False, "error": None},
            {"token": "", "done": True, "error": None,
             "usage": {"prompt_tokens": 8, "completion_tokens": 15, "prompt_cache_hit_tokens": 2}},
        ])
        sink = {}
        tokens = []
        async for t in call_llm_chat([{"role": "user", "content": "hi"}], tool_manager=tm, usage_sink=sink):
            tokens.append(t)
        assert "".join(tokens) == "最终"
        assert sink == {"input_tokens": 18, "output_tokens": 35, "cache_hit_tokens": 5}


class TestPluginLLMGatewayBilling:
    """PluginLLMGateway.stream_chat 暴露 last_* tokens"""

    async def test_stream_chat_exposes_last_tokens(self, monkeypatch):
        async def fake_call_llm_chat(messages, config, tool_manager, provider=None, usage_sink=None):
            if usage_sink is not None:
                usage_sink["input_tokens"] = 12
                usage_sink["output_tokens"] = 34
                usage_sink["cache_hit_tokens"] = 5
            yield "你好"

        with patch("src.interfaces.plugin_gateways.call_llm_chat", new=fake_call_llm_chat):
            gw = PluginLLMGateway(config={"api_key": "k"})
            results = []
            async for token in gw.stream_chat([{"role": "user", "content": "hi"}]):
                results.append(token)
        assert "".join(results) == "你好"
        assert gw.last_prompt_tokens == 12
        assert gw.last_completion_tokens == 34
        assert gw.last_cache_hit_tokens == 5

    async def test_stream_chat_no_usage_defaults_zero(self, monkeypatch):
        async def fake_call_llm_chat(messages, config, tool_manager, provider=None, usage_sink=None):
            yield "ok"

        with patch("src.interfaces.plugin_gateways.call_llm_chat", new=fake_call_llm_chat):
            gw = PluginLLMGateway(config={"api_key": "k"})
            async for _ in gw.stream_chat([{"role": "user", "content": "hi"}]):
                pass
        assert gw.last_prompt_tokens == 0
        assert gw.last_completion_tokens == 0
        assert gw.last_cache_hit_tokens == 0

    async def test_stream_chat_not_configured(self, monkeypatch):
        async def fake_call_llm_chat(messages, config, tool_manager, provider=None, usage_sink=None):
            yield "[LLM not configured: no LLM service plugin installed]"

        with patch("src.interfaces.plugin_gateways.call_llm_chat", new=fake_call_llm_chat):
            gw = PluginLLMGateway(config={})
            results = []
            async for token in gw.stream_chat([{"role": "user", "content": "hi"}]):
                results.append(token)
        assert results == ["[LLM not configured: no LLM service plugin installed]"]
        assert gw.last_completion_tokens == 0
