"""主动推送插件：AI 自主决定何时发起对话，推送话题、提醒、问候。

引擎实现见同目录 engine.py（ProactiveBrain + 模块级单例）。
"""

import asyncio

from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import llm_generate, get_device_key
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


# ── 生命周期钩子（插件加载/卸载时由 plugin_loader 调用）──────


async def _bind_registry_when_ready(brain) -> None:
    """等待设备注册表就绪后挂到引擎上（后台任务，不阻塞插件加载）。

    插件 on_startup 在 web.py lifespan 前段执行，此时 DeviceRegistry
    尚未创建（lifespan 后段才建）。轮询等待即可：引擎首次 tick 在
    start() 60 秒之后，而注册表在同一 lifespan 内毫秒级就绪，
    因此不影响推送时机。
    """
    from src.infrastructure.web import get_device_registry

    for _ in range(120):  # 最多等 2 分钟
        registry = get_device_registry()
        if registry is not None:
            brain.set_registry(registry)
            return
        await asyncio.sleep(1)
    logger.warning("[Proactive] 等待设备注册表超时，主动推送将无法查询在线设备")


async def on_startup():
    """插件加载钩子：启动 AI 主动推送系统（原 web.py lifespan 逻辑迁入）。"""
    try:
        from src.plugins.proactive_brain.engine import get_proactive_brain

        brain = get_proactive_brain()

        # 保持与原实现一致：挂到 app.state 上（供其他模块按需访问）
        try:
            from src.infrastructure.web import get_app
            app = get_app()
            if app is not None:
                app.state.proactive_brain = brain
        except Exception:
            pass

        # 注册表延迟绑定（插件加载早于 DeviceRegistry 创建）
        asyncio.create_task(_bind_registry_when_ready(brain))

        await brain.start()
    except Exception as e:
        logger.warning(f"[Proactive] 插件 on_startup 异常（不影响加载）: {e}")


async def on_shutdown():
    """插件卸载钩子：停止主动推送后台协程（引擎 stop 幂等）。"""
    try:
        from src.plugins.proactive_brain.engine import get_proactive_brain
        await get_proactive_brain().stop()
    except Exception as e:
        logger.warning(f"[Proactive] 插件 on_shutdown 异常（不影响卸载）: {e}")


# ── LLM 工具 ───────────────────────────────────────────────


@tool()
async def get_proactive_status(tool_manager=None) -> str:
    """查看主动推送功能的状态，包括是否启用、今日推送次数、上次推送时间等。"""
    from src.plugins.proactive_brain.engine import get_proactive_brain
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
    from src.plugins.proactive_brain.engine import get_proactive_brain
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
    from src.plugins.proactive_brain.engine import get_proactive_brain
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
