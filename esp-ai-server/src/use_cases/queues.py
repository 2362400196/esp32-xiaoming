from __future__ import annotations

import asyncio
from typing import Any

from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


class BackpressureQueue:
    """
    背压队列：支持流量控制的异步队列

    特性：
    - 有界队列（防止内存溢出）
    - 多种溢出策略（block/drop_oldest/drop_newest）
    - 支持优雅关闭和清空
    """

    def __init__(self, maxsize: int, name: str = "queue", on_full: str = "block"):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._name = name
        self._on_full = on_full
        self._dropped = 0

    @property
    def queue(self) -> asyncio.Queue:
        return self._queue

    async def put(self, item: Any) -> None:
        if self._on_full == "block":
            await self._queue.put(item)
        elif self._on_full == "drop_oldest":
            await self._put_drop_oldest(item)
        elif self._on_full == "drop_newest":
            self._put_drop_newest(item)

    def put_nowait(self, item: Any) -> None:
        if self._on_full == "block":
            self._queue.put_nowait(item)
        elif self._on_full == "drop_oldest":
            self._put_nowait_drop_oldest(item)
        elif self._on_full == "drop_newest":
            self._put_drop_newest(item)

    async def _put_drop_oldest(self, item: Any) -> None:
        while True:
            try:
                self._queue.put_nowait(item)
                break
            except asyncio.QueueFull:
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                    self._dropped += 1
                except asyncio.QueueEmpty:
                    pass

    def _put_nowait_drop_oldest(self, item: Any) -> None:
        while True:
            try:
                self._queue.put_nowait(item)
                break
            except asyncio.QueueFull:
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                    self._dropped += 1
                except asyncio.QueueEmpty:
                    break

    def _put_drop_newest(self, item: Any) -> None:
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            self._dropped += 1

    async def get(self) -> Any:
        return await self._queue.get()

    def get_nowait(self) -> Any:
        return self._queue.get_nowait()

    def task_done(self) -> None:
        self._queue.task_done()

    async def join(self) -> None:
        await self._queue.join()

    def clear(self) -> int:
        cleared = 0
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
                cleared += 1
            except asyncio.QueueEmpty:
                break
        if cleared:
            logger.debug(f"[Backpressure] {self._name}: 清空 {cleared} 条 (累计丢弃 {self._dropped})")
        return cleared

    def empty(self) -> bool:
        return self._queue.empty()

    def full(self) -> bool:
        return self._queue.full()

    def qsize(self) -> int:
        return self._queue.qsize()

    @property
    def dropped(self) -> int:
        return self._dropped

    def reset_stats(self) -> None:
        self._dropped = 0


class TextQueue(BackpressureQueue):
    """文本队列：LLM输出 → Splitter，满时阻塞（保证长回复不丢句）"""

    def __init__(self, maxsize: int = 100):
        super().__init__(maxsize=maxsize, name="text_queue", on_full="block")


class AudioQueue(BackpressureQueue):
    """音频队列：Splitter → TTS，满时阻塞"""

    def __init__(self, maxsize: int = 20):
        super().__init__(maxsize=maxsize, name="audio_queue", on_full="block")


class SendQueue(BackpressureQueue):
    """发送队列：TTS → Sender，满时阻塞"""

    def __init__(self, maxsize: int = 500):
        super().__init__(maxsize=maxsize, name="send_queue", on_full="block")


class BackpressureQueues:
    """
    三级背压队列组

    text:  LLM → Splitter (drop_oldest)
    audio: Splitter → TTS  (block)
    send:  TTS → Sender    (block)
    """

    def __init__(self):
        self.text = TextQueue(maxsize=100)
        self.audio = AudioQueue(maxsize=20)
        self.send = SendQueue(maxsize=256)

    def clear_all(self) -> None:
        self.text.clear()
        self.audio.clear()
        self.send.clear()

    def put_sentinel(self) -> None:
        try:
            self.text.put_nowait((-1, None))
        except asyncio.QueueFull:
            pass
        try:
            self.audio.put_nowait((-1, None, None))
        except asyncio.QueueFull:
            pass


__all__ = [
    "BackpressureQueue",
    "TextQueue",
    "AudioQueue",
    "SendQueue",
    "BackpressureQueues",
]
