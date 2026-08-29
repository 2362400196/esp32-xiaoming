from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.device import send_device_command

@tool()
async def show_text(text: str = "Hello", tool_manager=None) -> str:
    """在设备屏幕上显示文字（支持中英文）。
    当用户说"屏幕上显示 xxx"、"写 xxx 在屏幕上"时调用。
    参数 text: 要显示的文字（支持中英文）"""
    # 1. 先清空表情/字幕层，避免 Lua label 被盖住
    err = await send_device_command(tool_manager, "clear_screen")
    if err:
        return f"显示失败: {err}"

    # 2. Lua 引号转义，防止文字里的引号拼坏脚本
    safe = text.replace('\\', '\\\\').replace('"', '\\"')
    lua_code = (
        'local lv = require("lvgl")\n'
        'local scr = lv.scr_act()\n'
        'local label = lv.label(scr)\n'
        f'lv.label_set_text(label, "{safe}")\n'
        'lv.obj_center(label)'
    )
    err = await send_device_command(tool_manager, "execute_lua", lua_code)
    if err:
        return f"显示失败: {err}"
    return f"已在屏幕上显示：{text}"