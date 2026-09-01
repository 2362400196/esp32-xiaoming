from __future__ import annotations

import asyncio
import hashlib
import json
import struct
import time
import uuid
from typing import Any, Callable, Optional

import websockets

from src.infrastructure.config import get_settings
from src.infrastructure.connection_pool import ConnectionPoolBase
from src.interfaces.asr.base import BaseASRGateway, logger


class VolcEngineASRConnectionPool(ConnectionPoolBase):

    def __init__(
        self,
        api_key: str,
        resource_id: str = "volc.bigasr.sauc.duration",
        model_name: str = "bigmodel",
        audio_format: str = "pcm",
        sample_rate: int = 16000,
        **kwargs,
    ):
        super().__init__(pool_name=f"volcengine_asr_{resource_id}", **kwargs)
        self._api_key = api_key
        self._resource_id = resource_id
        self._model_name = model_name
        self._audio_format = audio_format
        self._sample_rate = sample_rate
        self._ws_url = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"

    def _make_header(self, message_type: int, flags: int = 0) -> bytes:
        version = 0x1 << 4
        header_size = 0x1 << 0
        byte0 = (version | header_size).to_bytes(1, 'big')
        byte1 = ((message_type << 4) | flags).to_bytes(1, 'big')
        serialization = 0x1 << 4
        compression = 0x0 << 0
        byte2 = (serialization | compression).to_bytes(1, 'big')
        byte3 = (0).to_bytes(1, 'big')
        return byte0 + byte1 + byte2 + byte3

    def _make_payload(self, data: dict) -> bytes:
        json_str = json.dumps(data)
        json_bytes = json_str.encode('utf-8')
        return struct.pack('>I', len(json_bytes)) + json_bytes

    async def _create_connection(self) -> Any:
        headers = {
            "X-Api-Key": self._api_key,
            "X-Api-Resource-Id": self._resource_id,
            "X-Api-Connect-Id": str(uuid.uuid4()),
        }

        conn = await websockets.connect(
            self._ws_url,
            additional_headers=headers,
            max_size=20 * 1024 * 1024,
            ping_interval=None,
        )

        return conn

    async def _heartbeat(self, conn: Any) -> None:
        while True:
            if self._closed:
                break

            await asyncio.sleep(self._heartbeat_interval)

            try:
                close_code = getattr(conn, 'close_code', None)
                if close_code is not None:
                    break
            except Exception:
                break

            try:
                await asyncio.wait_for(conn.ping(), timeout=5)
            except Exception:
                break

    async def _is_healthy(self, conn: Any) -> bool:
        try:
            close_code = getattr(conn, 'close_code', None)
            if close_code is not None:
                return False
            return getattr(conn, 'open', True)
        except Exception:
            return False

    async def _close_connection(self, conn: Any) -> None:
        try:
            close_code = getattr(conn, 'close_code', None)
            if close_code is None:
                await conn.close()
        except Exception as e:
            logger.debug(f"[Gateways] 关闭连接异常: {e}")


class VolcEngineASRGateway(BaseASRGateway):

    # 按配置键隔离的连接池字典（避免跨设备串用其他设备的 api_key 连接池）
    _pools: dict[str, VolcEngineASRConnectionPool] = {}
    # 已触发过 warm_up 的池键集合
    _pool_warmed: set[str] = set()
    binary_protocol: bool = True

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.api_key = config.get("api_key", "")
        self.resource_id = config.get("resource_id", "volc.bigasr.sauc.duration")
        self.model_name = config.get("model_name", "bigmodel")
        self._ws_url = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
        settings = get_settings()
        self._enable_pool = config.get("enable_pool", settings.asr.enable_pool) and bool(self.api_key)
        # 设备级连接池参数（回退全局）
        self._pool_max_size = config.get("pool_max_size") or settings.asr.pool_max_size
        self._pool_min_size = config.get("pool_min_size") or settings.asr.pool_min_size
        self._pool_heartbeat_interval = config.get("pool_heartbeat_interval") or settings.asr.pool_heartbeat_interval
        self._pool_idle_timeout = config.get("pool_idle_timeout") or settings.asr.pool_idle_timeout
        self._pool_connection_timeout = config.get("pool_connection_timeout") or settings.asr.pool_connection_timeout

    @classmethod
    def get_pool(cls, config: dict = None) -> VolcEngineASRConnectionPool | None:
        settings = get_settings()
        if config is None:
            config = {}
        # enable_pool 优先从 config（设备级）读取，回退全局
        enable_pool = config.get("enable_pool", settings.asr.enable_pool)
        if not enable_pool:
            return None
        if not config.get("api_key"):
            return None

        # 按当前配置生成稳定的池键：api_key 做短 hash 避免内存中明文暴露
        # 不同设备（api_key/resource_id/model_name 不同）各自持有独立连接池
        config_key = (
            f"{config.get('api_key', '')}:"
            f"{config.get('resource_id', 'volc.bigasr.sauc.duration')}:"
            f"{config.get('model_name', 'bigmodel')}"
        )
        pool_key = hashlib.md5(config_key.encode()).hexdigest()

        pool = cls._pools.get(pool_key)
        if pool is None or pool.is_closed:
            # 连接池尺寸参数优先从 config（设备级）读取，回退全局
            pool_config = {
                "max_size": config.get("pool_max_size") or settings.asr.pool_max_size,
                "min_size": config.get("pool_min_size") or settings.asr.pool_min_size,
                "heartbeat_interval": config.get("pool_heartbeat_interval") or settings.asr.pool_heartbeat_interval,
                "idle_timeout": config.get("pool_idle_timeout") or settings.asr.pool_idle_timeout,
                "connection_timeout": config.get("pool_connection_timeout") or settings.asr.pool_connection_timeout,
            }
            pool_config.update({
                "api_key": config.get("api_key", ""),
                "resource_id": config.get("resource_id", "volc.bigasr.sauc.duration"),
                "model_name": config.get("model_name", "bigmodel"),
            })
            pool = VolcEngineASRConnectionPool(**pool_config)
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

    def _make_header(self, message_type: int, flags: int = 0) -> bytes:
        version = 0x1 << 4
        header_size = 0x1 << 0
        byte0 = (version | header_size).to_bytes(1, 'big')
        byte1 = ((message_type << 4) | flags).to_bytes(1, 'big')
        serialization = 0x1 << 4
        compression = 0x0 << 0
        byte2 = (serialization | compression).to_bytes(1, 'big')
        byte3 = (0).to_bytes(1, 'big')
        return byte0 + byte1 + byte2 + byte3

    def _make_payload(self, data: dict) -> bytes:
        json_str = json.dumps(data)
        json_bytes = json_str.encode('utf-8')
        return struct.pack('>I', len(json_bytes)) + json_bytes

    def _build_url(self) -> str:
        return self._ws_url

    def _get_headers(self) -> dict:
        return {
            "X-Api-Key": self.api_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Connect-Id": str(uuid.uuid4()),
        }

    async def init_connection(self, ws: Any) -> bool:
        try:
            config_request = self._make_header(message_type=1, flags=0)
            config_payload = self._make_payload({
                "user": {"uid": "esp-ai"},
                "audio": {
                    "format": "pcm",
                    "rate": 16000,
                    "bits": 16,
                    "channel": 1,
                },
                "request": {
                    "model_name": self.model_name,
                    "enable_itn": False,
                    "enable_punc": False,
                    "end_window_size": 400,
                    "vad_segment_duration": 2000,
                    "force_to_speech_time": 1000,
                }
            })
            await ws.send(config_request + config_payload)
            logger.info("VolcEngine ASR config request sent, waiting for ack...")

            # 性能优化：将 ack 超时从 5s 降到 2s，ack 通常在 100ms 内返回
            # 超时后仍然继续（proceeding anyway），不阻塞音频接收
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=2.0)
                if isinstance(response, str):
                    response = response.encode('latin-1')
                if len(response) >= 12:
                    payload_size = struct.unpack('>I', response[8:12])[0]
                    if len(response) >= 12 + payload_size:
                        payload = response[12:12 + payload_size]
                        try:
                            result = json.loads(payload.decode('utf-8'))
                            code = result.get("code")
                            if code is not None and code != 0 and code != "0":
                                logger.error(f"VolcEngine ASR config rejected: {result.get('message', 'Unknown')}")
                                return False
                            if "error" in result:
                                logger.error(f"VolcEngine ASR config error: {result['error']}")
                                return False
                            logger.info(f"VolcEngine ASR config ack received, session ready")
                        except json.JSONDecodeError:
                            logger.warning("VolcEngine ASR config response is not valid JSON, proceeding anyway")
                else:
                    logger.warning(f"VolcEngine ASR config response too short: {len(response)} bytes")
            except asyncio.TimeoutError:
                logger.warning("VolcEngine ASR config ack timeout, proceeding anyway")

            return True
        except Exception as e:
            logger.error(f"VolcEngine ASR init connection failed: {e}")
            return False

    async def send_audio_data(self, ws: Any, audio_data: bytes) -> None:
        audio_request = self._make_header(message_type=2)
        audio_payload = struct.pack('>I', len(audio_data)) + audio_data
        await ws.send(audio_request + audio_payload)

    async def send_audio_end(self, ws: Any) -> None:
        end_request = self._make_header(message_type=2, flags=2)
        await ws.send(end_request)

    def parse_response(self, response: Any) -> Optional[dict]:
        try:
            if isinstance(response, str):
                response = response.encode('latin-1')

            if len(response) < 12:
                return None

            payload_size = struct.unpack('>I', response[8:12])[0]

            if len(response) < 12 + payload_size:
                return None

            payload = response[12:12 + payload_size]
            try:
                result = json.loads(payload.decode('utf-8'))
            except UnicodeDecodeError:
                return None

            code = result.get("code")
            if code is not None and code != 0 and code != "0":
                logger.error(f"VolcEngine ASR error: {result.get('message', 'Unknown')}")
                return None

            if "error" in result:
                logger.error(f"VolcEngine ASR server error: {result['error']}")
                return None

            result_data = result.get("result", {})
            texts = result_data.get("texts", [])

            # 计费：音频时长（毫秒），火山 ASR 按音频时长计费
            duration_ms = 0
            audio_info = result_data.get("audio_info") or {}
            if isinstance(audio_info, dict):
                duration_ms = int(audio_info.get("duration", 0) or 0)

            is_final = result.get("is_final", False)

            if not is_final:
                additions = result_data.get("additions", {})
                if additions.get("definite"):
                    is_final = True
                else:
                    utterances = result_data.get("utterances", [])
                    for utt in utterances:
                        if utt.get("definite") and utt.get("text"):
                            is_final = True
                            break

            if texts:
                text = texts[0].get("text", "")
                return {
                    "text": text,
                    "is_final": is_final,
                    "duration": duration_ms,
                }

            text = result_data.get("text", "")
            return {
                "text": text,
                "is_final": is_final,
                "duration": duration_ms,
            }
        except Exception as e:
            logger.debug(f"VolcEngine ASR response parse error: {e}")
            return None

    async def pre_connect(self) -> Any:
        if self._enable_pool:
            pool = self.get_pool({
                "api_key": self.api_key,
                "resource_id": self.resource_id,
                "model_name": self.model_name,
                "enable_pool": self._enable_pool,
                "pool_max_size": self._pool_max_size,
                "pool_min_size": self._pool_min_size,
                "pool_heartbeat_interval": self._pool_heartbeat_interval,
                "pool_idle_timeout": self._pool_idle_timeout,
                "pool_connection_timeout": self._pool_connection_timeout,
            })
            if pool is None:
                return None

            try:
                if self._pre_ws:
                    try:
                        await self._pre_ws.close()
                    except Exception as e:
                        logger.debug(f"[Gateways] VolcEngine pre_connect 关闭旧连接异常: {e}")

                wrapped = await pool.acquire(timeout=10.0)
                self._pre_ws = wrapped.connection
                self._pre_ws_pool_wrapper = wrapped
                logger.info("VolcEngine ASR WebSocket pre-connect success (from pool)")
                return self._pre_ws
            except Exception as e:
                logger.error(f"VolcEngine ASR pre-connect failed: {e}")
                self._pre_ws = None
                self._pre_ws_pool_wrapper = None
                return None
        else:
            if self._pre_ws:
                try:
                    await self._pre_ws.close()
                except Exception as e:
                    logger.debug(f"[Gateways] VolcEngine pre_connect 关闭旧连接异常: {e}")
            try:
                headers = self._get_headers()
                self._pre_ws = await websockets.connect(
                    self._ws_url,
                    additional_headers=headers,
                    max_size=20 * 1024 * 1024,
                    ping_interval=None,
                )
                success = await self.init_connection(self._pre_ws)
                if not success:
                    await self._pre_ws.close()
                    self._pre_ws = None
                    return None
                self._pre_ws_pool_wrapper = None
                logger.info("VolcEngine ASR WebSocket pre-connect success")
                return self._pre_ws
            except Exception as e:
                logger.error(f"VolcEngine ASR pre-connect failed: {e}")
                self._pre_ws = None
                return None

    async def disconnect(self) -> None:
        if self._enable_pool and self._pre_ws_pool_wrapper:
            pool = self.get_pool({
                "api_key": self.api_key,
                "resource_id": self.resource_id,
                "model_name": self.model_name,
                "enable_pool": self._enable_pool,
                "pool_max_size": self._pool_max_size,
                "pool_min_size": self._pool_min_size,
                "pool_heartbeat_interval": self._pool_heartbeat_interval,
                "pool_idle_timeout": self._pool_idle_timeout,
                "pool_connection_timeout": self._pool_connection_timeout,
            })
            if pool:
                try:
                    await pool.release(self._pre_ws_pool_wrapper)
                except Exception as e:
                    logger.debug(f"[Gateways] VolcEngine disconnect 归还连接池异常: {e}")
            self._pre_ws = None
            self._pre_ws_pool_wrapper = None
        elif self._pre_ws:
            try:
                await self._pre_ws.close()
            except Exception as e:
                logger.debug(f"[Gateways] VolcEngine disconnect 关闭连接异常: {e}")
            self._pre_ws = None
            self._pre_ws_pool_wrapper = None

    async def recognize(self, audio_data: bytes, callback: Callable[[str], None] = None) -> str:
        full_text = ""
        headers = self._get_headers()
        start_time = time.time()
        status = "success"

        try:
            async with websockets.connect(
                self._ws_url,
                additional_headers=headers,
                max_size=20 * 1024 * 1024,
                ping_interval=None,
            ) as ws:
                config_request = self._make_header(message_type=1, flags=0)
                config_payload = self._make_payload({
                    "user": {"uid": "esp-ai"},
                    "audio": {
                        "format": "pcm",
                        "rate": 16000,
                        "bits": 16,
                        "channel": 1,
                    },
                    "request": {
                        "model_name": self.model_name,
                        "enable_itn": True,
                        "enable_punc": True,
                    }
                })
                await ws.send(config_request + config_payload)

                audio_request = self._make_header(message_type=2, flags=0)
                audio_payload = struct.pack('>I', len(audio_data)) + audio_data
                await ws.send(audio_request + audio_payload)

                end_request = self._make_header(message_type=2, flags=2)
                await ws.send(end_request)

                while True:
                    response = await asyncio.wait_for(ws.recv(), timeout=30.0)
                    result = self.parse_response(response)
                    if result is None:
                        continue
                    if result.get("is_final"):
                        text = result.get("text", "")
                        full_text += text
                        if callback:
                            callback(text)
                        break
                    elif result.get("text"):
                        text = result.get("text", "")
                        full_text = text
                        if callback:
                            callback(text)

        except Exception as e:
            status = "error"
            logger.error(f"VolcEngine ASR recognize error: {e}")
        finally:
            duration = time.time() - start_time
            logger.debug(f"VolcEngine ASR recognize duration: {duration:.2f}s, status: {status}")

        return full_text

    async def recognize_streaming(self, audio_chunks: list[bytes], callback: Callable[[str], None] = None) -> str:
        full_text = ""
        headers = self._get_headers()

        try:
            async with websockets.connect(
                self._ws_url,
                additional_headers=headers,
                max_size=20 * 1024 * 1024,
                ping_interval=None,
            ) as ws:
                config_request = self._make_header(message_type=1, flags=0)
                config_payload = self._make_payload({
                    "user": {"uid": "esp-ai"},
                    "audio": {
                        "format": "pcm",
                        "rate": 16000,
                        "bits": 16,
                        "channel": 1,
                    },
                    "request": {
                        "model_name": self.model_name,
                        "enable_itn": True,
                        "enable_punc": True,
                    }
                })
                await ws.send(config_request + config_payload)

                for chunk in audio_chunks:
                    await self.send_audio_data(ws, chunk)

                await self.send_audio_end(ws)

                while True:
                    response = await asyncio.wait_for(ws.recv(), timeout=30.0)
                    result = self.parse_response(response)
                    if result is None:
                        continue
                    if result.get("is_final"):
                        text = result.get("text", "")
                        full_text += text
                        if callback:
                            callback(text)
                        break
                    elif result.get("text"):
                        text = result.get("text", "")
                        full_text = text
                        if callback:
                            callback(text)

        except Exception as e:
            logger.error(f"VolcEngine ASR streaming error: {e}")

        return full_text
