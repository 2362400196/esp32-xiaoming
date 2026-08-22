"""
WeChat Binding Manager — 微信绑定关系管理

管理微信用户与 ESP-AI 设备之间的绑定关系，以及通过 WebSocket
向设备发送指令。数据统一存储在 wechat_bot_data.json 中。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Optional

from src.use_cases.wechat_bot import _load_wechat_data, _save_wechat_data

logger = logging.getLogger(__name__)


@dataclass
class WeChatBinding:
    """微信用户与设备的绑定关系"""
    wechat_chat_id: str          # 微信聊天 ID（个人或群）
    wechat_user_id: str          # 微信用户 ID
    device_key: str              # ESP-AI 设备标识
    device_mac: str = ""         # 设备 MAC 地址
    bound_at: float = 0.0        # 绑定时间戳
    wechat_group_id: str = ""    # 群聊 ID（如果是群聊绑定）
    alias: str = ""              # 设备别名


class WeChatBindingManager:
    """微信绑定关系管理器（JSON 持久化）"""

    def __init__(self):
        self._bindings: dict[str, WeChatBinding] = {}  # device_key → WeChatBinding
        self._by_wechat: dict[str, str] = {}            # wechat_chat_id → device_key
        self._by_group: dict[str, str] = {}             # wechat_group_id → device_key
        self._load()

    # ── 持久化 ──────────────────────────────

    def _load(self) -> None:
        """从统一数据文件加载绑定关系。"""
        if self._bindings:
            return
        try:
            data = _load_wechat_data()
            for item in data.get("bindings", []):
                binding = WeChatBinding(**item)
                self._bindings[binding.device_key] = binding
                self._by_wechat[binding.wechat_chat_id] = binding.device_key
                if binding.wechat_group_id:
                    self._by_group[binding.wechat_group_id] = binding.device_key
        except Exception as e:
            logger.warning(f"[WeChatBind] 加载失败: {e}")

    def _save(self) -> None:
        """保存绑定关系到统一数据文件。"""
        try:
            data = _load_wechat_data()
            data["bindings"] = [
                {
                    "wechat_chat_id": b.wechat_chat_id,
                    "wechat_user_id": b.wechat_user_id,
                    "device_key": b.device_key,
                    "device_mac": b.device_mac,
                    "bound_at": b.bound_at,
                    "wechat_group_id": b.wechat_group_id,
                    "alias": b.alias,
                }
                for b in self._bindings.values()
            ]
            _save_wechat_data(data)
        except Exception as e:
            logger.warning(f"[WeChatBind] 保存失败: {e}")

    # ── 绑定操作 ─────────────────────────────

    def bind(self, wechat_chat_id: str, wechat_user_id: str, device_key: str,
             device_mac: str = "", wechat_group_id: str = "", alias: str = "") -> WeChatBinding:
        """绑定微信用户到设备"""
        binding = WeChatBinding(
            wechat_chat_id=wechat_chat_id,
            wechat_user_id=wechat_user_id,
            device_key=device_key,
            device_mac=device_mac,
            bound_at=time.time(),
            wechat_group_id=wechat_group_id,
            alias=alias or device_mac or device_key,
        )
        # 移除旧绑定
        old_key = self._by_wechat.get(wechat_chat_id)
        if old_key:
            self._bindings.pop(old_key, None)
        old_by_key = self._bindings.get(device_key)
        if old_by_key:
            self._by_wechat.pop(old_by_key.wechat_chat_id, None)

        self._bindings[device_key] = binding
        self._by_wechat[wechat_chat_id] = device_key
        if wechat_group_id:
            self._by_group[wechat_group_id] = device_key
        self._save()
        logger.info(f"[WeChatBind] 绑定成功: wechat={wechat_chat_id[:16]} → device={device_key[:16]}")
        return binding

    def unbind(self, device_key: str) -> bool:
        """解绑设备"""
        binding = self._bindings.pop(device_key, None)
        if binding:
            self._by_wechat.pop(binding.wechat_chat_id, None)
            if binding.wechat_group_id:
                self._by_group.pop(binding.wechat_group_id, None)
            self._save()
            logger.info(f"[WeChatBind] 解绑成功: device={device_key[:16]}")
            return True
        return False

    def unbind_by_wechat(self, wechat_chat_id: str) -> bool:
        """通过微信 chat_id 解绑"""
        device_key = self._by_wechat.pop(wechat_chat_id, None)
        if device_key:
            self._bindings.pop(device_key, None)
            self._save()
            logger.info(f"[WeChatBind] 解绑成功: wechat={wechat_chat_id[:16]}")
            return True
        return False

    # ── 查询 ────────────────────────────────

    def get_by_device_key(self, device_key: str) -> Optional[WeChatBinding]:
        """通过设备 key 获取绑定"""
        self._load()
        return self._bindings.get(device_key)

    def find_binding(self, device_id: str) -> Optional[WeChatBinding]:
        """统一查找绑定：同时匹配 device_key、MAC 地址、registry key"""
        self._load()
        binding = self._bindings.get(device_id)
        if binding:
            return binding
        for b in self._bindings.values():
            if b.device_mac == device_id:
                return b
        # 通过 registry 的 mac 索引再试一次
        try:
            from src.infrastructure.web import get_device_registry
            registry = get_device_registry()
            if registry:
                entry = registry.resolve(device_id)
                if entry:
                    mac = entry.get("mac", "") or entry.get("device_id", "")
                    if mac and mac != device_id:
                        binding = self._bindings.get(mac)
                        if binding:
                            return binding
                        for b in self._bindings.values():
                            if b.device_mac == mac:
                                return b
        except Exception as e:
            logger.debug(f"[WeChatBind] registry 查找设备异常: {e}")
        return None

    def get_by_wechat(self, wechat_chat_id: str) -> Optional[WeChatBinding]:
        """通过微信 chat_id 获取绑定（先查私聊，再查群聊）"""
        self._load()
        device_key = self._by_wechat.get(wechat_chat_id) or self._by_group.get(wechat_chat_id)
        if device_key:
            return self._bindings.get(device_key)
        return None

    def get_all_bindings(self) -> list[WeChatBinding]:
        """获取所有绑定关系"""
        return list(self._bindings.values())

    def is_bound(self, device_key: str) -> bool:
        """检查设备是否已绑定微信"""
        return device_key in self._bindings

    # ── 发送指令给设备 ──────────────────────

    async def send_instruct_to_device(self, device_key: str, command_id: str, data: str = "") -> bool:
        """通过 WebSocket 向设备发送 instruct 指令"""
        from src.infrastructure.web import get_device_registry

        registry = get_device_registry()
        if not registry:
            logger.warning("[WeChatBind] 设备注册表不可用")
            return False

        # 用 find_binding 统一查找（兼容 key 和 MAC）
        binding = self.find_binding(device_key)
        if not binding:
            logger.warning(f"[WeChatBind] 设备未绑定: {device_key}")
            return False

        session = registry.resolve(binding.device_mac)

        if not session or not session.get('channel'):
            if registry:
                all_ids = registry.get_all_ids()
                logger.warning(f"[WeChatBind] 设备 {device_key[:16]} 不在线，"
                              f"注册表中有 {len(all_ids)} 个设备: {[k[:20] for k in all_ids[:5]]}")
            return False

        msg = {
            "type": "instruct",
            "command_id": command_id,
            "data": data,
        }
        channel = session.get('channel') or session.get('session')
        if not channel:
            logger.warning(f"[WeChatBind] 设备 {device_key[:16]} 无可用 channel")
            return False
        try:
            channel.send_queue.put_nowait({"kind": "json", "data": msg})
            logger.info(f"[WeChatBind] 已发送指令 {command_id} 到设备 {device_key[:16]}")
            return True
        except Exception as e:
            logger.error(f"[WeChatBind] 发送指令失败: {e}")
            return False

    async def send_text_to_device(self, device_key: str, text: str) -> bool:
        """发送文本消息到设备（显示在屏幕上）"""
        return await self.send_instruct_to_device(device_key, "show_text", text)

    async def send_wechat_message_to_device(self, device_key: str, wechat_chat_id: str,
                                            wechat_user_id: str, text: str) -> bool:
        """将微信消息转发给设备，并记录 WeChat reply 上下文"""
        payload = json.dumps({
            "chat_id": wechat_chat_id,
            "user_id": wechat_user_id,
            "text": text,
        }, ensure_ascii=False)
        ok = await self.send_instruct_to_device(device_key, "wechat_msg", payload)
        if ok:
            # 在设备 session 上记录 WeChat reply 上下文，方便 LLM 回复后回传
            self._set_wechat_context(device_key, wechat_chat_id)
        return ok

    def _set_wechat_context(self, device_key: str, chat_id: str) -> None:
        """在设备 session 上设置 WeChat reply 上下文"""
        try:
            from src.infrastructure.web import get_device_registry
            registry = get_device_registry()
            if registry:
                session = registry.resolve(device_key)
                if session:
                    session['wechat_reply_context'] = {
                        'chat_id': chat_id,
                        'timestamp': time.time(),
                    }
        except Exception as e:
            logger.debug(f"[WeChatBind] 设置 WeChat 上下文失败: {e}")


# 全局单例
_binding_manager: Optional[WeChatBindingManager] = None


def get_wechat_binding_manager() -> WeChatBindingManager:
    """获取全局微信绑定管理器单例"""
    global _binding_manager
    if _binding_manager is None:
        _binding_manager = WeChatBindingManager()
    return _binding_manager