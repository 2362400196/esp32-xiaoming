# 服务端编程接口

本文档介绍如何在 小明同学 服务端代码中编程控制设备。适用于自定义工具开发、自动化脚本和服务端集成。

## 获取设备列表

```python
from src.infrastructure.web import get_device_registry

registry = get_device_registry()
if registry:
    # 获取所有设备 key
    device_keys = list(registry._devices.keys())

    # 获取设备详情
    device = registry.resolve("设备key")
    if device:
        channel = device.get("channel")    # WebSocket 通道
        session = device.get("session")    # 会话对象
        fsm = device.get("fsm")            # 状态机
        user_config = device.get("user_config")  # 设备配置
```

## 让设备说话

### speak(device_id, text)

让指定设备播放 TTS 语音：

```python
from src.infrastructure.web import get_speaker

speaker = get_speaker()
if speaker:
    await speaker.speak("设备key", "你好，这是一段测试语音", need_wakeup=True)
```

### 广播到所有设备

```python
await speaker.speak_all("大家好，欢迎使用", need_wakeup=True)
```

### 在自定义工具中直接播放 TTS

```python
from src.use_cases.tools_system import tool

@tool()
async def my_tool(tool_manager=None):
    if tool_manager and tool_manager.channel:
        # 发送 instruct 指令
        await tool_manager.channel.send_json({
            "type": "instruct",
            "command_id": "on_llm_cb",
            "data": "这是工具调用的语音内容"
        })
    return "操作成功"
```

## 唤醒设备

```python
speaker = get_speaker()
if speaker:
    # 唤醒指定设备
    await speaker.wakeup("设备key")

    # 唤醒所有设备
    await speaker.wakeup_all()
```

## 停止设备

```python
speaker = get_speaker()
if speaker:
    # 停止指定设备（进入待机）
    await speaker.stop("设备key")

    # 停止所有设备
    await speaker.stop_all()
```

## 控制音量

通过 WebSocket 发送音量指令：

```python
from src.infrastructure.web import get_device_registry

registry = get_device_registry()
if registry:
    device = registry.resolve("设备key")
    if device:
        channel = device.get("channel")
        if channel:
            await channel.send_json({
                "type": "instruct",
                "command_id": "set_volume",
                "data": "0.8"  # 0.0~1.0
            })
```

## 发送自定义指令

```python
await channel.send_json({
    "type": "instruct",
    "command_id": "custom_command",
    "data": "指令数据"
})
```

## 完整示例

```python
import asyncio
from src.infrastructure.web import get_speaker, get_device_registry

async def main():
    registry = get_device_registry()
    if not registry:
        print("设备注册表不可用")
        return

    # 获取所有设备
    device_keys = list(registry._devices.keys())
    if not device_keys:
        print("没有在线设备")
        return

    print(f"在线设备: {device_keys}")

    # 获取 Speaker
    speaker = get_speaker()
    if not speaker:
        print("Speaker 不可用")
        return

    # 唤醒并说话
    device_key = device_keys[0]
    await speaker.wakeup(device_key)
    await speaker.speak(device_key, "你好，欢迎使用小明同学", need_wakeup=True)

asyncio.run(main())
```

## Speaker API

| 方法 | 说明 |
|------|------|
| `speak(device_key, text, need_wakeup=True)` | 让指定设备说话 |
| `speak_all(text, need_wakeup=True)` | 广播到所有设备 |
| `wakeup(device_key)` | 唤醒设备 |
| `wakeup_all()` | 唤醒所有设备 |
| `stop(device_key)` | 停止设备 |
| `stop_all()` | 停止所有设备 |

## DeviceRegistry API

| 方法 | 说明 |
|------|------|
| `resolve(key)` | 通过设备 key 查找设备 |
| `get_all_ids()` | 获取所有设备 ID |
| `count()` | 在线设备数量 |
| `register(key, channel, session, fsm, ...)` | 注册新设备 |
| `unregister(key)` | 注销设备 |
| `has(key)` | 检查设备是否存在 |
| `get_by_mac(mac)` | 通过 MAC 地址查找 |
| `get_stats()` | 获取设备统计信息 |
| `set_pending_ota(key, cmd)` | 设置待推送 OTA 指令 |
| `set_pending_wifi_config(key, config)` | 设置待推送 WiFi 配置 |
| `set_pending_instruct(key, cmd)` | 设置待推送指令 |

---

## 内置工具

系统启动时自动注册以下内置工具（`src/use_cases/builtin_tools.py`）：

| 工具 | 参数 | 功能 |
|------|------|------|
| `get_current_time` | 无 | 获取当前日期和时间 |
| `get_current_date` | 无 | 获取今天的日期和星期几 |
| `set_volume` | `level: int (0-100)` | 设置设备音量 |
| `volume_up` | 无 | 音量调大 10% |
| `volume_down` | 无 | 音量调小 10% |
| `set_brightness` | `level: int (0-100)` | 设置屏幕亮度 |
| `standby` | 无 | 进入待机状态 |
| `play_music` | `song: str` | 搜索并播放歌曲 |
| `test_device` | 无 | 设备自检 |
| `execute_lua` | `code: str` | 在设备端执行 Lua 脚本 |
| `stop_lua` | 无 | 停止正在执行的 Lua 脚本 |
| `clear_screen` | 无 | 清除设备屏幕 Lua 绘图 |
| `http_request` | `url, method=GET, headers="", body=""` | 发送 HTTP GET/POST 请求 |
| `hello` | `name: str` | 向用户打招呼 |
| `list_skills` | 无 | 列出设备可用技能 |
| `read_skill_document` | `skill_id: str` | 读取指定技能文档 |
| `memory_store` | `content, device_id="", tags="", keywords=""` | 存储长期记忆 |
| `memory_recall` | `summary_labels="", device_id="", limit=8` | 按摘要标签检索记忆 |
| `memory_list` | `device_id=""` | 列出所有记忆 |
| `memory_update` | `memory_id, content="", tags="", keywords="", device_id=""` | 更新指定记忆 |
| `memory_forget` | `memory_id, device_id=""` | 删除指定记忆 |

## 自定义工具开发

在 `src/use_cases/custom/` 目录下新建 `.py` 文件，使用 `@tool()` 装饰器即可自动注册：

```python
from src.use_cases.tools_system import tool

@tool()
def hello(name: str) -> str:
    """向用户打招呼。name 为用户的名字。"""
    return f"你好 {name}！很高兴认识你。"
```

### 参数注入

函数签名中的特殊参数会自动注入：

| 参数 | 类型 | 说明 |
|------|------|------|
| `tool_manager` | `PerUserToolManager` | 工具管理器，可访问 `channel` 发送指令 |
| `channel` | `WSChannel` | WebSocket 通道，用于向设备发送 JSON/二进制消息 |
| `ctx` | 上下文对象 | 会话上下文，包含 `session_id`、`device_id` 等信息 |
| `fsm` | `SessionFSM` | 会话状态机，可读取/切换当前状态 |

#### PerUserToolManager 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `channel` | `WSChannel` | 当前设备的 WebSocket 通道 |
| `ctx` | 上下文对象 | 当前会话上下文 |
| `fsm` | `SessionFSM` | 当前会话状态机 |
| `user_config` | `DeviceConfig` | 当前设备配置（LLM/TTS/ASR 参数等）|
| `active_skills` | `set[str]` | 当前会话激活的技能 ID 集合 |
| `_disabled_tools` | `set[str]` | 被禁用的工具名集合 |

### 工具中断

工具中可抛出 `StopPipeline` 终止当前 Pipeline：

```python
from src.use_cases.tools_system import tool, StopPipeline

@tool()
async def my_tool(channel=None, fsm=None):
    if channel:
        await channel.send_json({
            "type": "instruct",
            "command_id": "on_llm_cb",
            "data": "正在处理，请稍候..."
        })
        raise StopPipeline()
```

---

## 技能系统（Skill）

技能是预定义的对话处理模块，存放在 `src/skills/` 目录下。

### 技能目录结构

```
src/skills/
├── guess_number/
│   └── SKILL.md       # 技能定义（名称、描述、指令）
├── gushi/
│   └── SKILL.md
├── new/
│   └── SKILL.md
└── test_device_only/
    └── SKILL.md
```

### SKILL.md 格式

```markdown
---
name: diary
description: 日记记录与回顾
category: ["生活"]
tags: ["日记", "记录"]
cap_groups: ["general"]
---
你是一个日记助手，帮助用户记录和回顾每天的日记内容。
```

| 字段 | 说明 |
|------|------|
| `name` | 技能唯一 ID（英文，对应目录名）|
| `description` | 技能描述（LLM 据此判断是否激活技能）|
| `category` | 分类标签列表 |
| `tags` | 搜索标签列表 |
| `cap_groups` | 能力组，用于技能互斥（同组技能同时只能激活一个，`general` 为通用组）|

### 技能 API

```python
from src.use_cases import skill_system

# 初始化技能系统
skill_system.init(skills_root_dir="src/skills", data_dir="src/data")

# 获取技能目录（返回设备可见的技能列表）
catalog = skill_system.get_catalog(device_id="设备key", skills=["diary"])

# 获取技能详情
entry = skill_system.get_skill("diary")

# 获取技能文档（SKILL.md 的 instructions 部分）
doc = skill_system.get_skill_document("diary")

# 获取技能能力组
cap_groups = skill_system.get_skill_cap_groups("diary")

# 获取技能运行时目录（entries/ 数据存储位置）
skill_dir = skill_system.get_skill_directory("diary")

# 创建技能
skill_system.create_skill(
    name="my_skill",
    description="我的技能",
    instructions="指令内容",
    category=["工具"],
    tags=["自定义"],
)

# 更新技能
skill_system.update_skill(skill_id="my_skill", description="新描述", ...)

# 删除技能
skill_system.delete_skill("my_skill")

# 重新加载所有技能
skill_system.reload()
```

---

## 记忆系统

### 短时记忆（ConversationMemory）

```python
from src.use_cases.memory import ConversationMemory

memory = ConversationMemory(max_messages=20)
memory.add_user_message("你好")
memory.add_assistant_message("你好！有什么可以帮助你的？")

# 构建 LLM 消息列表
messages = memory.build_messages(system_prompt="你是助手", current_user_message="今天天气如何")

# 获取消息列表
msgs = memory.messages()

# 清空记忆
memory.clear()
```

### 长期记忆（LongTermMemory）

长期记忆存储跨会话的耐久事实（用户偏好、重要事件等），通过摘要标签和关键词检索。

```python
from src.use_cases.memory import LongTermMemoryServiceImpl
from src.infrastructure.db.repositories.ltm_repository import SqlLongTermMemoryRepository

repo = SqlLongTermMemoryRepository()
ltm = LongTermMemoryServiceImpl(repository=repo)

# 存储记忆
memory_id, is_new = await ltm.store(MemoryItem(
    device_id="设备key",
    content="用户喜欢听古典音乐",
    tags=["偏好", "音乐"],
))

# 检索记忆
items = await ltm.recall(MemoryQuery(
    device_id="设备key",
    keyword="音乐",           # 关键词搜索
    limit=5,
))

# 列出所有记忆
items = await ltm.list_all(device_id="设备key")

# 更新记忆
await ltm.update(memory_id="xxx", patch={"content": "新内容"}, device_id="设备key")

# 删除记忆
item = await ltm.forget(memory_id="xxx", device_id="设备key")

# 获取摘要目录
catalog = await ltm.get_summary_catalog(device_id="设备key")
```

#### MemoryItem 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `memory_id` | str | 记忆 ID，格式 `mem-{timestamp}-{seq}`，留空自动生成 |
| `device_id` | str | 所属设备 key |
| `content` | str | 归一化记忆事实（核心内容）|
| `tags` | list[str] | 摘要标签，最多 3 个，用于构建摘要目录 |
| `keywords` | list[str] | 关键词，最多 3 个，用于关键词索引 |
| `source` | str | 来源，默认 `manual` |

#### MemoryQuery 字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `device_id` | str | `""` | 所属设备 key |
| `keyword` | str | `""` | 关键词搜索（模糊匹配）|
| `summary_labels` | tuple[str, ...] | `()` | 摘要标签精确过滤 |
| `limit` | int | `8` | 返回上限 |

---

## 图片发送

通过 WebSocket 向设备屏幕发送图片指令。

```python
from src.use_cases.image_sender import ImageSender

sender = ImageSender()

# 发送图片 URL 到设备屏幕
# width/height 默认 80x80（SCREEN_WIDTH/SCREEN_HEIGHT）
await sender.send_image_to_device(channel, "https://example.com/image.jpg", width=240, height=240)

# 清除设备屏幕图片
await sender.send_clear_image(channel)

# 发送情绪图片（需启用 SERVER_EMOTION_ENABLED）
# 根据 text 内容自动匹配表情 GIF
await sender.send_emotion_image(channel, "今天真开心", device_id="设备key")

# 发送自定义图片（二进制数据）
# 内部会上传到静态服务并返回 URL
image_url = await sender.send_custom_image(channel, image_bytes)
```

| 方法 | 参数 | 说明 |
|------|------|------|
| `send_image_to_device` | `channel, image_url, width=240, height=240` | 发送图片 URL 到设备 |
| `send_clear_image` | `channel` | 清除屏幕图片 |
| `send_emotion_image` | `channel, text, device_id=""` | 根据文本情绪匹配表情 |
| `send_custom_image` | `channel, image_bytes` | 发送二进制图片数据 |

---

## MCP 外部工具

MCP（Model Context Protocol）用于接入外部工具服务，扩展 LLM 的能力。

```python
from src.use_cases.tools_system import PerUserToolManager

# 初始化 MCP 连接（shared 必填：共享工具管理器）
tool_mgr = PerUserToolManager(shared=shared_tool_mgr)
await tool_mgr.initialize_mcp({
    "amap-maps": {
        "type": "streamable_http",
        "url": "https://mcp.api-inference.modelscope.net/xxx/mcp"
    }
})

# 获取 MCP 工具 Schema（LLM function calling 用）
schemas = tool_mgr._mcp_tool_schemas

# 调用工具（统一入口 call_tool）
result = await tool_mgr.call_tool("maps_direction_walking", {
    "starts": "天安门",
    "ends": "故宫"
})
```

### MCP 配置格式

| 字段 | 说明 |
|------|------|
| `type` | 传输协议：`streamable_http` / `sse` |
| `url` | MCP 服务器地址 |
| `headers` | 自定义请求头（可选）|

MCP 配置也可通过 `.env` 全局配置或设备级配置设置：

```bash
# .env 全局配置
MCP_SERVERS_JSON={"amap-maps":{"type":"streamable_http","url":"https://xxx/mcp"}}
```

多用户模式下，每个设备可在数据库中配置独立的 MCP 服务器。

---

## 设备数据存储（DeviceRepository）

`DeviceRepository` 是底层设备数据操作接口，封装了设备配置、MCP 服务器、功能开关等数据的读写。

### 获取实例

```python
from src.infrastructure.db.repositories.device_repository import DeviceRepository

repo = DeviceRepository()
```

### 设备查询

| 方法 | 说明 |
|------|------|
| `resolve_device(device_id_or_mac)` | 解析设备标识，返回 `(device_id, config_dict)` 或 `(None, None)`。按 device_id → device_key → mac_address 顺序查找 |
| `check_device_owner(device_id, user_id)` | 校验设备是否属于指定用户，返回 `bool` |
| `find_by_mac(mac)` | 通过 MAC 查找设备，返回 `(device_id, config_dict)` |
| `find_by_key(key)` | 通过 device_key 查找设备，返回 `(device_id, config_dict)` |

**resolve_device 示例：**

```python
device_id, config = await repo.resolve_device("D8:3B:DA:6D:D9:3C")
if not device_id:
    raise ValueError("设备不存在")
# config 包含设备所有配置字段
```

### MCP 服务器管理

| 方法 | 说明 |
|------|------|
| `get_mcp_servers(device_id)` | 获取设备所有 MCP 服务器配置，返回 `dict` |
| `set_mcp_server(device_id, server_name, config)` | 添加或更新 MCP 服务器配置 |
| `delete_mcp_server(device_id, server_name)` | 删除指定 MCP 服务器 |
| `toggle_mcp_server(device_id, server_name, disabled)` | 启用或禁用 MCP 服务器 |
| `toggle_mcp_tool(device_id, server_name, tool_name, disabled)` | 启用或禁用 MCP 服务器中的单个工具 |
| `get_disabled_mcp(device_id)` | 获取设备的 MCP 禁用列表，返回 `{disabled_servers: [], disabled_tools: {}}` |
| `mcp_enabled_plugins_add(device_id, server_name)` | 将 `mcp:{server_name}` 加入 `enabled_plugins`，确保 AI 可见 |
| `mcp_enabled_plugins_remove(device_id, server_name)` | 从 `enabled_plugins` 移除 `mcp:{server_name}` |

**MCP 操作示例：**

```python
# 添加 MCP 服务器
await repo.set_mcp_server(
    device_id, "amap-maps",
    {"type": "streamable_http", "url": "https://mcp.example.com/weather"}
)
await repo.mcp_enabled_plugins_add(device_id, "amap-maps")

# 禁用服务器
await repo.toggle_mcp_server(device_id, "amap-maps", disabled=True)

# 禁用单个工具（只禁用 maps_weather，其他工具正常）
await repo.toggle_mcp_tool(device_id, "amap-maps", "maps_weather", disabled=True)

# 获取禁用状态
disabled = await repo.get_disabled_mcp(device_id)
# disabled = {"disabled_servers": ["amap-maps"], "disabled_tools": {"amap-maps": ["maps_weather"]}}

# 删除服务器
await repo.delete_mcp_server(device_id, "amap-maps")
await repo.mcp_enabled_plugins_remove(device_id, "amap-maps")
```

### 设备配置更新

| 方法 | 说明 |
|------|------|
| `update_device_partial(device_id, updates)` | 部分更新设备配置字段，**不覆盖未传字段** |
| `get_device_config(device_id)` | 获取设备配置，返回 `dict` |

```python
# 更新设备部分配置
await repo.update_device_partial(device_id, {
    "disabled_mcp_servers": ["amap-maps"],
    "disabled_mcp_tools": {"amap-maps": ["maps_weather"]},
})
```
