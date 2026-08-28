"""
VolcEngineTTSGateway / VoiceGenerator 单元测试

覆盖范围：
- Message 协议 marshal/unmarshal/from_bytes
- receive_message / full_client_request / finish_connection
- get_resource_id
- VolcEngineTTSGateway 构造与配置
- get_pool / close_pool
- _create_connection / create_session / synthesize / synthesize_stream / close
- TTSSession synthesize / close / _reconnect
- VoiceGenerator make_tts_frame / make_end_frame
- create_tts_gateway 工厂函数
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import websockets

from src.interfaces.tts_gateways import (
    EventType,
    Message,
    MsgType,
    MsgTypeFlagBits,
    TTSSession,
    VoiceGenerator,
    VolcEngineTTSGateway,
    create_tts_gateway,
    finish_connection,
    full_client_request,
    get_resource_id,
    receive_message,
)


# ─── 辅助：构造 Mock settings / websocket ──────────────────

def make_mock_tts_settings(enable_pool=True, api_key="default-tts-key"):
    """构造模拟的 settings.tts 配置"""
    settings = MagicMock()
    settings.tts.api_key = api_key
    settings.tts.resource_id = "seed-tts-2.0"
    settings.tts.voice_type = "BV001_streaming"
    settings.tts.sample_rate = 24000
    settings.tts.speed_ratio = 1.0
    settings.tts.volume_ratio = 1.0
    settings.tts.pitch_ratio = 1.0
    settings.tts.explicit_dialect = ""
    settings.tts.provider = "volcengine"
    settings.tts.enable_pool = enable_pool
    settings.tts.pool_max_size = 10
    settings.tts.pool_min_size = 2
    settings.tts.pool_heartbeat_interval = 30
    settings.tts.pool_idle_timeout = 300
    settings.tts.pool_connection_timeout = 15
    return settings


class FakeWebSocket:
    """模拟 websocket 连接"""

    def __init__(self):
        self.send = AsyncMock()
        self.recv = AsyncMock()
        self.close = AsyncMock()
        self.ping = AsyncMock()
        self.open = True
        self.close_code = None


@pytest.fixture
def patched_tts():
    """patch get_settings 与 websockets.connect，返回控制句柄"""
    settings = make_mock_tts_settings()
    fake_ws = FakeWebSocket()
    with patch("src.interfaces.tts_gateways.get_settings", return_value=settings) as m_settings, \
            patch("src.interfaces.tts_gateways.websockets.connect",
                  new=AsyncMock(return_value=fake_ws)) as m_connect:
        yield {
            "settings": settings,
            "websockets_connect": m_connect,
            "fake_ws": fake_ws,
        }


@pytest.fixture(autouse=True)
def reset_tts_pool():
    """每个测试前后重置类级连接池字典，避免相互影响"""
    VolcEngineTTSGateway._pools.clear()
    VolcEngineTTSGateway._pool_warmed.clear()
    yield
    VolcEngineTTSGateway._pools.clear()
    VolcEngineTTSGateway._pool_warmed.clear()


def _close_coro_side_effect(coro, *args, **kwargs):
    """模拟 asyncio.create_task：直接关闭传入的协程，避免未 await 警告"""
    if hasattr(coro, "close"):
        coro.close()
    return MagicMock()


# ─── Message 协议测试 ──────────────────────────────────────

class TestMessageProtocol:
    """Message 二进制协议测试"""

    def test_marshal_unmarshal_full_client_request(self):
        # NoSeq flag 的 FullClientRequest：写入/读取 payload，对称
        msg = Message(type=MsgType.FullClientRequest, flag=MsgTypeFlagBits.NoSeq)
        msg.payload = b'{"hello":"world"}'
        data = msg.marshal()
        assert isinstance(data, bytes)
        # 通过 from_bytes 解析回来
        parsed = Message.from_bytes(data)
        assert parsed.type == MsgType.FullClientRequest
        assert parsed.flag == MsgTypeFlagBits.NoSeq
        assert parsed.payload == b'{"hello":"world"}'

    def test_marshal_unmarshal_audio_only_server_with_seq(self):
        # AudioOnlyServer + PositiveSeq：写入/读取 sequence + payload，对称
        msg = Message(type=MsgType.AudioOnlyServer, flag=MsgTypeFlagBits.PositiveSeq)
        msg.sequence = 42
        msg.payload = b"audio-bytes"
        data = msg.marshal()
        parsed = Message.from_bytes(data)
        assert parsed.type == MsgType.AudioOnlyServer
        assert parsed.flag == MsgTypeFlagBits.PositiveSeq
        assert parsed.sequence == 42
        assert parsed.payload == b"audio-bytes"

    def test_marshal_unmarshal_error_message(self):
        # Error 类型：写入/读取 error_code + payload
        msg = Message(type=MsgType.Error)
        msg.error_code = 1001
        msg.payload = b"err"
        data = msg.marshal()
        parsed = Message.from_bytes(data)
        assert parsed.type == MsgType.Error
        assert parsed.error_code == 1001
        assert parsed.payload == b"err"

    def test_from_bytes_too_short_raises(self):
        with pytest.raises(ValueError):
            Message.from_bytes(b"\x00")

    def test_message_default_values(self):
        msg = Message()
        assert msg.version.value == 1
        assert msg.type == MsgType.Invalid
        assert msg.payload == b""

    def test_message_with_event_start_connection_no_session_id(self):
        # StartConnection 事件不写 session_id
        msg = Message(type=MsgType.FullClientRequest, flag=MsgTypeFlagBits.WithEvent)
        msg.event = EventType.StartConnection
        msg.payload = b"{}"
        data = msg.marshal()
        # 至少能序列化
        assert len(data) > 4


# ─── receive_message / full_client_request / finish_connection ─

class TestWsHelpers:
    """websocket 辅助函数测试"""

    async def test_receive_message_bytes(self):
        ws = FakeWebSocket()
        msg = Message(type=MsgType.AudioOnlyServer, flag=MsgTypeFlagBits.PositiveSeq)
        msg.sequence = 1
        msg.payload = b"audio"
        ws.recv.return_value = msg.marshal()
        result = await receive_message(ws)
        assert result.type == MsgType.AudioOnlyServer
        assert result.payload == b"audio"

    async def test_receive_message_str_raises(self):
        ws = FakeWebSocket()
        ws.recv.return_value = "text-message"
        with pytest.raises(ValueError):
            await receive_message(ws)

    async def test_receive_message_other_type_raises(self):
        ws = FakeWebSocket()
        ws.recv.return_value = 12345
        with pytest.raises(ValueError):
            await receive_message(ws)

    async def test_full_client_request_sends_bytes(self):
        ws = FakeWebSocket()
        await full_client_request(ws, b'{"text":"hi"}')
        ws.send.assert_awaited_once()
        sent = ws.send.await_args.args[0]
        assert isinstance(sent, bytes)
        # 解析回来验证 payload
        parsed = Message.from_bytes(sent)
        assert parsed.type == MsgType.FullClientRequest
        assert parsed.payload == b'{"text":"hi"}'

    async def test_finish_connection_sends_bytes(self):
        ws = FakeWebSocket()
        await finish_connection(ws)
        ws.send.assert_awaited_once()
        sent = ws.send.await_args.args[0]
        assert isinstance(sent, bytes)
        parsed = Message.from_bytes(sent)
        assert parsed.flag == MsgTypeFlagBits.WithEvent
        assert parsed.event == EventType.FinishConnection


# ─── get_resource_id 测试 ──────────────────────────────────

class TestGetResourceId:
    """get_resource_id 测试"""

    def test_s_prefix_voice(self):
        # 声音复刻大模型音色 -> seed-icl-2.0
        assert get_resource_id("S_xyz") == "seed-icl-2.0"

    def test_clone_prefixes(self):
        # 复刻查询接口(icl_)/复刻2.0(saturn_)/DIT复刻(DiT_)同样归为声音复刻
        assert get_resource_id("icl_xyz") == "seed-icl-2.0"
        assert get_resource_id("saturn_xyz") == "seed-icl-2.0"
        assert get_resource_id("DiT_xyz") == "seed-icl-2.0"

    def test_bigtts_voice(self):
        # 豆包语音合成大模型(模型2.0)音色 -> seed-tts-2.0
        assert get_resource_id("zh_female_xiaohe_uranus_bigtts") == "seed-tts-2.0"
        assert get_resource_id("zh_female_wanwanxiaohe_moon_bigtts") == "seed-tts-2.0"

    def test_normal_voice(self):
        assert get_resource_id("BV001_streaming") == "seed-tts-2.0"

    def test_empty_voice(self):
        assert get_resource_id("") == "seed-tts-2.0"


# ─── VoiceGenerator 测试 ───────────────────────────────────

class TestVoiceGenerator:
    """VoiceGenerator 帧构造测试"""

    def setup_method(self):
        self.gen = VoiceGenerator()

    def test_make_tts_frame_normal(self):
        audio = b"\x00\x01\x02\x03"
        frame = self.gen.make_tts_frame("0001", audio)
        assert frame == b"0001" + b"00" + audio

    def test_make_tts_frame_with_status(self):
        frame = self.gen.make_tts_frame("abcd", b"\xff", status="01")
        assert frame == b"abcd" + b"01" + b"\xff"

    def test_make_end_frame(self):
        assert self.gen.make_end_frame("0001") == b"0001" + b"03"

    def test_make_end_frame_continue(self):
        # status="02"：继续对话语义（服务端无缝续轮时使用）
        assert self.gen.make_end_frame("0001", status="02") == b"0001" + b"02"

    def test_make_end_frame_empty_session(self):
        assert self.gen.make_end_frame("") == b"03"

    def test_make_tts_frame_empty_audio(self):
        assert self.gen.make_tts_frame("0001", b"") == b"000100"


# ─── VolcEngineTTSGateway 构造测试 ─────────────────────────

class TestVolcEngineTTSGatewayInit:
    """VolcEngineTTSGateway 构造与配置测试"""

    def test_init_with_config(self, patched_tts):
        config = {
            "api_key": "k1",
            "resource_id": "rid",
            "voice_type": "BV002",
            "speed_ratio": 1.2,
            "volume_ratio": 0.8,
            "pitch_ratio": 1.1,
            "enable_pool": False,
        }
        gw = VolcEngineTTSGateway(config=config)
        assert gw.api_key == "k1"
        assert gw.resource_id == "rid"
        assert gw.voice_type == "BV002"
        assert gw.speed_ratio == 1.2
        assert gw.volume_ratio == 0.8
        assert gw.pitch_ratio == 1.1
        assert gw._enable_pool is False

    def test_init_defaults_from_settings(self, patched_tts):
        gw = VolcEngineTTSGateway(config=None)
        assert gw.api_key == "default-tts-key"
        assert gw.voice_type == "BV001_streaming"
        assert gw.speed_ratio == 1.0
        assert gw._max_retries == 3

    def test_init_resource_id_derived_from_voice(self, patched_tts):
        # settings 中 resource_id 为空、config 未提供时，按 voice_type 推导
        patched_tts["settings"].tts.resource_id = ""
        gw = VolcEngineTTSGateway(config={"api_key": "k", "voice_type": "S_123"})
        assert gw.resource_id == "seed-icl-2.0"

    def test_init_sample_rate_from_device(self, patched_tts):
        # 设备上报 spk_sample_rate=16000 时，TTS 采样率跟随设备
        gw = VolcEngineTTSGateway(config={"api_key": "k", "sample_rate": 16000})
        assert gw.sample_rate == 16000

    def test_init_sample_rate_default(self, patched_tts):
        # 未上报时用全局默认 24000
        gw = VolcEngineTTSGateway(config={"api_key": "k"})
        assert gw.sample_rate == 24000

    def test_init_sample_rate_invalid_fallback(self, patched_tts):
        # 非法采样率回退到 24000
        gw = VolcEngineTTSGateway(config={"api_key": "k", "sample_rate": 12345})
        assert gw.sample_rate == 24000

    def test_init_enable_pool_requires_api_key(self, patched_tts):
        # api_key 为空时，即使配置开启连接池，实际也关闭
        gw = VolcEngineTTSGateway(config={"api_key": "", "enable_pool": True})
        assert gw._enable_pool is False


# ─── get_pool / close_pool 测试 ────────────────────────────

class TestTTSPool:
    """连接池类方法测试"""

    def test_get_pool_disabled(self, patched_tts):
        patched_tts["settings"].tts.enable_pool = False
        assert VolcEngineTTSGateway.get_pool() is None

    def test_get_pool_no_api_key(self, patched_tts):
        patched_tts["settings"].tts.enable_pool = True
        assert VolcEngineTTSGateway.get_pool(config={}) is None

    def test_get_pool_creates_pool(self, patched_tts):
        patched_tts["settings"].tts.enable_pool = True
        config = {"api_key": "k", "voice_type": "BV001"}
        with patch("src.interfaces.tts_gateways.asyncio.create_task",
                   side_effect=_close_coro_side_effect) as m_task:
            pool = VolcEngineTTSGateway.get_pool(config=config)
        assert pool is not None
        assert pool in VolcEngineTTSGateway._pools.values()
        m_task.assert_called_once()
        # 再次获取应复用
        with patch("src.interfaces.tts_gateways.asyncio.create_task",
                   side_effect=_close_coro_side_effect):
            pool2 = VolcEngineTTSGateway.get_pool(config=config)
        assert pool2 is pool

    async def test_close_pool_no_pool(self, patched_tts):
        # 没有连接池时 close_pool 不报错
        await VolcEngineTTSGateway.close_pool()

    def test_get_pool_isolated_per_config(self, patched_tts):
        """不同设备配置（api_key/voice_type 不同）应持有独立连接池，避免密钥串用"""
        patched_tts["settings"].tts.enable_pool = True
        with patch("src.interfaces.tts_gateways.asyncio.create_task",
                   side_effect=_close_coro_side_effect):
            pool_a = VolcEngineTTSGateway.get_pool(config={"api_key": "key-a", "voice_type": "BV001"})
            pool_b = VolcEngineTTSGateway.get_pool(config={"api_key": "key-b", "voice_type": "BV001"})
        assert pool_a is not pool_b
        assert len(VolcEngineTTSGateway._pools) == 2
        # 相同配置复用同一个池
        with patch("src.interfaces.tts_gateways.asyncio.create_task",
                   side_effect=_close_coro_side_effect):
            assert VolcEngineTTSGateway.get_pool(config={"api_key": "key-a", "voice_type": "BV001"}) is pool_a

    async def test_close_pool_with_pool(self, patched_tts):
        patched_tts["settings"].tts.enable_pool = True
        config = {"api_key": "k"}
        with patch("src.interfaces.tts_gateways.asyncio.create_task",
                   side_effect=_close_coro_side_effect):
            pool = VolcEngineTTSGateway.get_pool(config=config)
        pool.close = AsyncMock()
        await VolcEngineTTSGateway.close_pool()
        pool.close.assert_awaited_once()
        assert VolcEngineTTSGateway._pools == {}


# ─── _create_connection / create_session 测试 ──────────────

class TestCreateSession:
    """create_session 测试"""

    async def test_create_connection_success(self, patched_tts):
        gw = VolcEngineTTSGateway(config={"api_key": "k"})
        ws = await gw._create_connection()
        assert ws is patched_tts["fake_ws"]
        patched_tts["websockets_connect"].assert_awaited_once()

    async def test_create_session_success(self, patched_tts):
        gw = VolcEngineTTSGateway(config={"api_key": "k"})
        # 池的 acquire 会创建后台心跳任务，patch 掉避免测试后残留挂起
        with patch("src.interfaces.tts_gateways.asyncio.create_task",
                   side_effect=_close_coro_side_effect):
            session = await gw.create_session()
        assert isinstance(session, TTSSession)
        assert session.websocket is patched_tts["fake_ws"]
        # websocket 已加入活跃列表
        assert patched_tts["fake_ws"] in gw._active_websockets

    async def test_create_session_cancel_event(self, patched_tts):
        gw = VolcEngineTTSGateway(config={"api_key": "k"})
        cancel_event = MagicMock()
        cancel_event.is_set.return_value = True
        with patch("src.interfaces.tts_gateways.asyncio.create_task",
                   side_effect=_close_coro_side_effect):
            with pytest.raises(asyncio_cancelled_error_or_runtime()):
                await gw.create_session(cancel_event=cancel_event)

    async def test_create_session_retry_then_fail(self, patched_tts):
        # 连接持续失败，重试后抛出异常
        # 注意：必须禁用连接池——池的后台 _cleanup_loop 会持有 asyncio.sleep(60)，
        # 若把 asyncio.sleep patch 成立即返回，清理循环会变成忙等死循环卡死事件循环
        gw = VolcEngineTTSGateway(config={"api_key": "k", "enable_pool": False})
        patched_tts["websockets_connect"].side_effect = OSError("conn refused")
        with pytest.raises((OSError, RuntimeError)):
            await gw.create_session()


def asyncio_cancelled_error_or_runtime():
    """跨版本兼容：返回 CancelledError 或 RuntimeError"""
    import asyncio
    return (asyncio.CancelledError, RuntimeError)


# ─── synthesize_stream 测试 ────────────────────────────────

class TestSynthesizeStream:
    """synthesize / synthesize_stream 流式合成测试"""

    async def test_synthesize_stream_success(self, patched_tts):
        gw = VolcEngineTTSGateway(config={"api_key": "k"})
        # 构造两条消息：音频 + SessionFinished
        audio_msg = Message(type=MsgType.AudioOnlyServer, flag=MsgTypeFlagBits.PositiveSeq)
        audio_msg.sequence = 1
        audio_msg.payload = b"audio-data"
        done_msg = Message(type=MsgType.FullServerResponse, flag=MsgTypeFlagBits.WithEvent)
        done_msg.event = EventType.SessionFinished
        # receive_message 直接返回 Message 对象
        with patch("src.interfaces.tts_gateways.receive_message",
                   new=AsyncMock(side_effect=[audio_msg, done_msg])):
            results = []
            async for chunk in gw.synthesize_stream("hello"):
                results.append(chunk)
        assert results == [b"audio-data"]

    async def test_synthesize_stream_session_failed(self, patched_tts):
        gw = VolcEngineTTSGateway(config={"api_key": "k"})
        fail_msg = Message(type=MsgType.FullServerResponse, flag=MsgTypeFlagBits.WithEvent)
        fail_msg.event = EventType.SessionFailed
        fail_msg.payload = b"failure"
        with patch("src.interfaces.tts_gateways.receive_message",
                   new=AsyncMock(return_value=fail_msg)):
            results = []
            async for chunk in gw.synthesize_stream("hello"):
                results.append(chunk)
        assert results == []

    async def test_synthesize_stream_error_message(self, patched_tts):
        gw = VolcEngineTTSGateway(config={"api_key": "k"})
        err_msg = Message(type=MsgType.Error)
        err_msg.payload = b"err"
        with patch("src.interfaces.tts_gateways.receive_message",
                   new=AsyncMock(return_value=err_msg)):
            results = []
            async for chunk in gw.synthesize_stream("hello"):
                results.append(chunk)
        assert results == []

    async def test_synthesize_stream_cancel_event(self, patched_tts):
        gw = VolcEngineTTSGateway(config={"api_key": "k"})
        cancel_event = MagicMock()
        cancel_event.is_set.return_value = True
        # 取消事件触发时应立即返回
        with patch("src.interfaces.tts_gateways.receive_message", new=AsyncMock()):
            results = []
            async for chunk in gw.synthesize_stream("hello", cancel_event=cancel_event):
                results.append(chunk)
        assert results == []

    async def test_synthesize_stream_empty_payload_audio_skipped(self, patched_tts):
        gw = VolcEngineTTSGateway(config={"api_key": "k"})
        empty_audio = Message(type=MsgType.AudioOnlyServer, flag=MsgTypeFlagBits.PositiveSeq)
        empty_audio.payload = b""
        done_msg = Message(type=MsgType.FullServerResponse, flag=MsgTypeFlagBits.WithEvent)
        done_msg.event = EventType.SessionFinished
        with patch("src.interfaces.tts_gateways.receive_message",
                   new=AsyncMock(side_effect=[empty_audio, done_msg])):
            results = []
            async for chunk in gw.synthesize_stream("hello"):
                results.append(chunk)
        # 空 payload 不应 yield
        assert results == []

    async def test_synthesize_delegates_to_stream(self, patched_tts):
        gw = VolcEngineTTSGateway(config={"api_key": "k"})
        done_msg = Message(type=MsgType.FullServerResponse, flag=MsgTypeFlagBits.WithEvent)
        done_msg.event = EventType.SessionFinished
        with patch("src.interfaces.tts_gateways.receive_message",
                   new=AsyncMock(return_value=done_msg)):
            results = []
            async for chunk in gw.synthesize("hi"):
                results.append(chunk)
        assert results == []


# ─── TTSSession 测试 ───────────────────────────────────────

class TestTTSSession:
    """TTSSession 行为测试"""

    async def test_session_synthesize_success(self, patched_tts):
        gw = VolcEngineTTSGateway(config={"api_key": "k"})
        ws = FakeWebSocket()
        session = TTSSession(gw, ws, "sid-1")
        audio_msg = Message(type=MsgType.AudioOnlyServer, flag=MsgTypeFlagBits.PositiveSeq)
        audio_msg.payload = b"chunk"
        done_msg = Message(type=MsgType.FullServerResponse, flag=MsgTypeFlagBits.WithEvent)
        done_msg.event = EventType.SessionFinished
        with patch("src.interfaces.tts_gateways.receive_message",
                   new=AsyncMock(side_effect=[audio_msg, done_msg])):
            results = []
            async for chunk in session.synthesize("hello"):
                results.append(chunk)
        # session.synthesize 产出 TTSSynthEvent（kind=audio）
        assert [(r.kind, r.data) for r in results] == [("audio", b"chunk")]
        # 序号自增
        assert session._seq == 1

    async def test_session_synthesize_closed_returns_nothing(self, patched_tts):
        gw = VolcEngineTTSGateway(config={"api_key": "k"})
        ws = FakeWebSocket()
        session = TTSSession(gw, ws, "sid-1")
        session._closed = True
        results = []
        async for chunk in session.synthesize("hello"):
            results.append(chunk)
        assert results == []

    async def test_session_close(self, patched_tts):
        gw = VolcEngineTTSGateway(config={"api_key": "k"})
        ws = FakeWebSocket()
        gw._active_websockets.append(ws)
        session = TTSSession(gw, ws, "sid-1")
        await session.close()
        assert session._closed is True
        ws.close.assert_awaited()
        assert ws not in gw._active_websockets

    async def test_session_close_idempotent(self, patched_tts):
        gw = VolcEngineTTSGateway(config={"api_key": "k"})
        ws = FakeWebSocket()
        session = TTSSession(gw, ws, "sid-1")
        await session.close()
        # 第二次 close 不应再调用 ws.close
        ws.close.reset_mock()
        await session.close()
        ws.close.assert_not_awaited()

    async def test_session_synthesize_session_failed(self, patched_tts):
        gw = VolcEngineTTSGateway(config={"api_key": "k"})
        ws = FakeWebSocket()
        session = TTSSession(gw, ws, "sid-1")
        fail_msg = Message(type=MsgType.FullServerResponse, flag=MsgTypeFlagBits.WithEvent)
        fail_msg.event = EventType.SessionFailed
        fail_msg.payload = b"fail"
        with patch("src.interfaces.tts_gateways.receive_message",
                   new=AsyncMock(return_value=fail_msg)):
            results = []
            async for chunk in session.synthesize("hello"):
                results.append(chunk)
        assert results == []

    async def test_session_synthesize_cancel_event(self, patched_tts):
        gw = VolcEngineTTSGateway(config={"api_key": "k"})
        ws = FakeWebSocket()
        session = TTSSession(gw, ws, "sid-1")
        cancel_event = MagicMock()
        cancel_event.is_set.return_value = True
        with patch("src.interfaces.tts_gateways.receive_message", new=AsyncMock()):
            results = []
            async for chunk in session.synthesize("hello", cancel_event=cancel_event):
                results.append(chunk)
        assert results == []

    async def test_session_reconnect(self, patched_tts):
        gw = VolcEngineTTSGateway(config={"api_key": "k"})
        old_ws = FakeWebSocket()
        new_ws = FakeWebSocket()
        gw._active_websockets.append(old_ws)
        session = TTSSession(gw, old_ws, "sid-1")
        session._seq = 5
        # _create_connection 返回新 ws
        with patch.object(gw, "_create_connection", new=AsyncMock(return_value=new_ws)):
            await session._reconnect()
        assert session.websocket is new_ws
        assert session._seq == 0
        assert old_ws not in gw._active_websockets
        assert new_ws in gw._active_websockets

    async def test_session_is_expired(self, patched_tts):
        import time as _time
        gw = VolcEngineTTSGateway(config={"api_key": "k"})
        ws = FakeWebSocket()
        session = TTSSession(gw, ws, "sid-1")
        # 当前刚创建，未过期
        assert session._is_expired(max_idle=10000) is False
        # 将创建时间设为很久以前，则过期
        session._created_at = _time.time() - 100
        assert session._is_expired(max_idle=10) is True


# ─── close 测试 ────────────────────────────────────────────

class TestGatewayClose:
    """VolcEngineTTSGateway.close 测试"""

    async def test_close_closes_all_websockets(self, patched_tts):
        gw = VolcEngineTTSGateway(config={"api_key": "k"})
        ws1 = FakeWebSocket()
        ws2 = FakeWebSocket()
        gw._active_websockets.extend([ws1, ws2])
        await gw.close()
        ws1.close.assert_awaited_once()
        ws2.close.assert_awaited_once()
        assert gw._active_websockets == []

    async def test_close_empty(self, patched_tts):
        gw = VolcEngineTTSGateway(config={"api_key": "k"})
        await gw.close()  # 不应报错
        assert gw._active_websockets == []

    async def test_close_session_delegates(self, patched_tts):
        gw = VolcEngineTTSGateway(config={"api_key": "k"})
        session = MagicMock()
        session.close = AsyncMock()
        await gw.close_session(session)
        session.close.assert_awaited_once()

    async def test_close_session_none(self, patched_tts):
        gw = VolcEngineTTSGateway(config={"api_key": "k"})
        # 传入 None 不应报错
        await gw.close_session(None)


# ─── create_tts_gateway 工厂函数测试 ───────────────────────

class TestCreateTTSGateway:
    """create_tts_gateway 工厂函数测试"""

    def test_create_volcengine_provider(self, patched_tts):
        gw = create_tts_gateway(config={"provider": "volcengine", "api_key": "k"})
        assert isinstance(gw, VolcEngineTTSGateway)
        assert gw.api_key == "k"

    def test_create_default_provider(self, patched_tts):
        gw = create_tts_gateway(config={"api_key": "k"})
        assert isinstance(gw, VolcEngineTTSGateway)

    def test_create_no_config(self, patched_tts):
        gw = create_tts_gateway()
        assert isinstance(gw, VolcEngineTTSGateway)
        assert gw.api_key == "default-tts-key"

    def test_create_unknown_provider_falls_back(self, patched_tts):
        # 未知 provider 也回退到 VolcEngineTTSGateway
        gw = create_tts_gateway(config={"provider": "unknown", "api_key": "k"})
        assert isinstance(gw, VolcEngineTTSGateway)
