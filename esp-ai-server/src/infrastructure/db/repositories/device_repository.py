"""设备配置仓储（阶段 2：仓储层）

替代 ``users.json`` 中设备配置字典的读写，提供异步与同步两套接口：
- 异步方法供 FastAPI 路由层使用（通过 ``get_session_ctx()``）
- 同步方法供 ``load_devices()`` 等兼容入口使用（通过 ``get_sync_session()``）

返回的 dict 结构与原 ``users.json`` 中的设备配置字典**完全一致**，保持向后兼容：
- 标量字段（``name``、``key``、``asr_provider`` 等）映射到列
- 嵌套对象（``asr_config``、``tts_config``、``mcp_servers``、``music``、``wakeup``、
  ``llm``、``ota``）存 JSON 列
- ``disabled_tools``、``disabled_mcp_servers``、``disabled_skills``、``skills`` 为 JSON 数组
- ``disabled_mcp_tools`` 为 JSON 对象

替代项（已全部移除）：
- ``src/infrastructure/web.py`` 中的 ``_hot_reload_device_config``（保留，用于热重载）
- ``src/infrastructure/device_api.py`` 中的 ``update_device_config``
- 原 ``src/infrastructure/users_json_helper.py`` 的 JSON 读写函数（文件已删除）
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from sqlalchemy import or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db.models.device import DeviceModel
from src.infrastructure.db.session import get_session_ctx
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


# ============================================================
# 每设备读写锁：保证同一设备的“读-改-写”类操作（部分更新、技能增删、
# MCP 配置写入）互斥，避免并发请求在各自 session 里读旧值互相覆盖。
# SQLite 单文件库无行锁，仓储方法又各自开会话，只能在进程内串行化。
# ============================================================

_device_rw_locks: dict[str, asyncio.Lock] = {}
_device_rw_locks_guard = asyncio.Lock()


@asynccontextmanager
async def _device_rw_lock(device_id: str) -> AsyncIterator[None]:
    async with _device_rw_locks_guard:
        lock = _device_rw_locks.setdefault(device_id, asyncio.Lock())
    async with lock:
        yield


# ============================================================
# dict <-> DeviceModel 转换辅助函数
# ============================================================

def _dict_to_model_fields(device_id: str, config: dict) -> dict:
    """将 users.json 格式的设备配置 dict 转换为 DeviceModel 字段字典。

    标量字段映射到列，嵌套对象（``asr_config``、``tts_config``、``mcp_servers`` 等）
    存 JSON 列。``llm.*`` 和 ``ota.*`` 拍平到对应列。
    """
    llm = config.get("llm") or {}
    ota = config.get("ota") or {}
    return {
        "device_id": device_id,
        # 基本信息
        "name": config.get("name", "") or "",
        "device_key": config.get("key", "") or config.get("api_key", "") or device_id,
        "management_api_key": config.get("management_api_key", "") or "",
        "mac_address": config.get("mac", "") or device_id,
        # ASR/LLM/TTS 提供商
        "asr_provider": config.get("asr_provider", "") or "",
        "llm_type": config.get("llm_type", "") or "",
        "tts_type": config.get("tts_type", "") or "",
        # 嵌套配置（JSON 列）
        "asr_config": config.get("asr_config") or {},
        "tts_config": config.get("tts_config") or {},
        "music_config": config.get("music_config") or config.get("music") or {},
        "mcp_servers": config.get("mcp_servers") or {},
        "wakeup_config": config.get("wakeup_config") or config.get("wakeup") or {},
        # LLM 配置（从 llm dict 拍平）
        "llm_api_key": llm.get("api_key", "") or "",
        "llm_base_url": llm.get("base_url", "") or "",
        "llm_model": llm.get("model", "") or "",
        "llm_system_prompt": llm.get("system_prompt", "") or "",
        "llm_memory_enabled": llm.get("memory_enabled", True),
        "llm_memory_max_messages": llm.get("memory_max_messages", 20),
        "llm_memory_long_term_enabled": llm.get("memory_long_term_enabled", True),
        "llm_memory_long_term_auto_extract": llm.get("memory_long_term_auto_extract", True),
        # 限流
        "rate_limit_rpm": config.get("rate_limit_rpm", 0) or 0,
        # OTA 配置（从 ota dict 拍平）
        "ota_enabled": ota.get("enabled", True),
        "ota_bin_url": ota.get("bin_url", "") or "",
        "ota_version": ota.get("version", "") or "",
        "ota_bin_id": ota.get("bin_id", "") or "",
        "ota_is_official": ota.get("is_official", "0") or "0",
        # 禁用项（JSON 列）
        "disabled_tools": config.get("disabled_tools") or [],
        "disabled_mcp_servers": config.get("disabled_mcp_servers") or [],
        "disabled_mcp_tools": config.get("disabled_mcp_tools") or {},
        "disabled_skills": config.get("disabled_skills") or [],
        # 插件商店：已安装插件列表 + 插件配置 + 屏幕能力
        "enabled_plugins": config.get("enabled_plugins"),
        "plugin_configs": config.get("plugin_configs") or {},
        "has_display": config.get("has_display"),
        # 屏幕显示配置
        "robot_mode": config.get("robot_mode", "false"),
        "screensaver_enabled": config.get("screensaver_enabled", "true"),
        "screensaver_timeout": config.get("screensaver_timeout", "30"),
        # 限流技能列表
        "skills": config.get("skills") or [],
        # 表情包 / 运行时状态
        "active_emo_pack": config.get("active_emo_pack", "default") or "default",
        "is_online": config.get("is_online", False),
        "last_seen": config.get("last_seen", 0.0) or 0.0,
    }


def _model_to_dict(model: DeviceModel) -> dict:
    """将 DeviceModel 转换为 users.json 格式的设备配置 dict。

    返回结构与 ``users.json`` 中的设备配置字典完全一致，供 ``load_devices()`` 使用。
    """
    return {
        "name": model.name or "",
        "key": model.device_key or "",
        "management_api_key": model.management_api_key or "",
        # asr
        "asr_provider": model.asr_provider or "",
        "asr_config": dict(model.asr_config or {}),
        # llm
        "llm_type": model.llm_type or "",
        "llm": {
            "api_key": model.llm_api_key or "",
            "base_url": model.llm_base_url or "",
            "model": model.llm_model or "",
            "system_prompt": model.llm_system_prompt or "",
            "memory_enabled": model.llm_memory_enabled,
            "memory_max_messages": model.llm_memory_max_messages,
            "memory_long_term_enabled": model.llm_memory_long_term_enabled,
            "memory_long_term_auto_extract": model.llm_memory_long_term_auto_extract,
        },
        # tts
        "tts_type": model.tts_type or "",
        "tts_config": dict(model.tts_config or {}),
        # music / mcp / wakeup
        "music": dict(model.music_config or {}),
        "mcp_servers": dict(model.mcp_servers or {}),
        "wakeup": dict(model.wakeup_config or {}),
        # 限流
        "rate_limit_rpm": model.rate_limit_rpm,
        # ota
        "ota": {
            "enabled": model.ota_enabled,
            "bin_url": model.ota_bin_url or "",
            "version": model.ota_version or "",
            "bin_id": model.ota_bin_id or "",
            "is_official": model.ota_is_official or "0",
        },
        # 禁用项
        "disabled_tools": list(model.disabled_tools or []),
        "disabled_mcp_servers": list(model.disabled_mcp_servers or []),
        "disabled_mcp_tools": dict(model.disabled_mcp_tools or {}),
        "disabled_skills": list(model.disabled_skills or []),
        # 插件商店：已安装插件列表 + 插件配置 + 屏幕能力
        "enabled_plugins": model.enabled_plugins,
        "plugin_configs": dict(model.plugin_configs or {}),
        "has_display": model.has_display,
        # 屏幕显示配置
        "robot_mode": model.robot_mode or "false",
        "screensaver_enabled": model.screensaver_enabled or "true",
        "screensaver_timeout": model.screensaver_timeout or "30",
        # 技能
        "skills": list(model.skills or []),
    }


def _deep_merge(base: dict, updates: dict) -> dict:
    """深度合并 updates 到 base（返回新 dict，不修改入参）。

    - dict 类型递归合并
    - 其他类型（list、str、int 等）直接覆盖
    """
    result: dict = dict(base)
    for k, v in updates.items():
        if v is None:
            continue
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _now_ts() -> float:
    """当前 UTC 时间戳（秒）"""
    return datetime.now(timezone.utc).timestamp()


# ============================================================
# DeviceRepository
# ============================================================

class DeviceRepository:
    """设备配置仓储

    异步方法供路由层使用（``get_session_ctx()``），同步方法供 ``load_devices()``
    等兼容入口使用（``get_sync_session()``）。

    所有返回的 dict 都与 ``users.json`` 中的设备配置字典结构一致，保证向后兼容。
    """

    # ============================================================
    # 异步方法
    # ============================================================

    async def get_device_config(self, device_id_or_mac: str) -> Optional[dict]:
        """获取设备配置（按 device_id / device_key / mac_address 查找）。

        返回与 ``users.json`` 中设备配置字典结构一致的 dict，未找到返回 None。
        """
        if not device_id_or_mac:
            return None
        async with get_session_ctx() as session:
            model = await self._select_device(session, device_id_or_mac)
            if model is None:
                return None
            return _model_to_dict(model)

    async def get_all_devices(self) -> dict[str, dict]:
        """获取所有设备配置，返回 ``{device_id: config_dict}``。

        等价于 ``users.json`` 中 ``data["devices"]`` 的结构。
        """
        async with get_session_ctx() as session:
            result = await session.execute(select(DeviceModel))
            models = result.scalars().all()
            return {m.device_id: _model_to_dict(m) for m in models}

    async def upsert_device(self, device_id: str, config: dict) -> None:
        """插入或更新设备配置（SQLite ``INSERT ... ON CONFLICT DO UPDATE``）。

        - 新设备：插入
        - 已存在设备：更新所有字段（``created_at`` 保留，``updated_at`` 刷新）
        """
        if not device_id:
            return
        fields = _dict_to_model_fields(device_id, config or {})
        values = {k: v for k, v in fields.items() if k != "device_id"}
        stmt = sqlite_insert(DeviceModel).values(device_id=device_id, **values)
        # ON CONFLICT DO UPDATE：更新所有非主键字段，并刷新 updated_at
        update_cols = {k: getattr(stmt.excluded, k) for k in values.keys()}
        update_cols["updated_at"] = _now_ts()
        stmt = stmt.on_conflict_do_update(
            index_elements=["device_id"],
            set_=update_cols,
        )
        async with get_session_ctx() as session:
            await session.execute(stmt)

    async def update_device_partial(self, device_id: str, updates: dict) -> Optional[dict]:
        """部分更新设备配置（深度合并 ``updates`` 到现有配置）。

        - 嵌套 dict（如 ``llm``、``ota``、``mcp_servers``）递归合并
        - 标量和 list 字段（如 ``skills``、``name``）直接覆盖
        - 返回更新后的完整 dict，未找到设备返回 None
        """
        if not device_id or not updates:
            return None
        async with _device_rw_lock(device_id):
            async with get_session_ctx() as session:
                model = await self._select_device(session, device_id)
                if model is None:
                    return None
                # 转为 dict（含 mac，用于合并时保留 mac_address）
                current = _model_to_dict(model)
                current["mac"] = model.mac_address or ""
                # 深度合并
                merged = _deep_merge(current, updates)
                # 转换为 model 字段并应用
                new_fields = _dict_to_model_fields(device_id, merged)
                for k, v in new_fields.items():
                    if k == "device_id":
                        continue
                    setattr(model, k, v)
                # 显式刷新 updated_at（热重载靠它判断配置变更，不依赖 onupdate 隐式触发）
                model.updated_at = _now_ts()
                await session.flush()
                return _model_to_dict(model)

    async def reset_device(self, device_id: str) -> bool:
        """清空设备所有配置（解绑/恢复出厂设置），保留 device_id 和 device_key"""
        if not device_id:
            return False
        async with get_session_ctx() as session:
            result = await session.execute(
                select(DeviceModel).where(DeviceModel.device_id == device_id)
            )
            model = result.scalar_one_or_none()
            if model is None:
                return False
            defaults = {
                "name": "",
                "device_key": "",
                "asr_provider": "",
                "llm_type": "",
                "tts_type": "volcengine",
                "asr_config": {},
                "tts_config": {"api_key": "", "resource_id": "seed-tts-2.0", "voice_type": "zh_female_xiaohe_uranus_bigtts"},
                "music_config": {},
                "wakeup_config": {},
                "mcp_servers": {},
                "llm_api_key": "",
                "llm_base_url": "",
                "llm_model": "",
                "llm_system_prompt": "",
                "llm_memory_enabled": True,
                "llm_memory_max_messages": 20,
                "llm_memory_long_term_enabled": True,
                "llm_memory_long_term_auto_extract": True,
                "rate_limit_rpm": 0,
                "ota_enabled": False,
                "ota_bin_url": "",
                "ota_version": "",
                "ota_bin_id": "",
                "ota_is_official": "0",
                "disabled_tools": [],
                "disabled_mcp_servers": [],
                "disabled_mcp_tools": {},
                "disabled_skills": [],
                "skills": [],
                "active_emo_pack": "",
                "user_id": None,
                "bound_at": None,
                "bind_code": None,
                "bind_code_expires": None,
                "management_api_key": "",
            }
            for k, v in defaults.items():
                setattr(model, k, v)
            await session.flush()
            logger.info(f"[DeviceRepo] 设备 {device_id} 配置已清空（解绑）")
            return True

    async def find_by_key(self, key: str) -> Optional[tuple[str, dict]]:
        """按 device_key（API key）查找设备。

        返回 ``(device_id, config_dict)``，未找到返回 None。
        """
        if not key:
            return None
        async with get_session_ctx() as session:
            result = await session.execute(
                select(DeviceModel).where(DeviceModel.device_key == key)
            )
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return (model.device_id, _model_to_dict(model))

    async def find_by_mac(self, mac: str) -> Optional[tuple[str, dict]]:
        """按 MAC 地址查找设备。

        优先匹配 ``mac_address`` 列；若未命中，回退匹配 ``device_id`` 列
        （users.json 中 dict key 通常就是 MAC）。

        返回 ``(device_id, config_dict)``，未找到返回 None。
        """
        if not mac:
            return None
        async with get_session_ctx() as session:
            result = await session.execute(
                select(DeviceModel).where(DeviceModel.mac_address == mac)
            )
            model = result.scalar_one_or_none()
            if model is None:
                # 回退：device_id == mac（users.json 中 dict key 即 MAC）
                result = await session.execute(
                    select(DeviceModel).where(DeviceModel.device_id == mac)
                )
                model = result.scalar_one_or_none()
            if model is None:
                return None
            return (model.device_id, _model_to_dict(model))

    async def add_skill_to_device(self, device_id: str, skill_name: str) -> bool:
        """向设备添加技能（已存在则跳过）。

        返回 True 表示设备存在（技能已添加或已存在），False 表示设备不存在。
        """
        if not device_id or not skill_name:
            return False
        async with _device_rw_lock(device_id):
            async with get_session_ctx() as session:
                model = await self._select_device(session, device_id)
                if model is None:
                    return False
                skills = list(model.skills or [])
                if skill_name not in skills:
                    skills.append(skill_name)
                    model.skills = skills
                return True

    async def remove_skill_from_all_devices(self, skill_name: str) -> int:
        """从所有设备的 ``skills`` 列表中移除指定技能。

        返回受影响的设备数量。
        """
        if not skill_name:
            return 0
        count = 0
        async with get_session_ctx() as session:
            result = await session.execute(select(DeviceModel))
            for model in result.scalars().all():
                skills = list(model.skills or [])
                if skill_name in skills:
                    skills.remove(skill_name)
                    model.skills = skills
                    count += 1
        return count

    async def toggle_skill(self, device_id: str, skill_id: str, disabled: bool) -> None:
        """启用或禁用技能（操作 ``disabled_skills`` 列表）。

        - ``disabled=True``：将 ``skill_id`` 加入 ``disabled_skills``
        - ``disabled=False``：将 ``skill_id`` 从 ``disabled_skills`` 移除
        """
        if not device_id or not skill_id:
            return
        async with _device_rw_lock(device_id):
            async with get_session_ctx() as session:
                model = await self._select_device(session, device_id)
                if model is None:
                    return
                disabled_list = list(model.disabled_skills or [])
                if disabled:
                    if skill_id not in disabled_list:
                        disabled_list.append(skill_id)
                else:
                    disabled_list = [s for s in disabled_list if s != skill_id]
                model.disabled_skills = disabled_list

    async def get_mcp_servers(self, device_id: str) -> dict:
        """获取设备的 MCP 服务器配置。

        返回 ``{server_name: config_dict}``，设备不存在返回空 dict。
        """
        if not device_id:
            return {}
        async with get_session_ctx() as session:
            model = await self._select_device(session, device_id)
            if model is None:
                return {}
            return dict(model.mcp_servers or {})

    async def set_mcp_server(self, device_id: str, server_name: str, config: dict) -> None:
        """添加或更新设备的单个 MCP 服务器配置。"""
        if not device_id or not server_name:
            return
        async with _device_rw_lock(device_id):
            async with get_session_ctx() as session:
                model = await self._select_device(session, device_id)
                if model is None:
                    return
                servers = dict(model.mcp_servers or {})
                servers[server_name] = config or {}
                model.mcp_servers = servers

    async def delete_mcp_server(self, device_id: str, server_name: str) -> None:
        """删除设备的指定 MCP 服务器配置（不存在则无操作）。"""
        if not device_id or not server_name:
            return
        async with _device_rw_lock(device_id):
            async with get_session_ctx() as session:
                model = await self._select_device(session, device_id)
                if model is None:
                    return
                servers = dict(model.mcp_servers or {})
                if server_name in servers:
                    del servers[server_name]
                    model.mcp_servers = servers

    async def resolve_device(self, device_id_or_mac: str) -> tuple[Optional[str], Optional[dict]]:
        """解析设备标识，返回 (device_id, config_dict) 或 (None, None)。

        按 device_id → device_key → mac_address 顺序查找。
        """
        if not device_id_or_mac:
            return None, None
        async with get_session_ctx() as session:
            model = await self._select_device(session, device_id_or_mac)
            if model is None:
                return None, None
            return model.device_id, _model_to_dict(model)

    async def check_device_owner(self, device_id: str, user_id: str) -> bool:
        """校验设备是否属于指定用户。"""
        if not device_id or not user_id:
            return False
        async with get_session_ctx() as session:
            result = await session.execute(
                select(DeviceModel).where(
                    DeviceModel.device_id == device_id,
                    DeviceModel.user_id == user_id,
                )
            )
            return result.scalar_one_or_none() is not None

    async def toggle_mcp_server(self, device_id: str, server_name: str, disabled: bool) -> None:
        """启用或禁用 MCP 服务器。"""
        if not device_id or not server_name:
            return
        async with get_session_ctx() as session:
            model = await self._select_device(session, device_id)
            if model is None:
                return
            ds = list(model.disabled_mcp_servers or [])
            if disabled:
                if server_name not in ds:
                    ds.append(server_name)
            else:
                ds = [s for s in ds if s != server_name]
            model.disabled_mcp_servers = ds

    async def toggle_mcp_tool(self, device_id: str, server_name: str, tool_name: str, disabled: bool) -> None:
        """启用或禁用 MCP 服务器中的单个工具。"""
        if not device_id or not server_name or not tool_name:
            return
        async with get_session_ctx() as session:
            model = await self._select_device(session, device_id)
            if model is None:
                return
            dt = dict(model.disabled_mcp_tools or {})
            server_disabled = list(dt.get(server_name, []) or [])
            if disabled:
                if tool_name not in server_disabled:
                    server_disabled.append(tool_name)
            else:
                server_disabled = [t for t in server_disabled if t != tool_name]
            dt[server_name] = server_disabled
            model.disabled_mcp_tools = dt

    async def get_disabled_mcp(self, device_id: str) -> dict:
        """获取设备的 MCP 禁用列表。"""
        if not device_id:
            return {"disabled_servers": [], "disabled_tools": {}}
        async with get_session_ctx() as session:
            model = await self._select_device(session, device_id)
            if model is None:
                return {"disabled_servers": [], "disabled_tools": {}}
            return {
                "disabled_servers": list(model.disabled_mcp_servers or []),
                "disabled_tools": dict(model.disabled_mcp_tools or {}),
            }

    async def mcp_enabled_plugins_add(self, device_id: str, server_name: str) -> None:
        """将 mcp:{server_name} 加入 enabled_plugins（确保 AI 可见）。"""
        if not device_id or not server_name:
            return
        async with get_session_ctx() as session:
            model = await self._select_device(session, device_id)
            if model is None:
                return
            plugins = model.enabled_plugins
            if plugins is None:
                return
            mcp_id = f"mcp:{server_name}"
            if mcp_id not in plugins:
                plugins.append(mcp_id)
                model.enabled_plugins = plugins

    async def mcp_enabled_plugins_remove(self, device_id: str, server_name: str) -> None:
        """从 enabled_plugins 移除 mcp:{server_name}。"""
        if not device_id or not server_name:
            return
        async with get_session_ctx() as session:
            model = await self._select_device(session, device_id)
            if model is None:
                return
            plugins = model.enabled_plugins
            if plugins is None:
                return
            mcp_id = f"mcp:{server_name}"
            if mcp_id in plugins:
                model.enabled_plugins = [p for p in plugins if p != mcp_id]

    # ============================================================
    # 同步方法
    # ============================================================

    def load_all_devices_sync(self) -> dict[str, dict]:
        """同步加载所有设备配置（供 ``load_devices()`` 兼容入口使用）。

        返回 ``{device_id: config_dict}``，结构与 ``users.json`` 的
        ``devices`` 字典完全一致。
        """
        from src.infrastructure.db.compat.sync_session import get_sync_session
        with get_sync_session() as session:
            result = session.execute(select(DeviceModel))
            models = result.scalars().all()
            return {m.device_id: _model_to_dict(m) for m in models}

    # ============================================================
    # 内部辅助
    # ============================================================

    @staticmethod
    async def _select_device(session: AsyncSession, device_id_or_mac: str) -> Optional[DeviceModel]:
        """按 device_id / device_key / mac_address 查找设备模型。

        单条 or_() 查询一次命中（device_id 为 PK，通常一击即中）。
        """
        result = await session.execute(
            select(DeviceModel)
            .where(
                or_(
                    DeviceModel.device_id == device_id_or_mac,
                    DeviceModel.device_key == device_id_or_mac,
                    DeviceModel.mac_address == device_id_or_mac,
                )
            )
            .limit(1)
        )
        return result.scalar_one_or_none()


__all__ = ["DeviceRepository"]
