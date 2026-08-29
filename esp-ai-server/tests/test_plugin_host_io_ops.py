"""沙箱新增 SDK 操作（设备 IO / 音乐播放）的裁决器单元测试。

覆盖：
    - 权限门禁：未声明 device 权限时被 PermissionDenied 拦截
    - 复用主进程 SDK 实现：无设备时的返回约定（写操作错误串 / 读操作 -1）
    - 设备作用域：显式指定非绑定设备被拦截
"""

import asyncio

import pytest

from src.infrastructure.plugin_host.adjudicator import Adjudicator, CallContext, PermissionDenied


def _ctx(device_key: str = "") -> CallContext:
    return CallContext(call_id=0, device_key=device_key)


def test_io_ops_require_device_permission():
    """未声明 device 权限 → 新 IO/音乐操作被拒绝。"""
    adj = Adjudicator("p_no_perm", permissions=[])
    for op in ("gpio_mode", "gpio_write", "gpio_read", "pwm_write",
               "adc_read", "servo_write", "play_music_url"):
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
