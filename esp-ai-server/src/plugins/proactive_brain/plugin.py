"""主动推送插件：AI 自主决定何时发起对话，推送话题、提醒、问候。"""

from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import llm_generate, get_device_key


@tool()
async def get_proactive_status(tool_manager=None) -> str:
    """查看主动推送功能的状态，包括是否启用、今日推送次数、上次推送时间等。"""
    from src.use_cases.proactive_brain import get_proactive_brain
    brain = get_proactive_brain()
    if not brain or not brain._task:
        return "主动推送未启动"
    running = not brain._task.done() if brain._task else False
    return (
        f"主动推送状态：{'运行中' if running else '已停止'}\n"
        f"今日推送：{getattr(brain, '_daily_count', 0)} 次\n"
        f"冷却中：{getattr(brain, '_cooling', False)}"
    )


@tool()
async def toggle_proactive(enabled: bool, tool_manager=None) -> str:
    """启用或禁用主动推送功能。
    参数:
        enabled: true 为启用，false 为禁用
    """
    from src.use_cases.proactive_brain import get_proactive_brain
    brain = get_proactive_brain()
    if not brain:
        return "主动推送系统未初始化"
    if enabled:
        await brain.start()
        return "主动推送已启用，AI 将适时发起对话"
    else:
        await brain.stop()
        return "主动推送已禁用，AI 不会再主动发起对话"


@tool()
async def trigger_proactive_push(tool_manager=None) -> str:
    """手动触发一次主动推送，让 AI 立即决定是否发起对话。"""
    from src.use_cases.proactive_brain import get_proactive_brain
    from datetime import datetime
    brain = get_proactive_brain()
    if not brain:
        return "主动推送系统未初始化"
    try:
        result = await brain._tick()
        if result:
            return f"主动推送已触发：{result[:50]}..."
        return "AI 判断当前不适合推送，已跳过"
    except Exception as e:
        return f"推送失败: {e}"