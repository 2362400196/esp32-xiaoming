"""Sender Worker：send_queue → 发送音频到客户端。"""
from __future__ import annotations

import asyncio
import time

from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


class SenderWorkerMixin:
    """Sender Worker：按播放速率节流发送音频帧。"""

    async def _sender_task(self):
        """Sender Worker：send_queue → 发送音频到客户端
        字幕和时长信息已由 _tts_task 直接发送，不再经过此队列。"""
        total_sent = 0
        frame_count = 0
        client_max_buffer = self.config.client_max_buffer
        # 按播放速率(1x)节流发送音频，避免发送超前导致：
        # 1) 客户端缓冲被打满 → 播放卡顿
        # 2) WiFi 半双工下音频抢占语音数据通道
        # 不依赖客户端 client_available_audio 上报（客户端已禁用该上报）。
        send_start_time = None
        sent_audio_ms_total = 0.0
        # 允许发送超前播放的最大毫秒数。300ms 过浅：TTS 首帧后生成间隙或句子间停顿
        # 超过 300ms 时客户端流缓冲排空 → I2S 欠载（"卡顿一下"）。
        # 加大到 1000ms，客户端维持 ~1s 缓冲吸收间隙（客户端流缓冲 50KB≈6.4s，足够容纳）。
        TARGET_AUDIO_LEAD_MS = 1000
        AUDIO_BITRATE_KBPS = 64      # MP3 发送比特率（与客户端 spk_bitrate=64 一致）

        try:
            while True:
                if self.cancel_event.is_set():
                    return

                item = await self.queues.send.get()
                seq_id, audio, _ = item[0], item[1], item[2]

                if self.cancel_event.is_set():
                    self.queues.send.task_done()
                    return

                if seq_id == -1 or audio is None:
                    logger.info(f"[Pipeline] Sender 结束，{frame_count}帧/{total_sent}B")
                    self.queues.send.task_done()
                    return

                if not audio:
                    self.queues.send.task_done()
                    continue

                try:
                    # 第一帧实际音频数据到达时，发送 play_audio 和 tts_chunk_start
                    if not self._play_audio_sent:
                        self._play_audio_sent = True
                        self._perf["first_audio_sent"] = time.time()
                        await self.channel.send_json({"type": "play_audio", "tts_task_id": self.config.tts_session_id})
                        # 等待客户端处理 play_audio 并上报缓冲区状态，最多 50ms
                        wait_start = time.time()
                        while self._device_buffer >= client_max_buffer and time.time() - wait_start < 0.05:
                            await asyncio.sleep(0.01)
                        await self.channel.send_json({"type": "session_status", "status": "tts_chunk_start"})
                        logger.info(f"[Pipeline] 发送 play_audio + tts_chunk_start，device_buffer={self._device_buffer}")

                    if self.cancel_event.is_set():
                        self.queues.send.task_done()
                        return

                    await self.channel.send_bytes(audio)
                    total_sent += len(audio)
                    frame_count += 1

                    if frame_count % 50 == 0:
                        logger.info(f"[Pipeline] Sender: {frame_count}帧/{total_sent}B")

                except Exception as e:
                    logger.debug(f"[Pipeline] Sender 发送失败: {e}")
                    self.queues.send.task_done()
                    return

                # 流控：按音频播放速率(1x)节流，允许 TARGET_AUDIO_LEAD_MS 超前。
                # 帧时长按 MP3 比特率估算：frame_ms = bytes * 8 / bitrate_kbps
                if send_start_time is None:
                    send_start_time = time.time()
                frame_audio_ms = len(audio) * 8.0 / AUDIO_BITRATE_KBPS
                sent_audio_ms_total += frame_audio_ms
                elapsed_real_ms = (time.time() - send_start_time) * 1000.0
                overrun_ms = sent_audio_ms_total - elapsed_real_ms
                if overrun_ms > TARGET_AUDIO_LEAD_MS:
                    await asyncio.sleep((overrun_ms - TARGET_AUDIO_LEAD_MS) / 1000.0)

                # 兜底：客户端若仍上报 client_available_audio，保留缓冲满保护
                if self._device_buffer < client_max_buffer * 0.1:
                    await asyncio.sleep(0.5)
                elif self._device_buffer < client_max_buffer * 0.3:
                    await asyncio.sleep(0.2)

                self.queues.send.task_done()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[Pipeline] Sender 异常: {e}")
