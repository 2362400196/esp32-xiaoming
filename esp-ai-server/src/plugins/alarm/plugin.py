import uuid as _uuid
from datetime import datetime as _datetime, timedelta as _timedelta

from src.use_cases.alarm_manager import AlarmItem, get_alarm_manager
from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import get_device_key

def _parse_time(delay_str: str) -> _datetime | None:
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


@tool()
async def set_reminder(text: str, time: str, repeat: str = "once", tool_manager=None) -> str:
    """设置一个提醒，到时间后设备会语音播报提醒内容，同时发送微信消息通知。
    参数:
        text: 提醒内容
        time: 触发时间，支持"30秒"/"5分钟"/"14:30"/"2026-07-28 14:30"等格式（最小精度1秒）
        repeat: 重复模式 once/daily/weekly/monthly
    """
    if not tool_manager or not tool_manager.channel:
        return "设备未连接，无法设置提醒"
    trigger_at = _parse_time(time)
    if not trigger_at:
        return f"无法解析时间: {time}"
    device_key = get_device_key(tool_manager)
    alarm_id = "reminder_" + _uuid.uuid4().hex[:8]
    get_alarm_manager().add_alarm(AlarmItem(alarm_id=alarm_id, device_key=device_key, alarm_type="reminder", trigger_at=trigger_at, text=text, repeat=repeat))
    return f"提醒已设置：{text}，将在 {trigger_at.strftime('%Y-%m-%d %H:%M')} 触发{'' if repeat == 'once' else '（'+repeat+'）'}"


@tool()
async def set_alarm(time: str, repeat: str = "once", song: str = "", tool_manager=None) -> str:
    """设置闹钟，到时间后设备会播放音乐。
    参数:
        time: 闹钟时间，支持"30秒"/"5分钟"/"14:30"/"2026-07-28 14:30"等格式（最小精度1秒）
        repeat: 重复模式 once/daily/weekly/monthly
        song: 闹钟铃声歌名，用户指定时填入（如"好运来"）。用户未指定歌名时留空，闹钟触发时将随机播放一首歌。
    """
    if not tool_manager or not tool_manager.channel:
        return "设备未连接，无法设置闹钟"
    trigger_at = _parse_time(time)
    if not trigger_at:
        return f"无法解析时间: {time}"
    device_key = get_device_key(tool_manager)
    alarm_id = "alarm_" + _uuid.uuid4().hex[:8]
    get_alarm_manager().add_alarm(AlarmItem(alarm_id=alarm_id, device_key=device_key, alarm_type="alarm", trigger_at=trigger_at, text=song, repeat=repeat))
    song_display = f"播放「{song}」" if song else "随机播放音乐"
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
    trigger_at = _parse_time(time)
    if not trigger_at:
        return f"无法解析时间: {time}"
    device_key = get_device_key(tool_manager)
    alarm_id = "sleep_" + _uuid.uuid4().hex[:8]
    get_alarm_manager().add_alarm(AlarmItem(
        alarm_id=alarm_id,
        device_key=device_key,
        alarm_type="sleep_timer",
        trigger_at=trigger_at,
        text="睡眠定时器",
        repeat="once",
    ))
    return f"睡眠定时器已设置，将在 {trigger_at.strftime('%H:%M')} 自动停止播放并进入休息状态"


@tool()
async def list_alarms(tool_manager=None) -> str:
    """列出当前设备所有闹钟、提醒和睡眠定时器。
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
    return f"已取消: {alarm_id}" if ok else f"未找到: {alarm_id}"
