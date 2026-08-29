from __future__ import annotations

import asyncio
import hashlib
import io
import json
import struct
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Optional

import websockets

from src.domain.exceptions import TTSError
from src.domain.repositories import TTSRepository
from src.infrastructure.config import get_settings
from src.infrastructure.connection_pool import ConnectionPoolBase, ConnectionWrapper
from src.infrastructure.logging import get_logger, trace_id_var
from src.infrastructure.monitoring import get_metrics

logger = get_logger("tts_gateway")


class MsgType(IntEnum):
    Invalid = 0
    FullClientRequest = 0b1
    AudioOnlyClient = 0b10
    FullServerResponse = 0b1001
    AudioOnlyServer = 0b1011
    FrontEndResultServer = 0b1100
    Error = 0b1111


class MsgTypeFlagBits(IntEnum):
    NoSeq = 0
    PositiveSeq = 0b1
    LastNoSeq = 0b10
    NegativeSeq = 0b11
    WithEvent = 0b100


class VersionBits(IntEnum):
    Version1 = 1


class HeaderSizeBits(IntEnum):
    HeaderSize4 = 1


class SerializationBits(IntEnum):
    Raw = 0
    JSON = 0b1


class CompressionBits(IntEnum):
    None_ = 0


class EventType(IntEnum):
    None_ = 0
    StartConnection = 1
    FinishConnection = 2
    ConnectionStarted = 50
    ConnectionFailed = 51
    ConnectionFinished = 52
    StartSession = 100
    CancelSession = 101
    FinishSession = 102
    SessionStarted = 150
    SessionCanceled = 151
    SessionFinished = 152
    SessionFailed = 153
    TaskRequest = 200
    AudioMuted = 250
    SayHello = 300
    TTSSentenceStart = 350
    TTSSentenceEnd = 351
    TTSResponse = 352
    TTSSubtitle = 364
    TTSEnded = 359


@dataclass
class TTSSynthEvent:
    """TTS 合成事件：kind="audio" 时 data 为音频字节；kind="subtitle" 时 data 为 {seq, words}"""
    kind: str
    data: Any


@dataclass
class Message:
    version: VersionBits = VersionBits.Version1
    header_size: HeaderSizeBits = HeaderSizeBits.HeaderSize4
    type: MsgType = MsgType.Invalid
    flag: MsgTypeFlagBits = MsgTypeFlagBits.NoSeq
    serialization: SerializationBits = SerializationBits.JSON
    compression: CompressionBits = CompressionBits.None_
    event: EventType = EventType.None_
    session_id: str = ""
    connect_id: str = ""
    sequence: int = 0
    error_code: int = 0
    payload: bytes = b""

    @classmethod
    def from_bytes(cls, data: bytes) -> Message:
        if len(data) < 3:
            raise ValueError(f"Data too short: expected at least 3 bytes, got {len(data)}")
        type_and_flag = data[1]
        msg_type = MsgType(type_and_flag >> 4)
        flag = MsgTypeFlagBits(type_and_flag & 0b00001111)
        msg = cls(type=msg_type, flag=flag)
        msg.unmarshal(data)
        return msg

    def marshal(self) -> bytes:
        buffer = io.BytesIO()
        header = [
            (self.version << 4) | self.header_size,
            (self.type << 4) | self.flag,
            (self.serialization << 4) | self.compression,
        ]
        header_size = 4 * self.header_size
        if padding := header_size - len(header):
            header.extend([0] * padding)
        buffer.write(bytes(header))
        writers = self._get_writers()
        for writer in writers:
            writer(buffer)
        return buffer.getvalue()

    def unmarshal(self, data: bytes) -> None:
        buffer = io.BytesIO(data)
        version_and_header_size = buffer.read(1)[0]
        self.version = VersionBits(version_and_header_size >> 4)
        self.header_size = HeaderSizeBits(version_and_header_size & 0b00001111)
        buffer.read(1)
        serialization_compression = buffer.read(1)[0]
        self.serialization = SerializationBits(serialization_compression >> 4)
        self.compression = CompressionBits(serialization_compression & 0b00001111)
        header_size = 4 * self.header_size
        read_size = 3
        if padding_size := header_size - read_size:
            buffer.read(padding_size)
        readers = self._get_readers()
        for reader in readers:
            reader(buffer)

    def _get_writers(self) -> list[Callable[[io.BytesIO], None]]:
        writers = []
        if self.flag == MsgTypeFlagBits.WithEvent:
            writers.extend([self._write_event, self._write_session_id])
        if self.type in [
            MsgType.FullClientRequest,
            MsgType.FullServerResponse,
            MsgType.FrontEndResultServer,
            MsgType.AudioOnlyClient,
            MsgType.AudioOnlyServer,
        ]:
            if self.flag in [MsgTypeFlagBits.PositiveSeq, MsgTypeFlagBits.NegativeSeq]:
                writers.append(self._write_sequence)
        elif self.type == MsgType.Error:
            writers.append(self._write_error_code)
        writers.append(self._write_payload)
        return writers

    def _get_readers(self) -> list[Callable[[io.BytesIO], None]]:
        readers = []
        if self.type in [
            MsgType.FullClientRequest,
            MsgType.FullServerResponse,
            MsgType.FrontEndResultServer,
            MsgType.AudioOnlyClient,
            MsgType.AudioOnlyServer,
        ]:
            if self.flag in [MsgTypeFlagBits.PositiveSeq, MsgTypeFlagBits.NegativeSeq]:
                readers.append(self._read_sequence)
        elif self.type == MsgType.Error:
            readers.append(self._read_error_code)
        if self.flag == MsgTypeFlagBits.WithEvent:
            readers.extend([self._read_event, self._read_session_id, self._read_connect_id])
        readers.append(self._read_payload)
        return readers

    def _write_event(self, buffer: io.BytesIO) -> None:
        buffer.write(struct.pack(">i", self.event))

    def _write_session_id(self, buffer: io.BytesIO) -> None:
        if self.event in [
            EventType.StartConnection,
            EventType.FinishConnection,
            EventType.ConnectionStarted,
            EventType.ConnectionFailed,
        ]:
            return
        session_id_bytes = self.session_id.encode("utf-8")
        size = len(session_id_bytes)
        buffer.write(struct.pack(">I", size))
        if size > 0:
            buffer.write(session_id_bytes)

    def _write_sequence(self, buffer: io.BytesIO) -> None:
        buffer.write(struct.pack(">i", self.sequence))

    def _write_error_code(self, buffer: io.BytesIO) -> None:
        buffer.write(struct.pack(">I", self.error_code))

    def _write_payload(self, buffer: io.BytesIO) -> None:
        size = len(self.payload)
        buffer.write(struct.pack(">I", size))
        buffer.write(self.payload)

    def _read_event(self, buffer: io.BytesIO) -> None:
        event_bytes = buffer.read(4)
        if event_bytes:
            self.event = EventType(struct.unpack(">i", event_bytes)[0])

    def _read_session_id(self, buffer: io.BytesIO) -> None:
        if self.event in [
            EventType.StartConnection,
            EventType.FinishConnection,
            EventType.ConnectionStarted,
            EventType.ConnectionFailed,
            EventType.ConnectionFinished,
        ]:
            return
        size_bytes = buffer.read(4)
        if size_bytes:
            size = struct.unpack(">I", size_bytes)[0]
            if size > 0:
                session_id_bytes = buffer.read(size)
                if len(session_id_bytes) == size:
                    self.session_id = session_id_bytes.decode("utf-8")

    def _read_connect_id(self, buffer: io.BytesIO) -> None:
        if self.event in [EventType.ConnectionStarted, EventType.ConnectionFailed, EventType.ConnectionFinished]:
            size_bytes = buffer.read(4)
            if size_bytes:
                size = struct.unpack(">I", size_bytes)[0]
                if size > 0:
                    self.connect_id = buffer.read(size).decode("utf-8")

    def _read_sequence(self, buffer: io.BytesIO) -> None:
        sequence_bytes = buffer.read(4)
        if sequence_bytes:
            self.sequence = struct.unpack(">i", sequence_bytes)[0]

    def _read_error_code(self, buffer: io.BytesIO) -> None:
        error_code_bytes = buffer.read(4)
        if error_code_bytes:
            self.error_code = struct.unpack(">I", error_code_bytes)[0]

    def _read_payload(self, buffer: io.BytesIO) -> None:
        size_bytes = buffer.read(4)
        if size_bytes:
            size = struct.unpack(">I", size_bytes)[0]
            if size > 0:
                self.payload = buffer.read(size)


async def receive_message(websocket) -> Message:
    data = await websocket.recv()
    if isinstance(data, str):
        raise ValueError(f"Unexpected text message: {data}")
    elif isinstance(data, bytes):
        return Message.from_bytes(data)
    else:
        raise ValueError(f"Unexpected message type: {type(data)}")


async def full_client_request(websocket, payload: bytes) -> None:
    msg = Message(type=MsgType.FullClientRequest, flag=MsgTypeFlagBits.NoSeq)
    msg.payload = payload
    await websocket.send(msg.marshal())


async def finish_connection(websocket) -> None:
    msg = Message(type=MsgType.FullClientRequest, flag=MsgTypeFlagBits.WithEvent)
    msg.event = EventType.FinishConnection
    msg.payload = b"{}"
    await websocket.send(msg.marshal())


def get_resource_id(voice: str) -> str:
    """根据音色名推导 V3 单向流式接口对应的 X-Api-Resource-Id。

    服务端连接的是 V3 端点 ``wss://openspeech.bytedance.com/api/v3/tts/unidirectional/stream``，
    该端点合法的资源 ID 为 ``seed-tts-2.0`` / ``seed-tts-1.0``(豆包语音合成大模型)、
    ``seed-icl-2.0`` / ``seed-icl-1.0``(豆包声音复刻大模型)。
    旧 v1 接口的资源 ID(如 ``volc.megatts.default`` / ``volc.service_type.10029``)
    在 V3 端点上会鉴权失败(握手 HTTP 401)。

    声音复刻音色前缀:``S_``(复刻 speakerid)、``icl_``(复刻查询接口返回)、
    ``saturn_``(声音复刻 2.0)、``DiT_``(DIT 复刻)，均使用 ``seed-icl-2.0``，
    复刻 1.0 音色需显式配置 ``seed-icl-1.0``；
    大模型音色默认对应模型 2.0，使用 ``seed-tts-2.0``，
    模型 1.0 音色(如 ``zh_female_wanwanxiaohe_moon_bigtts``)需显式配置 ``seed-tts-1.0``。
    """
    _voice = voice.lower()
    if _voice.startswith(("s_", "icl_", "saturn_", "dit_")):
        return "seed-icl-2.0"
    return "seed-tts-2.0"


class VolcEngineTTSConnectionPool(ConnectionPoolBase):

    def __init__(
        self,
        api_key: str,
        resource_id: str = "seed-tts-2.0",
        voice_type: str = "BV001_streaming",
        speed_ratio: float = 1.0,
        volume_ratio: float = 1.0,
        pitch_ratio: float = 1.0,
        **kwargs,
    ):
        super().__init__(pool_name="volcengine_tts", **kwargs)
        self._api_key = api_key
        self._resource_id = resource_id
        self._voice_type = voice_type
        self._speed_ratio = speed_ratio
        self._volume_ratio = volume_ratio
        self._pitch_ratio = pitch_ratio
        self._ping_interval = 30

    async def _create_connection(self) -> Any:
        headers = {
            "X-Api-Key": self._api_key,
            "X-Api-Resource-Id": self._resource_id,
            "X-Api-Connect-Id": str(uuid.uuid4()),
        }
        # 向下游 TTS 服务传播 trace_id
        try:
            _tid = trace_id_var.get()
            if _tid:
                headers["X-Trace-Id"] = _tid
        except Exception:
            pass
        url = "wss://openspeech.bytedance.com/api/v3/tts/unidirectional/stream"
        conn = await asyncio.wait_for(
            websockets.connect(
                url,
                additional_headers=headers,
                max_size=20 * 1024 * 1024,
                ping_interval=self._ping_interval,
                ping_timeout=15,
                open_timeout=self._connection_timeout,
            ),
            timeout=self._connection_timeout,
        )
        return conn

    async def _heartbeat(self, conn: Any) -> None:
        while True:
            if self._closed:
                break
            await asyncio.sleep(self._heartbeat_interval)
            if self._is_ws_closed(conn):
                break
            try:
                await asyncio.wait_for(conn.ping(), timeout=5)
            except Exception:
                break

    def _is_ws_closed(self, conn: Any) -> bool:
        try:
            close_code = getattr(conn, "close_code", None)
            if close_code is not None:
                return True
            return False
        except Exception:
            return True

    async def _is_healthy(self, conn: Any) -> bool:
        if self._is_ws_closed(conn):
            return False
        try:
            return getattr(conn, "open", False)
        except Exception:
            return False

    async def _close_connection(self, conn: Any) -> None:
        try:
            if not self._is_ws_closed(conn):
                await conn.close()
        except Exception as e:
            logger.debug(f"[TTS Pool] 关闭连接异常: {e}")


class TTSSession:

    def __init__(self, gateway: VolcEngineTTSGateway, websocket, session_id: str, pool_wrapper=None):
        self._gateway = gateway
        self._websocket = websocket
        self._session_id = session_id
        self._pool_wrapper = pool_wrapper
        self._seq = 0
        self._closed = False
        self._released = False
        self._close_on_release = False
        self._created_at = time.time()

    @property
    def websocket(self):
        return self._websocket

    @property
    def session_id(self):
        return self._session_id

    def _is_expired(self, max_idle: float = 30.0) -> bool:
        return time.time() - self._created_at > max_idle

    async def _reconnect(self):
        old_ws = self._websocket
        try:
            await old_ws.close()
        except Exception as e:
            logger.debug(f"[TTS] 关闭旧 websocket 异常: {e}")
        with suppress(ValueError):
            self._gateway._active_websockets.remove(old_ws)
        if self._pool_wrapper:
            pool = self._gateway.get_pool(self._gateway._get_pool_config())
            if pool:
                try:
                    await pool.release(self._pool_wrapper)
                except Exception as e:
                    logger.debug(f"[TTS] 重连归还旧连接异常: {e}")
                try:
                    self._pool_wrapper = await pool.acquire(timeout=10.0)
                    self._websocket = self._pool_wrapper.connection
                    self._gateway._active_websockets.append(self._websocket)
                    self._created_at = time.time()
                    self._seq = 0
                    logger.info("[TTS] Session WS 已从连接池重连")
                    return
                except Exception as e:
                    logger.error(f"[TTS] 重连从池取连接失败: {e}")
            self._pool_wrapper = None
        self._websocket = await self._gateway._create_connection()
        self._gateway._active_websockets.append(self._websocket)
        self._created_at = time.time()
        self._seq = 0
        logger.info("[TTS] Session WS 已重连")

    async def synthesize(self, text: str, cancel_event=None) -> AsyncIterator[TTSSynthEvent]:
        if self._closed:
            return

        if len(text) > 500:
            logger.warning(f"[TTS] 文本长度过长: {len(text)}字符")

        self._seq += 1
        seq = self._seq

        request = {
            "user": {"uid": str(uuid.uuid4())},
            "req_params": {
                "speaker": self._gateway.voice_type,
                "audio_params": {
                    "format": "mp3",
                    "sample_rate": self._gateway.sample_rate,
                    "speed_ratio": self._gateway.speed_ratio,
                    "volume_ratio": self._gateway.volume_ratio,
                    "pitch_ratio": self._gateway.pitch_ratio,
                },
                "text": text,
            },
        }
        if self._gateway.enable_subtitle:
            request["req_params"]["audio_params"]["enable_subtitle"] = True
        if self._gateway.explicit_dialect:
            request["req_params"]["explicit_dialect"] = self._gateway.explicit_dialect

        try:
            await full_client_request(self._websocket, json.dumps(request).encode())
        except Exception as e:
            if isinstance(e, websockets.exceptions.ConnectionClosed):
                logger.error(f"[TTS] WS 已断开 #{seq}，尝试重连: {e}")
                try:
                    await self._reconnect()
                    await full_client_request(self._websocket, json.dumps(request).encode())
                except Exception as e2:
                    logger.error(f"[TTS] 重连后发送仍失败 #{seq}: {e2}")
                    self._closed = True
                    self._close_on_release = True
                    return
            else:
                logger.error(f"[TTS] 发送请求失败 #{seq}: {e}")
                self._closed = True
                self._close_on_release = True
                return

        try:
            while True:
                if cancel_event and cancel_event.is_set():
                    logger.info(f"[TTS] 合成 #{seq} 被取消信号中断")
                    self._close_on_release = True
                    return
                try:
                    msg = await asyncio.wait_for(receive_message(self._websocket), timeout=self._gateway._message_timeout)
                except asyncio.TimeoutError:
                    logger.error(f"[TTS] 接收消息超时 #{seq}")
                    self._close_on_release = True
                    return

                if msg.type == MsgType.AudioOnlyServer:
                    if msg.payload:
                        yield TTSSynthEvent("audio", msg.payload)
                elif msg.type == MsgType.FullServerResponse:
                    if msg.event == EventType.TTSSubtitle:
                        yield self._parse_subtitle_event(seq, msg)
                    elif msg.event == EventType.SessionFinished:
                        logger.debug(f"[TTS] 句子 #{seq} 合成完成")
                        return
                    elif msg.event == EventType.SessionFailed:
                        payload_str = msg.payload.decode("utf-8", "ignore") if msg.payload else "Unknown"
                        logger.error(f"[TTS] 合成失败 #{seq}: {payload_str}")
                        self._close_on_release = True
                        return
                elif msg.type == MsgType.Error:
                    payload_str = msg.payload.decode("utf-8", "ignore") if msg.payload else "Unknown"
                    logger.error(f"[TTS] 合成错误 #{seq}: {payload_str}")
                    self._close_on_release = True
                    return

        except (websockets.exceptions.ConnectionClosed, OSError, ConnectionError) as e:
            logger.error(f"[TTS] WS 连接异常 #{seq}: {e}")
            self._closed = True
            self._close_on_release = True
        except asyncio.CancelledError:
            self._close_on_release = True
            raise

    async def synthesize_audio(self, text: str, cancel_event=None) -> AsyncIterator[bytes]:
        """合成并仅产出音频字节（忽略字幕事件），供不关心字级时间戳的调用方使用。"""
        async for event in self.synthesize(text, cancel_event=cancel_event):
            if event.kind == "audio" and event.data:
                yield event.data

    def _parse_subtitle_event(self, seq: int, msg: Message) -> TTSSynthEvent:
        """解析 TTSSubtitle 事件（EventType=364），提取字级时间戳。

        words 时间戳单位为秒，且是整句累计的绝对时间（实测每个子句批次
        的首字 startTime 都大于上一批次末字 endTime，为子句间自然停顿），
        因此直接换算为毫秒即可，无需累加子句偏移。
        """
        try:
            payload = json.loads(msg.payload.decode("utf-8", "ignore"))
            words = payload.get("words") or []
            if not words:
                return TTSSynthEvent("subtitle", {"seq": seq, "words": []})
            word_list = []
            for w in words:
                try:
                    start_ms = int(float(w.get("startTime", 0)) * 1000)
                    end_ms = int(float(w.get("endTime", 0)) * 1000)
                except (TypeError, ValueError):
                    continue
                word_list.append({
                    "word": w.get("word", ""),
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                })
            return TTSSynthEvent("subtitle", {"seq": seq, "words": word_list})
        except Exception as e:
            logger.warning(f"[TTS] 解析字幕事件异常 #{seq}: {e}")
            return TTSSynthEvent("subtitle", {"seq": seq, "words": []})

    async def close(self):
        if self._released:
            return
        self._released = True
        self._closed = True
        if self._pool_wrapper:
            # 连接池模式：不发送 FinishConnection、不关闭 WS，直接归还池供跨轮复用
            pool = self._gateway.get_pool(self._gateway._get_pool_config())
            if pool:
                if self._close_on_release:
                    # 合成异常/中断：连接状态不确定，先关闭再归还（池会检测不健康并清理）
                    try:
                        await self._websocket.close()
                    except Exception as e:
                        logger.debug(f"[TTS] 关闭异常 WS 异常: {e}")
                try:
                    await pool.release(self._pool_wrapper)
                except Exception as e:
                    logger.debug(f"[TTS] 归还连接池异常: {e}")
            self._pool_wrapper = None
            with suppress(ValueError):
                self._gateway._active_websockets.remove(self._websocket)
            logger.info(f"[TTS] Session {self._session_id} 已归还连接池")
            return
        try:
            await finish_connection(self._websocket)
        except Exception as e:
            logger.debug(f"[TTS] finish_connection 异常: {e}")
        try:
            await self._websocket.close()
        except Exception as e:
            logger.debug(f"[TTS] 关闭 websocket 异常: {e}")
        with suppress(ValueError):
            self._gateway._active_websockets.remove(self._websocket)
        logger.info(f"[TTS] Session {self._session_id} 已关闭")


class VolcEngineTTSGateway(TTSRepository):

    # 按配置键隔离的连接池字典（避免跨设备串用其他设备的 api_key 连接池）
    _pools: dict[str, VolcEngineTTSConnectionPool] = {}
    # 已触发过 warm_up 的池键集合
    _pool_warmed: set[str] = set()

    def __init__(self, config: dict | None = None):
        settings = get_settings()
        tts_config = settings.tts
        effective = config or {}

        self.api_key = effective.get("api_key", tts_config.api_key)
        self.resource_id = effective.get("resource_id", tts_config.resource_id) or get_resource_id(
            effective.get("voice_type", tts_config.voice_type or "BV001_streaming")
        )
        self.voice_type = effective.get("voice_type", tts_config.voice_type or "BV001_streaming")
        # 采样率优先取设备上报的 spk_sample_rate（经 effective["sample_rate"] 传入），
        # 否则用全局配置，默认 24000。火山大模型 TTS 合法值：8000/16000/22050/24000/32000/44100/48000
        try:
            self.sample_rate = int(effective.get("sample_rate") or tts_config.sample_rate or 24000)
        except (ValueError, TypeError):
            self.sample_rate = 24000
        if self.sample_rate not in (8000, 16000, 22050, 24000, 32000, 44100, 48000):
            logger.warning(f"[TTS] 非法采样率 {self.sample_rate}，回退到 24000")
            self.sample_rate = 24000
        self.speed_ratio = effective.get("speed_ratio", tts_config.speed_ratio)
        self.volume_ratio = effective.get("volume_ratio", tts_config.volume_ratio)
        self.pitch_ratio = effective.get("pitch_ratio", tts_config.pitch_ratio)
        self.explicit_dialect = effective.get("explicit_dialect", tts_config.explicit_dialect) or ""
        self.enable_subtitle = effective.get("enable_subtitle", tts_config.enable_subtitle)
        self._max_retries = 3
        self._ping_interval = 30
        self._connection_timeout = 15
        self._message_timeout = 20
        self._active_websockets: list = []
        self._enable_pool = effective.get("enable_pool", tts_config.enable_pool) and bool(self.api_key)
        # 设备级连接池参数（回退全局）
        self._pool_max_size = effective.get("pool_max_size") or tts_config.pool_max_size
        self._pool_min_size = effective.get("pool_min_size") or tts_config.pool_min_size
        self._pool_heartbeat_interval = effective.get("pool_heartbeat_interval") or tts_config.pool_heartbeat_interval
        self._pool_idle_timeout = effective.get("pool_idle_timeout") or tts_config.pool_idle_timeout
        self._pool_connection_timeout = effective.get("pool_connection_timeout") or tts_config.pool_connection_timeout

    async def aclose(self) -> None:
        """释放本网关实例持有的 WS 连接（服务关闭/设备会话关闭时调用）。

        注意：连接池连接由 close_pool() 统一管理，此处只处理本实例
        直接持有的活跃 websocket（非池会话）。
        """
        for ws in list(self._active_websockets):
            try:
                await ws.close()
            except Exception as e:
                logger.debug(f"[TTS] aclose 关闭 WS 异常: {e}")
        self._active_websockets.clear()

    @classmethod
    def get_pool(cls, config: dict | None = None) -> VolcEngineTTSConnectionPool | None:
        settings = get_settings()
        tts_config = settings.tts

        if config is None:
            config = {
                "api_key": tts_config.api_key,
                "resource_id": tts_config.resource_id,
                "voice_type": tts_config.voice_type,
                "speed_ratio": tts_config.speed_ratio,
                "volume_ratio": tts_config.volume_ratio,
                "pitch_ratio": tts_config.pitch_ratio,
                "enable_pool": tts_config.enable_pool,
                "pool_max_size": tts_config.pool_max_size,
                "pool_min_size": tts_config.pool_min_size,
                "pool_heartbeat_interval": tts_config.pool_heartbeat_interval,
                "pool_idle_timeout": tts_config.pool_idle_timeout,
                "pool_connection_timeout": tts_config.pool_connection_timeout,
            }
        # enable_pool 优先从 config（设备级）读取，回退全局
        enable_pool = config.get("enable_pool", tts_config.enable_pool)
        if not enable_pool:
            return None
        if not config.get("api_key"):
            return None

        # 按当前配置生成稳定的池键：api_key 做短 hash 避免内存中明文暴露
        # 不同设备（api_key/resource_id/voice_type 不同）各自持有独立连接池
        config_key = (
            f"{config.get('api_key', '')}:"
            f"{config.get('resource_id', 'seed-tts-2.0')}:"
            f"{config.get('voice_type', 'BV001_streaming')}"
        )
        pool_key = hashlib.md5(config_key.encode()).hexdigest()

        pool = cls._pools.get(pool_key)
        if pool is None or pool.is_closed:
            # 连接池尺寸参数优先从 config（设备级）读取，回退全局
            pool_config = {
                "max_size": config.get("pool_max_size") or tts_config.pool_max_size,
                "min_size": config.get("pool_min_size") or tts_config.pool_min_size,
                "heartbeat_interval": config.get("pool_heartbeat_interval") or tts_config.pool_heartbeat_interval,
                "idle_timeout": config.get("pool_idle_timeout") or tts_config.pool_idle_timeout,
                "connection_timeout": config.get("pool_connection_timeout") or tts_config.pool_connection_timeout,
            }
            pool = VolcEngineTTSConnectionPool(
                api_key=config.get("api_key", ""),
                resource_id=config.get("resource_id", "seed-tts-2.0"),
                voice_type=config.get("voice_type", "BV001_streaming"),
                speed_ratio=config.get("speed_ratio", 1.0),
                volume_ratio=config.get("volume_ratio", 1.0),
                pitch_ratio=config.get("pitch_ratio", 1.0),
                **pool_config,
            )
            cls._pools[pool_key] = pool
            cls._pool_warmed.discard(pool_key)

        if pool_key not in cls._pool_warmed:
            asyncio.create_task(pool.warm_up())
            cls._pool_warmed.add(pool_key)

        return pool

    @classmethod
    async def close_pool(cls) -> None:
        for pool in list(cls._pools.values()):
            if not pool.is_closed:
                await pool.close()
        cls._pools.clear()
        cls._pool_warmed.clear()

    async def _create_connection(self):
        headers = {
            "X-Api-Key": self.api_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Connect-Id": str(uuid.uuid4()),
        }
        # 向下游 TTS 服务传播 trace_id
        try:
            _tid = trace_id_var.get()
            if _tid:
                headers["X-Trace-Id"] = _tid
        except Exception:
            pass
        url = "wss://openspeech.bytedance.com/api/v3/tts/unidirectional/stream"

        websocket = await asyncio.wait_for(
            websockets.connect(
                url,
                additional_headers=headers,
                max_size=20 * 1024 * 1024,
                ping_interval=self._ping_interval,
                ping_timeout=15,
                open_timeout=self._connection_timeout,
            ),
            timeout=self._connection_timeout,
        )
        return websocket

    def _get_pool_config(self) -> dict:
        return {
            "api_key": self.api_key,
            "resource_id": self.resource_id,
            "voice_type": self.voice_type,
            "speed_ratio": self.speed_ratio,
            "volume_ratio": self.volume_ratio,
            "pitch_ratio": self.pitch_ratio,
            "enable_pool": self._enable_pool,
            "pool_max_size": self._pool_max_size,
            "pool_min_size": self._pool_min_size,
            "pool_heartbeat_interval": self._pool_heartbeat_interval,
            "pool_idle_timeout": self._pool_idle_timeout,
            "pool_connection_timeout": self._pool_connection_timeout,
        }

    async def create_session(self, cancel_event=None, tool_manager=None) -> TTSSession:
        # 连接池模式：从池中取 WS，实现跨轮次复用
        if self._enable_pool:
            pool = self.get_pool(self._get_pool_config())
            if pool is not None:
                try:
                    wrapped = await pool.acquire(timeout=10.0)
                    if cancel_event and cancel_event.is_set():
                        await pool.release(wrapped)
                        raise asyncio.CancelledError("Session creation cancelled")
                    websocket = wrapped.connection
                    self._active_websockets.append(websocket)
                    session_id = str(uuid.uuid4())
                    logger.info(f"[TTS] Session 已建立 (连接池复用): {session_id}")
                    return TTSSession(self, websocket, session_id, pool_wrapper=wrapped)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"[TTS] 从连接池获取 WS 失败，回退普通建连: {e}")
            else:
                logger.warning("[TTS] 连接池不可用，回退普通模式")

        last_error = None

        for attempt in range(self._max_retries):
            websocket = None
            session_id = str(uuid.uuid4())
            try:
                websocket = await self._create_connection()
                self._active_websockets.append(websocket)

                if cancel_event and cancel_event.is_set():
                    await websocket.close()
                    raise asyncio.CancelledError("Session creation cancelled")

                logger.info(f"[TTS] Session 已建立 (WS 复用): {session_id}")
                return TTSSession(self, websocket, session_id)

            except (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError, OSError, ConnectionError) as e:
                last_error = e
                if attempt < self._max_retries - 1:
                    logger.warning(f"[TTS] 连接异常，正在重试 ({attempt + 1}/{self._max_retries}): {e}")
                    await asyncio.sleep(1.0)
                    continue
                logger.error(f"[TTS] 重试 {self._max_retries} 次后仍失败: {e}")
            except Exception as e:
                logger.error(f"[TTS] 创建 session 异常: {e}")
                raise
            finally:
                if websocket and attempt >= self._max_retries - 1:
                    try:
                        await websocket.close()
                    except Exception as e:
                        logger.debug(f"[TTS] 重试关闭 ws 异常: {e}")
                    with suppress(ValueError):
                        self._active_websockets.remove(websocket)

        if last_error:
            raise last_error
        raise RuntimeError("Failed to create TTS session")

    async def synthesize(self, text: str, **kwargs) -> AsyncIterator[bytes]:
        # 业务指标：TTS 请求计时起点
        _tts_track_start = time.time()
        _tts_track_status = "success"
        try:
            async for chunk in self.synthesize_stream(text, cancel_event=kwargs.get("cancel_event")):
                yield chunk
        except Exception:
            _tts_track_status = "error"
            raise
        finally:
            # 业务指标：TTS 请求结果与耗时
            try:
                get_metrics().track_tts_request("volcengine", _tts_track_status, time.time() - _tts_track_start)
            except Exception:
                pass

    async def close_session(self, session: Any) -> None:
        if session:
            await session.close()

    async def synthesize_stream(self, text: str, cancel_event=None) -> AsyncIterator[bytes]:
        if len(text) > 500:
            logger.warning(f"[TTS] 文本长度过长: {len(text)}字符，可能会导致合成失败")

        websocket = None
        last_error = None

        for attempt in range(self._max_retries):
            try:
                websocket = await self._create_connection()
                self._active_websockets.append(websocket)

                request = {
                    "user": {"uid": str(uuid.uuid4())},
                    "req_params": {
                        "speaker": self.voice_type,
                        "audio_params": {
                            "format": "mp3",
                            "sample_rate": self.sample_rate,
                            "speed_ratio": self.speed_ratio,
                            "volume_ratio": self.volume_ratio,
                            "pitch_ratio": self.pitch_ratio,
                        },
                        "text": text,
                    },
                }
                if self.enable_subtitle:
                    request["req_params"]["audio_params"]["enable_subtitle"] = True
                if self.explicit_dialect:
                    request["req_params"]["explicit_dialect"] = self.explicit_dialect

                await full_client_request(websocket, json.dumps(request).encode())
                if attempt > 0:
                    logger.info("[TTS] 重试发送文本合成请求成功")

                while True:
                    if cancel_event and cancel_event.is_set():
                        logger.info("[TTS] 合成被取消信号中断")
                        return
                    try:
                        msg = await asyncio.wait_for(receive_message(websocket), timeout=self._message_timeout)
                    except asyncio.TimeoutError:
                        logger.error("[TTS] 接收消息超时，重新建立连接")
                        raise

                    if msg.type == MsgType.FullServerResponse:
                        if msg.event == EventType.SessionFinished:
                            logger.info("[TTS] 语音合成完成")
                            return
                        elif msg.event == EventType.SessionFailed:
                            payload_str = msg.payload.decode("utf-8", "ignore") if msg.payload else "Unknown"
                            logger.error(f"[TTS] 合成会话失败: {payload_str}")
                            return
                    elif msg.type == MsgType.AudioOnlyServer:
                        if msg.payload:
                            yield msg.payload
                    elif msg.type == MsgType.Error:
                        payload_str = msg.payload.decode("utf-8", "ignore") if msg.payload else "Unknown"
                        logger.error(f"[TTS] 合成错误: {payload_str}")
                        return

            except (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError, OSError, ConnectionError) as e:
                last_error = e
                if attempt < self._max_retries - 1:
                    logger.warning(f"[TTS] 连接异常，正在重试 ({attempt + 1}/{self._max_retries}): {e}")
                    if websocket:
                        try:
                            await websocket.close()
                        except Exception as e:
                            logger.debug(f"[TTS] 合成重试关闭 ws 异常: {e}")
                    await asyncio.sleep(1.0)
                    continue
                logger.error(f"[TTS] 重试 {self._max_retries} 次后仍失败: {e}")
                raise

            except Exception as e:
                logger.error(f"[TTS] 合成异常: {e}")
                raise

            finally:
                if websocket:
                    try:
                        await finish_connection(websocket)
                        await websocket.close()
                    except Exception as e:
                        logger.debug(f"[TTS] 最终重试清理 ws 异常: {e}")
                    with suppress(ValueError):
                        self._active_websockets.remove(websocket)

        if last_error:
            raise last_error

    async def synthesize_stream_with_pool(self, text: str, cancel_event=None) -> AsyncIterator[bytes]:
        if not self._enable_pool:
            async for chunk in self.synthesize_stream(text, cancel_event):
                yield chunk
            return

        pool = self.get_pool(self._get_pool_config())
        if pool is None:
            logger.warning("[TTS] 连接池不可用，回退到普通模式")
            async for chunk in self.synthesize_stream(text, cancel_event):
                yield chunk
            return

        if len(text) > 500:
            logger.warning(f"[TTS] 文本长度过长: {len(text)}字符，可能会导致合成失败")

        wrapped = None

        try:
            wrapped = await pool.acquire(timeout=10.0)
            websocket = wrapped.connection

            request = {
                "user": {"uid": str(uuid.uuid4())},
                "req_params": {
                    "speaker": self.voice_type,
                    "audio_params": {
                        "format": "mp3",
                        "sample_rate": self.sample_rate,
                        "speed_ratio": self.speed_ratio,
                        "volume_ratio": self.volume_ratio,
                        "pitch_ratio": self.pitch_ratio,
                    },
                    "text": text,
                },
            }
            if self.enable_subtitle:
                request["req_params"]["audio_params"]["enable_subtitle"] = True
            if self.explicit_dialect:
                request["req_params"]["explicit_dialect"] = self.explicit_dialect

            await full_client_request(websocket, json.dumps(request).encode())

            while True:
                if cancel_event and cancel_event.is_set():
                    logger.info("[TTS] 合成被取消信号中断")
                    return

                try:
                    msg = await asyncio.wait_for(receive_message(websocket), timeout=self._message_timeout)
                except asyncio.TimeoutError:
                    logger.error("[TTS] 接收消息超时")
                    return

                if msg.type == MsgType.FullServerResponse:
                    if msg.event == EventType.SessionFinished:
                        logger.info("[TTS] 语音合成完成")
                        return
                    elif msg.event == EventType.SessionFailed:
                        payload_str = msg.payload.decode("utf-8", "ignore") if msg.payload else "Unknown"
                        logger.error(f"[TTS] 合成会话失败: {payload_str}")
                        return
                elif msg.type == MsgType.AudioOnlyServer:
                    if msg.payload:
                        yield msg.payload
                elif msg.type == MsgType.Error:
                    payload_str = msg.payload.decode("utf-8", "ignore") if msg.payload else "Unknown"
                    logger.error(f"[TTS] 合成错误: {payload_str}")
                    return

        except (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError, OSError, ConnectionError) as e:
            logger.error(f"[TTS] 连接池合成异常: {e}")
            if wrapped:
                await pool.release(wrapped)
                wrapped = None
            async for chunk in self.synthesize_stream(text, cancel_event):
                yield chunk

        except Exception as e:
            logger.error(f"[TTS] 连接池合成异常: {e}")

        finally:
            if wrapped:
                await pool.release(wrapped)

    async def close(self):
        ws_list = list(self._active_websockets)
        self._active_websockets.clear()
        for ws in ws_list:
            try:
                await ws.close()
            except Exception as e:
                logger.debug(f"[TTS] 批量关闭 ws 异常: {e}")
        if ws_list:
            logger.info(f"[TTS] 已关闭 {len(ws_list)} 个活跃连接")


class VoiceGenerator:

    def make_tts_frame(self, session_id: str, audio_data: bytes, status: str = "00") -> bytes:
        sid = session_id.encode("utf-8")
        ss = status.encode("utf-8")
        return sid + ss + audio_data

    def make_end_frame(self, session_id: str, status: str = "03") -> bytes:
        """构造 TTS 结束帧。

        与 esp-ai-idf-client 的 SID_TTS_END_RESTART/SID_TTS_END 语义对齐：
        - status="02"：继续对话（设备 drain 后无缝进入下一轮聆听，不恢复唤醒监听）
        - status="03"：会话结束（设备 drain 后恢复语音唤醒，回到待机）
        """
        sid = session_id.encode("utf-8")
        return sid + status.encode("utf-8")


def create_tts_gateway(config: dict | None = None) -> VolcEngineTTSGateway:
    settings = get_settings()
    provider = (config or {}).get("provider", settings.tts.provider)

    if provider == "volcengine":
        return VolcEngineTTSGateway(config=config)

    return VolcEngineTTSGateway(config=config)
