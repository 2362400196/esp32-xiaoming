"""WS 会话微信回复：把本轮 LLM 回复发回微信用户。"""
from __future__ import annotations

from src.infrastructure.logging import get_logger
from src.use_cases.sdk.events import EVENT_WECHAT_MESSAGE, publish

logger = get_logger(__name__)


class WechatMixin:
    """微信回复相关方法。"""

    async def _send_wechat_reply_if_needed(self, reply_text: str) -> None:
        """LLM 回复完成后，如果有待发送的 WeChat 消息，回复给微信用户"""
        try:
            from src.infrastructure.web import get_device_registry, get_app
            registry = get_device_registry()
            if not registry:
                return
            entry = registry.resolve(self.device_key)
            if not entry or not isinstance(entry, dict):
                return
            wechat_chat_id = entry.get('wechat_chat_id', '')
            reply_pending = entry.get('wechat_reply_pending', False)
            if not wechat_chat_id or not reply_pending:
                return
            entry['wechat_reply_pending'] = False
            bot = getattr(get_app().state, 'wechat_bot', None)
            if bot and hasattr(bot, 'send_text') and reply_text:
                await bot.send_text(wechat_chat_id, reply_text)
                logger.info(f"[WeChat] LLM 回复已发送到微信 {wechat_chat_id[:20]}: {reply_text[:60]}")
                # 微信消息事件 → 发布给订阅插件（publish 内部容错）
                publish(EVENT_WECHAT_MESSAGE, chat_id=wechat_chat_id, text=reply_text)
        except Exception as e:
            logger.error(f"[WeChat] 发送 LLM 回复到微信失败: {e}", exc_info=True)

