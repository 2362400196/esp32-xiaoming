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
            "data": 'local lv=require("lvgl")\nlocal t=lv.label(lv.scr_act())\nlv.label_set_text(t,"你好 '..name..'")\nlv.set_style_text_font(t,"puhui")',
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

在工具函数中通过 `tool_manager.get_plugin_config()` 读取：

```python
@tool(cache=False)
async def get_weather(city: str = "", tool_manager=None) -> str:
    """查询天气"""
    amap_key = tool_manager.get_plugin_config("weather", "amap_key", "")
    if not amap_key:
        return "天气服务未配置，请在插件设置中填写高德 API Key"
    # ... 使用 amap_key 查询天气
```

配置特性：

- **按设备存储**：每台设备独立配置，互不影响
- **白名单校验**：只接受声明过的字段，未知字段被拒绝
- **即时生效**：保存后热重载在线设备，无需重启
- **保存 API**：`PUT /api/v1/devices/{device_id}/plugins/{plugin_name}/config`

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
