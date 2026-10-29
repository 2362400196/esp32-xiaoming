"""Splitter Worker：text_queue → audio_queue。"""
from __future__ import annotations

import asyncio

from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


class SplitterWorkerMixin:
    """Splitter Worker：合并短句后送入 TTS 队列。"""

    MERGE_THRESHOLD = 40  # 短句合并长度阈值（字符），减少 TTS 请求数

    async def _splitter_task(self):
        """Splitter Worker：text_queue → audio_queue（合并短块，减少 TTS 请求数）

        首句立即发出保证首响延迟；后续软切分短句累积合并，
        遇到硬切分（。！？）或达到长度阈值时一次性发出。
        """
        pending = ""
        pending_seq = -1
        first_emitted = False
        try:
            while True:
                if self.cancel_event.is_set():
                    return

                seq_id, sentence = await self.queues.text.get()
                try:
                    if seq_id == -1 or sentence is None:
                        if pending:
                            await self.queues.audio.put((pending_seq, pending, pending))
                            pending = ""
                        await self.queues.audio.put((-1, None, None))
                        return

                    if not sentence.strip() or len(sentence.strip()) <= 1:
                        continue

                    if not first_emitted:
                        await self.queues.audio.put((seq_id, sentence, sentence))
                        first_emitted = True
                        continue

                    if not pending:
                        pending_seq = seq_id
                    pending += sentence
                    is_hard_stop = sentence[-1] in "。！？.!?"
                    if is_hard_stop or len(pending) >= self.MERGE_THRESHOLD:
                        await self.queues.audio.put((pending_seq, pending, pending))
                        pending = ""
                finally:
                    self.queues.text.task_done()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[Pipeline] Splitter 任务异常: {e}")
