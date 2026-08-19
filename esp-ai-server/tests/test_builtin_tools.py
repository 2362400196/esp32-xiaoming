"""
builtin_tools.py 单元测试

覆盖工具：
- get_current_time / get_current_date：时间日期工具
- set_volume / volume_down / volume_up / set_brightness：设备控制工具
- standby：待机（抛 StopPipeline）
- parse_lrc / fetch_lyrics：歌词解析与下载
- play_music：音乐播放（mock urllib + settings）
- test_device：设备测试（mock get_app）
- execute_lua / stop_lua / clear_screen：Lua 控制
- memory_store / memory_recall / memory_list / memory_update / memory_forget：长期记忆工具
- _resolve_device_id / _get_ltm_service 辅助函数

通过 mock channel / tool_manager / settings / urllib 避免真实网络和设备调用。
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.use_cases.builtin_tools import (
    _get_default_ltm_service,
    _get_ltm_service,
    _resolve_device_id,
    clear_screen,
    execute_lua,
    fetch_lyrics,
    get_current_date,
    get_current_time,
    memory_forget,
    memory_list,
    memory_recall,
    memory_store,
    memory_update,
    parse_lrc,
    play_music,
    set_brightness,
    set_volume,
    standby,
    stop_lua,
    test_device,
    volume_down,
    volume_up,
)
from src.use_cases.tools_system import StopPipeline


# ============================================================
# 时间日期工具
# ============================================================


class TestGetCurrentTime:
    """get_current_time：获取当前日期和时间"""

    def test_returns_formatted_string(self):
        result = get_current_time()
        assert isinstance(result, str)
        assert "年" in result
        assert "月" in result
        assert "日" in result
        assert "时" in result
        assert "分" in result

    def test_format_matches_pattern(self):
        result = get_current_time()
        # 格式应为 "YYYY年MM月DD日 HH时MM分"
        assert len(result) >= 14


class TestGetCurrentDate:
    """get_current_date：获取日期和星期"""

    def test_returns_formatted_string(self):
        result = get_current_date()
        assert isinstance(result, str)
        assert "年" in result
        assert "月" in result
        assert "日" in result

    def test_includes_weekday(self):
        result = get_current_date()
        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        assert any(w in result for w in weekdays)


# ============================================================
# 音量控制工具
# ============================================================


def _make_tool_manager_with_channel():
    """构造一个带 channel 的 mock tool_manager"""
    tm = MagicMock()
    tm.channel = MagicMock()
    tm.channel.send_json = AsyncMock()
    tm.channel.send_text = AsyncMock()
    tm.user_config = None
    return tm


class TestSetVolume:
    """set_volume：设置设备音量"""

    async def test_with_channel_sends_instruction(self):
        tm = _make_tool_manager_with_channel()
        result = await set_volume(80, tool_manager=tm)
        assert "80%" in result
        tm.channel.send_json.assert_awaited_once()
        sent = tm.channel.send_json.call_args.args[0]
        assert sent["type"] == "instruct"
        assert sent["command_id"] == "set_volume"
        assert sent["data"] == "0.8"

    async def test_without_channel_returns_message(self):
        result = await set_volume(50, tool_manager=None)
        assert "50%" in result
        assert "未连接设备" in result

    async def test_clamps_above_100(self):
        tm = _make_tool_manager_with_channel()
        result = await set_volume(150, tool_manager=tm)
        assert "100%" in result

    async def test_clamps_below_0(self):
        tm = _make_tool_manager_with_channel()
        result = await set_volume(-10, tool_manager=tm)
        assert "0%" in result

    async def test_mute(self):
        tm = _make_tool_manager_with_channel()
        result = await set_volume(0, tool_manager=tm)
        assert "0%" in result

    async def test_send_exception_returns_error_message(self):
        tm = _make_tool_manager_with_channel()
        tm.channel.send_json = AsyncMock(side_effect=RuntimeError("send fail"))
        result = await set_volume(50, tool_manager=tm)
        assert "设置音量失败" in result


class TestVolumeDown:
    """volume_down：调小音量"""

    async def test_with_channel(self):
        tm = _make_tool_manager_with_channel()
        result = await volume_down(tool_manager=tm)
        assert "调小" in result
        sent = tm.channel.send_json.call_args.args[0]
        assert sent["command_id"] == "subtract_volume"
        assert sent["data"] == "0.1"

    async def test_without_channel(self):
        result = await volume_down(tool_manager=None)
        assert "未连接设备" in result

    async def test_send_exception(self):
        tm = _make_tool_manager_with_channel()
        tm.channel.send_json = AsyncMock(side_effect=RuntimeError("fail"))
        result = await volume_down(tool_manager=tm)
        assert "失败" in result


class TestVolumeUp:
    """volume_up：调大音量"""

    async def test_with_channel(self):
        tm = _make_tool_manager_with_channel()
        result = await volume_up(tool_manager=tm)
        assert "调大" in result
        sent = tm.channel.send_json.call_args.args[0]
        assert sent["command_id"] == "add_volume"

    async def test_without_channel(self):
        result = await volume_up(tool_manager=None)
        assert "未连接设备" in result


class TestSetBrightness:
    """set_brightness：设置屏幕亮度"""

    async def test_with_channel(self):
        tm = _make_tool_manager_with_channel()
        result = await set_brightness(50, tool_manager=tm)
        assert "50%" in result
        sent = tm.channel.send_json.call_args.args[0]
        assert sent["command_id"] == "set_brightness"
        assert sent["data"] == "50"

    async def test_without_channel(self):
        result = await set_brightness(50, tool_manager=None)
        assert "未连接设备" in result

    async def test_clamps_values(self):
        tm = _make_tool_manager_with_channel()
        result = await set_brightness(200, tool_manager=tm)
        assert "100%" in result


# ============================================================
# standby 待机
# ============================================================


class TestStandby:
    """standby：设置设备待机"""

    async def test_with_channel_raises_stop_pipeline(self):
        tm = _make_tool_manager_with_channel()
        with pytest.raises(StopPipeline):
            await standby(tool_manager=tm)
        # 应发送 session_end 和 send_text
        tm.channel.send_json.assert_awaited()
        tm.channel.send_text.assert_awaited_with("session_end")

    async def test_without_channel_returns_message(self):
        result = await standby(tool_manager=None)
        assert "待机" in result


# ============================================================
# parse_lrc 歌词解析
# ============================================================


class TestParseLrc:
    """parse_lrc：解析 LRC 歌词文本"""

    def test_basic_line(self):
        lrc = "[01:23.45]这是一句歌词"
        result = parse_lrc(lrc)
        assert len(result) == 1
        assert result[0]["text"] == "这是一句歌词"
        # 1分23秒450毫秒
        assert result[0]["time"] == 1 * 60000 + 23 * 1000 + 450

    def test_without_fraction(self):
        lrc = "[01:23]歌词"
        result = parse_lrc(lrc)
        assert len(result) == 1
        assert result[0]["time"] == 83000

    def test_multiple_lines(self):
        lrc = "[00:01.00]第一行\n[00:03.00]第二行\n[00:02.00]第三行"
        result = parse_lrc(lrc)
        assert len(result) == 3
        # 应按时间排序
        assert result[0]["text"] == "第一行"
        assert result[1]["text"] == "第三行"
        assert result[2]["text"] == "第二行"

    def test_empty_lines_skipped(self):
        lrc = "[00:01.00]有内容\n\n[00:02.00]也有内容"
        result = parse_lrc(lrc)
        assert len(result) == 2

    def test_empty_text_skipped(self):
        lrc = "[00:01.00]\n[00:02.00]有内容"
        result = parse_lrc(lrc)
        assert len(result) == 1
        assert result[0]["text"] == "有内容"

    def test_empty_input(self):
        assert parse_lrc("") == []

    def test_no_timestamp_lines(self):
        lrc = "没有时间戳的行\n[00:01.00]有时间戳"
        result = parse_lrc(lrc)
        assert len(result) == 1

    def test_three_digit_fraction(self):
        lrc = "[00:01.123]测试"
        result = parse_lrc(lrc)
        assert len(result) == 1
        assert result[0]["time"] == 1000 + 123

    def test_whitespace_after_timestamp_stripped(self):
        lrc = "[00:01.00]   带空格的歌词"
        result = parse_lrc(lrc)
        assert result[0]["text"] == "带空格的歌词"


# ============================================================
# fetch_lyrics 歌词下载
# ============================================================


class TestFetchLyrics:
    """fetch_lyrics：下载并解析歌词"""

    def test_success(self):
        lrc_text = "[00:01.00]第一行\n[00:02.00]第二行"
        mock_resp = MagicMock()
        mock_resp.read.return_value = lrc_text.encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=None)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = fetch_lyrics("http://example.com/lyrics.lrc")
        assert len(result) == 2

    def test_failure_returns_empty(self):
        with patch("urllib.request.urlopen", side_effect=RuntimeError("network error")):
            result = fetch_lyrics("http://example.com/bad")
        assert result == []


# ============================================================
# play_music 音乐播放
# ============================================================


class TestPlayMusic:
    """play_music：搜索并播放歌曲"""

    def _make_tm_with_music_config(self, api_url="http://music.api", lyrics_offset=0):
        tm = MagicMock()
        tm.channel = MagicMock()
        tm.channel.send_json = AsyncMock()
        tm.user_config = MagicMock()
        tm.user_config.music_config = {
            "api_url": api_url,
            "lyrics_offset": lyrics_offset,
        }
        return tm

    async def test_no_api_url_returns_message(self):
        tm = MagicMock()
        tm.channel = None
        tm.user_config = None
        settings = MagicMock()
        settings.music.api_url = ""
        settings.music.lyrics_offset = 0
        with patch("src.use_cases.builtin_tools.get_settings", return_value=settings):
            result = await play_music("歌", tool_manager=tm)
        assert "未配置" in result or "音乐服务" in result

    async def test_api_request_failure_returns_message(self):
        tm = self._make_tm_with_music_config()
        with patch("urllib.request.urlopen", side_effect=Exception("network error")):
            result = await play_music("歌", tool_manager=tm)
        assert "不可用" in result

    async def test_url_error_returns_message(self):
        import urllib.error
        tm = self._make_tm_with_music_config()
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("fail")):
            result = await play_music("歌", tool_manager=tm)
        assert "不可用" in result

    async def test_song_not_found(self):
        tm = self._make_tm_with_music_config()
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"success": False}).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=None)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = await play_music("不存在的歌", tool_manager=tm)
        assert "未找到" in result

    async def test_no_audio_url(self):
        tm = self._make_tm_with_music_config()
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"success": True, "audio_url": ""}).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=None)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = await play_music("歌", tool_manager=tm)
        assert "没有可播放" in result

    async def test_success_with_channel_raises_stop_pipeline(self):
        tm = self._make_tm_with_music_config()
        api_data = {
            "success": True,
            "audio_url": "http://audio.url",
            "title": "歌名",
            "artist": "歌手",
            "lyric_url": "",
            "duration": 180,
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(api_data).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=None)
        with patch("urllib.request.urlopen", return_value=mock_resp), \
                patch("src.use_cases.builtin_tools.fetch_lyrics", return_value=[]):
            with pytest.raises(StopPipeline):
                await play_music("歌", tool_manager=tm)
        # 应发送 play_music 和 music_meta 指令
        sent_commands = [c.args[0]["command_id"] for c in tm.channel.send_json.call_args_list]
        assert "play_music" in sent_commands
        assert "music_meta" in sent_commands

    async def test_success_with_lyrics(self):
        tm = self._make_tm_with_music_config(lyrics_offset=100)
        api_data = {
            "success": True,
            "audio_url": "http://audio.url",
            "title": "歌名",
            "artist": "歌手",
            "lyric_url": "http://lyric.url",
            "duration": 180,
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(api_data).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=None)
        lyrics = [{"time": 1000, "text": "第一行"}, {"time": 2000, "text": "第二行"}]
        with patch("urllib.request.urlopen", return_value=mock_resp), \
                patch("src.use_cases.builtin_tools.fetch_lyrics", return_value=lyrics):
            with pytest.raises(StopPipeline):
                await play_music("歌", tool_manager=tm)
        # 应发送 lyric_line 指令
        sent_commands = [c.args[0]["command_id"] for c in tm.channel.send_json.call_args_list]
        assert "lyric_line" in sent_commands

    async def test_success_without_channel_returns_message(self):
        tm = MagicMock()
        tm.channel = None
        tm.user_config = None
        settings = MagicMock()
        settings.music.api_url = "http://music.api"
        settings.music.lyrics_offset = 0
        api_data = {
            "success": True,
            "audio_url": "http://audio.url",
            "title": "歌名",
            "artist": "歌手",
            "lyric_url": "",
            "duration": 180,
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(api_data).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=None)
        with patch("src.use_cases.builtin_tools.get_settings", return_value=settings), \
                patch("urllib.request.urlopen", return_value=mock_resp), \
                patch("src.use_cases.builtin_tools.fetch_lyrics", return_value=[]):
            result = await play_music("歌", tool_manager=tm)
        assert "未连接设备" in result


# ============================================================
# test_device 设备测试
# ============================================================


class TestTestDevice:
    """test_device：设备测试工具"""

    async def test_without_channel_returns_message(self):
        result = await test_device(channel=None)
        assert "未连接设备" in result

    async def test_with_channel_no_app_returns_message(self):
        channel = MagicMock()
        with patch("src.infrastructure.web.get_app", return_value=None):
            result = await test_device(channel=channel)
        assert "未连接设备" in result

    async def test_with_channel_no_speaker_returns_message(self):
        channel = MagicMock()
        app = MagicMock()
        app.state.speaker = None
        with patch("src.infrastructure.web.get_app", return_value=app):
            result = await test_device(channel=channel)
        assert "未连接设备" in result

    async def test_with_speaker_raises_stop_pipeline(self):
        channel = MagicMock()
        ctx = MagicMock()
        fsm = MagicMock()
        app = MagicMock()
        app.state.speaker = MagicMock()
        app.state.speaker.speak_direct = AsyncMock()
        with patch("src.infrastructure.web.get_app", return_value=app):
            with pytest.raises(StopPipeline):
                await test_device(channel=channel, ctx=ctx, fsm=fsm)
        app.state.speaker.speak_direct.assert_awaited_once()


# ============================================================
# Lua 控制工具
# ============================================================


class TestExecuteLua:
    """execute_lua：在设备上运行 Lua 脚本"""

    async def test_with_channel_sends_code(self):
        tm = _make_tool_manager_with_channel()
        result = await execute_lua("print('hello')", tool_manager=tm)
        assert "已发送" in result or "成功" in result
        sent = tm.channel.send_json.call_args.args[0]
        assert sent["command_id"] == "execute_lua"
        assert sent["data"] == "print('hello')"

    async def test_without_channel(self):
        result = await execute_lua("code", tool_manager=None)
        assert "未连接设备" in result

    async def test_send_exception(self):
        tm = _make_tool_manager_with_channel()
        tm.channel.send_json = AsyncMock(side_effect=RuntimeError("fail"))
        result = await execute_lua("code", tool_manager=tm)
        assert "失败" in result


class TestStopLua:
    """stop_lua：停止设备上的 Lua 脚本"""

    async def test_with_channel(self):
        tm = _make_tool_manager_with_channel()
        result = await stop_lua(tool_manager=tm)
        assert "停止" in result
        sent = tm.channel.send_json.call_args.args[0]
        assert sent["command_id"] == "stop_lua"

    async def test_without_channel(self):
        result = await stop_lua(tool_manager=None)
        assert "未连接设备" in result

    async def test_send_exception(self):
        tm = _make_tool_manager_with_channel()
        tm.channel.send_json = AsyncMock(side_effect=RuntimeError("fail"))
        result = await stop_lua(tool_manager=tm)
        assert "失败" in result


class TestClearScreen:
    """clear_screen：清除屏幕 Lua 绘制"""

    async def test_with_channel(self):
        tm = _make_tool_manager_with_channel()
        result = await clear_screen(tool_manager=tm)
        assert "清屏" in result
        sent = tm.channel.send_json.call_args.args[0]
        assert sent["command_id"] == "clear_screen"

    async def test_without_channel(self):
        result = await clear_screen(tool_manager=None)
        assert "未连接设备" in result

    async def test_send_exception(self):
        tm = _make_tool_manager_with_channel()
        tm.channel.send_json = AsyncMock(side_effect=RuntimeError("fail"))
        result = await clear_screen(tool_manager=tm)
        assert "失败" in result


# ============================================================
# 长期记忆工具
# ============================================================


def _make_tm_with_ltm(device_id="d1"):
    """构造一个带 ltm_service 的 mock tool_manager"""
    tm = MagicMock()
    tm.channel = None
    tm.user_config = MagicMock()
    tm.user_config.device_id = device_id
    tm.user_config.key = device_id
    tm.ltm_service = MagicMock()
    tm.ltm_service.store = AsyncMock()
    tm.ltm_service.recall = AsyncMock()
    tm.ltm_service.list_all = AsyncMock()
    tm.ltm_service.update = AsyncMock()
    tm.ltm_service.forget = AsyncMock()
    return tm


class TestResolveDeviceId:
    """_resolve_device_id：自动填充 device_id"""

    def test_returns_explicit_device_id(self):
        assert _resolve_device_id("explicit", None) == "explicit"

    def test_from_user_config_device_id(self):
        tm = MagicMock()
        tm.user_config = MagicMock()
        tm.user_config.device_id = "from_config"
        tm.user_config.key = None
        assert _resolve_device_id("", tm) == "from_config"

    def test_from_user_config_key(self):
        tm = MagicMock()
        tm.user_config = MagicMock()
        tm.user_config.device_id = None
        tm.user_config.key = "from_key"
        assert _resolve_device_id("", tm) == "from_key"

    def test_returns_empty_when_no_config(self):
        assert _resolve_device_id("", None) == ""

    def test_returns_empty_when_config_has_no_id(self):
        tm = MagicMock()
        tm.user_config = MagicMock()
        tm.user_config.device_id = None
        tm.user_config.key = None
        assert _resolve_device_id("", tm) == ""


class TestGetLtmService:
    """_get_ltm_service：获取 LTM 服务"""

    def test_returns_from_tool_manager(self):
        tm = MagicMock()
        tm.ltm_service = "injected_service"
        assert _get_ltm_service(tm) == "injected_service"

    def test_returns_default_when_no_tm(self):
        with patch("src.use_cases.builtin_tools._get_default_ltm_service", return_value="default"):
            assert _get_ltm_service(None) == "default"

    def test_returns_default_when_no_ltm_attr(self):
        tm = MagicMock(spec=[])  # 无 ltm_service 属性
        with patch("src.use_cases.builtin_tools._get_default_ltm_service", return_value="default"):
            assert _get_ltm_service(tm) == "default"

    def test_returns_default_when_ltm_none(self):
        tm = MagicMock()
        tm.ltm_service = None
        with patch("src.use_cases.builtin_tools._get_default_ltm_service", return_value="default"):
            assert _get_ltm_service(tm) == "default"


class TestGetDefaultLtmService:
    """_get_default_ltm_service：创建默认 LTM 服务单例"""

    def test_returns_singleton(self):
        # 重置单例
        import src.use_cases.builtin_tools as bt
        bt._ltm_service = None
        s1 = _get_default_ltm_service()
        s2 = _get_default_ltm_service()
        assert s1 is s2


class TestMemoryStore:
    """memory_store：存储长期记忆"""

    async def test_no_device_id_returns_error(self):
        tm = MagicMock()
        tm.user_config = None
        result = await memory_store("内容", tool_manager=tm)
        assert "无法获取设备ID" in result

    async def test_store_new(self):
        tm = _make_tm_with_ltm()
        tm.ltm_service.store = AsyncMock(return_value=("mem-1", True))
        result = await memory_store("我喜欢蓝色", tags="颜色", keywords="蓝色", tool_manager=tm)
        assert "已记住" in result
        tm.ltm_service.store.assert_awaited_once()

    async def test_store_dedup(self):
        tm = _make_tm_with_ltm()
        tm.ltm_service.store = AsyncMock(return_value=("mem-1", False))
        result = await memory_store("我喜欢蓝色", tool_manager=tm)
        assert "已存在" in result

    async def test_tags_and_keywords_parsed(self):
        tm = _make_tm_with_ltm()
        tm.ltm_service.store = AsyncMock(return_value=("mem-1", True))
        await memory_store("内容", tags="a,b,c", keywords="x,y,z", tool_manager=tm)
        item = tm.ltm_service.store.call_args.args[0]
        assert item.tags == ["a", "b", "c"]
        assert item.keywords == ["x", "y", "z"]

    async def test_explicit_device_id_overrides_config(self):
        tm = _make_tm_with_ltm("config_id")
        tm.ltm_service.store = AsyncMock(return_value=("mem-1", True))
        await memory_store("内容", device_id="explicit_id", tool_manager=tm)
        item = tm.ltm_service.store.call_args.args[0]
        assert item.device_id == "explicit_id"


class TestMemoryRecall:
    """memory_recall：召回长期记忆"""

    async def test_no_device_id_returns_error(self):
        tm = MagicMock()
        tm.user_config = None
        result = await memory_recall("标签", tool_manager=tm)
        assert "无法获取设备ID" in result

    async def test_recall_found(self):
        tm = _make_tm_with_ltm()
        item = MagicMock()
        item.memory_id = "mem-1"
        item.content = "记忆内容"
        item.tags = ["标签"]
        tm.ltm_service.recall = AsyncMock(return_value=[item])
        result = await memory_recall("标签", tool_manager=tm)
        assert "1 条" in result
        assert "记忆内容" in result

    async def test_recall_not_found(self):
        tm = _make_tm_with_ltm()
        tm.ltm_service.recall = AsyncMock(return_value=[])
        result = await memory_recall("标签", tool_manager=tm)
        assert "未找到" in result

    async def test_labels_parsed(self):
        tm = _make_tm_with_ltm()
        tm.ltm_service.recall = AsyncMock(return_value=[])
        await memory_recall("a,b,c", tool_manager=tm)
        query = tm.ltm_service.recall.call_args.args[0]
        assert tuple(query.summary_labels) == ("a", "b", "c")


class TestMemoryList:
    """memory_list：列出长期记忆"""

    async def test_no_device_id_returns_error(self):
        tm = MagicMock()
        tm.user_config = None
        result = await memory_list(tool_manager=tm)
        assert "无法获取设备ID" in result

    async def test_list_with_items(self):
        tm = _make_tm_with_ltm()
        item = MagicMock()
        item.memory_id = "mem-1"
        item.content = "内容"
        item.source = "manual"
        tm.ltm_service.list_all = AsyncMock(return_value=[item])
        result = await memory_list(tool_manager=tm)
        assert "1 条" in result
        assert "内容" in result

    async def test_list_empty(self):
        tm = _make_tm_with_ltm()
        tm.ltm_service.list_all = AsyncMock(return_value=[])
        result = await memory_list(tool_manager=tm)
        assert "暂无" in result


class TestMemoryUpdate:
    """memory_update：更新长期记忆"""

    async def test_no_device_id_returns_error(self):
        tm = MagicMock()
        tm.user_config = None
        result = await memory_update("mem-1", tool_manager=tm)
        assert "无法获取设备ID" in result

    async def test_update_success(self):
        tm = _make_tm_with_ltm()
        tm.ltm_service.update = AsyncMock(return_value=True)
        result = await memory_update("mem-1", content="新内容", tags="a,b", tool_manager=tm)
        assert "已更新" in result
        patch_dict = tm.ltm_service.update.call_args.args[1]
        assert patch_dict["content"] == "新内容"
        assert patch_dict["tags"] == ["a", "b"]

    async def test_update_not_found(self):
        tm = _make_tm_with_ltm()
        tm.ltm_service.update = AsyncMock(return_value=False)
        result = await memory_update("mem-1", tool_manager=tm)
        assert "未找到" in result

    async def test_partial_update_only_content(self):
        tm = _make_tm_with_ltm()
        tm.ltm_service.update = AsyncMock(return_value=True)
        await memory_update("mem-1", content="新内容", tool_manager=tm)
        patch_dict = tm.ltm_service.update.call_args.args[1]
        assert patch_dict == {"content": "新内容"}


class TestMemoryForget:
    """memory_forget：删除长期记忆"""

    async def test_no_device_id_returns_error(self):
        tm = MagicMock()
        tm.user_config = None
        result = await memory_forget("mem-1", tool_manager=tm)
        assert "无法获取设备ID" in result

    async def test_forget_success(self):
        tm = _make_tm_with_ltm()
        item = MagicMock()
        item.content = "被删除的内容"
        tm.ltm_service.forget = AsyncMock(return_value=item)
        result = await memory_forget("mem-1", tool_manager=tm)
        assert "已删除" in result

    async def test_forget_not_found(self):
        tm = _make_tm_with_ltm()
        tm.ltm_service.forget = AsyncMock(return_value=None)
        result = await memory_forget("mem-1", tool_manager=tm)
        assert "未找到" in result
