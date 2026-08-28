"""
alarm_manager.py - 闹钟和提醒管理器（DB 持久化）
"""
from __future__ import annotations

import asyncio
import calendar
import json
import os
from datetime import datetime, timedelta
from typing import Any, Optional

from src.infrastructure.logging import get_logger
from src.infrastructure.task_manager import background_task
from src.infrastructure.db.repositories.growth_repositories import AlarmRepository
from src.use_cases._plugin_helpers import http_request, play_music_url

logger = get_logger("alarm")


class AlarmItem:
    """一个闹钟或提醒"""

    def __init__(
        self,
        alarm_id: str,
        device_key: str,
        alarm_type: str,  # "alarm" or "reminder"
        trigger_at: datetime,
        text: str = "",
        repeat: str = "once",  # once / daily / weekly / monthly
        created_at: Optional[datetime] = None,
    ):
        self.alarm_id = alarm_id
        self.device_key = device_key
        self.alarm_type = alarm_type
        self.trigger_at = trigger_at
        self.text = text
        self.repeat = repeat
        self.created_at = created_at or datetime.now()

    def is_expired(self) -> bool:
        return datetime.now() >= self.trigger_at

    def next_trigger(self) -> Optional[datetime]:
        """计算下一次触发时间（重复模式）"""
        if self.repeat == "once":
            return None
        now = datetime.now()
        if self.repeat == "daily":
            next_time = self.trigger_at.replace(
                year=now.year, month=now.month, day=now.day
            )
            if next_time <= now:
                next_time += timedelta(days=1)
            return next_time
        elif self.repeat == "weekly":
            # 以原触发时间的 weekday 为基准，保持周几语义：
            # 先取今天的日期 + 原触发时刻，再对齐到原触发时间的 weekday
            days_ahead = (self.trigger_at.weekday() - now.weekday()) % 7
            next_time = self.trigger_at.replace(
                year=now.year, month=now.month, day=now.day
            ) + timedelta(days=days_ahead)
            if next_time <= now:
                next_time += timedelta(weeks=1)
            return next_time
        elif self.repeat == "monthly":
            # 原始日 day=31 而目标月只有 30 天时 replace 会抛 ValueError，
            # 这里 clamp 到该月最后一天，避免闹钟循环卡死
            day = self.trigger_at.day
            last_day = calendar.monthrange(now.year, now.month)[1]
            next_time = self.trigger_at.replace(
                year=now.year, month=now.month, day=min(day, last_day)
            )
            if next_time <= now:
                month = next_time.month + 1
                year = next_time.year + (month - 1) // 12
                month = (month - 1) % 12 + 1
                last_day = calendar.monthrange(year, month)[1]
                next_time = self.trigger_at.replace(
                    year=year, month=month, day=min(day, last_day)
                )
            return next_time
        return None


class AlarmManager:
    """全局闹钟/提醒管理器（DB 持久化）"""

    def __init__(self):
        self._alarms: dict[str, AlarmItem] = {}
        self._task: Optional[asyncio.Task] = None
        self._device_registry = None
        self._repo = AlarmRepository()

    async def load_from_db(self) -> None:
        """启动时从 DB 加载所有闹钟到内存"""
        try:
            rows = await self._repo.list_all()
            now = datetime.now()
            for row in rows:
                trigger_at = datetime.fromtimestamp(row["trigger_at"])
                # 跳过已过期的单次闹钟
                if trigger_at <= now and row["repeat"] == "once":
                    continue
                item = AlarmItem(
                    alarm_id=row["alarm_id"],
                    device_key=row["device_key"],
                    alarm_type=row["alarm_type"],
                    trigger_at=trigger_at,
                    text=row.get("text", ""),
                    repeat=row.get("repeat", "once"),
                )
                self._alarms[item.alarm_id] = item
            if rows:
                logger.info(f"[Alarm] 从 DB 加载了 {len(self._alarms)} 个闹钟")
        except Exception as e:
            logger.warning(f"[Alarm] DB 加载失败（首次启动时正常）: {e}")

    def set_registry(self, registry):
        self._device_registry = registry

    def add_alarm(self, item: AlarmItem) -> str:
        self._alarms[item.alarm_id] = item
        # 写入 DB：add_alarm 是同步接口（调用方未 await），无法直接 await；
        # 通过 task_manager 包装持有引用，失败时记 ERROR 日志
        background_task(self._repo.upsert({
            "alarm_id": item.alarm_id,
            "device_key": item.device_key,
            "alarm_type": item.alarm_type,
            "trigger_at": item.trigger_at.timestamp(),
            "text": item.text,
            "repeat": item.repeat,
            "created_at": item.created_at.timestamp(),
        }), name="alarm_db_upsert")
        logger.info(
            f"[Alarm] 已添加{alarm_type_text(item.alarm_type)}: "
            f"{item.alarm_id}, 触发时间={item.trigger_at}, 重复={item.repeat}"
        )
        return item.alarm_id

    def remove_alarm(self, alarm_id: str) -> bool:
        if alarm_id in self._alarms:
            del self._alarms[alarm_id]
            # 从 DB 删除：同 add_alarm，通过 task_manager 包装，失败记 ERROR 日志
            background_task(self._repo.delete(alarm_id), name="alarm_db_delete")
            logger.info(f"[Alarm] 已移除: {alarm_id}")
            return True
        return False

    def list_alarms(self, device_key: str = "") -> list[dict]:
        result = []
        for item in self._alarms.values():
            if device_key and item.device_key != device_key:
                continue
            result.append(
                {
                    "id": item.alarm_id,
                    "type": item.alarm_type,
                    "trigger_at": item.trigger_at.isoformat(),
                    "text": item.text,
                    "repeat": item.repeat,
                }
            )
        return result

    async def start(self):
        """启动后台检查协程"""
        if self._task is not None:
            return
        self._task = background_task(self._check_loop(), name="alarm_check_loop")
        logger.info("[Alarm] 后台检查已启动 (task=%s)", hex(id(self._task)))

    async def stop(self):
        if self._task:
            self._task.cancel()
            self._task = None
            logger.info("[Alarm] 后台检查已停止")

    async def _check_loop(self):
        """每秒检查一次到期的闹钟/提醒"""
        logger.info("[Alarm] 检查循环开始运行")
        while True:
            try:
                await self._check()
            except asyncio.CancelledError:
                logger.info("[Alarm] 检查循环被取消")
                break
            except Exception as e:
                logger.error(f"[Alarm] 检查异常: {e}")
            await asyncio.sleep(1)

    async def _check(self):
        now = datetime.now()
        expired_items = [
            item for item in self._alarms.values() if item.is_expired()
        ]
        if expired_items:
            logger.info(f"[Alarm] 检查到 {len(expired_items)} 个到期项")
        for item in expired_items:
            try:
                await self._trigger(item)
            except Exception as e:
                logger.error(f"[Alarm] 触发失败 {item.alarm_id}: {e}")

            # 重复模式：计算下一次触发
            next_time = item.next_trigger()
            if next_time:
                item.trigger_at = next_time
                # 直接 await 更新 DB 中的触发时间（持久化失败由 _check_loop 记 ERROR 日志）
                await self._repo.upsert({
                    "alarm_id": item.alarm_id,
                    "device_key": item.device_key,
                    "alarm_type": item.alarm_type,
                    "trigger_at": next_time.timestamp(),
                    "text": item.text,
                    "repeat": item.repeat,
                    "created_at": item.created_at.timestamp(),
                })
                logger.info(
                    f"[Alarm] {item.alarm_id} 下次触发: {next_time}"
                )
            else:
                del self._alarms[item.alarm_id]
                # 直接 await 从 DB 删除已过期的单次闹钟
                await self._repo.delete(item.alarm_id)

    async def _trigger(self, item: AlarmItem):
        """触发闹钟或提醒（语音 + 微信双通道）"""
        if not self._device_registry:
            logger.warning(f"[Alarm] 设备注册表未设置，无法触发 {item.alarm_id}")
            return

        logger.info(f"[Alarm] 触发 {item.alarm_type}: {item.alarm_id} (device_key={item.device_key})")

        # 1. 先发送微信提醒（不依赖设备在线状态，确保提醒不丢失）
        await self._send_wechat_notification(item)

        # 2. 检查设备是否在线，在线则播放语音/音乐
        device = self._device_registry.resolve(item.device_key)
        if not device:
            logger.warning(f"[Alarm] 设备不在线: {item.device_key}（微信提醒已尝试发送）")
            return

        channel = device.get("channel")
        if not channel or not channel.connected:
            logger.warning(f"[Alarm] 设备通道未连接: {item.device_key}（微信提醒已尝试发送）")
            return

        if item.alarm_type == "reminder":
            # 提醒：合成 TTS 并直接发送音频帧，不经过 session_start/iat_start
            logger.info(f"[Alarm] 合成并发送 TTS: {item.text}")
            await self._play_tts(channel, device, item.text)

        elif item.alarm_type == "alarm":
            # 闹钟：优先音乐服务（音乐插件已启用且配置了服务地址），否则降级为 TTS 语音播报
            music_ok = self._is_music_plugin_enabled(device)
            music_api_url = self._resolve_music_api_url(device) if music_ok else ""
            if music_ok and music_api_url:
                await self._play_alarm_music(channel, device, item, music_api_url)
            else:
                reason = "音乐插件未启用" if not music_ok else "音乐服务未配置"
                logger.info(f"[Alarm] {reason}，闹钟降级为 TTS 语音播报: {item.alarm_id}")
                now = datetime.now()
                await self._play_tts(channel, device, f"起床啦，现在是{now.strftime('%H点%M分')}，该起床啦")

        elif item.alarm_type == "sleep_timer":
            # 睡眠定时器：停止一切活动，进入休息状态
            logger.info(f"[Alarm] 睡眠定时器触发，停止所有活动: {item.alarm_id}")
            try:
                # 1. 停止网络音乐播放（network_audio 任务 + 扬声器缓冲区）
                await channel.send_json({
                    "type": "instruct",
                    "command_id": "stop_music",
                    "data": "",
                })
                await asyncio.sleep(0.1)

                # 2. 清理歌词界面和音乐播放器 UI
                await channel.send_json({
                    "type": "instruct",
                    "command_id": "music_end",
                    "data": "",
                })
                await asyncio.sleep(0.05)

                # 3. 清除工具状态显示
                await channel.send_json({
                    "type": "instruct",
                    "command_id": "on_tool_status",
                    "data": "",
                })

                # 4. 发送 session_end，设备将停止扬声器、恢复唤醒词检测
                await channel.send_json({"type": "session_status", "status": "session_end"})
                await channel.send_text("session_end")

                logger.info(f"[Alarm] 睡眠定时器: 已发送停止指令到设备 {item.device_key[:16]}")
            except Exception as e:
                logger.error(f"[Alarm] 睡眠定时器触发失败: {e}")

    async def _send_wechat_notification(self, item: AlarmItem) -> None:
        """发送微信提醒消息（设备离线时也能送达）

        通过 WeChatBindingManager 查找设备绑定的微信会话，
        若设备已绑定微信且微信 Bot 已配置，则发送文本提醒。
        未绑定或未配置时静默跳过，不影响语音提醒流程。
        """
        try:
            from src.infrastructure.web import get_app
            from src.use_cases.wechat_binding import get_wechat_binding_manager

            app = get_app()
            if not app or not hasattr(app, 'state'):
                return

            bot = getattr(app.state, 'wechat_bot', None)
            if not bot or not bot.state.configured:
                return  # 微信未配置，静默跳过

            bind_mgr = get_wechat_binding_manager()
            binding = bind_mgr.find_binding(item.device_key)
            if not binding or not binding.wechat_chat_id:
                return  # 设备未绑定微信，静默跳过

            # 根据类型构建消息内容
            trigger_time_str = item.trigger_at.strftime('%H:%M')
            if item.alarm_type == "reminder":
                msg = f"⏰ 提醒（{trigger_time_str}）：{item.text}"
            else:
                msg = f"⏰ 闹钟时间到了（{trigger_time_str}），快起床啦！"

            await bot.send_text(binding.wechat_chat_id, msg)
            logger.info(f"[Alarm] 微信提醒已发送到 {binding.wechat_chat_id[:16]}: {msg[:40]}")
        except Exception as e:
            logger.warning(f"[Alarm] 微信提醒发送失败: {e}")

    def _is_music_plugin_enabled(self, device) -> bool:
        """判断音乐插件（media_player）是否已启用（与 tools_system 白名单语义一致）。

        可选插件需在设备 enabled_plugins 白名单内才生效；
        enabled_plugins 为 None/空 时按无白名单处理（可选插件默认不启用）。
        """
        try:
            from src.infrastructure.plugin_loader import (
                get_loaded_plugins,
                is_optional_plugin,
                is_system_plugin,
            )
            if "media_player" not in get_loaded_plugins():
                return False
            user_config = device.get("user_config") if device else None
            enabled = None
            if user_config and hasattr(user_config, "enabled_plugins"):
                enabled = user_config.enabled_plugins
            enabled_set = set(enabled) if enabled else None
            if is_optional_plugin("media_player") and not is_system_plugin("media_player"):
                if enabled_set is None or "media_player" not in enabled_set:
                    return False
            return True
        except Exception:
            return False

    def _resolve_music_api_url(self, device) -> str:
        """解析音乐服务地址，优先级：media_player 插件 KV 配置 > 设备 music_config > 全局 .env。"""
        # 1. media_player 插件 KV 配置（按设备隔离存储）
        try:
            kv_url = self._read_media_player_kv("api_url", device)
            if kv_url and str(kv_url).strip():
                return str(kv_url).strip()
        except Exception:
            pass
        # 2. 设备 music_config
        try:
            user_config = device.get("user_config") if device else None
            if user_config and hasattr(user_config, "music_config") and user_config.music_config:
                url = (user_config.music_config.get("api_url") or "").strip()
                if url:
                    return url
        except Exception:
            pass
        # 3. 全局 .env
        try:
            from src.infrastructure.config import get_settings
            url = (get_settings().music.api_url or "").strip()
            if url:
                return url
        except Exception:
            pass
        return ""

    def _read_media_player_kv(self, key: str, device) -> Any:
        """读取 media_player 插件在 KV 中的配置（按设备隔离存储）。

        路径：data/plugins/kv/{sanitized_device_id}/media_player.json
        优先按设备 mac/device_id 查找，未命中时扫描所有设备目录回退。
        """
        import re
        root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
        kv_root = os.path.join(root, "data", "plugins", "kv")
        candidates: list[str] = []
        if device:
            mac = device.get("mac") or ""
            if mac:
                candidates.append(re.sub(r'[\\/:*?"<>|]', '-', mac))
            dev_id = device.get("device_id") or ""
            if dev_id:
                candidates.append(re.sub(r'[\\/:*?"<>|]', '-', dev_id))
        for safe_id in candidates:
            path = os.path.join(kv_root, safe_id, "media_player.json")
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        store = json.load(f)
                        if key in store:
                            return store.get(key)
                except (json.JSONDecodeError, OSError):
                    continue
        if os.path.isdir(kv_root):
            for entry in os.listdir(kv_root):
                path = os.path.join(kv_root, entry, "media_player.json")
                if os.path.isfile(path):
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            store = json.load(f)
                            if key in store:
                                return store.get(key)
                    except (json.JSONDecodeError, OSError):
                        continue
        return None

    async def _play_alarm_music(self, channel, device, item: AlarmItem, music_api_url: str) -> None:
        """通过音乐服务搜索并播放闹钟铃声。"""
        try:
            if item.text:
                resp, err = await http_request(
                    "GET", f"{music_api_url}/stream_pcm",
                    params={"song": item.text}, timeout=10,
                )
            else:
                resp, err = await http_request("GET", f"{music_api_url}/random", timeout=10)
            if err:
                raise err
            data = resp.json()
            if not data.get("success"):
                logger.warning(f"[Alarm] 未找到歌曲: {item.text or '随机'}")
                return
            audio_url = data.get("audio_url", "")
            if not audio_url:
                logger.warning(f"[Alarm] 歌曲无音频链接: {data.get('title', item.text or '随机')}")
                return
            result = await play_music_url(
                url=audio_url,
                title=data.get("title", item.text or "随机"),
                artist=data.get("artist", ""),
                duration=data.get("duration", 0),
                device_key=item.device_key,
                lyric_url=data.get("lyric_url", ""),
            )
            logger.info(f"[Alarm] 闹钟铃声: {data.get('title', item.text or '随机')}, SDK 结果: {result}")
        except Exception as e:
            logger.error(f"[Alarm] 搜索歌曲失败: {e}")

    async def _play_tts(self, channel, device, text: str) -> None:
        """合成 TTS 并直接发送音频帧（不经过 session_start/iat_start）。"""
        try:
            from src.infrastructure.config import get_settings
            from src.interfaces.tts_gateways import create_tts_gateway, VoiceGenerator
            settings = get_settings()

            user_config = device.get("user_config")
            _tts_cfg = None
            if user_config and hasattr(user_config, 'tts_config') and user_config.tts_config:
                _u = user_config.tts_config
                _tts_cfg = {
                    "api_key": _u.get("api_key", settings.tts.api_key),
                    "resource_id": _u.get("resource_id") or settings.tts.resource_id or "",
                    "voice_type": _u.get("voice_type", settings.tts.voice_type or "BV001_streaming"),
                    "sample_rate": settings.tts.sample_rate or 24000,
                    "speed_ratio": _u.get("speed_ratio", settings.tts.speed_ratio or 1.0),
                    "volume_ratio": _u.get("volume_ratio", settings.tts.volume_ratio or 1.0),
                    "pitch_ratio": _u.get("pitch_ratio", settings.tts.pitch_ratio or 1.0),
                    "enable_pool": settings.tts.enable_pool,
                }
            volc_tts = create_tts_gateway(config=_tts_cfg)
            tts_session = await volc_tts.create_session()
            if tts_session:
                vg = VoiceGenerator()
                audio_chunks = []
                async for chunk in tts_session.synthesize_audio(text):
                    if chunk:
                        audio_chunks.append(chunk)
                if audio_chunks:
                    await channel.send_json({"type": "play_audio", "tts_task_id": "0010"})
                    await asyncio.sleep(0.1)
                    await channel.send_json({"type": "session_status", "status": "tts_chunk_start"})
                    await asyncio.sleep(0.05)
                    for chunk in audio_chunks:
                        frame = vg.make_tts_frame("0010", chunk, "00")
                        await channel.send_bytes(frame)
                        await asyncio.sleep(0.02)
                    await channel.send_bytes(vg.make_end_frame("0010"))
                    await asyncio.sleep(0.05)
                    await channel.send_json({"type": "session_status", "status": "tts_real_end"})
                    logger.info(f"[Alarm] TTS 音频已发送: {len(audio_chunks)} 帧, {text[:20]}")
                await tts_session.close()
            await volc_tts.close()
        except Exception as e:
            logger.error(f"[Alarm] TTS 播报失败: {e}")


def alarm_type_text(t: str) -> str:
    if t == "alarm":
        return "闹钟"
    elif t == "sleep_timer":
        return "睡眠定时器"
    return "提醒"


# 全局单例
_alarm_manager: Optional[AlarmManager] = None


def get_alarm_manager() -> AlarmManager:
    global _alarm_manager
    if _alarm_manager is None:
        _alarm_manager = AlarmManager()
    return _alarm_manager
