"""
内置插件工具单元测试（src/plugins/* 迁移版）

原 src/use_cases/builtin_tools.py 的函数已迁移至 src/plugins/ 各插件模块，
本文件直接测试迁移后的插件实现。覆盖：

- system_basic：get_current_time / get_current_date / set_volume / volume_down /
  volume_up / set_brightness / standby / get_volume / get_brightness
- media_player：_fetch_lyrics_sdk（LRC 下载与解析，已从插件迁移至 SDK）/ play_music
- device_control：test_device / execute_lua / stop_lua / clear_screen
- memory：memory_store / memory_recall / memory_list / memory_update / memory_forget

通过 mock channel / tool_manager / http_request / request_device_result /
get_settings 避免真实网络和设备调用；权限敏感调用通过 set_plugin_context
模拟插件 manifest 权限上下文（与 tools_system.call_tool 的生产注入一致）。
"""
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.plugin_security import reset_plugin_context, set_plugin_context
from src.plugins.device_control.plugin import clear_screen, execute_lua, stop_lua, test_device
from src.plugins.media_player.plugin import play_music
from src.use_cases.sdk.music import _fetch_lyrics_sdk
from src.plugins.memory.plugin import (
    memory_forget,
    memory_list,
    memory_recall,
    memory_store,
    memory_update,
)
from src.plugins.system_basic.plugin import (
    get_brightness,
    get_current_date,
    get_current_time,
    get_volume,
    set_brightness,
    set_volume,
    standby,
    volume_down,
    volume_up,
)
from src.use_cases.tools_system import StopPipeline


@contextmanager
def _plugin_ctx(plugin: str, permissions: list[str]):
    """模拟插件 manifest 权限上下文（与生产 tools_system.call_tool 一致）。"""
    token = set_plugin_context(plugin, permissions)
    try:
        yield
    finally:
        reset_plugin_context(token)


# ============================================================
# 时间日期工具（system_basic）
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
# 音量控制工具（system_basic）
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
        with _plugin_ctx("system_basic", ["device"]):
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
        assert "设备未连接" in result

    async def test_clamps_above_100(self):
        tm = _make_tool_manager_with_channel()
        with _plugin_ctx("system_basic", ["device"]):
            result = await set_volume(150, tool_manager=tm)
        assert "100%" in result

    async def test_clamps_below_0(self):
        tm = _make_tool_manager_with_channel()
        with _plugin_ctx("system_basic", ["device"]):
            result = await set_volume(-10, tool_manager=tm)
        assert "0%" in result

    async def test_mute(self):
        tm = _make_tool_manager_with_channel()
        with _plugin_ctx("system_basic", ["device"]):
            result = await set_volume(0, tool_manager=tm)
        assert "0%" in result

    async def test_send_exception_returns_error_message(self):
        tm = _make_tool_manager_with_channel()
        tm.channel.send_json = AsyncMock(side_effect=RuntimeError("send fail"))
        with _plugin_ctx("system_basic", ["device"]):
            result = await set_volume(50, tool_manager=tm)
        assert "50%" in result
        assert "发送失败" in result

    async def test_without_permission_declared(self):
        tm = _make_tool_manager_with_channel()
        with _plugin_ctx("system_basic", []):
            result = await set_volume(50, tool_manager=tm)
        assert "设备指令权限未声明" in result


class TestVolumeDown:
    """volume_down：调小音量"""

    async def test_with_channel(self):
        tm = _make_tool_manager_with_channel()
        with _plugin_ctx("system_basic", ["device"]):
            result = await volume_down(tool_manager=tm)
        assert "调小" in result
        sent = tm.channel.send_json.call_args.args[0]
        assert sent["command_id"] == "subtract_volume"
        assert sent["data"] == "0.1"

    async def test_without_channel(self):
        result = await volume_down(tool_manager=None)
        assert "设备未连接" in result

    async def test_send_exception(self):
        tm = _make_tool_manager_with_channel()
        tm.channel.send_json = AsyncMock(side_effect=RuntimeError("fail"))
        with _plugin_ctx("system_basic", ["device"]):
            result = await volume_down(tool_manager=tm)
        assert "失败" in result


class TestVolumeUp:
    """volume_up：调大音量"""

    async def test_with_channel(self):
        tm = _make_tool_manager_with_channel()
        with _plugin_ctx("system_basic", ["device"]):
            result = await volume_up(tool_manager=tm)
        assert "调大" in result
        sent = tm.channel.send_json.call_args.args[0]
        assert sent["command_id"] == "add_volume"

    async def test_without_channel(self):
        result = await volume_up(tool_manager=None)
        assert "设备未连接" in result


class TestSetBrightness:
    """set_brightness：设置屏幕亮度"""

    async def test_with_channel(self):
        tm = _make_tool_manager_with_channel()
        with _plugin_ctx("system_basic", ["device"]):
            result = await set_brightness(50, tool_manager=tm)
        assert "50%" in result
        sent = tm.channel.send_json.call_args.args[0]
        assert sent["command_id"] == "set_brightness"
        assert sent["data"] == "50"

    async def test_without_channel(self):
        result = await set_brightness(50, tool_manager=None)
        assert "设备未连接" in result

    async def test_clamps_values(self):
        tm = _make_tool_manager_with_channel()
        with _plugin_ctx("system_basic", ["device"]):
            result = await set_brightness(200, tool_manager=tm)
        assert "100%" in result


# ============================================================
# standby 待机（system_basic）
# ============================================================


class TestStandby:
    """standby：设置设备待机"""

    async def test_with_channel_raises_stop_pipeline(self):
        tm = _make_tool_manager_with_channel()
        with _plugin_ctx("system_basic", ["device"]):
            with pytest.raises(StopPipeline):
                await standby(tool_manager=tm)
        # 应发送 session_end 和 send_text
        tm.channel.send_json.assert_awaited()
        tm.channel.send_text.assert_awaited_with("session_end")

    async def test_without_channel_returns_message(self):
        result = await standby(tool_manager=None)
        assert "待机" in result


# ============================================================
# 设备状态查询（system_basic）
# ============================================================


class TestGetVolume:
    """get_volume：获取设备当前音量"""

    async def test_with_device_reply(self):
        tm = _make_tool_manager_with_channel()
        with _plugin_ctx("system_basic", ["device"]), \
                patch("src.plugins.system_basic.plugin.request_device_result",
                      AsyncMock(return_value=("volume=80", "ok", ""))):
            result = await get_volume(tool_manager=tm)
        assert "80%" in result

    async def test_offline(self):
        tm = _make_tool_manager_with_channel()
        with patch("src.plugins.system_basic.plugin.request_device_result",
                   AsyncMock(return_value=("", "offline", "设备未连接"))):
            result = await get_volume(tool_manager=tm)
        assert "设备未连接" in result

    async def test_timeout(self):
        tm = _make_tool_manager_with_channel()
        with _plugin_ctx("system_basic", ["device"]), \
                patch("src.plugins.system_basic.plugin.request_device_result",
                      AsyncMock(return_value=("", "timeout", "设备未在 5 秒内响应"))):
            result = await get_volume(tool_manager=tm)
        assert "5 秒" in result


class TestGetBrightness:
    """get_brightness：获取设备屏幕亮度"""

    async def test_with_device_reply(self):
        tm = _make_tool_manager_with_channel()
        with _plugin_ctx("system_basic", ["device"]), \
                patch("src.plugins.system_basic.plugin.request_device_result",
                      AsyncMock(return_value=("brightness=60", "ok", ""))):
            result = await get_brightness(tool_manager=tm)
        assert "60%" in result


# ============================================================
# _fetch_lyrics_sdk 歌词下载与 LRC 解析（media_player -> SDK）
# ============================================================


def _fake_http_response(text=""):
    resp = MagicMock()
    resp.text = text
    return resp


async def _parse_lrc(lrc_text: str) -> list:
    """通过 SDK 的 _fetch_lyrics_sdk 解析 LRC 文本（原插件 parse_lrc 已迁移至此）。"""
    with patch("src.use_cases.sdk.music.http_request",
               AsyncMock(return_value=(_fake_http_response(lrc_text), None))):
        return await _fetch_lyrics_sdk("http://example.com/lyrics.lrc")


class TestParseLrc:
    """_fetch_lyrics_sdk：解析 LRC 歌词文本（原插件 parse_lrc 功能已迁移至 SDK）"""

    async def test_basic_line(self):
        result = await _parse_lrc("[01:23.45]这是一句歌词")
        assert len(result) == 1
        assert result[0]["text"] == "这是一句歌词"
        # 1分23秒450毫秒
        assert result[0]["time"] == 1 * 60000 + 23 * 1000 + 450

    async def test_without_fraction(self):
        result = await _parse_lrc("[01:23]歌词")
        assert len(result) == 1
        assert result[0]["time"] == 83000

    async def test_multiple_lines(self):
        lrc = "[00:01.00]第一行\n[00:03.00]第二行\n[00:02.00]第三行"
        result = await _parse_lrc(lrc)
        assert len(result) == 3
        # 应按时间排序
        assert result[0]["text"] == "第一行"
        assert result[1]["text"] == "第三行"
        assert result[2]["text"] == "第二行"

    async def test_empty_lines_skipped(self):
        lrc = "[00:01.00]有内容\n\n[00:02.00]也有内容"
        result = await _parse_lrc(lrc)
        assert len(result) == 2

    async def test_empty_text_skipped(self):
        lrc = "[00:01.00]\n[00:02.00]有内容"
        result = await _parse_lrc(lrc)
        assert len(result) == 1
        assert result[0]["text"] == "有内容"

    async def test_empty_input(self):
        assert await _parse_lrc("") == []

    async def test_no_timestamp_lines(self):
        lrc = "没有时间戳的行\n[00:01.00]有时间戳"
        result = await _parse_lrc(lrc)
        assert len(result) == 1

    async def test_three_digit_fraction(self):
        result = await _parse_lrc("[00:01.123]测试")
        assert len(result) == 1
        assert result[0]["time"] == 1000 + 123

    async def test_whitespace_after_timestamp_stripped(self):
        result = await _parse_lrc("[00:01.00]   带空格的歌词")
        assert result[0]["text"] == "带空格的歌词"


# ============================================================
# _fetch_lyrics_sdk 歌词下载（media_player -> SDK）
# ============================================================


class TestFetchLyrics:
    """_fetch_lyrics_sdk：下载并解析歌词"""

    async def test_success(self):
        lrc_text = "[00:01.00]第一行\n[00:02.00]第二行"
        result = await _parse_lrc(lrc_text)
        assert len(result) == 2

    async def test_failure_returns_empty(self):
        with patch("src.use_cases.sdk.music.http_request",
                   AsyncMock(return_value=(None, RuntimeError("network error")))):
            result = await _fetch_lyrics_sdk("http://example.com/bad")
        assert result == []

    async def test_exception_returns_empty(self):
        with patch("src.use_cases.sdk.music.http_request",
                   AsyncMock(side_effect=RuntimeError("boom"))):
            result = await _fetch_lyrics_sdk("http://example.com/bad")
        assert result == []


# ============================================================
# play_music 音乐播放（media_player）
# ============================================================


class TestPlayMusic:
    """play_music：搜索并播放歌曲

    重构后的 play_music 通过 SDK 的 play_music_url 下发播放指令
    （歌词下载/逐行推送也由 SDK 完成），成功后抛出 StopPipeline。
    """

    def _make_tm(self):
        tm = MagicMock()
        tm.channel = MagicMock()
        tm.channel.send_json = AsyncMock()
        tm.user_config = MagicMock()
        tm.user_config.key = "bound_d1"
        return tm

    def _settings(self, api_url="http://music.api"):
        settings = MagicMock()
        settings.music.api_url = api_url
        settings.music.lyrics_offset = 0
        return settings

    def _patch_api(self, data):
        resp = MagicMock()
        resp.json.return_value = data
        return patch("src.plugins.media_player.plugin.http_request",
                     AsyncMock(return_value=(resp, None)))

    async def test_no_api_url_returns_message(self):
        tm = self._make_tm()
        with patch("src.plugins.media_player.plugin.kv_get", MagicMock(return_value="")), \
                patch("src.plugins.media_player.plugin.get_settings",
                      return_value=self._settings("")):
            result = await play_music("歌", tool_manager=tm)
        assert "音乐服务" in result

    async def test_api_request_failure_returns_message(self):
        tm = self._make_tm()
        with patch("src.plugins.media_player.plugin.kv_get", MagicMock(return_value="")), \
                patch("src.plugins.media_player.plugin.get_settings",
                      return_value=self._settings()), \
                patch("src.plugins.media_player.plugin.http_request",
                      AsyncMock(return_value=(None, Exception("network error")))):
            result = await play_music("歌", tool_manager=tm)
        assert "不可用" in result

    async def test_song_not_found(self):
        tm = self._make_tm()
        with patch("src.plugins.media_player.plugin.kv_get", MagicMock(return_value="")), \
                patch("src.plugins.media_player.plugin.get_settings",
                      return_value=self._settings()), \
                self._patch_api({"success": False}):
            result = await play_music("不存在的歌", tool_manager=tm)
        assert "未找到" in result

    async def test_no_audio_url(self):
        tm = self._make_tm()
        with patch("src.plugins.media_player.plugin.kv_get", MagicMock(return_value="")), \
                patch("src.plugins.media_player.plugin.get_settings",
                      return_value=self._settings()), \
                self._patch_api({"success": True, "audio_url": ""}):
            result = await play_music("歌", tool_manager=tm)
        assert "没有可播放" in result

    async def test_success_with_channel_raises_stop_pipeline(self):
        tm = self._make_tm()
        api_data = {
            "success": True,
            "audio_url": "http://audio.url",
            "title": "歌名",
            "artist": "歌手",
            "lyric_url": "",
            "duration": 180,
        }
        pmu = AsyncMock(return_value="ok")
        with patch("src.plugins.media_player.plugin.kv_get", MagicMock(return_value="")), \
                patch("src.plugins.media_player.plugin.get_settings",
                      return_value=self._settings()), \
                self._patch_api(api_data), \
                patch("src.plugins.media_player.plugin.play_music_url", pmu):
            with pytest.raises(StopPipeline):
                await play_music("歌", tool_manager=tm)
        # 应通过 SDK 下发播放指令（播放指令与 music_meta 由 SDK 组装发送）
        pmu.assert_awaited_once()
        kwargs = pmu.call_args.kwargs
        assert kwargs["url"] == "http://audio.url"
        assert kwargs["title"] == "歌名"
        assert kwargs["artist"] == "歌手"
        assert kwargs["duration"] == 180
        assert kwargs["device_key"] == "bound_d1"

    async def test_success_with_lyrics_passes_lyric_url(self):
        tm = self._make_tm()
        api_data = {
            "success": True,
            "audio_url": "http://audio.url",
            "title": "歌名",
            "artist": "歌手",
            "lyric_url": "http://lyric.url",
            "duration": 180,
        }
        pmu = AsyncMock(return_value="ok")
        with patch("src.plugins.media_player.plugin.kv_get", MagicMock(return_value="")), \
                patch("src.plugins.media_player.plugin.get_settings",
                      return_value=self._settings()), \
                self._patch_api(api_data), \
                patch("src.plugins.media_player.plugin.play_music_url", pmu):
            with pytest.raises(StopPipeline):
                await play_music("歌", tool_manager=tm)
        # 歌词 URL 与偏移应透传给 SDK（下载与 lyric_line 推送由 SDK 完成）
        kwargs = pmu.call_args.kwargs
        assert kwargs["lyric_url"] == "http://lyric.url"
        assert kwargs["lyrics_offset"] == 0


# ============================================================
# test_device 设备测试（device_control）
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
# Lua 控制工具（device_control）
# ============================================================


class TestExecuteLua:
    """execute_lua：在设备上运行 Lua 脚本"""

    async def test_with_channel_sends_code(self):
        tm = _make_tool_manager_with_channel()
        with _plugin_ctx("device_control", ["device"]), \
                patch("src.plugins.device_control.plugin.request_device_result",
                      AsyncMock(return_value=("print('hello')", "ok", ""))):
            result = await execute_lua("print('hello')", tool_manager=tm)
        assert "成功" in result
        assert "print('hello')" in result

    async def test_without_channel(self):
        with patch("src.plugins.device_control.plugin.request_device_result",
                   AsyncMock(return_value=("", "offline", "设备未连接"))):
            result = await execute_lua("code", tool_manager=None)
        assert "未连接设备" in result

    async def test_send_exception(self):
        tm = _make_tool_manager_with_channel()
        with _plugin_ctx("device_control", ["device"]), \
                patch("src.plugins.device_control.plugin.request_device_result",
                      AsyncMock(return_value=("", "error", "发送失败: fail"))):
            result = await execute_lua("code", tool_manager=tm)
        assert "失败" in result

    async def test_timeout(self):
        tm = _make_tool_manager_with_channel()
        with _plugin_ctx("device_control", ["device"]), \
                patch("src.plugins.device_control.plugin.request_device_result",
                      AsyncMock(return_value=("", "timeout", "设备未在 8 秒内响应"))):
            result = await execute_lua("code", tool_manager=tm)
        assert "8 秒" in result


class TestStopLua:
    """stop_lua：停止设备上的 Lua 脚本"""

    async def test_with_channel(self):
        tm = _make_tool_manager_with_channel()
        with _plugin_ctx("device_control", ["device"]):
            result = await stop_lua(tool_manager=tm)
        assert "停止" in result
        sent = tm.channel.send_json.call_args.args[0]
        assert sent["command_id"] == "stop_lua"

    async def test_without_channel(self):
        result = await stop_lua(tool_manager=None)
        assert "设备未连接" in result

    async def test_send_exception(self):
        tm = _make_tool_manager_with_channel()
        tm.channel.send_json = AsyncMock(side_effect=RuntimeError("fail"))
        with _plugin_ctx("device_control", ["device"]):
            result = await stop_lua(tool_manager=tm)
        assert "失败" in result


class TestClearScreen:
    """clear_screen：清除屏幕 Lua 绘制"""

    async def test_with_channel(self):
        tm = _make_tool_manager_with_channel()
        with _plugin_ctx("device_control", ["device"]):
            result = await clear_screen(tool_manager=tm)
        assert "清屏" in result
        sent = tm.channel.send_json.call_args.args[0]
        assert sent["command_id"] == "clear_screen"

    async def test_without_channel(self):
        result = await clear_screen(tool_manager=None)
        assert "设备未连接" in result

    async def test_send_exception(self):
        tm = _make_tool_manager_with_channel()
        tm.channel.send_json = AsyncMock(side_effect=RuntimeError("fail"))
        with _plugin_ctx("device_control", ["device"]):
            result = await clear_screen(tool_manager=tm)
        assert "失败" in result


# ============================================================
# 长期记忆工具（memory）
# ============================================================


def _make_tm_with_ltm(device_key="bound_d1"):
    """构造一个带 ltm_service 的 mock tool_manager"""
    tm = MagicMock()
    tm.channel = None
    tm.user_config = MagicMock()
    tm.user_config.device_id = None
    tm.user_config.key = device_key
    tm.ltm_service = MagicMock()
    tm.ltm_service.store = AsyncMock()
    tm.ltm_service.recall = AsyncMock()
    tm.ltm_service.list_all = AsyncMock()
    tm.ltm_service.update = AsyncMock()
    tm.ltm_service.forget = AsyncMock()
    return tm


class TestMemoryStore:
    """memory_store：存储长期记忆"""

    async def test_no_device_id_returns_error(self):
        tm = MagicMock()
        tm.user_config = None
        with _plugin_ctx("memory", ["ltm"]):
            result = await memory_store("内容", tool_manager=tm)
        assert "无法获取设备ID" in result

    async def test_store_new(self):
        tm = _make_tm_with_ltm()
        tm.ltm_service.store = AsyncMock(return_value=("mem-1", True))
        with _plugin_ctx("memory", ["ltm"]):
            result = await memory_store("我喜欢蓝色", tags="颜色", keywords="蓝色", tool_manager=tm)
        assert "已记住" in result
        tm.ltm_service.store.assert_awaited_once()

    async def test_store_dedup(self):
        tm = _make_tm_with_ltm()
        tm.ltm_service.store = AsyncMock(return_value=("mem-1", False))
        with _plugin_ctx("memory", ["ltm"]):
            result = await memory_store("我喜欢蓝色", tool_manager=tm)
        assert "已存在" in result

    async def test_tags_and_keywords_parsed(self):
        tm = _make_tm_with_ltm()
        tm.ltm_service.store = AsyncMock(return_value=("mem-1", True))
        with _plugin_ctx("memory", ["ltm"]):
            await memory_store("内容", tags="a,b,c", keywords="x,y,z", tool_manager=tm)
        item = tm.ltm_service.store.call_args.args[0]
        assert item.tags == ["a", "b", "c"]
        assert item.keywords == ["x", "y", "z"]

    async def test_explicit_device_id_overrides_config(self):
        tm = _make_tm_with_ltm("config_id")
        tm.ltm_service.store = AsyncMock(return_value=("mem-1", True))
        with _plugin_ctx("memory", ["ltm"]):
            await memory_store("内容", device_id="explicit_id", tool_manager=tm)
        item = tm.ltm_service.store.call_args.args[0]
        assert item.device_id == "explicit_id"


class TestMemoryRecall:
    """memory_recall：召回长期记忆"""

    async def test_no_device_id_returns_error(self):
        tm = MagicMock()
        tm.user_config = None
        with _plugin_ctx("memory", ["ltm"]):
            result = await memory_recall("标签", tool_manager=tm)
        assert "无法获取设备ID" in result

    async def test_recall_found(self):
        tm = _make_tm_with_ltm()
        item = MagicMock()
        item.memory_id = "mem-1"
        item.content = "记忆内容"
        item.tags = ["标签"]
        tm.ltm_service.recall = AsyncMock(return_value=[item])
        with _plugin_ctx("memory", ["ltm"]):
            result = await memory_recall("标签", tool_manager=tm)
        assert "1 条" in result
        assert "记忆内容" in result

    async def test_recall_not_found(self):
        tm = _make_tm_with_ltm()
        tm.ltm_service.recall = AsyncMock(return_value=[])
        with _plugin_ctx("memory", ["ltm"]):
            result = await memory_recall("标签", tool_manager=tm)
        assert "未找到" in result

    async def test_labels_parsed(self):
        tm = _make_tm_with_ltm()
        tm.ltm_service.recall = AsyncMock(return_value=[])
        with _plugin_ctx("memory", ["ltm"]):
            await memory_recall("a,b,c", tool_manager=tm)
        query = tm.ltm_service.recall.call_args.args[0]
        assert tuple(query.summary_labels) == ("a", "b", "c")


class TestMemoryList:
    """memory_list：列出长期记忆"""

    async def test_no_device_id_returns_error(self):
        tm = MagicMock()
        tm.user_config = None
        with _plugin_ctx("memory", ["ltm"]):
            result = await memory_list(tool_manager=tm)
        assert "无法获取设备ID" in result

    async def test_list_with_items(self):
        tm = _make_tm_with_ltm()
        item = MagicMock()
        item.memory_id = "mem-1"
        item.content = "内容"
        item.source = "manual"
        tm.ltm_service.list_all = AsyncMock(return_value=[item])
        with _plugin_ctx("memory", ["ltm"]):
            result = await memory_list(tool_manager=tm)
        assert "1 条" in result
        assert "内容" in result

    async def test_list_empty(self):
        tm = _make_tm_with_ltm()
        tm.ltm_service.list_all = AsyncMock(return_value=[])
        with _plugin_ctx("memory", ["ltm"]):
            result = await memory_list(tool_manager=tm)
        assert "暂无" in result


class TestMemoryUpdate:
    """memory_update：更新长期记忆"""

    async def test_no_device_id_returns_error(self):
        tm = MagicMock()
        tm.user_config = None
        with _plugin_ctx("memory", ["ltm"]):
            result = await memory_update("mem-1", tool_manager=tm)
        assert "无法获取设备ID" in result

    async def test_update_success(self):
        tm = _make_tm_with_ltm()
        tm.ltm_service.update = AsyncMock(return_value=True)
        with _plugin_ctx("memory", ["ltm"]):
            result = await memory_update("mem-1", content="新内容", tags="a,b", tool_manager=tm)
        assert "已更新" in result
        patch_dict = tm.ltm_service.update.call_args.args[1]
        assert patch_dict["content"] == "新内容"
        assert patch_dict["tags"] == ["a", "b"]

    async def test_update_not_found(self):
        tm = _make_tm_with_ltm()
        tm.ltm_service.update = AsyncMock(return_value=False)
        with _plugin_ctx("memory", ["ltm"]):
            result = await memory_update("mem-1", tool_manager=tm)
        assert "未找到" in result

    async def test_partial_update_only_content(self):
        tm = _make_tm_with_ltm()
        tm.ltm_service.update = AsyncMock(return_value=True)
        with _plugin_ctx("memory", ["ltm"]):
            await memory_update("mem-1", content="新内容", tool_manager=tm)
        patch_dict = tm.ltm_service.update.call_args.args[1]
        assert patch_dict == {"content": "新内容"}


class TestMemoryForget:
    """memory_forget：删除长期记忆"""

    async def test_no_device_id_returns_error(self):
        tm = MagicMock()
        tm.user_config = None
        with _plugin_ctx("memory", ["ltm"]):
            result = await memory_forget("mem-1", tool_manager=tm)
        assert "无法获取设备ID" in result

    async def test_forget_success(self):
        tm = _make_tm_with_ltm()
        item = MagicMock()
        item.content = "被删除的内容"
        tm.ltm_service.forget = AsyncMock(return_value=item)
        with _plugin_ctx("memory", ["ltm"]):
            result = await memory_forget("mem-1", tool_manager=tm)
        assert "已删除" in result

    async def test_forget_not_found(self):
        tm = _make_tm_with_ltm()
        tm.ltm_service.forget = AsyncMock(return_value=None)
        with _plugin_ctx("memory", ["ltm"]):
            result = await memory_forget("mem-1", tool_manager=tm)
        assert "未找到" in result