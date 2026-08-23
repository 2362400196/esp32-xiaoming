"""SDK 音乐播放 - 向设备推送音乐播放指令"""

import json
import re

from src.infrastructure.plugin_security import require_permission
from src.use_cases.sdk.device import send_instruct
from src.use_cases.sdk.http import http_request


async def play_music_url(url: str, title: str = "", artist: str = "",
                          duration: int = 0, device_key: str = "",
                          lyric_url: str = "", lyrics_offset: int = 0) -> str:
    """向设备发送音乐播放指令。

    传入一个可直接播放的音频 URL，即可让设备播放该音乐。
    支持同时发送歌曲信息和歌词，适合从其他插件（如闹钟）调用。

    Args:
        url: 音频文件 URL（必填，如 http://192.168.1.100:2233/music/xxx.mp3）
        title: 歌曲标题（可选，默认空字符串）
        artist: 歌手名称（可选，默认空字符串）
        duration: 歌曲时长秒数（可选，默认 0）
        device_key: 设备标识（可选，不传时自动选择第一个在线设备）
        lyric_url: 歌词文件 URL（可选，会自动下载并逐行推送）
        lyrics_offset: 歌词时间偏移毫秒（可选，默认 0）

    Returns:
        成功返回 "ok"，失败返回错误描述字符串
    """
    require_permission("device", "发送音乐播放指令")
    from src.infrastructure.device_api import get_device_registry

    registry = get_device_registry()
    if not registry:
        return "设备注册表不可用"

    channel = None
    if device_key:
        device = registry.resolve(device_key)
        if device:
            channel = device.get("channel")
    else:
        for did in registry.get_all_ids():
            device = registry.get(did)
            if device and device.get("channel"):
                try:
                    ch = device["channel"]
                    await ch.send_json({"type": "ping"})
                    channel = ch
                    break
                except Exception:
                    continue

    if not channel:
        return "没有可用的在线设备"

    try:
        await send_instruct(channel, "play_music", url)
    except Exception as e:
        return f"发送播放指令失败: {e}"

    if title or artist or lyric_url or duration:
        try:
            await send_instruct(channel, "music_meta", json.dumps(
                {
                    "title": title or "",
                    "artist": artist or "",
                    "duration": duration,
                    "lyric_url": lyric_url or "",
                    "lyric_count": 0,
                    "lyric_offset_ms": lyrics_offset,
                },
                ensure_ascii=False,
            ))
        except Exception as e:
            return f"歌曲信息已发送，但元数据推送失败: {e}"

    if lyric_url:
        try:
            lyrics = await _fetch_lyrics_sdk(lyric_url)
            for i, line in enumerate(lyrics):
                await send_instruct(channel, "lyric_line", json.dumps(
                    {"index": i, "time": line["time"] + lyrics_offset, "text": line["text"]},
                    ensure_ascii=False,
                ))
        except Exception:
            pass

    return "ok"


async def _fetch_lyrics_sdk(lyric_url: str) -> list:
    """下载并解析 LRC 歌词（仅供 play_music_url 内部使用）。"""
    try:
        resp, err = await http_request("GET", lyric_url, timeout=6)
        if err:
            return []
        lrc_text = resp.text
        result = []
        pattern = re.compile(r"\[(\d{1,3}):(\d{2})(?:\.(\d{2,3}))?\]\s*(.*)")
        for line in lrc_text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            m = pattern.match(line)
            if m:
                minutes = int(m.group(1))
                seconds = int(m.group(2))
                fraction = m.group(3) or "0"
                fraction_ms = int(fraction) * (100 if len(fraction) == 1 else 10 if len(fraction) == 2 else 1)
                time_ms = minutes * 60000 + seconds * 1000 + fraction_ms
                text = m.group(4).strip()
                if text:
                    result.append({"time": time_ms, "text": text})
        result.sort(key=lambda x: x["time"])
        return result
    except Exception:
        return []