"""SDK 工具函数 - 设备标识解析、配置读取、JSON 工具等"""

import json
import os
import time as _time
import uuid as _uuid
from typing import Any


def get_device_key(tool_manager) -> str:
    """获取设备绑定 key（bound_xxx 格式）；未连接/未配置时返回空字符串。"""
    if tool_manager and hasattr(tool_manager, 'user_config') and tool_manager.user_config:
        return getattr(tool_manager.user_config, 'key', None) or ''
    return ''


def resolve_device_key(device_key: str, tool_manager) -> str:
    """自动填充 device_key：优先 tool_manager.user_config.key（bound_xxx 格式），
    其次 user_config.device_id（MAC）经 devices 表映射为 device_key。

    所有工具都通过此函数获取设备标识，确保查询 diary/short_term_memories 等
    内部表时使用正确的 bound_xxx 格式，而非 MAC 地址。
    """
    if device_key:
        return device_key
    if tool_manager and hasattr(tool_manager, 'user_config') and tool_manager.user_config:
        cfg = tool_manager.user_config
        key = getattr(cfg, 'key', None)
        if key:
            return key
        cfg_id = getattr(cfg, 'device_id', None)
        if cfg_id:
            try:
                from sqlalchemy import select

                from src.infrastructure.db.compat.sync_session import get_sync_session
                from src.infrastructure.db.models.device import DeviceModel
                with get_sync_session() as session:
                    result = session.execute(
                        select(DeviceModel.device_key).where(DeviceModel.device_id == cfg_id)
                    )
                    row = result.scalar_one_or_none()
                    if row:
                        return row
            except Exception:
                pass
            return cfg_id
    return device_key


def get_plugin_config_or_env(tool_manager, plugin: str, key: str, env_var: str | None = None, default: str = "") -> str:
    """读取插件配置：优先设备插件商店配置（tool_manager.get_plugin_config），
    其次环境变量（仅限白名单），最后默认值。"""
    if tool_manager is not None and hasattr(tool_manager, "get_plugin_config"):
        cfg = tool_manager.get_plugin_config(plugin, key, "")
        if cfg:
            return cfg
    if env_var:
        from src.infrastructure.plugin_security import current_plugin, env_var_allowed
        ctx = current_plugin()
        plugin_id = ctx.plugin if ctx else plugin
        if env_var_allowed(plugin_id, env_var):
            val = os.environ.get(env_var, "")
            if val:
                return val
    return default


def generate_uuid() -> str:
    """生成 UUID v4 字符串。"""
    return str(_uuid.uuid4())


def current_timestamp() -> float:
    """获取当前时间戳（秒）。"""
    return _time.time()


def json_dumps(obj: Any, indent: int | None = None) -> str:
    """JSON 序列化对象为字符串。"""
    return json.dumps(obj, ensure_ascii=False, indent=indent)


def json_loads(s: str) -> Any:
    """JSON 反序列化字符串为 Python 对象。"""
    return json.loads(s)