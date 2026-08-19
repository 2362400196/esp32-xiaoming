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
| 指令回执 | `request_device_result()` / `send_device_command_ack()` | 下发指令并**等待设备回复结果**（Lua 返回、状态查询、指令 ack） |
| 配置读取 | `get_plugin_config_or_env()` | 插件配置 → 环境变量 → 默认值，三级回退 |
| HTTP 请求 | `http_request()` / `http_get_json()` | 统一超时与错误处理的外部 API 调用 |
| LTM 记忆 | `get_ltm_service()` / `get_default_ltm_service()` | 访问长期记忆服务（注入优先） |
| 仓储工厂 | `get_diary_repository()` / `get_device_repository()` | 延迟加载数据库仓储，避免插件启动即依赖 DB |
| 技能目录 | `skill_catalog_text()` | 渲染当前设备可用技能目录文本 |

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

## 三、指令回执：等待设备回复

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

## 四、插件配置读取：配置 → 环境变量 → 默认值

插件可能需要用户配置 API Key，但老插件往往还要兼容"从环境变量读"的部署方式。`get_plugin_config_or_env` 统一了三者优先级：

```python
from src.use_cases._plugin_helpers import get_plugin_config_or_env

# 参数：tool_manager, 插件 id, 配置 key, 环境变量名（可空）, 默认值
amap_key = get_plugin_config_or_env(
    tool_manager, "weather", "amap_key",
    env_var="AMAP_WEATHER_KEY", default="",
)
```

**优先级**：`tool_manager.get_plugin_config()`（设备插件配置）→ 环境变量 → 默认值。

::: warning 环境变量有白名单限制
环境变量回退**不是随便什么变量都能读**。出于安全（沙箱机制的一部分），只允许读取：
- 以 `<插件id>_` 开头（如插件 `quote` 可用 `QUOTE_API_URL`）
- 或 `PLUGIN_` 开头
- 或通过环境变量 `PLUGIN_ENV_ALLOWLIST`（逗号分隔）显式放行

不符合规则的变量名会被拒绝，直接落到默认值。建议插件环境变量一律用 `<插件id>_` 前缀命名。
:::

替换之前常见的 `_get_xxx_key` 手写回退逻辑：

```python
# ❌ 旧写法：每个插件重复实现
def _get_amap_key(tool_manager) -> str:
    if tool_manager and hasattr(tool_manager, "get_plugin_config"):
        cfg = tool_manager.get_plugin_config("weather", "amap_key", "")
        if cfg:
            return cfg
    import os
    return os.environ.get("AMAP_WEATHER_KEY", "")

# ✅ 新写法：一行搞定
amap_key = get_plugin_config_or_env(tool_manager, "weather", "amap_key",
                                    env_var="AMAP_WEATHER_KEY", default="")
```

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

## 九、最佳实践与迁移清单

### 新插件写法模板

```python
from src.use_cases.tools_system import tool, StopPipeline
from src.use_cases._plugin_helpers import (
    get_device_key,                 # 设备标识（查表用）
    send_device_command,            # 一次性指令
    request_device_result,          # 需要回执的指令
    get_plugin_config_or_env,       # 配置读取
    http_get_json,                  # 外部 API
)

@tool(cache=False)
async def example(value: str = "", tool_manager=None) -> str:
    """示例工具。"""
    key = get_plugin_config_or_env(tool_manager, "example", "api_key",
                                   env_var="EXAMPLE_API_KEY", default="")
    data, err = await http_get_json("https://api.example.com/v1", params={"q": value})
    if err:
        return f"请求失败: {err}"
    err = await send_device_command(tool_manager, "show_card", json.dumps(data))
    if err:
        return "卡片显示失败"
    return "操作完成"
```

### 旧代码迁移对照

| 旧写法（每个插件各写一份） | 新写法（统一 SDK） |
|---------------------------|---------------------|
| `tool_manager.channel.send_json({"type": "instruct", "command_id": "...", "data": "..."})` | `await send_device_command(tool_manager, "...", "...")` |
| `if not tool_manager or not tool_manager.channel: return "设备未连接"` + `try/except` | `err = await send_device_command(...)`；`err` 非空即失败原因 |
| 手写 future + `asyncio.wait_for` 等设备回复 | `request_device_result(...)`，返回 `(result, status, detail)` |
| 每个插件写 `_get_xxx_key()`（配置→环境变量回退） | `get_plugin_config_or_env(...)` |
| `httpx.AsyncClient(timeout=...)` + `try/except` | `http_get_json(...)` 返回 `(data, error)` |
| 模块顶层 `import` 数据库仓储 | 工具内 `get_diary_repository()` / `get_device_repository()` |
| 自己拼技能列表文本 | `skill_catalog_text(tool_manager)` |

### 注意事项

- **下划线模块**：`_plugin_helpers.py` 不会被自动注册为工具，可放心 import
- **future 冲突**：同一 `future_attr` 同时只能有一个请求在等待，不同类型用不同属性名
- **延迟导入**：仓储工厂在工具函数内调用，不要在模块顶层
- **成功/失败约定**：`send_device_command` 返回 `None`=成功、字符串=失败原因；HTTP 函数返回 `(result, None)` / `(None, error)`；`request_device_result` 用 `status` 判断
- **中文可播报**：错误信息返回中文文本，TTS 直接播给用户

## 参考文件

| 文件 | 说明 |
|------|------|
| `src/use_cases/_plugin_helpers.py` | 插件 SDK 源码（唯一实现，本教程即基于此） |
| `src/plugins/system_basic/plugin.py` | `send_device_command` + `request_device_result` 示例 |
| `src/plugins/weather/plugin.py` | `get_plugin_config_or_env` + `http_get_json` + `send_device_command` 示例 |
| `src/plugins/media_player/plugin.py` | `send_instruct` + `http_request` 示例 |
| `src/plugins/memory/plugin.py` | `resolve_device_key` + LTM 服务示例 |
| `src/plugins/diary/plugin.py` | `resolve_device_key` + `get_diary_repository` 示例 |
| `src/use_cases/skill_tools.py` | `skill_catalog_text` 示例 |
