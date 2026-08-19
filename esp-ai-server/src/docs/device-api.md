# ESP-AI-Server API 文档

本文档描述 ESP-AI-Server 提供的全部 REST API 接口。

> **文档版本**: v2.0 · 基于 `src/infrastructure/device_api.py` + `src/infrastructure/web.py` 实际路由生成

---

## 基础信息

| 项目 | 值 |
|------|-----|
| **Base URL** | `http://<server-ip>:8088` |
| **数据格式** | JSON |
| **WebSocket** | `ws://<server-ip>:8088?key=<设备密钥>` |

---

## 认证

### API 请求认证（X-API-Key）

大多数 API 需要通过 Header 传入 API Key：

```bash
curl -H "X-API-Key: your_api_key" http://localhost:8088/api/v1/devices
```

配置方式（`.env`）：

```
AUTH_API_KEY=设备认证密钥
ADMIN_API_KEY=管理后台认证密钥
```

> 若 `ADMIN_API_KEY` 未配置，API 允许无认证访问（仅限开发环境）。

### 设备 WebSocket 认证

设备通过 WebSocket URL 参数认证：

```
ws://<server-ip>:8088?key=<设备密钥>
ws://<server-ip>:8088/connect_espai_node?key=<设备密钥>
```

---

## 通用响应结构

### 成功响应

```json
{
  "code": 0,
  "message": "ok",
  "data": { ... }
}
```

### 错误响应

```json
{
  "code": 1,
  "message": "错误描述",
  "data": null
}
```

### HTTP 状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 请求成功（业务状态见 `code` 字段） |
| 401 | 缺少 `X-API-Key` Header |
| 403 | API Key 无效 |

---

## 一、设备管理 API（`/api/v1/devices`）

### 1.1 获取所有在线设备

```
GET /api/v1/devices
```

**响应示例：**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "count": 2,
    "devices": [
      {
        "mac": "AA:BB:CC:DD:EE:01",
        "device_key": "device_key_001",
        "name": "客厅设备",
        "state": "IDLE",
        "connected": true,
        "tts_playing": false,
        "session_id": "session_001",
        "uptime": 3600.5,
        "messages_count": 15
      }
    ],
    "timestamp": 1699999999.0
  }
}
```

---

### 1.2 获取指定设备信息

```
GET /api/v1/devices/{mac}
```

**参数：**

| 参数 | 位置 | 说明 |
|------|------|------|
| `mac` | URL | MAC 地址或设备 key |

**响应同上（单设备）。**

---

### 1.3 让指定设备说话

```
POST /api/v1/devices/{mac}/speak
Content-Type: application/json
```

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `mac` | URL | string | MAC 地址或设备 key |
| `text` | Body | string | 要播报的文本（1–1000 字） |

**请求体：**

```json
{
  "text": "你好"
}
```

```json
{
  "code": 0,
  "message": "Play started",
  "data": {
    "mac": "AA:BB:CC:DD:EE:01",
    "text": "你好"
  }
}
```

---

### 1.4 广播说话到所有设备

```
POST /api/v1/devices/speak/all
Content-Type: application/json
```

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `text` | Body | string | 播报文本 |

**请求体：**

```json
{
  "text": "大家好"
}
```

```json
{
  "code": 0,
  "message": "Played to 2 devices",
  "data": {
    "count": 2,
    "devices": ["AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02"],
    "text": "大家好"
  }
}
```

---

### 1.5 唤醒指定设备

```
POST /api/v1/devices/{mac}/wakeup
```

| 参数 | 位置 | 说明 |
|------|------|------|
| `mac` | URL | MAC 地址或设备 key |

```json
{
  "code": 0,
  "message": "Wakeup success",
  "data": {
    "device_id": "AA:BB:CC:DD:EE:01"
  }
}
```

---

### 1.6 广播唤醒所有设备

```
POST /api/v1/devices/wakeup/all
```

```json
{
  "code": 0,
  "message": "Woken up 2 devices",
  "data": {
    "count": 2,
    "devices": ["AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02"]
  }
}
```

---

### 1.7 停止指定设备

```
POST /api/v1/devices/{mac}/stop
```

| 参数 | 位置 | 说明 |
|------|------|------|
| `mac` | URL | MAC 地址或设备 key |

```json
{
  "code": 0,
  "message": "Device entered standby",
  "data": {
    "device_id": "AA:BB:CC:DD:EE:01"
  }
}
```

---

### 1.8 停止所有设备

```
POST /api/v1/devices/stop/all
```

```json
{
  "code": 0,
  "message": "Stopped 2 devices",
  "data": {
    "count": 2,
    "devices": ["AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02"]
  }
}
```

---

### 1.9 获取设备统计

```
GET /api/v1/devices/{mac}/stats
```

或

```
POST /api/v1/devices/{mac}/stats
```

| 参数 | 位置 | 说明 |
|------|------|------|
| `mac` | URL | MAC 地址或设备 key |

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "mac": "AA:BB:CC:DD:EE:01",
    "device_key": "device_key_001",
    "uptime": 3600.5,
    "messages_count": 15,
    "conversations_count": 8,
    "last_activity": 1699999999.0,
    "last_speak_time": 1699999980.0,
    "last_wakeup_time": 1699999900.0
  }
}
```

---

### 1.10 获取设备对话历史

```
GET /api/v1/devices/{mac}/history?limit=20
```

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `mac` | URL | string | MAC 地址或设备 key |
| `limit` | Query | int | 返回条数，默认 20，范围 1–100 |

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "mac": "AA:BB:CC:DD:EE:01",
    "messages": [
      {
        "role": "user",
        "content": "今天天气怎么样？",
        "timestamp": 1699999900.0
      },
      {
        "role": "assistant",
        "content": "今天天气晴朗，温度20度。",
        "timestamp": 1699999910.0
      }
    ],
    "count": 2
  }
}
```

---

### 1.11 清空设备对话历史

```
POST /api/v1/devices/{mac}/history
```

| 参数 | 位置 | 说明 |
|------|------|------|
| `mac` | URL | MAC 地址或设备 key |

```json
{
  "code": 0,
  "message": "History cleared",
  "data": {
    "mac": "AA:BB:CC:DD:EE:01"
  }
}
```

---

### 1.12 获取设备音量

```
GET /api/v1/devices/{mac}/volume
```

| 参数 | 位置 | 说明 |
|------|------|------|
| `mac` | URL | MAC 地址或设备 key |

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "mac": "AA:BB:CC:DD:EE:01",
    "volume": 0.8
  }
}
```

---

### 1.13 设置设备音量

```
POST /api/v1/devices/{mac}/volume
Content-Type: application/json
```

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `mac` | URL | string | MAC 地址或设备 key |
| `volume` | Body | float | 音量值，范围 0.0–1.0 |

**请求体：**

```json
{
  "volume": 0.8
}
```

```json
{
  "code": 0,
  "message": "Volume set",
  "data": {
    "mac": "AA:BB:CC:DD:EE:01",
    "volume": 0.8
  }
}
```

---

### 1.14 获取设备配置

```
GET /api/v1/devices/{mac}/config
```

| 参数 | 位置 | 说明 |
|------|------|------|
| `mac` | URL | MAC 地址或设备 key |

**响应：** 返回 `users.json` 中该设备的完整原始配置。

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "mac": "AA:BB:CC:DD:EE:01",
    "device_key": "device_key_001",
    "name": "客厅设备",
    "key": "123",
    "asr_provider": "volcengine",
    "asr_config": {
      "volcengine": {
        "api_key": "****",
        "resource_id": "volc.bigasr.sauc.duration",
        "model": "bigmodel"
      }
    },
    "llm_type": "openai",
    "llm": {
      "api_key": "****",
      "base_url": "https://api.deepseek.com/v1",
      "model": "deepseek-v4-flash",
      "system_prompt": "你的名字叫小欢...",
      "memory_enabled": true,
      "memory_max_messages": 20
    },
    "tts_type": "volcengine",
    "tts_config": {
      "api_key": "****",
      "resource_id": "seed-tts-1.0",
      "voice_type": "zh_female_wanwanxiaohe_moon_bigtts",
      "speed_ratio": 1.0,
      "volume_ratio": 1.0,
      "pitch_ratio": 1.0,
      "volume": 2.0
    },
    "music": {
      "api_url": "http://192.168.1.100:2233",
      "lyrics_offset": 400
    },
    "mcp_servers": {},
    "rate_limit_rpm": 60,
    "disabled_tools": []
  }
}
```

---

### 1.15 更新设备配置

```
POST /api/v1/devices/{mac}/config
```

| 参数 | 位置 | 说明 |
|------|------|------|
| `mac` | URL | MAC 地址或设备 key |
| Body | JSON | 要更新的字段（可选，只传需要改的） |

**请求体字段（全部可选）：**

| 字段 | 类型 | 映射路径 | 说明 |
|------|------|---------|------|
| `name` | string | `name` | 设备名称 |
| `key` | string | `key` | 设备密钥 |
| `asr_provider` | string | `asr_provider` | ASR 提供商 |
| `llm_type` | string | `llm_type` | LLM 类型 |
| `tts_type` | string | `tts_type` | TTS 类型 |
| `rate_limit_rpm` | int | `rate_limit_rpm` | 每分钟限流数 |
| `disabled_tools` | array | `disabled_tools` | 禁用的工具列表 |
| `llm_api_key` | string | `llm.api_key` | LLM API Key |
| `llm_base_url` | string | `llm.base_url` | LLM 接口地址 |
| `llm_model` | string | `llm.model` | LLM 模型名 |
| `llm_system_prompt` | string | `llm.system_prompt` | 系统提示词 |
| `memory_enabled` | bool | `llm.memory_enabled` | 是否开启记忆 |
| `memory_max_messages` | int | `llm.memory_max_messages` | 最大记忆条数 |
| `tts_api_key` | string | `tts_config.api_key` | TTS API Key |
| `tts_resource_id` | string | `tts_config.resource_id` | TTS 资源 ID |
| `voice_type` | string | `tts_config.voice_type` | TTS 音色 |
| `speed_ratio` | float | `tts_config.speed_ratio` | 语速比 |
| `volume_ratio` | float | `tts_config.volume_ratio` | 音量比 |
| `pitch_ratio` | float | `tts_config.pitch_ratio` | 音调比 |
| `tts_volume` | float | `tts_config.volume` | TTS 音量 |
| `asr_api_key` | string | `asr_config.volcengine.api_key` | ASR API Key |
| `asr_resource_id` | string | `asr_config.volcengine.resource_id` | ASR 资源 ID |
| `asr_model` | string | `asr_config.volcengine.model` | ASR 模型名 |
| `music_api_url` | string | `music.api_url` | 音乐服务地址 |
| `music_lyrics_offset` | int | `music.lyrics_offset` | 歌词偏移量(ms) |
| `wakeup_text` | string | `wakeup.text` | 唤醒提示文字 |
| `wakeup_enabled` | bool | `wakeup.enabled` | 是否播放唤醒音 |
| `wakeup_cache_enabled` | bool | `wakeup.cache_enabled` | 是否缓存唤醒音频 |
| `wakeup_play_enabled` | bool | `wakeup.play_enabled` | 是否等待播放完成 |
| `wakeup_source` | string | `wakeup.source` | 音频来源（`file` / `tts`） |
| `tts_config` | dict | `tts_config` | **整体替换** TTS 配置块 |
| `asr_config` | dict | `asr_config` | **整体替换** ASR 配置块 |
| `music` | dict | `music` | **整体替换** music 配置块 |
| `mcp_servers` | dict | `mcp_servers` | **整体替换** MCP 服务器配置 |

> **⚠️ 不要传 `\"llm\": {...}` 整体替换！** `llm` 已被禁用为整体替换字段，必须通过 `llm_api_key`、`llm_model`、`llm_system_prompt` 等独立字段逐个修改。
> 同理 `name`、`key`、`asr_provider` 等顶层字段直接传同名 field 即可，不要像 `{\"name\": {...}}` 这样嵌套。

---

**示例 1 — 修改 LLM 的 system_prompt（推荐方式）：**

```bash
curl -X POST -H "X-API-Key: admin123" \
  -H "Content-Type: application/json" \
  -d '{"llm_system_prompt": "你的名字叫小欢，是一个智能语音助手"}' \
  http://localhost:8088/api/v1/devices/AA:BB:CC:DD:EE:01/config
```

✅ **正确**：只改 `llm.system_prompt`，`api_key`、`model` 等不受影响

---

**示例 2 — 同时修改多个 LLM 字段：**

```bash
curl -X POST -H "X-API-Key: admin123" \
  -H "Content-Type: application/json" \
  -d '{
    "llm_model": "deepseek-v4-pro",
    "llm_system_prompt": "你是小欢",
    "memory_max_messages": 30
  }' \
  http://localhost:8088/api/v1/devices/AA:BB:CC:DD:EE:01/config
```

---

**示例 3 — 修改唤醒音频配置：**

```bash
curl -X POST -H "X-API-Key: admin123" \
  -H "Content-Type: application/json" \
  -d '{
    "wakeup_text": "你好呀",
    "wakeup_source": "tts"
  }' \
  http://localhost:8088/api/v1/devices/AA:BB:CC:DD:EE:01/config
```

---

**示例 4 — 修改 TTS 音色和语速：**

```bash
curl -X POST -H "X-API-Key: admin123" \
  -H "Content-Type: application/json" \
  -d '{"voice_type": "zh_female_new", "speed_ratio": 1.2}' \
  http://localhost:8088/api/v1/devices/AA:BB:CC:DD:EE:01/config
```

---

**示例 5 — 整体替换 MCP 服务器：**

```bash
curl -X POST -H "X-API-Key: admin123" \
  -H "Content-Type: application/json" \
  -d '{"mcp_servers": {"new-tool": {"type": "stdio", "command": "npx", "args": ["-y", "server-package"]}}}' \
  http://localhost:8088/api/v1/devices/AA:BB:CC:DD:EE:01/config
```

---

**示例 6 — 整体替换 music 配置：**

```bash
curl -X POST -H "X-API-Key: admin123" \
  -H "Content-Type: application/json" \
  -d '{"music": {"api_url": "http://192.168.1.200:2233", "lyrics_offset": 500}}' \
  http://localhost:8088/api/v1/devices/AA:BB:CC:DD:EE:01/config
```

---

**补充说明：字段更新的优先级规则**

| 传参方式 | 行为 | 适用场景 |
|---------|------|---------|
| 独立字段如 `llm_api_key` | 只修改 `llm.api_key`，不影响同层其他字段 | ✅ 日常修改 |
| 整体替换如 `tts_config` | 整个替换 `tts_config` 对象 | ⚠️ 需要全量替换时 |
| 不传的字段 | 保持原值，不做任何修改 | — |

**响应：**

```json
{
  "code": 0,
  "message": "Config updated",
  "data": {
    "mac": "AA:BB:CC:DD:EE:01",
    "config": {
      "voice_type": "zh_female_new",
      "rate_limit_rpm": 120
    }
  }
}
```

> 更新后系统会自动重载认证配置，更新在线设备的内存配置对象（`session.user_config`、`tool_manager.user_config`），并对在线设备推送必要的运行时变更（如 `llm_system_prompt`、`voice_type`）。

---

### 1.16 推送 OTA 固件升级到指定设备

```
POST /api/v1/devices/{mac}/ota
```

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `mac` | URL | string | MAC 地址或设备 key |
| Body | JSON | object | 可选。`url`、`version`、`bin_id`、`is_official` |

```json
{
  "code": 0,
  "message": "OTA pushed",
  "data": {
    "success": true,
    "device_key": "device_key_001",
    "method": "pending_ota"
  }
}
```

---

### 1.17 强制 OTA 升级（忽略版本检查）

```
POST /api/v1/devices/{mac}/ota/force
```

参数同上。

---

### 1.18 广播 OTA 到所有设备

```
POST /api/v1/devices/ota/all
```

可选 Body：`{"url": "...", "version": "..."}`

---

### 1.19 设置设备 WiFi

```
POST /api/v1/devices/{mac}/wifi
```

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `mac` | URL | string | MAC 地址或设备 key |
| Body | JSON | object | `{"ssid": "WiFi名", "password": "密码"}` |

---

### 1.20 设置麦克风引脚

```
POST /api/v1/devices/{mac}/pins/mic
```

Body：`{"pin": 4}`

---

### 1.21 设置扬声器引脚

```
POST /api/v1/devices/{mac}/pins/speaker
```

Body：`{"pin": 5}`

---

## 二、固件管理 API（`/api/v1/firmware`）

### 2.1 上传固件

```
POST /api/v1/firmware/upload
```

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `file` | FormData | file | 固件 `.bin` 文件 |

```json
{
  "code": 0,
  "message": "Firmware uploaded",
  "data": {
    "filename": "firmware_v1.2.bin",
    "size": 1048576,
    "version": "1.2",
    "upload_time": 1699999999.0
  }
}
```

---

### 2.2 获取固件列表

```
GET /api/v1/firmware
```

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "count": 3,
    "firmwares": [
      {
        "filename": "firmware_v1.2.bin",
        "size": 1048576,
        "version": "1.2",
        "is_default": true,
        "upload_time": 1699999999.0
      }
    ]
  }
}
```

---

### 2.3 获取固件信息

```
GET /api/v1/firmware/{filename}
```

| 参数 | 位置 | 说明 |
|------|------|------|
| `filename` | URL | 固件文件名 |

---

### 2.4 删除固件

```
POST /api/v1/firmware/{filename}
```

| 参数 | 位置 | 说明 |
|------|------|------|
| `filename` | URL | 固件文件名 |

---

### 2.5 设置默认固件

```
POST /api/v1/firmware/default?filename=firmware_v1.2.bin
```

| 参数 | 位置 | 说明 |
|------|------|------|
| `filename` | Query | 固件文件名 |

---

## 三、技能与工具 API（`/api/v1`）

### 3.1 获取可用技能列表

```
GET /api/v1/skills?device_id=xxx
```

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `device_id` | Query | string | 可选。按设备过滤技能，不传则返回所有技能 |

**响应示例：**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "count": 3,
    "skills": [
      {
        "id": "weather",
        "description": "查询天气信息",
        "category": "tool",
        "tags": ["weather", "query"],
        "device_id": null
      },
      {
        "id": "music",
        "description": "播放音乐",
        "category": "entertainment",
        "tags": ["music", "play"],
        "device_id": "device_key_001"
      }
    ]
  }
}
```

---

### 3.2 获取可用工具列表

```
GET /api/v1/tools
```

**响应示例：**

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "type": "global",
      "name": "get_weather",
      "description": "获取指定城市的天气信息",
      "parameters": { ... }
    },
    {
      "type": "device",
      "name": "play_music",
      "description": "播放音乐",
      "parameters": { ... }
    }
  ]
}
```

---

### 3.3 创建技能

```
POST /api/v1/skills
Content-Type: application/json
```

**请求体：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 技能 ID，只能用小写字母、数字、下划线，且以字母开头 |
| `description` | string | 是 | 技能描述，同时作为激活条件（描述哪些用户意图触发此技能） |
| `instructions` | string | 是 | 给 LLM 的执行指令，自然语言步骤 |
| `category` | string[] | 否 | 分类，如 `["utility"]`、`["entertainment"]` |
| `tags` | string[] | 否 | 标签数组 |
| `cap_groups` | string[] | 否 | 需要的工具组，如 `["tools:get_current_time"]` |

**请求示例：**

```json
{
  "name": "weather_query",
  "description": "查询天气。用户问天气、温度、是否下雨时激活",
  "instructions": "1. 获取用户所在城市\n2. 调用天气工具查询\n3. 用简洁友好的语气回复",
  "category": ["utility"],
  "tags": ["weather", "query"],
  "cap_groups": ["tools:get_weather"]
}
```

**响应示例：**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "id": "weather_query",
    "description": "查询天气。用户问天气、温度、是否下雨时激活",
    "category": ["utility"],
    "tags": ["weather", "query"],
    "file_path": "/path/to/src/skills/weather_query/SKILL.md"
  }
}
```

> 创建后系统自动生成标准 `SKILL.md` 文件并注册到内存，无需重启服务。

---

### 3.4 删除技能

```
DELETE /api/v1/skills/{skill_id}
```

| 参数 | 位置 | 说明 |
|------|------|------|
| `skill_id` | URL | 技能 ID |

**响应示例：**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "deleted": "weather_query"
  }
}
```

---

### 3.5 重新加载技能

```
POST /api/v1/skills/reload
```

重新扫描技能目录并热更新内存中的技能列表，无需重启服务。

**响应示例：**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "count": 5
  }
}
```

---

## 四、表情管理 API（`/api/v1/emos`）

### 4.1 获取默认表情列表

```
GET /api/v1/emos
```

返回 `src/emos/default/` 目录下的通用表情。

### 4.2 获取设备专属表情列表

```
GET /api/v1/emos/{device_id}
```

**参数：**

| 参数 | 位置 | 说明 |
|------|------|------|
| `device_id` | URL | 设备 MAC 地址或 device_id |

**逻辑：**
1. 服务端将 `device_id` 解析为设备 `key`（如 `"123"`）
2. 查找 `src/emos/{key}/` 目录，存在则返回专用表情
3. 不存在则自动从 `src/emos/default/` 复制创建，并返回新目录的内容

**响应示例：**

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "name": "happy",
      "filename": "happy.gif",
      "size": 46807,
      "url": "http://192.168.31.176:8088/emos/123/happy.gif"
    }
  ]
}
```

### 4.3 上传表情

```
POST /api/v1/emos/upload
Content-Type: multipart/form-data
```

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `file` | FormData | file | GIF 文件（仅支持 .gif） |
| `device_key` | Query | string | 可选。不传则上传到 `default/`（通用）；传则上传到对应设备目录 |

**文件名即表情名**，例如上传 `happy.gif` 对应快乐、`sad.gif` 对应伤心。映射关系见设备端 `gif_files[]` 数组。

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "name": "happy",
    "filename": "happy.gif",
    "size": 46807,
    "device_key": "default"
  }
}
```

**给指定设备上传：**

```bash
# 上传到 key=123 的设备专用目录
curl -X POST -F "file=@happy.gif" "http://localhost:8088/api/v1/emos/upload?device_key=123"
```

> 首次调用设备专属 API 时会自动创建设备目录并复制 default 内容，无需手动操作。更换设备表情只需替换对应目录下的文件。

---

## 五、系统管理 API（`/api/v1/system`）

### 5.1 获取系统信息

```
GET /api/v1/system/info
```

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "version": "3.0.0-clean-arch",
    "architecture": "Clean Architecture",
    "uptime": 1699999999.0,
    "server": {
      "host": "0.0.0.0",
      "port": 8088,
      "workers": 1
    },
    "devices": {
      "online": 3
    },
    "features": {
      "auth_enabled": true,
      "remote_config_enabled": false,
      "mcp_enabled": true
    }
  }
}
```

---

### 5.2 获取系统配置（脱敏）

```
GET /api/v1/system/config
```

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "server": { "host": "0.0.0.0", "port": 8088 },
    "asr": {
      "provider": "volcengine",
      "no_speech_timeout": 5,
      "silence_timeout": 2,
      "enable_pool": true
    },
    "llm": {
      "provider": "openai",
      "model": "gpt-4",
      "base_url": "https://api.openai.com",
      "temperature": 0.7,
      "memory_enabled": true
    },
    "tts": {
      "provider": "volcengine",
      "voice_type": "BV700",
      "speed_ratio": 1.0,
      "enable_pool": true
    },
    "wakeup": {
      "enable_audio": true,
      "text": "我在呢..."
    }
  }
}
```

---

### 5.3 获取网关状态

```
GET /api/v1/system/gateways
```

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "asr": {
      "enabled": true,
      "provider": "VolcEngineASRGateway"
    },
    "llm": {
      "enabled": true,
      "provider": "OpenAIGateway"
    },
    "tts": {
      "enabled": true,
      "provider": "VolcEngineTTSGateway"
    }
  }
}
```

---

### 5.4 重新加载配置

```
POST /api/v1/system/reload
```

```json
{
  "code": 0,
  "message": "Config reloaded",
  "data": {
    "timestamp": 1699999999.0
  }
}
```

---

### 5.5 获取性能指标

```
GET /api/v1/system/metrics
```

返回设备统计、连接池统计、并发控制状态、CPU/内存使用等。

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "devices": { ... },
    "pools": { ... },
    "concurrency": { ... },
    "system": {
      "cpu_percent": 12.5,
      "memory_mb": 256.3,
      "memory_percent": 3.2,
      "num_threads": 48
    },
    "uptime": 1699999999.0
  }
}
```

---

## 六、SDK API（`/api/v1/sdk`）

### 6.1 SDK 查询新固件

```
GET /api/v1/sdk/query_new_ota?mac=AA:BB:CC:DD:EE:01&version=1.0
```

| 参数 | 位置 | 说明 |
|------|------|------|
| `mac` | Query | 设备 MAC |
| `version` | Query | 当前固件版本 |

```json
{
  "success": true,
  "data": {
    "latest": false,
    "bin_url": "http://.../firmware_v1.2.bin"
  }
}
```

---

## 七、健康/监控端点（`/health`、`/metrics`、`/stats`）

### 7.1 存活检查

```
GET /health/live
```

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "status": "alive"
  }
}
```

### 7.2 就绪检查

```
GET /health/ready
```

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "status": "ready",
    "components": ["llm_gateway", "tts_gateway"]
  }
}
```

### 7.3 Prometheus 指标

```
GET /metrics
```

返回 Prometheus 格式的监控指标数据。

### 7.4 服务器统计

```
GET /stats
```

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "server": {"version": "3.0.0-clean-arch", "architecture": "Clean Architecture"},
    "sessions": {"active": 0},
    "devices": {"total": 0, "online": 0},
    "gateways": {"asr": true, "llm": true, "tts": true},
    "timestamp": 1699999999.0
  }
}
```

---

## 八、简化版 API（`/api/`）

以下端点由 `src/infrastructure/web.py` 注册，功能与 `v1` 版相同，但不带版本前缀。新旧可混用。

### 设备

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/devices` | 获取所有在线设备 |
| `GET` | `/api/devices/{device_id}` | 获取指定设备详情 |
| `GET` | `/api/health` | API 健康检查 |

### 控制（参数通过 JSON Body 传）

| 方法 | 路径 | Body | 说明 |
|------|------|------|------|
| `POST` | `/api/wakeup` | `{"device_id": "..."}` | 唤醒设备 |
| `POST` | `/api/wakeup/all` | — | 唤醒所有 |
| `POST` | `/api/speak` | `{"device_id": "...", "text": "..."}` | 说话 |
| `POST` | `/api/speak/all` | `{"text": "..."}` | 广播说话 |
| `POST` | `/api/stop` | `{"device_id": "..."}` | 停止 |
| `POST` | `/api/stop/all` | — | 停止所有 |

---

## 九、旧架构 API（`app/api/routes.py`）

以下端点由旧架构 `app/` 提供，通过 `app/main.py` 启动时可用。

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/devices` | 设备列表 |
| `GET` | `/api/devices/{device_id}` | 设备详情 |
| `POST` | `/api/wakeup` | 唤醒（Body: `{"device_id":"..."}`） |
| `POST` | `/api/wakeup/all` | 唤醒所有 |
| `POST` | `/api/speak` | 说话（Body: `{"device_id":"...","text":"..."}`） |
| `POST` | `/api/speak/all` | 广播说话（Body: `{"text":"..."}`） |
| `POST` | `/api/stop` | 停止（Body: `{"device_id":"..."}`） |
| `POST` | `/api/stop/all` | 停止所有 |
| `POST` | `/api/display-image` | 发送图片（Form: `device_id` + `file`） |
| `POST` | `/api/clear-image` | 清除图片（Form: `device_id`） |
| `GET` | `/api/devices/{device_id}/config` | 获取设备配置 |
| `POST` | `/api/devices/{device_id}/config` | 更新设备配置 |

---

## 设备状态说明

| 状态 | 说明 |
|------|------|
| `IDLE` | 待机 |
| `ASR` | 语音识别中 |
| `LLM` | 调用大模型中 |
| `TTS` | 语音合成中 |
| `unknown` | 未知 |

---

## 完整 API 速查表

### `/api/v1/` 路由组（主力 API）

| 方法 | 路径 | 功能 |
|------|------|------|
| `GET` | `/api/v1/devices` | 获取所有在线设备 |
| `GET` | `/api/v1/devices/{mac}` | 获取指定设备信息 |
| `POST` | `/api/v1/devices/{mac}/speak` | 让指定设备说话 |
| `POST` | `/api/v1/devices/speak/all` | 广播说话 |
| `POST` | `/api/v1/devices/{mac}/wakeup` | 唤醒指定设备 |
| `POST` | `/api/v1/devices/wakeup/all` | 广播唤醒 |
| `POST` | `/api/v1/devices/{mac}/stop` | 停止指定设备 |
| `POST` | `/api/v1/devices/stop/all` | 停止所有设备 |
| `GET` / `POST` | `/api/v1/devices/{mac}/stats` | 获取设备统计 |
| `GET` | `/api/v1/devices/{mac}/history` | 获取对话历史 |
| `POST` | `/api/v1/devices/{mac}/history` | 清空对话历史 |
| `GET` | `/api/v1/devices/{mac}/config` | 获取设备配置 |
| `POST` | `/api/v1/devices/{mac}/config` | 更新设备配置 |
| `GET` | `/api/v1/devices/{mac}/volume` | 获取音量 |
| `POST` | `/api/v1/devices/{mac}/volume` | 设置音量 |
| `POST` | `/api/v1/devices/{mac}/ota` | 推送 OTA 升级 |
| `POST` | `/api/v1/devices/{mac}/ota/force` | 强制 OTA 升级 |
| `POST` | `/api/v1/devices/ota/all` | 广播 OTA 升级 |
| `POST` | `/api/v1/devices/{mac}/wifi` | 设置设备 WiFi |
| `POST` | `/api/v1/devices/{mac}/pins/mic` | 设置麦克风引脚 |
| `POST` | `/api/v1/devices/{mac}/pins/speaker` | 设置扬声器引脚 |
| `POST` | `/api/v1/firmware/upload` | 上传固件 |
| `GET` | `/api/v1/firmware` | 获取固件列表 |
| `GET` | `/api/v1/firmware/{filename}` | 获取固件信息 |
| `POST` | `/api/v1/firmware/{filename}` | 删除固件 |
| `POST` | `/api/v1/firmware/default` | 设置默认固件 |
| `GET` | `/api/v1/skills` | 获取可用技能列表 |
| `POST` | `/api/v1/skills` | 创建技能 |
| `DELETE` | `/api/v1/skills/{skill_id}` | 删除技能 |
| `POST` | `/api/v1/skills/reload` | 重新加载技能 |
| `GET` | `/api/v1/tools` | 获取可用工具列表 |
| `GET` | `/api/v1/system/info` | 获取系统信息 |
| `GET` | `/api/v1/system/config` | 获取系统配置(脱敏) |
| `GET` | `/api/v1/system/gateways` | 获取网关状态 |
| `POST` | `/api/v1/system/reload` | 重新加载配置 |
| `GET` | `/api/v1/system/metrics` | 获取性能指标 |
| `GET` | `/api/v1/sdk/query_new_ota` | SDK 查询新固件 |

### 基础路径路由

| 方法 | 路径 | 功能 |
|------|------|------|
| `GET` | `/health/live` | 存活检查 |
| `GET` | `/health/ready` | 就绪检查 |
| `GET` | `/metrics` | Prometheus 指标 |
| `GET` | `/stats` | 服务器统计 |
| `ws` | `/` | WebSocket 连接 |
| `ws` | `/connect_espai_node` | WebSocket 连接 |

### WebSocket

```
ws://<server>:8088?key=<设备密钥>
ws://<server>:8088/connect_espai_node?key=<设备密钥>
```

---

## 使用示例

### Python

```python
import requests

API_KEY = "admin123"
BASE_URL = "http://localhost:8088"
headers = {"X-API-Key": API_KEY}

# 获取设备列表
resp = requests.get(f"{BASE_URL}/api/v1/devices", headers=headers)
devices = resp.json()["data"]["devices"]

# 让设备说话（JSON Body）
mac = devices[0]["mac"]
requests.post(
    f"{BASE_URL}/api/v1/devices/{mac}/speak",
    headers=headers,
    json={"text": "你好！"}
)

# 更新设备配置
requests.post(
    f"{BASE_URL}/api/v1/devices/{mac}/config",
    headers=headers,
    json={"voice_type": "zh_female_new", "rate_limit_rpm": 120}
)

# 设置音量（JSON Body）
requests.post(
    f"{BASE_URL}/api/v1/devices/{mac}/volume",
    headers=headers,
    json={"volume": 0.8}
)
```

### JavaScript

```javascript
const API_KEY = "admin123";
const BASE_URL = "http://localhost:8088";
const headers = { "X-API-Key": API_KEY, "Content-Type": "application/json" };

// 获取设备列表
const res = await fetch(`${BASE_URL}/api/v1/devices`, { headers });
const { data: { devices } } = await res.json();

// 让设备说话（JSON Body）
await fetch(
  `${BASE_URL}/api/v1/devices/${devices[0].mac}/speak`,
  { method: "POST", headers, body: JSON.stringify({ text: "你好" }) }
);

// 更新配置
await fetch(
  `${BASE_URL}/api/v1/devices/${devices[0].mac}/config`,
  { method: "POST", headers, body: JSON.stringify({ voice_type: "zh_female_new" }) }
);
```

---

> **文档版本**: v2.0 · 最后更新: 2025-01 · 与实际代码 `src/infrastructure/device_api.py` + `src/infrastructure/web.py` 保持一致
