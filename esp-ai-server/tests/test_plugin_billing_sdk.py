"""插件计费上报 SDK 测试

覆盖：
- ``sdk.billing.add_asr / add_llm / add_tts``：从 tool_manager.billing 读取
  当前会话计费累加器并累加；无累加器时静默跳过
- 权限门禁：插件未声明 billing 权限时抛 PermissionError
- 沙箱 RPC 裁决器：``billing_add_*`` op 的权限拦截与转发
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from src.infrastructure.plugin_host.adjudicator import Adjudicator, CallContext, PermissionDenied
from src.infrastructure.plugin_security import reset_plugin_context, set_plugin_context
from src.use_cases.billing import BillingAccumulator
from src.use_cases.sdk.billing import add_asr, add_llm, add_tts


def _ctx(device_key: str = "") -> CallContext:
    return CallContext(call_id=0, device_key=device_key)


def _tm_with_billing():
    """构造挂载了 BillingAccumulator 的 tool_manager 桩。"""
    tm = MagicMock()
    tm.billing = BillingAccumulator("dev1", "sess1")
    return tm


class TestSdkBilling:
    """主进程 SDK billing 函数"""

    def test_add_asr_accumulates(self):
        tm = _tm_with_billing()
        add_asr(1.5, tool_manager=tm)
        add_asr(0.5, tool_manager=tm)
        assert tm.billing.asr_minutes == 2.0

    def test_add_llm_accumulates(self):
        tm = _tm_with_billing()
        add_llm(input_tokens=100, output_tokens=50, cache_hit_tokens=20, tool_manager=tm)
        add_llm(input_tokens=30, output_tokens=10, tool_manager=tm)
        assert tm.billing.llm_input_tokens == 130
        assert tm.billing.llm_output_tokens == 60
        assert tm.billing.llm_cache_hit_tokens == 20

    def test_add_tts_accumulates(self):
        tm = _tm_with_billing()
        add_tts(30, tool_manager=tm)
        add_tts(70, tool_manager=tm)
        assert tm.billing.tts_chars == 100

    def test_no_billing_attr_silently_skips(self):
        """tool_manager 没有 billing 属性时不抛异常（非会话上下文）。"""
        tm = MagicMock()
        del tm.billing
        add_asr(1.0, tool_manager=tm)
        add_llm(output_tokens=10, tool_manager=tm)
        add_tts(5, tool_manager=tm)

    def test_none_tool_manager_silently_skips(self):
        add_asr(1.0, tool_manager=None)
        add_llm(output_tokens=10, tool_manager=None)
        add_tts(5, tool_manager=None)

    def test_requires_billing_permission(self):
        """插件上下文未声明 billing 权限 → PermissionError。"""
        token = set_plugin_context("demo", ["network"])
        try:
            with pytest.raises(PermissionError) as ei:
                add_asr(1.0, tool_manager=_tm_with_billing())
            assert "billing" in str(ei.value)
        finally:
            reset_plugin_context(token)

    def test_declared_billing_permission_passes(self):
        token = set_plugin_context("demo", ["billing"])
        try:
            tm = _tm_with_billing()
            add_asr(2.0, tool_manager=tm)
            assert tm.billing.asr_minutes == 2.0
        finally:
            reset_plugin_context(token)


class TestAdjudicatorBillingOps:
    """沙箱 RPC 裁决器 billing_add_* op"""

    def test_ops_require_billing_permission(self):
        adj = Adjudicator("p_no_perm", permissions=[])
        for op in ("billing_add_asr", "billing_add_llm", "billing_add_tts"):
            with pytest.raises(PermissionDenied):
                asyncio.run(adj.handle(op, {}, _ctx()))

    def test_add_asr_forwards_to_billing(self):
        tm = _tm_with_billing()
        ctx = _ctx()
        ctx.tool_manager = tm
        adj = Adjudicator("p", permissions=["billing"])
        asyncio.run(adj.handle("billing_add_asr", {"minutes": 3.0}, ctx))
        assert tm.billing.asr_minutes == 3.0

    def test_add_llm_forwards_to_billing(self):
        tm = _tm_with_billing()
        ctx = _ctx()
        ctx.tool_manager = tm
        adj = Adjudicator("p", permissions=["billing"])
        asyncio.run(adj.handle(
            "billing_add_llm",
            {"input_tokens": 100, "output_tokens": 50, "cache_hit_tokens": 20},
            ctx,
        ))
        assert tm.billing.llm_input_tokens == 100
        assert tm.billing.llm_output_tokens == 50
        assert tm.billing.llm_cache_hit_tokens == 20

    def test_add_tts_forwards_to_billing(self):
        tm = _tm_with_billing()
        ctx = _ctx()
        ctx.tool_manager = tm
        adj = Adjudicator("p", permissions=["billing"])
        asyncio.run(adj.handle("billing_add_tts", {"chars": 88}, ctx))
        assert tm.billing.tts_chars == 88

    def test_no_tool_manager_silently_skips(self):
        """无 tool_manager（无会话）时静默跳过，不抛异常。"""
        adj = Adjudicator("p", permissions=["billing"])
        asyncio.run(adj.handle("billing_add_asr", {"minutes": 1.0}, _ctx()))
        asyncio.run(adj.handle("billing_add_llm", {"output_tokens": 5}, _ctx()))
        asyncio.run(adj.handle("billing_add_tts", {"chars": 5}, _ctx()))
