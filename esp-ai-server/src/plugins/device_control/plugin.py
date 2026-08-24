from src.use_cases.tools_system import StopPipeline, tool
from src.use_cases._plugin_helpers import send_device_command, request_device_result, speak_direct

@tool()
async def test_device(channel=None, ctx=None, fsm=None) -> str:
    """设备测试工具，当用户说测试的时候你执行"""
    if channel:
        ok = await speak_direct(channel, ctx, fsm, "测试成功")
        if ok:
            raise StopPipeline()

    return "测试指令已生成（未连接设备）"


@tool()
async def execute_lua(code: str, tool_manager=None) -> str:
    """在用户的 ESP32 设备上直接运行 Lua 脚本代码（通过设备固件的 Lua 引擎）。
如果返回的结果中包含 [Lua Error] 标记，说明脚本运行出错了，请分析错误原因并修复代码后重新调用此工具。

===== 使用规则 =====
- 用户要求"画 xxx"时，你**必须调用此工具**生成 Lua 代码来实际绘制。
- ⚠️ **绝对不要清空屏幕！** 设备屏幕由系统管理，obj_clean(scr) 会误删系统控件导致崩溃重启！
  每次画新图时直接在屏幕上叠加绘制即可。如需清屏请调用 clear_screen 工具。
- ⚠️ **不支持中文！** 设备固件没有编译中文字体，用 lvgl.label 显示中文会变成方框。
  如果用户要求写字，写英文或数字，不要写中文。
- ⚠️ **GPIO48 已被板载情绪灯占用，不能用作普通 GPIO！** 如需控制灯带请用 led 模块。
- 用户要求"画图形"时，必须先画一个背景矩形（从 y=40 开始，避让顶部状态栏），再在背景上画图形。
- 画三角形等形状使用 lvgl.line 系列函数。

===== 可用模块（require 加载）=====
- delay: delay_ms(ms), delay_us(us)
- system: millis(), free_heap(), free_psram(), chip_info(), restart()
- json: encode(table), decode(str), pretty(table)
- lvgl: obj(parent)/scr_act()/label(parent)/btn(parent)/line(parent), obj_set_pos/size, obj_center/del/clean, label_set_text, line_set_points, set_style_*, color_make/hex, disp_hor/ver_res, LEFT/CENTER/RIGHT
  注：lvgl.obj(parent) 如果不传 parent 会自动使用当前屏幕，但**不要传 nil**。
- gpio: mode(pin, dir), write(pin, val), read(pin)
- http: get(url), post(url, body, content_type)
- led (WS2812): init(pin, count), set(idx,R,G,B), set_hsv(idx,H,S,V), show(), clear(), brightness(val), deinit()
  板载情绪灯：led.init(48, 1)
======================"""

    result, status, detail = await request_device_result(
        tool_manager, "execute_lua", "_pending_lua_future", timeout=8.0, data=code,
    )
    if status != "ok":
        if status == "offline":
            return "Lua 脚本指令已生成（未连接设备）"
        if status == "timeout":
            return "Lua 脚本已发送到设备执行，但未在 8 秒内收到执行结果（可能脚本还在运行中）"
        return f"发送 Lua 脚本失败: {detail}"
    return f"Lua 脚本执行成功:\n{result}"


@tool()
async def stop_lua(tool_manager=None) -> str:
    """停止设备上所有正在运行的 Lua 脚本。
当用户说"停下来"、"停止"、"别画了"等，或 execute_lua 工具执行超时/卡住时调用此工具。"""

    err = await send_device_command(tool_manager, "stop_lua")
    if err:
        return f"停止指令已生成（{err}）"
    return "已发送停止指令到设备"


@tool()
async def clear_screen(tool_manager=None) -> str:
    """清除设备屏幕上所有 Lua 绘制的图案，让屏幕恢复到正常显示状态。
当用户说"清屏"、"恢复"、"变回原来的样子"、"擦掉画的"时调用此工具。
注意：清除后，设备的表情、状态文字等系统界面会恢复正常显示。"""

    err = await send_device_command(tool_manager, "clear_screen")
    if err:
        return f"清屏指令已生成（{err}）"
    return "已发送清屏指令到设备"
