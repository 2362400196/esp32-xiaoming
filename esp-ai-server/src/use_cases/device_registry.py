from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import socket
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, List, Optional

from src.infrastructure.config import get_settings, SID_TTS, SID_CONNECTED, SCREEN_WIDTH, SCREEN_HEIGHT
from src.infrastructure.logging import get_logger
from src.interfaces.tts_gateways import create_tts_gateway, VoiceGenerator
from src.domain.services import MemoryService
from src.domain.entities import Conversation, Message
from src.use_cases.session_fsm import SessionState
from src.use_cases.sdk.events import publish, EVENT_DEVICE_ONLINE, EVENT_DEVICE_OFFLINE

logger = get_logger(__name__)

_CHUNK_SIZE = 2048


class DeviceRegistry:
    """设备注册表（优化支持500+并发）- 使用高效索引和无锁读取"""
    
    def __init__(self):
        self._devices: dict = {}
        self._mac_index: dict = {}
        self._lock = asyncio.Lock()
        self._stats = {
            "register_count": 0,
            "unregister_count": 0,
            "lookup_count": 0,
        }
        # 后台任务引用（防止被 GC 回收导致协程中途取消且无告警）
        self._bg_tasks: set = set()

    async def register(
        self,
        device_id: str,
        channel,
        session,
        fsm,
        user_config=None,
        asr_client=None,
        tool_manager=None,
        mac: str = "",
        firmware_version: str = "",
    ):
        async with self._lock:
            # 清理旧条目（设备重连时避免资源泄漏）
            old_device = self._devices.get(device_id)
            if old_device:
                logger.info(f"[DeviceRegistry] 设备 {device_id} 重连，清理旧条目")
                old_mac = old_device.get("mac", "")
                if old_mac and old_mac in self._mac_index:
                    del self._mac_index[old_mac]
                # 异步清理旧资源（不阻塞注册）
                try:
                    old_session = old_device.get("session")
                    if old_session and hasattr(old_session, "cancel_event"):
                        old_session.cancel_event.set()
                    old_tm = old_device.get("tool_manager")
                    if old_tm and hasattr(old_tm, "cleanup"):
                        _t = asyncio.create_task(old_tm.cleanup())
                        self._bg_tasks.add(_t)
                        _t.add_done_callback(self._bg_tasks.discard)
                    old_channel = old_device.get("channel")
                    if old_channel:
                        _t2 = asyncio.create_task(old_channel.close())
                        self._bg_tasks.add(_t2)
                        _t2.add_done_callback(self._bg_tasks.discard)
                except Exception as e:
                    logger.warning(f"[DeviceRegistry] 清理旧设备资源异常: {e}")

            self._devices[device_id] = {
                "channel": channel,
                "session": session,
                "fsm": fsm,
                "user_config": user_config,
                "asr_client": asr_client,
                "tool_manager": tool_manager,
                "llm_processor": getattr(session, "llm_processor", None),
                "mac": mac,
                "firmware_version": firmware_version,
                "ota_updating": False,
                "ota_progress": 0.0,
                "pending_ota": None,
                "last_ota_url": "",
                "pending_wifi_config": None,
                "pending_instruct": None,
                "register_time": time.time(),
            }
            if mac:
                self._mac_index[mac] = device_id
            self._stats["register_count"] += 1
            logger.info(f"[DeviceRegistry] 已注册设备: key={device_id} mac={mac or device_id}, firmware={firmware_version}, 总数: {len(self._devices)}")

        # 注册成功 → 发布设备上线事件（publish 内部容错，不影响注册流程）
        publish(EVENT_DEVICE_ONLINE, device_id=device_id)

    async def unregister(self, device_id: str, session=None):
        """注销设备。

        Args:
            device_id: 设备 key
            session: 调用方持有的 session 对象，用于属主校验。
                     传入时与注册表中当前条目的 session 做 ``is`` 比对：
                     不一致说明是旧会话迟到的清理（重连竞态），跳过注销，避免误杀新会话；
                     传 None 保持旧行为（无条件注销，兼容其他调用点）。
        """
        async with self._lock:
            if device_id not in self._devices:
                return

            device = self._devices[device_id]
            mac = device.get("mac", "")

            # 属主校验：注册表中的 session 已被新会话覆盖 → 旧会话迟到的 cleanup，跳过
            if session is not None and device.get("session") is not session:
                logger.debug(
                    f"[DeviceRegistry] 设备 {device_id} 已被新会话接管，跳过旧会话的注销"
                )
                return

            logger.info(f"[DeviceRegistry] 开始注销设备: key={device_id}")

            try:
                session = device.get("session")
                if session and hasattr(session, "cancel_event"):
                    session.cancel_event.set()

                # 关闭设备的 LLM 网关（释放 AsyncOpenAI 的 SSL 连接，
                # 避免进程退出时 GC 在已关闭的事件循环上报错）
                llm_processor = None
                if session is not None:
                    llm_processor = getattr(session, "llm_processor", None)
                if llm_processor is not None and hasattr(llm_processor, "aclose"):
                    try:
                        await asyncio.wait_for(llm_processor.aclose(), timeout=2.0)
                    except Exception as e:
                        logger.debug(f"[DeviceRegistry] 关闭 LLM 网关异常: {e}")

                tool_manager = device.get("tool_manager")
                if tool_manager and hasattr(tool_manager, "cleanup"):
                    try:
                        await asyncio.wait_for(tool_manager.cleanup(), timeout=2.0)
                    except Exception as e:
                        logger.warning(f"[DeviceRegistry] 关闭 MCP 客户端异常: {e}")

                channel = device.get("channel")
                if channel:
                    await channel.close()

            except Exception as e:
                logger.warning(f"[DeviceRegistry] 清理设备资源时异常: {e}")
            finally:
                del self._devices[device_id]
                if mac and mac in self._mac_index:
                    del self._mac_index[mac]
                self._stats["unregister_count"] += 1
                logger.info(f"[DeviceRegistry] 已注销设备: {device_id}, 剩余: {len(self._devices)}")
                # 实际删除后 → 发布设备离线事件（publish 内部容错）
                publish(EVENT_DEVICE_OFFLINE, device_id=device_id)

    def get(self, device_id: str):
        self._stats["lookup_count"] += 1
        return self._devices.get(device_id)

    def get_by_mac(self, mac: str):
        self._stats["lookup_count"] += 1
        api_key = self._mac_index.get(mac)
        if api_key:
            return self._devices.get(api_key)
        return self._devices.get(mac)

    def resolve(self, device_id: str):
        self._stats["lookup_count"] += 1
        api_key = self._mac_index.get(device_id)
        if api_key:
            return self._devices.get(api_key)
        return self._devices.get(device_id)

    def has(self, device_id: str) -> bool:
        return device_id in self._devices

    def get_all_ids(self) -> list[str]:
        return list(self._devices.keys())

    def count(self) -> int:
        return len(self._devices)

    def get_all_sessions(self):
        return [d["session"] for d in self._devices.values() if d.get("session")]

    async def close_all(self) -> None:
        """关闭所有设备连接（服务端退出时调用，避免残留 WebSocket/SSL 连接）。"""
        devices = list(self._devices.values())
        for d in devices:
            try:
                session = d.get("session")
                if session and hasattr(session, "cancel_event"):
                    session.cancel_event.set()
                # 关闭设备的 LLM 网关（释放 AsyncOpenAI 的 SSL 连接）
                llm_processor = getattr(session, "llm_processor", None) if session else None
                if llm_processor is not None and hasattr(llm_processor, "aclose"):
                    try:
                        await asyncio.wait_for(llm_processor.aclose(), timeout=2.0)
                    except Exception as e:
                        logger.debug(f"[DeviceRegistry] 关闭 LLM 网关异常: {e}")
                channel = d.get("channel")
                if channel and hasattr(channel, "close"):
                    await channel.close()
            except Exception as e:
                logger.warning(f"[DeviceRegistry] 关闭设备连接异常: {e}")
        self._devices.clear()
        self._mac_index.clear()
        if devices:
            logger.info(f"[DeviceRegistry] 已关闭 {len(devices)} 个设备连接")
    
    def get_stats(self) -> dict:
        return {
            "total_devices": len(self._devices),
            "mac_index_size": len(self._mac_index),
            **self._stats,
        }

    def update_ota_progress(self, device_id: str, progress: float):
        device = self.resolve(device_id)
        if device:
            device["ota_progress"] = progress
            if progress >= 100:
                device["ota_updating"] = False
            logger.debug(f"[OTA] 设备 {device_id} 升级进度: {progress}%")

    def set_ota_updating(self, device_id: str, updating: bool):
        device = self.resolve(device_id)
        if device:
            device["ota_updating"] = updating
            if updating:
                device["ota_progress"] = 0.0
            logger.info(f"[OTA] 设备 {device_id} OTA状态: {'升级中' if updating else '空闲'}")

    def set_pending_ota(self, device_id: str, ota_command: Optional[dict]):
        device = self.resolve(device_id)
        if device:
            device["pending_ota"] = ota_command
            if ota_command:
                logger.info(f"[OTA] 设备 {device_id} 已设置待推送OTA: {ota_command}")
            else:
                logger.info(f"[OTA] 设备 {device_id} 已清除待推送OTA")

    def get_pending_ota(self, device_id: str) -> Optional[dict]:
        device = self.resolve(device_id)
        if device:
            return device.get("pending_ota")
        return None

    def set_pending_wifi_config(self, device_id: str, config: Optional[dict]):
        device = self.resolve(device_id)
        if device:
            device["pending_wifi_config"] = config
            if config:
                logger.info(f"[Wifi] 设备 {device_id} 已设置待推送WiFi配置: {config.get('wifi_name', '')}")
            else:
                logger.info(f"[Wifi] 设备 {device_id} 已清除待推送WiFi配置")

    def get_pending_wifi_config(self, device_id: str) -> Optional[dict]:
        device = self.resolve(device_id)
        if device:
            return device.get("pending_wifi_config")
        return None

    def set_pending_instruct(self, device_id: str, command: Optional[dict]):
        device = self.resolve(device_id)
        if device:
            device["pending_instruct"] = command
            if command:
                logger.info(f"[Instruct] 设备 {device_id} 已设置待推送指令: {command.get('command_id', '')}")
            else:
                logger.info(f"[Instruct] 设备 {device_id} 已清除待推送指令")

    def get_pending_instruct(self, device_id: str) -> Optional[dict]:
        device = self.resolve(device_id)
        if device:
            return device.get("pending_instruct")
        return None
