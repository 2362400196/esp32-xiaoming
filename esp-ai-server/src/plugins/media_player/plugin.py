import json
import urllib.parse

from src.use_cases._plugin_helpers import get_logger, get_settings
from src.use_cases.tools_system import StopPipeline, tool
from src.use_cases._plugin_helpers import (
    get_device_key,
    http_request,
    play_music_url,
    kv_get,
    kv_set,
)

logger = get_logger(__name__)

# 当前播放状态（供前端正在播放页使用）
_current_playing: dict = {"title": "", "artist": "", "playing": False}


def set_now_playing(title: str = "", artist: str = "", playing: bool = True) -> None:
    """设置当前播放状态。"""
    _current_playing["title"] = title
    _current_playing["artist"] = artist
    _current_playing["playing"] = playing


def get_now_playing() -> dict:
    """获取当前播放状态（返回副本，防止外部修改）。"""
    return dict(_current_playing)


def _resolve_music_api(tool_manager) -> tuple[str, int]:
    """解析音乐服务地址与歌词偏移，优先级：KV 存储 > 全局配置（.env MUSIC_API_URL）。"""
    url = kv_get("api_url", tool_manager=tool_manager)
    if url:
        offset = 0
        try:
            offset = int(kv_get("lyrics_offset", "0", tool_manager=tool_manager) or 0)
        except ValueError:
            offset = 0
        return url, offset
    settings = get_settings()
    return settings.music.api_url, settings.music.lyrics_offset


async def _search_music_api(song: str, artist: str, tool_manager=None) -> dict:
    """内部工具：搜索音乐 API，返回歌曲信息或抛出异常。"""
    music_api_url, lyrics_offset = _resolve_music_api(tool_manager)
    if not music_api_url:
        raise ValueError("音乐服务未配置")

    if song:
        api_url = f"{music_api_url}/stream_pcm?song={urllib.parse.quote(song)}"
        if artist:
            api_url += f"&artist={urllib.parse.quote(artist)}"
    else:
        api_url = f"{music_api_url}/random"

    resp, err = await http_request("GET", api_url, timeout=10)
    if err:
        raise ConnectionError(f"音乐搜索服务暂不可用: {err}")

    data = resp.json()
    if not data.get("success"):
        raise LookupError(f"未找到歌曲: {song}" if song else "随机推荐失败，音乐库可能为空")

    audio_url = data.get("audio_url", "")
    if not audio_url:
        raise LookupError("没有可播放的音频链接")

    # URL 编码路径部分（文件名含空格/中文时 ESP32 HTTP 客户端无法解析）
    parsed = urllib.parse.urlsplit(audio_url)
    if parsed.path:
        decoded_path = urllib.parse.unquote(parsed.path)
        encoded_path = urllib.parse.quote(decoded_path, safe="/")
        audio_url = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, encoded_path, parsed.query, parsed.fragment)
        )

    return {
        "audio_url": audio_url,
        "title": data.get("title", song or "未知"),
        "artist": data.get("artist", "未知"),
        "lyric_url": data.get("lyric_url", ""),
        "duration": data.get("duration", 0),
        "lyrics_offset": lyrics_offset,
    }


async def play_random_music_to_channel(channel, tool_manager=None) -> bool:
    """向设备发送一首随机歌曲（供 music_play_next 自动续播调用）。

    从音乐 API /random 接口获取随机歌曲，通过 SDK 发送到设备。
    与 play_music 工具共享相同的搜索和发送逻辑，但不经过 LLM pipeline。

    Args:
        channel: WSChannel 设备通道（保留兼容，实际由 SDK 通过 device_key 发送）
        tool_manager: 工具管理器（读取商店插件配置的 api_url，可选）

    Returns:
        True 表示成功发送，False 表示失败
    """
    try:
        info = await _search_music_api("", "", tool_manager)
    except ValueError as e:
        logger.warning(f"[音乐续播] {e}")
        return False
    except Exception as e:
        logger.error(f"[音乐续播] 搜索异常: {e}")
        return False

    device_key = get_device_key(tool_manager)
    result = await play_music_url(
        url=info["audio_url"],
        title=info["title"],
        artist=info["artist"],
        duration=info["duration"],
        device_key=device_key,
        lyric_url=info["lyric_url"],
        lyrics_offset=info["lyrics_offset"],
    )

    if result == "ok":
        logger.info(f"[音乐续播] 已发送: {info['title']} - {info['artist']}")
        return True

    logger.warning(f"[音乐续播] 发送失败: {result}")
    return False


@tool()
async def play_music(song: str = "", artist: str = "", tool_manager=None) -> str:
    """搜索并播放歌曲。根据用户说的歌名搜索歌曲，找到后通过设备播放。
    参数 song 为用户说的歌名，例如"好运来"、"晴天"、"起风了"等。用户未指定歌名时（如"随便放一首"、"播放音乐"）留空，将随机推荐一首歌。
    参数 artist 为歌手名称，例如"邓紫棋"、"周杰伦"等。
    重要：artist 参数应尽量填写。用户明确提到歌手时用用户说的歌手；用户未提及时，根据你的知识判断这首歌最知名的原唱或最流行的翻唱歌手填入，例如"晴天"→"周杰伦"、"海阔天空"→"Beyond"、"姑娘别哭泣"→"小阿七"。
    注意：歌名和歌手名称之间一定不能有任何变电符号，例如空格、逗号等。如果返回"音乐搜索服务暂不可用"等错误信息，请直接告诉用户该信息，不要再重试调用此工具。"""
    try:
        info = await _search_music_api(song, artist, tool_manager)
    except ValueError:
        return "音乐服务未配置，请在 App 插件商店中配置音乐服务地址，或联系管理员在 .env 中设置 MUSIC_API_URL"
    except ConnectionError as e:
        logger.error(f"[音乐] API 请求失败: {e}")
        return "音乐搜索服务暂不可用（网络连接失败），请告知用户稍后重试"
    except LookupError as e:
        return str(e)

    device_key = get_device_key(tool_manager)
    result = await play_music_url(
        url=info["audio_url"],
        title=info["title"],
        artist=info["artist"],
        duration=info["duration"],
        device_key=device_key,
        lyric_url=info["lyric_url"],
        lyrics_offset=info["lyrics_offset"],
    )

    set_now_playing(title=info["title"], artist=info["artist"], playing=True)
    logger.info(f"[音乐] 已发送: {info['title']} - {info['artist']}, 结果: {result}")
    raise StopPipeline()


@tool()
async def media_save_config(api_url: str = "", lyrics_offset: str = "", tool_manager=None) -> str:
    """保存音乐服务配置。不传参时返回当前配置。"""
    if not api_url and not lyrics_offset:
        cfg = {
            "api_url": kv_get("api_url", tool_manager=tool_manager) or "",
            "lyrics_offset": kv_get("lyrics_offset", "0", tool_manager=tool_manager) or "",
        }
        return json.dumps(cfg, ensure_ascii=False)
    if api_url:
        kv_set("api_url", api_url, tool_manager=tool_manager)
    if lyrics_offset:
        kv_set("lyrics_offset", lyrics_offset, tool_manager=tool_manager)
    return "ok"


@tool()
async def media_search_music(song: str = "", artist: str = "", tool_manager=None) -> str:
    """搜索音乐。根据歌名搜索，返回歌曲列表 JSON。song 为空时返回随机推荐。"""
    try:
        info = await _search_music_api(song, artist, tool_manager)
        return json.dumps({
            "success": True,
            "title": info["title"],
            "artist": info["artist"],
            "audio_url": info["audio_url"],
            "lyric_url": info.get("lyric_url", ""),
            "duration": info.get("duration", 0),
        }, ensure_ascii=False)
    except ValueError as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    except ConnectionError as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    except LookupError as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@tool()
async def media_play_url(audio_url: str = "", title: str = "", artist: str = "", tool_manager=None) -> str:
    """播放指定 URL 的音乐。将音频链接发送到设备播放。"""
    if not audio_url:
        return "无播放链接"
    device_key = get_device_key(tool_manager)
    result = await play_music_url(
        url=audio_url,
        title=title or "未知",
        artist=artist or "未知",
        device_key=device_key,
    )
    if result == "ok":
        set_now_playing(title=title, artist=artist, playing=True)
        logger.info(f"[音乐] 前端播放: {title} - {artist}")
        return "ok"
    return f"发送失败: {result}"


@tool()
async def media_test_connection(api_url: str = "", tool_manager=None) -> str:
    """测试音乐服务连接状态。api_url 为空时使用已保存的配置。"""
    if not api_url:
        api_url = kv_get("api_url", tool_manager=tool_manager) or ""
    if not api_url:
        return "未配置音乐服务地址"
    try:
        url = api_url.rstrip("/") + "/random"
        resp, err = await http_request("GET", url, timeout=5)
        if err:
            return f"连接失败: {err}"
        data = resp.json()
        if data.get("success") is not None:
            return "ok"
        return "服务返回异常数据"
    except Exception as e:
        return f"无法连接: {e}"


@tool()
async def media_get_now_playing(tool_manager=None) -> str:
    """获取当前正在播放的歌曲信息（供前端「正在播放」页使用）。"""
    return json.dumps(_current_playing, ensure_ascii=False)