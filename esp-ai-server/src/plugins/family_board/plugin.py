"""家庭留言板插件 —— 设备之间互留语音留言。

核心玩法：
  - 用户对 A 设备说「给书房的设备留个言，记得吃药」→ LLM 调 family_board_send
  - 目标设备在线：立即主动播报留言内容（对讲机体验），并标记已读
  - 目标设备离线：留言存入收件箱，下次唤醒时自动播报（EVENT_SESSION_START 钩子）
  - 支持查看/删除/清空收件箱；网页后台「留言板」页可全局管理

存储：直接文件读写 data/plugins/family_board/messages.json（与 alarm 插件
同款模式，内置插件不走 kv 的 ContextVar 机制）。
key 为目标设备标识（device_key，bound_xxx 格式），留言板天然跨设备共享。
"""

import json
import os
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.utils import get_device_key
from src.use_cases.sdk.events import EVENT_SESSION_START, subscribe, unsubscribe
from src.use_cases.sdk.infrastructure import (
    get_device_registry,
    speak_to_device,
    get_logger,
)

logger = get_logger("family_board")

# 收件箱每设备留言上限（超出丢最旧）
_INBOX_MAX = 50
# 唤醒播报一次最多读出的留言条数与单条字数
_ANNOUNCE_MAX = 5
_ANNOUNCE_CHARS = 80

# ── 生命周期钩子 ─────────────────────────────────────────────

_sub_id: str = ""


async def on_startup():
    """订阅「语音会话开始」事件：设备唤醒时播报未读留言。"""
    global _sub_id
    _sub_id = subscribe(EVENT_SESSION_START, _announce_on_wake, plugin_name="family_board")
    logger.info("[FamilyBoard] 留言板已启动，唤醒播报钩子已注册")


async def on_shutdown():
    """取消事件订阅。"""
    global _sub_id
    if _sub_id:
        unsubscribe(_sub_id)
        _sub_id = ""


# ── 数据存储（直接文件读写，模式与 alarm 插件一致）──────────


def _get_data_dir() -> str:
    d = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "plugins", "family_board")
    d = os.path.normpath(d)
    os.makedirs(d, exist_ok=True)
    return d


def _read_store() -> Dict[str, List[Dict[str, Any]]]:
    path = os.path.join(_get_data_dir(), "messages.json")
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _write_store(data: Dict[str, List[Dict[str, Any]]]) -> None:
    path = os.path.join(_get_data_dir(), "messages.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_inbox(device_key: str) -> List[Dict[str, Any]]:
    msgs = _read_store().get(device_key)
    return msgs if isinstance(msgs, list) else []


def _save_inbox(device_key: str, msgs: List[Dict[str, Any]]) -> None:
    store = _read_store()
    if msgs:
        store[device_key] = msgs
    else:
        store.pop(device_key, None)  # 空收件箱不落盘
    _write_store(store)


def _unread(msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [m for m in msgs if not m.get("read")]


# ── 设备目录（DB 全量设备 + registry 在线状态）───────────────


async def _db_devices() -> List[Dict[str, Any]]:
    """全量设备（含离线）：device_key / name / is_online。

    is_online 由 DeviceRegistry 在上下线时落库，秒级延迟，够用。
    """
    from src.infrastructure.db.session import get_session_ctx
    from src.infrastructure.db.models.device import DeviceModel
    from sqlalchemy import select

    async with get_session_ctx() as s:
        rows = (await s.execute(select(DeviceModel))).scalars().all()
        return [
            {
                "device_key": r.device_key or "",
                "name": r.name or "",
                "online": bool(r.is_online),
            }
            for r in rows
            if r.device_key
        ]


def _registry_names() -> Dict[str, str]:
    """在线设备的名称速查（user_config.name）。"""
    reg = get_device_registry()
    names: Dict[str, str] = {}
    if reg is None:
        return names
    for key in reg.get_all_ids():
        dev = reg.resolve(key) or {}
        cfg = dev.get("user_config") or {}
        if isinstance(cfg, dict) and cfg.get("name"):
            names[key] = cfg["name"]
    return names


async def _resolve_target(target: str) -> Optional[Dict[str, Any]]:
    """把 LLM 给的目标（device_key / MAC / 设备名）解析成设备记录。

    优先精确匹配 device_key，其次名称包含匹配（大小写不敏感）。
    """
    target = (target or "").strip()
    if not target:
        return None
    devices = await _db_devices()
    # 精确 key / MAC 匹配
    for d in devices:
        if target and (d["device_key"] == target):
            return d
    # 名称匹配（LLM 通常给中文设备名，如「书房」）
    low = target.lower()
    candidates = [d for d in devices if low in (d["name"] or "").lower()]
    if len(candidates) == 1:
        return candidates[0]
    # 多个同名候选 → 取第一个（LLM 会看到列表自行消歧）
    if candidates:
        return candidates[0]
    return None


# ── 唤醒播报（EVENT_SESSION_START）──────────────────────────


async def _announce_on_wake(device_key: str = "", **_) -> None:
    """设备唤醒时播报未读留言，播报成功后标记已读。"""
    if not device_key:
        return
    msgs = _load_inbox(device_key)
    unread = _unread(msgs)
    if not unread:
        return
    # 组装播报文本：最多读 _ANNOUNCE_MAX 条，单条截断
    lines = []
    for i, m in enumerate(unread[:_ANNOUNCE_MAX], 1):
        content = (m.get("content") or "").strip()
        if len(content) > _ANNOUNCE_CHARS:
            content = content[:_ANNOUNCE_CHARS] + "……"
        sender = m.get("from_name") or "有人"
        ts = m.get("ts") or 0
        when = ""
        try:
            when = datetime.fromtimestamp(float(ts)).strftime("%m月%d日%H点%M分")
        except Exception:
            pass
        prefix = f"{when}，" if when else ""
        lines.append(f"第{'一二三四五'[i-1]}条，{prefix}{sender}说：{content}")
    rest = len(unread) - _ANNOUNCE_MAX
    text = (
        f"你有 {len(unread)} 条新留言。" + "。".join(lines) + "。"
        + (f"还有 {rest} 条留言稍后告诉你。" if rest > 0 else "")
    )
    ok = await speak_to_device(device_key, text)
    if ok:
        # 播报成功 → 全部标已读（只标播出的部分，剩余保持未读下次继续）
        done_ids = {m.get("id") for m in unread[:_ANNOUNCE_MAX]}
        for m in msgs:
            if m.get("id") in done_ids:
                m["read"] = True
        _save_inbox(device_key, msgs)
        logger.info(f"[FamilyBoard] 唤醒播报完成: {device_key} 共 {min(len(unread), _ANNOUNCE_MAX)} 条")
    else:
        logger.warning(f"[FamilyBoard] 唤醒播报失败（设备离线或 Speaker 不可用）: {device_key}")


# ── LLM 工具 ────────────────────────────────────────────────


@tool()
async def family_board_list_devices(tool_manager=None) -> str:
    """列出家里所有设备（名称、在线状态、未读留言数）。
    当用户想留言、问家里有哪些设备、问某设备有没有留言时调用。
    留言前务必先用此工具确认收件人名称，把返回的「名称」作为 family_board_send 的 target。"""
    devices = await _db_devices()
    if not devices:
        return "还没有任何已绑定的设备"
    store = _read_store()
    reg = get_device_registry()
    lines = []
    for d in devices:
        unread = len(_unread(store.get(d["device_key"], []) or []))
        online = "在线" if (d["online"] or (reg and reg.has(d["device_key"]))) else "离线"
        lines.append(f"{d['name'] or '未命名'} | {online} | 未读留言 {unread} 条 | key={d['device_key']}")
    return "设备列表：\n" + "\n".join(lines)


@tool()
async def family_board_send(target: str, content: str, sender_name: str = "", tool_manager=None) -> str:
    """给家里另一台设备留言。
    当用户说「给xx留言」「告诉xx」「跟xx说」时调用。
    参数:
        target: 目标设备（优先用 family_board_list_devices 返回的名称；也可用 key）
        content: 留言内容（原话转述，不要添加额外客套）
        sender_name: 留言人名称，用户没说时填当前设备名，不知道则留空
    """
    content = (content or "").strip()
    if not content:
        return "留言内容不能为空"
    if len(content) > 500:
        content = content[:500]
    dev = await _resolve_target(target)
    if dev is None:
        return (
            f"没有找到叫「{target}」的设备。请先调用 family_board_list_devices 查看设备列表，"
            "把确切的设备名称告诉我。"
        )
    target_key = dev["device_key"]
    target_name = dev["name"] or target_key
    if target_key == get_device_key(tool_manager):
        return "这就是当前设备自己，不用给自己留言"

    msg = {
        "id": uuid.uuid4().hex[:12],
        "from_id": get_device_key(tool_manager),
        "from_name": (sender_name or "").strip() or "家人",
        "content": content,
        "ts": time.time(),
        "read": False,
    }

    reg = get_device_registry()
    is_online = bool(dev["online"]) or (reg is not None and reg.has(target_key))
    if is_online:
        # 在线：立即主动播报（对讲机体验），播报成功即标记已读
        ok = await speak_to_device(target_key, f"{msg['from_name']}给你留言：{content}")
        if ok:
            msg["read"] = True
            return f"已送达「{target_name}」并当场播报：{content}"
        # 播报失败（正忙等）→ 落收件箱等唤醒播报
    inbox = _load_inbox(target_key)
    inbox.append(msg)
    if len(inbox) > _INBOX_MAX:
        inbox = inbox[-_INBOX_MAX:]
    _save_inbox(target_key, inbox)
    if is_online:
        return f"「{target_name}」正忙，留言已存入它的收件箱，唤醒时会自动播报"
    return f"「{target_name}」目前离线，留言已存入收件箱，它下次唤醒时会自动播报"


@tool()
async def family_board_read(mark_read: bool = True, tool_manager=None) -> str:
    """查看当前设备的留言收件箱。
    当用户说「看看留言」「有没有人给我留言」「读一下留言」时调用。
    参数:
        mark_read: 是否把这些留言标记为已读（默认 true）
    """
    device_key = get_device_key(tool_manager)
    msgs = _load_inbox(device_key)
    if not msgs:
        return "收件箱是空的，没有留言"
    lines = []
    for i, m in enumerate(msgs[-10:], 1):  # 最多展示最近 10 条
        status = "已读" if m.get("read") else "未读"
        ts = m.get("ts") or 0
        try:
            when = datetime.fromtimestamp(float(ts)).strftime("%m-%d %H:%M")
        except Exception:
            when = ""
        lines.append(f"{i}. [{status}]{(' ' + when) if when else ''} {m.get('from_name', '有人')}：{m.get('content', '')}")
    if mark_read:
        for m in msgs:
            m["read"] = True
        _save_inbox(device_key, msgs)
    total_unread = len(_unread(msgs))
    head = f"收件箱共 {len(msgs)} 条（未读 {total_unread} 条），最近留言："
    return head + "\n" + "\n".join(lines)


@tool()
async def family_board_manage(action: str, index: int = 0, tool_manager=None) -> str:
    """管理当前设备的留言收件箱。
    当用户说「删掉第2条留言」「清空留言」「留言都看过了」时调用。
    参数:
        action: 动作，clear=清空收件箱 / delete=删除指定序号留言 / mark_all_read=全部标已读
        index: delete 时的留言序号（family_board_read 返回列表中的序号，从 1 开始）
    """
    device_key = get_device_key(tool_manager)
    msgs = _load_inbox(device_key)
    if action == "clear":
        _save_inbox(device_key, [])
        return "收件箱已清空"
    if action == "mark_all_read":
        for m in msgs:
            m["read"] = True
        _save_inbox(device_key, msgs)
        return "所有留言已标记为已读"
    if action == "delete":
        if not msgs:
            return "收件箱是空的"
        if index < 1 or index > len(msgs):
            return f"序号超出范围（1~{len(msgs)}），请先调用 family_board_read 查看列表"
        removed = msgs.pop(index - 1)
        _save_inbox(device_key, msgs)
        return f"已删除留言：{removed.get('from_name', '有人')}：{removed.get('content', '')[:50]}"
    return f"不支持的动作「{action}」，可用：clear / delete / mark_all_read"


# ── 前端 exec API（网页后台「留言板」页通过 exec 桥调用）────


async def _api_summary() -> Dict[str, Any]:
    """全部设备的收件箱总览（含留言明细）。"""
    devices = await _db_devices()
    store = _read_store()
    reg = get_device_registry()
    reg_names = _registry_names()
    out = []
    for d in devices:
        key = d["device_key"]
        msgs = store.get(key, []) or []
        out.append({
            "device_key": key,
            "name": d["name"] or reg_names.get(key) or "未命名",
            "online": bool(d["online"]) or (reg is not None and reg.has(key)),
            "unread": len(_unread(msgs)),
            "messages": list(reversed(msgs)),  # 前端展示：最新在上
        })
    return {"devices": out}


async def _api_delete_message(device_key: str = "", msg_id: str = "") -> Dict[str, Any]:
    """删除指定留言。"""
    if not device_key or not msg_id:
        return {"ok": False, "error": "缺少 device_key 或 msg_id"}
    msgs = _load_inbox(device_key)
    before = len(msgs)
    msgs = [m for m in msgs if m.get("id") != msg_id]
    if len(msgs) == before:
        return {"ok": False, "error": "留言不存在"}
    _save_inbox(device_key, msgs)
    return {"ok": True}


async def _api_clear_inbox(device_key: str = "") -> Dict[str, Any]:
    """清空指定设备收件箱。"""
    if not device_key:
        return {"ok": False, "error": "缺少 device_key"}
    _save_inbox(device_key, [])
    return {"ok": True}


# exec 桥入口：前端 POST /api/v1/plugins/family_board/exec {method, args}
frontend_api: Dict[str, Any] = {
    "summary": _api_summary,
    "delete_message": _api_delete_message,
    "clear_inbox": _api_clear_inbox,
}
