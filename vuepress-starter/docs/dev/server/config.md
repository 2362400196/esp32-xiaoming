# 配置文档

所有配置通过 `.env` 环境变量管理，复制 `.env.example` 为 `.env` 后编辑。

## 部署模式

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `DEPLOY_MODE` | `single` | `single`=从 `.env` 读取配置, `multi`=从数据库 `devices` 表按设备读取 |

## 服务器

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `HOST` | `0.0.0.0` | 监听地址 |
| `PORT` | `8088` | 监听端口 |
| `LOG_FORMAT` | `console` | 日志格式：`console` / `json` |
| `DEBUG_LOG` | `false` | 是否输出 DEBUG 日志 |
| `DEBUG_LOG_LEVEL` | `INFO` | DEBUG 日志级别 |
| `CORS_ORIGINS` | `""`（空，不允许跨域）| CORS 跨域来源（逗号分隔，留空表示不允许任何跨域，生产环境需显式配置允许的域名）|

### 日志文件

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `LOG_FILE_PATH` | `logs/esp_ai.log` | 日志文件路径 |
| `LOG_MAX_SIZE` | `10485760` | 单个日志文件最大字节数 |
| `LOG_BACKUP_COUNT` | `5` | 保留的日志文件数 |

## 数据库

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `DATABASE_URL` | `sqlite+aiosqlite:///data/espai.db` | 异步数据库 URL |
| `DATABASE_SYNC_URL` | `sqlite:///data/espai.db` | 同步数据库 URL |
| `DATABASE_ECHO` | `false` | 是否打印 SQL 日志 |

## 鉴权

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `AUTH_ENABLED` | `true` | 启用鉴权 |
| `JWT_SECRET` | `""` | JWT 签名密钥（生产环境必须设置固定值）|
| `DEPLOY_MODE` | `single` | 部署模式（`multi` 模式下设备配置从数据库读取）|

> 新版设备使用绑定码 + JWT 认证，`AUTH_API_KEY` / `ADMIN_API_KEY` 已废弃（deprecated），不再推荐使用；管理 REST API 仍可通过 `ADMIN_API_KEY`（或每设备 `management_api_key`）配置。

## 速率限制（三层）

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `RATE_LIMIT_MAX_RPM` | `0` | 第 1 层：每个客户端 IP 每分钟最大请求数（0=禁用）|
| `PERF_RATE_LIMIT_GLOBAL_RPM` | `3000` | 第 2 层：全局每分钟请求上限 |
| `rate_limit_rpm`（设备字段）| 跟随全局 | 第 3 层：设备级限流，通过 API 创建设备或更新配置时设置 |

## OTA 固件升级

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `OTA_ENABLED` | `true` | 启用 OTA |
| `OTA_VERSION` | `""` | 固件版本号 |
| `OTA_BIN_URL` | `""` | 固件下载地址 |
| `OTA_BIN_ID` | `""` | 固件文件 ID |
| `OTA_IS_OFFICIAL` | `0` | 是否官方版本 |

> OTA 支持设备级配置，通过 API 设置设备 `ota` 字段（`enabled`, `bin_url`, `version`, `bin_id`, `is_official`）可覆盖全局配置。

## 性能优化

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `PERF_GLOBAL_MAX_CONCURRENT_SESSIONS` | `500` | 全局最大并发会话数 |
| `PERF_ENABLE_GLOBAL_CONCURRENCY_LIMIT` | `true` | 启用全局并发限制 |
| `PERF_AUDIO_QUEUE_MAX_SIZE` | `200` | 音频队列上限 |
| `PERF_SEND_QUEUE_MAX_SIZE` | `500` | 发送队列上限 |
| `PERF_MAX_MESSAGES_PER_SESSION` | `100` | 单会话最大消息数 |
| `PERF_PROCESS_POOL_MAX_WORKERS` | `8` | CPU 密集型线程池大小 |

## ASR 语音识别

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `ASR_PROVIDER` | `tencent` | 厂商：`volcengine` / `tencent` / `aliyun` / `xunfei` |

### 火山引擎

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `ASR_VOLCENGINE_API_KEY` | `""` | API Key |
| `ASR_VOLCENGINE_RESOURCE_ID` | `volc.bigasr.sauc.duration` | 资源 ID |
| `ASR_VOLCENGINE_MODEL` | `bigmodel` | 模型名 |

### 腾讯云

| 环境变量 | 说明 |
|---------|------|
| `ASR_TENCENT_APP_ID` | AppId |
| `ASR_TENCENT_SECRET_ID` | SecretId |
| `ASR_TENCENT_SECRET_KEY` | SecretKey |
| `ASR_TENCENT_ENGINE` | 引擎类型（默认 `16k_zh`）|


### 超时与并发

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `ASR_MAX_CONCURRENCY` | `100` | ASR 最大并发数 |
| `ASR_NO_SPEECH_TIMEOUT` | `5` | 无人说话超时退出（秒）|
| `ASR_SILENCE_TIMEOUT` | `2` | 说话后静默超时进入 LLM（秒）|

### ASR 连接池

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `ASR_POOL_ENABLED` | `true` | 启用连接池 |
| `ASR_POOL_MAX_SIZE` | `100` | 池最大连接数 |
| `ASR_POOL_MIN_SIZE` | `2` | 池最小连接数 |
| `ASR_POOL_HEARTBEAT_INTERVAL` | `30` | 心跳间隔（秒）|
| `ASR_POOL_IDLE_TIMEOUT` | `300` | 空闲超时（秒）|
| `ASR_POOL_CONNECTION_TIMEOUT` | `15` | 连接超时（秒）|

## LLM 大模型

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `LLM_API_KEY` | `""` | API Key |
| `LLM_BASE_URL` | `""` | API 地址（如 `https://api.deepseek.com/v1`）|
| `LLM_MODEL` | `""` | 模型名（如 `deepseek-v4-flash`）|
| `LLM_SYSTEM_PROMPT` | `""` | 系统提示词（未配置时使用内置默认提示词）|
| `LLM_TEMPERATURE` | `0.7` | 温度参数 |
| `LLM_MAX_TOKENS` | `2000` | 最大 Token 数 |

### 对话记忆

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `LLM_MEMORY_ENABLED` | `true` | 启用短时记忆 |
| `LLM_MEMORY_MAX_MESSAGES` | `20` | 最大记忆消息数 |
| `LLM_MEMORY_MAX_TOKENS` | `2000` | 最大记忆 Token 数 |
| `LLM_MEMORY_LONG_TERM_ENABLED` | `true` | 启用长期记忆 |
| `LLM_MEMORY_LONG_TERM_AUTO_EXTRACT` | `true` | 自动提取摘要 |

## TTS 语音合成

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `TTS_VOLCENGINE_API_KEY` | `""` | 火山引擎 API Key |
| `TTS_VOLCENGINE_RESOURCE_ID` | `""` | 资源 ID |
| `TTS_VOLCENGINE_VOICE_TYPE` | `""` | 音色 ID |
| `TTS_VOLCENGINE_SPEED` | `1.0` | 语速（0.5~2.0）|
| `TTS_VOLCENGINE_VOLUME` | `1.0` | 音量（0.5~2.0）|
| `TTS_VOLCENGINE_PITCH` | `1.0` | 音调（0.5~2.0）|

### TTS 连接池

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `TTS_POOL_ENABLED` | `true` | 启用连接池 |
| `TTS_POOL_MAX_SIZE` | `100` | 池最大连接数 |
| `TTS_POOL_MIN_SIZE` | `2` | 池最小连接数 |
| `TTS_POOL_HEARTBEAT_INTERVAL` | `30` | 心跳间隔（秒）|
| `TTS_POOL_IDLE_TIMEOUT` | `300` | 空闲超时（秒）|
| `TTS_POOL_CONNECTION_TIMEOUT` | `15` | 连接超时（秒）|

## 唤醒配置

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `WAKEUP_TEXT` | `我在呢` | 唤醒回复文本 |
| `ENABLE_WAKEUP_AUDIO` | `true` | 启用唤醒音频 |
| `WAKE_AUDIO_CACHE_ENABLED` | `true` | 缓存唤醒音频 |
| `WAKE_AUDIO_PLAY_ENABLED` | `true` | 播放唤醒音频 |
| `WAKE_AUDIO_SOURCE` | `file` | 来源：`tts` / `file` |
| `WAKE_AUDIO_ON_NEXT_ROUND` | `false` | 下一轮是否播放 |

## 情感检测

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `SERVER_EMOTION_ENABLED` | `true` | 启用情感检测，设备屏幕根据对话显示表情 |
| `SERVER_EMOTION_GIF_DIR` | `emos` | 表情 GIF 目录 |
| `SERVER_EMOTION_STATIC_DIR` | `static_emos` | 静态表情目录 |

## MCP 外部工具

| 环境变量 | 说明 |
|---------|------|
| `MCP_SERVERS_JSON` | JSON 格式的 MCP 服务器配置 |

```bash
MCP_SERVERS_JSON={"amap-maps":{"type":"streamable_http","url":"https://xxx/mcp"}}
```

## 音乐播放

| 环境变量 | 说明 |
|---------|------|
| `MUSIC_API_URL` | 音乐 API 地址 |
| `LYRICS_OFFSET` | 歌词偏移（毫秒）|

## AI 成长系统

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `GROWTH_COOLDOWN_SECONDS` | `300` | 对话结束后冷却时间（秒），过后触发成长任务 |

## 远程配置

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `REMOTE_CONFIG_ENABLED` | `false` | 启用远程配置 |
| `REMOTE_CONFIG_URL` | `""` | 远程配置 URL |
| `REMOTE_CONFIG_API_KEY` | `""` | 远程配置 API Key |
| `REMOTE_CONFIG_CACHE_TTL` | `300` | 缓存时间（秒）|
| `REMOTE_CONFIG_REFRESH_INTERVAL` | `60` | 刷新间隔（秒）|

## 优雅退出

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `SHUTDOWN_GRACE_PERIOD` | `10` | SIGTERM 后等待活跃连接完成（秒）|

## 多设备配置

多用户模式下（`DEPLOY_MODE=multi`），设备配置存储在数据库 `devices` 表中，可通过 API 管理。

### 创建设备

```bash
POST /api/v1/devices
Authorization: Bearer <your-jwt-token>
Content-Type: application/json

{"mac": "AA:BB:CC:DD:EE:FF", "key": "my_key", "name": "客厅设备"}
```

详见 [API 文档 > 设备管理](/dev/api#设备管理)。

### 设备配置字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 设备名称 |
| `key` | string | 连接鉴权密钥。创建设备时必填（手动指定）；通过绑定码绑定后自动生成 `bound_xxx` 形式，无需手动设置 |
| `mac` | string | MAC 地址（设备唯一 ID）|
| `asr_provider` | string | ASR 厂商，未填继承 `.env` |
| `llm` | object | LLM 参数：`api_key`, `base_url`, `model`, `system_prompt` 等 |
| `tts_config` | object | TTS 全量配置：`api_key`, `voice_type`, `speed_ratio` 等 |
| `asr_config` | object | 按厂商名为 key 的 ASR 配置对象 |
| `mcp_servers` | object | MCP 外部工具服务器配置 |
| `skills` | string[] | 启用的技能列表 |
| `disabled_tools` | string[] | 禁用的内置工具 |
| `disabled_skills` | string[] | 禁用的技能 |
| `disabled_mcp_servers` | string[] | 禁用的 MCP 服务器 |
| `disabled_mcp_tools` | object | 按服务器禁用的工具 |
| `ota` | object | OTA 配置：`enabled`, `bin_url`, `version`, `bin_id`, `is_official` |
| `wakeup` | object | 唤醒配置：`text`, `enabled`, `source`, `play_on_next_round`, `cache_enabled` |
| `music` | object | 音乐配置：`api_url`, `lyrics_offset` |
| `rate_limit_rpm` | int | 每分钟 LLM 调用上限 |

### 配置优先级

```
设备数据库配置 > .env 环境变量 > 代码默认值
```