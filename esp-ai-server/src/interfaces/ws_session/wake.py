"""WS 会话唤醒流程：唤醒提示音、等待播放完成与连接问候音频。"""
from __future__ import annotations

import asyncio
import time

from src.domain.entities import SessionState
from src.infrastructure.logging import get_logger
from src.infrastructure.task_manager import background_task
from src.infrastructure.web import get_app

from .helpers import _get_wake_enable_audio

logger = get_logger(__name__)


class WakeMixin:
    """唤醒流程与连接问候音频相关方法。"""

    async def _do_wake_start(self) -> None:
        """唤醒处理"""
        session = self.session
        fsm = self.fsm
        channel = self.channel
        settings = self.settings
        user_config = getattr(self.session, 'user_config', self.user_config)

        # 性能：设备唤醒到用户开口之间有 1-2 秒（唤醒提示音播放），
        # 用这个空档后台预取 prompt 组装素材（LTM 目录/记忆条目/用户画像），
        # 使本轮及后续 60s 内对话的首响延迟不再包含这些 DB 读。
        try:
            from src.use_cases.pipeline import prewarm_prompt_caches
            background_task(
                prewarm_prompt_caches(session.device_id or self.device_key, session.ltm_service),
                name="prompt_prewarm",
            )
        except Exception as e:
            logger.debug(f"[Session:{session.session_id}] prompt 预热启动失败: {e}")

        wam = getattr(get_app().state, 'wake_audio_manager', None)
        wake_ok = True
        try:
            if wam and _get_wake_enable_audio(settings, user_config):
                # 注意：_wake_audio_played 已在 start 命令处理时 clear()

                # 本轮唤醒轮次号，用于防止上一轮迟到的 client_out_audio_over 串扰
                session._wake_audio_round += 1
                current_round = session._wake_audio_round

                try:
                    played = await wam.play(channel, user_config=user_config)
                except Exception as e:
                    logger.warning(f"[Session:{session.session_id}] Wake audio send failed: {e}")
                    # play() 失败时也要 set 事件，否则会话卡死
                    session._wake_audio_played.set()
                    return
                if session._closed:
                    logger.warning(f"[Session:{session.session_id}] Session closed during wake audio, aborting")
                    return
                if not played:
                    # TTS 合成失败/无音频：跳过等待，直接进入 ASR，避免 10s 卡顿
                    logger.warning(f"[Session:{session.session_id}] Wake audio unavailable, skipping wait")
                    session._wake_audio_played.set()
                # 与 play() 内部判定保持一致（user_config 优先），避免播放与等待状态不一致
                play_enabled = wam._get_wakeup_cfg(user_config, 'play_enabled', settings.wakeup.audio_play_enabled)
                if play_enabled:
                    session._waiting_wake_audio = True  # 标记正在等待唤醒音频完成
                    session._wake_audio_expected_round = current_round
                    try:
                        await asyncio.wait_for(session._wake_audio_played.wait(), timeout=10.0)
                    except asyncio.TimeoutError:
                        logger.warning(f"[Session:{session.session_id}] Wake audio wait timeout")
                        wake_ok = False
                    finally:
                        session._waiting_wake_audio = False  # 清除标志
                else:
                    session._wake_audio_played.set()

            if not wake_ok:
                logger.warning(f"[Session:{session.session_id}] Wake audio failed, sending session_end")
                await session.send_session_end()
                return

            if session._closed:
                logger.warning(f"[Session:{session.session_id}] Session closed before ASR start, aborting")
                return

            logger.info(f"[Session:{session.session_id}] Wake audio complete, starting ASR")
            await fsm.set(SessionState.ASR)
            self._start_asr_session()
            # 让出事件循环，确保 ASR 任务启动
            await asyncio.sleep(0)
            try:
                await channel.send_json({"type": "session_status", "status": "iat_start"})
                logger.info(f"[Session:{session.session_id}] iat_start sent to device")
            except Exception as e:
                logger.warning(f"[Session:{session.session_id}] Failed to send iat_start: {e}")
                return
        except asyncio.CancelledError:
            # 被新的 start 命令取消，清理 _waiting_wake_audio 标志
            session._waiting_wake_audio = False
            logger.info(f"[Session:{session.session_id}] Wake start task cancelled")
            raise
        finally:
            # 唤醒流程结束（正常/失败/取消），清除新一轮唤醒标志
            self._new_wake_pending = False


    async def _play_connect_audio(self) -> None:
        """播放连接音频"""
        channel = self.channel
        fsm = self.fsm
        voice_generator = self.voice_generator
        session = self.session
        await channel.send_json({"type": "stc_time", "stc_time": str(int(time.time()))})
        # 性能优化：将 sleep 从 0.3+0.1+0.1+0.1+0.5+0.1=1.2s 压缩到 0.4s
        # 设备端处理这些命令很快，不需要过长等待
        await asyncio.sleep(0.1)
        await channel.send_json({"type": "play_audio", "tts_task_id": "0001"})
        await channel.send_json({"type": "session_status", "status": "tts_chunk_start"})
        await channel.send_bytes(voice_generator.make_end_frame("0001"))
        await channel.send_json({"type": "session_status", "status": "tts_chunk_end"})
        await asyncio.sleep(0.2)
        # 仅在没有活跃会话时发送 session_end，避免与真实会话的 session_end 冲突
        if fsm.get() == SessionState.IDLE:
            await channel.send_json({"type": "session_status", "status": "session_end"})
            await channel.send_text("session_end")
        else:
            logger.info(f"[Session:{session.session_id}] Skip connect audio session_end, session already active (fsm={fsm.get()})")

