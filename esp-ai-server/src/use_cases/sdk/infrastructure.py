"""SDK 基础设施封装 — 统一封装框架基础设施层能力，插件不直接 import infrastructure。

插件端统一使用此模块获取日志器、配置、Speaker、设备注册表等框架能力，
避免直接 import src.infrastructure 下的模块。
"""


def get_logger(name):
    """获取日志记录器。"""
    from src.infrastructure.logging import get_logger as _get_logger
    return _get_logger(name)


def get_settings():
    """获取系统配置。"""
    from src.infrastructure.config import get_settings as _get_settings
    return _get_settings()


def get_device_registry():
    """获取设备注册表。"""
    from src.infrastructure.web import get_device_registry as _get_device_registry
    return _get_device_registry()


async def speak_direct(channel, ctx, fsm, text):
    """让设备直接播报语音（不经过 LLM 流程）。

    .. deprecated::
        旧 API，要求插件持有 channel/ctx/fsm 等框架内部对象（插件通常拿不到），
        保留兼容。新代码推荐使用 :func:`speak_to_device`（只需设备标识）。

    Returns:
        True 表示播报已提交；无 Speaker 时返回 False。
    """
    from src.infrastructure.web import get_app
    app = get_app()
    if app and hasattr(app.state, 'speaker') and app.state.speaker:
        await app.state.speaker.speak_direct(channel, ctx, fsm, text)
        return True
    return False


async def speak_to_device(device_key: str, text: str) -> bool:
    """向指定设备主动播报语音（推荐封装，不经过 LLM 流程）。

    与旧版 speak_direct 不同，本函数不需要插件持有 channel/session/fsm
    等框架内部对象——内部从 device_registry 解析设备的
    channel/session/fsm/user_config，并调用 speaker.speak_direct 完成播报。

    Args:
        device_key: 设备标识（bound_xxx 格式或 MAC）
        text: 要播报的文本

    Returns:
        True 表示播报已提交；设备离线 / 注册表或 Speaker 不可用 / 播报异常时返回 False。
    """
    if not device_key or not text:
        return False
    registry = get_device_registry()
    if not registry:
        return False
    device = registry.resolve(device_key)
    if not device:
        return False
    channel = device.get("channel")
    if channel is None or not getattr(channel, "connected", True):
        return False
    from src.infrastructure.web import get_app
    app = get_app()
    if not (app and hasattr(app.state, "speaker") and app.state.speaker):
        return False
    try:
        # speaker.speak_direct 签名: (channel, session, fsm, text, user_config=None, ...)
        await app.state.speaker.speak_direct(
            channel,
            device.get("session"),
            device.get("fsm"),
            text,
            user_config=device.get("user_config"),
        )
        return True
    except Exception as e:
        get_logger(__name__).error(f"[speak_to_device] 向设备 {device_key} 播报失败: {e}")
        return False


def get_wechat_bot():
    """获取 WeChatBot 实例（委托给 wechat_bot.py 的进程级单例）。

    历史教训：这里曾自建第二个 WeChatBot 实例并附带独立的简版消息回调
    （含"自动绑到第一台设备"逻辑）——两个实例用同一 token 各自轮询，
    微信服务端会话冲突返回 -14 session timeout，最终 token 被误判失效。
    现在统一使用 wechat_bot.py 的单例，消息回调由 web.py lifespan 注册完整版。
    """
    from src.use_cases.wechat_bot import get_or_create_bot
    return get_or_create_bot()


def get_wechat_binding_mgr():
    """获取微信绑定管理器（模块级单例）。"""
    if get_wechat_binding_mgr._instance is not None:
        return get_wechat_binding_mgr._instance
    from src.use_cases.wechat_binding import get_wechat_binding_manager
    mgr = get_wechat_binding_manager()
    get_wechat_binding_mgr._instance = mgr
    return mgr


get_wechat_binding_mgr._instance = None


def get_remote_config_provider():
    """获取远程配置提供者。"""
    from src.infrastructure.remote_config import get_remote_config_provider as _get_provider
    return _get_provider()