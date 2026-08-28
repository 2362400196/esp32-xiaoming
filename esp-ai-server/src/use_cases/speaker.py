from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import socket
import uuid
from dataclasses import dataclass, field
from typing import Any, List, Optional

from src.infrastructure.config import get_settings, SID_TTS, SID_CONNECTED, SCREEN_WIDTH, SCREEN_HEIGHT
from src.infrastructure.logging import get_logger
from src.infrastructure.task_manager import background_task
from src.interfaces.tts_gateways import create_tts_gateway, VoiceGenerator
from src.domain.services import MemoryService
from src.domain.entities import Conversation, Message
from src.use_cases.session_fsm import SessionState

logger = get_logger(__name__)

_CHUNK_SIZE = 2048


class Speaker:
    def __init__(self, device_registry: DeviceRegistry, wake_audio_manager: WakeAudioManager):
        self._registry = device_registry
        self._wake_audio = wake_audio_manager
        # 后台任务引用（防止被 GC 回收导致协程中途取消且无告警）
        self._bg_tasks: set = set()

    async def _speak_core(self, channel, fsm, text, user_config=None, device_id=None, need_wakeup=False):
        if not channel or not channel.connected:
            logger.warning("[Speak] 设备通道未连接")
            return False

        logger.info(f"[Speak] 当前状态: {fsm.get()}")
        await fsm.set(SessionState.TTS)

        label = f"device={device_id}" if device_id else "direct"
        logger.info(f"[Speak] 开始合成语音: {label}, text={text[:30]}...")

        volc_tts = None
        session = None
        try:
            # 优先使用 user_config 中的 TTS 配置，回退到全局配置
            _tts_cfg = None
            _settings = get_settings()
            if user_config and hasattr(user_config, 'tts_config') and user_config.tts_config:
                _u = user_config.tts_config
                _tts_cfg = {
                    "api_key": _u.get("api_key", _settings.tts.api_key),
                    "resource_id": _u.get("resource_id") or _settings.tts.resource_id or "",
                    "voice_type": _u.get("voice_type", _settings.tts.voice_type or "BV001_streaming"),
                    "sample_rate": _settings.tts.sample_rate or 24000,
                    "speed_ratio": _u.get("speed_ratio", _settings.tts.speed_ratio or 1.0),
                    "volume_ratio": _u.get("volume_ratio", _settings.tts.volume_ratio or 1.0),
                    "pitch_ratio": _u.get("pitch_ratio", _settings.tts.pitch_ratio or 1.0),
                    "enable_pool": _settings.tts.enable_pool,
                }
            volc_tts = create_tts_gateway(config=_tts_cfg)
            session = await volc_tts.create_session()

            if not session:
                logger.error("[Speak] TTS会话创建失败")
                return False

            # 先合成语音，确认能产生音频
            vg = self._wake_audio.voice_generator
            audio_chunks = []
            async for chunk in session.synthesize_audio(text):
                if chunk:
                    audio_chunks.append(chunk)
                    if len(audio_chunks) >= 500:
                        break  # 防止内存溢出

            logger.info(f"[Speak] TTS 合成完成，共 {len(audio_chunks)} 个音频块")

            if len(audio_chunks) == 0:
                logger.error("[Speak] TTS 合成未产生任何音频数据，跳过播放")
                await session.close()
                session = None  # 标记已关闭
                await volc_tts.close()
                volc_tts = None  # 标记已关闭
                return False

            # TTS 成功，再发送消息到设备播放
            if need_wakeup:
                await channel.send_json({"type": "session_start", "session_id": SID_CONNECTED})
                await asyncio.sleep(0.1)
                await channel.send_json({"type": "session_status", "status": "iat_start"})
                await asyncio.sleep(0.1)

            await channel.send_json({"type": "instruct", "command_id": "on_iat_cb", "data": text})
            await asyncio.sleep(0.1)
            await channel.send_json({"type": "play_audio", "tts_task_id": SID_TTS})
            await asyncio.sleep(0.1)
            await channel.send_json({"type": "session_status", "status": "tts_chunk_start"})
            await asyncio.sleep(0.1)

            for chunk in audio_chunks:
                frame = vg.make_tts_frame(SID_TTS, chunk, "00")
                await channel.send_bytes(frame)
                await asyncio.sleep(0.02)

            await channel.send_bytes(vg.make_end_frame(SID_TTS))
            await asyncio.sleep(0.1)
            await channel.send_json({"type": "session_status", "status": "tts_real_end"})

            await session.close()
            session = None  # 标记已关闭
            await volc_tts.close()
            volc_tts = None  # 标记已关闭

            logger.info(f"[Speak] 已完成: {text[:30]}...")
            return True

        except Exception as e:
            logger.error(f"[Speak] 播放失败: {e}")
            try:
                vg = self._wake_audio.voice_generator
                await channel.send_bytes(vg.make_end_frame(SID_TTS))
                await channel.send_json({"type": "session_status", "status": "tts_real_end"})
            except Exception as e2:
                logger.debug(f"[Speak] 发送结束帧失败: {e2}")
            return False
        finally:
            # 确保异常路径下 TTS 资源也被释放
            if session is not None:
                try:
                    await session.close()
                except Exception:
                    pass
            if volc_tts is not None:
                try:
                    await volc_tts.close()
                except Exception:
                    pass

    def _resolve_device(self, device_id: str):
        return self._registry.get_by_mac(device_id) or self._registry.get(device_id)

    async def speak(self, device_id, text, user_config=None, need_wakeup=False):
        device = self._resolve_device(device_id)
        if not device:
            logger.warning(f"[Speak] 设备未连接: {device_id}")
            return False

        return await self._speak_core(
            device["channel"],
            device["fsm"],
            text,
            user_config=device.get("user_config") or user_config,
            device_id=device_id,
            need_wakeup=need_wakeup,
        )

    async def speak_direct(self, channel, session, fsm, text, user_config=None, need_wakeup=False):
        return await self._speak_core(
            channel,
            fsm,
            text,
            user_config=user_config,
            need_wakeup=need_wakeup,
        )

    async def speak_all(self, text, user_config=None, need_wakeup=False):
        device_ids = self._registry.get_all_ids()
        if not device_ids:
            logger.warning("[Speak] 无设备连接")
            return

        for device_id in device_ids:
            await self.speak(device_id, text, user_config=user_config, need_wakeup=need_wakeup)

    async def wakeup(self, device_id):
        settings = get_settings()
        device = self._resolve_device(device_id)
        if not device:
            logger.warning(f"[Wakeup] 设备未连接: {device_id}")
            return False

        channel = device["channel"]
        session = device["session"]
        fsm = device["fsm"]
        user_config = device.get("user_config")

        if not channel or not channel.connected:
            logger.warning(f"[Wakeup] 设备通道未连接: {device_id}")
            return False

        logger.info(f"[Wakeup] 当前状态: {fsm.get()}")

        try:
            await channel.send_json({"type": "session_start", "session_id": SID_CONNECTED})
            await asyncio.sleep(0.1)

            enable_audio = True
            if user_config and hasattr(user_config, 'wakeup_config') and user_config.wakeup_config:
                enable_audio = user_config.wakeup_config.get('enabled', settings.wakeup.enable_audio)
            else:
                enable_audio = settings.wakeup.enable_audio
            if enable_audio:
                session._wake_audio_played.clear()
                played = await self._wake_audio.play(channel, user_config=user_config)
                if self._wake_audio._get_wakeup_cfg(user_config, 'play_enabled', settings.wakeup.audio_play_enabled):
                    if not played:
                        # TTS 合成失败/无音频：跳过等待，避免 10s 超时延迟
                        logger.warning("[Wakeup] Wake audio unavailable, skipping wait")
                        session._wake_audio_played.set()
                    try:
                        await asyncio.wait_for(session._wake_audio_played.wait(), timeout=10.0)
                    except asyncio.TimeoutError:
                        logger.warning("[Wakeup] 等待 wake 音频播放完成超时(10s)")
                else:
                    session._wake_audio_played.set()

            await channel.send_json({"type": "session_status", "status": "iat_start"})
            await asyncio.sleep(0.1)

            background_task(session.start_auto_conversation(), name="auto_conversation")
            logger.info("[Wakeup] 唤醒完成，ASR 已启动")
            return True

        except Exception as e:
            logger.error(f"[Wakeup] 唤醒失败: {e}")
            return False

    async def wakeup_all(self):
        device_ids = self._registry.get_all_ids()
        if not device_ids:
            logger.warning("[Wakeup] 无设备连接")
            return

        for device_id in device_ids:
            await self.wakeup(device_id)

    async def stop(self, device_id):
        device = self._resolve_device(device_id)
        if not device:
            logger.warning(f"[Stop] 设备未连接: {device_id}")
            return False

        channel = device["channel"]
        session = device["session"]
        fsm = device["fsm"]

        if not channel or not channel.connected:
            logger.warning(f"[Stop] 设备通道未连接: {device_id}")
            return False

        logger.info(f"[Stop] 当前状态: {fsm.get()}")

        try:
            session.runtime.asr_processed = True
            await session.drain_asr()

            if session.tts_playing:
                logger.info("[Stop] TTS 正在播放，强制中断")
                await session.interrupt()

            session.cancel_event.set()

            await fsm.set(SessionState.IDLE)
            await channel.send_json({"type": "session_stop_ack", "session_id": SID_CONNECTED})
            await asyncio.sleep(0.05)
            await channel.send_json({"type": "session_status", "status": "session_end"})
            await asyncio.sleep(0.05)
            await channel.send_text("session_end")

            logger.info(f"[Stop] 设备已进入待机: {device_id}")
            return True

        except Exception as e:
            logger.error(f"[Stop] 停止失败: {e}")
            return False

    async def stop_all(self):
        device_ids = self._registry.get_all_ids()
        if not device_ids:
            logger.warning("[Stop] 无设备连接")
            return

        logger.info(f"[Stop] 停止 {len(device_ids)} 台设备")
        for device_id in device_ids:
            await self.stop(device_id)

    async def register_device(
        self,
        device_id,
        channel,
        session,
        fsm,
        user_config=None,
        asr_client=None,
        mac: str = "",
        firmware_version: str = "",
    ):
        await self._registry.register(
            device_id,
            channel,
            session,
            fsm,
            user_config=user_config,
            asr_client=asr_client,
            mac=mac,
            firmware_version=firmware_version,
        )

    def unregister_device(self, device_id):
        self._registry.unregister(device_id)

    def get_device(self, device_id):
        return self._resolve_device(device_id)

    def get_all_devices(self):
        return self._registry.get_all_ids()

