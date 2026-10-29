"""WS 会话 ASR 相关方法：识别回调、VAD 结束与 ASR 轮次启动。"""
from __future__ import annotations

import asyncio
import time

from src.domain.entities import SessionState
from src.infrastructure.logging import get_logger
from src.infrastructure.task_manager import background_task

logger = get_logger(__name__)


class AsrMixin:
    """ASR 识别与轮次调度相关方法。"""

    def on_asr_text(self, text: str) -> None:
        """ASR 文本回调"""
        # 注意：空文本（ASR 流结束/静音帧）不覆盖已有识别结果！
        # 否则用户说完话后 ASR 收到结束帧回调空串，把"现在音量多少"覆盖成空，
        # VAD 结束时 final text 为空 → 识别成功却无任何回复（实测 bug）。
        if text:
            self.session.runtime.asr_full_text = text
            self.session.runtime.asr_last_result_time = time.time()
            # 实时下发 ASR 中间结果，屏幕边听边显示（VAD 结束后不再发，避免覆盖 LLM 字幕）
            if not self.session.runtime.asr_processed:
                try:
                    background_task(self._send_iat_partial(text), name="send_iat_partial")
                except RuntimeError:
                    pass

    async def _send_iat_partial(self, text: str) -> None:
        try:
            await self.channel.send_json({"type": "instruct", "command_id": "on_iat_cb", "data": text})
        except Exception as e:
            logger.debug(f"[VAD] 发送 ASR 中间结果失败: {e}")

    async def on_vad_end(self) -> None:
        """VAD 结束回调"""
        session = self.session
        channel = self.channel
        settings = self.settings
        user_config = self.user_config

        async with self._vad_end_lock:
            if session.runtime.asr_processed:
                return
            session.runtime.asr_processed = True

        if self.tts_done_waiter and not self.tts_done_waiter.done():
            self.tts_done_waiter.cancel()
            self.tts_done_waiter = None

        try:
            await channel.send_json({"type": "session_status", "status": "iat_end"})
        except Exception as e:
            logger.warning(f"[VAD] Send iat_end failed: {e}")
            return

        await asyncio.sleep(0.03)
        text = session.runtime.asr_full_text
        logger.info(f"[VAD] ASR final text: {text}")

        await session.drain_asr()
        if not text.strip():
            await session.send_session_end()
            return

        # 计费：累加本次 ASR 音频时长（分钟），火山 ASR 按时长计费
        session.billing.add_asr(session._billing_asr_minutes())

        rate_limit = user_config.rate_limit_rpm if user_config and user_config.rate_limit_rpm is not None else settings.rate_limit.max_rpm
        if rate_limit > 0:
            now = time.time()
            self.call_times = [t for t in self.call_times if now - t < 60]
            if len(self.call_times) >= rate_limit:
                logger.warning(f"[RateLimit] Device exceeded {rate_limit} calls/minute")
                await session.send_session_end()
                return
            self.call_times.append(now)

        try:
            await channel.send_json({"type": "instruct", "command_id": "on_iat_cb", "data": text})
            await asyncio.sleep(0.03)
        except Exception as e:
            logger.warning(f"[VAD] Send instruct failed: {e}")
            return

        session.tts_playback_done.clear()
        self.pipeline_task = background_task(session.run_pipeline(text), name="run_pipeline")
        self.tts_done_waiter = background_task(self._on_tts_complete(), name="tts_complete_waiter")


    async def _start_next_asr(self):
        """启动下一轮 ASR"""
        session = self.session
        fsm = self.fsm
        channel = self.channel
        asr_client = self.asr_client
        if fsm.get() == SessionState.ASR:
            logger.info(f"[Session:{session.session_id}] Already in ASR state, skip")
            return

        if asr_client:
            session.cancel_pre_asr()
            await session.pre_connect_asr()

        await fsm.set(SessionState.ASR)
        self._start_asr_session()
        # 让出事件循环，确保 ASR 任务启动
        await asyncio.sleep(0)
        await channel.send_json({"type": "session_status", "status": "iat_start"})
        logger.info(f"[Session:{session.session_id}] Next round ASR started")


    def _start_asr_session(self) -> None:
        """启动 ASR 会话"""
        session = self.session
        asr_client = self.asr_client
        # 幂等保护：已有活跃 ASR 任务（或正在启动）时跳过重复启动。
        # 防止 _start_next_asr（旧 pipeline 取消触发）与 _do_wake_start（唤醒音频播完触发）
        # 双重启动竞态：旧会话被取消后音频发往已关闭连接，新会话无输入 → 识别空文本断连。
        if self._asr_starting or (session.runtime.asr_task and not session.runtime.asr_task.done()):
            logger.info(f"[Session:{session.session_id}] ASR 已活跃，跳过重复启动")
            return
        self._asr_starting = True
        session.runtime.asr_start_time = time.time()
        session.runtime.asr_last_result_time = None
        session.runtime.asr_full_text = ""
        if asr_client:
            session.runtime.asr_stop_event = asyncio.Event()
            task = background_task(session.start_asr(self.on_asr_text, self.on_vad_end), name="start_asr")
            task.add_done_callback(self._on_asr_start_done)
        else:
            # 无 ASR 客户端：没有启动任务可回调，立即清除标志避免卡死
            self._asr_starting = False
        background_task(session.start_watchdog(self.on_vad_end), name="session_watchdog")

    def _on_asr_start_done(self, task: asyncio.Task) -> None:
        """start_asr 启动任务完成回调，清除同步启动标志"""
        self._asr_starting = False
        if task.cancelled():
            logger.info(f"[Session:{self.session.session_id}] ASR 启动任务已取消")
        elif task.exception():
            logger.warning(f"[Session:{self.session.session_id}] ASR 启动任务异常: {task.exception()}")

