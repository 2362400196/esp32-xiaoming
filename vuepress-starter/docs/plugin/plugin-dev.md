# 插件开发教程

插件是扩展设备能力的最小单元——一段服务器端 Python 代码，通过 `@tool()` 装饰器注册为 LLM 可调用的工具。插件以 `.zip` 包形式发布，用户在 Web 管理界面一键安装、按设备启用，无需修改服务器核心代码、无需重新编译设备固件。

::: tip 先看这个
编写插件前建议先阅读 [插件公共工具库（Plugin SDK）](./plugin-sdk.md)，SDK 统一封装了设备指令、配置读取、HTTP 请求等高频操作，能帮你少写大量样板代码。
:::

## 架构总览

```
开发者                      云市场                          用户服务器
┌──────────┐    上传 zip    ┌──────────────┐   下载安装   ┌──────────────────┐
│ 编写代码  │ ────────────→ │ manifest.json │ ─────────→ │ data/plugins/     │
│ 打包 zip │               │ + plugin.py  │             │   installed/      │
│ 上架商店 │               │ + 版本/评论   │             │ plugin_loader 加载 │
└──────────┘               └──────────────┘             └──────────────────┘
                                                            │ WebSocket
                                                            ▼
                                                     ┌──────────────┐
                                                     │ 设备端（固件） │
                                                     │ 指令/Lua/卡片 │
                                                     └──────────────┘
```

语音交互闭环：用户说话 → ASR 转文字 → LLM 判断调用哪个工具 → 插件执行逻辑 → 返回文本由 TTS 播报，同时可通过指令通道控制设备屏幕/硬件。

## 推荐导入方式

::: tip 新旧导入路径
插件 SDK 已按功能拆分到 `src/use_cases/sdk/` 子模块中。推荐使用新路径，代码更清晰：

```python
# 推荐（新路径）
from src.use_cases.sdk.http import http_request, http_get_json
from src.use_cases.sdk.device import send_device_command, request_device_result
from src.use_cases.sdk.storage import kv_get, kv_set, plugin_data_read
from src.use_cases.sdk.services import llm_chat, tts_synthesize
from src.use_cases.sdk.music import play_music_url
from src.use_cases.sdk.io import gpio_write, gpio_read
from src.use_cases.sdk.utils import json_dumps, get_device_key

# 兼容（旧路径，仍可用）
from src.use_cases._plugin_helpers import send_device_command, http_get_json
```

旧路径 `from src.use_cases._plugin_helpers import xxx` 仍然兼容，新插件建议使用新路径。
:::

## 快速开始

从零开发一个完整插件，覆盖：编写 → 打包 → 上传全流程。

### 1. 创建插件文件

```
hello/
├── manifest.json    # 插件元数据
└── plugin.py        # 工具入口
```

**manifest.json**：

```json
{
  "id": "hello",
  "name": "打招呼",
  "version": "1.0.0",
  "description": "一个打招呼的示例插件",
  "requires": []
}
```

**plugin.py**：

```python
from src.use_cases.tools_system import tool

@tool()
async def say_hello(name: str = "朋友", tool_manager=None) -> str:
    """和用户打个招呼。当用户说"打招呼"、"你好"时调用。
    参数 name: 用户名字（可选）"""
    if tool_manager and tool_manager.channel:
        await tool_manager.channel.send_json({
            "type": "instruct", "command_id": "execute_lua",
            "data": 'local lv=require("lvgl")\nlocal t=lv.label(lv.scr_act())\nlv.label_set_text(t,"你好 '..name..'")',
        })
    return f"你好，{name}！"
```

### 2. 打包

将 `manifest.json` 和 `plugin.py` 打成 zip 包（文件需在 zip 根目录或单层子目录下）：

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

### 3. 上传

登录 Web 管理界面 → **插件市场 → 开发者** tab → 点击 **开启开发者模式** → 拖入 `hello-1.0.0.zip`，选择：

- **上架商店**：公开发布到市场，所有用户可搜索安装
- **本地测试**：仅安装到当前服务器，不公开

### 4. 本地开发调试（无需打包）

开发阶段可直接在 `src/plugins/` 目录编写，改完调用热加载接口生效（需管理员权限）：

```bash
# 在 src/plugins/ 下创建插件目录
mkdir src/plugins/hello
# 写好 plugin.py 和 manifest.json 后热加载
curl -X POST -H "Authorization: Bearer <token>" http://<服务器IP>:8088/api/v1/plugins/reload
```

## 插件包格式

### zip 结构

```
my-plugin-1.0.0.zip
├── manifest.json     # 必须，插件元数据
├── plugin.py         # 必须，工具注册入口
├── requirements.txt  # 可选，Python 依赖
└── README.md         # 可选，使用说明
```

### manifest.json 字段

manifest.json 字段分为两类：**基础字段**（本地加载器 `PluginManifest` 读取）和**市场字段**（仅云市场上传时使用）。

**基础字段**（本地加载器校验）：

| 字段 | 必填 | 默认值 | 说明 |
|------|:----:|--------|------|
| `id` | 是 | — | 标识符，仅字母/数字/下划线/短横线 |
| `name` | 是 | — | 显示名称（中文） |
| `version` | 否 | `1.0.0` | 版本号 `x.y` 或 `x.y.z`（至少两段，每段以数字开头） |
| `description` | 否 | `""` | 一句话描述 |
| `author` | 否 | `""` | 作者名 |
| `api_version` | 否 | `1.0` | API 兼容版本，加载时校验是否与当前系统兼容 |
| `requires` | 否 | `[]` | 能力要求，如 `["display"]` 表示需屏幕，无屏设备自动隐藏 |
| `config_fields` | 否 | `[]` | 用户配置字段声明，详见[插件配置](#插件配置) |
| `permissions` | 否 | `[]` | 权限声明，如 `["network", "file_read"]`。声明哪些权限决定插件能调用哪些 SDK 能力，未声明的调用会被沙箱拒绝，详见[插件沙箱机制](./sandbox.md) |
| `dependencies` | 否 | `[]` | Python 依赖声明（预留） |
| `file_hashes` | 否 | `[]` | 包内文件 SHA-256 哈希列表，安装时校验，防文件被篡改/夹带 |
| `signature` | 否 | `""` | 开发者数字签名（base64），管理员配置 `PLUGIN_SIGN_PUBLIC_KEY` 后强制本地安装验签 |

**市场字段**（仅 `/api/v1/marketplace/plugins/upload` 上传时读取，本地安装时忽略）：

| 字段 | 说明 |
|------|------|
| `category` | 分类，如 `weather`、`tools`，默认 `general` |
| `tags` | 搜索标签数组，如 `["天气", "温度"]` |
| `changelog` | 版本更新说明 |

### 加载机制

加载器扫描两个目录，同名插件 **installed 目录优先于内置目录**（下载版本覆盖内置）：

| 目录 | 说明 |
|------|------|
| `data/plugins/installed/` | 从市场下载或 zip 安装的插件 |
| `src/plugins/` | 随源码分发的内置插件 |

加载时：**内置插件**在进程内动态 import `plugin.py` → `@tool()` 装饰器自动注册工具到全局工具表 → LLM 会话中即可调用；**已安装插件**则在独立子进程沙箱中加载，与主服务隔离。热加载时先注销旧工具再重新加载，支持改代码不重启服务器。

::: tip 已安装插件跑在沙箱里
第三方插件（来自市场或 zip 上传）运行在**独立子进程沙箱**中：环境变量被擦除、import 被白名单限制、危险系统调用被拦截、SDK 能力按 `permissions` 权限裁决。插件代码拿不到服务器密钥、连不上内网、写不了任意文件。完整机制见[插件沙箱机制](./sandbox.md)。
:::

## 工具定义

`plugin.py` 中用 `@tool()` 装饰器定义工具函数，LLM 根据函数签名和文档字符串自动决策何时调用：

```python
@tool()
async def 工具名(参数: 类型 = 默认值, tool_manager=None) -> str:
    """工具描述：告诉 LLM 何时调用、参数含义（必写！LLM 靠它判断）。
    参数 xxx: 说明"""
    ...
    return "返回给 LLM 的文本（会被 TTS 播报）"
```

### cache 参数

`@tool()` 接受 `cache` 参数（默认 `True`）：

| cache | 行为 | 适用场景 |
|:-----:|------|----------|
| `True`（默认） | 相同参数 300 秒内复用结果，跳过函数体 | 纯数据查询（如纯文本天气） |
| `False` | 每次调用都执行函数 | 含副作用的工具（屏幕显示、设备指令、音乐播放） |

::: warning
含屏幕显示的工具必须设 `cache=False`。否则缓存命中时跳过整个函数，卡片不再显示。天气插件就是 `@tool(cache=False)`。
:::

```python
@tool(cache=False)  # 有屏幕显示副作用，禁用缓存
async def get_weather(city: str = "", tool_manager=None) -> str:
    ...
```

### 参数类型

LLM 传入的参数会自动按类型注解转换：

| 注解 | Schema 类型 | 说明 |
|------|-------------|------|
| `str` | string | 默认类型 |
| `int` | integer | 自动 `int(float(val))` |
| `float` | number | 自动 `float(val)` |
| `bool` | boolean | 字符串 `"true"/"1"/"yes"` 自动转 `True` |
| `list` | array | |
| `dict` | object | |

无默认值的参数标记为 `required`，有默认值的标记为可选。

### 自动注入参数

以下参数名会被框架自动注入，**不出现在 LLM 的参数 Schema 中**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `tool_manager` | `PerUserToolManager` | 工具管理器，含 `channel`、`plugin_configs`、`get_plugin_config()`、`ctx`、`fsm` 等 |
| `channel` | WebSocket | 设备通道，等价于 `tool_manager.channel` |
| `ctx` | dict | 会话上下文（高级场景） |
| `fsm` | SessionFSM | 会话状态机（高级场景） |

最常用的是 `tool_manager`，通过它可以访问设备通道和插件配置。

### 中断 Pipeline

工具接管了音频通道（如播放音乐），不希望 LLM 再生成回复时，抛出 `StopPipeline`：

```python
from src.use_cases.tools_system import tool, StopPipeline

@tool(cache=False)
async def standby(tool_manager=None) -> str:
    """当用户说休息、退下、关机时进入待机"""
    await tool_manager.channel.send_text("session_end")
    raise StopPipeline()  # LLM 不再生成回复
```

## 调用设备能力

### 指令通道

通过 `tool_manager.channel.send_json()` 下发指令控制设备硬件：

```python
await tool_manager.channel.send_json({
    "type": "instruct",
    "command_id": "set_volume",
    "data": "0.8",
})
```

常用指令：

| command_id | 功能 |
|---|---|
| `set_volume` / `add_volume` / `subtract_volume` / `get_volume` | 音量控制 |
| `set_brightness` / `get_brightness` | 亮度控制 |
| `play_music` / `stop_music` | 音乐播放/停止 |
| `execute_lua` | 执行 Lua 脚本（见下文） |
| `show_card` | 渲染卡片（见下文） |
| `set_rotation` | 屏幕旋转 |
| `clear_screen` | 清屏 |
| `update_config` | 更新设备配置 |

### Lua 通道

通过 `execute_lua` 指令下发 Lua 脚本，直接操作 LVGL 屏幕和硬件外设：

```python
lua = 'local lv=require("lvgl")\nlocal t=lv.label(lv.scr_act())\nlv.label_set_text(t,"你好")\nlv.set_style_text_font(t,"puhui")'
await tool_manager.channel.send_json({
    "type": "instruct", "command_id": "execute_lua", "data": lua,
})
```

可用 Lua 模块：

| 模块 | 说明 |
|------|------|
| `lvgl` | 屏幕控件（label/button/image 等） |
| `gpio` | GPIO 引脚 |
| `led` | LED 控制 |
| `system` | 系统信息 |
| `json` | JSON 解析 |
| `delay` | 延时 |
| `adc` | 模拟输入 |
| `uart` | 串口通信 |

::: tip
设备固件内置中文字体（`font_puhui_16_4`，覆盖常用汉字 + 天气符号），并已设为 LVGL 全局默认字体。Lua 创建的标签**默认即支持中文**，无需额外设置：
```lua
local lv = require("lvgl")
local t = lv.label(lv.scr_act())
lv.label_set_text(t, "你好")   -- 直接显示中文
```
如需在其他原生 LVGL 控件中显式使用中文字体，可调用 `lv.set_style_text_font(obj, "puhui")`。
:::

### show_card 卡片协议

通过 `show_card` 指令下发 JSON 描述，设备端用原生 LVGL 渲染卡片，支持彩色图标 + 大号数字 + 中文：

```python
import json

await tool_manager.channel.send_json({
    "type": "instruct",
    "command_id": "show_card",
    "data": json.dumps({
        "bg": "000000",                    # 背景色（RGB hex）
        "card": {                           # 卡片容器
            "x": 20, "y": 40, "w": 200, "h": 160,
            "bg": "1E1E1E", "radius": 12, "border": "444444"
        },
        "items": [
            {"t": "img", "id": "sun", "x": 14, "y": 8},          # 彩色图标
            {"t": "label", "text": "北京市", "x": 54, "y": 16, "color": "FFFFFF", "font": "puhui"},
            {"t": "label", "text": "30°", "y": 30, "color": "FFFFFF", "font": "mont48", "align": "center"},
            {"t": "sep", "y": 114, "color": "3A3A3A"},            # 分隔线
        ],
    }, ensure_ascii=False),
})
```

**items 元素类型**：

| t（类型） | 字段 | 说明 |
|---|---|---|
| `img` | `id`, `x`, `y` | 彩色图标，id 可用：`sun`/`sun_cloud`/`cloud`/`overcast`/`rain`/`storm`/`snow`/`fog` |
| `label` | `text`, `x`/`y`, `color`, `font`, `align` | 文本标签 |
| `sep` | `y`, `color` | 水平分隔线 |

**font 可选值**：

| font | 说明 |
|------|------|
| `"puhui"` | 16px 中文字体（全量汉字 + °·~ 符号） |
| `"mont48"` | 48px 大号数字字体 |
| 省略 | 默认 14px |

::: tip
卡片在表情/状态变化时自动清除。卡片文本需避开源字体缺失的字符（如 ≤≥℃）。
:::

## 插件配置

插件需要用户提供 API Key 等参数时，声明 `config_fields`，Web 界面自动出现配置入口。

### 声明字段

在 `manifest.json` 中声明：

```json
{
  "config_fields": [
    {
      "key": "amap_key",
      "label": "高德 API Key",
      "type": "text",
      "required": true,
      "placeholder": "https://console.amap.com 获取"
    }
  ]
}
```

### 读取配置

::: tip 推荐使用 KV 存储
新版本插件已改用**插件专属 KV 存储**来管理配置，不再经过 `config_fields` 系统。KV 存储路径自动按设备隔离，插件之间互不可见，且支持前端通过 `save_config` 工具读写。详见 [插件公共工具库（Plugin SDK）→ KV 存储](./plugin-sdk.md#十三、键值存储（权限-kv）)。
:::

在工具函数中通过 `kv_get` / `kv_set` 读写：

```python
from src.use_cases.sdk.storage import kv_get, kv_set

@tool(cache=False)
async def get_weather(city: str = "", tool_manager=None) -> str:
    """查询天气"""
    amap_key = kv_get("amap_key", default="", tool_manager=tool_manager)
    if not amap_key:
        return "天气服务未配置，请在插件设置中填写高德 API Key"
    # ... 使用 amap_key 查询天气
```

配置特性：

- **按设备隔离**：KV 文件按设备 MAC 地址隔离，每台设备独立配置
- **即时生效**：保存后热重载在线设备，无需重启
- **前端保存**：通过 `save_config` 工具，前端调用通用工具接口写入

### 设备级配置（plugin_configs，数据库存储）

ASR / LLM / TTS 服务插件（以及任何声明了 `config` 参数的插件工具）使用**设备级配置**：配置保存在 `devices` 表的 `plugin_configs` JSON 字段中，按插件名分组。框架自动完成存储、加载、合并三个环节，**插件开发者无需编写任何数据库代码**。

#### 存储结构

```json
{
  "plugin_configs": {
    "weather":        {"amap_key": "xxx"},
    "asr_volcengine": {"api_key": "yyy", "resource_id": "zzz"},
    "llm_openai":     {"api_key": "yyy", "base_url": "https://api.openai.com/v1", "model": "gpt-4o"}
  }
}
```

#### 保存配置

通过标准接口保存（无需插件代码）：

```
PUT /api/v1/devices/{device_id}/plugins/{plugin_name}/config
{"config": {"api_key": "xxx", "model": "gpt-4o"}}
```

框架处理流程：校验插件存在 → 合并进 `plugin_configs[插件名]`（保留其他插件的配置）→ 写入数据库 → 热重载在线设备立即生效。

#### 运行时读取

设备连接时框架把 `plugin_configs` 加载进 `tool_mgr.plugin_configs`；调用插件工具时，若工具函数声明了 `config` 参数，框架自动把该插件的配置合并进 `config`（非空值覆盖默认值）。插件只需在工具函数中读取：

```python
@tool()
async def asr_volcengine_start_session(config: dict | None = None, ...):
    cfg = config or {}
    api_key = cfg.get("api_key", "")    # 从设备配置读取
    resource_id = cfg.get("resource_id", "volc.bigasr.sauc.duration")  # 带默认值兜底
    if not api_key:
        return {"session_id": "", "error": "api_key 未配置"}
```

::: tip 关于 config_fields
设备级配置**不需要**在 manifest 中声明 `config_fields`。声明它仅有两个作用：① 配置保存接口的键名白名单校验（防止拼错键名）；② 前端配置表单的字段元数据（标签/类型/默认值）。对服务插件而言这两者都不是必需的，因此可以省略，配置保存接口会接受任意键。
:::

#### 与 KV 存储的区别

| 维度 | 设备级配置（plugin_configs） | KV 存储 |
|------|------------------------------|---------|
| 存储位置 | `devices` 表 `plugin_configs` JSON 字段 | `data/plugins/kv/{mac}/xxx.json` 文件 |
| 注入方式 | 自动合并进 `config` 参数 | 工具内 `kv_get` / `kv_set` 手动读写 |
| 适用场景 | 服务插件（ASR/LLM/TTS）等需要框架注入配置的场景 | 普通功能插件的自有状态 / 配置 |
| 配置入口 | 设备配置接口 / 前端表单 | `save_config` 工具 / 前端 |
| 默认值 | `config.get("key", "默认值")` 兜底 | `kv_get("key", default="默认值")` 兜底 |

## 语音服务插件开发（ASR / LLM / TTS）

ASR（语音识别）、LLM（大模型对话）、TTS（语音合成）三类插件是系统的 **AI 服务提供商**。与天气、闹钟这类普通工具插件不同，它们**不直接控制设备**，而是把外部 AI 服务接入系统，供核心语音交互流程调用。

::: tip 详细教程
本章是三类语音服务插件的**总览**。每个插件的完整开发教程（原理、协议、完整代码、调试排错）请分别阅读：

- [ASR 插件开发教程](./asr-plugin.md) — 语音识别（WebSocket 双向流式）
- [TTS 插件开发教程](./tts-plugin.md) — 语音合成（WebSocket 单向流式）
- [LLM 插件开发教程](./llm-plugin.md) — 大模型对话（HTTP SSE 流式 + 工具调用）
:::

### 与普通插件的区别

| 维度 | 普通工具插件 | 语音服务插件 |
|------|-------------|-------------|
| 调用方 | LLM 自主决策调用 | 系统语音流程按固定顺序调用 |
| 数据形态 | 一次性请求/响应 | **流式**：数据边产生边传输 |
| 状态管理 | 无状态 | **跨多次调用**保存会话状态 |
| 底层依赖 | `http_request` | WebSocket（ASR/TTS）+ SSE（LLM） |
| 返回值 | 文本（会被 TTS 播报） | 结构化 dict（`session_id`/`text`/`audio`） |

### 通用工具链设计

三类插件都遵循 **"开始 → 传输/读取 → 结束"** 三段式工具链，每次调用返回结构化 dict 而不是文本：

| 阶段 | ASR | LLM | TTS | 作用 |
|------|-----|-----|-----|------|
| 开始 | `start_session` | `start_chat` | `start_synthesis` | 建立连接/请求，返回会话 ID |
| 传输 | `send_audio` / `get_result` | `get_next` | `get_audio` | 发送数据或拉取增量结果 |
| 结束 | `end_session` | `end_chat` | `end_synthesis` | 发送结束信号、清理资源 |

**会话缓存**：用模块级字典 `_sessions: dict[str, dict]` 保存会话状态，key 是工具返回给上层的短 ID（如 `uuid.uuid4().hex[:8]`）：

```python
_sessions: dict[str, dict] = {}

@tool(cache=False)
async def xxx_start(...) -> dict:
    sess_id = uuid.uuid4().hex[:8]
    _sessions[sess_id] = {"ws_id": ws_id, "done": False, ...}
    return {"session_id": sess_id, "error": None}
```

::: warning 必须 `cache=False`
语音服务工具**全部**要设 `@tool(cache=False)`。默认缓存会在相同参数下 300 秒内跳过函数体，导致第二次识别/合成直接返回旧结果。
:::

### 返回值约定

所有语音服务工具返回**结构化 dict**（而非文本），统一格式：

```python
# 开始类
{"session_id": str, "error": str | None}
# 传输类
{"text": str, "is_final": bool, "error": str | None}     # ASR / LLM
{"audio_base64": str, "done": bool, "error": str | None}  # TTS
# 结束类
{"final_text": str, "error": str | None}
```

- 成功时 `error` 为 `None`，失败时返回可读的中文错误
- 上层根据 `error` 判断是否继续，`is_final` / `done` 判断是否结束

---

### 一、ASR 插件开发（WebSocket 双向流式）

#### 原理

ASR 是**双向流式**：客户端持续发送音频分片，服务端持续返回识别文本。典型协议是火山引擎的 SAUC：

```
客户端 → 服务端：初始化配置帧 → 音频数据帧 → 结束帧
服务端 → 客户端：识别结果帧（增量文本 + 最终标记）
```

SAUC 协议帧格式（火山引擎）：

```
┌──────────────┬──────────────┬──────────────────────────┐
│  4 字节头部   │  4 字节长度   │  payload（JSON / 音频）    │
└──────────────┴──────────────┴──────────────────────────┘
头部字节：
  byte0: version(高4位) | header_size(低4位)
  byte1: message_type(高4位) | flags(低4位)
  byte2: serialization(高4位) | compression(低4位)
  byte3: 保留
```

#### 工具链

| 工具 | 作用 |
|------|------|
| `asr_start_session(config)` | 连接 WebSocket，发送初始化配置，返回 `session_id` |
| `asr_send_audio(session_id, audio)` | 发送 base64 音频分片（16bit PCM / 16kHz / 单声道） |
| `asr_get_result(session_id)` | 拉取最新识别结果（增量文本 + `is_final` 标记） |
| `asr_end_session(session_id)` | 发送结束帧，读取最终结果，关闭连接 |

#### 完整代码

```python
"""ASR 服务插件示例（火山引擎 SAUC 协议）"""

from __future__ import annotations

import asyncio
import base64
import json
import struct
import uuid

from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import ws_connect, ws_send, ws_recv, ws_close

ASR_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"

# 会话缓存：session_id → {"ws_id", "current_text", "is_final"}
_sessions: dict[str, dict] = {}

# 互斥锁：同一 WebSocket 不能并发 recv
_ws_recv_lock = asyncio.Lock()


def _make_header(message_type: int, flags: int = 0) -> bytes:
    """构造 SAUC 协议 4 字节头部。"""
    version = 0x1 << 4
    header_size = 0x1 << 0
    byte0 = (version | header_size).to_bytes(1, "big")
    byte1 = ((message_type << 4) | flags).to_bytes(1, "big")
    serialization = 0x1 << 4  # JSON
    compression = 0x0 << 0
    byte2 = (serialization | compression).to_bytes(1, "big")
    byte3 = (0).to_bytes(1, "big")
    return byte0 + byte1 + byte2 + byte3


def _make_payload(data: dict) -> bytes:
    """构造 JSON payload：4 字节长度 + JSON 数据。"""
    json_bytes = json.dumps(data).encode("utf-8")
    return struct.pack(">I", len(json_bytes)) + json_bytes


def _parse_response(data: bytes) -> dict | None:
    """解析 SAUC 响应帧。"""
    if len(data) < 12:
        return None
    payload_size = struct.unpack(">I", data[8:12])[0]
    if len(data) < 12 + payload_size:
        return None
    try:
        return json.loads(data[12:12 + payload_size].decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _extract_text(result: dict) -> str:
    """从 ASR 结果中提取文本。"""
    texts = result.get("result", {}).get("texts", [])
    if texts:
        return texts[0].get("text", "")
    return result.get("result", {}).get("text", "")


def _is_final(result: dict) -> bool:
    """判断是否为最终结果。"""
    if result.get("is_final"):
        return True
    additions = result.get("result", {}).get("additions", {})
    if additions.get("definite"):
        return True
    return False


@tool(cache=False)
async def asr_start_session(config: dict | None = None, tool_manager=None) -> dict:
    """开始 ASR 识别会话，返回 session_id。

    Args:
        config: 配置，包含 api_key, resource_id, model_name

    Returns:
        {"session_id": str, "error": str|null}
    """
    cfg = config or {}
    api_key = cfg.get("api_key", "")
    if not api_key:
        return {"session_id": "", "error": "api_key 未配置"}

    headers = {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": cfg.get("resource_id", "volc.bigasr.sauc.duration"),
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }
    try:
        ws_id = await ws_connect(ASR_URL, headers)
    except Exception as e:
        return {"session_id": "", "error": f"WebSocket 连接失败: {e}"}

    # 发送初始化配置（message_type=1）
    config_request = _make_header(message_type=1, flags=0)
    config_payload = _make_payload({
        "user": {"uid": "esp-ai"},
        "audio": {"format": "pcm", "rate": 16000, "bits": 16, "channel": 1},
        "request": {
            "model_name": cfg.get("model_name", "bigmodel"),
            "enable_itn": False,
            "enable_punc": False,
            "end_window_size": 400,
            "vad_segment_duration": 2000,
            "force_to_speech_time": 1000,
        },
    })
    await ws_send(ws_id, config_request + config_payload)

    sess_id = uuid.uuid4().hex[:8]
    _sessions[sess_id] = {"ws_id": ws_id, "current_text": "", "is_final": False}
    return {"session_id": sess_id, "error": None}


@tool(cache=False)
async def asr_send_audio(session_id: str, audio: str, tool_manager=None) -> dict:
    """发送音频分片（base64，16bit PCM / 16kHz / 单声道）。"""
    session = _sessions.get(session_id)
    if not session:
        return {"text": "", "is_final": True, "error": "session not found"}

    audio_bytes = base64.b64decode(audio)
    # 发送音频数据（message_type=2），不等待结果
    audio_header = _make_header(message_type=2)
    audio_payload = struct.pack(">I", len(audio_bytes)) + audio_bytes
    try:
        await ws_send(session["ws_id"], audio_header + audio_payload)
    except Exception as e:
        return {"text": session["current_text"], "is_final": True,
                "error": f"发送音频失败: {e}"}
    return {"text": session["current_text"], "is_final": session["is_final"], "error": None}


@tool(cache=False)
async def asr_get_result(session_id: str, tool_manager=None) -> dict:
    """拉取最新识别结果。"""
    session = _sessions.get(session_id)
    if not session:
        return {"text": "", "is_final": True, "error": "session not found"}

    async with _ws_recv_lock:
        data = await ws_recv(session["ws_id"], timeout=0.1)
        if data:
            result = _parse_response(data)
            if result:
                text = _extract_text(result)
                if text:
                    session["current_text"] = text
                if _is_final(result):
                    session["is_final"] = True
    return {"text": session["current_text"], "is_final": session["is_final"], "error": None}


@tool(cache=False)
async def asr_end_session(session_id: str, tool_manager=None) -> dict:
    """结束会话，返回最终识别结果。"""
    session = _sessions.pop(session_id, None)
    if not session:
        return {"final_text": "", "error": "session not found"}

    # 发送结束帧（message_type=2, flags=2），必须带 4 字节长度前缀（值为 0）
    try:
        end_frame = _make_header(message_type=2, flags=2) + struct.pack(">I", 0)
        await ws_send(session["ws_id"], end_frame)
    except Exception as e:
        return {"final_text": session["current_text"], "error": f"发送结束帧失败: {e}"}

    # 读取最终结果
    final_text = session["current_text"]
    while True:
        data = await ws_recv(session["ws_id"], timeout=0.5)
        if data is None:
            break
        result = _parse_response(data)
        if result:
            text = _extract_text(result)
            if text:
                final_text = text
            if _is_final(result) or result.get("code") == 0:
                break

    try:
        await ws_close(session["ws_id"])
    except Exception:
        pass
    return {"final_text": final_text, "error": None}
```

#### 关键点

- **音频格式**：火山 ASR 要求 16bit PCM / 16kHz / 单声道。设备端麦克风采集后需转成该格式，再 base64 编码传给 `send_audio`
- **结束帧的坑**：结束帧也必须带 4 字节 payload 长度前缀（值为 0），否则火山报 `parse payload size failed: body too short` 并强制断连
- **并发 recv**：同一 WebSocket 不能并发 `recv`（websockets 库限制），多协程共享连接时用 `asyncio.Lock()` 保护
- **增量结果**：`get_result` 返回的 `text` 是**累计文本**（服务端回传的是全量），`is_final` 为 True 时表示该句已定稿

#### manifest.json

```json
{
  "id": "asr_volcengine",
  "name": "火山引擎 ASR 提供商",
  "version": "1.0.0",
  "permissions": ["network"],
  "provides": {"asr": ["volcengine"]},
  "config_fields": [
    {"key": "api_key", "label": "API Key", "type": "password"},
    {"key": "resource_id", "label": "Resource ID", "type": "text"},
    {"key": "model_name", "label": "模型", "type": "text", "default": "bigmodel"}
  ]
}
```

- `permissions: ["network"]`：WebSocket 连接需要 `network` 权限
- `provides`：声明本插件提供的服务类型（`asr` / `llm` / `tts`），供系统按能力路由

---

### 二、LLM 插件开发（HTTP SSE 流式）

#### 原理

LLM 是**单向流式**：一次 POST 请求，服务端以 SSE（Server-Sent Events）逐行推送 token。OpenAI 兼容接口的 SSE 格式：

```
data: {"choices":[{"delta":{"content":"你"}}]}
data: {"choices":[{"delta":{"content":"好"}}]}
data: {"choices":[{"delta":{"content":""},"finish_reason":"stop"}]}
data: [DONE]
```

#### 工具链

| 工具 | 作用 |
|------|------|
| `llm_start_chat(messages, config)` | 发起流式请求，返回 `chat_id` |
| `llm_get_next(chat_id)` | 从 SSE 流读取下一个 token |
| `llm_end_chat(chat_id)` | 关闭流并清理 |

#### 完整代码

```python
"""LLM 服务插件示例（OpenAI 兼容接口，真流式）"""

from __future__ import annotations

import json
import time
import uuid

from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import (
    http_stream_open,
    http_stream_read,
    http_stream_close,
)

_sessions: dict[str, dict] = {}


@tool(cache=False)
async def llm_start_chat(messages: list, config: dict | None = None, tool_manager=None) -> dict:
    """开始 LLM 对话（真流式），返回 chat_id。

    Args:
        messages: 对话消息列表 [{"role": "user", "content": "..."}, ...]
        config: 配置，包含 api_key, base_url, model

    Returns:
        {"chat_id": str, "error": str|null}
    """
    cfg = config or {}
    api_key = cfg.get("api_key", "")
    if not api_key:
        return {"chat_id": "", "error": "api_key 未配置"}

    payload = {
        "model": cfg.get("model", "gpt-4o"),
        "messages": messages,
        "stream": True,
    }
    stream_id, err = await http_stream_open(
        "POST",
        f"{cfg.get('base_url', 'https://api.openai.com/v1')}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        content=json.dumps(payload),
        timeout=30.0,
    )
    if err:
        return {"chat_id": "", "error": str(err)}

    chat_id = uuid.uuid4().hex[:8]
    _sessions[chat_id] = {"stream_id": stream_id, "done": False, "error": None}
    return {"chat_id": chat_id, "error": None}


@tool(cache=False)
async def llm_get_next(chat_id: str, tool_manager=None) -> dict:
    """获取下一个 token（从 SSE 流实时读取）。"""
    session = _sessions.get(chat_id)
    if not session:
        return {"token": "", "done": True, "error": "session not found"}
    if session["error"]:
        return {"token": "", "done": True, "error": session["error"]}
    if session["done"]:
        return {"token": "", "done": True, "error": None}

    # 持续读取 SSE 行，直到拿到一段内容或流结束
    while True:
        line, err = await http_stream_read(session["stream_id"], timeout=0.3)
        if err:
            session["error"] = str(err)
            session["done"] = True
            return {"token": "", "done": True, "error": str(err)}
        if line is None:
            # 超时无新数据：LLM 仍在生成，返回空 token 保持轮询
            return {"token": "", "done": False, "error": None}

        line = line.strip()
        if not line or line.startswith(":") or not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            session["done"] = True
            return {"token": "", "done": True, "error": None}

        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            continue

        choices = obj.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        content = delta.get("content") or ""
        if content:
            return {"token": content, "done": False, "error": None}
        if choices[0].get("finish_reason"):
            session["done"] = True
            return {"token": "", "done": True, "error": None}


@tool(cache=False)
async def llm_end_chat(chat_id: str, tool_manager=None) -> dict:
    """清理 LLM 会话并关闭流。"""
    session = _sessions.pop(chat_id, None)
    if session and session.get("stream_id"):
        try:
            await http_stream_close(session["stream_id"])
        except Exception:
            pass
    return {}
```

#### 关键点

- **真流式 vs 假流式**：`http_stream_open/read` 是逐行读取响应体（真流式），不要用 `http_request` 一次性缓冲后逐字符模拟（假流式，首字延迟高）
- **SSE 行解析**：跳过空行、注释行（`:` 开头）、非 `data:` 行；`data: [DONE]` 表示流结束
- **空 token 轮询**：`http_stream_read` 超时返回 `(None, None)`，此时 LLM 仍在生成，应返回空 token 让上层继续轮询，**不要**把它当流结束
- **推理模型**：部分模型（如 DeepSeek-R1）先输出 `reasoning_content` 再输出 `content`，首字延迟会包含推理耗时，可在日志中记录
- **兼容性**：OpenAI 兼容接口（DeepSeek、通义千问、Kimi 等）都可用此模板，只需改 `base_url` 和 `model`

#### manifest.json

```json
{
  "id": "llm_openai",
  "name": "OpenAI LLM 提供商",
  "version": "1.0.0",
  "permissions": ["network", "env_read"],
  "provides": {"llm": ["openai"]},
  "config_fields": [
    {"key": "api_key", "label": "API Key", "type": "password"},
    {"key": "base_url", "label": "接口地址", "type": "text", "default": "https://api.openai.com/v1"},
    {"key": "model", "label": "模型", "type": "text", "default": "gpt-4o"}
  ]
}
```

---

### 三、TTS 插件开发（WebSocket 单向流式）

#### 原理

TTS 是**单向流式**：客户端发一次合成请求，服务端持续推送音频分片。典型协议是火山引擎 V3：

```
客户端 → 服务端：FullClientRequest（合成请求）
服务端 → 客户端：AudioOnlyServer（音频分片）→ FullServerResponse（事件帧）→ 结束事件
```

V3 协议帧格式（火山引擎）：

```
┌──────────────┬──────────────┬────────────┬──────────────┬──────────────┬──────────────┐
│  4 字节头部   │  4 字节 event │ session_id │  4 字节 seq   │  4 字节长度   │   payload    │
└──────────────┴──────────────┴────────────┴──────────────┴──────────────┴──────────────┘
```

#### 工具链

| 工具 | 作用 |
|------|------|
| `tts_start_synthesis(text, config)` | 连接 WebSocket，发送合成请求，返回 `syn_id` |
| `tts_get_audio(syn_id)` | 接收下一段音频（base64），`done` 标记合成完成 |
| `tts_end_synthesis(syn_id)` | 清理会话（保留持久连接） |

#### 完整代码

```python
"""TTS 服务插件示例（火山引擎 V3 协议）"""

from __future__ import annotations

import base64
import io
import json
import struct
import time
import uuid

from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import ws_connect, ws_send, ws_recv, ws_close

TTS_URL = "wss://openspeech.bytedance.com/api/v3/tts/unidirectional/stream"

_sessions: dict[str, dict] = {}

# 持久连接：跨多句合成复用同一 WebSocket，避免每句新建连接触发限流
_conn: dict | None = None
_CONN_IDLE_TIMEOUT = 60.0

# 协议常量
MSG_TYPE_FULL_CLIENT_REQUEST = 0b1
MSG_TYPE_AUDIO_ONLY_SERVER = 0b1011
MSG_TYPE_FULL_SERVER_RESPONSE = 0b1001
MSG_TYPE_ERROR = 0b1111

FLAG_WITH_EVENT = 0b100

EVENT_FINISH_SESSION = 102
EVENT_SESSION_FINISHED = 152
EVENT_SESSION_FAILED = 153
EVENT_TTS_RESPONSE = 352
EVENT_TTS_ENDED = 359
EVENT_CONNECTION_FINISHED = 52


def _build_message(type_: int, flags: int = 0, payload: bytes = b"",
                   event: int | None = None, session_id: str = "") -> bytes:
    """构造 TTS V3 协议帧。"""
    buf = io.BytesIO()
    version = 0x1 << 4
    header_size = 0x1 << 0
    byte0 = (version | header_size).to_bytes(1, "big")
    byte1 = ((type_ << 4) | flags).to_bytes(1, "big")
    serialization = 0x1 << 4  # JSON
    compression = 0x0 << 0
    byte2 = (serialization | compression).to_bytes(1, "big")
    byte3 = (0).to_bytes(1, "big")
    buf.write(byte0 + byte1 + byte2 + byte3)

    if flags & FLAG_WITH_EVENT:
        buf.write(struct.pack(">i", event or 0))
        if event not in (2, 1, 50, 51):  # 这些事件省略 session_id
            sid_bytes = session_id.encode("utf-8")
            buf.write(struct.pack(">I", len(sid_bytes)))
            if sid_bytes:
                buf.write(sid_bytes)

    buf.write(struct.pack(">I", len(payload)))
    if payload:
        buf.write(payload)
    return buf.getvalue()


def _parse_message(data: bytes) -> dict:
    """解析 TTS V3 协议帧。"""
    msg = {"type": None, "flags": 0, "event": None, "session_id": "",
           "sequence": 0, "payload": b"", "error_code": 0}
    if len(data) < 3:
        msg["type"] = MSG_TYPE_ERROR
        return msg

    buf = io.BytesIO(data)
    byte0 = buf.read(1)[0]
    byte1 = buf.read(1)[0]
    msg["type"] = byte1 >> 4
    msg["flags"] = byte1 & 0b00001111

    header_size = byte0 & 0b00001111
    read_size = 3
    if padding := (header_size * 4) - read_size:
        buf.read(padding)

    if msg["flags"] & FLAG_WITH_EVENT:
        ev_bytes = buf.read(4)
        if len(ev_bytes) == 4:
            msg["event"] = struct.unpack(">i", ev_bytes)[0]
        if msg["event"] not in (1, 2, 50, 51):
            sid_len_bytes = buf.read(4)
            if len(sid_len_bytes) == 4:
                sid_len = struct.unpack(">I", sid_len_bytes)[0]
                if sid_len > 0:
                    msg["session_id"] = buf.read(sid_len).decode("utf-8", errors="replace")

    if msg["type"] == MSG_TYPE_ERROR:
        ec_bytes = buf.read(4)
        if len(ec_bytes) == 4:
            msg["error_code"] = struct.unpack(">I", ec_bytes)[0]
    else:
        seq_bytes = buf.read(4)
        if len(seq_bytes) == 4:
            msg["sequence"] = struct.unpack(">i", seq_bytes)[0]

    plen_bytes = buf.read(4)
    if len(plen_bytes) == 4:
        plen = struct.unpack(">I", plen_bytes)[0]
        if plen > 0:
            msg["payload"] = buf.read(plen)
    return msg


def _build_request_payload(config: dict, text: str) -> bytes:
    """构造合成请求 JSON payload。"""
    request = {
        "user": {"uid": str(uuid.uuid4())},
        "req_params": {
            "speaker": config.get("voice_type", "BV001_streaming"),
            "audio_params": {
                "format": "mp3",
                "sample_rate": int(config.get("sample_rate", "24000")),
                "speed_ratio": float(config.get("speed_ratio", "1.0")),
                "volume_ratio": float(config.get("volume_ratio", "1.0")),
                "pitch_ratio": float(config.get("pitch_ratio", "1.0")),
            },
            "text": text,
        },
    }
    return json.dumps(request, ensure_ascii=False).encode("utf-8")


@tool(cache=False)
async def tts_start_synthesis(text: str, config: dict | None = None, tool_manager=None) -> dict:
    """开始 TTS 语音合成，返回 syn_id。

    Args:
        text: 待合成文本
        config: 配置，包含 api_key, resource_id, voice_type 等

    Returns:
        {"syn_id": str, "error": str|null}
    """
    global _conn
    cfg = config or {}
    api_key = cfg.get("api_key", "")
    if not api_key:
        return {"syn_id": "", "error": "api_key 未配置"}

    headers = {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": cfg.get("resource_id", "volc.tts.222222222"),
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }

    now = time.time()
    ws_id = None
    # 复用空闲持久连接；超时则重建
    if _conn is not None:
        if now - _conn["last_used"] > _CONN_IDLE_TIMEOUT:
            try:
                await ws_close(_conn["ws_id"])
            except Exception:
                pass
            _conn = None
        else:
            ws_id = _conn["ws_id"]

    if ws_id is None:
        try:
            ws_id = await ws_connect(TTS_URL, headers)
        except Exception as e:
            return {"syn_id": "", "error": f"WebSocket 连接失败: {e}"}
        _conn = {"ws_id": ws_id, "last_used": now}

    payload = _build_request_payload(cfg, text)
    request_frame = _build_message(type_=MSG_TYPE_FULL_CLIENT_REQUEST, payload=payload)
    try:
        await ws_send(ws_id, request_frame)
    except Exception:
        # 连接可能已被服务端关闭，重建后重试
        try:
            await ws_close(ws_id)
        except Exception:
            pass
        _conn = None
        try:
            ws_id = await ws_connect(TTS_URL, headers)
            _conn = {"ws_id": ws_id, "last_used": now}
            await ws_send(ws_id, request_frame)
        except Exception as e:
            return {"syn_id": "", "error": f"发送请求失败: {e}"}

    syn_id = uuid.uuid4().hex[:8]
    _sessions[syn_id] = {"ws_id": ws_id, "done": False, "buffer": []}
    return {"syn_id": syn_id, "error": None}


@tool(cache=False)
async def tts_get_audio(syn_id: str, tool_manager=None) -> dict:
    """获取下一段音频数据（base64 编码）。"""
    global _conn
    session = _sessions.get(syn_id)
    if not session:
        return {"audio_base64": "", "done": True, "error": "session not found"}

    # 优先从缓冲区取
    if session["buffer"]:
        return {"audio_base64": session["buffer"].pop(0), "done": False, "error": None}
    if session["done"]:
        return {"audio_base64": "", "done": True, "error": None}

    try:
        data = await ws_recv(session["ws_id"], timeout=0.5)
    except Exception as e:
        if _conn and _conn["ws_id"] == session["ws_id"]:
            _conn = None
        return {"audio_base64": "", "done": True, "error": f"接收失败: {e}"}
    if data is None:
        return {"audio_base64": "", "done": False, "error": None}

    msg = _parse_message(data)
    msg_type = msg.get("type")
    msg_event = msg.get("event")
    payload = msg.get("payload", b"")

    if msg_type == MSG_TYPE_ERROR:
        session["done"] = True
        return {"audio_base64": "", "done": True, "error": f"服务端错误: code={msg.get('error_code')}"}

    if msg_type == MSG_TYPE_AUDIO_ONLY_SERVER:
        if payload:
            return {"audio_base64": base64.b64encode(payload).decode("ascii"), "done": False, "error": None}
        return {"audio_base64": "", "done": False, "error": None}

    if msg_type == MSG_TYPE_FULL_SERVER_RESPONSE:
        if msg_event in (EVENT_SESSION_FINISHED, EVENT_TTS_ENDED):
            session["done"] = True
            return {"audio_base64": "", "done": True, "error": None}
        if msg_event == EVENT_SESSION_FAILED:
            session["done"] = True
            return {"audio_base64": "", "done": True, "error": f"合成失败: {payload.decode('utf-8', errors='replace')}"}
        if msg_event == EVENT_CONNECTION_FINISHED:
            session["done"] = True
            if _conn and _conn["ws_id"] == session["ws_id"]:
                _conn = None
            return {"audio_base64": "", "done": True, "error": None}

    return {"audio_base64": "", "done": False, "error": None}


@tool(cache=False)
async def tts_end_synthesis(syn_id: str, tool_manager=None) -> dict:
    """清理 TTS 合成会话（保留持久连接供后续句子复用）。"""
    global _conn
    session = _sessions.pop(syn_id, None)
    if session and _conn and _conn["ws_id"] == session["ws_id"]:
        _conn["last_used"] = time.time()
    return {}
```

#### 关键点

- **持久连接复用**：`_conn` 全局缓存最近一次连接，60 秒内复用，避免每句合成新建连接触发火山限流。`end_synthesis` **不关闭连接**，只刷新最后使用时间
- **事件驱动结束**：TTS 没有"一次性返回全部"的响应，靠事件帧判断结束——`SessionFinished`(152) / `TTSEnded`(359) 表示合成完成，`SessionFailed`(153) 表示失败
- **音频分片**：`AudioOnlyServer`(0b1011) 帧的 payload 就是一段 MP3 音频，base64 编码后返回，上层拼接后播放
- **断线重连**：发送请求失败时，连接可能已被服务端关闭，需关闭旧连接、重建、重发请求

#### manifest.json

```json
{
  "id": "tts_volcengine",
  "name": "火山引擎 TTS 提供商",
  "version": "1.0.0",
  "permissions": ["network"],
  "provides": {"tts": ["volcengine"]},
  "config_fields": [
    {"key": "api_key", "label": "API Key", "type": "password"},
    {"key": "resource_id", "label": "Resource ID", "type": "text"},
    {"key": "voice_type", "label": "音色", "type": "text", "default": "BV001_streaming"},
    {"key": "speed_ratio", "label": "语速", "type": "text", "default": "1.0"},
    {"key": "volume_ratio", "label": "音量", "type": "text", "default": "1.0"},
    {"key": "pitch_ratio", "label": "音调", "type": "text", "default": "1.0"}
  ]
}
```

---

### 四、调试与排错

#### 日志

插件中可用 `logging.getLogger("plugin.<插件id>")` 打日志，管理员可在 Web 界面查看插件日志：

```python
import logging
logger = logging.getLogger("plugin.asr_volcengine")

logger.info(f"收到 {len(data)} bytes, 前16字节: {data[:16].hex()}")
logger.info(f"解析结果: type={msg['type']}, event={msg['event']}")
```

#### 常见问题

| 现象 | 原因 | 排查 |
|------|------|------|
| 连接失败 | API Key 错误 / 网络不通 | 检查 `config` 里的 `api_key`，确认服务地址可达 |
| 识别/合成无结果 | 协议帧拼错 | 打印收发帧的 hex 前 16 字节，对照协议文档 |
| 第二次调用返回旧结果 | 忘了 `cache=False` | 所有语音服务工具必须 `@tool(cache=False)` |
| 报 `cannot call recv while another coroutine is running` | 并发 recv | 用 `asyncio.Lock()` 保护 `ws_recv` |
| TTS 每句都新建连接被限流 | 未复用连接 | 实现持久连接缓存（见上文 `_conn`） |
| 会话 ID 无效 | 会话被清理 | 确认 `start` 返回的 ID 与后续调用一致，超时后会话可能已过期 |

#### 参考实现

| 插件 | 协议 | 文件 |
|------|------|------|
| 火山引擎 ASR | SAUC | `data/plugins/installed/asr_volcengine/plugin.py` |
| OpenAI LLM | SSE | `data/plugins/installed/llm_openai/plugin.py` |
| 火山引擎 TTS | V3 | `data/plugins/installed/tts_volcengine/plugin.py` |

---

## 发布与市场

### 开发者模式

登录 Web 管理界面 → **插件市场 → 开发者** tab → 点击 **开启开发者模式**，系统自动生成 API Key。开发者复用现有用户账号，无需单独注册。

### 两种上传方式

| 方式 | 端点 | 可见性 | 版本要求 |
|------|------|--------|----------|
| 上架商店 | `POST /api/v1/marketplace/plugins/upload` | 所有用户可搜索安装 | 每次上传版本号必须递增 |
| 本地测试 | `POST /api/v1/plugins/install` | 仅本服务器可用 | 可覆盖同版本 |

### 版本管理

上架商店时版本号必须严格递增（同版本号重复上传会被拒绝）。修改 `manifest.json` 中的 `version` 后重新打包上传即可。市场保留完整版本历史。

### 插件更新流程

开发者上传新版本后，用户可通过 Web 界面更新已安装的插件：

1. **检查更新**：插件市场 → 已安装 tab → 点击「检查更新」按钮，系统向市场 API 查询每个已安装插件的最新版本
2. **显示徽章**：有新版本的插件卡片上显示「新版本 vX.Y.Z」金色呼吸徽章
3. **执行更新**：点击「更新」按钮，系统从市场下载最新版 zip → 卸载旧版 → 安装新版 → 热加载
4. **配置保留**：设备级插件配置（高德 Key、音乐服务地址等）存在数据库 `devices.plugin_configs` 字段中，更新插件只替换代码文件，配置不受影响

```
用户点击「更新」
    ↓
POST /api/v1/plugins/{name}/update
    ↓
PluginManager.update_plugin(name)
    ├─ 从市场下载最新 zip（GET /api/v1/marketplace/plugins/{slug}/download）
    ├─ 卸载旧版（_do_unload + 删除旧目录）
    ├─ 解压新版到 data/plugins/installed/{plugin_id}/
    └─ 重新加载插件（plugin_loader._load_plugin）
    ↓
设备级 plugin_configs 不受影响（存在数据库，不在插件目录）
```

### API 参考

**开发者端点**（需 JWT 认证）：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/marketplace/developer/enable` | POST | 开启开发者模式，生成 API Key |
| `/api/v1/marketplace/developer/info` | GET | 查询开发者状态 |
| `/api/v1/marketplace/developer/bio` | PUT | 更新开发者简介 |

**市场端点**（浏览无需认证，上传需 JWT + 开发者模式）：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/marketplace/plugins` | GET | 插件列表（分页 + 搜索 + 分类 + 排序） |
| `/api/v1/marketplace/plugins/{slug}` | GET | 插件详情 |
| `/api/v1/marketplace/plugins/{slug}/versions` | GET | 版本历史 |
| `/api/v1/marketplace/plugins/{slug}/download` | GET | 下载 zip |
| `/api/v1/marketplace/plugins/{slug}/reviews` | GET | 查看评论 |
| `/api/v1/marketplace/plugins/{slug}/reviews` | POST | 提交评论（一人一评，1-5 分） |
| `/api/v1/marketplace/plugins/upload` | POST | 上传 zip 到市场 |
| `/api/v1/marketplace/categories` | GET | 分类列表 |

**本地插件管理端点**（`/api/v1/plugins` 需登录即可，其余需管理员认证）：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/plugins` | GET | 所有已加载插件列表（任意登录用户） |
| `/api/v1/plugins/installed` | GET | 已安装插件（含版本/来源/工具） |
| `/api/v1/plugins/install` | POST | 从 zip 安装（multipart 上传） |
| `/api/v1/plugins/{name}` | DELETE | 卸载插件（内置不可卸载） |
| `/api/v1/plugins/{name}/update` | POST | 从市场更新到最新版 |
| `/api/v1/plugins/updates` | GET | 检查所有插件更新 |
| `/api/v1/plugins/reload` | POST | 热加载全部插件 |

**设备级插件端点**（需设备归属校验）：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/devices/{device_id}/plugins` | GET | 查询设备启用的插件白名单 |
| `/api/v1/devices/{device_id}/plugins` | PUT | 设置插件白名单（空=全部启用） |
| `/api/v1/devices/{device_id}/plugins/{name}/config` | PUT | 保存插件配置（白名单校验） |

::: tip 插件白名单语义
设备有一个 `enabled_plugins` 白名单：为 `null` 或空列表表示**全部启用**；非空列表表示**只启用列表中的插件**。未安装任何插件的设备，所有插件工具不可用。无屏设备自动隐藏 `requires` 含 `display` 的插件。
:::

## 最佳实践

| 建议 | 说明 |
|---|---|
| 文档字符串写清楚 | LLM 靠描述判断调用时机和参数含义，写得越具体调用越准 |
| 含副作用设 `cache=False` | 屏幕显示/设备指令/音乐播放类工具必须禁用缓存，否则第二次调用不执行 |
| 网络调用设超时 | `httpx.AsyncClient(timeout=8)`，避免长时间阻塞 |
| 失败返回中文提示 | 不要抛异常，返回可播报的文本让 TTS 念给用户 |
| 无状态设计 | 每次调用独立，不依赖模块级可变状态 |
| 版本号递增 | 上架市场的插件每次上传版本号必须大于已有版本 |
| 配置项声明 | 需要 API Key 等用户输入时用 `config_fields` 声明，不要硬编码 |

## 参考文件

| 文件 | 说明 |
|------|------|
| `src/use_cases/_plugin_helpers.py` | 插件公共工具库（Plugin SDK），详见[插件公共工具库（Plugin SDK）](./plugin-sdk.md) |
| `src/use_cases/tools_system.py` | 工具系统：`@tool` 装饰器、`StopPipeline`、`PerUserToolManager` |
| `src/infrastructure/plugin_loader.py` | 插件加载器：扫描目录、进程内加载内置插件、子进程沙箱加载已安装插件、热加载 |
| `src/infrastructure/plugin_manager.py` | 插件包管理器：安装、卸载、更新、版本检查 |
| `src/infrastructure/plugin_manifest.py` | manifest.json 模型：字段校验、兼容性检查、签名与文件哈希校验 |
| `src/infrastructure/plugin_host/` | 插件沙箱运行时：子进程 runner、supervisor、SDK 权限裁决器、SDK 桩 |
| `src/infrastructure/plugin_security.py` | 插件权限上下文、环境变量白名单、AST 静态审计 |
| `src/infrastructure/routes/marketplace.py` | 云市场路由：上传、搜索、评论、下载 |
| `src/infrastructure/routes/plugins.py` | 本地插件路由：热加载、设备级插件控制、安装/卸载 |
| `src/plugins/weather/plugin.py` | 天气插件示例（含 show_card 卡片 + config_fields 配置） |
| `src/plugins/system_basic/plugin.py` | 系统基础插件示例（时间查询、亮度控制） |
| `esp-ai-idf-client/main/commands/` | 设备端指令实现（set_volume / show_card 等） |
