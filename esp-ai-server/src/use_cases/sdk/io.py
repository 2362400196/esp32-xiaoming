"""SDK 设备 IO 控制 - GPIO / PWM / ADC / 舵机

设备固件支持两种 IO 控制方式：
  1. hardware-fns 消息（写操作）：直接发送 {"type": "hardware-fns", "fn_name": "...", ...}
     支持 pinMode / digitalWrite / analogWrite / ledcWrite
  2. execute_lua 指令（读操作）：通过 Lua 引擎执行 gpio.read / adc 读取并返回结果
     支持 gpio.read(pin) 返回 0/1

注意：ESP32-S3 ADC 仅限 GPIO1~10（ADC1 通道）
"""

from src.infrastructure.plugin_security import require_permission
from src.use_cases.sdk.device import request_device_result
from src.use_cases.sdk.utils import get_device_key


def _resolve_io_channel(device_key: str = "", tool_manager=None):
    """解析设备通道，用于发送 hardware-fns 消息。"""
    if not device_key and tool_manager:
        device_key = get_device_key(tool_manager)
    if not device_key:
        return None
    from src.infrastructure.device_api import get_device_registry
    registry = get_device_registry()
    if not registry:
        return None
    device = registry.resolve(device_key)
    if not device:
        return None
    return device.get("channel")


async def gpio_mode(pin: int, mode: str = "output", tool_manager=None, device_key: str = "") -> str:
    """配置 GPIO 引脚模式。

    Args:
        pin: GPIO 引脚编号
        mode: 引脚模式，可选："output" / "input" / "input_pullup"
        tool_manager: 自动传入
        device_key: 设备标识，为空时自动推断

    Returns:
        "ok" 表示成功，字符串表示失败原因
    """
    require_permission("device", "设置 GPIO 引脚模式")
    channel = _resolve_io_channel(device_key, tool_manager)
    if not channel:
        return "设备未连接"
    mode_upper = mode.upper()
    if mode_upper not in ("OUTPUT", "INPUT", "INPUT_PULLUP", "INPUT_PULLDOWN"):
        return f"不支持的模式: {mode}（可选: output/input/input_pullup）"
    try:
        await channel.send_json({
            "type": "hardware-fns",
            "fn_name": "pinMode",
            "pin": pin,
            "str_val": mode_upper,
        })
        return "ok"
    except Exception as e:
        return f"设置 GPIO 模式失败: {e}"


async def gpio_write(pin: int, value: int, tool_manager=None, device_key: str = "") -> str:
    """写入数字信号到 GPIO 引脚。

    Args:
        pin: GPIO 引脚编号
        value: 输出值，0 或 1（非零值视为 1）
        tool_manager: 自动传入
        device_key: 设备标识，为空时自动推断

    Returns:
        "ok" 表示成功，字符串表示失败原因
    """
    require_permission("device", "写入 GPIO 数字信号")
    channel = _resolve_io_channel(device_key, tool_manager)
    if not channel:
        return "设备未连接"
    try:
        await channel.send_json({
            "type": "hardware-fns",
            "fn_name": "digitalWrite",
            "pin": pin,
            "str_val": "HIGH" if value else "LOW",
        })
        return "ok"
    except Exception as e:
        return f"写入 GPIO 失败: {e}"


async def gpio_read(pin: int, tool_manager=None, device_key: str = "") -> int:
    """读取 GPIO 引脚数字信号。

    Args:
        pin: GPIO 引脚编号
        tool_manager: 自动传入（读操作需要 tool_manager 来等待设备返回结果）
        device_key: 设备标识，为空时自动推断

    Returns:
        0 或 1 表示引脚电平，-1 表示读取失败
    """
    require_permission("device", "读取 GPIO 数字信号")
    if not device_key and tool_manager:
        device_key = get_device_key(tool_manager)
    if not device_key:
        return -1
    result, status, detail = await request_device_result(
        tool_manager, "execute_lua", "_pending_lua_future",
        data=f"local gpio=require('gpio'); return tostring(gpio.read({pin}))",
        timeout=5.0,
    )
    if status == "ok":
        try:
            return int(result.strip())
        except (ValueError, AttributeError):
            return -1
    return -1


async def pwm_write(pin: int, duty: int, freq: int = 5000, tool_manager=None, device_key: str = "") -> str:
    """PWM 输出（通过 LEDC 控制器）。

    Args:
        pin: GPIO 引脚编号
        duty: 占空比 0-1023（10bit 分辨率）
        freq: PWM 频率 Hz，默认 5000Hz
        tool_manager: 自动传入
        device_key: 设备标识，为空时自动推断

    Returns:
        "ok" 表示成功，字符串表示失败原因
    """
    require_permission("device", "PWM 输出")
    channel = _resolve_io_channel(device_key, tool_manager)
    if not channel:
        return "设备未连接"
    duty = max(0, min(duty, 1023))
    try:
        await channel.send_json({
            "type": "hardware-fns",
            "fn_name": "pinMode",
            "pin": pin,
            "str_val": "LEDC",
            "freq": freq,
            "resolution": 10,
        })
        await channel.send_json({
            "type": "hardware-fns",
            "fn_name": "analogWrite",
            "pin": pin,
            "num_val": duty,
        })
        return "ok"
    except Exception as e:
        return f"PWM 输出失败: {e}"


async def adc_read(pin: int, tool_manager=None, device_key: str = "") -> int:
    """读取 ADC 模拟值。

    ESP32-S3 ADC1 通道对应 GPIO1~10，返回 12bit 原始值 0-4095。

    Args:
        pin: GPIO 引脚编号（1-10，ADC1 通道）
        tool_manager: 自动传入
        device_key: 设备标识，为空时自动推断

    Returns:
        0-4095 的原始 ADC 值，-1 表示读取失败
    """
    require_permission("device", "读取 ADC 模拟值")
    if not device_key and tool_manager:
        device_key = get_device_key(tool_manager)
    if not device_key:
        return -1
    if pin < 1 or pin > 10:
        return -1
    lua_code = (
        f"local adc = require('adc')\n"
        f"if adc then\n"
        f"  local val = adc.read({pin})\n"
        f"  return tostring(val)\n"
        f"else\n"
        f"  return '0'\n"
        f"end"
    )
    result, status, detail = await request_device_result(
        tool_manager, "execute_lua", "_pending_lua_future",
        data=lua_code,
        timeout=5.0,
    )
    if status == "ok":
        try:
            return int(result.strip())
        except (ValueError, AttributeError):
            return -1
    return -1


async def servo_write(pin: int, angle: int, tool_manager=None, device_key: str = "") -> str:
    """控制舵机角度。

    Args:
        pin: GPIO 引脚编号（舵机信号线）
        angle: 目标角度 0-180 度
        tool_manager: 自动传入
        device_key: 设备标识，为空时自动推断

    Returns:
        "ok" 表示成功，字符串表示失败原因
    """
    require_permission("device", "控制舵机")
    channel = _resolve_io_channel(device_key, tool_manager)
    if not channel:
        return "设备未连接"
    angle = max(0, min(angle, 180))
    try:
        await channel.send_json({
            "type": "hardware-fns",
            "fn_name": "pinMode",
            "pin": pin,
            "str_val": "LEDC",
            "freq": 50,
            "resolution": 10,
        })
        await channel.send_json({
            "type": "hardware-fns",
            "fn_name": "ledcWrite",
            "pin": pin,
            "channel": 0,
            "deg": angle,
        })
        return "ok"
    except Exception as e:
        return f"舵机控制失败: {e}"