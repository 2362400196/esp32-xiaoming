from src.use_cases._plugin_helpers import get_logger
from src.use_cases.tools_system import StopPipeline, tool
from src.use_cases._plugin_helpers import send_device_command, request_device_result

logger = get_logger(__name__)


@tool()
def get_current_time() -> str:
    """获取当前日期和时间"""
    from datetime import datetime

    now = datetime.now()
    return now.strftime("%Y年%m月%d日 %H时%M分")


@tool()
def get_current_date() -> str:
    """获取今天的日期和星期几"""
    from datetime import datetime

    now = datetime.now()
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    return f"{now.strftime('%Y年%m月%d日')} {weekdays[now.weekday()]}"

@tool()
async def set_volume(level: int, tool_manager=None) -> str:
    """设置设备音量到指定值。
    参数 level 为 0-100 的整数，0 静音，100 最大。
    用户说"音量调到 80"→ level=80
    用户说"声音最大"→ level=100
    用户说"静音"→ level=0
    用户说"声音调小/最小"→ level=10"""

    level = max(0, min(100, level))
    volume = level / 100.0
    err = await send_device_command(tool_manager, "set_volume", str(volume))
    if err:
        return f"音量设置指令已生成: {level}%（{err}）"
    return f"已将音量设置为 {level}%"


@tool()
async def volume_down(tool_manager=None) -> str:
    """把音量调小一点（每次降低 10%）"""
    err = await send_device_command(tool_manager, "subtract_volume", "0.1")
    if err:
        return f"调小音量指令已生成（{err}）"
    return "已调小音量"


@tool()
async def volume_up(tool_manager=None) -> str:
    """把音量调大一点（每次增加 10%）"""
    err = await send_device_command(tool_manager, "add_volume", "0.1")
    if err:
        return f"调大音量指令已生成（{err}）"
    return "已调大音量"


@tool()
async def set_brightness(level: int, tool_manager=None) -> str:
    """设置屏幕亮度。
    参数 level 为 0-100 的整数，0 最暗（关屏），100 最亮。
    用户说"亮度调到 50"→ level=50
    用户说"屏幕最亮"→ level=100
    用户说"屏幕调暗一点"→ level=30"""
    level = max(0, min(100, level))
    err = await send_device_command(tool_manager, "set_brightness", str(level))
    if err:
        return f"亮度设置指令已生成: {level}%（{err}）"
    return f"已将屏幕亮度设置为 {level}%"


@tool()
async def standby(tool_manager=None) -> str:
    """当用户说休息，退下，退出，关机等词的时候将设备设置为待机状态，不响应语音指令"""
    if not tool_manager or not tool_manager.channel:
        return "已进入待机状态"
    # 先清除工具状态显示
    await send_device_command(tool_manager, "on_tool_status", "")
    await tool_manager.channel.send_json({"type": "session_status", "status": "session_end"})
    await tool_manager.channel.send_text("session_end")
    raise StopPipeline()


async def _query_device_state(tool_manager, command_id: str) -> str:
    """下发设备状态查询指令，等待设备回复（5 秒超时）。
    设备回复格式: data 为 "volume=80" / "brightness=60" 形式的字符串。
    使用独立的 _pending_device_state_future，避免与 execute_lua 的 future 冲突。"""
    result, status, detail = await request_device_result(
        tool_manager, command_id, "_pending_device_state_future", timeout=5.0,
    )
    if status != "ok":
        return detail if status == "offline" else (f"设备未在 5 秒内响应" if status == "timeout" else f"查询失败: {detail}")
    return result.strip()


@tool()
async def get_volume(tool_manager=None) -> str:
    """获取设备当前的音量（百分比 0-100）。当用户问"现在音量多大"、"音量是多少"、"当前音量"时调用。"""
    result = await _query_device_state(tool_manager, "get_volume")
    if result.startswith("volume="):
        return f"当前音量是 {result[len('volume='):]}%"
    return result


@tool()
async def get_brightness(tool_manager=None) -> str:
    """获取设备屏幕当前的亮度（百分比 0-100）。当用户问"屏幕亮度多少"、"现在亮度"时调用。"""
    result = await _query_device_state(tool_manager, "get_brightness")
    if result.startswith("brightness="):
        return f"当前屏幕亮度是 {result[len('brightness='):]}%"
    return result
