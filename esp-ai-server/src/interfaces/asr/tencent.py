from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
import urllib.parse
import uuid
from typing import Any, Callable, Optional

import websockets

from src.interfaces.asr.base import BaseASRGateway, logger


class TencentASRGateway(BaseASRGateway):

    _pool = None
    _pool_initialized = False
    binary_protocol: bool = False

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.app_id = config.get("app_id", "")
        self.secret_id = config.get("secret_id", "")
        self.secret_key = config.get("secret_key", "")
        self.engine_model_type = config.get("engine_model_type", "16k_zh")
        self.voice_format = config.get("voice_format", 1)
        self.needvad = config.get("needvad", 1)
        self.ws_url = f"wss://asr.cloud.tencent.com/asr/v2/{self.app_id}"
        self._enable_pool = False

    @classmethod
    def get_pool(cls, config: dict = None):
        return None

    @classmethod
    async def close_pool(cls) -> None:
        if cls._pool and not cls._pool.is_closed:
            await cls._pool.close()
            cls._pool = None
            cls._pool_initialized = False

    def _generate_signature(self, params: dict) -> str:
        sorted_params = sorted(params.items())
        param_str = "&".join(f"{k}={v}" for k, v in sorted_params)
        signature_origin = f"asr.cloud.tencent.com/asr/v2/{self.app_id}?{param_str}"
        hmac_obj = hmac.new(self.secret_key.encode("utf-8"), signature_origin.encode("utf-8"), hashlib.sha1)
        return urllib.parse.quote(base64.b64encode(hmac_obj.digest()).decode("utf-8"))

    def _build_url(self) -> str:
        timestamp = int(time.time())
        expired = timestamp + 3600
        nonce = int(1000000000 + (uuid.uuid4().int % 8000000000))
        voice_id = str(uuid.uuid4())

        params = {
            "secretid": self.secret_id,
            "timestamp": timestamp,
            "expired": expired,
            "nonce": nonce,
            "engine_model_type": self.engine_model_type,
            "voice_id": voice_id,
            "voice_format": self.voice_format,
            "needvad": self.needvad,
            "vad_silence_time": 1000,
            "filter_empty_result": 0,
        }

        signature = self._generate_signature(params)
        params["signature"] = signature

        param_string = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.ws_url}?{param_string}"

    def _get_headers(self) -> dict:
        return {}

    async def init_connection(self, ws: Any) -> bool:
        return True

    async def send_audio_data(self, ws: Any, audio_data: bytes) -> None:
        if isinstance(audio_data, bytes):
            await ws.send(audio_data)
        else:
            await ws.send(bytes(audio_data))

    async def send_audio_end(self, ws: Any) -> None:
        await ws.send(b"")

    def parse_response(self, response: Any) -> Optional[dict]:
        try:
            result = json.loads(response) if isinstance(response, str) else response
            if result.get("code") != 0:
                return None
            if result.get("result"):
                text_data = result["result"]
                if isinstance(text_data, dict):
                    text = text_data.get("voice_text_str", "")
                else:
                    text = str(text_data)
                is_final = result.get("is_final", False) or result.get("slice_type") == 2
                return {
                    "text": text,
                    "is_final": is_final,
                    "confidence": 1.0,
                }
            return None
        except Exception:
            return None

    async def pre_connect(self) -> Any:
        if self._pre_ws:
            try:
                await self._pre_ws.close()
            except Exception as e:
                logger.debug(f"[Gateways] pre_connect 关闭旧连接异常: {e}")
        try:
            url = self._build_url()
            self._pre_ws = await websockets.connect(url, max_size=20 * 1024 * 1024)
            self._pre_ws_pool_wrapper = None
            logger.info("Tencent ASR WebSocket pre-connect success")
            return self._pre_ws
        except Exception as e:
            logger.error(f"Tencent ASR pre-connect failed: {e}")
            self._pre_ws = None
            return None

    async def disconnect(self) -> None:
        if self._pre_ws:
            try:
                await self._pre_ws.close()
            except Exception as e:
                logger.debug(f"[Gateways] disconnect 关闭连接异常: {e}")
            self._pre_ws = None
            self._pre_ws_pool_wrapper = None

    async def recognize(self, audio_data: bytes, callback: Callable[[str], None] = None) -> str:
        full_text = ""
        url = self._build_url()
        start_time = time.time()
        status = "success"

        try:
            async with websockets.connect(url, max_size=20 * 1024 * 1024) as ws:
                logger.info("Tencent ASR WebSocket connected, sending audio")
                await self.send_audio_data(ws, audio_data)

                while True:
                    try:
                        response = await asyncio.wait_for(ws.recv(), timeout=30.0)
                        result = json.loads(response)

                        if result.get("code") != 0:
                            logger.error(f"Tencent ASR error: {result.get('message', 'Unknown error')}")
                            break

                        if result.get("result"):
                            text_data = result["result"]
                            if isinstance(text_data, dict):
                                text = text_data.get("voice_text_str", "")
                            else:
                                text = str(text_data)
                            if callback:
                                callback(text)
                            full_text += text

                        if result.get("is_final", False):
                            break

                        if result.get("slice_type") == 2:
                            break

                    except asyncio.TimeoutError:
                        logger.warning("Tencent ASR receive timeout")
                        break

        except Exception as e:
            status = "error"
            logger.error(f"Tencent ASR WebSocket error: {e}")
        finally:
            duration = time.time() - start_time
            logger.debug(f"Tencent ASR recognize duration: {duration:.2f}s, status: {status}")

        return full_text

    async def recognize_streaming(self, audio_chunks: list[bytes], callback: Callable[[str], None] = None) -> str:
        full_text = ""
        url = self._build_url()

        try:
            async with websockets.connect(url, max_size=20 * 1024 * 1024) as ws:
                for chunk in audio_chunks:
                    await self.send_audio_data(ws, chunk)
                    await asyncio.sleep(0.01)

                await self.send_audio_end(ws)

                while True:
                    try:
                        response = await asyncio.wait_for(ws.recv(), timeout=30.0)
                        result = json.loads(response)

                        if result.get("code") != 0:
                            logger.error(f"Tencent ASR error: {result.get('message', 'Unknown error')}")
                            break

                        if result.get("result"):
                            text_data = result["result"]
                            if isinstance(text_data, dict):
                                text = text_data.get("voice_text_str", "")
                            else:
                                text = str(text_data)
                            if callback:
                                callback(text)
                            full_text += text

                        if result.get("is_final", False):
                            break

                        if result.get("slice_type") == 2:
                            break

                    except asyncio.TimeoutError:
                        logger.warning("Tencent ASR receive timeout")
                        break

        except Exception as e:
            logger.error(f"Tencent ASR streaming error: {e}")

        return full_text
