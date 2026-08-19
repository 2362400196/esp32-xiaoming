# 最小配置

项目默认使用**多用户模式（multi）**：ASR、LLM、TTS 等密钥通过 App 在线配置并存入数据库（devices 表），**无需手动在 `.env` 里填写各种 API Key**。`.env` 只需几项基础配置即可跑起来。

## 最小 .env 配置

```bash
# ============================================================
# 部署模式
# multi - 多用户（默认推荐）：ASR/LLM/TTS 配置从数据库读取，App 在线管理
# single- 单用户：ASR/LLM/TTS 配置从 .env 读取
# ============================================================
DEPLOY_MODE=multi

# ============================================================
# 服务器配置
# ============================================================
HOST=0.0.0.0
PORT=8088
LOG_FORMAT=console
DEBUG_LOG=false
DEBUG_LOG_LEVEL=INFO

# ============================================================
# 设备连接鉴权
# 打开设备鉴权，生产环境请把 JWT_SECRET 改为随机字符串
# ============================================================
AUTH_ENABLED=true
JWT_SECRET=your-random-secret-string

# ============================================================
# 全局限流
# ============================================================
RATE_LIMIT_MAX_RPM=60

# ============================================================
# 性能优化配置（支持 500+ 并发）
# ============================================================
# 全局并发控制
PERF_GLOBAL_MAX_CONCURRENT_SESSIONS=500
PERF_ENABLE_GLOBAL_CONCURRENCY_LIMIT=true
# 队列大小限制
PERF_AUDIO_QUEUE_MAX_SIZE=200
PERF_SEND_QUEUE_MAX_SIZE=500
# 内存保护
PERF_MAX_MESSAGES_PER_SESSION=100
# 全局限流 RPM
PERF_RATE_LIMIT_GLOBAL_RPM=3000
# CPU 密集型任务线程池
PERF_PROCESS_POOL_MAX_WORKERS=8

# ============================================================
# ASR 连接池配置（语音识别）
# ============================================================
ASR_PROVIDER=volcengine
# 连接池设置
ASR_POOL_ENABLED=true
ASR_POOL_MAX_SIZE=100
ASR_POOL_MIN_SIZE=2
ASR_POOL_HEARTBEAT_INTERVAL=30
ASR_POOL_IDLE_TIMEOUT=300
ASR_POOL_CONNECTION_TIMEOUT=15
# ASR 并发限制
ASR_MAX_CONCURRENCY=100
# ASR 超时配置
ASR_NO_SPEECH_TIMEOUT=5
ASR_SILENCE_TIMEOUT=2

# ============================================================
# TTS 连接池设置
# ============================================================
TTS_POOL_ENABLED=true
TTS_POOL_MAX_SIZE=100
TTS_POOL_MIN_SIZE=2
TTS_POOL_HEARTBEAT_INTERVAL=30
TTS_POOL_IDLE_TIMEOUT=300
TTS_POOL_CONNECTION_TIMEOUT=15

# ============================================================
# 情感检测配置
# ============================================================
SERVER_EMOTION_ENABLED=true

# ============================================================
# AI 成长系统配置
# ============================================================
# 成长任务冷却时间（秒）：对话结束后等待指定时间无新对话才触发成长任务
# 默认 300 秒（5 分钟），设置为 0 则立即触发
GROWTH_COOLDOWN_SECONDS=300

# ============================================================
# 优雅退出
# ============================================================
SHUTDOWN_GRACE_PERIOD=10
```

> 其余配置项（ASR / LLM / TTS 密钥、唤醒音频、OTA 等）均可留空或使用默认值——多用户模式下它们**优先按设备从数据库读取**，通过 App 配置。

## 启动

### 1. 复制配置文件

**Windows**

在 `esp-ai-server` 项目目录下，手动把 `.env.example` 复制一份并重命名为 `.env`；或直接用编辑器新建一个 `.env` 文件，把上方的最小配置粘贴进去。

**macOS / Linux**

```bash
cp .env.example .env
```

### 2. 编辑配置

用文本编辑器打开 `.env`，将 `DEPLOY_MODE` 设为 `multi`（并填入上方最小配置）。ASR / LLM / TTS 密钥**无需填写**，多用户模式下通过 App 在线配置。

### 3. 启动服务

```bash
uv run python main.py
```

服务启动后监听 `http://0.0.0.0:8088`，日志输出到控制台。

> 💡 更多进阶配置（端口、鉴权、性能优化、OTA、ASR/LLM/TTS 厂商切换等）参见开发文档的[配置文档](/dev/server/config)。

