import json
import re
import urllib.parse

from src.infrastructure.logging import get_logger
from src.infrastructure.config import get_settings
from src.use_cases.tools_system import StopPipeline, tool
from src.use_cases._plugin_helpers import get_plugin_config_or_env, http_request, send_instruct

logger = get_logger(__name__)

def parse_lrc(lrc_text: str) -> list:
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


async def fetch_lyrics(lyric_url: str) -> list:
    try:
        logger.info(f"[歌词] 开始下载: {lyric_url}")
        resp, err = await http_request("GET", lyric_url, timeout=6)
        if err:
            raise err
        lrc_text = resp.text
        logger.info(f"[歌词] 下载完成, {len(lrc_text)} 字符")
        result = parse_lrc(lrc_text)
        logger.info(f"[歌词] 解析完成, 共 {len(result)} 行")
        return result
    except Exception as e:
        logger.error(f"[歌词] 下载或解析失败: {e}")
        return []


async def play_random_music_to_channel(channel, tool_manager=None) -> bool:
    """向设备发送一首随机歌曲（供 music_play_next 自动续播调用）

    从音乐 API /random 接口获取随机歌曲，发送 play_music + music_meta + 歌词到设备。
    与 play_music 工具共享相同的发送逻辑，但不经过 LLM pipeline。

    Args:
        channel: WSChannel 设备通道
        tool_manager: 工具管理器（读取商店插件配置的 api_url，可选）

    Returns:
        True 表示成功发送，False 表示失败
    """
    music_api_url, lyrics_offset = _resolve_music_api(tool_manager)

    if not music_api_url:
        logger.warning("[音乐续播] 音乐服务未配置")
        return False

    try:
        api_url = f"{music_api_url}/random"
        resp, err = await http_request("GET", api_url, timeout=10)
        if err:
            raise err
        data = resp.json()
    except Exception as e:
        logger.error(f"[音乐续播] API 请求异常: {e}")
        return False

    if not data.get("success"):
        logger.warning("[音乐续播] 随机推荐失败，音乐库可能为空")
        return False

    audio_url = data.get("audio_url", "")
    if not audio_url:
        logger.warning("[音乐续播] 随机推荐的歌曲没有可播放的音频链接")
        return False

    # URL 编码路径部分（与 play_music 工具一致）
    parsed = urllib.parse.urlsplit(audio_url)
    if parsed.path:
        decoded_path = urllib.parse.unquote(parsed.path)
        encoded_path = urllib.parse.quote(decoded_path, safe="/")
        audio_url = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, encoded_path, parsed.query, parsed.fragment)
        )

    title = data.get("title", "未知")
    artist = data.get("artist", "未知")
    lyric_url = data.get("lyric_url", "")
    duration = data.get("duration", 0)

    lyrics = await fetch_lyrics(lyric_url) if lyric_url else []

    logger.info(f"[音乐续播] 发送 play_music: {title} - {artist}, 歌词 {len(lyrics)} 行, 时长 {duration}s")

    await send_instruct(channel, "play_music", audio_url)

    await send_instruct(channel, "music_meta", json.dumps(
        {
            "title": title,
            "artist": artist,
            "duration": duration,
            "lyric_url": lyric_url,
            "lyric_count": len(lyrics),
            "lyric_offset_ms": lyrics_offset,
        },
        ensure_ascii=False,
    ))

    for i, line in enumerate(lyrics):
        await send_instruct(channel, "lyric_line", json.dumps(
            {
                "index": i,
                "time": line["time"] + lyrics_offset,
                "text": line["text"],
            },
            ensure_ascii=False,
        ))

    logger.info(f"[音乐续播] 歌词逐行推送完成, 共 {len(lyrics)} 行")
    return True


def _resolve_music_api(tool_manager) -> tuple[str, int]:
    """解析音乐服务地址与歌词偏移，优先级：商店插件配置 > 全局配置（.env MUSIC_API_URL）。"""
    # 1. 商店插件配置（App 插件商店「⚙ 配置」填的 api_url）
    url = get_plugin_config_or_env(tool_manager, "media_player", "api_url")
    if url:
        offset = 0
        try:
            offset = int(tool_manager.get_plugin_config("media_player", "lyrics_offset", "0") or 0)
        except ValueError:
            offset = 0
        return url, offset
    # 2. 全局配置
    settings = get_settings()
    return settings.music.api_url, settings.music.lyrics_offset

@tool()
async def play_music(song: str = "", artist: str = "", tool_manager=None) -> str:
    """搜索并播放歌曲。根据用户说的歌名搜索歌曲，找到后通过设备播放。
    参数 song 为用户说的歌名，例如"好运来"、"晴天"、"起风了"等。用户未指定歌名时（如"随便放一首"、"播放音乐"）留空，将随机推荐一首歌。
    参数 artist 为歌手名称，例如"邓紫棋"、"周杰伦"等。
    重要：artist 参数应尽量填写。用户明确提到歌手时用用户说的歌手；用户未提及时，根据你的知识判断这首歌最知名的原唱或最流行的翻唱歌手填入，例如"晴天"→"周杰伦"、"海阔天空"→"Beyond"、"姑娘别哭泣"→"小阿七"。
    注意：歌名和歌手名称之间一定不能有任何变电符号，例如空格、逗号等。如果返回"音乐搜索服务暂不可用"等错误信息，请直接告诉用户该信息，不要再重试调用此工具。"""
    music_api_url, lyrics_offset = _resolve_music_api(tool_manager)

    if not music_api_url:
        return "音乐服务未配置，请在 App 插件商店中配置音乐服务地址，或联系管理员在 .env 中设置 MUSIC_API_URL"

    try:
        if song:
            # 按歌名搜索
            encoded_song = urllib.parse.quote(song)
            api_url = f"{music_api_url}/stream_pcm?song={encoded_song}"
            if artist:
                encoded_artist = urllib.parse.quote(artist)
                api_url += f"&artist={encoded_artist}"
        else:
            # 未指定歌名，随机推荐一首
            api_url = f"{music_api_url}/random"
        resp, err = await http_request("GET", api_url, timeout=10)
        if err:
            raise err
        data = resp.json()
    except Exception as e:
        logger.error(f"[音乐] API 请求失败: {api_url} -> {e}")
        return "音乐搜索服务暂不可用（网络连接失败），请告知用户稍后重试"

    if not data.get("success"):
        return f"未找到歌曲: {song}" if song else "随机推荐失败，音乐库可能为空，请稍后重试"

    audio_url = data.get("audio_url", "")
    if not audio_url:
        return f"歌曲 {song} 没有可播放的音频链接" if song else "随机推荐的歌曲没有可播放的音频链接"

    # URL 编码路径部分（文件名含空格/中文时 ESP32 HTTP 客户端无法解析）
    # 音乐 API 返回的 audio_url 可能已经编码过一次，先 unquote 解码再 quote 重新编码，
    # 避免双重编码（%E5 → %25E5）导致设备 HTTP 客户端无法解析
    parsed = urllib.parse.urlsplit(audio_url)
    if parsed.path:
        decoded_path = urllib.parse.unquote(parsed.path)
        encoded_path = urllib.parse.quote(decoded_path, safe="/")
        audio_url = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, encoded_path, parsed.query, parsed.fragment)
        )

    title = data.get("title", song)
    artist = data.get("artist", "未知")
    lyric_url = data.get("lyric_url", "")
    duration = data.get("duration", 0)

    lyrics = await fetch_lyrics(lyric_url) if lyric_url else []

    if not tool_manager or not tool_manager.channel:
        return "播放音乐指令已生成（未连接设备）"

    ch = tool_manager.channel
    logger.info(f"[音乐] 发送 play_music 指令: {title} - {artist}, 歌词 {len(lyrics)} 行, 时长 {duration}s")

    await send_instruct(ch, "play_music", audio_url)

    await send_instruct(ch, "music_meta", json.dumps(
        {
            "title": title,
            "artist": artist,
            "duration": duration,
            "lyric_url": lyric_url,
            "lyric_count": len(lyrics),
            "lyric_offset_ms": lyrics_offset,
        },
        ensure_ascii=False,
    ))

    for i, line in enumerate(lyrics):
        await send_instruct(ch, "lyric_line", json.dumps(
            {
                "index": i,
                "time": line["time"] + lyrics_offset,
                "text": line["text"],
            },
            ensure_ascii=False,
        ))

    logger.info(f"[音乐] 歌词逐行推送完成, 共 {len(lyrics)} 行")
    raise StopPipeline()
