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
from src.interfaces.tts_gateways import create_tts_gateway, VoiceGenerator
from src.domain.services import MemoryService
from src.domain.entities import Conversation, Message
from src.use_cases.session_fsm import SessionState

logger = get_logger(__name__)

_CHUNK_SIZE = 2048

# TTS 合成结果的最小有效长度（字节）。
# 火山 TTS 流式合成中途失败（SessionFailed/Error/超时）时可能不抛异常而提前 return，
# 此时已收到的部分音频（截断的 MP3）会被当作完整结果发送，设备端播放极短片段近乎无声。
# 低于该阈值视为合成失败，触发重试。64kbps/24kHz 下 2048 字节 ≈ 0.25s，正常“我在呢”≥8KB。
_MIN_WAKE_AUDIO_BYTES = 2048

# 唤醒音频 TTS 合成总超时（秒）。
# 火山 TTS 连接/合成偶发半开无响应时，若无总超时，ensure_cache 的 _cache_lock
# 会被长时间占用，导致后续所有唤醒都卡在等待锁上（只能靠重启服务端恢复）。
WAKE_AUDIO_SYNTH_TIMEOUT = 15.0


class WakeAudioManager:
    def __init__(self, voice_generator: VoiceGenerator | None = None):
        self._mp3_cache: bytes | None = None
        self._voice_generator = voice_generator or VoiceGenerator()
        self._tts_gateway = None  # 缓存 TTS 网关实例，避免每次新建连接
        self._cache_lock = asyncio.Lock()  # 防止并发 ensure_cache 竞争
        self._cache_config_signature: str | None = None  # 缓存对应的配置签名

    @property
    def voice_generator(self) -> VoiceGenerator:
        return self._voice_generator

    def _get_wakeup_cfg(self, user_config, key: str, default):
        """从 user_config.wakeup_config 取值，回退到 settings.wakeup 全局配置"""
        if user_config and hasattr(user_config, 'wakeup_config') and user_config.wakeup_config:
            return user_config.wakeup_config.get(key, default)
        return default

    def _build_config_signature(self, user_config=None) -> str:
        """根据唤醒音频相关配置生成签名，用于检测配置是否变化"""
        settings = get_settings()
        wake_text = self._get_wakeup_cfg(user_config, 'text', settings.wakeup.text)
        audio_source = self._get_wakeup_cfg(user_config, 'source', settings.wakeup.audio_source)
        # 包含 TTS 语音类型，不同设备可能用不同声音
        voice_type = ""
        if user_config and hasattr(user_config, 'tts_config') and user_config.tts_config:
            voice_type = user_config.tts_config.get("voice_type", "")
        return f"{wake_text}|{audio_source}|{voice_type}"

    async def ensure_cache(self, user_config=None):
        """确保唤醒音频缓存已就绪，加锁防止并发竞争，配置变化时自动重建缓存"""
        settings = get_settings()
        if not self._get_wakeup_cfg(user_config, 'cache_enabled', settings.wakeup.audio_cache_enabled):
            logger.info("[WakeAudio] 缓存已关闭，跳过加载")
            return None

        # 检查配置是否变化：如果缓存对应的配置与当前请求的配置不同，清除旧缓存
        current_signature = self._build_config_signature(user_config)
        if self._mp3_cache is not None and self._cache_config_signature != current_signature:
            logger.info(f"[WakeAudio] 配置已变化 (旧={self._cache_config_signature}, 新={current_signature})，清除旧缓存")
            self._mp3_cache = None
            self._cache_config_signature = None

        if self._mp3_cache is not None:
            return self._mp3_cache

        # 加锁防止多个协程同时合成（如连接初始化预热 + 首次唤醒 play 同时触发）
        async with self._cache_lock:
            # 双重检查：拿到锁后可能已被其他协程填充
            if self._mp3_cache is not None:
                return self._mp3_cache

            mp3_file = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "app", "audio", "dou.mp3",
            )

            audio_source = self._get_wakeup_cfg(user_config, 'source', settings.wakeup.audio_source)
            if audio_source == "file" and os.path.isfile(mp3_file):
                try:
                    with open(mp3_file, "rb") as f:
                        self._mp3_cache = f.read()
                    self._cache_config_signature = current_signature
                    logger.info(f"[WakeAudio] 已加载唤醒音频文件: {mp3_file} ({len(self._mp3_cache)} bytes)")
                except Exception as e:
                    logger.error(f"[WakeAudio] 加载唤醒音频文件失败: {e}")
                    self._mp3_cache = None
            else:
                if audio_source == "file":
                    logger.info(f"[WakeAudio] 唤醒音频文件不存在: {mp3_file}，回退到 TTS 合成")
                else:
                    logger.info("[WakeAudio] 音频来源=tts，使用 TTS 合成")
                self._mp3_cache = await self._tts_synthesize(user_config=user_config)
                if self._mp3_cache is None:
                    # 冷启动/网络波动时 TTS 连接可能不稳，首次失败后重建网关重试一次
                    logger.warning("[WakeAudio] 首次 TTS 合成失败/结果异常，重试一次")
                    self._mp3_cache = await self._tts_synthesize(user_config=user_config)
                if self._mp3_cache is not None:
                    self._cache_config_signature = current_signature
            return self._mp3_cache

    async def _tts_synthesize(self, user_config=None) -> bytes | None:
        settings = get_settings()
        wake_text = self._get_wakeup_cfg(user_config, 'text', settings.wakeup.text)
        logger.info(f"[WakeAudio] TTS 预合成唤醒音频: {wake_text}")

        # 优先使用 user_config 中的 TTS 配置，回退到全局配置
        tts_config = None
        if user_config and hasattr(user_config, 'tts_config') and user_config.tts_config:
            user_tts_cfg = user_config.tts_config
            tts_config = {
                "api_key": user_tts_cfg.get("api_key", settings.tts.api_key),
                "resource_id": user_tts_cfg.get("resource_id") or settings.tts.resource_id or "",
                "voice_type": user_tts_cfg.get("voice_type", settings.tts.voice_type or "BV001_streaming"),
                "sample_rate": settings.tts.sample_rate or 24000,
                "speed_ratio": user_tts_cfg.get("speed_ratio", settings.tts.speed_ratio or 1.0),
                "volume_ratio": user_tts_cfg.get("volume_ratio", settings.tts.volume_ratio or 1.0),
                "pitch_ratio": user_tts_cfg.get("pitch_ratio", settings.tts.pitch_ratio or 1.0),
                "enable_pool": settings.tts.enable_pool,
            }
            logger.info(f"[WakeAudio] 使用设备 TTS 配置: api_key={'***' + tts_config['api_key'][-4:] if tts_config.get('api_key') else 'EMPTY'}, "
                        f"resource_id={tts_config.get('resource_id')}, voice_type={tts_config.get('voice_type')}")
        else:
            logger.warning(f"[WakeAudio] 无设备 TTS 配置，回退到全局配置: api_key={'有' if settings.tts.api_key else '空'}, "
                           f"resource_id={settings.tts.resource_id}, voice_type={settings.tts.voice_type}")

        # 检查 API key 是否有效
        effective_api_key = (tts_config or {}).get("api_key") or settings.tts.api_key
        if not effective_api_key:
            logger.error("[WakeAudio] TTS API key 为空，无法合成唤醒音频")
            return None

        # 复用 TTS 网关实例，避免每次新建 WebSocket 连接
        # 但 api_key / voice_type / resource_id 任一变化都必须重建（否则音色改了
        # 唤醒音频仍用旧网关的旧音色合成）
        need_recreate = False
        if self._tts_gateway is None:
            need_recreate = True
        else:
            _cfg = tts_config or {}
            _gw = self._tts_gateway
            if hasattr(_gw, 'api_key') and _gw.api_key != effective_api_key:
                logger.warning("[WakeAudio] 缓存的 TTS 网关 API key 不匹配，重新创建")
                need_recreate = True
            elif hasattr(_gw, 'voice_type') and _cfg.get("voice_type") and _gw.voice_type != _cfg.get("voice_type"):
                logger.warning(f"[WakeAudio] 缓存的 TTS 网关音色不匹配 (旧={_gw.voice_type}, 新={_cfg.get('voice_type')})，重新创建")
                need_recreate = True
            elif hasattr(_gw, 'resource_id') and _cfg.get("resource_id") and _gw.resource_id != _cfg.get("resource_id"):
                logger.warning(f"[WakeAudio] 缓存的 TTS 网关资源不匹配 (旧={_gw.resource_id}, 新={_cfg.get('resource_id')})，重新创建")
                need_recreate = True

        if need_recreate:
            self._tts_gateway = create_tts_gateway(config=tts_config)
            logger.info("[WakeAudio] TTS 网关已创建/重建")

        volc_tts = self._tts_gateway
        session = None
        try:
            session = await volc_tts.create_session()
            chunks = []

            async def _collect_chunks():
                async for chunk in session.synthesize_audio(wake_text):
                    if chunk:
                        chunks.append(chunk)

            # 合成整体加总超时：避免火山连接半开时无响应导致 _cache_lock 长期占用
            await asyncio.wait_for(_collect_chunks(), timeout=WAKE_AUDIO_SYNTH_TIMEOUT)
            result = b"".join(chunks)
            if len(result) < _MIN_WAKE_AUDIO_BYTES:
                # 截断/异常数据不可用：不缓存，重建网关供重试使用新连接
                logger.error(f"[WakeAudio] TTS 合成结果异常过短: {len(result)} bytes (< {_MIN_WAKE_AUDIO_BYTES})，视为合成失败")
                self._tts_gateway = None
                return None
            logger.info(f"[WakeAudio] TTS 合成完成: {len(result)} bytes")
            return result
        except Exception as e:
            logger.error(f"[WakeAudio] TTS 合成唤醒音频失败: {e}")
            # 合成失败时重置网关，下次重试将创建新连接
            self._tts_gateway = None
            return None
        finally:
            if session is not None:
                try:
                    await session.close()
                except Exception as e:
                    logger.debug(f"[WakeAudio] 关闭 TTS session 异常: {e}")

    async def play(self, channel, user_config=None) -> bool:
        """播放唤醒音频。

        Returns:
            True: 已成功下发音频（设备会回复 client_out_audio_over）
            False: 无可用音频（TTS 合成失败/结果异常/播放被关闭），调用方应跳过等待
        """
        settings = get_settings()
        if not self._get_wakeup_cfg(user_config, 'play_enabled', settings.wakeup.audio_play_enabled):
            logger.info("[WakeAudio] 播放已关闭，跳过")
            return False
        audio_data = await self.ensure_cache(user_config=user_config)
        if not audio_data:
            logger.error("[WakeAudio] 无音频数据，跳过唤醒提示")
            return False

        try:
            await channel.send_json({"type": "play_audio", "tts_task_id": SID_TTS})
            await channel.send_json({"type": "session_status", "status": "tts_chunk_start"})

            _TOTAL = len(audio_data)
            sent = 0
            while sent < _TOTAL:
                chunk = audio_data[sent : sent + _CHUNK_SIZE]
                sent += len(chunk)
                frame = self._voice_generator.make_tts_frame(SID_TTS, chunk, "00")
                await channel.send_bytes(frame)
                await asyncio.sleep(0.02)

            # status="02"：唤醒音频播完即进入 ASR，避免设备恢复唤醒监听产生空窗
            await channel.send_bytes(self._voice_generator.make_end_frame(SID_TTS, status="02"))
            await channel.send_json({"type": "session_status", "status": "tts_real_end"})

            logger.info(f"[WakeAudio] 唤醒音频已发送: {_TOTAL} bytes")
            return True
        except Exception as e:
            logger.error(f"[WakeAudio] 播放唤醒音频失败: {e}")
            return False
    def clear_cache(self):
        self._mp3_cache = None
        self._cache_config_signature = None
        logger.info("[WakeAudio] 唤醒音频缓存已清除")

