# API 文档

## 基础信息

| 项目 | 值 |
|------|-----|
| Base URL | `http://<server-ip>:8088` |
| API 前缀 | `/api/v1` |
| 数据格式 | JSON |
| WebSocket | 详见 [WebSocket 通信协议](/dev/server/ws) |

## 鉴权

新版服务端使用 **JWT 用户认证**，取代了旧版的 `AUTH_API_KEY` / `ADMIN_API_KEY` 双密钥模型。

- **用户接口**：通过 `Authorization: Bearer <JWT>` Header 鉴权
- **WebSocket 设备连接**：设备无需携带密钥，未绑定设备自动进入绑定模式
- **白名单接口**：`/api/health`、`/api/v1/auth/*`、SDK 接口

```bash
curl -H "Authorization: Bearer <your-jwt-token>" http://localhost:8088/api/v1/devices
```

## 响应格式

```json
// 成功
{"code": 0, "message": "ok", "data": {...}}
// 失败
{"code": 1, "message": "错误描述", "data": null}
```

### HTTP 状态码

| 状态码 | 说明 |
|--------|------|
| `200` | 请求成功（业务逻辑错误也返回 200，通过 `code` 字段区分）|
| `401` | 未提供 JWT Token，或 Token 无效 / 已过期 |
| `422` | 请求参数校验失败 |

## 用户认证（无需 JWT）

### 注册

**POST** `/api/v1/auth/register`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `email` | string | 是 | 邮箱或手机号（唯一标识）|
| `password` | string | 是 | 密码（至少 6 位）|
| `nickname` | string | 否 | 昵称 |

```bash
curl -X POST http://localhost:8088/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "123456", "nickname": "我的设备"}'
```

```json
// 成功
{"code": 0, "message": "ok", "data": {"user_id": "uuid-xxx"}}
```

### 登录

**POST** `/api/v1/auth/login`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `email` | string | 是 | 注册时使用的邮箱/手机号 |
| `password` | string | 是 | 密码 |

```bash
curl -X POST http://localhost:8088/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "123456"}'
```

```json
// 成功
{"code": 0, "message": "ok", "data": {
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "user_id": "uuid-xxx",
  "email": "user@example.com",
  "nickname": "我的昵称"
}}
```

## 健康检查与监控（无需鉴权）

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/health/live` | GET | 存活检查 |
| `/health/ready` | GET | 就绪检查 |
| `/stats` | GET | 服务统计概览 |
| `/metrics` | GET | Prometheus 指标 |

## 设备管理（`/api/v1` 需 JWT）

### 获取设备列表

**GET** `/api/v1/devices`

获取当前用户的设备列表。

```bash
curl -H "Authorization: Bearer <token>" http://localhost:8088/api/v1/devices
```

```json
{"code": 0, "data": {
  "devices": [
    {
      "device_id": "5d47bb925ea440b3b",
      "mac": "5d47bb925ea440b3b",
      "name": "欢哥的设备",
      "device_key": "bound_xxxxxxxxxxxxxxxx",
      "online": true,
      "bound_at": 1720000000.0
    }
  ]
}}
```

### 绑定设备

**POST** `/api/v1/bind`

通过绑定码绑定设备到当前用户（无需知道 device_id）。设备首次连接时会生成 6 位绑定码显示在屏幕，用户需在 App 或 Web 中输入该码完成绑定。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `bind_code` | string | 是 | 设备屏幕显示的 6 位绑定码 |
| `name` | string | 否 | 设备名称（不填则为空）|

```bash
curl -X POST http://localhost:8088/api/v1/bind \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"bind_code": "3IW5N9", "name": "客厅设备"}'
```

```json
// 成功（device_id 返回在顶层，不在 data 内）
{"code": 0, "message": "Device bound successfully", "device_id": "5d47bb925ea440b3b"}
// 绑定码已过期
{"code": 1, "message": "Bind code expired", "data": null}
```

### 解绑设备

**POST** `/api/v1/devices/{mac}/unbind`

解绑设备（仅解除与当前用户的绑定关系，不清空设备配置）。如果设备在线，会立即发送重置指令。

```bash
curl -X POST http://localhost:8088/api/v1/devices/5d47bb925ea440b3b/unbind \
  -H "Authorization: Bearer <token>"
```

```json
{"code": 0, "message": "Device unbound"}
```


**POST** `/api/v1/devices`

直接创建并绑定设备到当前用户（适用于用户已知设备配置的场景）。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `mac` | string | 是 | 设备 MAC 地址 |
| `key` | string | 是 | 设备连接密钥（WebSocket `?key=` 参数）|
| `name` | string | 是 | 设备显示名称 |
| `asr_provider` | string | 否 | ASR 厂商 |
| `llm_api_key` | string | 否 | LLM API Key |
| `llm_base_url` | string | 否 | LLM Base URL |
| `llm_model` | string | 否 | LLM 模型名 |
| `llm_system_prompt` | string | 否 | LLM 系统提示词 |
| `tts_voice_type` | string | 否 | TTS 音色 ID |

```bash
curl -X POST http://localhost:8088/api/v1/devices \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"mac": "5d47bb925ea440b3b", "key": "设备连接key", "name": "我的设备", "llm_api_key": "sk-xxx", "llm_model": "deepseek-v4-flash"}'
```

```json
{"code": 0, "message": "ok", "data": {"device_id": "5d47bb925ea440b3b", "name": "我的设备"}}
```

### 获取设备详情

**GET** `/api/v1/devices/{device_id}`

路径参数 `device_id`（可传 MAC / device_key / device_id）。响应 `data` 字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `device_id` | string | 设备 MAC |
| `name` | string | 设备名（可能为空串）|
| `connected` | bool | 是否在线 |
| `state` | string | 会话状态（如 `idle`）|
| `session_id` | string | 当前会话 ID |
| `tts_playing` | bool | 是否正在播放 TTS |

```bash
curl -H "Authorization: Bearer <token>" http://localhost:8088/api/v1/devices/5d47bb925ea440b3b
```

### 获取设备状态

**GET** `/api/v1/devices/{mac}/stats`

无请求体。响应 `data` 字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `mac` | string | 设备 MAC |
| `device_key` | string | 解析后的设备密钥 |
| `uptime` | number | 会话运行秒数 |
| `messages_count` | int | 会话消息数 |
| `conversations_count` | int | 会话轮数 |
| `last_activity` | number/null | 最近活跃时间戳 |
| `last_speak_time` | number/null | 最近播报时间戳 |
| `last_wakeup_time` | number/null | 最近唤醒时间戳 |

### 设备控制

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/speak` | POST | 让设备播放 TTS |
| `/api/v1/wakeup` | POST | 唤醒设备 |
| `/api/v1/stop` | POST | 设备进入待机 |
| `/api/v1/speak/all` | POST | 向所有设备播报 |
| `/api/v1/wakeup/all` | POST | 唤醒所有设备 |
| `/api/v1/stop/all` | POST | 所有设备进入待机 |
| `/api/v1/devices/{mac}/speak` | POST | 兼容路由：让设备播放 TTS |
| `/api/v1/devices/{mac}/wakeup` | POST | 兼容路由：唤醒设备 |

请求体（JSON）：

| 接口 | 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| `/speak` | `device_id` | string | 是 | 设备标识 |
| `/speak` | `text` | string | 是 | 播报文本（≤500 字）|
| `/wakeup` | `device_id` | string | 是 | 设备标识 |
| `/stop` | `device_id` | string | 是 | 设备标识 |
| `/speak/all` | `text` | string | 是 | 播报文本（≤500 字）|

```bash
curl -X POST http://localhost:8088/api/v1/speak \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"device_id": "5d47bb925ea440b3b", "text": "你好，我是小明同学"}'
```

### 设备配置

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/devices/{mac}/config` | GET | 获取设备配置 |
| `/api/v1/devices/{mac}/config` | POST | 更新设备配置（热重载）|
| `/api/v1/devices/{mac}/volume` | GET | 获取音量 |
| `/api/v1/devices/{mac}/volume` | POST | 设置音量（body：`{"volume": 0.8}`，范围 0.0~1.0）|

#### POST /api/v1/devices/{mac}/config 参数

所有字段可选，仅更新传入字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 设备名称 |
| `asr_provider` | string | ASR 厂商 |
| `llm_api_key` | string | LLM API Key |
| `llm_base_url` | string | LLM Base URL |
| `llm_model` | string | LLM 模型名 |
| `llm_system_prompt` | string | LLM 系统提示词 |
| `voice_type` | string | TTS 音色 ID |
| `asr_config` | object | ASR 配置（含 api_key/resource_id）|
| `tts_config` | object | TTS 配置（含 api_key/voice_type）|
| `music` | object | 音乐服务配置：`api_url`, `lyrics_offset` |
| `wakeup` | object | 唤醒配置：`text`, `enabled`, `source`, `play_on_next_round` |
| `ota` | object | OTA 设备级配置（通过设备 OTA 接口配置，见下方 OTA 升级章节）|

```bash
curl -X POST http://localhost:8088/api/v1/devices/5d47bb925ea440b3b/config \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"llm_api_key": "sk-xxx", "llm_model": "deepseek-v4-flash"}'
```

设置音量示例：

```bash
curl -X POST http://localhost:8088/api/v1/devices/5d47bb925ea440b3b/volume \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"volume": 0.8}'
```

### OTA 升级

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/devices/{mac}/ota` | POST | 推送 OTA 升级（带版本检查）|
| `/api/v1/devices/{mac}/ota/force` | POST | 强制 OTA 升级（跳过版本检查）|
| `/api/v1/devices/ota/all` | POST | 批量推送 OTA |
| `/api/v1/devices/{mac}/ota/status` | GET | 查询升级状态 |
| `/api/v1/devices/{mac}/ota/reset` | POST | 重置升级状态 |

请求体（JSON，可省略；缺省自动回退：设备配置 → 全局配置 → 本地已上传固件）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `url` | string | 否 | 固件下载 URL |
| `version` | string | 否 | 固件版本号 |
| `bin_id` | string | 否 | 固件 bin ID |
| `is_official` | string | 否 | 是否官方版本（`"0"` / `"1"`）|

```bash
curl -X POST http://localhost:8088/api/v1/devices/5d47bb925ea440b3b/ota \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"url": "http://192.168.1.100:8088/firmware/1.0.bin", "version": "1.0.0", "bin_id": "abc123"}'
```

### 远程 WiFi

**POST** `/api/v1/devices/{mac}/wifi`

请求体（JSON）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `ssid` | string | 是 | 新 WiFi 名称 |
| `password` | string | 否 | 新 WiFi 密码（默认空）|

下发后设备会重启生效。

```bash
curl -X POST http://localhost:8088/api/v1/devices/5d47bb925ea440b3b/wifi \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"ssid": "MyWiFi", "password": "12345678"}'
```

### MCP 管理

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/devices/{mac}/mcp` | GET | 获取 MCP 服务器列表 |
| `/api/v1/devices/{mac}/mcp/{name}` | PUT | 添加/更新 MCP 服务器 |
| `/api/v1/devices/{mac}/mcp/{name}` | DELETE | 删除 MCP 服务器 |
| `/api/v1/devices/{mac}/mcp/{name}/tools` | GET | 获取 MCP 工具列表 |
| `/api/v1/devices/{mac}/tools` | GET | 获取设备全部工具 |

PUT `/api/v1/devices/{mac}/mcp/{name}` 请求体（JSON）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `url` | string | 是 | MCP 服务器地址（≤2048）|
| `type` | string | 否 | 传输类型，默认 `streamable_http` |
| `headers` | object | 否 | 自定义请求头 |
| `auth` | object | 否 | 认证配置（与原 headers 合并）|

```bash
curl -X PUT http://localhost:8088/api/v1/devices/5d47bb925ea440b3b/mcp/amap \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"type": "streamable_http", "url": "https://mcp.example.com/mcp", "auth": {"Authorization": "Bearer xxx"}}'
```

> `.../mcp/{name}/tools` 与 `.../tools` 返回的每项仅含 `name` / `description`（不含 parameters）；全局 `GET /api/v1/tools` 才带 `parameters`。

## 工具与技能

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/tools` | GET | 列出所有可用工具（带 parameters）|
| `/api/v1/skills` | GET | 技能列表（?device_id=xxx）|
| `/api/v1/skills` | POST | 创建技能 |
| `/api/v1/skills/{id}` | GET | 技能详情 |
| `/api/v1/skills/{id}` | PUT | 更新技能 |
| `/api/v1/skills/{id}` | DELETE | 删除技能 |
| `/api/v1/skills/{id}/toggle` | POST | 启用/禁用技能 |

POST `/api/v1/skills` 请求体（JSON）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 技能名 |
| `description` | string | 是 | 技能描述 |
| `instructions` | string | 是 | 技能指令/提示词正文 |
| `category` | list | 否 | 分类，默认 `[]` |
| `tags` | list | 否 | 标签，默认 `[]` |
| `cap_groups` | list | 否 | 能力组，默认 `[]` |
| `device_id` | string | 否 | 绑定到指定设备（默认空）|

PUT `/api/v1/skills/{id}` 请求体同上（仅更新 `description` / `instructions` / `category` / `tags` / `cap_groups`）。

POST `/api/v1/skills/{id}/toggle` 参数（query）：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `device_id` | string | 是 | 设备标识 |
| `disabled` | bool | 否 | 默认 `true`（true=禁用，false=启用）|

```bash
curl -X POST http://localhost:8088/api/v1/skills \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "guess_number", "description": "猜数字游戏", "instructions": "和用户玩猜数字游戏..."}'
```

## 表情包

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/emos/packs/list` | GET | 表情包列表 |
| `/api/v1/emos/packs/{name}` | GET | 表情包内容 |
| `/api/v1/emos/packs/create` | POST | 创建表情包（query 参数 `name`）|
| `/api/v1/emos/packs/{name}` | DELETE | 删除表情包 |
| `/api/v1/emos/packs/{pack}/upload` | POST | 上传 GIF（multipart/form-data）|
| `/api/v1/emos/active/{key}` | GET | 获取激活的表情包 |
| `/api/v1/emos/active/{key}` | POST | 应用表情包（query 参数 `pack`）|

参数说明：

| 接口 | 参数 | 位置 | 说明 |
|------|------|------|------|
| `/packs/create` | `name` | query | 表情包名称（必填）|
| `/active/{key}` | `pack` | query | 表情包目录名（必填）|
| `/packs/{pack}/upload` | `file` | form-data | GIF 文件（必填，≤10MB）|
| `/packs/{pack}/upload` | `name` | form-data | 目标文件名（可选，匹配标准表情槽位）|
| `/packs/{pack}/upload` | `size` | form-data | 目标尺寸（可选，>0 时裁剪缩放）|

```bash
curl -X POST "http://localhost:8088/api/v1/emos/active/5d47bb925ea440b3b?pack=default" \
  -H "Authorization: Bearer <token>"
```

## SDK 接口（无需鉴权）

| 接口 | 方法 | 说明 |
|------|------|------|
| `/sdk/query_new_ota` | GET | 设备查询 OTA 更新 |

参数：`?version=1.0.0&bin_id=xxx&is_official=0&mac=xx:xx:xx:xx`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `version` | string | 否 | 设备当前固件版本号 |
| `bin_id` | string | 否 | 设备当前固件 bin ID |
| `is_official` | string | 否 | 是否官方版本（`0` 或 `1`），默认 `0` |
| `mac` | string | 否 | 设备 MAC 地址，用于查询设备级 OTA 配置（不传则使用全局配置）|

**判断优先级（从高到低）**：

1. 设备级 `ota_bin_id`（数据库中每设备独立）与客户端 `bin_id` 比对
2. 设备级 `ota_bin_id` 为空时回退到全局 `ota_bin_id`（环境变量 `OTA_BIN_ID`）与客户端 `bin_id` 比对
3. 版本号比对（设备级 > 全局）

## 完整配网与绑定流程

```
1. 设备开机 → 连接 WiFi
2. 设备通过 WebSocket 连接服务器（不带 key）
3. 服务端检测设备未绑定 → 生成 6 位绑定码 → 发回设备屏幕显示 → 断开连接
4. 用户注册/登录（POST /api/v1/auth/register + login）
5. 获取 JWT token（POST /api/v1/auth/login）
6. 输入绑定码 + 设备名称 → 绑定设备（POST /api/v1/bind）
7. 设备自动重连 → 服务端识别已绑定 → 加载 ASR/LLM/TTS 配置 → 正常对话
```
