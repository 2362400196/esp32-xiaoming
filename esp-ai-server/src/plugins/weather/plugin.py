"""天气插件：高德天气 API，语音播报 + 屏幕天气卡片（原生渲染）。

安装后 LLM 自动获得 get_weather 工具（用户问天气时调用）：
  - 语音：返回中文天气文本（LLM 直接播报）
  - 屏幕：通过 show_card 指令下发 JSON 卡片，设备端原生 LVGL 渲染——
    彩色天气图标（img 元素，设备端内置 weather_icons.c）+ 48px 大号温度
    （mont48）+ 中文字体（font_puhui_16_4.c，全量汉字 + °·~ 符号）。
    卡片文本需避开源字体缺失的 ≤≥℃ 字符。

配置：高德 Key 通过设备插件商店「⚙ 配置」设置，或环境变量 WEATHER_AMAP_KEY 提供
（兼容旧变量名 AMAP_WEATHER_KEY，需在 PLUGIN_ENV_ALLOWLIST 中显式放行）。
文档：https://lbs.amap.com/api/webservice/guide/api-advanced/weatherinfo
"""

from src.use_cases._plugin_helpers import json_dumps

from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import http_get_json, send_device_command
from src.use_cases.sdk.storage import kv_get, kv_set

AMAP_WEATHER_URL = "https://restapi.amap.com/v3/weather/weatherInfo"


def _get_amap_key(tool_manager) -> str:
    """获取高德 Key：从插件专属 KV 存储读取（前端配置 → 插件存储，不经过主数据库）。"""
    return kv_get("amap_key", default="", tool_manager=tool_manager) or ""

# 天气 → 图标 id（设备端内置 ARGB8565 彩色图标表 fonts/weather_icons.c：
# sun 晴 / sun_cloud 晴间多云 / cloud 多云 / overcast 阴 /
# rain 雨 / storm 雷阵雨 / snow 雪 / fog 雾霾沙尘）
WEATHER_ICON = {
    "晴": "sun",
    "晴间多云": "sun_cloud",
    "多云": "cloud",
    "阴": "overcast",
    "小雨": "rain",
    "中雨": "rain",
    "大雨": "rain",
    "暴雨": "rain",
    "阵雨": "rain",
    "雷阵雨": "storm",
    "雷雨": "storm",
    "小雪": "snow",
    "中雪": "snow",
    "大雪": "snow",
    "暴雪": "snow",
    "雨夹雪": "snow",
    "雾": "fog",
    "霾": "fog",
    "浮尘": "fog",
    "扬沙": "fog",
    "沙尘暴": "fog",
}


def _weather_icon(weather_cn: str) -> str:
    return WEATHER_ICON.get(weather_cn, "cloud")


def _build_card_json(city_cn: str, weather_cn: str, temp: str,
                     humidity: str, wind_text: str, forecast_text: str) -> str:
    """生成 show_card 指令的 JSON 卡片描述（设备端原生 LVGL 渲染）。
    温度用 48px 大号数字字体（mont48），图标/中文用 puhui 字体。"""
    card = {
        "bg": "000000",
        "card": {"x": 20, "y": 40, "w": 200, "h": 160, "bg": "1E1E1E",
                 "radius": 12, "border": "444444"},
        "items": [
            # 天气图标（彩色图片，左上 32x32）
            {"t": "img", "id": _weather_icon(weather_cn),
             "x": 14, "y": 8},
            # 城市名（白色，图标右侧垂直居中）
            {"t": "label", "text": city_cn,
             "x": 54, "y": 16, "color": "FFFFFF", "font": "puhui"},
            # 当前温度（48px 大号，居中，最醒目）
            {"t": "label", "text": f"{temp}°",
             "y": 30, "color": "FFFFFF", "font": "mont48", "align": "center"},
            # 天气详情（浅灰，居中）
            {"t": "label", "text": f"{weather_cn} · 湿度{humidity}%{wind_text}",
             "y": 92, "color": "AAAAAA", "font": "puhui", "align": "center"},
            # 分隔线
            {"t": "sep", "y": 114, "color": "3A3A3A"},
            # 今日预报（深灰，居中）
            {"t": "label", "text": forecast_text,
             "y": 130, "color": "888888", "font": "puhui", "align": "center"},
        ],
    }
    return json_dumps(card)


@tool(cache=False)
async def get_weather(city: str = "", tool_manager=None) -> str:
    """查询指定城市的实时天气并播报，同时在设备屏幕显示天气卡片。
    只要用户询问任何与天气/气温/冷暖/雨雪/带伞相关的问题，【必须】调用此工具获取实时数据，
    绝不可以用历史对话中的旧天气信息、记忆或常识猜测回答——天气实时变化，必须每次重新查询！
    即使之前的对话里已经查过同一城市的天气，用户再次问天气也必须重新调用本工具。
    参数 city: 城市名称，如"北京"、"上海"、"广州"。用户明确说城市时用用户说的城市；
    用户只说"这里/本地/今天"等未指定城市时，city 留空（默认使用北京）。"""
    # 未指定城市时的默认城市（可改为设备所在城市）
    if not city or not city.strip():
        city = "西安"
    amap_key = _get_amap_key(tool_manager)
    if not amap_key:
        return "天气服务未配置，请在 App 插件商店中为「天气」插件配置高德 API Key，或联系管理员在 .env 中设置 WEATHER_AMAP_KEY"
    # 实测高德：extensions=base 只返回实况(lives)，all 只返回预报(forecasts)，需分别请求
    live_data, err = await http_get_json(
        AMAP_WEATHER_URL, params={"key": amap_key, "city": city, "extensions": "base"},
    )
    if err:
        return f"天气查询失败（网络错误）: {err}"
    fc_data, err = await http_get_json(
        AMAP_WEATHER_URL, params={"key": amap_key, "city": city, "extensions": "all"},
    )
    if err:
        return f"天气查询失败（网络错误）: {err}"

    if live_data.get("status") != "1" or not live_data.get("lives"):
        info = live_data.get("info", "未知错误")
        return f"查询{city}天气失败: {info}（请确认城市名称是否正确）"

    live = live_data["lives"][0]
    # 城市显示名用工具参数（用户原话提取，如"西安"），不用高德返回的 city 字段——
    # 高德对部分城市返回下级区划名（如"西安区"），直接显示不友好
    city_name = city
    weather_cn = live.get("weather", "")
    temp = live.get("temperature", "?")   # 当前温度（实况）
    humidity = live.get("humidity", "?")
    wind_dir = live.get("winddirection", "")
    wind_power = live.get("windpower", "")
    # ≤/≥ 符号在 AlibabaPuHuiTi 源字体中无字形（设备端显示为空白），卡片直接省略；
    # 语音文本替换为自然说法
    wind_power_card = wind_power.replace("≤", "").replace("≥", "")
    wind_power = wind_power.replace("≤", "小于等于").replace("≥", "大于等于")

    # 今日预报（forecasts[0].casts[0]）——仅用于"今日最高/最低"次要信息
    today_cast = None
    if fc_data.get("forecasts"):
        casts = fc_data["forecasts"][0].get("casts", [])
        if casts:
            today_cast = casts[0]

    speech = (f"{city_name}当前{weather_cn}，气温{temp}度，"
              f"{wind_dir}{wind_power}级，湿度{humidity}%")
    if today_cast:
        day_temp = today_cast.get("daytemp", "?")
        night_temp = today_cast.get("nighttemp", "?")
        day_weather = today_cast.get("dayweather", "")
        night_weather = today_cast.get("nightweather", "")
        speech += (f"。今天白天{day_weather}，最高{day_temp}度，"
                   f"夜间{night_weather}，最低{night_temp}度")

    # 屏幕天气卡片（show_card 原生渲染：大号温度 + 图标 + 中文）
    wind_text = f" · {wind_dir}{wind_power_card}级" if wind_dir else ""
    forecast_text = "今日预报"
    if today_cast:
        forecast_text = (f"今日 {today_cast.get('dayweather','')} "
                         f"{today_cast.get('daytemp','?')}~"
                         f"{today_cast.get('nighttemp','?')}°")
    card_json = _build_card_json(
        city_name, weather_cn, temp, humidity, wind_text, forecast_text,
    )
    await send_device_command(tool_manager, "show_card", card_json)

    return speech


@tool(cache=False)
async def test_weather_query(city: str = "北京", tool_manager=None) -> str:
    """测试天气查询（前端测试用，返回 JSON 格式天气数据，通过 SDK 调用高德 API）。"""
    amap_key = _get_amap_key(tool_manager)
    if not amap_key:
        return json_dumps({"error": "请先配置高德 API Key"})
    data, err = await http_get_json(
        AMAP_WEATHER_URL, params={"key": amap_key, "city": city, "extensions": "base"},
    )
    if err:
        return json_dumps({"error": f"网络错误: {err}"})
    return json_dumps(data)


@tool(cache=False)
def save_config(amap_key: str = "", tool_manager=None) -> str:
    """保存天气插件配置到插件专属 KV 存储（不经过主数据库）。
    参数 amap_key: 高德 API Key。不传则返回当前配置。"""
    if not amap_key:
        current = kv_get("amap_key", default="", tool_manager=tool_manager)
        return json_dumps({"ok": True, "amap_key": current})
    kv_set("amap_key", amap_key, tool_manager=tool_manager)
    return json_dumps({"ok": True, "message": "配置已保存"})
