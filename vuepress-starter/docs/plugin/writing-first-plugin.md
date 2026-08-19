# 编写第一个插件

本篇通过 **6 个渐进式示例**，带你从零写出第一个插件。每个示例都可独立运行，逐步引入新概念。读完本文，你将掌握：工具注册、设备指令、参数校验、屏幕显示、网络调用、插件配置、中断 Pipeline 等核心能力。

::: tip 阅读前提
建议先浏览 [插件开发教程](./plugin-dev.md) 了解整体架构，再回到本篇动手实践。所有示例均基于真实内置插件代码简化而来，确保可直接复制运行。

示例二起会用到插件 SDK（`src/use_cases/_plugin_helpers.py`）——它统一封装了设备指令、配置读取、HTTP 请求等高频操作。完整说明见 [插件公共工具库（Plugin SDK）](./plugin-sdk.md)。
:::

---

## 示例一：Hello World（最简插件）

**目标**：注册一个工具，用户说"打招呼"时回复一句问候。不涉及设备硬件，仅返回文本由 TTS 播报。

### 1. 创建文件

```
hello/
├── manifest.json
└── plugin.py
```

**manifest.json**：

```json
{
  "id": "hello",
  "name": "打招呼",
  "version": "1.0.0",
  "description": "一个打招呼的示例插件"
}
```

**plugin.py**：

```python
from src.use_cases.tools_system import tool

@tool()
async def say_hello(name: str = "朋友") -> str:
    """和用户打个招呼。当用户说"打招呼"、"你好"、"问声好"时调用。
    参数 name: 用户名字（可选），用户说了名字就传入"""
    return f"你好，{name}！很高兴见到你。"
```

### 2. 关键点解析

| 要素 | 说明 |
|------|------|
| `@tool()` | 装饰器，将函数注册为 LLM 可调用的工具 |
| `async def` | 工具函数必须是异步函数 |
| `-> str` | 返回类型必须为字符串，返回值会被 TTS 播报给用户 |
| `name: str = "朋友"` | 参数名 + 类型注解 + 默认值，LLM 会根据 docstring 判断何时传参 |
| `"""..."""` | **文档字符串是最重要的部分**，LLM 完全依赖它判断调用时机和参数含义 |

### 3. 效果

用户说："跟张三打个招呼"

LLM 解析后调用 `say_hello(name="张三")`，设备播报："你好，张三！很高兴见到你。"

::: warning 文档字符串决定调用率
如果 docstring 只写"打招呼"，LLM 可能不知道何时调用。要写清触发词（"打招呼"、"你好"）和参数含义（"用户名字"），LLM 调用准确率会大幅提升。
:::

---

## 示例二：控制设备亮度（设备指令 + 参数校验）

**目标**：用户说"亮度调到 50"时，通过 WebSocket 下发指令控制设备屏幕亮度。引入 `tool_manager` 依赖注入和参数范围校验。

### 完整代码

```python
from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import send_device_command

@tool()
async def set_brightness(level: int, tool_manager=None) -> str:
    """设置屏幕亮度。
    参数 level 为 0-100 的整数，0 最暗（关屏），100 最亮。
    用户说"亮度调到 50"→ level=50
    用户说"屏幕最亮"→ level=100
    用户说"屏幕调暗一点"→ level=30"""
    # 参数校验：限制到合法范围
    level = max(0, min(100, level))

    err = await send_device_command(tool_manager, "set_brightness", str(level))
    if err:
        return f"亮度设置指令已生成: {level}%（{err}）"
    return f"已将屏幕亮度设置为 {level}%"
```

### 新概念：`tool_manager` 依赖注入

`tool_manager` 是框架自动注入的参数，**不会出现在 LLM 的参数 Schema 中**——LLM 看不到它，也不会试图填值。框架在调用时自动传入。

通过 `tool_manager` 可以访问：

| 属性/方法 | 说明 |
|-----------|------|
| `tool_manager.channel` | WebSocket 设备通道，下发指令的入口 |
| `tool_manager.get_plugin_config(plugin_id, key, default)` | 读取插件配置（示例四演示） |
| `tool_manager.ctx` | 会话上下文（高级） |
| `tool_manager.fsm` | 会话状态机（高级） |

### 新概念：用 SDK 下发设备指令

示例中使用的是插件 SDK 的 `send_device_command(tool_manager, command_id, data)`。它封装了三条样板逻辑：

- **设备未连接** → 返回 `"设备未连接"`
- **发送异常** → 返回 `"发送失败: xxx"`
- **发送成功** → 返回 `None`

返回值语义：**`None` = 成功，字符串 = 失败原因**。所以示例里 `if err:` 就是失败分支，工具代码无需再手写 `try/except` 和连接判断。

如果不使用 SDK，指令的原始格式是这样的（一般不需要手写）：

```json
{
  "type": "instruct",
  "command_id": "指令名",
  "data": "指令数据（字符串）"
}
```

常用 `command_id` 速查：

| command_id | 功能 | data 格式 |
|------------|------|-----------|
| `set_brightness` | 设置亮度 | `"0"` ~ `"100"` |
| `set_volume` | 设置音量 | `"0.0"` ~ `"1.0"` |
| `add_volume` / `subtract_volume` | 增减音量 | `"0.1"`（每次 10%） |
| `set_rotation` | 屏幕旋转 | `"90"` / `"cw"` / `"ccw"` |
| `execute_lua` | 执行 Lua 脚本 | Lua 代码字符串 |
| `show_card` | 渲染卡片 | JSON 卡片描述 |
| `clear_screen` | 清屏 | `""` |
| `play_music` | 播放音频 | 音频 URL |

::: tip 需要等待设备回执？
`send_device_command` 只负责"发出"，不等待设备回复。如果指令需要设备返回值（如 `execute_lua` 的结果、`get_volume` 的状态），改用 `request_device_result`——详见 [插件公共工具库（Plugin SDK）](./plugin-sdk.md#三、指令回执等待设备回复)。
:::

### 新概念：参数校验

```python
level = max(0, min(100, level))
```

LLM 偶尔会传入超范围值（如 `level=150`）。用 `max`/`min` 钳制到合法范围，比直接报错体验更好。

::: tip 为什么 `data` 要 `str(level)`？
设备端接收的 `data` 字段始终是字符串。整数、浮点数必须手动转为字符串再发送。
:::

---

## 示例三：屏幕显示文字（Lua 脚本）

**目标**：在设备屏幕上显示自定义文字。通过 `execute_lua` 指令下发 Lua 脚本，直接操作 LVGL 屏幕控件。

### 完整代码

```python
from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import send_device_command

@tool()
async def show_text(text: str = "Hello", tool_manager=None) -> str:
    """在设备屏幕上显示文字（支持中英文）。
    当用户说"屏幕上显示 xxx"、"写 xxx 在屏幕上"时调用。
    参数 text: 要显示的文字（支持中英文）"""
    # 构建 Lua 脚本：在屏幕上创建一个 label 并设置文字
    # 固件默认字体即中文字体，中文无需额外设置
    lua_code = (
        'local lv = require("lvgl")\n'
        'local scr = lv.scr_act()\n'
        'local label = lv.label(scr)\n'
        f'lv.label_set_text(label, "{text}")\n'
        'lv.obj_center(label)'
    )

    err = await send_device_command(tool_manager, "execute_lua", lua_code)
    if err:
        return f"显示失败: {err}"
    return f"已在屏幕上显示：{text}"
```

### 新概念：Lua 脚本通道

`execute_lua` 让你在服务器端用 Python 动态拼接 Lua 代码，下发到设备执行。设备固件内置 Lua 引擎，可操作屏幕、GPIO、LED 等。

常用 Lua 模块：

```lua
local lv = require("lvgl")       -- 屏幕 UI 控件
local gpio = require("gpio")     -- GPIO 引脚
local led = require("led")       -- WS2812 灯带
local system = require("system") -- 系统信息
local delay = require("delay")   -- 延时
```

::: warning Lua 注意事项
- **默认字体已支持中文**：固件内置中文字体（`font_puhui_16_4`）为 LVGL 全局默认字体，`lv.label()` 默认即可显示中文，无需调用 `lv.set_style_text_font(obj, "puhui")`
- **不要调用 `obj_clean(scr)` 清空屏幕**，会误删系统控件导致崩溃
- 如需清屏，使用 `clear_screen` 指令而非 Lua 代码
:::

### 进阶：指定中文字体

标签默认即支持中文。如需在其他原生 LVGL 控件中显式指定中文字体，可调用 `lv.set_style_text_font`：

```python
lua_code = (
    'local lv = require("lvgl")\n'
    'local label = lv.label(lv.scr_act())\n'
    f'lv.label_set_text(label, "你好世界")\n'
    'lv.set_style_text_font(label, "puhui")\n'   # 显式指定中文字体
    'lv.obj_center(label)'
)
```

---

## 示例四：查名言（网络 API 调用 + 插件配置）

**目标**：调用外部 API 获取每日名言，返回给用户播报。引入 HTTP 请求、超时控制、`config_fields` 插件配置。

### 1. manifest.json（含配置项）

```json
{
  "id": "quote",
  "name": "每日名言",
  "version": "1.0.0",
  "description": "获取每日一句名言金句",
  "requires": [],
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

### 2. plugin.py

```python
from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import get_plugin_config_or_env, http_request

@tool()
async def get_quote(tool_manager=None) -> str:
    """获取一句每日名言或金句。当用户说"来一句名言"、"今天说什么"、"说句金句"时调用。"""
    # 读取插件配置（配置 → 环境变量 → 默认值 三级回退）
    api_url = get_plugin_config_or_env(
        tool_manager, "quote", "api_url",
        env_var="QUOTE_API_URL",
        default="https://v1.hitokoto.cn/?c=d&encode=text",
    )
    timeout = int(get_plugin_config_or_env(tool_manager, "quote", "timeout", default="8"))

    # SDK 统一封装超时与异常处理，返回 (response, error)
    resp, err = await http_request("GET", api_url, timeout=timeout)
    if err:
        return f"获取名言失败: {err}"

    quote_text = resp.text.strip()
    if not quote_text:
        return "今日名言为空"

    return f"今日金句：{quote_text}"
```

### 3. 新概念：`config_fields` 配置体系

声明 `config_fields` 后，Web 管理界面的插件卡片上会自动出现 **⚙ 配置** 按钮，用户点击即可填写。配置特性：

| 特性 | 说明 |
|------|------|
| **按设备存储** | 每台设备独立配置，互不影响 |
| **白名单校验** | 只接受声明过的字段，未知字段被拒绝 |
| **即时生效** | 保存后热重载在线设备，无需重启 |
| **读取方式** | `tool_manager.get_plugin_config(plugin_id, key, default)` |

示例中使用的是 SDK 的 `get_plugin_config_or_env`，它把三层来源合并为一次调用：

```python
# 优先级：设备插件配置 → 环境变量 → 默认值
api_url = get_plugin_config_or_env(
    tool_manager,      # 自动注入的 tool_manager
    "quote",           # plugin_id：manifest.json 中的 id
    "api_url",         # key：config_fields 中声明的 key
    env_var="QUOTE_API_URL",   # 可空，环境变量名
    default="默认地址",        # 未配置时的默认值
)
```

如果不需要环境变量回退，也可以直接用底层方法：

```python
api_url = tool_manager.get_plugin_config("quote", "api_url", "默认地址")
```

### 4. 新概念：SDK 网络请求

示例中改用 SDK 的 `http_request(method, url, *, params=None, headers=None, content=None, timeout=10.0)`，统一处理超时与异常，返回 `(response, error)` 元组：

```python
# ① 返回 (response, error)，先判断 error 再使用 response
resp, err = await http_request("GET", url, timeout=8)
if err:
    return f"请求失败: {err}"   # 返回可播报的中文提示，TTS 念给用户听

# ② 需要自动解析 JSON 时用 http_get_json
data, err = await http_get_json(url, params={"key": key})
if err:
    return "查询失败"

# ③ 超长结果截断
if len(text) > 3000:
    text = text[:3000] + "（结果已截断）"
```

::: tip 约定
`http_request` / `http_get_json` 永远返回 `(result, None)` 成功 或 `(None, error)` 失败，不再抛异常。拿到结果后先判断 `error` 是否为空。
:::

---

## 示例五：倒计时器（多指令组合 + StopPipeline）

**目标**：用户说"倒计时 10 秒"后，设备屏幕显示倒计时数字，到 0 时播报"时间到"。引入多指令组合、`StopPipeline` 中断机制。

### 完整代码

```python
import asyncio

from src.use_cases.tools_system import tool, StopPipeline
from src.use_cases._plugin_helpers import send_device_command

@tool(cache=False)
async def countdown(seconds: int = 10, tool_manager=None) -> str:
    """在设备屏幕上显示倒计时。当用户说"倒计时 10 秒"、"数 5 秒"时调用。
    参数 seconds: 倒计时秒数（1-60）"""
    seconds = max(1, min(60, seconds))

    # 循环下发 Lua 脚本更新屏幕上的数字
    for i in range(seconds, 0, -1):
        lua_code = (
            'local lv = require("lvgl")\n'
            'local scr = lv.scr_act()\n'
            f'lv.obj_clean(scr)\n'           # 注意：实际应用中不要清屏，此处仅为示例
            f'local label = lv.label(scr)\n'
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

### 新概念：`@tool(cache=False)`

默认情况下，`@tool()` 开启缓存——相同参数 300 秒内复用结果，跳过函数体。对于含副作用的工具（屏幕显示、设备指令、音乐播放），必须禁用缓存：

```python
@tool(cache=False)  # 每次调用都执行函数体
async def countdown(seconds: int = 10, tool_manager=None) -> str:
```

| cache 值 | 行为 | 适用场景 |
|:--------:|------|----------|
| `True`（默认） | 相同参数 300 秒内复用结果 | 纯数据查询（如时间查询） |
| `False` | 每次调用都执行函数体 | 含副作用的工具（屏幕、设备指令、音乐） |

::: danger 忘记 cache=False 的后果
如果屏幕显示类工具没设 `cache=False`，第二次调用时缓存命中，函数体被跳过，屏幕不再更新。
:::

### 新概念：`StopPipeline`

抛出 `StopPipeline` 后，LLM 不再生成回复文本，而是直接播报 `StopPipeline` 中传入的字符串。适用场景：

- 工具已接管音频通道（如播放音乐），不需要 LLM 再生成回复
- 工具已经通过其他方式向用户传达了信息（如屏幕显示）
- 待机/关机场景，不需要任何回复

```python
from src.use_cases.tools_system import StopPipeline

raise StopPipeline("这段文字会被 TTS 播报")  # 带参数：播报后结束
raise StopPipeline()                         # 无参数：静默结束
```

---

## 示例六：多工具插件（一个插件注册多个工具）

**目标**：在一个插件中注册多个工具——查天气 + 设天气卡片。展示真实插件的典型结构：辅助函数 + 多个 `@tool` + 配置读取。

### 1. manifest.json

```json
{
  "id": "mini_weather",
  "name": "迷你天气",
  "version": "1.0.0",
  "description": "查询天气并显示卡片",
  "requires": ["display"],
  "config_fields": [
    {
      "key": "amap_key",
      "label": "高德 API Key",
      "type": "text",
      "required": true,
      "placeholder": "https://console.amap.com 获取（必填）"
    }
  ],
  "permissions": ["network"]
}
```

### 2. plugin.py

```python
import json

from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import (
    get_plugin_config_or_env,
    http_get_json,
    send_device_command,
)

AMAP_WEATHER_URL = "https://restapi.amap.com/v3/weather/weatherInfo"

# 天气 → 图标 id 映射
WEATHER_ICON = {
    "晴": "sun", "多云": "cloud", "阴": "overcast",
    "小雨": "rain", "中雨": "rain", "大雨": "rain",
    "雷阵雨": "storm", "小雪": "snow", "中雪": "snow",
    "雾": "fog", "霾": "fog",
}


def _build_card(city: str, weather: str, temp: str) -> str:
    """生成 show_card 卡片 JSON。"""
    icon = WEATHER_ICON.get(weather, "cloud")
    return json.dumps({
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
    }, ensure_ascii=False)


@tool(cache=False)
async def get_weather(city: str = "", tool_manager=None) -> str:
    """查询指定城市的实时天气并播报，同时在设备屏幕显示天气卡片。
    只要用户询问天气/气温/冷暖/雨雪/带伞相关的问题，必须调用此工具。
    参数 city: 城市名称，如"北京"、"上海"。用户未指定时留空（默认北京）。"""
    if not city.strip():
        city = "北京"

    # SDK 读取配置：设备配置 → 环境变量 → 默认值
    amap_key = get_plugin_config_or_env(
        tool_manager, "mini_weather", "amap_key",
        env_var="AMAP_WEATHER_KEY", default="",
    )
    if not amap_key:
        return "天气服务未配置，请在插件设置中填写高德 API Key"

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
```

### 3. 结构解析

这个示例展示了真实插件的典型代码结构：

```
plugin.py 代码组织
├── 导入区          import json, tool, _plugin_helpers
├── 常量区          AMAP_WEATHER_URL, WEATHER_ICON
├── 辅助函数区      _build_card()
└── 工具定义区      @tool get_weather()
```

辅助函数用 `_` 前缀（如 `_build_card`），不会被注册为工具。只有 `@tool()` 装饰的函数才会进入 LLM 工具列表。

::: tip 相比旧代码简化了什么？
老版本需要手写 `_get_amap_key()`（配置→环境变量回退）、`httpx.AsyncClient` + `try/except`、以及 `send_json` + 连接判断。用 SDK 后这三处分别替换为 `get_plugin_config_or_env`、`http_get_json`、`send_device_command`，工具函数从 60 行瘦身到 40 行。
:::

### 4. `requires` 字段

```json
"requires": ["display"]
```

声明此插件需要屏幕能力。无屏设备连接时，此插件自动隐藏，不会出现在工具列表中。

### 5. `show_card` 卡片协议

比 `execute_lua` 更简洁的屏幕显示方式——下发 JSON 描述，设备端用原生 LVGL 渲染：

```python
# SDK 方式：send_device_command 返回 None 即发送成功
err = await send_device_command(tool_manager, "show_card", json.dumps({
    "bg": "000000",           # 背景色
    "card": { ... },          # 卡片容器
    "items": [ ... ],         # 卡片内容元素
}, ensure_ascii=False))
if err:
    return f"卡片显示失败: {err}"
```

items 支持的元素类型：

| 类型 (`t`) | 用途 | 关键字段 |
|------------|------|----------|
| `img` | 彩色图标 | `id`（sun/cloud/rain/...）, `x`, `y` |
| `label` | 文本标签 | `text`, `color`, `font`, `align` |
| `sep` | 分隔线 | `y`, `color` |

---

## 本地调试流程

### 方式一：直接放 `src/plugins/`（推荐开发阶段）

```bash
# 1. 在服务器源码目录创建插件
mkdir esp-ai-server/src/plugins/hello
# 写好 manifest.json 和 plugin.py

# 2. 热加载（无需重启服务器，需管理员 token）
curl -X POST \
  -H "Authorization: Bearer <your_token>" \
  http://<服务器IP>:8088/api/v1/plugins/reload

# 3. 改代码后再次热加载即可生效
```

### 方式二：打包 zip 上传（测试打包流程）

::: code-tabs#shell
@tab bash
```bash
cd hello
zip -r hello-1.0.0.zip manifest.json plugin.py
```
@tab PowerShell
```powershell
Compress-Archive -Path manifest.json,plugin.py -DestinationPath hello-1.0.0.zip
```
:::

上传：Web 管理界面 → **插件市场 → 开发者** → 拖入 zip → 选择"本地测试"。

### 调试技巧

| 技巧 | 说明 |
|------|------|
| 看日志 | 服务器日志会打印工具调用记录，确认是否被 LLM 选中 |
| docstring 调优 | 如果 LLM 不调用你的工具，大概率是 docstring 不够清晰，加触发词和示例 |
| `return` 调试 | 在函数中 `return` 变量值，通过 TTS 播报来"听"数据 |
| 先测逻辑再接设备 | 先不写 `send_device_command`，只 `return` 文本验证参数解析是否正确 |

### 常见问题排查

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| `NameError: name 'tool_manager' is not defined` | 函数签名缺少 `tool_manager=None` | 加上参数：`async def foo(tool_manager=None) -> str:` |
| LLM 不调用工具 | docstring 太模糊 | 写清触发词、参数含义、调用时机 |
| 第二次调用屏幕不更新 | 忘了 `cache=False` | 含副作用的工具必须 `@tool(cache=False)` |
| 设备不响应指令 | `data` 不是字符串 | 用 `str()` 转换：`"data": str(level)` |
| 中文显示为方框 | 未使用中文字体（旧固件默认字体无中文字形） | 升级固件到默认中文字体版本，或显式 `lv.set_style_text_font(obj, "puhui")` |
| 插件上传后不显示 | 未在设备插件管理中启用 | 商店 → 已安装 → 找到插件 → 点击启用 |

---

## 完整示例速查表

| 示例 | 核心概念 | 适用场景 |
|------|----------|----------|
| 一、Hello World | `@tool()` 注册、docstring、返回文本 | 入门，纯文本回复 |
| 二、控制亮度 | `tool_manager` 注入、`send_device_command`、参数校验 | 设备硬件控制 |
| 三、屏幕显示 | `send_device_command` + `execute_lua`、Lua 脚本拼接 | 自定义屏幕 UI |
| 四、查名言 | `http_request`、`get_plugin_config_or_env` 配置 | 调用外部 API |
| 五、倒计时 | `cache=False`、多指令组合、`StopPipeline` | 接管会话流程 |
| 六、迷你天气 | `http_get_json`、`send_device_command` 卡片、`requires` | 完整真实插件 |

---

## 下一步

- 完整 API 参考：[插件开发教程](./plugin-dev.md)
- 插件市场发布流程：[插件开发教程 → 发布与市场](./plugin-dev.md#发布与市场)
- 高频操作封装：[插件公共工具库（Plugin SDK）](./plugin-sdk.md)
- 设备端指令实现：`esp-ai-idf-client/main/commands/` 目录
- 更多内置插件参考：`esp-ai-server/src/plugins/` 目录下的 `weather`、`alarm`、`media_player` 等
