"""proactive_brain 引擎测试：主动推送的会话新鲜度判断与失败计数

覆盖：
- 会话过期的设备被跳过，不调用 send_text
- 至少一个设备推送成功 → 返回 True
- 全部失败/全部跳过 → 返回 False
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.plugins.proactive_brain.engine import ProactiveBrain


class _Binding:
    def __init__(self, chat_id):
        self.wechat_chat_id = chat_id


class _Registry:
    def __init__(self, ids):
        self._ids = ids

    def get_all_ids(self):
        return self._ids


def _run_push(brain, bot, bindings, text="hello"):
    """在 mock 的 app.state / binding manager 下执行 _push_to_all"""
    app = MagicMock()
    app.state.wechat_bot = bot
    bind_mgr = MagicMock()
    bind_mgr.find_binding.side_effect = bindings
    with patch("src.infrastructure.web.get_app", return_value=app), \
         patch("src.use_cases.wechat_binding.get_wechat_binding_manager", return_value=bind_mgr):
        return asyncio.run(brain._push_to_all(text))


class TestPushToAll:
    def test_skips_stale_session(self):
        """会话过期的设备被跳过，不调用 send_text"""
        brain = ProactiveBrain()
        brain._registry = _Registry(["dev1", "dev2"])
        bot = MagicMock()
        bot.is_chat_session_fresh.side_effect = [False, True]
        bot.send_text = AsyncMock(return_value=True)

        ok = _run_push(brain, bot, [_Binding("chat1"), _Binding("chat2")])

        assert ok is True
        bot.send_text.assert_awaited_once_with("chat2", "hello")

    def test_all_stale_returns_false(self):
        """全部设备会话过期 → 返回 False，不调用 send_text"""
        brain = ProactiveBrain()
        brain._registry = _Registry(["dev1", "dev2"])
        bot = MagicMock()
        bot.is_chat_session_fresh.return_value = False
        bot.send_text = AsyncMock(return_value=True)

        ok = _run_push(brain, bot, [_Binding("chat1"), _Binding("chat2")])

        assert ok is False
        bot.send_text.assert_not_awaited()

    def test_all_send_fail_returns_false(self):
        """会话新鲜但发送全部失败 → 返回 False"""
        brain = ProactiveBrain()
        brain._registry = _Registry(["dev1"])
        bot = MagicMock()
        bot.is_chat_session_fresh.return_value = True
        bot.send_text = AsyncMock(return_value=False)

        ok = _run_push(brain, bot, [_Binding("chat1")])

        assert ok is False
        bot.send_text.assert_awaited_once_with("chat1", "hello")

    def test_partial_success_returns_true(self):
        """部分设备成功 → 返回 True"""
        brain = ProactiveBrain()
        brain._registry = _Registry(["dev1", "dev2"])
        bot = MagicMock()
        bot.is_chat_session_fresh.return_value = True
        bot.send_text = AsyncMock(side_effect=[False, True])

        ok = _run_push(brain, bot, [_Binding("chat1"), _Binding("chat2")])

        assert ok is True
        assert bot.send_text.await_count == 2

    def test_no_bot_returns_false(self):
        """wechat_bot 不可用 → 返回 False"""
        brain = ProactiveBrain()
        brain._registry = _Registry(["dev1"])
        app = MagicMock()
        app.state.wechat_bot = None
        with patch("src.infrastructure.web.get_app", return_value=app):
            ok = asyncio.run(brain._push_to_all("hello"))
        assert ok is False
