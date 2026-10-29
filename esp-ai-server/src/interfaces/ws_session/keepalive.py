"""WS 会话空闲保活：心跳与 OTA / WiFi / 指令下发。"""
from __future__ import annotations

import asyncio
import time

from src.domain.entities import SessionState
from src.infrastructure.logging import get_logger
from src.infrastructure.web import get_device_registry

logger = get_logger(__name__)


class KeepaliveMixin:
    """空闲保活相关方法。"""

    async def idle_keepalive(self):
        """空闲保活"""
        session = self.session
        fsm = self.fsm
        channel = self.channel
        device_key = self.device_key
        count = 0
        while not session._closed:
            interval = 1 if fsm.get() == SessionState.TTS else 3
            await asyncio.sleep(interval)
            if session._closed:
                break

            # 连接已死（发送循环标记 connected=False）→ 心跳已无法送达，
            # 立即停止并交给 run() 主循环关闭会话，让设备尽快感知并重连
            if not channel.connected:
                logger.warning(f"[Keepalive] {device_key[:8]} 连接已断开，停止心跳")
                break

            registry = get_device_registry()
            if registry:
                pending = registry.get_pending_ota(device_key)
                if pending:
                    try:
                        channel.send_json_nowait(pending)
                        registry.set_ota_updating(device_key, True)
                        registry.set_pending_ota(device_key, None)
                        logger.info(f"[Keepalive] 发送OTA指令: {pending}")
                        continue
                    except Exception as e:
                        logger.error(f"[Keepalive] 发送OTA失败: {e}")

                pending_wifi = registry.get_pending_wifi_config(device_key)
                if pending_wifi:
                    try:
                        channel.send_json_nowait(pending_wifi)
                        registry.set_pending_wifi_config(device_key, None)
                        logger.info(f"[Keepalive] 发送WiFi配置指令: {pending_wifi}")
                        continue
                    except Exception as e:
                        logger.error(f"[Keepalive] 发送WiFi配置失败: {e}")

                pending_instruct = registry.get_pending_instruct(device_key)
                if pending_instruct:
                    try:
                        channel.send_json_nowait(pending_instruct)
                        registry.set_pending_instruct(device_key, None)
                        logger.info(f"[Keepalive] 发送指令: {pending_instruct.get('command_id', '')}")
                        continue
                    except Exception as e:
                        logger.error(f"[Keepalive] 发送指令失败: {e}")

            channel.send_json_nowait({"type": "keepalive", "ts": int(time.time())})
            count += 1
            if count % 10 == 0:
                logger.info(f"[Keepalive] {device_key[:8]}: {count} times")

