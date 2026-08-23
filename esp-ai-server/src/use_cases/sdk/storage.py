"""SDK 数据持久化 - 文件读写、键值存储"""

import json
import os
import shutil
from typing import Any

from src.infrastructure.plugin_security import require_permission


def _get_plugin_id() -> str:
    """获取当前插件 ID。"""
    from src.infrastructure.plugin_security import current_plugin
    ctx = current_plugin()
    return ctx.plugin if ctx else "unknown"


def _get_project_root() -> str:
    """获取项目根目录。"""
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _get_plugin_data_dir() -> str:
    """获取当前插件的数据目录（自动创建）。"""
    plugin_id = _get_plugin_id()
    base = os.path.join(_get_project_root(), "data", "plugins", "data", plugin_id)
    os.makedirs(base, exist_ok=True)
    return base


def _safe_resolve_path(base: str, relative_path: str) -> str:
    """安全解析路径，防止路径穿越攻击。"""
    full = os.path.normpath(os.path.join(base, relative_path))
    if not full.startswith(base):
        raise PermissionError(f"路径越界: {relative_path}")
    return full


def plugin_data_read(path: str, tool_manager=None) -> str | None:
    """读取插件数据文件。

    Args:
        path: 相对路径（如 "config.json" 或 "subdir/data.txt"）
        tool_manager: 自动传入

    Returns:
        文件内容字符串，文件不存在时返回 None
    """
    require_permission("file_read", "读取插件数据文件")
    full = _safe_resolve_path(_get_plugin_data_dir(), path)
    if not os.path.isfile(full):
        return None
    with open(full, "r", encoding="utf-8") as f:
        return f.read()


def plugin_data_write(path: str, content: str, tool_manager=None) -> None:
    """写入插件数据文件。

    Args:
        path: 相对路径（如 "config.json"）
        content: 文件内容
        tool_manager: 自动传入
    """
    require_permission("file_write", "写入插件数据文件")
    base = _get_plugin_data_dir()
    full = _safe_resolve_path(base, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)


def plugin_data_list(path: str = "", tool_manager=None) -> list:
    """列出插件数据目录下的文件和子目录。

    Args:
        path: 相对目录路径，为空时列出根目录
        tool_manager: 自动传入

    Returns:
        列表，每项包含 name/is_dir/size/mtime
    """
    require_permission("file_read", "列出插件数据目录")
    base = _get_plugin_data_dir()
    full = _safe_resolve_path(base, path)
    if not os.path.isdir(full):
        return []
    result = []
    for entry in os.scandir(full):
        size = entry.stat().st_size if entry.is_file() else 0
        result.append({
            "name": entry.name,
            "is_dir": entry.is_dir(),
            "size": size,
            "mtime": entry.stat().st_mtime,
        })
    return result


def plugin_data_delete(path: str, tool_manager=None) -> bool:
    """删除插件数据文件或空目录。

    Args:
        path: 相对路径
        tool_manager: 自动传入

    Returns:
        True 表示删除成功，False 表示路径不存在
    """
    require_permission("file_write", "删除插件数据文件")
    base = _get_plugin_data_dir()
    full = _safe_resolve_path(base, path)
    if os.path.isfile(full):
        os.remove(full)
        return True
    if os.path.isdir(full):
        shutil.rmtree(full)
        return True
    return False


# ── 键值存储（KV Store）──


def _get_kv_store_path() -> str:
    """获取当前插件的 KV 存储文件路径。"""
    plugin_id = _get_plugin_id()
    kv_dir = os.path.join(_get_project_root(), "data", "plugins", "kv")
    os.makedirs(kv_dir, exist_ok=True)
    return os.path.join(kv_dir, f"{plugin_id}.json")


def _load_kv_store() -> dict:
    """加载 KV 存储。"""
    path = _get_kv_store_path()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_kv_store(store: dict) -> None:
    """保存 KV 存储。"""
    path = _get_kv_store_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def kv_get(key: str, default: Any = None, tool_manager=None) -> Any:
    """读取键值存储。

    Args:
        key: 键名
        default: 键不存在时返回的默认值
        tool_manager: 自动传入

    Returns:
        存储的值，键不存在时返回 default
    """
    require_permission("kv", "读取键值存储")
    store = _load_kv_store()
    return store.get(key, default)


def kv_set(key: str, value: Any, tool_manager=None) -> None:
    """写入键值存储。

    Args:
        key: 键名
        value: 值（必须是 JSON 可序列化的类型）
        tool_manager: 自动传入
    """
    require_permission("kv", "写入键值存储")
    store = _load_kv_store()
    store[key] = value
    _save_kv_store(store)


def kv_delete(key: str, tool_manager=None) -> bool:
    """删除键值存储中的条目。

    Args:
        key: 键名，为空时自动推断
        tool_manager: 自动传入

    Returns:
        True 表示删除成功，False 表示键不存在
    """
    require_permission("kv", "删除键值存储")
    store = _load_kv_store()
    if key in store:
        del store[key]
        _save_kv_store(store)
        return True
    return False


def kv_list(prefix: str = "", tool_manager=None) -> list:
    """列出键值存储中的所有条目（可按前缀过滤）。

    Args:
        prefix: 可选，只返回键以此前缀开头的条目
        tool_manager: 自动传入

    Returns:
        列表，每项包含 {"key": "...", "value": ...}
    """
    require_permission("kv", "列出键值存储")
    store = _load_kv_store()
    if prefix:
        return [{"key": k, "value": v} for k, v in store.items() if k.startswith(prefix)]
    return [{"key": k, "value": v} for k, v in store.items()]