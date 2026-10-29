"""TTS Worker：audio_queue → TTS 合成 → send_queue。"""
from __future__ import annotations

import asyncio
import json
import re
import time

from src.infrastructure.logging import get_logger
from src.use_cases.pipeline.mp3 import _estimate_word_timestamps, mp3_duration_ms

logger = get_logger(__name__)


class TtsWorkerMixin:
    """TTS Worker：逐句合成音频并下发字幕/时长。"""

    # 过滤 Markdown 和特殊符号（工具调用结果常带这些）
    MARKDOWN_CLEANER = re.compile(r'(\*\*|__|\*|_|`|#{1,6}\s*|~~)(.*?)\1')
    LINE_CLEANER = re.compile(r'^[-*]\s+|^\d+\.\s+', re.MULTILINE)

    async def _synthesize_one(self, session, seq_id, synth_text, stats):
        """合成一句文本，音频帧直接入发送队列。

        返回 (audio_data, subtitle_end_ms, total_audio_bytes)；
        合成异常时返回 None（调用方按占位空帧兜底，不重试）；
        CancelledError 在完成 audio 队列 task_done 后原样抛出。
        """
        total_audio_bytes = 0
        audio_data = bytearray()
        subtitle_end_ms = 0  # 本句字幕末字 end_ms（句内累计），用于时长兜底
        sent_label = False   # 首个音频帧携带句子文本（与旧单帧标签行为一致）
        try:
            async for event in session.synthesize(synth_text, cancel_event=self.cancel_event):
                if self.cancel_event.is_set():
                    break
                if isinstance(event, bytes):
                    # 插件 TTS 网关：直接产出音频字节，无字幕事件
                    audio_chunk = event
                elif event.kind == "subtitle":
                    # 字级时间戳：换算为绝对流位置（相对整轮播放起点）后下发，
                    # 设备端按实际播放位置直接比对，不受语气快慢/情感停顿影响
                    words = event.data.get("words", [])
                    if words:
                        for w in words:
                            if w.get("end_ms", 0) > subtitle_end_ms:
                                subtitle_end_ms = w["end_ms"]
                        base = int(self._cumulative_duration_ms)
                        abs_words = [{
                            "word": w["word"],
                            "start_ms": w["start_ms"] + base,
                            "end_ms": w["end_ms"] + base,
                        } for w in words]
                        await self.channel.send_json({
                            "type": "instruct",
                            "command_id": "tts_subtitle",
                            "data": json.dumps({"seq": seq_id, "words": abs_words}, ensure_ascii=False),
                        })
                        logger.info(f"[Pipeline] TTS #{seq_id} 字幕 {len(abs_words)} 字, 流基准 {base}ms")
                    continue
                else:
                    audio_chunk = event.data
                if audio_chunk:
                    total_audio_bytes += len(audio_chunk)
                    audio_data.extend(audio_chunk)
                    stats["chunks"] += 1
                    stats["bytes"] += len(audio_chunk)
                    frame = self.voice_generator.make_tts_frame(
                        self.config.tts_session_id, audio_chunk, "00"
                    )
                    await self.queues.send.put((seq_id, frame, synth_text if not sent_label else None))
                    sent_label = True
        except asyncio.CancelledError:
            self.queues.audio.task_done()
            raise
        except Exception as e:
            logger.error(f"[Pipeline] TTS 合成 #{seq_id} 异常: {e}")
            return None
        return audio_data, subtitle_end_ms, total_audio_bytes

    async def _tts_task(self, volc_tts, session):
        """TTS Worker：audio_queue → TTS合成 → send_queue"""
        _perf = self._perf
        _perf["tts_start"] = time.time()
        synth_stats = {"chunks": 0, "bytes": 0}
        own_session = session is None
        if own_session:
            try:
                session = await volc_tts.create_session(cancel_event=self.cancel_event, tool_manager=self._tool_manager)
            except Exception as e:
                logger.error(f"[Pipeline] TTS 创建 session 失败: {e}")
                await self.queues.send.put((-1, None, None))
                return
        try:
            while True:
                if self.cancel_event.is_set():
                    await self.queues.send.put((-1, None, None))
                    return

                seq_id, sentence_text, _ = await self.queues.audio.get()

                if self.cancel_event.is_set():
                    self.queues.audio.task_done()
                    await self.queues.send.put((-1, None, None))
                    return

                if seq_id == -1 or sentence_text is None:
                    self.queues.audio.task_done()
                    await self.queues.send.put((-1, None, None))
                    return

                if not sentence_text.strip() or len(sentence_text.strip()) <= 1:
                    self.queues.audio.task_done()
                    continue

                # 过滤 Markdown 格式化符号和内部标记
                sentence_text = self.MARKDOWN_CLEANER.sub(r'\2', sentence_text)
                sentence_text = self.LINE_CLEANER.sub('', sentence_text)
                sentence_text = re.sub(r'\[secret:\d+\]', '', sentence_text)
                sentence_text = sentence_text.replace('\n\n', '\n').replace('  ', ' ').strip()

                sentence_text = self._detect_and_send_emotion(sentence_text)

                # 计费：累加本次 TTS 合成文本字符数（含标点）
                if self.billing is not None:
                    self.billing.add_tts(len(sentence_text))

                logger.info(f"[Pipeline] TTS 合成 #{seq_id}: {sentence_text[:60]}...")

                # 保存原始文本，估算 TTS 时长，立刻发给发送器
                original_text = sentence_text
                tts_duration_ms = 0
                if original_text:
                    cn_chars = sum(1 for c in original_text if '\u4e00' <= c <= '\u9fff')
                    # 标点单独计费，避免被当作英文(90ms/字)重复累加导致估算偏长、字幕滞后
                    punct_chars = sum(1 for c in original_text if c in "，。！？,.!?；;：:、…")
                    en_chars = len(original_text) - cn_chars - punct_chars
                    tts_duration_ms = int(cn_chars * 230 + en_chars * 90)
                    # 标点停顿补偿：TTS 在逗号/句号等处有自然语气停顿，纯字符估算偏短
                    tts_duration_ms += original_text.count("，") * 250
                    tts_duration_ms += original_text.count("。") * 400
                    tts_duration_ms += original_text.count("！") * 400
                    tts_duration_ms += original_text.count("？") * 400
                    tts_duration_ms += original_text.count(",") * 250
                    tts_duration_ms += original_text.count(".") * 300
                    tts_duration_ms += original_text.count("!") * 300
                    tts_duration_ms += original_text.count("?") * 300
                    if tts_duration_ms < 500:
                        tts_duration_ms = 500
                    logger.info(f"[Pipeline] TTS #{seq_id} {len(original_text)}字(中{cn_chars}英{en_chars}), 估 {tts_duration_ms}ms")
                    # 合成前直接发送字幕和估算时长，不等音频帧，避免被音频队列阻塞。
                    # 字幕先到、音频后播；合成完成后会下发该句真实时长（tts_duration）修正。
                    payload = json.dumps({"text": original_text, "duration_ms": tts_duration_ms, "seq": seq_id}, ensure_ascii=False)
                    await self.channel.send_json({"type": "instruct", "command_id": "on_llm_cb", "data": payload})
                total_audio_bytes = 0
                audio_data = bytearray()
                subtitle_end_ms = 0  # 本句字幕末字 end_ms（句内累计），用于时长兜底
                synth_stats = {"chunks": 0, "bytes": 0}
                # 【空音频重试】插件 TTS 偶发静默空完成：连接被服务端关闭时
                # get_audio 返回 done=True / 0 字节 / 无错误（插件"服务端关闭连接，
                # 标记完成"路径），旧版视为正常完成 → 整句音频丢失 → Sender 0 帧结束、
                # 连 play_audio 都不发 → 设备等不到回复、服务端空等播放完成 33s 超时
                # （2026-10-26 16:45 实测"打断后跳聆听中不播放"）。重试一次：
                # 重新走连接池获取，健康检查会丢弃被关闭的坏连接。
                for _synth_attempt in range(2):
                    if _synth_attempt > 0:
                        logger.warning(
                            f"[Pipeline] TTS #{seq_id} 上一次合成 0 字节音频"
                            f"（连接疑似被服务端静默关闭），重试第 {_synth_attempt + 1} 次"
                        )
                    _synth = await self._synthesize_one(session, seq_id, sentence_text, synth_stats)
                    if _synth is None:
                        await self.queues.send.put((seq_id, b"", None))
                        break
                    audio_data, subtitle_end_ms, total_audio_bytes = _synth
                    if total_audio_bytes > 0 or self.cancel_event.is_set():
                        break
                if total_audio_bytes == 0 and _synth is not None and not self.cancel_event.is_set():
                    logger.error(f"[Pipeline] TTS #{seq_id} 重试后仍 0 字节音频，本句跳过（设备端将无本句音频）")

                # TTS 合成完成，解析 MP3 帧头得到该句真实时长；
                # 用字幕末字 endTime 兜底：音频收集不全或 MP3 解析失败时仍能给出准确时长
                actual_ms = mp3_duration_ms(bytes(audio_data)) if audio_data else 0
                if subtitle_end_ms == 0 and actual_ms > 0 and original_text:
                    # 无字级时间戳的 TTS：按 MP3 真实时长生成估算字级时间戳，
                    # 让设备端所有 TTS 统一走字级渲染路径（同一套滚动/匹配逻辑）
                    est_words = _estimate_word_timestamps(original_text, actual_ms)
                    if est_words:
                        base = int(self._cumulative_duration_ms)
                        abs_words = [{
                            "word": w["word"],
                            "start_ms": w["start_ms"] + base,
                            "end_ms": w["end_ms"] + base,
                        } for w in est_words]
                        await self.channel.send_json({
                            "type": "instruct",
                            "command_id": "tts_subtitle",
                            "data": json.dumps({"seq": seq_id, "words": abs_words}, ensure_ascii=False),
                        })
                        subtitle_end_ms = est_words[-1]["end_ms"]
                        logger.info(f"[Pipeline] TTS #{seq_id} 无字幕事件, 按MP3时长生成估算时间戳 {len(abs_words)} 词")
                if subtitle_end_ms > actual_ms:
                    actual_ms = subtitle_end_ms
                if actual_ms > 0:
                    self._total_duration_ms += actual_ms
                    self._cumulative_duration_ms += actual_ms
                    logger.info(f"[Pipeline] TTS #{seq_id} 实际时长: {tts_duration_ms}ms → {actual_ms}ms, 累计 {self._total_duration_ms}ms")
                    # 下发该句真实时长（带 seq），设备端按 seq 更新对应句子槽
                    await self.channel.send_json({
                        "type": "instruct",
                        "command_id": "tts_duration",
                        "data": json.dumps({"seq": seq_id, "duration_ms": actual_ms}),
                    })
                elif tts_duration_ms > 0 and total_audio_bytes > 0:
                    # 【0 字节不计入时长】估算时长只代表"本来该有多少音频"。
                    # 旧版对 0 字节句子也计入 total_duration_ms，上层据此误判
                    # "已有音频下发"，空等设备回 client_out_audio_over 直到 33s
                    # 超时（2026-10-26 实测"打断后跳聆听中不播放"的直接原因）。
                    # 0 字节 = 设备端不会播放本句，时长累计（字幕基准/播放等待
                    # 判定）都必须跳过，让上层走"无音频输出"快速收尾路径。
                    self._total_duration_ms += tts_duration_ms
                    self._cumulative_duration_ms += tts_duration_ms

                self.queues.audio.task_done()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[Pipeline] TTS 任务异常: {e}")
        finally:
            _perf["tts_end"] = time.time()
            _perf["tts_chunks"] = synth_stats["chunks"]
            _perf["tts_audio_bytes"] = synth_stats["bytes"]
            if own_session and session:
                try:
                    await session.close()
                except Exception as e:
                    logger.debug(f"[Pipeline] 关闭 TTS session 异常: {e}")
