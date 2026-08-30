"""沙箱新增 SDK 操作（设备 IO / 音乐播放 / 语音播报）的裁决器单元测试。

覆盖：
    - 权限门禁：未声明 device 权限时被 PermissionDenied 拦截
    - 复用主进程 SDK 实现：无设备时的返回约定（写操作错误串 / 读操作 -1 / 播报 False）
    - 设备作用域：显式指定非绑定设备被拦截
"""

import asyncio

import pytest

from src.infrastructure.plugin_host.adjudicator import Adjudicator, CallContext, PermissionDenied


def _ctx(device_key: str = "") -> CallContext:
    return CallContext(call_id=0, device_key=device_key)


def test_io_ops_require_device_permission():
    """未声明 device 权限 → 新 IO/音乐/播报操作被拒绝。"""
    adj = Adjudicator("p_no_perm", permissions=[])
    for op in ("gpio_mode", "gpio_write", "gpio_read", "pwm_write",
               "adc_read", "servo_write", "play_music_url", "speak_text"):
        with pytest.raises(PermissionDenied):
            asyncio.run(adj.handle(op, {}, _ctx()))


def test_unknown_op_denied():
    adj = Adjudicator("p", permissions=["device"])
    with pytest.raises(PermissionDenied):
        asyncio.run(adj.handle("gpio_write_all", {}, _ctx()))


def test_gpio_write_without_device_returns_error_string():
    """无设备时写操作返回错误串（复用主进程 SDK 约定），不抛异常。"""
    adj = Adjudicator("p", permissions=["device"])
    result = asyncio.run(adj.handle("gpio_write", {"pin": 2, "value": 1}, _ctx()))
    assert isinstance(result, str)
    assert result != "ok"


def test_gpio_read_without_device_returns_minus_one():
    adj = Adjudicator("p", permissions=["device"])
    result = asyncio.run(adj.handle("gpio_read", {"pin": 2}, _ctx()))
    assert result == -1


def test_adc_read_without_device_returns_minus_one():
    adj = Adjudicator("p", permissions=["device"])
    result = asyncio.run(adj.handle("adc_read", {"pin": 3}, _ctx()))
    assert result == -1


def test_io_write_ops_without_device_return_error_strings():
    adj = Adjudicator("p", permissions=["device"])
    for op, params in (
        ("gpio_mode", {"pin": 2, "mode": "output"}),
        ("pwm_write", {"pin": 2, "duty": 512}),
        ("servo_write", {"pin": 2, "angle": 90}),
    ):
        result = asyncio.run(adj.handle(op, params, _ctx()))
        assert isinstance(result, str)
        assert result != "ok"


def test_play_music_url_without_device_returns_error_string():
    adj = Adjudicator("p", permissions=["device"])
    result = asyncio.run(adj.handle(
        "play_music_url", {"url": "http://example.com/a.mp3"}, _ctx()
    ))
    assert isinstance(result, str)
    assert result != "ok"


def test_io_ops_reject_other_device_scope():
    """插件绑定设备 A 时，显式指定设备 B 的 IO 操作被拦截。"""
    adj = Adjudicator("p", permissions=["device"])
    with pytest.raises(PermissionDenied):
        asyncio.run(adj.handle(
            "gpio_write", {"pin": 2, "value": 1, "device_key": "bound_other"},
            _ctx(device_key="bound_demo"),
        ))


def test_io_ops_with_bound_device_key_allowed():
    """显式传绑定设备自身的 device_key 不被拦截（无设备连接时返回错误串）。"""
    adj = Adjudicator("p", permissions=["device"])
    result = asyncio.run(adj.handle(
        "gpio_write", {"pin": 2, "value": 1, "device_key": "bound_demo"},
        _ctx(device_key="bound_demo"),
    ))
    assert isinstance(result, str)


# ════════════════════════════════════════════════════════════
# speak_text（语音播报：需 device + tts 双权限）
# ════════════════════════════════════════════════════════════

_TTS_PERMS = ["device", "tts"]


def test_speak_text_requires_both_device_and_tts():
    """speak_text 需同时声明 device 与 tts，缺任一都被拦截。"""
    for perms in ([], ["device"], ["tts"]):
        adj = Adjudicator("p", permissions=perms)
        with pytest.raises(PermissionDenied):
            asyncio.run(adj.handle("speak_text", {"text": "你好"}, _ctx()))


def test_speak_text_without_device_returns_false():
    """无设备时 speak_text 返回 False（复用 speak_to_device 约定），不抛异常。"""
    adj = Adjudicator("p", permissions=_TTS_PERMS)
    result = asyncio.run(adj.handle("speak_text", {"text": "你好"}, _ctx()))
    assert result is False


def test_speak_text_empty_text_returns_false():
    adj = Adjudicator("p", permissions=_TTS_PERMS)
    result = asyncio.run(adj.handle("speak_text", {"text": ""}, _ctx()))
    assert result is False


def test_speak_text_rejects_other_device_scope():
    """插件绑定设备 A 时，显式指定设备 B 的播报被拦截。"""
    adj = Adjudicator("p", permissions=_TTS_PERMS)
    with pytest.raises(PermissionDenied):
        asyncio.run(adj.handle(
            "speak_text", {"text": "你好", "device_key": "bound_other"},
            _ctx(device_key="bound_demo"),
        ))


def test_speak_text_forwards_to_speak_to_device():
    """绑定设备时，speak_text 把 text/device_key 透传给主进程 speak_to_device。"""
    from unittest.mock import AsyncMock, patch

    adj = Adjudicator("p", permissions=_TTS_PERMS)
    with patch(
        "src.use_cases.sdk.infrastructure.speak_to_device",
        new=AsyncMock(return_value=True),
    ) as m:
        result = asyncio.run(adj.handle(
            "speak_text", {"text": "你好", "device_key": "bound_demo"},
            _ctx(device_key="bound_demo"),
        ))
    assert result is True
    m.assert_awaited_once_with("bound_demo", "你好")


def test_speak_text_with_bound_device_returns_false_without_registry():
    """绑定设备但主进程注册表不可用 → 返回 False（设备未连接语义）。"""
    adj = Adjudicator("p", permissions=_TTS_PERMS)
    result = asyncio.run(adj.handle(
        "speak_text", {"text": "你好", "device_key": "bound_demo"},
        _ctx(device_key="bound_demo"),
    ))
    assert result is False
