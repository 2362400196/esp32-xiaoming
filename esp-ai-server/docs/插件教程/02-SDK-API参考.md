# 02 - SDK API 参考

插件 SDK 统一从 `src.use_cases._plugin_helpers` 导入（也推荐直接按域从 `src.use_cases.sdk.<域>` 导入）：

```python
from src.use_cases._plugin_helpers import http_request, send_device_command, kv_get
# 或按域：
from src.use_cases.sdk.http import http_request
from src.use_cases.sdk.device import send_device_command
from src.use_cases.sdk.io import gpio_write
from src.use_cases.sdk.music import play_music_url
from src.use_cases.sdk.storage import kv_get, plugin_data_write
from src.use_cases.sdk.services import llm_chat, tts_synthesize
```

**内置插件 vs 沙箱插件**：

- **内置插件**（`src/plugins/`）：进程内运行，调用 SDK 真实实现。
- **沙箱插件**（`data/plugins/installed/`）：运行在子进程，SDK 调用通过 RPC 转发到主进程（由 `sdk_shim.py` 桩接管）。本文每节标注"沙箱可用性"——标记 **沙箱可用** 的表示 shim 已覆盖、签名一致；未覆盖的仅内置插件可用。

**通用约定**：

- `tool_manager` 参数一律"自动传入"，插件调用时无需关心。
- 权限不足时抛 `PermissionError`（或设备类操作返回错误串，见各 API 说明）。
- 带 `device_key` 参数的 API，为空时自动推断为当前会话设备；沙箱下强制限定为本次调用绑定的设备（见 [03](03-权限与安全.md) 的设备作用域）。

---

## 一、设备指令（权限：`device`）

**沙箱可用** ✅

### send_device_command

```python
async def send_device_command(tool_manager=None, command_id="", data="") -> str | None
```

下发一条 instruct 指令给设备，不等待回复。

- 返回：`None` = 成功；字符串 = 失败原因（如 `"设备未连接"`）。

```python
err = await send_device_command(command_id="set_volume", data="50")
```

### send_device_command_ack

```python
async def send_device_command_ack(tool_manager=None, command_id="", data="", timeout=8.0) -> tuple
```

下发指令并等待设备 ack。

- 返回：`(result, status, detail)`，`status ∈ {"ok", "offline", "timeout", "error"}`。

### request_device_result

```python
async def request_device_result(tool_manager=None, command_id="", future_attr="",
                                timeout=8.0, data="", if_busy=None) -> tuple
```

下发指令并等待设备通过 future 回复结果（读传感器等场景）。

- 返回：`(result, status, detail)`，`status ∈ {"ok", "offline", "timeout", "error", "busy"}`。

### send_instruct

```python
async def send_instruct(channel=None, command_id="", data="") -> None
```

向指定 channel 发原始 instruct（需要 channel 对象）。**沙箱插件一般用 `send_device_command` 代替**；沙箱 shim 已覆盖此函数（channel 由主进程注入）。

### device_is_online / device_get_info

```python
def device_is_online(device_key: str = "", tool_manager=None) -> bool
async def device_get_info(device_key: str = "", tool_manager=None) -> dict
```

- `device_get_info` 返回 `{"device_key", "mac", "firmware_version", "register_time", "ota_updating", "ota_progress"}`，设备不在线返回 `{}`。

---

## 二、设备 IO：GPIO / PWM / ADC / 舵机（权限：`device`）

**沙箱可用** ✅（本版本新增 shim，签名与主进程 `src/use_cases/sdk/io.py` 一致）

返回约定：**写操作**返回 `"ok"` 或错误描述字符串；**读操作**返回 `int`，失败返回 `-1`。
所有函数均支持 `device_key` 参数（为空时用当前设备；沙箱下只能操作绑定设备）。

```python
from src.use_cases._plugin_helpers import gpio_mode, gpio_write, gpio_read, pwm_write, adc_read, servo_write

await gpio_mode(2, "output")          # 模式: output / input / input_pullup / input_pulldown
result = await gpio_write(2, 1)       # 数字写，返回 "ok" 或错误串
level  = await gpio_read(2)           # 数字读，0/1，失败 -1
result = await pwm_write(4, 512, 5000)  # PWM：duty 0-1023（10bit），freq 默认 5000Hz
value  = await adc_read(1)            # ADC 读，0-4095；ESP32-S3 仅 GPIO1~10（ADC1），越界返回 -1
result = await servo_write(5, 90)     # 舵机角度 0-180 度（自动裁剪）
```

| 函数 | 签名 | 返回 |
|------|------|------|
| `gpio_mode` | `(pin: int, mode: str = "output", tool_manager=None, device_key: str = "")` | `"ok"`/错误串 |
| `gpio_write` | `(pin: int, value: int, tool_manager=None, device_key: str = "")` | `"ok"`/错误串 |
| `gpio_read` | `(pin: int, tool_manager=None, device_key: str = "")` | `0/1`，失败 `-1` |
| `pwm_write` | `(pin: int, duty: int, freq: int = 5000, tool_manager=None, device_key: str = "")` | `"ok"`/错误串 |
| `adc_read` | `(pin: int, tool_manager=None, device_key: str = "")` | `0-4095`，失败 `-1` |
| `servo_write` | `(pin: int, angle: int, tool_manager=None, device_key: str = "")` | `"ok"`/错误串 |

> 读操作（`gpio_read`/`adc_read`）通过设备端 Lua 引擎实现，需要设备在线并支持 `execute_lua`，超时 5 秒。

---

## 三、音乐播放（权限：`device`）

**沙箱可用** ✅（本版本新增 shim）

### play_music_url

```python
async def play_music_url(url: str, title: str = "", artist: str = "",
                         duration: int = 0, device_key: str = "",
                         lyric_url: str = "", lyrics_offset: int = 0) -> str
```

向设备推送一个可直接播放的音频 URL，设备立即播放。

- `url`：音频文件 URL（必填）。
- `title` / `artist` / `duration`：歌曲元信息，会推送 `music_meta` 指令驱动歌词/界面显示。
- `lyric_url`：LRC 歌词 URL，服务器自动下载解析并逐行推送（**歌词下载内部走 HTTP，需要插件声明 `network` 权限才能取到歌词；未声明时播放正常但歌词为空**）。
- `lyrics_offset`：歌词时间偏移（毫秒）。
- `device_key`：为空时自动选择第一个在线设备（沙箱下受设备作用域约束）。
- 返回：`"ok"` 或错误描述字符串（`"设备注册表不可用"` / `"没有可用的在线设备"` / `"发送播放指令失败: ..."` 等）。

```python
result = await play_music_url("http://192.168.1.100:2233/music/song.mp3",
                              title="歌曲名", artist="歌手", duration=210)
```

---

## 四、HTTP 请求（权限：`network`）

**沙箱可用** ✅（`http_request` / `http_get_json` / `http_stream_*`）

所有 URL 经过 SSRF 防护（禁止内网/回环/云元数据地址）与全局域名白名单（环境变量 `PLUGIN_URL_ALLOWLIST`，逗号分隔，配置后仅允许访问白名单域名）。

### http_request

```python
async def http_request(method: str, url: str, *, params: dict | None = None,
                       headers: dict | None = None, content=None,
                       timeout: float = 10.0) -> tuple
```

- 返回：`(response, None)` 或 `(None, error)`。
- response 暴露 `.status_code`、`.text`、`.json()`（沙箱下是最小模拟对象，仅这三个成员）。

```python
resp, err = await http_request("GET", "https://api.example.com/v1/data",
                               params={"q": "hello"}, timeout=5.0)
if err is None and resp.status_code == 200:
    data = resp.json()
```

### http_get_json

```python
async def http_get_json(url: str, params: dict | None = None,
                        headers: dict | None = None, timeout: float = 8.0) -> tuple
```

- 返回：`(data, None)` 或 `(None, error)`。

### 流式 HTTP（SSE）

```python
async def http_stream_open(method: str, url: str, *, headers: dict | None = None,
                           content=None, timeout: float = 30.0) -> tuple   # -> (stream_id, err)
async def http_stream_read(stream_id: str, timeout: float = 0.5) -> tuple  # -> (line, err)
async def http_stream_close(stream_id: str) -> None
```

- `http_stream_read`：`(line, None)` 正常一行；`(None, None)` 读超时（可继续轮询）；`(None, err)` 出错。

---

## 五、WebSocket（权限：`network`）

**沙箱可用** ✅（沙箱版额外支持连接池）

```python
async def ws_connect(url: str, headers: dict | None = None, pool: str = "normal",
                     pool_headers: list | None = None) -> str   # 返回 session_id
async def ws_send(session_id: str, data: bytes) -> None
async def ws_recv(session_id: str, timeout: float = 0.1) -> bytes | None
async def ws_close(session_id: str) -> None
async def ws_prewarm(url: str, headers: dict | None = None, count: int = 1,
                     pool_headers: list | None = None) -> int    # 仅沙箱 shim 提供
```

- `pool`：`"reuse"`（close 时归还复用，适合请求型连接）、`"prewarm"`（取预热连接，close 真正关闭，适合会话型）、`"normal"`（不池化）。
- `pool_headers`：声明参与连接池分组的自定义鉴权 header（如 `["x-nls-token"]`），避免不同凭据混池。
- 错误约定：连接/收发失败抛 `RuntimeError`；`ws_recv` 超时返回 `None`。

> 注意：主进程版 `src/use_cases/sdk/ws.py` 的 `ws_connect(url, headers)` 没有 `pool`/`pool_headers` 参数；连接池是沙箱 shim 的扩展能力，内置插件不可用。

---

## 六、存储：插件数据文件（权限：`file_read` / `file_write`）

**沙箱可用** ✅

数据目录：`data/plugins/data/<插件ID>/`，路径穿越受保护（只能访问本插件目录）。

```python
def plugin_data_read(path: str, tool_manager=None) -> str | None        # 不存在返回 None
def plugin_data_write(path: str, content: str, tool_manager=None) -> None
def plugin_data_list(path: str = "", tool_manager=None) -> list         # [{name, is_dir, size, mtime}]
def plugin_data_delete(path: str, tool_manager=None) -> bool            # 文件或空目录
```

---

## 七、键值存储 KV（权限：`kv`）

**沙箱可用** ✅

存储文件：`data/plugins/kv/<设备ID>/<插件ID>.json`（设备隔离）或 `data/plugins/kv/<插件ID>.json`（全局，多设备共享）。
当调用上下文携带 `device_id`（tool_manager）时自动按设备隔离，多用户互不干扰。

```python
def kv_get(key: str, default=None, tool_manager=None)
def kv_set(key: str, value, tool_manager=None) -> None          # value 必须 JSON 可序列化
def kv_delete(key: str, tool_manager=None) -> bool              # False = 键不存在
def kv_list(prefix: str = "", tool_manager=None) -> list        # [{"key": ..., "value": ...}]
```

```python
visits = kv_get("visit_count", default=0)
kv_set("visit_count", visits + 1)
```

---

## 八、AI 服务

**沙箱可用** ✅（`llm_chat` / `llm_generate` / `tts_synthesize` / `get_user_profile_summary`）

```python
async def llm_chat(messages: list, system_prompt: str | None = None,
                   tool_manager=None) -> str          # 权限: llm
async def llm_generate(prompt: str, system_prompt: str | None = None,
                       tool_manager=None) -> str      # 权限: llm（单轮封装）
async def tts_synthesize(text: str, voice: str | None = None,
                         tool_manager=None) -> bytes  # 权限: tts，返回 MP3 字节
async def get_user_profile_summary(device_key: str = "",
                                   tool_manager=None) -> str  # 权限: db
```

```python
answer = await llm_chat([{"role": "user", "content": "把这句话翻译成英语：你好"}])
audio = await tts_synthesize("合成这段话", voice="BV001_streaming")
```

---

## 九、长期记忆 / 仓库（权限：`ltm` / `db`）

**沙箱可用** ✅（沙箱下返回 RPC 代理对象，方法签名一致）

```python
def get_ltm_service(tool_manager=None): ...       # 权限: ltm
def get_default_ltm_service(): ...                # 权限: ltm
def get_diary_repository(): ...                   # 权限: db
def get_device_repository(): ...                  # 权限: db
```

`ltm_service`（LtmProxy）方法：

```python
await svc.store(item)                    # item 为 dict（含 text/device_id 等），返回 (memory_id, changed)
items = await svc.recall(query)          # query 为 dict（device_id/summary_labels/keyword/limit），返回 list[dict]
items = await svc.list_all(device_id)
ok    = await svc.update(memory_id, patch, device_id)   # -> bool
item  = await svc.forget(memory_id, device_id)
```

`diary_repo` 方法：`get_recent(device_id, limit=7)`、`upsert_entry(device_id, date, content, append=False)`、`search(device_id, keyword)`。
`device_repo` 方法：`get_device_config(device_id)`、`update_device_partial(device_id, partial)`。

> 沙箱下这些操作强制限定当前绑定设备（`device_id` 传别的设备会被拒绝）。

---

## 十、工具注册与流程控制

**沙箱可用** ✅

```python
from src.use_cases.tools_system import tool, StopPipeline

@tool(name=None, description=None, cache=True)   # 详见 01-快速开始
async def my_tool(...) -> str: ...

raise StopPipeline()   # 终止本次 LLM 生成流程（与主进程语义一致）
```

`register_tool(td)`：以编程方式注册工具（接受 ToolDefinition 兼容对象），一般用不到。

---

## 十一、基础设施与工具函数

| 函数 | 说明 | 沙箱可用 |
|------|------|----------|
| `get_device_key(tool_manager=None) -> str` | 当前设备绑定 key（bound_xxx），空串表示未连接 | ✅ |
| `resolve_device_key(device_key: str = "", tool_manager=None) -> str` | MAC→device_key 映射补全 | ✅ |
| `get_plugin_config_or_env(tool_manager=None, plugin="", key="", env_var=None, default="") -> str` | 读插件配置；带 `env_var` 时受环境变量白名单限制 | ✅ |
| `plugin_log(message: str, level: str = "info") -> None` | 写插件日志（debug/info/warn/error） | ✅ |
| `skill_catalog_text(tool_manager=None) -> str` | 技能目录文本 | ✅ |
| `mask_secret(value, visible=4) -> str` / `is_secret_key(key) -> bool` | 配置脱敏 | ✅ |
| `generate_uuid()` / `current_timestamp()` / `json_dumps(obj, indent=None)` / `json_loads(s)` | 纯本地工具 | ✅ |
| `get_logger(name)` / `get_settings()` | 框架日志/配置 | ❌ 仅内置插件 |
| `get_device_registry()` | 设备注册表对象 | ❌ 仅内置插件 |
| `speak_direct(channel, ctx, fsm, text)` | 直接 TTS 播放到设备 | ❌ 仅内置插件 |
| `get_wechat_bot()` / `get_wechat_binding_mgr()` / `get_remote_config_provider()` | 微信/远程配置基础设施 | ❌ 仅内置插件 |

---

## 十二、权限速查

每个 API 所需的 `manifest.permissions` 声明：

| 权限 | 覆盖的 API |
|------|-----------|
| `device` | 设备指令全部、`device_is_online`、`device_get_info`、全部 IO（gpio/pwm/adc/servo）、`play_music_url` |
| `network` | `http_request`、`http_get_json`、`http_stream_*`、`ws_*`（以及 `play_music_url` 的歌词下载） |
| `ltm` | `get_ltm_service` / `get_default_ltm_service` |
| `db` | `get_diary_repository`、`get_device_repository`、`get_user_profile_summary` |
| `file_read` / `file_write` | `plugin_data_read/list` / `plugin_data_write/delete` |
| `kv` | `kv_get/set/delete/list` |
| `llm` | `llm_chat` / `llm_generate` |
| `tts` | `tts_synthesize` |

完整权限模型见 [03-权限与安全](03-权限与安全.md)。
