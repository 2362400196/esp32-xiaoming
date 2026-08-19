from __future__ import annotations

from typing import Any, AsyncIterator, Optional

from src.interfaces.asr.base import BaseASRGateway


class XunfeiASRGateway(BaseASRGateway):

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.app_id = config.get("app_id", "")
        self.api_key = config.get("api_key", "")
        self.api_secret = config.get("api_secret", "")

    def _build_url(self) -> str:
        return "wss://iat.xfyun.cn/v2/iat"

    def _get_headers(self) -> dict:
        return {}

    async def init_connection(self, ws: Any) -> bool:
        return True

    async def send_audio_data(self, ws: Any, audio_data: bytes) -> None:
        await ws.send(audio_data)

    async def send_audio_end(self, ws: Any) -> None:
        await ws.send(b"")

    def parse_response(self, response: Any) -> Optional[dict]:
        return None

    async def recognize_once(self, audio_data: bytes, **kwargs) -> str:
        return ""

    async def recognize_streaming(
        self,
        audio_stream: AsyncIterator[bytes],
        on_result: Any,
        on_final: Any,
        **kwargs
    ) -> str:
        return ""
