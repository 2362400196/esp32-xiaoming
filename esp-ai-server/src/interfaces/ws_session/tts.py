"""WS 会话 TTS 完成回调：等待流水线、播放完成与下一轮恢复。"""
from __future__ import annotations

import asyncio
import time

from src.domain.entities import SessionState
from src.infrastructure.config import get_settings
from src.infrastructure.logging import get_logger

from .helpers import _log_perf_report

logger = get_logger(__name__)


class TtsMixin:
    """TTS 播放完成与流水线收尾相关方法。"""

    async def _on_tts_complete(self) -> None:
        """TTS 完成回调"""
        session = self.session
        fsm = self.fsm
        try:
            logger.info(f"[Session:{session.session_id}] Waiting for pipeline to complete...")
            # 动态 pipeline 超时：TTS 合成期间持续产出音频，超时随合成进度延长。
            # 基础 30s + 已合成音频时长×1.5 + 15s 余量，
            # 避免长故事/长回答（LLM 10s + 串行 TTS 合成 + 音频按播放速率发送）被 30s 硬超时误杀。
            _pipeline = session._current_pipeline
            _started = time.time()
            _deadline = _started + 30.0
            # 绝对上限：无论音频产出多少，本轮 pipeline 最多等 300s。
            # 见下方"只在有进展时续期"的说明——没有这条上限，续期逻辑本身能把
            # 一轮已卡死的 pipeline 无限续命。
            _hard_deadline = _started + 300.0
            _last_est_audio_s = 0.0
            result = None
            try:
                while True:
                    _remaining = _deadline - time.time()
                    if _remaining <= 0:
                        logger.warning(f"[Session:{session.session_id}] Pipeline timeout, cancelling and moving on")
                        self.pipeline_task.cancel()
                        try:
                            await self.pipeline_task
                        except asyncio.CancelledError:
                            pass
                        except Exception as e:
                            logger.debug(f"[Session:{session.session_id}] Pipeline cancel cleanup error: {e}")
                        result = None
                        break
                    try:
                        # shield 防止 wait_for 超时误取消 pipeline_task（外部 cancel 仍会传播）
                        result = await asyncio.wait_for(
                            asyncio.shield(self.pipeline_task), timeout=min(_remaining, 1.0)
                        )
                        break
                    except asyncio.TimeoutError:
                        # 每 1s 检查一次：只有"确实又产出了更多音频"才算有进展，才允许延期。
                        # 旧实现只要 _total_duration_ms > 0 就每秒续一次，pipeline 卡在
                        # TTS 死连接上（音频不再增长）时会永远等不到超时——设备停在
                        # "播放中"，服务端空转（2026-10-26 打断后卡住实测就是这个）。
                        _est_audio_s = 0.0
                        if _pipeline is not None:
                            _est_audio_s = getattr(_pipeline, "_total_duration_ms", 0) / 1000.0
                        if _est_audio_s > _last_est_audio_s + 0.05:
                            _last_est_audio_s = _est_audio_s
                            _new_deadline = time.time() + max(30.0, _est_audio_s * 1.5 + 15.0)
                            if _new_deadline > _deadline:
                                _deadline = min(_new_deadline, _hard_deadline)
                                if _deadline >= _hard_deadline:
                                    logger.warning(
                                        f"[Session:{session.session_id}] Pipeline 已达 300s 硬上限，"
                                        f"不再随音频产出延期（est_audio={_est_audio_s:.1f}s）"
                                    )
            except asyncio.CancelledError:
                # pipeline 被外部取消（如 client_out_audio_over 或新 start 命令）
                logger.info(f"[Session:{session.session_id}] Pipeline cancelled externally")
                result = None

            stop_pipeline = getattr(result, 'stop_pipeline', False) if result else False

            if stop_pipeline:
                logger.info(f"[Session:{session.session_id}] Pipeline 被 StopPipeline 终止，工具已接管，不启动下一轮 ASR")
                self._trigger_growth()
                await fsm.set(SessionState.IDLE)
                session.tts_playback_done.set()
                # 计费：本轮对话结束（工具接管），保存记录并重置累计器
                await session.billing.save_record_and_reset()
                return

            # 获取音频总时长（毫秒）
            total_duration_ms = getattr(result, 'total_duration_ms', 0) if result else 0
            audio_duration_s = total_duration_ms / 1000.0

            # 如果 Pipeline 被取消或未产生任何音频，跳过 TTS 播放等待（设备不会回 client_out_audio_over）
            if not result or total_duration_ms == 0:
                logger.info(f"[Session:{session.session_id}] Pipeline 无音频输出 (cancelled={result is None}), 跳过 TTS 播放等待")
                _log_perf_report(session, result, _pipeline, session.runtime.asr_full_text)
                session.tts_playback_done.set()
                self._trigger_growth()
                # 计费：本轮对话结束（无音频输出），保存记录并重置累计器
                await session.billing.save_record_and_reset()
                if not session._closed and fsm.get() != SessionState.IDLE:
                    # 新一轮唤醒流程进行中（新 start 命令取消了本 pipeline）：
                    # 不在此启动下一轮 ASR，由 _do_wake_start 在唤醒音频播完后统一启动，
                    # 避免双重启动竞态导致音频发往被取消的旧会话
                    if self._new_wake_pending:
                        logger.info(f"[Session:{session.session_id}] 新一轮唤醒流程进行中，跳过 _start_next_asr（由 _do_wake_start 启动 ASR）")
                        return
                    await self._start_next_asr()
                elif fsm.get() == SessionState.IDLE:
                    logger.info(f"[Session:{session.session_id}] Session is IDLE, skip next ASR")
                return

            # 动态计算 TTS 播放完成超时时间
            _settings = get_settings()
            base_timeout = _settings.session.tts_playback_base_timeout
            max_timeout = _settings.session.tts_playback_max_timeout
            duration_multiplier = _settings.session.tts_playback_duration_multiplier

            # 计算动态超时：基础时间 + 音频时长 × 乘数
            dynamic_timeout = base_timeout + audio_duration_s * duration_multiplier
            # 限制最大超时
            dynamic_timeout = min(dynamic_timeout, max_timeout)

            logger.info(f"[Session:{session.session_id}] Pipeline completed, audio_duration={audio_duration_s:.1f}s, dynamic_timeout={dynamic_timeout:.1f}s, waiting for TTS playback done")
            self._trigger_growth()
            try:
                await asyncio.wait_for(session.tts_playback_done.wait(), timeout=dynamic_timeout)
            except asyncio.TimeoutError:
                logger.warning(f"[Session:{session.session_id}] TTS playback done timeout ({dynamic_timeout:.1f}s), proceeding anyway")
            logger.info(f"[Session:{session.session_id}] TTS playback done, fsm={fsm.get()}, closed={session._closed}")
            _log_perf_report(session, result, _pipeline, session.runtime.asr_full_text)

            # 检查是否有 WeChat 回复待发送
            if result and result.full_text:
                await self._send_wechat_reply_if_needed(result.full_text)

            # 计费：本轮对话结束（TTS 播放完成），保存记录并重置累计器
            await session.billing.save_record_and_reset()

            if not session._closed and fsm.get() != SessionState.IDLE:
                await self._start_next_asr()
            elif fsm.get() == SessionState.IDLE:
                logger.info(f"[Session:{session.session_id}] Session is IDLE, skip next ASR")
        except asyncio.CancelledError:
            logger.info(f"[Session:{session.session_id}] _on_tts_complete cancelled")
            pass
        except Exception as e:
            logger.error(f"[TTS] Complete callback error: {e}", exc_info=True)
            # 即使出错也尝试启动下一轮 ASR，避免卡死
            try:
                if not session._closed and fsm.get() != SessionState.IDLE:
                    if self._new_wake_pending:
                        logger.info(f"[Session:{session.session_id}] 新一轮唤醒流程进行中，跳过恢复启动 ASR")
                        return
                    logger.info(f"[Session:{session.session_id}] Attempting recovery: starting next ASR after error")
                    await self._start_next_asr()
            except Exception as e2:
                logger.error(f"[Session:{session.session_id}] Recovery failed: {e2}")

