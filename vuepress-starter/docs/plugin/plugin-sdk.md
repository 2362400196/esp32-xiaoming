# 插件公共工具库（Plugin SDK）

插件开发中最容易踩坑的是**重复造轮子**：每个插件都要手写设备指令下发、错误处理、配置读取、HTTP 请求……写法还不一致，导致同样的逻辑散落在十几个插件里。

本系统将所有高频、易错的操作统一封装到 `src/use_cases/_plugin_helpers.py`（即**插件 SDK**）。插件里只做两件事：

1. `from src.use_cases._plugin_helpers import xxx` 引入所需能力
2. 专注于自己的业务逻辑

::: tip 为什么文件以下划线 `_` 开头？
`_plugin_helpers.py` 位于 `use_cases` 目录，`auto_discover` 扫描该目录时**会跳过下划线前缀的模块**，因此它不会被误当作技能/工具模块加载，可以安全 import。
:::

## 能力总览

| 分组 | 函数 | 用途 |
|------|------|------|
| 设备标识 | `get_device_key()` / `resolve_device_key()` | 拿到当前设备的 `bound_xxx` 标识，查询内部表必备 |
| 指令下发 | `send_instruct()` / `send_device_command()` | 向设备发一条 `instruct` 指令 |
| **音乐播放** | `play_music_url()` | 给一个链接即可播放音乐，支持歌词和元数据 |
| 指令回执 | `request_device_result()` / `send_device_command_ack()` | 下发指令并**等待设备回复结果**（Lua 返回、状态查询、指令 ack） |
| 配置读取 | `get_plugin_config_or_env()` | 插件配置 → 环境变量 → 默认值，三级回退 |
| HTTP 请求 | `http_request()` / `http_get_json()` | 统一超时与错误处理的外部 API 调用 |
| LTM 记忆 | `get_ltm_service()` / `get_default_ltm_service()` | 访问长期记忆服务（注入优先） |
| 仓储工厂 | `get_diary_repository()` / `get_device_repository()` | 延迟加载数据库仓储，避免插件启动即依赖 DB |
| 技能目录 | `skill_catalog_text()` | 渲染当前设备可用技能目录文本 |
| **LLM 对话** | `llm_chat()` / `llm_generate()` | 调用大模型进行对话或文本生成 |
| **TTS 合成** | `tts_synthesize()` | 文本转语音，返回 MP3 音频数据 |
| **设备状态** | `device_is_online()` / `device_get_info()` | 查询设备在线状态与基本信息 |
| **设备 IO 控制** | `gpio_mode()` / `gpio_write()` / `gpio_read()` / `pwm_write()` / `adc_read()` / `servo_write()` | 控制设备 GPIO、PWM、ADC、舵机 |
| **文件持久化** | `plugin_data_read()` / `plugin_data_write()` / `plugin_data_list()` / `plugin_data_delete()` | 读写插件专属数据目录 |
| **键值存储** | `kv_get()` / `kv_set()` / `kv_delete()` / `kv_list()` | 插件专属的持久化键值存储 |
| **用户画像** | `get_user_profile_summary()` | 获取当前设备用户的画像摘要 |
| **工具函数** | `generate_uuid()` / `current_timestamp()` / `json_dumps()` / `json_loads()` | 通用零依赖工具函数 |

---

## 一、设备标识解析

服务端内部表（`diaries`、`short_term_memories` 等）以 `bound_xxx` 格式的 **device_key** 为主键，而 `tool_manager.user_config` 里可能是 `key`（bound_xxx）也可能是裸 MAC 的 `device_id`。直接拿 `device_id` 去查表必然查不到数据。

### `get_device_key(tool_manager) -> str`

取 `tool_manager.user_config.key`（bound_xxx 格式）；未连接/未配置返回 `""`。

```python
from src.use_cases._plugin_helpers import get_device_key

key = get_device_key(tool_manager)
if not key:
    return "设备未连接，无法操作"
```

### `resolve_device_key(device_key, tool_manager) -> str`

**自动填充**：传入空值时依次尝试 `user_config.key` → `user_config.device_id`（MAC）经 devices 表映射为 `bound_xxx`。所有查询内部表的工具都应经过它：

```python
from src.use_cases._plugin_helpers import resolve_device_key

# device_key 参数可能是空的，交给函数自动解析
device_key = resolve_device_key(device_key_arg, tool_manager)
rows = repository.query_by_device(device_key)
```

::: warning 两处同名函数
`src/infrastructure/device_api.py` 中也有一个 `resolve_device_id(mac)`，作用是把 MAC 映射为 device_key（面向基础设施层）。插件层请统一使用 SDK 的 `resolve_device_key`，不要混淆。
:::

---

## 二、设备指令下发

设备指令统一为 WebSocket `instruct` 消息。SDK 提供两档封装，按是否需要回执选择。

### `send_instruct(channel, command_id, data="")`

最底层封装，**不检查**连接状态、**不捕获**异常，适合已经确认在线的场景（如播放音乐时连续下发多条指令）：

```python
from src.use_cases._plugin_helpers import send_instruct

await send_instruct(ch, "play_music", audio_url)
await send_instruct(ch, "music_meta", json.dumps({...}, ensure_ascii=False))
```

### `send_device_command(tool_manager, command_id, data="") -> str | None`

推荐在大多数工具中使用。内置两级防护：

- 设备未连接 → 返回 `"设备未连接"`
- 未声明 `device` 权限 → 返回 `"设备指令权限未声明"`
- 发送抛异常 → 返回 `"发送失败: xxx"`
- 发送成功 → 返回 `None`

```python
from src.use_cases._plugin_helpers import send_device_command

@tool()
async def set_brightness(level: int, tool_manager=None) -> str:
    """设置屏幕亮度。参数 level 为 0-100 的整数。"""
    level = max(0, min(100, level))
    err = await send_device_command(tool_manager, "set_brightness", str(level))
    if err:
        return f"亮度设置指令已生成: {level}%（{err}）"
    return f"已将屏幕亮度设置为 {level}%"
```

返回值语义：**`None` = 成功，字符串 = 失败原因**。用它替代手写 `try/except`，工具代码可以精简一半。

| 函数 | 检查连接 | 捕获异常 | 等待回执 | 适用场景 |
|------|:--------:|:--------:|:--------:|----------|
| `send_instruct` | ✗ | ✗ | ✗ | 已确认在线、连续批量下发 |
| `send_device_command` | ✓ | ✓ | ✗ | 普通一次性指令（音量/亮度/清屏） |
| `request_device_result` | ✓ | ✓ | ✓ | 需要设备返回值（Lua 执行、状态查询） |

---

## 三、音乐播放 SDK

### `play_music_url(url, title="", artist="", duration=0, device_key="", lyric_url="", lyrics_offset=0) -> str`

给一个音频链接即可让设备播放音乐。支持同时发送歌曲信息和歌词，适合从其他插件（如闹钟）调用。

**基础用法（只给链接）：**

```python
from src.use_cases._plugin_helpers import play_music_url

result = await play_music_url("http://192.168.1.100:2233/music/xxx.mp3")
if result == "ok":
    print("播放成功")
else:
    print(f"播放失败: {result}")
```

**完整用法（带歌曲信息和歌词）：**

```python
await play_music_url(
    url="http://192.168.1.100:2233/music/xxx.mp3",
    title="晴天",
    artist="周杰伦",
    duration=270,
    lyric_url="http://192.168.1.100:2233/lyrics/xxx.lrc",
    lyrics_offset=0,
)
```

**指定设备：**

```python
# 不传 device_key 会自动选择第一个在线设备
await play_music_url("http://...", device_key="bound_xxx")
```

**参数说明：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `url` | str | ✓ | 音频文件 URL，设备可直接 HTTP 下载播放 |
| `title` | str | | 歌曲标题，显示在设备屏幕上 |
| `artist` | str | | 歌手名称 |
| `duration` | int | | 歌曲时长（秒） |
| `device_key` | str | | 设备标识，不传自动选第一个在线设备 |
| `lyric_url` | str | | LRC 歌词文件 URL，会自动下载并逐行推送 |
| `lyrics_offset` | int | | 歌词时间偏移（毫秒） |

**返回值：** 成功返回 `"ok"`，失败返回错误描述字符串。

---

## 四、指令回执：等待设备回复

普通指令"发出即成功"，但有些指令需要设备**执行后回传结果**：

- `execute_lua`：设备执行 Lua 后把返回值发回来（如 GPIO 读取、传感器数值）
- `get_volume` / `get_brightness`：设备上报当前状态

### `request_device_result(tool_manager, command_id, future_attr, timeout=8.0, data="", if_busy=None)`

下发指令后挂起，等待设备回复并解析。返回统一三元组 `(result, status, detail)`：

| status | 含义 | result | detail |
|--------|------|--------|--------|
| `"ok"` | 成功 | 设备回复字符串 | `""` |
| `"offline"` | 设备未连接 | `None` | `"设备未连接"` |
| `"timeout"` | 超时 | `None` | `"设备未在 X 秒内响应"` |
| `"error"` | 发送异常 | `None` | 含异常信息 |
| `"busy"` | future 被占用 | `None` | `if_busy` 传入的文案 |

```python
from src.use_cases._plugin_helpers import request_device_result

async def _query_device_state(tool_manager, command_id: str) -> str:
    result, status, detail = await request_device_result(
        tool_manager, command_id, "_pending_device_state_future", timeout=5.0,
    )
    if status != "ok":
        return detail
    return result.strip()

@tool()
async def get_volume(tool_manager=None) -> str:
    """获取设备当前的音量（百分比 0-100）。"""
    result = await _query_device_state(tool_manager, "get_volume")
    if result.startswith("volume="):
        return f"当前音量是 {result[len('volume='):]}%"
    return result
```

### `future_attr` 是什么？

设备回复到达时，框架会把结果写入 `tool_manager.<future_attr>` 指向的 future。因此：

- 同一时间**同一类型的查询只能有一个**在等待——第二个调用会覆盖第一个的 future，导致第一个永远等不到结果
- 不同指令类型要用**不同的 future_attr**（如 Lua 用 `_pending_lua_future`、状态查询用 `_pending_device_state_future`），互不干扰
- 用 `if_busy="文案"` 在 future 被占用时立即返回 `busy`，避免无谓等待

```python
# 若 execute_lua 正在等待回复，立即返回而不是覆盖 future
result, status, detail = await request_device_result(
    tool_manager, "get_brightness", "_pending_device_state_future",
    timeout=3.0, if_busy="上一个查询尚未完成，请稍后再试",
)
if status == "busy":
    return detail
```

### `send_device_command_ack(tool_manager, command_id, data="", timeout=8.0)`

下发指令并等待设备返回 **ack 确认回执**（`instruct_ack` 消息）。返回三元组 `(result, status, detail)`，status 取值集合为 `{ok, offline, timeout, error}`。适用于设备侧"收到即回执"的指令确认场景，无需像 `request_device_result` 那样手动指定 `future_attr`。

---

## 四、插件配置存储：KV 存储优先

插件需要保存用户配置（如 API Key）时，**不要写入主数据库**，应使用插件专属的 KV 存储。

::: tip 设计原则
插件配置走 KV 存储，不经过主数据库 `device_config` 表。KV 存储是 JSON 文件，路径自动隔离（`data/plugins/kv/<插件id>.json`），插件之间互不可见。
:::

### 保存配置

```python
from src.use_cases.sdk.storage import kv_set, kv_get

# 保存（写入 data/plugins/kv/weather.json）
kv_set("amap_key", "用户的key", tool_manager=tool_manager)

# 读取
amap_key = kv_get("amap_key", default="", tool_manager=tool_manager)
```

### 配合前端

前端通过通用工具调用接口来读写配置：

```python
@tool(cache=False)
def save_config(amap_key: str = "", tool_manager=None) -> str:
    """保存配置到插件 KV 存储。不传 amap_key 则返回当前配置。"""
    if not amap_key:
        current = kv_get("amap_key", default="", tool_manager=tool_manager)
        return json_dumps({"ok": True, "amap_key": current})
    kv_set("amap_key", amap_key, tool_manager=tool_manager)
    return json_dumps({"ok": True, "message": "配置已保存"})
```

前端调用：

```javascript
// 保存
await api('/plugins/weather/tool/save_config', {
  method: 'POST',
  body: { args: { amap_key: 'xxx' }, device_id }
})

// 读取（不传参数）
const res = await api('/plugins/weather/tool/save_config', {
  method: 'POST',
  body: { args: {}, device_id }
})
// res.data.amap_key 即为当前配置
```

### 兼容旧环境变量

如果还想支持通过环境变量配置（如 Docker 部署），可以在 `kv_get` 拿不到时回退到环境变量：

```python
import os

amap_key = kv_get("amap_key", default="", tool_manager=tool_manager)
if not amap_key:
    amap_key = os.environ.get("WEATHER_AMAP_KEY", "")
```

::: warning 环境变量有白名单限制
环境变量读取受沙箱限制，只允许读取：
- 以 `<插件id>_` 开头（如 `WEATHER_AMAP_KEY`）
- 或 `PLUGIN_` 开头
- 或通过 `PLUGIN_ENV_ALLOWLIST` 显式放行
:::

---

## 五、HTTP 请求：统一超时与错误处理

插件调用外部 API 最常见的两个坑：**忘记设超时**导致会话卡死；**异常处理不统一**导致错误文案混乱。SDK 统一返回 `(result, error)` 元组：

### `http_request(method, url, *, params=None, headers=None, content=None, timeout=10.0)`

```python
from src.use_cases._plugin_helpers import http_request

resp, err = await http_request(
    "GET", api_url,
    params={"key": key, "city": city},
    timeout=8.0,
)
if err:
    return f"请求失败: {err}"
```

### `http_get_json(url, params=None, headers=None, timeout=8.0)`

GET 后自动解析 JSON，解析失败也算错误返回：

```python
from src.use_cases._plugin_helpers import http_get_json

data, err = await http_get_json(
    "https://restapi.amap.com/v3/weather/weatherInfo",
    params={"key": key, "city": city},
)
if err:
    return "天气查询失败（网络错误）"
if data.get("status") != "1":
    return "查询天气失败"
```

::: tip 约定
- 成功 → `(data, None)`；失败 → `(None, error)`。永远先判断 `error` 再使用 `data`
- 返回的可播报错误文案请用中文，TTS 会念给用户听
- 拿到的响应对象可以直接用 `.json()` / `.text`
:::

---

## 六、LTM 长期记忆服务

需要读写长期记忆（记忆系统）的插件，通过 SDK 获取服务实例，不必自行实例化仓储：

```python
from src.use_cases._plugin_helpers import get_ltm_service, get_default_ltm_service

# 优先使用 tool_manager 注入的实例（框架已按设备上下文配置好）
service = get_ltm_service(tool_manager)
# 或使用默认单例（模块级懒加载，无注入时使用）
service = get_default_ltm_service()
```

| 函数 | 行为 |
|------|------|
| `get_ltm_service(tool_manager)` | 优先返回 `tool_manager.ltm_service`，否则回退默认单例 |
| `get_default_ltm_service()` | 创建并缓存默认 LTM 服务（单例，重复调用返回同一实例） |

---

## 七、仓储工厂：延迟加载数据库依赖

插件若在模块顶层 import 数据库仓储，插件加载时就会触发 DB 初始化——即使该插件根本不用 DB。SDK 提供工厂函数，**调用时才延迟导入**：

```python
from src.use_cases._plugin_helpers import get_diary_repository, get_device_repository

# 在工具函数内部调用，而非模块顶层
repo = get_diary_repository()
entries = repo.get_recent(device_key, limit=5)
```

| 工厂 | 返回仓储 | 用途 |
|------|----------|------|
| `get_diary_repository()` | `DiaryRepository` | 日记读写（`get_recent` / `add_entry` 等） |
| `get_device_repository()` | `DeviceRepository` | 设备信息查询 |

---

## 八、技能目录渲染

`list_skills` 类工具（如 `skill_tools.py`）需要把设备可用的技能列给 LLM 看。手写渲染逻辑容易漏掉**禁用技能过滤**和**设备专属标记**，SDK 已统一处理：

```python
from src.use_cases._plugin_helpers import skill_catalog_text

@tool()
def list_skills(tool_manager=None) -> str:
    """列出设备上所有可用的技能(Skill)及其描述。"""
    return skill_catalog_text(tool_manager)
```

内部行为：

- 通过 `get_device_key(tool_manager)` 定位当前设备
- 自动过滤 `user_config.disabled_skills` 中禁用的技能
- 设备专属技能（绑定 device_id）会加 `[设备专属]` 标记
- 无可用技能时返回 `"当前没有可用的技能。"`

---

## 九、LLM 对话（权限 `llm`）

插件可以调用大模型进行文本生成、智能分析、主动对话等操作。SDK 提供两种调用方式：

### `llm_chat(messages, system_prompt=None, tool_manager=None) -> str`

发送消息列表给 LLM，返回完整回复文本。`messages` 格式与 OpenAI API 一致。

```python
from src.use_cases._plugin_helpers import llm_chat

@tool()
async def analyze_sentiment(text: str, tool_manager=None) -> str:
    """分析用户输入的情感倾向。"""
    messages = [
        {"role": "system", "content": "你是一个情感分析助手。请用一句话分析用户的情感倾向（积极/消极/中性）。"},
        {"role": "user", "content": text},
    ]
    result = await llm_chat(messages, tool_manager=tool_manager)
    return f"情感分析结果：{result}"
```

### `llm_generate(prompt, system_prompt=None, tool_manager=None) -> str`

更简洁的单轮文本生成，直接传入提示文本即可：

```python
from src.use_cases._plugin_helpers import llm_generate

@tool()
async def summarize(text: str, tool_manager=None) -> str:
    """总结一段文本的核心内容。"""
    summary = await llm_generate(
        f"请用一句话总结以下内容：{text}",
        tool_manager=tool_manager,
    )
    return f"总结：{summary}"
```

::: tip 适用场景
- **文本分析**：情感分析、意图分类、关键词提取
- **智能回复**：生成个性化回复文案
- **内容生成**：写诗、写故事、生成报告
- **数据提取**：从非结构化文本中提取结构化信息
:::

---

## 十、TTS 语音合成（权限 `tts`）

将文本转换为 MP3 格式的音频数据，插件可以获取音频后通过设备指令发送给设备播放。

### `tts_synthesize(text, voice=None, tool_manager=None) -> bytes`

```python
from src.use_cases._plugin_helpers import tts_synthesize, send_device_command

@tool()
async def speak_text(text: str, tool_manager=None) -> str:
    """让设备用语音播报一段文本。"""
    audio_bytes = await tts_synthesize(text, tool_manager=tool_manager)
    if not audio_bytes:
        return "语音合成失败"
    # 发送给设备播放（具体指令取决于设备实现）
    err = await send_device_command(tool_manager, "play_audio", audio_bytes)
    if err:
        return f"播报失败: {err}"
    return "正在播报"
```

`voice` 参数可选，不传时使用全局配置的音色。

---

## 十一、设备状态查询（权限 `device`）

查询设备的在线状态和基本信息，无需下发指令即可获取设备信息。

### `device_is_online(device_key="", tool_manager=None) -> bool`

检查设备是否在线。不传 `device_key` 时自动使用当前调用上下文绑定的设备：

```python
from src.use_cases._plugin_helpers import device_is_online

@tool()
async def check_device(tool_manager=None) -> str:
    """检查当前设备是否在线。"""
    if device_is_online(tool_manager=tool_manager):
        return "设备在线"
    return "设备离线"
```

### `device_get_info(device_key="", tool_manager=None) -> dict`

获取设备详细信息，包括固件版本、MAC 地址、注册时间、OTA 状态等：

```python
from src.use_cases._plugin_helpers import device_get_info

@tool()
async def get_device_status(tool_manager=None) -> str:
    """获取设备当前状态信息。"""
    info = await device_get_info(tool_manager=tool_manager)
    if not info:
        return "设备不在线或未注册"
    fw = info.get("firmware_version", "未知")
    mac = info.get("mac", "未知")
    online = "在线" if device_is_online(tool_manager=tool_manager) else "离线"
    return f"设备 {mac}，固件版本 {fw}，状态：{online}"
```

返回的 dict 包含字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `device_key` | str | 设备标识 |
| `mac` | str | MAC 地址 |
| `firmware_version` | str | 固件版本 |
| `register_time` | float | 注册时间戳 |
| `ota_updating` | bool | 是否正在 OTA 升级 |
| `ota_progress` | float | OTA 升级进度（0~100） |

---

## 十二、插件数据持久化（权限 `file_read` / `file_write`）

每个插件拥有**独立的文件系统目录**，可以读写自己的数据文件。路径自动隔离，插件之间互不可见，且带有**路径穿越防护**。

### `plugin_data_read(path, tool_manager=None) -> str | None`

读取插件数据目录下的文件，文件不存在返回 `None`：

```python
from src.use_cases._plugin_helpers import plugin_data_read

# 读取配置文件
config_text = plugin_data_read("config.json", tool_manager=tool_manager)
if config_text is None:
    config_text = "{}"
```

### `plugin_data_write(path, content, tool_manager=None) -> None`

写入文件到插件数据目录，自动创建中间目录：

```python
from src.use_cases._plugin_helpers import plugin_data_write

# 保存缓存数据
plugin_data_write("cache/last_result.json", json.dumps(result), tool_manager=tool_manager)
```

### `plugin_data_list(path="", tool_manager=None) -> list`

列出目录下的文件和子目录，返回每项的 `name` / `is_dir` / `size` / `mtime`：

```python
from src.use_cases._plugin_helpers import plugin_data_list

files = plugin_data_list(tool_manager=tool_manager)
for f in files:
    if not f["is_dir"]:
        print(f"  {f['name']} ({f['size']} bytes)")
```

### `plugin_data_delete(path, tool_manager=None) -> bool`

删除文件或目录（含子目录递归删除），返回是否删除成功：

```python
from src.use_cases._plugin_helpers import plugin_data_delete

if plugin_data_delete("old_cache.json", tool_manager=tool_manager):
    print("已删除旧缓存")
```

数据文件存储在 `data/plugins/data/<插件id>/` 目录下，重启服务后仍然保留。

---

## 十三、键值存储（权限 `kv`）

插件专属的**持久化键值存储**，适合保存配置、状态、缓存等简单数据。无需处理文件路径，开箱即用。

### `kv_get(key, default=None, tool_manager=None) -> Any`

读取键值，键不存在时返回 `default`：

```python
from src.use_cases._plugin_helpers import kv_get, kv_set

# 读取上次运行的时间戳
last_run = kv_get("last_run_time", default=0, tool_manager=tool_manager)
```

### `kv_set(key, value, tool_manager=None) -> None`

写入键值，`value` 必须是 JSON 可序列化的类型：

```python
# 保存用户设置
kv_set("user_name", "小明", tool_manager=tool_manager)
kv_set("volume", 80, tool_manager=tool_manager)
kv_set("tags", ["音乐", "新闻", "天气"], tool_manager=tool_manager)
```

### `kv_delete(key, tool_manager=None) -> bool`

删除键值，返回是否删除成功：

```python
if kv_delete("temp_data", tool_manager=tool_manager):
    print("临时数据已清除")
```

### `kv_list(prefix="", tool_manager=None) -> list`

列出所有键值（可按前缀过滤），每项包含 `key` 和 `value`：

```python
all_data = kv_list(tool_manager=tool_manager)
# 只列出 cache_ 开头的键
cache_data = kv_list(prefix="cache_", tool_manager=tool_manager)
```

数据存储在 `data/plugins/kv/<插件id>.json` 文件中，重启服务后保留。

---

## 十四、用户画像（权限 `db`）

获取当前设备用户的画像摘要，用于了解用户偏好、姓名、兴趣等信息，实现个性化服务。

### `get_user_profile_summary(device_key="", tool_manager=None) -> str`

```python
from src.use_cases._plugin_helpers import get_user_profile_summary

@tool()
async def greet_user(tool_manager=None) -> str:
    """个性化问候用户。"""
    profile = await get_user_profile_summary(tool_manager=tool_manager)
    if profile == "暂无用户信息":
        return "你好！我是你的智能助手。"
    return f"根据你的信息，{profile}，有什么我可以帮你的吗？"
```

返回的摘要文本包含：名字、职业、家人、喜欢/不喜欢的事物、正在学习的内容、最近关心的事、最近情绪等。

---

## 十五、通用工具函数（无需权限）

纯本地执行的工具函数，不涉及 RPC 通信，零开销。

### `generate_uuid() -> str`

生成 UUID v4 字符串：

```python
from src.use_cases._plugin_helpers import generate_uuid

request_id = generate_uuid()
```

### `current_timestamp() -> float`

获取当前 Unix 时间戳（秒）：

```python
from src.use_cases._plugin_helpers import current_timestamp

now = current_timestamp()
```

### `json_dumps(obj, indent=None) -> str`

JSON 序列化（支持中文，自动 `ensure_ascii=False`）：

```python
from src.use_cases._plugin_helpers import json_dumps

text = json_dumps({"name": "小明", "age": 8}, indent=2)
```

### `json_loads(s) -> Any`

JSON 反序列化：

```python
from src.use_cases._plugin_helpers import json_loads

data = json_loads('{"name": "小明"}')
```

---

## 十一、设备 IO 控制：控制 GPIO、PWM、舵机

插件可以直接通过 SDK 控制 ESP32 设备的硬件引脚，无需编写 Lua 代码。

| 函数 | 用途 | 读写 |
|------|------|------|
| `gpio_mode(pin, mode)` | 配置引脚模式（output/input/input_pullup） | 写 |
| `gpio_write(pin, value)` | 写入数字信号（0 或 1） | 写 |
| `gpio_read(pin)` | 读取数字信号（返回 0 或 1） | 读 |
| `pwm_write(pin, duty, freq)` | PWM 输出，duty 0-1023，freq 默认 5000Hz | 写 |
| `adc_read(pin)` | 读取模拟值（GPIO1-10，返回 0-4095） | 读 |
| `servo_write(pin, angle)` | 控制舵机角度（0-180 度） | 写 |

### 写操作：GPIO 输出 / PWM / 舵机

写操作通过 `hardware-fns` 消息直接发送到设备，无需等待返回：

```python
from src.use_cases._plugin_helpers import gpio_mode, gpio_write, pwm_write, servo_write

@tool()
async def turn_on_led(tool_manager=None) -> str:
    """打开 LED 灯（GPIO2）"""
    err = await gpio_mode(2, "output", tool_manager=tool_manager)
    if err != "ok":
        return err
    err = await gpio_write(2, 1, tool_manager=tool_manager)
    return "LED 已打开" if err == "ok" else err

@tool()
async def set_motor_speed(speed: int, tool_manager=None) -> str:
    """设置电机转速（PWM 输出）。speed: 0-1023"""
    return await pwm_write(4, speed, tool_manager=tool_manager)

@tool()
async def rotate_servo(angle: int, tool_manager=None) -> str:
    """控制舵机旋转到指定角度。angle: 0-180"""
    return await servo_write(5, angle, tool_manager=tool_manager)
```

### 读操作：数字读取 / 模拟读取

读操作通过 `execute_lua` 指令在设备端执行 Lua 代码并返回结果：

```python
from src.use_cases._plugin_helpers import gpio_read, adc_read

@tool()
async def check_sensor(tool_manager=None) -> str:
    """读取传感器状态"""
    val = await gpio_read(4, tool_manager=tool_manager)
    if val == -1:
        return "读取失败"
    return f"传感器状态: {'高电平' if val else '低电平'}"

@tool()
async def read_light_sensor(tool_manager=None) -> str:
    """读取光线传感器（ADC，GPIO1）"""
    val = await adc_read(1, tool_manager=tool_manager)
    if val == -1:
        return "读取失败"
    return f"光线强度: {val}/4095"
```

### 注意事项

- **GPIO48 已被板载情绪灯占用**，不能用作普通 GPIO
- **ADC 仅限 GPIO1-10**（ESP32-S3 ADC1 通道）
- 读操作需要 `tool_manager` 参数，写操作可选 `device_key` 参数
- 写操作先发送硬件配置再发送数据，无需手动调用 `pinMode`

## 参考文件

| 文件 | 说明 |
|------|------|
| `src/use_cases/_plugin_helpers.py` | 插件 SDK 源码（唯一实现，本教程即基于此） |
| `src/plugins/system_basic/plugin.py` | `send_device_command` + `request_device_result` 示例 |
| `src/plugins/weather/plugin.py` | `kv_get` + `kv_set` + `http_get_json` + `send_device_command` 示例 |
| `src/plugins/media_player/plugin.py` | `play_music_url` + `http_request` 示例 |
| `src/plugins/memory/plugin.py` | `resolve_device_key` + LTM 服务示例 |
| `src/plugins/diary/plugin.py` | `resolve_device_key` + `get_diary_repository` 示例 |
| `src/use_cases/skill_tools.py` | `skill_catalog_text` 示例 |
| `src/plugins/device_control/plugin.py` | `gpio_mode` + `gpio_read` + `pwm_write` 等 IO SDK 示例 |
