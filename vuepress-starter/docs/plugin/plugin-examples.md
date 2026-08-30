# 插件示例合集（SDK 版 · 可直接测试）

> 本文从《[编写第一个插件](./writing-first-plugin.md)》中提取全部 6 个示例，**逐一对齐插件 SDK 的调用方式全部重写**；再按 SDK 子模块补全新能力示例（七 ~ 二十二），并在附录给出主进程内置插件专用 SDK 的用法。
> 每个示例都是完整可运行的独立插件（`manifest.json` + `plugin.py`），可以直接在在线编辑器里创建后，用 **运行测试** 验证效果。

## 通用测试步骤

1. 管理后台 → **插件 → 我的插件 → 新建插件**。
2. 粘贴下面的 `manifest.json` 和 `plugin.py`，保存（自动热重载）。
3. 打开 **运行测试**，选择工具、填参数、点 **▶ 运行**，看结果与底部运行日志。
4. 测试完成后在"我的插件"里禁用或删除该测试插件即可。

::: tip 测试前必读
- 建议把示例里的插件 `id` 加个后缀（如 `hello_demo`），避免与已安装插件重名导致工具注册冲突。
- 涉及设备指令的示例（二、三、五、六）需要**设备在线**才有效果；纯文本/网络示例（一、四）不依赖设备。
- 插件 `permissions` 必须覆盖代码实际用到的能力，否则运行测试会返回权限错误。
:::

---

## 示例一：Hello World（纯文本回复）

**目标**：注册一个工具，用户说"打招呼"时回复一句问候。不涉及设备硬件，仅返回文本由 TTS 播报。

**manifest.json**：

```json
{
  "id": "hello_demo",
  "name": "打招呼",
  "version": "1.0.0",
  "description": "一个打招呼的示例插件",
  "permissions": []
}
```

**plugin.py**：

```python
from src.use_cases.sdk.tools import tool


@tool()
async def say_hello(name: str = "朋友") -> str:
    """和用户打个招呼。当用户说"打招呼"、"你好"、"问声好"时调用。
    参数 name: 用户名字（可选），用户说了名字就传入"""
    return f"你好，{name}！很高兴见到你。"
```

**SDK 说明**：

| 要素 | 说明 |
|------|------|
| `from src.use_cases.sdk.tools import tool` | SDK 工具装饰器，把函数注册为 LLM 可调用的工具 |
| `@tool()` | 不写 `cache=False`，纯查询默认开启缓存（同参数 300 秒内复用） |
| `async def` + `-> str` | 工具必须是异步函数，返回值会被 TTS 播报 |
| `name: str = "朋友"` | 参数名 + 类型注解 + 默认值，LLM 根据 docstring 判断何时传参 |
| `"""..."""` | **最重要**：写清触发词（"打招呼"、"你好"）和参数含义，LLM 靠它决定调用时机 |

**测试**：运行测试 → `say_hello` → 参数 `name` 留空或填 `张三` → 预期返回 `你好，朋友！很高兴见到你。` / `你好，张三！很高兴见到你。`。此示例无需任何权限，`permissions` 为空数组。

---

## 示例二：控制设备亮度（设备指令 + 参数校验）

**目标**：用户说"亮度调到 50"时，通过 WebSocket 下发指令控制设备屏幕亮度。

**manifest.json**：

```json
{
  "id": "brightness_demo",
  "name": "屏幕亮度",
  "version": "1.0.0",
  "description": "控制设备屏幕亮度",
  "permissions": ["device"]
}
```

**plugin.py**：

```python
from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.device import send_device_command


@tool(cache=False)
async def set_brightness(level: int = 50, tool_manager=None) -> str:
    """设置屏幕亮度。
    参数 level 为 0-100 的整数，0 最暗（关屏），100 最亮。
    用户说"亮度调到 50"→ level=50
    用户说"屏幕最亮"→ level=100
    用户说"屏幕调暗一点"→ level=30"""
    # 参数校验：限制到合法范围
    level = max(0, min(100, level))

    err = await send_device_command(tool_manager, "set_brightness", str(level))
    if err:
        return f"亮度设置失败: {err}"
    return f"已将屏幕亮度设置为 {level}%"
```

**SDK 说明**：

- `from src.use_cases.sdk.device import send_device_command`：下发设备指令的封装。
- `send_device_command(tool_manager, command_id, data)` 返回值语义：**`None` = 成功，字符串 = 失败原因**。`if err:` 即失败分支，无需手写 try/except 和连接判断。
- `tool_manager` 由框架自动注入，**不会出现在 LLM 参数 Schema 中**，LLM 看不到也不会填值。
- 设备指令有副作用，必须 `@tool(cache=False)`，否则二次调用会命中缓存、屏幕不再更新。
- `data` 字段设备端始终按字符串接收，所以整数要 `str(level)` 后再发。
- 调用了 `send_device_command`，必须声明 `"permissions": ["device"]`，否则沙箱裁决器直接拒绝（返回 `设备指令权限未声明`）。

**测试**：设备在线 → 参数 `level=50` → 预期 `已将屏幕亮度设置为 50%`；设备离线 → `亮度设置失败: 设备未连接`。可顺手观察设备屏幕亮度变化。

---

## 示例三：屏幕显示文字（Lua 脚本）

**目标**：在设备屏幕上显示自定义文字。通过 `execute_lua` 指令下发 Lua 脚本，直接操作 LVGL 屏幕控件。

**manifest.json**：

```json
{
  "id": "screen_text_demo",
  "name": "屏幕显示",
  "version": "1.0.0",
  "description": "在设备屏幕上显示文字",
  "permissions": ["device"]
}
```

**plugin.py**：

```python
from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.device import send_device_command


@tool(cache=False)
async def show_text(text: str = "Hello", tool_manager=None) -> str:
    """在设备屏幕上显示文字（支持中英文）。
    当用户说"屏幕上显示 xxx"、"写 xxx 在屏幕上"时调用。
    参数 text: 要显示的文字（支持中英文）"""
    # 1. 先清空表情/字幕层，避免 Lua label 被盖住
    err = await send_device_command(tool_manager, "clear_screen")
    if err:
        return f"显示失败: {err}"

    # 2. Lua 引号转义，防止文字里的引号拼坏脚本
    safe = text.replace('\\', '\\\\').replace('"', '\\"')
    lua_code = (
        'local lv = require("lvgl")\n'
        'local scr = lv.scr_act()\n'
        'local label = lv.label(scr)\n'
        f'lv.label_set_text(label, "{safe}")\n'
        'lv.obj_center(label)'
    )
    err = await send_device_command(tool_manager, "execute_lua", lua_code)
    if err:
        return f"显示失败: {err}"
    return f"已在屏幕上显示：{text}"
```

**SDK 说明**：

- 与示例二同一套 `send_device_command` SDK，只是 `command_id` 换成 `clear_screen` / `execute_lua`。
- `execute_lua` 让你在服务端用 Python 动态拼接 Lua 代码，下发到设备执行（可操作屏幕、GPIO、LED 等）。
- 固件内置中文字体，`lv.label()` 默认即可显示中文，无需额外指定字体。

::: warning Lua 注意事项
- **不要调用 `obj_clean(scr)` 清空屏幕**，会误删系统控件导致崩溃；清屏用 `clear_screen` 指令。
- 每个 `execute_lua` 运行在独立 Lua 状态，无法复用 label 变量，所以示例每次先清屏再建新 label。
:::

**测试**：设备在线 → 参数 `text="你好世界"` → 预期返回 `已在屏幕上显示：你好世界`，且设备屏幕显示"你好世界"。

---

## 示例四：查名言（网络 API 调用 + 插件配置）

**目标**：调用外部 API 获取每日名言，返回给用户播报。

**manifest.json**（含配置项）：

```json
{
  "id": "quote_demo",
  "name": "每日名言",
  "version": "1.0.0",
  "description": "获取每日一句名言金句",
  "config_fields": [
    {
      "key": "api_url",
      "label": "名言 API 地址",
      "type": "text",
      "required": true,
      "placeholder": "https://api.example.com/quote（必填）",
      "default": "https://v1.hitokoto.cn/?c=d&encode=text"
    },
    {
      "key": "timeout",
      "label": "请求超时（秒）",
      "type": "number",
      "required": false,
      "default": "8"
    }
  ],
  "permissions": ["network"]
}
```

**plugin.py**：

```python
from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.http import http_request
from src.use_cases.sdk.utils import get_plugin_config_or_env


@tool()
async def get_quote(tool_manager=None) -> str:
    """获取一句每日名言或金句。当用户说"来一句名言"、"今天说什么"、"说句金句"时调用。"""
    # 读取插件配置（配置 → 环境变量 → 默认值 三级回退）
    api_url = get_plugin_config_or_env(
        tool_manager, "quote_demo", "api_url",
        env_var="QUOTE_API_URL",
        default="https://v1.hitokoto.cn/?c=d&encode=text",
    )
    timeout = int(get_plugin_config_or_env(tool_manager, "quote_demo", "timeout", default="8"))

    # SDK 统一封装超时与异常处理，返回 (response, error)
    resp, err = await http_request("GET", api_url, timeout=timeout)
    if err:
        return f"获取名言失败: {err}"

    quote_text = resp.text.strip()
    if not quote_text:
        return "今日名言为空"

    return f"今日金句：{quote_text}"
```

**SDK 说明**：

- `from src.use_cases.sdk.http import http_request`：`http_request(method, url, *, timeout=...)` 统一处理超时与异常，返回 `(response, error)` 元组——`response` 暴露 `.status_code` / `.text` / `.json()`。
- `from src.use_cases.sdk.utils import get_plugin_config_or_env`：把"设备插件配置 → 环境变量 → 默认值"三层来源合并为一次调用。这里第一个参数必须传插件 id（manifest 里的 `id`）。
- 需要自动解析 JSON 时改用 `http_get_json(url, params=...)`，同样返回 `(data, error)`。
- 调用了 `http_request`，必须声明 `"permissions": ["network"]`；沙箱的 SSRF 防护会自动阻止对内网地址的请求。

**测试**：运行测试 → `get_quote` → 无需参数 → 预期返回 `今日金句：...`（hitokoto 默认地址，无需配置）。也可在插件设置里改 `api_url` 后重测。

---

## 示例五：倒计时器（多指令组合 + StopPipeline）

**目标**：用户说"倒计时 10 秒"后，设备屏幕显示倒计时数字，到 0 时播报"时间到"。

**manifest.json**：

```json
{
  "id": "countdown_demo",
  "name": "倒计时",
  "version": "1.0.0",
  "description": "在设备屏幕上显示倒计时",
  "permissions": ["device"]
}
```

**plugin.py**：

```python
import asyncio

from src.use_cases.sdk.tools import tool, StopPipeline
from src.use_cases.sdk.device import send_device_command


@tool(cache=False)
async def countdown(seconds: int = 10, tool_manager=None) -> str:
    """在设备屏幕上显示倒计时。当用户说"倒计时 10 秒"、"数 5 秒"时调用。
    参数 seconds: 倒计时秒数（1-60）"""
    seconds = max(1, min(60, seconds))

    # 循环下发 Lua 脚本更新屏幕上的数字
    # ⚠️ 不要调用 obj_clean(scr) 清空屏幕，会误删系统控件导致崩溃
    # 每个 execute_lua 运行在独立 Lua 状态，无法复用 label 变量，
    # 每次循环先清屏再创建新 label，避免数字累积
    for i in range(seconds, 0, -1):
        await send_device_command(tool_manager, "clear_screen", "")
        lua_code = (
            'local lv = require("lvgl")\n'
            'local scr = lv.scr_act()\n'
            'local label = lv.label(scr)\n'
            f'lv.label_set_text(label, "{i}")\n'
            'lv.set_style_text_font(label, "mont48")\n'
            'lv.obj_center(label)'
        )
        err = await send_device_command(tool_manager, "execute_lua", lua_code)
        if err:
            return f"倒计时出错: {err}"
        await asyncio.sleep(1)

    # 倒计时结束，清屏并播报
    err = await send_device_command(tool_manager, "clear_screen", "")
    if err:
        return f"倒计时出错: {err}"

    # 抛出 StopPipeline：不再让 LLM 生成回复，直接播报下面的文本
    raise StopPipeline(f"倒计时 {seconds} 秒结束，时间到！")
```

**SDK 说明**：

- `from src.use_cases.sdk.tools import tool, StopPipeline`：`StopPipeline` 由 SDK 统一导出。
- `@tool(cache=False)`：含副作用的工具必须禁用缓存，否则二次调用命中缓存、函数体被跳过。
- 抛出 `StopPipeline(文本)` 后，LLM 不再生成回复，直接播报传入的文本（工具已接管音频/屏幕通道时使用）。

::: tip 关于运行测试的提示
"运行测试"是**直接调用工具**，不走 LLM 对话流程，因此**不会拦截 StopPipeline**：直接运行时，倒计时会在屏幕上走完，最后返回 `✓ 运行成功`，结果里显示 `[StopPipeline] 倒计时 N 秒结束，时间到！`——这是工具正常接管屏幕/音频通道后的结束信号，不是错误。
要完整验证"到时播报时间到"，请在**对话**里触发：设备在线时问"倒计时 3 秒"，屏幕逐秒倒数，最后播报"倒计时 3 秒结束，时间到！"。
:::

---

## 示例六：多工具插件（查天气 + 设天气卡片）

**目标**：在一个插件中注册多个工具——查天气 + 设天气卡片。展示真实插件的典型结构：辅助函数 + 多个 `@tool` + KV 配置读写。

**manifest.json**：

```json
{
  "id": "mini_weather_demo",
  "name": "迷你天气",
  "version": "1.0.0",
  "description": "查询天气并显示卡片",
  "requires": ["display"],
  "config_fields": [],
  "permissions": ["network", "device", "kv"]
}
```

**plugin.py**：

```python
from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.http import http_get_json
from src.use_cases.sdk.device import send_device_command
from src.use_cases.sdk.storage import kv_get, kv_set
from src.use_cases.sdk.utils import json_dumps

AMAP_WEATHER_URL = "https://restapi.amap.com/v3/weather/weatherInfo"

# 天气 → 图标 id 映射
WEATHER_ICON = {
    "晴": "sun", "晴间多云": "sun_cloud", "多云": "cloud", "阴": "overcast",
    "小雨": "rain", "中雨": "rain", "大雨": "rain", "雷阵雨": "storm",
    "小雪": "snow", "中雪": "snow", "雾": "fog", "霾": "fog",
}


def _build_card(city: str, weather: str, temp: str) -> str:
    """生成 show_card 卡片 JSON。"""
    icon = WEATHER_ICON.get(weather, "cloud")
    return json_dumps({
        "bg": "000000",
        "card": {"x": 20, "y": 40, "w": 200, "h": 160,
                 "bg": "1E1E1E", "radius": 12, "border": "444444"},
        "items": [
            {"t": "img", "id": icon, "x": 14, "y": 8},
            {"t": "label", "text": city, "x": 54, "y": 16,
             "color": "FFFFFF", "font": "puhui"},
            {"t": "label", "text": f"{temp}°", "y": 30,
             "color": "FFFFFF", "font": "mont48", "align": "center"},
            {"t": "label", "text": weather, "y": 92,
             "color": "AAAAAA", "font": "puhui", "align": "center"},
        ],
    })


@tool(cache=False)
async def get_weather(city: str = "", tool_manager=None) -> str:
    """查询指定城市的实时天气并播报，同时在设备屏幕显示天气卡片。
    只要用户询问天气/气温/冷暖/雨雪/带伞相关的问题，必须调用此工具。
    参数 city: 城市名称，如"北京"、"上海"。用户未指定时留空（默认北京）。"""
    if not city.strip():
        city = "北京"

    # KV 存储读取配置（按设备隔离）
    amap_key = kv_get("amap_key", default="", tool_manager=tool_manager)
    if not amap_key:
        return "天气服务未配置，请先在插件设置中填写高德 API Key"

    # SDK 发起请求并自动解析 JSON，返回 (data, error)
    data, err = await http_get_json(
        AMAP_WEATHER_URL,
        params={"key": amap_key, "city": city, "extensions": "base"},
    )
    if err:
        return f"天气查询失败（网络错误）: {err}"

    if data.get("status") != "1" or not data.get("lives"):
        return f"查询{city}天气失败"

    live = data["lives"][0]
    weather_cn = live.get("weather", "")
    temp = live.get("temperature", "?")
    humidity = live.get("humidity", "?")

    speech = f"{city}当前{weather_cn}，气温{temp}度，湿度{humidity}%"

    # 屏幕卡片：发送失败不影响语音播报（SDK 返回 None 即成功）
    card_json = _build_card(city, weather_cn, temp)
    await send_device_command(tool_manager, "show_card", card_json)

    return speech


@tool(cache=False)
async def save_config(amap_key: str = "", tool_manager=None) -> str:
    """保存插件配置到插件专属 KV 存储。
    参数 amap_key: 高德 API Key。不传则返回当前配置。"""
    if not amap_key:
        current = kv_get("amap_key", default="", tool_manager=tool_manager)
        return json_dumps({"ok": True, "amap_key": current})
    kv_set("amap_key", amap_key, tool_manager=tool_manager)
    return json_dumps({"ok": True, "message": "配置已保存"})
```

**SDK 说明**：

- `from src.use_cases.sdk.storage import kv_get, kv_set`：插件专属键值存储，按设备 MAC 隔离，存于 `data/plugins/kv/{sanitized_mac}/<插件id>.json`。
- `from src.use_cases.sdk.utils import json_dumps`：SDK 提供的 JSON 序列化（`ensure_ascii=False`）。
- 辅助函数用 `_` 前缀（如 `_build_card`）不会被注册为工具，只有 `@tool()` 装饰的函数进入 LLM 工具列表。
- `requires: ["display"]`：声明需要屏幕能力，无屏设备连接时此插件自动隐藏。
- 权限：`network`（查天气）、`device`（显示卡片）、`kv`（读写配置）三个都要声明。

**测试**（设备需在线且带屏幕）：

1. 运行测试 → 选 `save_config` → 参数 `amap_key` 填你的高德 Key → 预期 `{"ok": true, "message": "配置已保存"}`。
2. 再选 `get_weather` → 参数 `city` 填 `北京` → 预期返回 `北京当前...气温...度...`，且设备屏幕显示天气卡片。
3. 不带 Key 调 `save_config` 可回读当前配置；未配置 Key 时 `get_weather` 返回"天气服务未配置"。

::: tip 前端配置页面（可选）
此插件可以带一个前端配置页（`frontend/index.html`）方便在界面上填 Key——完整版本见《[编写第一个插件](./writing-first-plugin.md#示例六：多工具插件一个插件注册多个工具)》。纯用"运行测试"验证时**可以省略前端**，直接用 `save_config` 工具写入配置。
:::

---

## 示例七：设备状态与指令回执（device_is_online / device_get_info / send_device_command_ack）

**目标**：查询设备在线状态与基础信息；用"指令回执"方式读取设备返回值（如当前音量）。

**manifest.json**：

```json
{
  "id": "device_status_demo",
  "name": "设备状态",
  "version": "1.0.0",
  "description": "查询设备在线状态与指令回执",
  "permissions": ["device"]
}
```

**plugin.py**：

```python
from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.device import device_is_online, device_get_info, send_device_command_ack
from src.use_cases.sdk.utils import get_device_key, json_dumps


@tool()
async def device_status(tool_manager=None) -> str:
    """查询当前绑定设备的在线状态与基础信息。用户问"设备在线吗"、"查一下设备状态"时调用。"""
    key = get_device_key(tool_manager)
    if not key:
        return "当前没有绑定设备"
    if not device_is_online(key, tool_manager=tool_manager):
        return f"设备 {key} 当前离线"
    info = await device_get_info(key, tool_manager=tool_manager)
    return json_dumps({"device": key, "online": True, "info": info}, indent=2)


@tool(cache=False)
async def read_volume(tool_manager=None) -> str:
    """读取设备当前音量（等待设备回执）。当用户问"音量是多少"、"现在几格音量"时调用。"""
    result, status, detail = await send_device_command_ack(
        tool_manager, "get_volume", "", timeout=5.0
    )
    if status != "ok":
        return f"读取失败: {status} {detail}"
    return f"当前音量: {result}"
```

**SDK 说明**：

- `device_is_online(device_key, tool_manager)`：同步查询，返回布尔。
- `device_get_info(device_key, tool_manager)`：异步查询设备信息，返回 dict。
- `send_device_command_ack(tool_manager, command_id, data, timeout)`：发出指令并**等待设备回复**，返回 `(result, status, detail)` 三元组——`status == "ok"` 才取 `result`。比"发出即返回"的 `send_device_command` 多一步等待回执。

**测试**：设备在线 → `device_status` 返回在线信息 JSON；`read_volume` 返回当前音量（需固件支持 `get_volume` 指令回执，否则返回 timeout/error）。

---

## 示例八：设备 IO（GPIO / PWM / ADC / 舵机）

**目标**：演示 `sdk.io` 全部能力——数字读写、PWM、ADC、舵机。

**manifest.json**：

```json
{
  "id": "io_demo",
  "name": "设备 IO",
  "version": "1.0.0",
  "description": "GPIO / PWM / ADC / 舵机示例",
  "permissions": ["device"]
}
```

**plugin.py**：

```python
from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.io import gpio_write, gpio_read, pwm_write, adc_read, servo_write


@tool(cache=False)
async def gpio_set(pin: int = 2, value: int = 1, tool_manager=None) -> str:
    """控制 GPIO 引脚输出高低电平。
    参数 pin: GPIO 引脚号（如 2）；value: 0 低电平 / 1 高电平"""
    err = await gpio_write(pin, value, tool_manager=tool_manager)
    if err:
        return f"GPIO 操作失败: {err}"
    return f"GPIO{pin} 已输出{'高' if value else '低'}电平"


@tool()
async def gpio_read_pin(pin: int = 2, tool_manager=None) -> str:
    """读取 GPIO 引脚当前电平（0/1）。"""
    value = await gpio_read(pin, tool_manager=tool_manager)
    if value < 0:
        return f"读取 GPIO{pin} 失败"
    return f"GPIO{pin} 电平: {value}"


@tool(cache=False)
async def pwm_set(pin: int = 5, duty: int = 512, freq: int = 5000, tool_manager=None) -> str:
    """输出 PWM 信号（可驱动 LED 亮度、蜂鸣器等）。
    参数 pin: 引脚；duty: 0-1023；freq: 频率 Hz"""
    err = await pwm_write(pin, duty, freq, tool_manager=tool_manager)
    if err:
        return f"PWM 失败: {err}"
    return f"PWM{pin} 已输出（duty={duty}, {freq}Hz）"


@tool()
async def adc_read_pin(pin: int = 1, tool_manager=None) -> str:
    """读取 ADC 模拟值（ESP32-S3 仅 GPIO1~10 支持 ADC）。"""
    value = await adc_read(pin, tool_manager=tool_manager)
    if value < 0:
        return f"读取 ADC{pin} 失败"
    return f"ADC{pin} 读数: {value}"


@tool(cache=False)
async def servo_move(pin: int = 4, angle: int = 90, tool_manager=None) -> str:
    """控制舵机转到指定角度（0-180 度）。"""
    err = await servo_write(pin, angle, tool_manager=tool_manager)
    if err:
        return f"舵机控制失败: {err}"
    return f"舵机已转到 {angle}°"
```

**SDK 说明**：

- `gpio_mode(pin, mode)` 可先配置引脚模式（output/input/input_pullup/...），`gpio_write` / `gpio_read` 读写数字信号。
- `pwm_write(pin, duty, freq)`：duty 0-1023，freq 默认 5000Hz（LEDC）。
- `adc_read(pin)`：返回 0-4095，失败返回 -1。
- `servo_write(pin, angle)`：0-180 度。
- 这些 IO 操作统一返回"成功 `''` / 失败原因"（写操作）或数字（读操作）。

**测试**：需按固件接线把对应引脚接好硬件（LED/按键/电位器/舵机）。填对 `pin` 后逐个运行，观察硬件动作。引脚号与 `esp-ai-idf-client` 固件定义不一致时会返回设备端错误。

---

## 示例九：音乐播放（sdk.music）

**目标**：让设备播放一段网络音频。

**manifest.json**：

```json
{
  "id": "music_demo",
  "name": "音乐播放",
  "version": "1.0.0",
  "description": "播放网络音频示例",
  "permissions": ["device"]
}
```

**plugin.py**：

```python
from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.music import play_music_url


@tool(cache=False)
async def play_song(url: str = "", title: str = "网络音频", tool_manager=None) -> str:
    """播放一段音频/音乐。当用户提供音频直链要求播放时调用。
    参数 url: 音频文件直链（http/https，mp3 等）"""
    if not url.strip():
        return "请提供音频链接"
    err = await play_music_url(url, title=title, artist="")
    if err:
        return f"播放失败: {err}"
    return f"开始播放：{title}"
```

**SDK 说明**：

- `play_music_url(url, title="", artist="", duration=0, device_key="", ...)` 直接向设备下发音乐播放指令，返回 `"ok"` 或错误串。
- 注意：**沙箱版本的 `play_music_url` 没有 `tool_manager` 参数**，直接调用即可（设备 key 由主进程按绑定设备解析）。

**测试**：设备在线 → 填一个 mp3 直链（如公开测试音频 URL）→ 预期 `开始播放：网络音频`，设备扬声器出声。

---

## 示例十：KV 键值存储（sdk.storage.kv_*）

**目标**：演示插件专属键值存储的读写、删除、列举（按设备隔离）。

**manifest.json**：

```json
{
  "id": "kv_demo",
  "name": "KV 存储",
  "version": "1.0.0",
  "description": "键值存储示例",
  "permissions": ["kv"]
}
```

**plugin.py**：

```python
from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.storage import kv_get, kv_set, kv_delete, kv_list
from src.use_cases.sdk.utils import json_dumps


@tool(cache=False)
async def kv_write(key: str = "", value: str = "", tool_manager=None) -> str:
    """写入插件专属键值存储（按设备隔离）。
    参数 key: 键名；value: 值"""
    if not key.strip():
        return "请提供 key"
    kv_set(key, value, tool_manager=tool_manager)
    return f"已保存 {key} = {value}"


@tool()
async def kv_read(key: str = "", tool_manager=None) -> str:
    """读取插件专属键值存储中的值。
    参数 key: 键名"""
    if not key.strip():
        return "请提供 key"
    value = kv_get(key, default="(未设置)", tool_manager=tool_manager)
    return f"{key} = {value}"


@tool(cache=False)
async def kv_remove(key: str = "", tool_manager=None) -> str:
    """删除插件专属键值存储中的一个键。"""
    if not key.strip():
        return "请提供 key"
    ok = kv_delete(key, tool_manager=tool_manager)
    return f"已删除 {key}" if ok else f"删除失败（{key} 可能不存在）"


@tool()
async def kv_list_all(tool_manager=None) -> str:
    """列出本插件已保存的所有键。"""
    keys = kv_list(tool_manager=tool_manager) or []
    return json_dumps({"keys": keys, "count": len(keys)})
```

**SDK 说明**：

- `kv_get(key, default=None)` / `kv_set(key, value)` / `kv_delete(key)` / `kv_list(prefix="")`，均为同步调用、无需 `await`。
- 存储路径 `data/plugins/kv/{sanitized_mac}/<插件id>.json`，按设备 MAC 隔离。
- 读操作无副作用，可保持默认缓存；写/删有副作用，用 `cache=False`。

**测试**：`kv_write(key="greeting", value="你好")` → `kv_read(key="greeting")` → `kv_list_all` → `kv_remove(key="greeting")`。

---

## 示例十一：插件文件读写（sdk.storage.plugin_data_*）

**目标**：演示在插件目录读写文件（缓存、自定义日志、数据管理）。

**manifest.json**：

```json
{
  "id": "file_demo",
  "name": "插件文件",
  "version": "1.0.0",
  "description": "插件文件读写示例",
  "permissions": ["file_read", "file_write"]
}
```

**plugin.py**：

```python
from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.storage import plugin_data_write, plugin_data_read, plugin_data_list, plugin_data_delete
from src.use_cases.sdk.utils import json_dumps


@tool(cache=False)
async def file_write_text(filename: str = "note.txt", content: str = "", tool_manager=None) -> str:
    """把文本写入插件目录下的文件（用于缓存/自定义日志）。
    参数 filename: 文件名；content: 内容"""
    if content == "":
        return "请提供要写入的内容"
    plugin_data_write(filename, content, tool_manager=tool_manager)
    return f"已写入 {filename}"


@tool()
async def file_read_text(filename: str = "note.txt", tool_manager=None) -> str:
    """读取插件目录下的文件内容。
    参数 filename: 文件名"""
    content = plugin_data_read(filename, tool_manager=tool_manager)
    if content is None:
        return f"文件 {filename} 不存在"
    return content


@tool()
async def file_list_all(tool_manager=None) -> str:
    """列出插件目录下的所有文件。"""
    return json_dumps(plugin_data_list(tool_manager=tool_manager) or [])


@tool(cache=False)
async def file_remove(filename: str = "note.txt", tool_manager=None) -> str:
    """删除插件目录下的一个文件。"""
    ok = plugin_data_delete(filename, tool_manager=tool_manager)
    return f"已删除 {filename}" if ok else f"删除失败（{filename} 可能不存在）"
```

**SDK 说明**：

- `plugin_data_write(path, content)` / `plugin_data_read(path)` / `plugin_data_list(path="")` / `plugin_data_delete(path)`，同步调用，路径相对插件数据目录。
- `file_read` 权限：读/列举；`file_write` 权限：写/删。manifest 里两者都要声明。

**测试**：`file_write_text(filename="note.txt", content="今天天气不错")` → `file_read_text` → `file_list_all` → `file_remove`。

---

## 示例十二：长期记忆（sdk.services LTM）

**目标**：把事实写入设备的长期记忆，并按关键词检索。

**manifest.json**：

```json
{
  "id": "memory_demo",
  "name": "长期记忆",
  "version": "1.0.0",
  "description": "长期记忆读写示例",
  "permissions": ["ltm"]
}
```

**plugin.py**：

```python
from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.services import get_ltm_service
from src.use_cases.sdk.utils import get_device_key, json_dumps


@tool(cache=False)
async def memory_save(content: str = "", tool_manager=None) -> str:
    """把一条事实写入设备的长期记忆。当用户交代重要信息、喜好、习惯时调用。
    参数 content: 要记住的内容（归一化事实句，如"小明喜欢喝咖啡"）"""
    if not content.strip():
        return "请提供要记住的内容"
    key = get_device_key(tool_manager)
    service = get_ltm_service(tool_manager)
    memory_id, changed = await service.store({
        "device_id": key,
        "content": content,
        "tags": ["插件示例"],
        "keywords": ["记忆"],
    })
    return f"已记住（id={memory_id}，新增={changed}）"


@tool()
async def memory_recall(query: str = "", tool_manager=None) -> str:
    """从设备的长期记忆中检索内容。当用户问"你还记得 xxx 吗"时调用。
    参数 query: 检索关键词"""
    if not query.strip():
        return "请提供检索关键词"
    service = get_ltm_service(tool_manager)
    items = await service.recall({"device_id": "", "keyword": query, "limit": 5})
    if not items:
        return "暂时没找到相关记忆"
    return json_dumps(items, indent=2)
```

**SDK 说明**：

- `get_ltm_service(tool_manager)` 返回服务代理，`await service.store(item)` 存记忆、`await service.recall(query)` 检索。
- 记忆 item 是 dict：`device_id` / `content`（核心事实）/ `tags`（摘要标签）/ `keywords`（关键词）。
- 数据按设备隔离，跨设备读写会被沙箱裁决器拦截。

**测试**：`memory_save(content="小明喜欢喝咖啡")` → `memory_recall(query="咖啡")` → 返回记忆 JSON。

---

## 示例十三：数据库访问（日记 / 设备配置 / 用户画像）

**目标**：演示 `sdk.services` 的数据库能力——写日记、读设备配置、查用户画像。

**manifest.json**：

```json
{
  "id": "db_demo",
  "name": "数据库访问",
  "version": "1.0.0",
  "description": "日记 / 设备配置 / 用户画像示例",
  "permissions": ["db"]
}
```

**plugin.py**：

```python
from datetime import datetime

from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.services import get_diary_repository, get_device_repository, get_user_profile_summary
from src.use_cases.sdk.utils import get_device_key, json_dumps


@tool(cache=False)
async def diary_write(content: str = "", tool_manager=None) -> str:
    """写一条日记到设备日志。当用户说"记一下 xxx"、"写日记"时调用。
    参数 content: 日记内容"""
    if not content.strip():
        return "请提供日记内容"
    key = get_device_key(tool_manager)
    today = datetime.now().strftime("%Y-%m-%d")
    repo = get_diary_repository()
    await repo.upsert_entry(key, today, content, append=True)
    return "已写入今天的日记"


@tool()
async def diary_read_recent(tool_manager=None) -> str:
    """读取设备最近几天的日记。"""
    key = get_device_key(tool_manager)
    entries = await get_diary_repository().get_recent(key, limit=3)
    if not entries:
        return "还没有日记"
    return json_dumps(entries, indent=2)


@tool()
async def device_config_info(tool_manager=None) -> str:
    """读取当前设备的配置信息（只读，不修改）。"""
    key = get_device_key(tool_manager)
    config = await get_device_repository().get_device_config(key)
    if not config:
        return "未查询到设备配置"
    return json_dumps(config, indent=2)


@tool()
async def user_profile(tool_manager=None) -> str:
    """读取当前设备关联的用户画像摘要。"""
    key = get_device_key(tool_manager)
    summary = await get_user_profile_summary(key, tool_manager=tool_manager)
    return summary
```

**SDK 说明**：

- `get_diary_repository()`：`await upsert_entry(device_id, date, content, append=...)` / `await get_recent(device_id, limit=...)`。
- `get_device_repository()`：`await get_device_config(device_id)` 读配置；`update_device_partial(device_id, partial)` 可改配置（**敏感，示例只做只读演示**）。
- `get_user_profile_summary(device_key, tool_manager)`：异步返回用户画像文本。
- 日记/设备配置等数据操作必须限定在绑定设备，跨设备会被拦截。

**测试**：`diary_write(content="今天测试插件")` → `diary_read_recent` → `device_config_info` → `user_profile`。

---

## 示例十四：LLM 对话（sdk.services.llm_chat / llm_generate）

**目标**：在插件里直接调用大模型做文本分析、智能回复。

**manifest.json**：

```json
{
  "id": "llm_demo",
  "name": "LLM 调用",
  "version": "1.0.0",
  "description": "插件内调用大模型示例",
  "permissions": ["llm"]
}
```

**plugin.py**：

```python
from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.services import llm_chat, llm_generate


@tool(cache=False)
async def ask_llm(question: str = "", tool_manager=None) -> str:
    """把用户问题交给大模型分析并返回回答。当插件需要文本分析、智能回复时调用。
    参数 question: 用户的问题或要分析的文本"""
    if not question.strip():
        return "请提供问题"
    answer = await llm_chat(
        messages=[{"role": "user", "content": question}],
        system_prompt="你是一个简洁的助手，回答不超过50字。",
        tool_manager=tool_manager,
    )
    return answer or "LLM 未返回内容"


@tool(cache=False)
async def gen_text(prompt: str = "", tool_manager=None) -> str:
    """用一句提示词生成一段文本。
    参数 prompt: 生成提示词"""
    if not prompt.strip():
        return "请提供提示词"
    text = await llm_generate(prompt, tool_manager=tool_manager)
    return text or "LLM 未返回内容"
```

**SDK 说明**：

- `llm_chat(messages, system_prompt=None, tool_manager=None)`：多轮对话，`messages` 是 `[{"role": "user"/"assistant", "content": ...}]`。
- `llm_generate(prompt, system_prompt=None, tool_manager=None)`：单提示词生成。
- 需要 `"llm"` 权限；LLM 服务（全局或设备配置）需已启用。

**测试**：`ask_llm(question="用一句话介绍 ESP32")` → 返回大模型回答。

---

## 示例十五：TTS 合成与主动播报（sdk.services.tts_synthesize / speak_to_device）

**目标**：把文本合成为音频（拿原始字节），以及让设备直接播报一段话。

**manifest.json**：

```json
{
  "id": "tts_demo",
  "name": "TTS 播报",
  "version": "1.0.0",
  "description": "TTS 合成与主动播报示例",
  "permissions": ["tts", "device"]
}
```

**plugin.py**：

```python
from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.services import tts_synthesize, speak_to_device


@tool(cache=False)
async def tts_probe(text: str = "你好", tool_manager=None) -> str:
    """把文本合成为语音，返回音频大小（用于验证 TTS 链路是否可用）。
    参数 text: 要合成的文本"""
    audio = await tts_synthesize(text, tool_manager=tool_manager)
    if not audio:
        return "TTS 合成失败"
    return f"合成成功，音频 {len(audio)} 字节"


@tool(cache=False)
async def speak_now(text: str = "", tool_manager=None) -> str:
    """让设备直接播报一段话（边合成边推流播放）。当用户要求"播报 xxx"时调用。
    参数 text: 要播报的文本"""
    if not text.strip():
        return "请提供要播报的文本"
    ok = await speak_to_device("", text, tool_manager=tool_manager)
    if not ok:
        return "播报失败：设备离线或语音服务不可用"
    return "正在播报"
```

**SDK 说明**：

- `tts_synthesize(text, voice=None, tool_manager=None)`：返回**音频原始字节**（bytes），适合自建音频处理；工具函数要转成可返回的字符串（如长度）。
- `speak_to_device(device_key="", text="", tool_manager=None)`：`device_key` 留空由主进程回退到绑定设备，直接推流播放。
- 权限：`tts_synthesize` 需 `"tts"`；`speak_to_device` 需 `"device"` + `"tts"`（播报 = 设备动作 + 使用 TTS 合成）。

**测试**：`tts_probe(text="你好")` → 返回音频字节数；设备在线时 `speak_now(text="大家好")` → 设备直接出声。

---

## 示例十六：WebSocket 客户端（sdk.ws）

**目标**：在插件里建立 WebSocket 连接、收发消息（适合对接实时推送服务）。

**manifest.json**：

```json
{
  "id": "ws_demo",
  "name": "WebSocket",
  "version": "1.0.0",
  "description": "WebSocket 客户端示例",
  "permissions": ["network"]
}
```

**plugin.py**：

```python
from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.ws import ws_connect, ws_send, ws_recv, ws_close


@tool(cache=False)
async def ws_echo(url: str = "", message: str = "ping", tool_manager=None) -> str:
    """连接一个 WebSocket 服务并发送一条消息，返回收到的回复（用于测试 WS 服务）。
    参数 url: wss:// 开头的 WebSocket 地址；message: 要发送的消息"""
    if not url.strip():
        return "请提供 WebSocket 地址（wss:// 开头）"
    session_id = await ws_connect(url)
    if not session_id:
        return "连接失败"
    try:
        await ws_send(session_id, message.encode("utf-8"))
        data = await ws_recv(session_id, timeout=3.0)
        if data is None:
            return "连接成功，但超时未收到回复"
        return f"收到回复: {data.decode('utf-8', errors='replace')}"
    finally:
        await ws_close(session_id)
```

**SDK 说明**：

- `ws_connect(url, headers=None, pool="normal", ...)` → 返回 `session_id`；`ws_send(session_id, data: bytes)`、`ws_recv(session_id, timeout)`、`ws_close(session_id)`。
- `ws_send` / `ws_recv` 收发的是**二进制 bytes**。
- 需要 `"network"` 权限；沙箱对 WS 地址同样做 SSRF 防护。

**测试**：填一个公开 echo 服务（如 `wss://echo.websocket.org`）→ 预期返回 `收到回复: ping`。

---

## 示例十七：流式 HTTP / SSE（sdk.http.http_stream_*）

**目标**：以流式方式读取 SSE / 长连接接口的数据（如逐行推送）。

**manifest.json**：

```json
{
  "id": "sse_demo",
  "name": "流式 HTTP",
  "version": "1.0.0",
  "description": "SSE 流式读取示例",
  "permissions": ["network"]
}
```

**plugin.py**：

```python
from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.http import http_stream_open, http_stream_read, http_stream_close


@tool(cache=False)
async def sse_probe(url: str = "", tool_manager=None) -> str:
    """读取一个 SSE 流式接口的前几行（用于测试流式 HTTP）。
    参数 url: SSE / 流式接口地址"""
    if not url.strip():
        return "请提供 SSE 地址"
    stream_id, err = await http_stream_open("GET", url)
    if err:
        return f"打开流失败: {err}"
    lines = []
    try:
        for _ in range(5):
            line, err = await http_stream_read(stream_id, timeout=2.0)
            if err:
                return f"读取流失败: {err}"
            if line is None:
                break
            lines.append(line)
    finally:
        await http_stream_close(stream_id)
    if not lines:
        return "流已结束，无数据"
    return f"收到 {len(lines)} 行数据: " + " | ".join(lines)
```

**SDK 说明**：

- `http_stream_open(method, url, *, headers, content, timeout=30)` → `(stream_id, None)` 或 `(None, err)`。
- `http_stream_read(stream_id, timeout)` → `(line, None)`；超时/结束返回 `(None, None)`。
- `http_stream_close(stream_id)` 关闭流。记得用 `try/finally` 确保关闭。
- 需要 `"network"` 权限。

**测试**：填一个 SSE 接口地址（如某些 AI 流式接口）→ 返回前几行数据。

---

## 示例十八：通用工具函数与自定义日志（sdk.utils + plugin_log）

**目标**：演示纯本地的通用函数（UUID、时间戳、JSON 序列化）与自定义日志。

**manifest.json**：

```json
{
  "id": "utils_demo",
  "name": "工具函数",
  "version": "1.0.0",
  "description": "通用工具函数与自定义日志示例",
  "permissions": []
}
```

**plugin.py**：

```python
from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.utils import get_device_key, generate_uuid, current_timestamp, json_dumps, json_loads
from src.use_cases.sdk.services import plugin_log


@tool()
async def utils_demo(tool_manager=None) -> str:
    """演示 SDK 通用工具函数：设备标识、UUID、时间戳、JSON 序列化。"""
    data = {
        "device": get_device_key(tool_manager),
        "uuid": generate_uuid(),
        "timestamp": current_timestamp(),
        "obj": json_loads(json_dumps({"a": 1, "b": "中文字符"})),
    }
    return json_dumps(data, indent=2)


@tool(cache=False)
async def log_demo(message: str = "测试日志", tool_manager=None) -> str:
    """写入插件自定义日志（可在"运行测试"的运行日志中查看）。
    参数 message: 日志内容"""
    plugin_log(f"[示例] {message}", level="info")
    plugin_log(f"[示例] {message}（警告）", level="warn")
    return "已写入 2 条日志，请查看下方运行日志"
```

**SDK 说明**：

- `get_device_key(tool_manager)`：取绑定设备标识（空串表示未绑定）。
- `generate_uuid()` / `current_timestamp()`：纯本地生成，无需权限。
- `json_dumps(obj, indent)` / `json_loads(s)`：JSON 序列化（`ensure_ascii=False`）。
- `plugin_log(message, level)`：写入插件日志，`level` 支持 debug/info/warn/error；**无需任何权限**。

**测试**：`utils_demo` → 返回设备标识、UUID、时间戳 JSON；`log_demo` → 返回"已写入 2 条日志"，运行日志里能看到 `[示例] ...` 两行。

---

## 示例十九：长期记忆完整生命周期（LTM 增删改查）

**目标**：示例十二只演示了 `store` / `recall`，这里补齐 LTM 的**全部**操作——写入、列举、检索、修改、删除，并展示 `get_default_ltm_service` 的等价用法。

**manifest.json**：

```json
{
  "id": "memory_full_demo",
  "name": "记忆管理",
  "version": "1.0.0",
  "description": "长期记忆完整生命周期示例",
  "permissions": ["ltm"]
}
```

**plugin.py**：

```python
from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.services import get_ltm_service
from src.use_cases.sdk.utils import get_device_key, json_dumps


@tool(cache=False)
async def memory_save(content: str = "", tags: str = "", tool_manager=None) -> str:
    """把一条事实写入设备的长期记忆。当用户交代重要信息、喜好、习惯时调用。
    参数 content: 要记住的内容（归一化事实句，如"小明喜欢喝咖啡"）；
    tags: 逗号分隔的摘要标签（可选，如"喜好,咖啡"）"""
    if not content.strip():
        return "请提供要记住的内容"
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] or ["插件示例"]
    memory_id, changed = await get_ltm_service(tool_manager).store({
        "device_id": get_device_key(tool_manager),
        "content": content,
        "tags": tag_list,
        "keywords": ["记忆"],
    })
    return f"已记住（id={memory_id}，新增={changed}）"


@tool()
async def memory_list_all(tool_manager=None) -> str:
    """列出设备的所有长期记忆。当用户问"你都记得我什么"、"你记住了什么"时调用。"""
    items = await get_ltm_service(tool_manager).list_all(get_device_key(tool_manager)) or []
    if not items:
        return "暂无长期记忆"
    return json_dumps(items, indent=2)


@tool()
async def memory_recall(query: str = "", tool_manager=None) -> str:
    """从设备的长期记忆中检索内容。当用户问"你还记得 xxx 吗"时调用。
    参数 query: 检索关键词"""
    if not query.strip():
        return "请提供检索关键词"
    items = await get_ltm_service(tool_manager).recall(
        {"device_id": "", "keyword": query, "limit": 5}
    )
    if not items:
        return "暂时没找到相关记忆"
    return json_dumps(items, indent=2)


@tool(cache=False)
async def memory_update(memory_id: str = "", content: str = "", tool_manager=None) -> str:
    """修改一条已有的长期记忆。当用户说"把之前那句改成 xxx"时调用。
    参数 memory_id: 记忆 id（用 memory_list_all 查看）；content: 新内容"""
    if not memory_id.strip() or not content.strip():
        return "请提供 memory_id 和新内容"
    ok = await get_ltm_service(tool_manager).update(
        memory_id, {"content": content}, get_device_key(tool_manager)
    )
    return "已更新记忆" if ok else "更新失败（id 不存在）"


@tool(cache=False)
async def memory_forget(memory_id: str = "", tool_manager=None) -> str:
    """删除一条长期记忆。当用户说"忘掉 xxx"、"删掉那句记忆"时调用。
    参数 memory_id: 记忆 id"""
    if not memory_id.strip():
        return "请提供 memory_id"
    result = await get_ltm_service(tool_manager).forget(
        memory_id, get_device_key(tool_manager)
    )
    return f"已遗忘记忆 {memory_id}" if result else f"遗忘失败（{memory_id} 不存在）"
```

**SDK 说明**：

- `get_ltm_service(tool_manager)` 返回 LTM 服务代理，与 `get_default_ltm_service()` 等价（后者的沙箱/主进程签名一致）。
- 代理方法一览：`store(item) -> (id, changed)`、`recall(query) -> list`、`list_all(device_id) -> list`、`update(memory_id, patch, device_id) -> bool`、`forget(memory_id, device_id)`。
- 所有 LTM 操作按设备隔离，`device_id` 一律传 `get_device_key(tool_manager)` 的结果；`recall` 的 `device_id` 可留空由主进程回退到绑定设备。
- 需要 `"ltm"` 权限。

**测试**：`memory_save(content="小明喜欢喝咖啡", tags="喜好,咖啡")` → `memory_list_all`（记下返回的 id）→ `memory_recall(query="咖啡")` → `memory_update(memory_id=上一步的id, content="小明喜欢喝奶茶")` → `memory_list_all`（内容已变）→ `memory_forget(memory_id=该id)` → `memory_list_all`（已删空）。

---

## 示例二十：技能目录与日记搜索（skill_catalog_text + diary_search）

**目标**：演示 `sdk.services` 里示例十三未覆盖的两个能力——读取设备技能目录、按关键词全文搜索日记。

**manifest.json**：

```json
{
  "id": "catalog_demo",
  "name": "技能与日记",
  "version": "1.0.0",
  "description": "技能目录与日记搜索示例",
  "permissions": ["db"]
}
```

**plugin.py**：

```python
from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.services import skill_catalog_text, get_diary_repository
from src.use_cases.sdk.utils import get_device_key, json_dumps


@tool()
async def skill_list(tool_manager=None) -> str:
    """查看当前设备已安装/启用的插件技能目录。当用户问"你装了哪些插件"、"你会做什么"时调用。"""
    catalog = skill_catalog_text(tool_manager) or "（暂无技能）"
    return catalog


@tool()
async def diary_search(keyword: str = "", tool_manager=None) -> str:
    """在设备日记中按关键词搜索历史记录。当用户问"我之前记过 xxx 吗"时调用。
    参数 keyword: 搜索关键词"""
    if not keyword.strip():
        return "请提供搜索关键词"
    results = await get_diary_repository().search(get_device_key(tool_manager), keyword) or []
    if not results:
        return "没找到相关日记"
    return json_dumps(results, indent=2)
```

**SDK 说明**：

- `skill_catalog_text(tool_manager)`：同步返回技能目录文本（只读，**无需任何权限**）。
- `get_diary_repository().search(device_id, keyword)`：按关键词全文搜索日记，返回匹配列表；是示例十三 `get_recent` 的检索版。
- 日记搜索属于数据库操作，需要 `"db"` 权限；`skill_list` 无需权限，两个工具放同一插件里权限取并集即可。

**测试**：`skill_list` → 返回当前设备已安装插件/技能清单；先在示例十三里写一条日记，再 `diary_search(keyword="测试")` → 返回匹配的日记 JSON。

---

## 示例二十一：底层设备指令与设备标识解析（send_instruct + resolve_device_key）

**目标**：演示 `sdk.device` 里示例二/三/七未覆盖的两个函数——底层 `send_instruct`（发完即走）与 `resolve_device_key`（标识解析回退）。

**manifest.json**：

```json
{
  "id": "raw_instruct_demo",
  "name": "底层指令",
  "version": "1.0.0",
  "description": "底层设备指令与标识解析示例",
  "permissions": ["device"]
}
```

**plugin.py**：

```python
from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.device import send_instruct
from src.use_cases.sdk.utils import get_device_key, resolve_device_key


@tool()
async def bind_info(tool_manager=None) -> str:
    """查看当前绑定设备标识及解析结果。当调试设备绑定/多设备场景时调用。"""
    raw = get_device_key(tool_manager)
    resolved = resolve_device_key("", tool_manager=tool_manager)
    return f"绑定设备: {raw or '（无）'} → 解析结果: {resolved or '（无）'}"


@tool(cache=False)
async def raw_command(command: str = "set_brightness", data: str = "100", tool_manager=None) -> str:
    """用底层 send_instruct 发送一条原始设备指令（不检查连接、不等待回执）。
    适合"发完即走"的指令。参数 command: 指令名；data: 指令数据（字符串）"""
    try:
        await send_instruct(None, command, data)
        return f"已发送底层指令 {command}={data}"
    except Exception as e:
        return f"发送失败: {e}"
```

**SDK 说明**：

- `send_instruct(channel, command_id, data)` 是最底层下发接口：**不检查连接状态、不等待回执、不吞异常**——设备离线会抛异常，需要 `try/except`。日常场景用示例二的 `send_device_command`（自带连接检查）更省心。
- `resolve_device_key(device_key, tool_manager)`：传入空串时自动回退到本次调用绑定的设备，返回最终设备标识；用于显式指定设备时做归一化。
- 需要 `"device"` 权限。

**测试**：设备在线 → `bind_info` 返回绑定设备与解析结果；`raw_command(command="set_brightness", data="50")` → 返回 `已发送底层指令 set_brightness=50`（设备离线则返回发送失败原因）。

---

## 示例二十二：WebSocket 连接池（ws_prewarm + pool="reuse"）

**目标**：示例十六演示了普通 WS 收发，这里补充连接池预热 `ws_prewarm` 与 `pool="reuse"` 复用，展示如何降低首字延迟（ASR/TTS 类实时服务的标准做法）。

**manifest.json**：

```json
{
  "id": "ws_pool_demo",
  "name": "WS 连接池",
  "version": "1.0.0",
  "description": "WebSocket 连接池预热示例",
  "permissions": ["network"]
}
```

**plugin.py**：

```python
from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.ws import ws_prewarm, ws_connect, ws_send, ws_recv, ws_close


@tool(cache=False)
async def ws_pool_echo(url: str = "", message: str = "ping", tool_manager=None) -> str:
    """演示 WebSocket 连接池：先预热 2 条连接，再复用池中连接收发一条消息。
    参数 url: wss:// 开头的地址；message: 要发送的消息"""
    if not url.strip():
        return "请提供 WebSocket 地址（wss:// 开头）"
    created = await ws_prewarm(url, count=2)
    if created <= 0:
        return "连接池预热失败（地址不可达或非法）"
    # 用 "reuse" 池取用预热好的连接（close 时归还连接池，不真正断开）
    session_id = await ws_connect(url, pool="reuse")
    if not session_id:
        return "复用连接失败"
    try:
        await ws_send(session_id, message.encode("utf-8"))
        data = await ws_recv(session_id, timeout=3.0)
        if data is None:
            return f"已预热 {created} 条连接，发送成功但超时未收到回复"
        return f"已预热 {created} 条连接，收到回复: {data.decode('utf-8', errors='replace')}"
    finally:
        await ws_close(session_id)
```

**SDK 说明**：

- `ws_prewarm(url, headers=None, count=1, pool_headers=None)`：预先建立 N 条连接放入连接池，返回成功数量；常配合 `pool="prewarm"` 使用（取预热连接，close 时真正关闭）。
- `ws_connect(url, pool="reuse")`：复用池中空闲连接，`ws_close` 时归还连接池而非断开（请求型连接，如 TTS）。
- 需要 `"network"` 权限；沙箱对 WS 地址同样做 SSRF 防护。

**测试**：`url` 填公开 echo 服务（如 `wss://echo.websocket.org`）→ 预期返回 `已预热 2 条连接，收到回复: ping`。

---

## 附录：主进程内置插件专用 SDK（沙箱不可用）

::: danger 适用范围
以下 SDK **只有"内置插件"（随源码分发、进程内加载）才能用**。在线编辑器创建的沙箱插件无法 import 这些模块（沙箱没有对应 RPC 通道），会直接 `ModuleNotFoundError`。它们用于监听框架事件、读取系统配置、等待设备回执等进程内场景。
:::

### A. 事件订阅（sdk.events）

监听设备上线/离线、会话开始/结束、微信消息等框架事件，在插件里做自动联动。

```python
from src.use_cases.sdk.events import (
    subscribe, unsubscribe,
    EVENT_DEVICE_ONLINE, EVENT_DEVICE_OFFLINE,
)
from src.use_cases.sdk.services import plugin_log


def _on_online(device_id: str = "", **_):
    plugin_log(f"[事件] 设备上线: {device_id}", level="info")


def _on_offline(device_id: str = "", **_):
    plugin_log(f"[事件] 设备离线: {device_id}", level="warn")


# 内置插件在模块加载时订阅（沙箱插件不可用）
_sub_ids = [
    subscribe(EVENT_DEVICE_ONLINE, _on_online, plugin_name="my_builtin"),
    subscribe(EVENT_DEVICE_OFFLINE, _on_offline, plugin_name="my_builtin"),
]

# 不再需要时取消订阅（订阅 id 由 subscribe 返回）：
# for sid in _sub_ids:
#     unsubscribe(sid)
```

- 事件常量：`EVENT_DEVICE_ONLINE` / `EVENT_DEVICE_OFFLINE`（payload: `device_id`）、`EVENT_SESSION_START` / `EVENT_SESSION_END`（payload: `device_key`）、`EVENT_WECHAT_MESSAGE`（payload: `chat_id, text`）。
- 回调以**关键字参数**接收 payload（`device_id=...` 等），需带 `**kwargs` 容错；协程回调会被自动包装为后台任务，不阻塞主流程。
- 无需权限声明（事件订阅不经过沙箱裁决器）。

### B. 基础设施封装（sdk.infrastructure）

统一获取系统配置、日志器、设备注册表、微信机器人等框架对象（避免直接 import `src.infrastructure`）。

```python
from src.use_cases.sdk.infrastructure import (
    get_settings, get_logger, get_device_registry,
    get_wechat_bot, get_wechat_binding_mgr, get_remote_config_provider,
)

logger = get_logger("my_builtin")


def show_env():
    settings = get_settings()          # 系统配置对象（含 .env 合并结果）
    registry = get_device_registry()   # 设备注册表（查询在线设备等）
    logger.info("读取系统配置与设备注册表完成")
    return "已读取系统配置（详见插件运行日志）"
```

- `get_settings()`：系统配置（pydantic settings，含 .env）；`get_logger(name)`：命名日志器。
- `get_device_registry()`：设备注册表；`get_wechat_bot()` / `get_wechat_binding_mgr()`：微信机器人与其绑定管理（进程级单例）。
- `get_remote_config_provider()`：远程配置提供者。
- 无需权限声明，内置插件专用。

### C. 新式设备回执封装（sdk.device.lua_execute / get_device_state / device_command_ack）

这三者是 `sdk.device` 的**推荐高层封装**（内部已封装 Future 槽位，插件无需理解框架私有属性），但**当前沙箱 `sdk.device` 未导出**，仅主进程内置插件可用；沙箱插件请用 `send_device_command_ack`（示例七）达到类似效果。

```python
from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.device import lua_execute, get_device_state, device_command_ack


@tool(cache=False)
async def lua_run(tool_manager=None) -> str:
    """在设备 Lua 引擎执行脚本并等待结果。"""
    result, status, detail = await lua_execute(
        tool_manager, 'return "hello from lua"', timeout=5.0
    )
    if status != "ok":
        return f"执行失败: {status} {detail}"
    return f"Lua 返回: {result}"


@tool(cache=False)
async def read_vol(tool_manager=None) -> str:
    """读取设备状态（如音量）。"""
    result, status, detail = await get_device_state(tool_manager, "get_volume", timeout=5.0)
    if status != "ok":
        return f"读取失败: {status} {detail}"
    return f"当前音量: {result}"
```

- 三个封装统一返回 `(result, status, detail)` 三元组，`status` 为 `ok` / `offline` / `timeout` / `error` / `busy`。
- 需要 `"device"` 权限。

---

## 权限对照速查

| 示例 | 用到的 SDK | 权限声明 |
|------|-----------|----------|
| 一、Hello World | `sdk.tools.tool` | `[]` |
| 二、屏幕亮度 | `sdk.device.send_device_command` | `["device"]` |
| 三、屏幕显示 | `sdk.device.send_device_command` | `["device"]` |
| 四、查名言 | `sdk.http.http_request` + `sdk.utils.get_plugin_config_or_env` | `["network"]` |
| 五、倒计时 | `sdk.device.send_device_command` + `sdk.tools.StopPipeline` | `["device"]` |
| 六、迷你天气 | `sdk.http.http_get_json` + `sdk.device.send_device_command` + `sdk.storage.kv_get/kv_set` | `["network", "device", "kv"]` |
| 七、设备状态与回执 | `sdk.device.device_is_online/device_get_info/send_device_command_ack` | `["device"]` |
| 八、设备 IO | `sdk.io.gpio_*/pwm_write/adc_read/servo_write` | `["device"]` |
| 九、音乐播放 | `sdk.music.play_music_url` | `["device"]` |
| 十、KV 存储 | `sdk.storage.kv_*` | `["kv"]` |
| 十一、插件文件 | `sdk.storage.plugin_data_*` | `["file_read", "file_write"]` |
| 十二、长期记忆 | `sdk.services.get_ltm_service` | `["ltm"]` |
| 十三、数据库访问 | `sdk.services.get_diary_repository/get_device_repository/get_user_profile_summary` | `["db"]` |
| 十四、LLM 对话 | `sdk.services.llm_chat/llm_generate` | `["llm"]` |
| 十五、TTS 播报 | `sdk.services.tts_synthesize/speak_to_device` | `["tts", "device"]` |
| 十六、WebSocket | `sdk.ws.ws_connect/ws_send/ws_recv/ws_close` | `["network"]` |
| 十七、流式 HTTP | `sdk.http.http_stream_open/read/close` | `["network"]` |
| 十八、工具函数与日志 | `sdk.utils.*` + `sdk.services.plugin_log` | `[]` |
| 十九、记忆生命周期 | `sdk.services.get_ltm_service`（store/recall/list_all/update/forget） | `["ltm"]` |
| 二十、技能与日记搜索 | `sdk.services.skill_catalog_text` + `get_diary_repository().search` | `["db"]` |
| 二十一、底层指令 | `sdk.device.send_instruct` + `sdk.utils.resolve_device_key` | `["device"]` |
| 二十二、WS 连接池 | `sdk.ws.ws_prewarm` + `ws_connect(pool="reuse")` | `["network"]` |
| 附录 A、事件订阅 | `sdk.events.subscribe/unsubscribe` | 内置插件，无需 |
| 附录 B、基础设施 | `sdk.infrastructure.*` | 内置插件，无需 |
| 附录 C、回执封装 | `sdk.device.lua_execute/get_device_state/device_command_ack` | 内置插件，`["device"]` |

## SDK 能力覆盖对照

| SDK 子模块 | 已覆盖示例 |
|-----------|-----------|
| `sdk.tools`（`tool` / `StopPipeline`） | 一、五 |
| `sdk.device`（指令 / 回执 / 在线状态 / 信息 / 底层 send_instruct） | 二、三、五、六、七、二十一 |
| `sdk.io`（GPIO / PWM / ADC / 舵机） | 八 |
| `sdk.music`（音乐播放） | 九 |
| `sdk.http`（普通请求 / JSON / 流式 SSE） | 四、六、十七 |
| `sdk.storage`（KV / 插件文件） | 六、十、十一 |
| `sdk.services`（LTM / 日记 / 设备配置 / 用户画像 / LLM / TTS / 播报 / 日志 / 技能目录） | 十二、十三、十四、十五、十八、十九、二十 |
| `sdk.utils`（设备 key / 标识解析 / 配置 / UUID / 时间戳 / JSON） | 四、七、十、十八、二十一 |
| `sdk.ws`（WebSocket 客户端 / 连接池预热） | 十六、二十二 |
| `sdk.events`（事件订阅） | 附录 A |
| `sdk.infrastructure`（配置 / 日志 / 注册表 / 微信 / 远程配置） | 附录 B |

## 常见错误排查

| 报错 | 原因 | 解决 |
|------|------|------|
| `插件「x」未声明 device 权限，已阻止该操作` | 调了 `send_device_command` 等但没声明 | manifest 加上 `"permissions": ["device"]` |
| `插件「x」未声明 network 权限，已阻止该操作` | 调了 `http_request`/`http_get_json`/WS 但没声明 | 加上 `"permissions": ["network"]` |
| `插件「x」未声明 kv/ltm/db/llm/tts 权限...` | 数据/模型类操作权限缺失 | 按"权限对照速查"补对应权限 |
| `插件「x」尝试访问非当前设备的数据，已阻止` | 传了与绑定设备不同的 `device_id` | 一律传空串，让主进程按绑定设备解析 |
| `NameError: name 'tool_manager' is not defined` | 函数签名少了 `tool_manager=None` | 加上：`async def foo(..., tool_manager=None)` |
| 第二次调用屏幕不更新 | 忘了 `cache=False` | 含副作用的工具必须 `@tool(cache=False)` |
| 设备不响应指令 | `data` 不是字符串 | 用 `str()` 转换 |
| 运行测试返回 `[StopPipeline] ...` | 工具正常接管屏幕/音频通道而终止流程（如倒计时结束） | 属预期结果，非错误，详见示例五说明 |
| 代码保存后插件加载失败 | 模块顶层写了 `return` 等语句 | 所有逻辑必须包在 `@tool()` 函数内 |

## 下一步

- SDK 完整 API 参考：[插件公共工具库（Plugin SDK）](./plugin-sdk.md)
- 插件架构与生命周期：[插件开发教程](./plugin-dev.md)
- 沙箱权限模型：[插件沙箱机制](./sandbox.md)
