"""
ASR 网关单元测试

覆盖范围：
- BaseASRGateway 基类默认行为（通过 AliYunASRGateway 等具体子类验证）
- VolcEngineASRGateway：协议构造、URL/headers、parse_response、init_connection、
  pre_connect / disconnect、recognize / recognize_streaming
- TencentASRGateway：签名生成、URL 构造、parse_response、send_audio_*、
  pre_connect / disconnect、recognize / recognize_streaming
- create_asr_gateway 工厂函数（各 provider 与异常分支）
"""
import asyncio
import json
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.interfaces.asr.aliyun import AliYunASRGateway
from src.interfaces.asr.base import BaseASRGateway
from src.interfaces.asr.factory import create_asr_gateway
from src.interfaces.asr.tencent import TencentASRGateway
from src.interfaces.asr.volcengine import VolcEngineASRConnectionPool, VolcEngineASRGateway


# ─── 辅助：构造 Mock settings / websocket ──────────────────

def make_mock_asr_settings(enable_pool=False):
    """构造模拟的 settings.asr 配置"""
    settings = MagicMock()
    settings.asr.provider = "volcengine"
    settings.asr.tencent_app_id = "t-app"
    settings.asr.tencent_secret_id = "t-sid"
    settings.asr.tencent_secret_key = "t-skey"
    settings.asr.tencent_engine = "16k_zh"
    settings.asr.volcengine_api_key = "v-key"
    settings.asr.volcengine_resource_id = "volc.bigasr.sauc.duration"
    settings.asr.volcengine_model = "bigmodel"
    settings.asr.aliyun_access_key_id = "a-id"
    settings.asr.aliyun_access_key_secret = "a-secret"
    settings.asr.aliyun_app_key = "a-appkey"
    settings.asr.xunfei_app_id = "x-app"
    settings.asr.xunfei_api_key = "x-key"
    settings.asr.xunfei_api_secret = "x-secret"
    settings.asr.enable_pool = enable_pool
    settings.asr.pool_max_size = 10
    settings.asr.pool_min_size = 2
    settings.asr.pool_heartbeat_interval = 30
    settings.asr.pool_idle_timeout = 300
    settings.asr.pool_connection_timeout = 15
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


class FakeConnectResult:
    """同时支持 await 与 async with 的 websocket 连接代理
    - pre_connect: `await websockets.connect(...)` -> 返回内部 ws
    - recognize: `async with websockets.connect(...) as ws` -> 返回内部 ws
    """

    def __init__(self, ws):
        self._ws = ws

    def __await__(self):
        async def _coro():
            return self._ws
        return _coro().__await__()

    async def __aenter__(self):
        return self._ws

    async def __aexit__(self, *args):
        return False


class _ConcreteBaseASR(BaseASRGateway):
    """不覆盖任何方法的 BaseASRGateway 具体子类，用于测试基类默认行为"""

    def _build_url(self):
        return "wss://example/asr"

    def _get_headers(self):
        return {}

    async def init_connection(self, ws):
        return True

    async def send_audio_data(self, ws, audio_data):
        await ws.send(audio_data)

    async def send_audio_end(self, ws):
        await ws.send(b"")

    def parse_response(self, response):
        return None


def _build_volc_response(gw, result_dict, message_type=1, flags=0):
    """构造 VolcEngine ASR 二进制响应
    格式：header(4) + 占位(4) + payload_size(4) + payload
    （parse_response 从 offset 8 读取 payload_size）
    """
    body = json.dumps(result_dict).encode("utf-8")
    return (gw._make_header(message_type=message_type, flags=flags)
            + b"\x00\x00\x00\x00"
            + struct.pack(">I", len(body)) + body)


@pytest.fixture
def patched_asr():
    """patch get_settings 与 websockets.connect（MagicMock，返回 FakeConnectResult）"""
    settings = make_mock_asr_settings()
    default_ws = FakeWebSocket()
    with patch("src.interfaces.asr.volcengine.get_settings", return_value=settings), \
            patch("src.interfaces.asr.factory.get_settings", return_value=settings), \
            patch("src.interfaces.asr.tencent.websockets.connect",
                  return_value=FakeConnectResult(default_ws)) as m_connect_t, \
            patch("src.interfaces.asr.volcengine.websockets.connect",
                  return_value=FakeConnectResult(default_ws)) as m_connect_v:
        yield {
            "settings": settings,
            "tencent_connect": m_connect_t,
            "volcengine_connect": m_connect_v,
            "default_ws": default_ws,
        }


@pytest.fixture(autouse=True)
def reset_asr_pool():
    """重置 VolcEngineASRGateway 类级连接池"""
    VolcEngineASRGateway._pool = None
    VolcEngineASRGateway._pool_initialized = False
    yield
    VolcEngineASRGateway._pool = None
    VolcEngineASRGateway._pool_initialized = False


# ─── BaseASRGateway 测试 ───────────────────────────────────

class TestBaseASRGateway:
    """BaseASRGateway 基类默认行为测试（使用 _ConcreteBaseASR 具体子类）"""

    def test_take_pre_ws_returns_none_initially(self):
        gw = _ConcreteBaseASR(config={})
        ws, wrapper = gw.take_pre_ws()
        assert ws is None
        assert wrapper is None

    def test_take_pre_ws_clears_state(self):
        gw = _ConcreteBaseASR(config={})
        gw._pre_ws = "ws"
        gw._pre_ws_pool_wrapper = "wrapper"
        ws, wrapper = gw.take_pre_ws()
        assert ws == "ws"
        assert wrapper == "wrapper"
        assert gw._pre_ws is None
        assert gw._pre_ws_pool_wrapper is None

    def test_get_pool_returns_none_by_default(self):
        gw = _ConcreteBaseASR(config={})
        assert gw.get_pool() is None

    async def test_close_pool_default_noop(self):
        await _ConcreteBaseASR.close_pool()

    async def test_pre_connect_returns_none_default(self):
        gw = _ConcreteBaseASR(config={})
        assert await gw.pre_connect() is None

    async def test_disconnect_default_noop(self):
        gw = _ConcreteBaseASR(config={})
        await gw.disconnect()  # 不应报错

    async def test_recognize_default_returns_empty(self):
        gw = _ConcreteBaseASR(config={})
        assert await gw.recognize(b"audio") == ""

    async def test_recognize_stream_default_returns_empty(self):
        gw = _ConcreteBaseASR(config={})

        async def gen():
            yield b"chunk1"
            yield b"chunk2"

        assert await gw.recognize_stream(gen()) == ""

    async def test_recognize_streaming_default_returns_empty(self):
        gw = _ConcreteBaseASR(config={})
        assert await gw.recognize_streaming([b"a", b"b"]) == ""

    async def test_recognize_once_delegates_to_recognize(self):
        gw = _ConcreteBaseASR(config={})
        gw.recognize = AsyncMock(return_value="text")
        result = await gw.recognize_once(b"audio")
        assert result == "text"

    async def test_recognize_streaming_repo_calls_callbacks(self):
        gw = _ConcreteBaseASR(config={})
        gw.recognize_streaming = AsyncMock(return_value="final-text")

        async def gen():
            yield b"chunk"

        on_result = MagicMock()
        on_final = MagicMock()
        text = await gw.recognize_streaming_repo(gen(), on_result, on_final)
        assert text == "final-text"
        on_final.assert_called_once()

    def test_binary_protocol_default_false(self):
        gw = _ConcreteBaseASR(config={})
        assert gw.binary_protocol is False


# ─── VolcEngineASRGateway 测试 ─────────────────────────────

class TestVolcEngineASRGateway:
    """VolcEngineASRGateway 测试"""

    def test_init_defaults(self, patched_asr):
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        assert gw.api_key == "k"
        assert gw.resource_id == "volc.bigasr.sauc.duration"
        assert gw.model_name == "bigmodel"
        assert gw.binary_protocol is True
        assert gw._build_url() == "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"

    def test_init_with_custom_config(self, patched_asr):
        config = {
            "api_key": "k1",
            "resource_id": "custom.rid",
            "model_name": "custom-model",
        }
        gw = VolcEngineASRGateway(config=config)
        assert gw.api_key == "k1"
        assert gw.resource_id == "custom.rid"
        assert gw.model_name == "custom-model"

    def test_get_headers_contains_keys(self, patched_asr):
        gw = VolcEngineASRGateway(config={"api_key": "k", "resource_id": "rid"})
        headers = gw._get_headers()
        assert headers["X-Api-Key"] == "k"
        assert headers["X-Api-Resource-Id"] == "rid"
        assert "X-Api-Connect-Id" in headers

    def test_make_header_format(self, patched_asr):
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        header = gw._make_header(message_type=1, flags=0)
        assert len(header) == 4
        # byte0: version(1)<<4 | header_size(1) = 0x11
        assert header[0] == 0x11
        # byte1: (1<<4)|0 = 0x10
        assert header[1] == 0x10
        # byte2: serialization(1)<<4 | compression(0) = 0x10
        assert header[2] == 0x10

    def test_make_payload_format(self, patched_asr):
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        payload = gw._make_payload({"a": 1})
        size = struct.unpack(">I", payload[:4])[0]
        body = json.loads(payload[4:].decode("utf-8"))
        assert size == len(payload) - 4
        assert body == {"a": 1}

    def test_parse_response_valid_final(self, patched_asr):
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        result_dict = {
            "result": {"texts": [{"text": "hello"}], "additions": {"definite": True}},
            "is_final": False,
        }
        response = _build_volc_response(gw, result_dict)
        parsed = gw.parse_response(response)
        assert parsed is not None
        assert parsed["text"] == "hello"
        assert parsed["is_final"] is True

    def test_parse_response_utterances_definite(self, patched_asr):
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        result_dict = {
            "result": {
                "texts": [{"text": "world"}],
                "utterances": [{"definite": True, "text": "world"}],
            },
        }
        response = _build_volc_response(gw, result_dict)
        parsed = gw.parse_response(response)
        assert parsed["is_final"] is True

    def test_parse_response_not_final(self, patched_asr):
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        result_dict = {"result": {"texts": [{"text": "partial"}]}}
        response = _build_volc_response(gw, result_dict)
        parsed = gw.parse_response(response)
        assert parsed["text"] == "partial"
        assert parsed["is_final"] is False

    def test_parse_response_error_code_returns_none(self, patched_asr):
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        result_dict = {"code": 1001, "message": "bad"}
        response = _build_volc_response(gw, result_dict)
        assert gw.parse_response(response) is None

    def test_parse_response_error_field_returns_none(self, patched_asr):
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        result_dict = {"error": "something wrong"}
        response = _build_volc_response(gw, result_dict)
        assert gw.parse_response(response) is None

    def test_parse_response_too_short_returns_none(self, patched_asr):
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        assert gw.parse_response(b"\x00\x01\x02") is None

    def test_parse_response_str_input(self, patched_asr):
        # 字符串输入应被转为 bytes 处理
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        result_dict = {"result": {"texts": [{"text": "hi"}]}}
        response_bytes = _build_volc_response(gw, result_dict)
        parsed = gw.parse_response(response_bytes.decode("latin-1"))
        assert parsed is not None
        assert parsed["text"] == "hi"

    async def test_send_audio_data_sends_bytes(self, patched_asr):
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        ws = FakeWebSocket()
        await gw.send_audio_data(ws, b"audio-data")
        ws.send.assert_awaited_once()
        sent = ws.send.await_args.args[0]
        # 头部 4 字节 + 长度 4 字节 + 音频
        assert sent[4:8] == struct.pack(">I", len(b"audio-data"))
        assert sent[8:] == b"audio-data"

    async def test_send_audio_end_sends_header_only(self, patched_asr):
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        ws = FakeWebSocket()
        await gw.send_audio_end(ws)
        ws.send.assert_awaited_once()
        sent = ws.send.await_args.args[0]
        assert len(sent) == 4

    async def test_init_connection_success(self, patched_asr):
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        ws = FakeWebSocket()
        # 构造一个 ack 响应（code=0）
        ws.recv.return_value = _build_volc_response(gw, {"code": 0})
        result = await gw.init_connection(ws)
        assert result is True

    async def test_init_connection_error_code(self, patched_asr):
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        ws = FakeWebSocket()
        ws.recv.return_value = _build_volc_response(gw, {"code": 1001, "message": "rejected"})
        result = await gw.init_connection(ws)
        assert result is False

    async def test_init_connection_error_field(self, patched_asr):
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        ws = FakeWebSocket()
        ws.recv.return_value = _build_volc_response(gw, {"error": "bad"})
        result = await gw.init_connection(ws)
        assert result is False

    async def test_init_connection_timeout_proceeds(self, patched_asr):
        # ack 超时时仍应返回 True（继续执行）
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        ws = FakeWebSocket()
        ws.recv.side_effect = asyncio.TimeoutError()
        result = await gw.init_connection(ws)
        assert result is True

    async def test_init_connection_send_exception(self, patched_asr):
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        ws = FakeWebSocket()
        ws.send.side_effect = RuntimeError("send failed")
        result = await gw.init_connection(ws)
        assert result is False

    async def test_pre_connect_disabled_pool_success(self, patched_asr):
        patched_asr["settings"].asr.enable_pool = False
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        fake_ws = FakeWebSocket()
        patched_asr["volcengine_connect"].return_value = FakeConnectResult(fake_ws)
        # init_connection 返回 True
        fake_ws.recv.return_value = _build_volc_response(gw, {"code": 0})
        result = await gw.pre_connect()
        assert result is fake_ws
        assert gw._pre_ws is fake_ws

    async def test_pre_connect_disabled_pool_init_fails(self, patched_asr):
        patched_asr["settings"].asr.enable_pool = False
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        fake_ws = FakeWebSocket()
        patched_asr["volcengine_connect"].return_value = FakeConnectResult(fake_ws)
        # init_connection 返回 False（send 失败）
        fake_ws.send.side_effect = RuntimeError("fail")
        result = await gw.pre_connect()
        assert result is None
        assert gw._pre_ws is None

    async def test_pre_connect_disabled_pool_exception(self, patched_asr):
        patched_asr["settings"].asr.enable_pool = False
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        patched_asr["volcengine_connect"].side_effect = OSError("conn refused")
        result = await gw.pre_connect()
        assert result is None

    async def test_pre_connect_closes_old_ws(self, patched_asr):
        patched_asr["settings"].asr.enable_pool = False
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        old_ws = FakeWebSocket()
        gw._pre_ws = old_ws
        new_ws = FakeWebSocket()
        patched_asr["volcengine_connect"].return_value = FakeConnectResult(new_ws)
        new_ws.recv.return_value = _build_volc_response(gw, {"code": 0})
        await gw.pre_connect()
        old_ws.close.assert_awaited_once()

    async def test_disconnect_closes_pre_ws(self, patched_asr):
        patched_asr["settings"].asr.enable_pool = False
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        ws = FakeWebSocket()
        gw._pre_ws = ws
        await gw.disconnect()
        ws.close.assert_awaited_once()
        assert gw._pre_ws is None

    async def test_disconnect_no_pre_ws(self, patched_asr):
        patched_asr["settings"].asr.enable_pool = False
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        await gw.disconnect()  # 不应报错
        assert gw._pre_ws is None

    async def test_recognize_success(self, patched_asr):
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        # 构造一个 final 响应
        resp = _build_volc_response(gw, {"result": {"texts": [{"text": "你好"}]}, "is_final": True})

        fake_ws = FakeWebSocket()
        fake_ws.recv.return_value = resp
        patched_asr["volcengine_connect"].return_value = FakeConnectResult(fake_ws)

        text = await gw.recognize(b"audio")
        assert text == "你好"

    async def test_recognize_with_callback(self, patched_asr):
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        partial_resp = _build_volc_response(gw, {"result": {"texts": [{"text": "部分"}]}})
        final_resp = _build_volc_response(gw, {"result": {"texts": [{"text": "完成"}]}, "is_final": True})
        fake_ws = FakeWebSocket()
        fake_ws.recv.side_effect = [partial_resp, final_resp]
        patched_asr["volcengine_connect"].return_value = FakeConnectResult(fake_ws)

        callback = MagicMock()
        text = await gw.recognize(b"audio", callback=callback)
        assert "完成" in text
        assert callback.call_count >= 1

    async def test_recognize_exception_returns_empty(self, patched_asr):
        gw = VolcEngineASRGateway(config={"api_key": "k"})
        patched_asr["volcengine_connect"].side_effect = OSError("fail")
        text = await gw.recognize(b"audio")
        assert text == ""

    async def test_get_pool_disabled(self, patched_asr):
        patched_asr["settings"].asr.enable_pool = False
        assert VolcEngineASRGateway.get_pool(config={"api_key": "k"}) is None

    async def test_get_pool_no_api_key(self, patched_asr):
        patched_asr["settings"].asr.enable_pool = True
        assert VolcEngineASRGateway.get_pool(config={}) is None

    async def test_close_pool_no_pool(self, patched_asr):
        await VolcEngineASRGateway.close_pool()  # 不应报错


# ─── VolcEngineASRConnectionPool 测试 ──────────────────────

class TestVolcEngineASRConnectionPool:
    """VolcEngineASRConnectionPool 基础测试"""

    def test_pool_init(self):
        pool = VolcEngineASRConnectionPool(
            api_key="k",
            resource_id="rid",
            model_name="model",
            max_size=5,
            min_size=1,
        )
        assert pool._api_key == "k"
        assert pool._resource_id == "rid"
        assert pool._model_name == "model"

    def test_pool_make_header(self):
        pool = VolcEngineASRConnectionPool(api_key="k")
        header = pool._make_header(message_type=2, flags=2)
        assert len(header) == 4
        assert header[1] == (2 << 4) | 2

    def test_pool_make_payload(self):
        pool = VolcEngineASRConnectionPool(api_key="k")
        payload = pool._make_payload({"x": 1})
        size = struct.unpack(">I", payload[:4])[0]
        assert size == len(payload) - 4


# ─── TencentASRGateway 测试 ────────────────────────────────

class TestTencentASRGateway:
    """TencentASRGateway 测试"""

    def test_init_defaults(self):
        config = {"app_id": "app1", "secret_id": "sid", "secret_key": "skey"}
        gw = TencentASRGateway(config=config)
        assert gw.app_id == "app1"
        assert gw.secret_id == "sid"
        assert gw.secret_key == "skey"
        assert gw.engine_model_type == "16k_zh"
        assert gw.voice_format == 1
        assert gw.needvad == 1
        assert gw.binary_protocol is False
        assert "app1" in gw.ws_url

    def test_init_custom_config(self):
        config = {
            "app_id": "app1",
            "secret_id": "sid",
            "secret_key": "skey",
            "engine_model_type": "16k_en",
            "voice_format": 3,
            "needvad": 0,
        }
        gw = TencentASRGateway(config=config)
        assert gw.engine_model_type == "16k_en"
        assert gw.voice_format == 3
        assert gw.needvad == 0

    def test_get_headers_empty(self):
        gw = TencentASRGateway(config={"app_id": "a", "secret_id": "s", "secret_key": "k"})
        assert gw._get_headers() == {}

    def test_build_url_contains_signature(self):
        gw = TencentASRGateway(config={"app_id": "a", "secret_id": "s", "secret_key": "k"})
        url = gw._build_url()
        assert url.startswith("wss://asr.cloud.tencent.com/asr/v2/a?")
        assert "signature=" in url
        assert "secretid=s" in url
        assert "engine_model_type=16k_zh" in url

    def test_generate_signature_deterministic(self):
        gw = TencentASRGateway(config={"app_id": "a", "secret_id": "s", "secret_key": "k"})
        params = {"a": "1", "b": "2"}
        sig1 = gw._generate_signature(params)
        sig2 = gw._generate_signature(params)
        assert sig1 == sig2
        # 签名经过 URL 编码
        assert "%" in sig1 or sig1.isalnum()

    async def test_init_connection_returns_true(self):
        gw = TencentASRGateway(config={"app_id": "a", "secret_id": "s", "secret_key": "k"})
        assert await gw.init_connection(MagicMock()) is True

    async def test_send_audio_data_bytes(self):
        gw = TencentASRGateway(config={"app_id": "a", "secret_id": "s", "secret_key": "k"})
        ws = FakeWebSocket()
        await gw.send_audio_data(ws, b"audio")
        ws.send.assert_awaited_with(b"audio")

    async def test_send_audio_data_non_bytes(self):
        gw = TencentASRGateway(config={"app_id": "a", "secret_id": "s", "secret_key": "k"})
        ws = FakeWebSocket()
        await gw.send_audio_data(ws, bytearray(b"abc"))
        ws.send.assert_awaited_once()
        sent = ws.send.await_args.args[0]
        assert sent == b"abc"

    async def test_send_audio_end_sends_empty(self):
        gw = TencentASRGateway(config={"app_id": "a", "secret_id": "s", "secret_key": "k"})
        ws = FakeWebSocket()
        await gw.send_audio_end(ws)
        ws.send.assert_awaited_with(b"")

    def test_parse_response_dict_with_text(self):
        gw = TencentASRGateway(config={"app_id": "a", "secret_id": "s", "secret_key": "k"})
        result = gw.parse_response({"code": 0, "result": {"voice_text_str": "hello"}, "is_final": True})
        assert result["text"] == "hello"
        assert result["is_final"] is True

    def test_parse_response_string_with_text(self):
        gw = TencentASRGateway(config={"app_id": "a", "secret_id": "s", "secret_key": "k"})
        resp = json.dumps({"code": 0, "result": "raw text", "slice_type": 2})
        result = gw.parse_response(resp)
        assert result["text"] == "raw text"
        assert result["is_final"] is True

    def test_parse_response_nonzero_code_returns_none(self):
        gw = TencentASRGateway(config={"app_id": "a", "secret_id": "s", "secret_key": "k"})
        assert gw.parse_response({"code": 1, "result": "x"}) is None

    def test_parse_response_no_result_returns_none(self):
        gw = TencentASRGateway(config={"app_id": "a", "secret_id": "s", "secret_key": "k"})
        assert gw.parse_response({"code": 0}) is None

    def test_parse_response_invalid_returns_none(self):
        gw = TencentASRGateway(config={"app_id": "a", "secret_id": "s", "secret_key": "k"})
        assert gw.parse_response("not-json") is None

    async def test_pre_connect_success(self):
        gw = TencentASRGateway(config={"app_id": "a", "secret_id": "s", "secret_key": "k"})
        fake_ws = FakeWebSocket()
        with patch("src.interfaces.asr.tencent.websockets.connect",
                   return_value=FakeConnectResult(fake_ws)):
            result = await gw.pre_connect()
        assert result is fake_ws
        assert gw._pre_ws is fake_ws

    async def test_pre_connect_failure(self):
        gw = TencentASRGateway(config={"app_id": "a", "secret_id": "s", "secret_key": "k"})
        with patch("src.interfaces.asr.tencent.websockets.connect", side_effect=OSError("fail")):
            result = await gw.pre_connect()
        assert result is None
        assert gw._pre_ws is None

    async def test_pre_connect_closes_old_ws(self):
        gw = TencentASRGateway(config={"app_id": "a", "secret_id": "s", "secret_key": "k"})
        old_ws = FakeWebSocket()
        gw._pre_ws = old_ws
        new_ws = FakeWebSocket()
        with patch("src.interfaces.asr.tencent.websockets.connect",
                   return_value=FakeConnectResult(new_ws)):
            await gw.pre_connect()
        old_ws.close.assert_awaited_once()

    async def test_disconnect_closes_ws(self):
        gw = TencentASRGateway(config={"app_id": "a", "secret_id": "s", "secret_key": "k"})
        ws = FakeWebSocket()
        gw._pre_ws = ws
        await gw.disconnect()
        ws.close.assert_awaited_once()
        assert gw._pre_ws is None

    async def test_disconnect_no_ws(self):
        gw = TencentASRGateway(config={"app_id": "a", "secret_id": "s", "secret_key": "k"})
        await gw.disconnect()
        assert gw._pre_ws is None

    async def test_recognize_success(self):
        gw = TencentASRGateway(config={"app_id": "a", "secret_id": "s", "secret_key": "k"})
        fake_ws = FakeWebSocket()
        # 返回一个 final 结果
        fake_ws.recv.return_value = json.dumps({
            "code": 0, "result": {"voice_text_str": "你好"}, "is_final": True,
        })
        with patch("src.interfaces.asr.tencent.websockets.connect",
                   return_value=FakeConnectResult(fake_ws)):
            text = await gw.recognize(b"audio")
        assert text == "你好"

    async def test_recognize_error_code_breaks(self):
        gw = TencentASRGateway(config={"app_id": "a", "secret_id": "s", "secret_key": "k"})
        fake_ws = FakeWebSocket()
        fake_ws.recv.return_value = json.dumps({"code": 1, "message": "err"})
        with patch("src.interfaces.asr.tencent.websockets.connect",
                   return_value=FakeConnectResult(fake_ws)):
            text = await gw.recognize(b"audio")
        assert text == ""

    async def test_recognize_exception_returns_empty(self):
        gw = TencentASRGateway(config={"app_id": "a", "secret_id": "s", "secret_key": "k"})
        with patch("src.interfaces.asr.tencent.websockets.connect", side_effect=OSError("fail")):
            text = await gw.recognize(b"audio")
        assert text == ""

    async def test_recognize_streaming_success(self):
        gw = TencentASRGateway(config={"app_id": "a", "secret_id": "s", "secret_key": "k"})
        fake_ws = FakeWebSocket()
        fake_ws.recv.return_value = json.dumps({
            "code": 0, "result": {"voice_text_str": "完成"}, "slice_type": 2,
        })
        with patch("src.interfaces.asr.tencent.websockets.connect",
                   return_value=FakeConnectResult(fake_ws)):
            text = await gw.recognize_streaming([b"a", b"b"])
        assert text == "完成"


# ─── create_asr_gateway 工厂函数测试 ───────────────────────

class TestCreateASRGateway:
    """create_asr_gateway 工厂函数测试"""

    def test_create_tencent(self, patched_asr):
        gw = create_asr_gateway(provider="tencent", config={"app_id": "a"})
        assert isinstance(gw, TencentASRGateway)
        assert gw.app_id == "a"

    def test_create_tencent_uses_settings_defaults(self, patched_asr):
        gw = create_asr_gateway(provider="tencent")
        assert isinstance(gw, TencentASRGateway)
        assert gw.app_id == "t-app"
        assert gw.secret_id == "t-sid"

    def test_create_volcengine(self, patched_asr):
        gw = create_asr_gateway(provider="volcengine", config={"api_key": "k"})
        assert isinstance(gw, VolcEngineASRGateway)
        assert gw.api_key == "k"

    def test_create_bytedance_alias(self, patched_asr):
        gw = create_asr_gateway(provider="bytedance", config={"api_key": "k"})
        assert isinstance(gw, VolcEngineASRGateway)

    def test_create_volcengine_uses_settings_defaults(self, patched_asr):
        gw = create_asr_gateway(provider="volcengine")
        assert isinstance(gw, VolcEngineASRGateway)
        assert gw.api_key == "v-key"

    def test_create_aliyun(self, patched_asr):
        gw = create_asr_gateway(provider="aliyun", config={"app_key": "ak"})
        assert isinstance(gw, AliYunASRGateway)
        assert gw.app_key == "ak"

    def test_create_xunfei(self, patched_asr):
        from src.interfaces.asr.xunfei import XunfeiASRGateway
        gw = create_asr_gateway(provider="xunfei", config={"app_id": "x"})
        assert isinstance(gw, XunfeiASRGateway)
        assert gw.app_id == "x"

    def test_create_uses_settings_provider_when_none(self, patched_asr):
        patched_asr["settings"].asr.provider = "tencent"
        gw = create_asr_gateway()
        assert isinstance(gw, TencentASRGateway)

    def test_create_provider_case_insensitive(self, patched_asr):
        gw = create_asr_gateway(provider="TENCENT")
        assert isinstance(gw, TencentASRGateway)

    def test_create_unsupported_provider_raises(self, patched_asr):
        with pytest.raises(ValueError, match="Unsupported ASR provider"):
            create_asr_gateway(provider="unknown")
