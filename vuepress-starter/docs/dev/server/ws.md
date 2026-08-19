# WebSocket 通信协议

## 概述

设备通过 WebSocket 与服务端保持长连接，实现双向实时通信。连接格式：

```
ws://<server-ip>:8088?key=<设备密钥>[&mac=<MAC地址>&version=<固件版本>&AUDIO_BUFFER_SIZE=<缓冲区大小>]
```

**连接参数**：

| 参数 | 必填 | 别名 | 说明 |
|------|------|------|------|
| `key` | 否 | `api_key` | 设备鉴权密钥（新版可省略，设备自动进入绑定模式）|
| `mac` | 否 | `device_id` | 设备 MAC 地址（用于设备识别）|
| `version` | 否 | `v` | 固件版本号 |
| `AUDIO_BUFFER_SIZE` | 否 | — | 音频缓冲区大小（默认 10240）|
| `bitrate` | 否 | — | 音频比特率（服务端未使用，仅设备端配置）|
| `ext1`~`ext7` | 否 | — | 设备扩展参数（如 `ext5`=服务器IP、`ext6`=端口、`ext7`=启动模式），服务端未使用 |

> 实际设备连接 URL 示例：
> `ws://192.168.31.176:8088/connect_espai_node?mac=5d47bb925ea440b3b&v=1.0.0`

### 鉴权机制

服务端根据设备是否携带 `key` 参数采用不同的处理方式：

| 情况 | 处理方式 |
|------|---------|
| 携带 `key` | 与数据库 `device_key` 比对 |
| 无 `key` + 设备已绑定 | 自动使用数据库中的 `device_key`，跳过鉴权 |
| 无 `key` + 设备未绑定 | 进入**绑定模式**：生成 6 位绑定码，通过 `instruct` 指令发回设备屏幕，关闭连接 |

#### 绑定模式

设备首次连接时（无 `key` 且未在数据库中绑定到任何用户）：

1. 服务端生成 6 位大写字母+数字绑定码（如 `3IW5N9`），有效期 5 分钟
2. 发送指令到设备屏幕：`{"type": "instruct", "command_id": "show_bind_code", "data": "3IW5N9"}`
3. 关闭 WebSocket 连接（code=1000），使用正常关闭码以兼容 `esp_websocket_client` 的自动重连机制
4. 用户在 App/Web 中通过 REST API 绑定设备
5. 设备自动重连，服务端识别已绑定，正常提供服务

### 连接错误码

| WebSocket Close Code | 原因 |
|---------------------|------|
| `4001` | 缺少设备标识（mac/device_id 参数为空）|
| `4003` | 鉴权失败（密钥不匹配或设备未注册）|
| `1000` | 需要绑定（设备未注册，绑定码已发送到设备屏幕），使用正常关闭码触发 `esp_websocket_client` 自动重连 |
| `1011` | 服务端内部错误 |
| `1013` | 服务过载（全局并发插槽获取超时，默认 5 秒内未获得连接槽位）|

> `1013` 是企业级并发控制新增的错误码。当全局并发连接数达到上限（默认 500）时，新连接等待 5 秒仍未获得槽位会被拒绝。设备端应实现指数退避重连。

## 连接生命周期

```
设备连接 → 检查 key 参数
  ├─ 有 key → 与数据库 device_key 比对
  ├─ 无 key + 已绑定 → 使用 DB device_key 跳过鉴权
  └─ 无 key + 未绑定 → 生成绑定码 → 发回设备 → 断开连接
  → 初始化工具/MCP/ASR/记忆/Skill（并行）
  → 发送 play_audio_ws_conntceed（服务端）
  → 回复 play_audio_ws_conntceed（设备）
  → 发送连接问候音频（可选）
  → 启动 keepalive 心跳线程
  → 主消息循环（接收设备消息）
  → 断开连接 → 释放并发插槽 → cleanup
```

## 消息类型

### 设备 → 服务端

#### `ping` — 心跳请求

```json
{"type": "ping"}
```

服务端收到后立即回复 `{"type": "pong"}`。设备端据此检测连接活性。

#### `pong` — 心跳响应

```json
{"type": "pong"}
```

对服务端 `keepalive` 的响应（部分固件版本实现）。服务端收到后无需处理。

#### `start` — 开始对话

```json
{"type": "start"}
```

触发完整对话流程：唤醒音频 → ASR 开始识别。若设备已在 ASR 状态，会先重置再重启。

> 重复 `start` 处理：若唤醒流程正在执行或正在等待唤醒音频完成，重复的 `start` 会被忽略。

#### `play_audio_ws_conntceed` — 连接就绪确认

```json
{"type": "play_audio_ws_conntceed"}
```

设备确认连接建立完成，服务端收到后开始播放连接问候音频。

#### `iat_end` — 语音识别结束

```json
{"type": "iat_end"}
```

设备端 VAD 检测到说话结束，通知服务端结束 ASR 识别并启动 LLM Pipeline。

#### `client_out_audio_over` — TTS 播放完成

```json
{"type": "client_out_audio_over"}
```

设备端 TTS 音频播放完毕，服务端据此启动下一轮 ASR 或结束会话。

> 特殊情况：如果 Pipeline 仍在运行时收到此消息（如看门狗超时导致客户端提前结束），服务端会取消 Pipeline。

#### `client_out_audio_ing` — TTS 播放进行中

```json
{"type": "client_out_audio_ing"}
```

设备端正在播放 TTS 音频（纯通知，服务端无需处理）。

#### `client_available_audio` — 设备缓冲区更新

```json
{"type": "client_available_audio", "value": 10240}
```

设备端音频缓冲区可用大小变化，服务端据此进行流量控制。

#### `session_stop` — 停止会话

```json
{"type": "session_stop", "session_id": "0001"}
```

设备端请求结束当前会话。服务端会停止 ASR、中断 TTS、重置 FSM 到 IDLE，并回复：

```json
{"type": "session_stop_ack", "session_id": "0001"}
```

> 注意：`session_stop_ack` 中的 `session_id` 是服务端硬编码的 `"0001"`，不读取设备传来的 `session_id` 值。

#### `firmware_version` — 上报固件版本

```json
{"type": "firmware_version", "version": "1.45.80"}
```

设备连接后上报当前固件版本号，服务端更新设备注册表中的版本信息。

#### `ota_progress` — OTA 升级进度

```json
{"type": "ota_progress", "data": 45, "device_id": "xxx"}
```

OTA 升级过程中设备实时上报进度百分比（0-100）。

#### `ota_update_error` — OTA 升级失败

```json
{"type": "ota_update_error", "device_id": "xxx"}
```

OTA 升级失败通知，服务端会清除设备的 OTA 升级中状态。

#### `lua_result` — Lua 脚本执行结果

```json
{"type": "lua_result", "success": true, "output": "执行成功"}
```

设备端 Lua 脚本执行完成后返回结果给服务端。服务端通过 `tool_manager._pending_lua_future` 将结果传递给等待中的工具调用。

#### 二进制音频数据

```
bytes: <原始 PCM 音频数据>
```

设备采集的麦克风音频数据，通过 WebSocket 二进制帧发送。服务端会检查 `can_queue_audio()` 状态，在队列可写入时接收。

### 服务端 → 设备

#### `play_audio_ws_conntceed` — 连接确认

```json
{"type": "play_audio_ws_conntceed"}
```

服务端在 Session 初始化完成后发送，通知设备连接已就绪。

#### `session_start` — 会话开始

```json
{"type": "session_start", "session_id": "0001"}
```

新对话会话开始，设备应清空上一轮状态。在以下场景发送：
- 用户触发 `start` 开始新对话
- 中断后重启会话

#### `session_status` — 会话状态通知

```json
// ASR 开始
{"type": "session_status", "status": "iat_start"}

// ASR 结束
{"type": "session_status", "status": "iat_end"}

// TTS 块开始
{"type": "session_status", "status": "tts_chunk_start"}

// TTS 块结束
{"type": "session_status", "status": "tts_chunk_end"}

// TTS 全部结束
{"type": "session_status", "status": "tts_real_end"}

// 会话结束
{"type": "session_status", "status": "session_end"}
```

> `tts_real_end` 在以下场景发送：
> - 正常 TTS 播放完成
> - 会话被中断（`session.interrupt()`）时立即发送，通知设备停止播放

#### `instruct` — 指令

```json
// ASR 识别结果
{"type": "instruct", "command_id": "on_iat_cb", "data": "识别文本"}

// LLM 流式输出
{"type": "instruct", "command_id": "on_llm_cb", "data": "模型回复文本"}

// 工具调用状态反馈（显示在设备状态栏，与 on_llm_cb 分离避免干扰 TTS 文字同步）
{"type": "instruct", "command_id": "on_tool_status", "data": "正在处理中，请稍候..."}

// TTS 时长
{"type": "instruct", "command_id": "tts_duration", "data": "1500"}

// 设置音量
{"type": "instruct", "command_id": "set_volume", "data": "0.8"}

// 调大音量
{"type": "instruct", "command_id": "add_volume", "data": "0.1"}

// 调小音量
{"type": "instruct", "command_id": "subtract_volume", "data": "0.1"}

// OTA 升级
{"type": "instruct", "command_id": "ota_update", "data": "{\"url\":\"http://...\",\"version\":\"1.2.0\"}"}

// 更新配置
{"type": "instruct", "command_id": "update_config", "data": "{\"voice_type\":\"...\"}"}

// 设置麦克风引脚
{"type": "instruct", "command_id": "set_mic_pins", "data": "{\"bck\":4,\"ws\":5,\"data\":6}"}
```

> `on_tool_status` 与 `on_llm_cb` 的区别：
> - `on_llm_cb` 携带 LLM 生成的文本，会进入 TTS 合成流程
> - `on_tool_status` 携带工具调用状态提示，仅显示在设备状态栏（top_left），不进入 TTS
> - 两者分离是为了避免工具状态提示干扰 TTS 文字同步

#### `play_audio` — TTS 音频开始

```json
{"type": "play_audio", "tts_task_id": "0001"}
```

通知设备开始接收 TTS 音频帧。`tts_task_id` 为会话标识，与后续二进制帧的会话ID对应。

#### 二进制音频帧 — TTS 数据

```
帧结构：会话ID(4字节 utf-8) + 状态(2字节 utf-8) + 原始音频数据

正常帧：   "0001" + "00" + <PCM 音频数据>
结束帧：   "0001" + "03"
```

- 会话ID：4 字符，如 `"0001"`（连接问候音频）、`"0010"`（TTS 语音）
- 状态码：`"00"` = 正常数据，`"03"` = 结束帧
- 音频数据：原始 PCM 格式

#### `stc_time` — 时间同步

```json
{"type": "stc_time", "stc_time": "1234567890"}
```

服务端在连接问候阶段发送，用于设备时间同步。

#### `keepalive` — 保活心跳

```json
{"type": "keepalive", "ts": 1234567890}
```

服务端定期发送（默认间隔约 30 秒），用于检测连接活性。**设备无需回复**，服务端通过 TCP 层面是否发送成功判断连接状态。

> `keepalive` 与 `ping`/`pong` 是两套独立的心跳机制：
> - `keepalive`：服务端→设备的单向心跳，无需回复
> - `ping`/`pong`：设备发起心跳请求，服务端回复 `pong`

#### `show_image` — 显示图片

```json
{"type": "show_image", "url": "https://example.com/image.jpg", "width": 240, "height": 240}
```

服务端通知设备屏幕显示指定图片。`width`/`height` 为图片显示尺寸。

#### `clear_image` — 清除图片

```json
{"type": "clear_image"}
```

服务端通知设备清除屏幕当前显示的图片。

#### `emotion` — 表情图片

```json
{"type": "emotion", "data": "happy"}
```

服务端根据 LLM 回复末尾的情绪标签（如 `[e:快乐]`）发送对应表情图片到设备屏幕。`data` 为情绪标识符。

#### `set_wifi_config` — WiFi 配置

```json
{"type": "set_wifi_config", "configs": {"wifi_name": "MyWiFi", "wifi_pwd": "password123"}}
```

服务端推送 WiFi 配置到设备，设备收到后会重启应用新配置。

#### 待处理消息（设备连接时推送）

设备重新连接时，服务端会在 keepalive 心跳周期中检查是否有待处理的消息并推送：

```json
// OTA 升级待处理
{"type": "instruct", "command_id": "ota_update", "data": "..."}

// WiFi 配置待处理
{"type": "set_wifi_config", "configs": {"wifi_name": "...", "wifi_pwd": "..."}}

// 其他待处理指令
{"type": "instruct", "command_id": "...", "data": "..."}
```

#### `session_end` 文本消息

连接问候音频播放结束时，服务端除了发送 JSON 格式的 `session_status: session_end`，还会发送一条纯文本消息：

```
session_end
```

设备收到后确认连接问候阶段结束，进入待命状态。

## 完整对话流程

```
设备                   服务端
  │                       │
  │── WebSocket 连接 ──▶   │
  │                       │── 鉴权（single: 环境变量 / multi: 数据库查询）
  │                       │── 全局并发插槽获取
  │                       │── 创建 Session
  │                       │── 并行初始化（工具/MCP/ASR预连/记忆/Skill）
  │◀── play_audio_ws_conntceed ──│
  │── play_audio_ws_conntceed ──▶│
  │                       │── 播放连接问候音频（可选）
  │◀── session_status(session_end) ──│
  │◀── "session_end"（文本）──│
  │                       │
  │── ping ──────────────▶│  ← 设备心跳
  │◀── pong ──────────────│  ← 服务端响应
  │                       │
  │◀── keepalive ──────────│  ← 服务端单向心跳（无需回复）
  │                       │
  │── start ────────────▶│  ← 用户开始对话
  │◀── session_start ─────│  ← 会话开始
  │                       │── 播放唤醒音频
  │◀── session_status(iat_start) ──│
  │── 二进制音频数据 ────▶│  ← PCM 音频流
  │── iat_end ──────────▶│  ← VAD 检测到静默
  │                       │── Pipeline 启动
  │◀── instruct(on_iat_cb) ──│  ← ASR 结果
  │◀── instruct(on_llm_cb) ──│  ← LLM 流式输出
  │◀── instruct(on_tool_status) ──│  ← 工具调用状态（如有）
  │◀── session_status(tts_chunk_start) ──│
  │◀── play_audio ────────│
  │◀── 二进制音频帧 ──────│  ← TTS 音频
  │◀── session_status(tts_chunk_end) ──│
  │◀── session_status(tts_real_end) ──│
  │── client_out_audio_over ──▶│  ← 播放完成
  │                       │── 启动下一轮 ASR（连续对话）
```

## 中断流程

当用户在设备说话或 TTS 播放时再次说"开始"触发中断：

```
设备                   服务端
  │── start ────────────▶│
  │                       │── 检查当前状态
  │                       │
  │                       │  [若 ASR 进行中]
  │                       │── 发送 session_end 结束当前 ASR
  │                       │
  │                       │  [若 TTS 播放中]
  │                       │── 取消 tts_done_waiter
  │                       │── session.interrupt() 中断 TTS
  │                       │── 等待 tts_playback_done（0.5s 超时）
  │                       │── 发送 tts_real_end
  │                       │── 发送 end_frame（结束帧）
  │                       │
  │                       │  [通用清理]
  │                       │── 取消连接问候音频任务
  │                       │── 取消旧 Pipeline 任务
  │                       │── 清除唤醒音频事件
  │                       │── 重置 FSM 到 IDLE
  │                       │
  │◀── session_start ─────│  ← 会话重置
  │                       │── 取消预连 ASR，重新预连
  │                       │
  │                       │  [重新开始]
  │                       │── 播放唤醒音频（若启用）
  │                       │── 或直接进入 ASR（若未启用唤醒音频）
  │◀── session_status(iat_start) ──│  ← 新一轮 ASR 开始
```

> 中断流程的关键设计：
> - TTS 中断有 0.5 秒等待超时，避免设备无响应时长时间阻塞
> - 预连 ASR 会被取消并重建，确保新会话使用新的 ASR 连接
> - 唤醒音频任务会被取消并重新创建，避免多个任务竞争 `_waiting_wake_audio` 标志
