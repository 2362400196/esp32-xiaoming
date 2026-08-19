from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import send_device_command

@tool()
async def set_screen_rotation(angle: str = "", tool_manager=None) -> str:
    """旋转设备屏幕方向。
    参数:
        angle: 旋转方式，支持以下格式：
              "90"  → 绝对旋转到 90°
              "0"   → 恢复到 0°
              "cw"  → 顺时针转 90°
              "ccw" → 逆时针转 90°
    """
    valid_abs = {"0", "90", "180", "270"}
    valid_rel = {"cw", "ccw", "+", "-"}

    angle = angle.strip().lower()
    if angle not in valid_abs and angle not in valid_rel:
        return "不支持的旋转参数，请使用 0/90/180/270 或 cw(顺时针)/ccw(逆时针)"

    err = await send_device_command(tool_manager, "set_rotation", angle)
    if err:
        return f"屏幕旋转指令已生成（{err}）"

    return "屏幕已旋转"
