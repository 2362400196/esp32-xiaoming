"""闹钟、提醒和睡眠定时器插件。

增强功能：
  - 智能闹钟：使用 LLM 解析自然语言描述，自动设置
  - 闹钟统计：追踪闹钟使用习惯（用得多不多、什么时间爱设闹钟）
  - 设备感知：设置前自动检查设备在线状态，避免无效设置
  - 操作历史：记录闹钟设置/触发/取消记录，随时可查历史
"""

import json
import os
from datetime import datetime as _datetime, timedelta as _timedelta

from src.use_cases.alarm_manager import AlarmItem, get_alarm_manager
from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import (
    get_device_key,
    device_is_online,
    llm_generate,
    generate_uuid,
    json_dumps,
    json_loads,
)


# ── 生命周期钩子（插件加载/卸载时由 plugin_loader 调用）──────


async def on_startup():
    """插件加载钩子：确保闹钟后台检查协程已启动。

    AlarmManager.start 幂等（重复调用无副作用），与 web.py 启动时的
    调用兼容，不会重复创建后台任务。
    """
    try:
        mgr = get_alarm_manager()
        await mgr.start()
    except Exception as e:
        import logging
        logging.getLogger("alarm").warning(f"[Alarm] 插件 on_startup 异常（不影响加载）: {e}")


async def on_shutdown():
    """插件卸载钩子：停止闹钟后台检查协程（幂等）。"""
    try:
        await get_alarm_manager().stop()
    except Exception as e:
        import logging
        logging.getLogger("alarm").warning(f"[Alarm] 插件 on_shutdown 异常（不影响卸载）: {e}")


# ── 数据存储（直接文件读写，内置插件不走 kv 的 ContextVar 机制）──────


_DATA_DIR = None


def _get_data_dir():
    global _DATA_DIR
    if _DATA_DIR is None:
        d = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "plugins", "alarm")
        _DATA_DIR = os.path.normpath(d)
        os.makedirs(_DATA_DIR, exist_ok=True)
    return _DATA_DIR


def _read_data(filename: str) -> dict:
    path = os.path.join(_get_data_dir(), filename)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _write_data(filename: str, data: dict) -> None:
    path = os.path.join(_get_data_dir(), filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── 时间解析 ───────────────────────────────────────────────


def _parse_time(delay_str: str) -> _datetime | None:
    """解析用户输入的时间字符串。

    支持格式：
      - 相对时间："30秒"、"5分钟"、"2小时"、"1天"、"1周"
      - 绝对时间："14:30"（今天的 14:30，已过则明天）
      - 完整时间："2026-07-28 14:30"
    """
    delay_str = delay_str.strip()
    import re
    m = re.match(r"^(\d+)\s*(分|分钟|小时|天|周|月|秒)$", delay_str)
    if m:
        num = int(m.group(1))
        unit = m.group(2)
        now = _datetime.now()
        if unit in ('分', '分钟'):
            return now + _timedelta(minutes=num)
        elif unit == '小时':
            return now + _timedelta(hours=num)
        elif unit == '天':
            return now + _timedelta(days=num)
        elif unit == '周':
            return now + _timedelta(weeks=num)
        elif unit == '月':
            return now + _timedelta(days=num * 30)
        elif unit == '秒':
            return now + _timedelta(seconds=num)
    m = re.match(r"^(\d{1,2}):(\d{2})$", delay_str)
    if m:
        now = _datetime.now()
        t = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        if t <= now:
            t += _timedelta(days=1)
        return t
    m = re.match(r"^(\d{4}-\d{1,2}-\d{1,2})\s+(\d{1,2}):(\d{2})$", delay_str)
    if m:
        try:
            return _datetime.strptime(f"{m.group(1)} {m.group(2)}:{m.group(3)}", "%Y-%m-%d %H:%M")
        except ValueError:
            return None
    return None


# ── 操作历史记录 ───────────────────────────────────────────


def _log_history(device_key: str, action: str, detail: str) -> None:
    """记录闹钟操作历史（最多保留 200 条）。"""
    data = _read_data("history.json")
    history = data.get("history", [])
    history.append({
        "time": _datetime.now().isoformat(),
        "device_key": device_key[:16],
        "action": action,
        "detail": detail,
    })
    if len(history) > 200:
        history = history[-200:]
    data["history"] = history
    _write_data("history.json", data)


def _update_stats(action: str) -> None:
    """更新闹钟使用统计。"""
    data = _read_data("stats.json")
    today = _datetime.now().strftime("%Y-%m-%d")
    data["total_set"] = data.get("total_set", 0) + 1
    data["last_use"] = _datetime.now().isoformat()

    daily = data.get("daily", {})
    day = daily.get(today, {"set": 0, "cancel": 0})
    if action.startswith("set_") or action == "smart_alarm":
        day["set"] = day.get("set", 0) + 1
    else:
        day["cancel"] = day.get("cancel", 0) + 1
    daily[today] = day
    # 只保留最近 30 天
    if len(daily) > 30:
        keys = sorted(daily.keys())
        for k in keys[:-30]:
            del daily[k]
    data["daily"] = daily
    _write_data("stats.json", data)


# ── 工具函数 ───────────────────────────────────────────────


@tool()
async def set_reminder(text: str, time: str, repeat: str = "once", tool_manager=None) -> str:
    """设置一个提醒，到时间后设备会语音播报提醒内容。
    当用户说"提醒我xxx"、"记得xxx"、"待会儿提醒我"时调用。
    参数:
        text: 提醒内容
        time: 触发时间，支持"30秒"/"5分钟"/"14:30"/"2026-07-28 14:30"等格式（最小精度1秒）
        repeat: 重复模式 once/daily/weekly/monthly
    """
    if not tool_manager or not tool_manager.channel:
        return "设备未连接，无法设置提醒"
    if not device_is_online(tool_manager=tool_manager):
        return "设备当前不在线，建议等设备上线后再设置提醒"
    trigger_at = _parse_time(time)
    if not trigger_at:
        return f"无法解析时间: {time}"
    device_key = get_device_key(tool_manager)
    alarm_id = "reminder_" + generate_uuid()[:8]
    get_alarm_manager().add_alarm(AlarmItem(
        alarm_id=alarm_id, device_key=device_key,
        alarm_type="reminder", trigger_at=trigger_at, text=text, repeat=repeat,
    ))
    _log_history(device_key, "设置提醒", f"{text} @ {trigger_at.strftime('%m-%d %H:%M')} {repeat}")
    _update_stats("set_reminder")
    return f"提醒已设置：{text}，将在 {trigger_at.strftime('%Y-%m-%d %H:%M')} 触发{'' if repeat == 'once' else '（'+repeat+'）'}"


@tool()
async def set_alarm(time: str, repeat: str = "once", song: str = "", tool_manager=None) -> str:
    """设置闹钟，到时间后设备会播放音乐。
    当用户说"设个闹钟"、"几点叫我"、"早上叫我"时调用。设置提醒用 set_reminder 工具，不要用此工具。
    参数:
        time: 闹钟时间，支持"30秒"/"5分钟"/"14:30"/"2026-07-28 14:30"等格式（最小精度1秒）
        repeat: 重复模式 once/daily/weekly/monthly
        song: 闹钟铃声歌名，用户指定时填入（如"好运来"）。用户未指定歌名时留空，闹钟触发时将随机播放一首歌。
    """
    if not tool_manager or not tool_manager.channel:
        return "设备未连接，无法设置闹钟"
    if not device_is_online(tool_manager=tool_manager):
        return "设备当前不在线，建议等设备上线后再设置闹钟"
    trigger_at = _parse_time(time)
    if not trigger_at:
        return f"无法解析时间: {time}"
    device_key = get_device_key(tool_manager)
    alarm_id = "alarm_" + generate_uuid()[:8]
    get_alarm_manager().add_alarm(AlarmItem(
        alarm_id=alarm_id, device_key=device_key,
        alarm_type="alarm", trigger_at=trigger_at, text=song, repeat=repeat,
    ))
    song_display = f"播放「{song}」" if song else "随机播放音乐"
    _log_history(device_key, "设置闹钟", f"{song_display} @ {trigger_at.strftime('%m-%d %H:%M')} {repeat}")
    _update_stats("set_alarm")
    return f"闹钟已设置，将在 {trigger_at.strftime('%Y-%m-%d %H:%M')} {song_display}{'' if repeat == 'once' else '（'+repeat+'）'}"


@tool()
async def set_sleep_timer(time: str, tool_manager=None) -> str:
    """设置睡眠定时器，到时间后设备会停止音乐播放、故事等所有活动，进入休息状态。
    适用于听歌、听故事时定时关闭的场景。
    参数:
        time: 等待时间，支持"30秒"/"10分钟"/"1小时"等格式（最小精度1秒，仅支持相对时间）
    """
    if not tool_manager or not tool_manager.channel:
        return "设备未连接，无法设置睡眠定时器"
    if not device_is_online(tool_manager=tool_manager):
        return "设备当前不在线，无法设置睡眠定时器"
    trigger_at = _parse_time(time)
    if not trigger_at:
        return f"无法解析时间: {time}"
    device_key = get_device_key(tool_manager)
    alarm_id = "sleep_" + generate_uuid()[:8]
    get_alarm_manager().add_alarm(AlarmItem(
        alarm_id=alarm_id, device_key=device_key,
        alarm_type="sleep_timer", trigger_at=trigger_at,
        text="睡眠定时器", repeat="once",
    ))
    _log_history(device_key, "设置睡眠定时器", f"@ {trigger_at.strftime('%H:%M')}")
    _update_stats("set_sleep_timer")
    return f"睡眠定时器已设置，将在 {trigger_at.strftime('%H:%M')} 自动停止播放并进入休息状态"


@tool()
async def list_alarms(tool_manager=None) -> str:
    """查询已设置的闹钟、提醒和睡眠定时器列表。
    当用户问"查一下我的闹钟"、"我设了哪些提醒"、"有什么闹钟"、"还有多久"、"查看闹钟"时调用。
    返回结果中每条记录的 ID 字段即为 alarm_id，可用于 cancel_alarm 工具删除对应条目。"""
    device_key = get_device_key(tool_manager)
    alarms = get_alarm_manager().list_alarms(device_key)
    if not alarms:
        return "当前没有设置的闹钟或提醒"
    type_map = {"alarm": "闹钟", "reminder": "提醒", "sleep_timer": "睡眠定时器"}
    lines = []
    for a in alarms:
        type_text = type_map.get(a['type'], a['type'])
        song_text = f"铃声:{a['text']}" if a['text'] else "铃声:随机"
        lines.append(f"ID={a['id']} | {type_text} | {a['trigger_at']} | {song_text} | 重复:{a['repeat']}")
    return "\n".join(["当前闹钟/提醒列表："] + lines)


@tool()
async def cancel_alarm(alarm_id: str, tool_manager=None) -> str:
    """取消闹钟、提醒或睡眠定时器。
    参数 alarm_id 为条目 ID，请从 list_alarms 工具的返回结果中获取（格式为 ID=xxx 中的 xxx 部分）。
    如果用户说"删除所有闹钟"或"清空提醒"，请先调用 list_alarms 获取所有条目，然后逐个调用 cancel_alarm 删除。"""
    ok = get_alarm_manager().remove_alarm(alarm_id)
    if ok:
        _log_history(get_device_key(tool_manager), "取消", alarm_id[:20])
    return f"已取消: {alarm_id}" if ok else f"未找到: {alarm_id}"


# ════════════════════════════════════════════════════════════
# 新增功能
# ════════════════════════════════════════════════════════════


@tool()
async def smart_alarm(description: str, tool_manager=None) -> str:
    """智能闹钟/提醒：用自然语言描述，AI 自动解析并设置闹钟或提醒。
    当用户说"明天早上8点叫我去跑步"、"半小时后提醒我关火"、"每周一早上9点开晨会提醒"时调用。
    此工具会自动判断是设闹钟还是提醒，无需用户区分。
    参数:
        description: 自然语言描述，如"明天早上7点叫我起床"
    """
    if not tool_manager or not tool_manager.channel:
        return "设备未连接，无法设置闹钟"
    if not device_is_online(tool_manager=tool_manager):
        return "设备当前不在线，建议等设备上线后再设置"

    # 用 LLM 解析自然语言闹钟描述
    now = _datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
    parse_result = await llm_generate(
        f"当前时间：{now}\n"
        f"用户说：{description}\n\n"
        f"请解析出闹钟信息，严格按以下 JSON 格式返回（不要任何额外文字）：\n"
        f"{{\n"
        f'  "time": "解析后的时间，格式如 14:30 或 2026-07-28 14:30 或 5分钟",\n'
        f'  "text": "闹钟或提醒的内容描述",\n'
        f'  "type": "alarm 或 reminder",\n'
        f'  "repeat": "once 或 daily 或 weekly 或 monthly",\n'
        f'  "song": "闹钟铃声歌名，如「好运来」。用户没指定时填空字符串"\n'
        f"}}",
        tool_manager=tool_manager,
    )

    try:
        info = json_loads(parse_result.strip().strip("```json").strip("```").strip())
    except Exception:
        return f"我没理解你的闹钟需求，请说得简单一些，比如「明天早上8点叫我起床」"

    time_str = info.get("time", "")
    text = info.get("text", description)
    alarm_type = info.get("type", "reminder")
    repeat = info.get("repeat", "once")
    song = info.get("song", "")

    trigger_at = _parse_time(time_str)
    if not trigger_at:
        return f"无法解析时间「{time_str}」，试试说「5分钟后」或「14:30」"

    device_key = get_device_key(tool_manager)
    prefix = "alarm_" if alarm_type == "alarm" else "reminder_"
    alarm_id = prefix + generate_uuid()[:8]

    # 如果是闹钟类型：指定了歌名就用歌名，否则空字符串=随机播放
    actual_text = song if alarm_type == "alarm" and song else ("" if alarm_type == "alarm" else text)
    get_alarm_manager().add_alarm(AlarmItem(
        alarm_id=alarm_id, device_key=device_key,
        alarm_type=alarm_type, trigger_at=trigger_at, text=actual_text, repeat=repeat,
    ))

    type_text = "闹钟" if alarm_type == "alarm" else "提醒"
    song_display = f"，播放「{song}」" if song else ""
    _log_history(device_key, f"智能设置{type_text}", f"{text}{song_display} @ {trigger_at.strftime('%m-%d %H:%M')} {repeat}")
    _update_stats("smart_alarm")

    return (
        f"好的，已设置{type_text}：{text}{song_display}，"
        f"将在 {trigger_at.strftime('%Y-%m-%d %H:%M')} 触发"
        f"{'' if repeat == 'once' else '（每天重复）'}"
    )


@tool()
async def alarm_stats(tool_manager=None) -> str:
    """查看闹钟和提醒的使用统计，包括设置次数、最近一周的闹钟数量等。
    当用户问"我用了多少次闹钟"、"闹钟统计"、"使用情况"时调用。"""
    device_key = get_device_key(tool_manager)
    stats = _read_data("stats.json")
    history_data = _read_data("history.json")
    history = history_data.get("history", [])

    if not stats.get("total_set"):
        return "还没有闹钟使用记录，快去试试设置一个闹钟吧"

    total = stats.get("total_set", 0)
    last_use = stats.get("last_use", "未知")[:16]

    daily = stats.get("daily", {})
    recent_days = list(daily.keys())[-7:]
    recent_set = sum(daily.get(d, {}).get("set", 0) for d in recent_days)

    # 用 LLM 生成趣味统计总结
    summary = await llm_generate(
        f"闹钟使用数据：共设置过 {total} 次，最近一周设置了 {recent_set} 次，"
        f"最后使用时间 {last_use}。"
        f"请用一句话生成有趣的统计总结，活泼亲切一些。",
        tool_manager=tool_manager,
    )

    # 最近 5 条历史
    recent = []
    if isinstance(history, list):
        for h in history[-5:]:
            recent.append(f"  · {h.get('time', '')[:16]} {h.get('action', '')}：{h.get('detail', '')}")

    parts = [
        f"📊 闹钟统计",
        f"  共设置：{total} 次",
        f"  最近一周：{recent_set} 次",
        f"  最后使用：{last_use}",
        f"",
        f"  {summary}",
    ]
    if recent:
        parts.extend(["", "最近操作："] + recent)

    return "\n".join(parts)