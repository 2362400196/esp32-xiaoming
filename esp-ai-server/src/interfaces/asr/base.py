from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Callable, Optional

from src.domain.repositories import ASRRepository
from src.infrastructure.logging import get_logger

logger = get_logger("gateways")


class BaseASRGateway(ASRRepository, ABC):

    binary_protocol: bool = False

    def __init__(self, config: dict = None):
        self.config = config or {}
        self._enable_pool = False
        self._pre_ws = None
        self._pre_ws_pool_wrapper = None

    @abstractmethod
    def _build_url(self) -> str:
        pass

    @abstractmethod
    def _get_headers(self) -> dict:
        pass

    @abstractmethod
    async def init_connection(self, ws: Any) -> bool:
        pass

    @abstractmethod
    async def send_audio_data(self, ws: Any, audio_data: bytes) -> None:
        pass

    @abstractmethod
    async def send_audio_end(self, ws: Any) -> None:
        pass

    @abstractmethod
    def parse_response(self, response: Any) -> Optional[dict]:
        pass

    async def pre_connect(self) -> Any:
        return None

    async def disconnect(self) -> None:
        pass

    def take_pre_ws(self):
        ws = self._pre_ws
        wrapper = self._pre_ws_pool_wrapper
        self._pre_ws = None
        self._pre_ws_pool_wrapper = None
        return ws, wrapper

    @classmethod
    def get_pool(cls, config: dict = None):
        return None

    @classmethod
    async def close_pool(cls) -> None:
        pass

    async def recognize(self, audio_data: bytes, callback: Callable[[str], None] = None) -> str:
        return ""

    async def recognize_stream(self, audio_stream: AsyncIterator[bytes]) -> str:
        chunks = []
        async for chunk in audio_stream:
            chunks.append(chunk)
        return ""

    async def recognize_streaming(self, audio_chunks: list[bytes], callback: Callable[[str], None] = None) -> str:
        return ""

    async def recognize_once(self, audio_data: bytes, **kwargs) -> str:
        return await self.recognize(audio_data)

    async def recognize_streaming_repo(
        self,
        audio_stream: AsyncIterator[bytes],
        on_result: Any,
        on_final: Any,
        **kwargs
    ) -> str:
        chunks = []
        async for chunk in audio_stream:
            chunks.append(chunk)
        text = await self.recognize_streaming(chunks, on_result)
        if on_final:
            on_final()
        return text
