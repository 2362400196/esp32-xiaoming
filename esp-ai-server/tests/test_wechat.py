"""
WeChat 微信集成单元测试

覆盖范围：
- wechat_binding.py：配对码创建 / 消费（一次性）/ 过期
- routes/wechat.py：配对码生成接口（JWT 认证 + 设备归属校验）
- wechat_bot.py：群聊消息忽略，仅支持私聊；会话新鲜度判断；send_text -2 处理
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.use_cases.wechat_binding import (
    _pairing_codes,
    consume_pairing_code,
    create_pairing_code,
)
from src.use_cases.wechat_bot import WeChatAPIError


@pytest.fixture(autouse=True)
def _clean_pairing_codes():
    """每个用例前后清空内存配对码表，避免相互污染"""
    _pairing_codes.clear()
    yield
    _pairing_codes.clear()


# ── 配对码：创建 / 消费 / 过期 ──────────────────

class TestPairingCode:
    def test_create_and_consume(self):
        """创建 6 位数字码 → 消费返回 device_key → 一次性（二次消费失败）"""
        code = create_pairing_code("device-key-abc")
        assert isinstance(code, str) and len(code) == 6 and code.isdigit()
        assert consume_pairing_code(code) == "device-key-abc"
        # 一次性：消费后即失效
        assert consume_pairing_code(code) is None

    def test_consume_invalid_code(self):
        """未生成的配对码 / 空串消费均返回 None"""
        assert consume_pairing_code("999999") is None
        assert consume_pairing_code("") is None

    def test_expired_code(self):
        """过期的配对码消费返回 None（已从表中移除）"""
        code = create_pairing_code("device-key-abc", ttl_seconds=-1)
        assert code in _pairing_codes
        assert consume_pairing_code(code) is None
        assert code not in _pairing_codes

    def test_create_cleans_expired_codes(self):
        """新建配对码时顺带清理过期项，内存不无限增长"""
        expired = create_pairing_code("device-old", ttl_seconds=-1)
        fresh = create_pairing_code("device-new")
        assert expired not in _pairing_codes
        assert consume_pairing_code(fresh) == "device-new"


# ── 配对码生成接口 ──────────────────────────────

def _mock_user():
    u = MagicMock()
    u.id = 1
    u.role = "admin"
    u.is_active = True
    return u


def _build_client():
    """构建挂载 wechat 路由的测试应用（覆盖 get_current_user 依赖）"""
    from src.infrastructure.routes.wechat import router
    from src.infrastructure.security_jwt import get_current_user

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: _mock_user()
    return TestClient(app)


class TestPairingCodeRoute:
    def test_create_pairing_code_success(self):
        client = _build_client()
        resp = client.post("/api/v1/wechat/pairing-code", json={"device_id": "AA:BB:CC:DD"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["expires_in"] == 600
        # 生成的配对码可以消费出 device_id（admin 免归属校验，resolve 失败回退原值）
        assert consume_pairing_code(data["data"]["code"]) == "AA:BB:CC:DD"

    def test_create_pairing_code_not_owner(self):
        """非管理员且设备不属于该用户 → 403"""
        from src.infrastructure.routes import wechat as wechat_route

        non_admin = _mock_user()
        non_admin.role = "user"
        from src.infrastructure.security_jwt import get_current_user

        app = FastAPI()
        app.include_router(wechat_route.router)
        app.dependency_overrides[get_current_user] = lambda: non_admin

        async def _deny(device_id, user):
            return False

        import src.infrastructure.routes.wechat as wr
        original = wr.check_device_owner
        wr.check_device_owner = _deny
        try:
            client = TestClient(app)
            resp = client.post("/api/v1/wechat/pairing-code", json={"device_id": "AA:BB:CC:DD"})
            assert resp.status_code == 403
        finally:
            wr.check_device_owner = original

    def test_create_pairing_code_missing_device_id(self):
        client = _build_client()
        resp = client.post("/api/v1/wechat/pairing-code", json={"device_id": ""})
        assert resp.status_code == 400


# ── 群聊消息忽略 ────────────────────────────────

def _make_bot_skeleton():
    """构造不触碰持久化文件的 WeChatBot 骨架（绕过 __init__ 的 token 加载）"""
    from src.use_cases.wechat_bot import WeChatBot, WeChatState

    bot = WeChatBot.__new__(WeChatBot)
    bot.state = WeChatState()
    return bot


class TestGroupMessageIgnored:
    def test_group_message_ignored(self):
        """群聊消息（带 group_id）直接忽略，不触发 on_message 回调"""
        bot = _make_bot_skeleton()
        called = []

        async def cb(*args):
            called.append(args)

        bot.on_message = cb
        msg = {
            "from_user_id": "user1",
            "group_id": "group1",
            "message_id": 1,
            "item_list": [{"type": 1, "text_item": {"text": "你好"}}],
        }
        asyncio.run(bot._process_message(msg))
        assert called == []

    def test_private_message_still_works(self):
        """私聊消息正常触发 on_message，chat_id 即 from_user_id"""
        bot = _make_bot_skeleton()
        called = []

        async def cb(*args):
            called.append(args)

        bot.on_message = cb
        msg = {
            "from_user_id": "user1",
            "message_id": 2,
            "item_list": [{"type": 1, "text_item": {"text": "你好"}}],
        }
        asyncio.run(bot._process_message(msg))
        assert len(called) == 1
        # 回调参数：bot, chat_id, sender_id, message_id, text, context_token
        assert called[0][1] == "user1"
        assert called[0][2] == "user1"
        assert called[0][4] == "你好"


# ── 会话新鲜度判断 ─────────────────────────────

class TestChatSessionFreshness:
    def test_fresh_session(self):
        """用户最近发过消息 → 会话新鲜"""
        bot = _make_bot_skeleton()
        bot.state.last_user_msg_time["user1"] = time.time()
        assert bot.is_chat_session_fresh("user1") is True

    def test_stale_session(self):
        """用户超过 24h 未互动 → 会话过期"""
        bot = _make_bot_skeleton()
        bot.state.last_user_msg_time["user1"] = time.time() - 25 * 3600
        assert bot.is_chat_session_fresh("user1") is False

    def test_no_record(self):
        """无互动记录（如重启后）→ 视为过期"""
        bot = _make_bot_skeleton()
        assert bot.is_chat_session_fresh("user1") is False

    def test_custom_max_age(self):
        bot = _make_bot_skeleton()
        bot.state.last_user_msg_time["user1"] = time.time() - 3600
        assert bot.is_chat_session_fresh("user1", max_age_seconds=7200) is True
        assert bot.is_chat_session_fresh("user1", max_age_seconds=1800) is False

    def test_process_message_records_time(self):
        """收到用户消息时记录互动时间"""
        bot = _make_bot_skeleton()
        bot.on_message = None
        bot.on_attachment = None
        msg = {
            "from_user_id": "user1",
            "message_id": 3,
            "item_list": [{"type": 1, "text_item": {"text": "你好"}}],
        }
        asyncio.run(bot._process_message(msg))
        assert "user1" in bot.state.last_user_msg_time
        assert bot.is_chat_session_fresh("user1") is True


# ── send_text -2 prepare failed 处理 ───────────

class TestSendTextMinus2Handling:
    def test_minus2_clears_context_and_retries_once(self):
        """-2 prepare failed：清 context_token 后重试一次（不带 token），仍失败则放弃"""
        bot = _make_bot_skeleton()
        bot.state.configured = True
        bot.state.context_cache["user1"] = "stale-token"
        calls = []

        async def fake_send(chat_id, chunk):
            calls.append(bot.state.context_cache.get(chat_id))
            raise WeChatAPIError(-2, "prepare failed")

        bot._send_text_chunk = fake_send
        ok = asyncio.run(bot.send_text("user1", "hello"))
        assert ok is False
        # 第一次带 context_token，第二次不带（已清除），不再盲目重试第三次
        assert len(calls) == 2
        assert calls[0] == "stale-token"
        assert calls[1] is None
        assert "user1" not in bot.state.context_cache

    def test_minus2_then_success_without_context(self):
        """清 context_token 后重试成功（服务端会话仍有效）"""
        bot = _make_bot_skeleton()
        bot.state.configured = True
        bot.state.context_cache["user1"] = "stale-token"
        calls = []

        async def fake_send(chat_id, chunk):
            calls.append(bot.state.context_cache.get(chat_id))
            if len(calls) == 1:
                raise WeChatAPIError(-2, "prepare failed")
            return None

        bot._send_text_chunk = fake_send
        ok = asyncio.run(bot.send_text("user1", "hello"))
        assert ok is True
        assert len(calls) == 2
        assert calls[0] == "stale-token"
        assert calls[1] is None

    def test_non_minus2_error_no_retry(self):
        """非 -2 错误不重试，直接失败"""
        bot = _make_bot_skeleton()
        bot.state.configured = True
        calls = []

        async def fake_send(chat_id, chunk):
            calls.append(1)
            raise WeChatAPIError(-14, "session timeout")

        bot._send_text_chunk = fake_send
        ok = asyncio.run(bot.send_text("user1", "hello"))
        assert ok is False
        assert len(calls) == 1
