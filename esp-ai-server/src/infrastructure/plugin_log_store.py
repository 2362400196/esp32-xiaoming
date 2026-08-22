"""插件日志共享存储：为内置插件和已安装插件提供统一的日志读写。

功能：
    - 内存环形缓冲（每插件最多 MAX_ENTRIES 条）
    - 可选文件持久化（data/plugins/state/<id>/plugin.log）
    - 供 API 层查询（routes/plugins.py 的 /logs 接口）
    - 供 SDK 的 plugin_log() 函数写入

内置插件通过 _plugin_helpers.plugin_log() 写入；
已安装插件通过 SDK RPC → adjudicator → plugin_log_store 写入。
"""

from __future__ import annotations

import os
import threading
from collections import deque
from datetime import datetime

MAX_ENTRIES = 500

_lock = threading.Lock()
_logs: dict[str, deque[dict]] = {}
_state_dir: str = ""


def set_state_dir(path: str) -> None:
    global _state_dir
    _state_dir = path


def _get_deque(plugin_id: str) -> deque[dict]:
    if plugin_id not in _logs:
        _logs[plugin_id] = deque(maxlen=MAX_ENTRIES)
    return _logs[plugin_id]


def add_log(plugin_id: str, level: str, message: str) -> None:
    """添加一条插件日志。线程安全。"""
    entry = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "level": level,
        "message": message,
    }
    with _lock:
        _get_deque(plugin_id).append(entry)
    _write_to_file(plugin_id, entry)


def get_logs(plugin_id: str, limit: int = 100, level: str | None = None) -> list[dict]:
    """读取插件日志（最新在前）。线程安全。"""
    with _lock:
        entries = list(_logs.get(plugin_id, []))
    if level:
        entries = [e for e in entries if e["level"] == level]
    entries.reverse()
    if limit > 0:
        entries = entries[:limit]
    return entries


def clear_logs(plugin_id: str) -> int:
    """清空插件日志，返回被清除的条数。"""
    with _lock:
        dq = _logs.get(plugin_id)
        if dq is None:
            return 0
        count = len(dq)
        dq.clear()
        return count


def _write_to_file(plugin_id: str, entry: dict) -> None:
    """追加写入文件日志（best-effort，失败静默）。"""
    if not _state_dir:
        return
    try:
        log_dir = os.path.join(_state_dir, plugin_id)
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "plugin.log")
        line = f"[{entry['time']}] [{entry['level'].upper()}] {entry['message']}\n"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def load_all_from_file(plugin_id: str) -> int:
    """从文件加载历史日志到内存缓冲（启动时调用）。

    读取 data/plugins/state/<plugin_id>/plugin.log，解析行格式
    [ISO时间] [LEVEL] message，仅加载最近 MAX_ENTRIES 条。
    返回加载的条数。
    """
    if not _state_dir:
        return 0
    log_path = os.path.join(_state_dir, plugin_id, "plugin.log")
    if not os.path.isfile(log_path):
        return 0
    import re
    pattern = re.compile(r"^\[(.+?)\]\s*\[(\w+)\]\s*(.*)$")
    loaded = 0
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # 只取最近 MAX_ENTRIES 行（文件可能很大）
        for line in lines[-MAX_ENTRIES:]:
            m = pattern.match(line.rstrip("\n"))
            if not m:
                continue
            entry = {"time": m.group(1), "level": m.group(2).lower(), "message": m.group(3)}
            with _lock:
                _get_deque(plugin_id).append(entry)
            loaded += 1
    except Exception:
        pass
    return loaded
