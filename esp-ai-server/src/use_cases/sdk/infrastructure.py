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
    """让设备直接播报语音（不经过 LLM 流程）。"""
    from src.infrastructure.web import get_app
    app = get_app()
    if app and hasattr(app.state, 'speaker') and app.state.speaker:
        await app.state.speaker.speak_direct(channel, ctx, fsm, text)
        return True
    return False


def get_wechat_bot():
    """获取 WeChatBot 实例（懒创建 + 注册回调，模块级单例）。"""
    from src.use_cases.wechat_bot import WeChatBot, WeChatClientConfig
    from src.use_cases.wechat_binding import get_wechat_binding_manager

    if get_wechat_bot._instance is not None:
        return get_wechat_bot._instance

    settings = get_settings()
    cfg = settings.wechat_bot
    bot_config = WeChatClientConfig(
        token=cfg.token, base_url=cfg.base_url, cdn_base_url=cfg.cdn_base_url,
        account_id=cfg.account_id, app_id=cfg.app_id, client_version=cfg.client_version,
    )
    bot = WeChatBot(bot_config)

    bind_mgr = get_wechat_binding_manager()

    async def _on_wechat_message(bot_, chat_id, sender_id, message_id, text, context_token):
        binding = bind_mgr.get_by_wechat(chat_id)
        if not binding:
            registry = get_device_registry()
            if registry:
                device_ids = registry.get_all_ids()
                if device_ids:
                    first_id = device_ids[0]
                    entry = registry.resolve(first_id)
                    if entry:
                        mac = entry.get("mac", "") or entry.get("device_id", "") or first_id
                        device_key = first_id
                        bind_mgr.bind(chat_id, sender_id, device_key, device_mac=mac)
                        binding = bind_mgr.get_by_wechat(chat_id)
                        try:
                            await bot_.send_text(chat_id, "已自动绑定设备，现在可以开始对话了")
                        except Exception:
                            pass
            if not binding:
                return
        await bind_mgr.send_wechat_message_to_device(binding.device_key, chat_id, sender_id, text)

    bot.on_message = _on_wechat_message

    if bot.state.configured and not bot.state.poll_task:
        import asyncio
        asyncio.create_task(bot.start())

    get_wechat_bot._instance = bot
    return bot


get_wechat_bot._instance = None


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