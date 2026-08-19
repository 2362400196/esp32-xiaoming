# ESP-AI-Server 运维与部署指南

> 面向生产环境部署的运维手册，涵盖密钥管理、安全配置、速率限制、容器部署、可观测性与就绪检查。

---

## 一、密钥管理

### 1.1 密钥清单

服务运行所需的核心密钥（通过 `.env` 或环境变量注入，**禁止硬编码或提交到版本库**）：

| 环境变量 | 用途 | 必填 | 示例 |
|---|---|---|---|
| `AUTH_ENABLED` | 是否启用 REST API 认证 | 否（生产建议 `true`） | `true` |
| `ADMIN_API_KEY` | 管理端 API 密钥（全权限） | 启用认证时必填 | `sk-admin-xxxx` |
| `AUTH_API_KEY` | 设备认证密钥（WebSocket `?key=`） | 启用认证时必填 | `sk-device-xxxx` |
| `LLM_API_KEY` | LLM 服务密钥（OpenAI 兼容） | 是 | `sk-xxxx` |
| `ASR_VOLCENGINE_API_KEY` | 火山引擎 ASR 密钥 | ASR=volcengine 时必填 | `xxxx` |
| `TTS_VOLCENGINE_API_KEY` | 火山引擎 TTS 密钥 | 是 | `xxxx` |
| `TTS_VOLCENGINE_RESOURCE_ID` | TTS 资源 ID（V3 接口：`seed-tts-2.0`/`seed-tts-1.0`/`seed-icl-2.0`/`seed-icl-1.0`） | 否 | `seed-tts-2.0` |
| `MCP_SERVERS_JSON` | MCP 外部工具服务器配置（JSON） | 否 | `{"maps":{"command":"..."} }` |

### 1.2 密钥安全实践

- **生成强密钥**：`python -c "import secrets; print(secrets.token_urlsafe(32))"`
- **最小权限**：`ADMIN_API_KEY` 与 `AUTH_API_KEY` 使用不同值，管理端与设备端权限分离。
- **轮换机制**：密钥更换时，先更新服务端 `.env`，重启服务，再批量更新设备配置。
- **日志脱敏**：服务端日志已对密钥脱敏（仅输出前缀或完全隐藏），切勿在自定义日志中打印原始密钥。
- **向后兼容**：未配置任何密钥且 `AUTH_ENABLED=false` 时，REST API 处于无保护状态，服务端会记录一次性 WARNING。生产环境必须启用认证。

### 1.3 认证方式（严格分离）

**设计原则**：设备密钥与管理密钥严格分离，设备密钥**无法**访问管理 REST API，消除权限提升风险。

| 场景 | 密钥 | 传输方式 |
|---|---|---|
| 设备 WebSocket | `AUTH_API_KEY`（或 users.json per-device key） | URL `?key=<KEY>` |
| 管理 REST API | `ADMIN_API_KEY` **仅** | `X-API-Key` 或 `Authorization: Bearer` |

**REST API**（两种等价方式，仅接受 ADMIN_API_KEY）：
```bash
# X-API-Key 头
curl -H "X-API-Key: $ADMIN_API_KEY" http://localhost:8088/api/devices

# Authorization: Bearer 头
curl -H "Authorization: Bearer $ADMIN_API_KEY" http://localhost:8088/api/devices
```

**WebSocket（设备，使用 AUTH_API_KEY）**：
```
ws://server:8088/?key=$AUTH_API_KEY
```

> ⚠️ **安全提示**：用 `AUTH_API_KEY` 访问管理 API 会返回 `403 Forbidden`，响应和日志中会提示"管理 API 不接受设备密钥 AUTH_API_KEY"。这确保即使设备密钥泄露，攻击者也无法调用管理接口。

---

## 二、安全配置

### 2.1 CORS 跨域

通过 `CORS_ORIGINS` 环境变量配置允许的前端来源（逗号分隔）：

```bash
# 生产环境：限定具体域名
CORS_ORIGINS=https://admin.example.com,https://app.example.com

# 开发环境：允许全部（默认）
CORS_ORIGINS=*
```

### 2.2 速率限制

通过 `RATE_LIMIT_MAX_RPM` 配置每个客户端 IP 的请求上限（每分钟请求数）：

```bash
# 每分钟 120 次/IP
RATE_LIMIT_MAX_RPM=120

# 0 或不配置 = 禁用（默认）
RATE_LIMIT_MAX_RPM=0
```

- 采用令牌桶算法，允许短时突发。
- 超限时返回 HTTP `429 Too Many Requests`，响应头携带 `Retry-After`（秒）。
- 仅对 REST API 生效，WebSocket 设备连接不受限。
- 令牌桶按 IP 隔离，闲置 10 分钟自动回收，无内存泄漏风险。

### 2.3 REST API 输入校验

所有写接口（POST/PUT/DELETE）已启用：
- **认证依赖**：`Depends(verify_admin_api_key)` 校验 API Key。
- **字段约束**：Pydantic 模型限制长度（如 `device_id` ≤ 64 字符，`text` ≤ 500 字符）。
- **全局异常兜底**：未处理异常统一返回 `{"code":1,"message":"Internal server error"}`，不泄露堆栈。

---

## 三、容器部署

### 3.1 Docker 构建

```bash
# 构建镜像
docker build -t esp-ai-server:3.0.0 .

# 运行（挂载 .env 与数据卷）
docker run -d \
  --name esp-ai \
  --env-file .env \
  -p 8088:8088 \
  -v esp-ai-data:/app/src/data \
  -v esp-ai-logs:/app/logs \
  --memory=2g --cpus=2 \
  --restart unless-stopped \
  esp-ai-server:3.0.0
```

### 3.2 Docker Compose

```bash
docker compose up -d
```

`docker-compose.yml` 已配置：
- 资源限制：2G 内存 / 2 CPU
- 日志轮转：json-file，10m × 3 份
- 健康检查：`/health/live`，30s 间隔

### 3.3 健康检查端点

| 端点 | 用途 | 状态码 |
|---|---|---|
| `GET /health/live` | 存活探针（进程是否运行） | 200 |
| `GET /health/ready` | 就绪探针（ASR/LLM/TTS 网关是否就绪） | 200 或 503 |

Kubernetes 探针配置示例：
```yaml
livenessProbe:
  httpGet: { path: /health/live, port: 8088 }
  periodSeconds: 30
readinessProbe:
  httpGet: { path: /health/ready, port: 8088 }
  periodSeconds: 10
  failureThreshold: 3
```

---

## 四、可观测性

### 4.1 链路追踪（trace_id）

- 每个 HTTP 请求自动生成 `trace_id`（或从 `X-Trace-Id` 请求头透传）。
- `trace_id` 注入到 contextvar，所有日志自动携带。
- `trace_id` 透传到下游 LLM/TTS/ASR 请求头（`X-Trace-Id`），实现全链路关联。
- 响应头返回 `X-Trace-Id` 与 `X-Response-Time`（毫秒）。

### 4.2 Prometheus 指标

`GET /metrics` 暴露 Prometheus 格式指标：

| 指标 | 类型 | 说明 |
|---|---|---|
| `espai_session_active` | Gauge | 当前活跃会话数 |
| `espai_websocket_connections_current` | Gauge | 当前 WebSocket 连接数 |
| `espai_asr_request_duration_seconds` | Histogram | ASR 请求耗时 |
| `espai_llm_request_duration_seconds` | Histogram | LLM 请求耗时 |
| `espai_llm_first_token_latency_seconds` | Histogram | LLM 首 token 延迟 |
| `espai_tts_request_duration_seconds` | Histogram | TTS 请求耗时 |
| `espai_pipeline_run_duration_seconds` | Histogram | Pipeline 运行耗时 |
| `http_request_duration_seconds` | Histogram | HTTP 请求耗时（自动） |

Prometheus 抓取配置：
```yaml
scrape_configs:
  - job_name: esp-ai
    metrics_path: /metrics
    static_configs:
      - targets: ['esp-ai:8088']
```

### 4.3 日志

- 格式：彩色控制台 + 可选文件轮转（`LOG_FILE_PATH=logs/esp_ai.log`）。
- 轮转：默认 10MB × 5 份。
- 级别：`LOG_LEVEL=INFO`（生产）/ `DEBUG`（排查）。
- 音频队列日志已降级到 DEBUG，避免 I/O 阻塞事件循环。

---

## 五、企业级就绪检查清单

| 维度 | 项 | 状态 |
|---|---|---|
| **安全** | REST API 认证（API Key） | ✅ |
| | CORS 跨域配置 | ✅ |
| | 输入校验（Pydantic + 长度限制） | ✅ |
| | 密钥日志脱敏 | ✅ |
| | 速率限制（令牌桶 / IP） | ✅ |
| | 全局异常兜底（不泄露堆栈） | ✅ |
| **可观测** | trace_id 全链路透传 | ✅ |
| | Prometheus 业务 + HTTP 指标 | ✅ |
| | 存活 / 就绪探针 | ✅ |
| | 结构化日志 + 文件轮转 | ✅ |
| **可靠性** | 动态 TTS 超时（防无限等待） | ✅ |
| | MCP 工具调用双重超时 + 断连 | ✅ |
| | 空 Pipeline 跳过等待 | ✅ |
| | WSChannel 双队列优先级控制 | ✅ |
| | 优雅关闭（资源清理） | ✅ |
| **部署** | 多阶段 Dockerfile | ✅ |
| | Docker Compose 资源限制 | ✅ |
| | CI/CD（lint + type-check + test + cov 80%） | ✅ |
| | .dockerignore / .env 隔离 | ✅ |
| **质量** | 单元测试 2371+ | ✅ |
| | 覆盖率 81%+ | ✅ |
| | ruff lint + mypy | ✅ |

---

## 六、已知技术债务与演进路线

### 6.1 架构合规

当前 `use_cases/` 层存在对 `infrastructure/` 的导入，按严格 Clean Architecture 属于依赖方向违规。实际情况分两类：

**可接受（横切关注点）**：`config`、`logging`、`monitoring` 属于基础设施横切层，use_cases 依赖它们在工程实践中普遍接受，不引入业务耦合。

**待重构（真违规）**：以下为函数体内延迟导入，未造成循环依赖，但违反依赖规则：
- `session.py` / `auth_service.py` → `infrastructure.memory_repository`
- `builtin_tools.py` / `self_learning.py` → `infrastructure.web.get_app`

**演进路线**：在 `domain/repositories.py` 定义仓储端口接口，在 `infrastructure/` 实现具体类，通过依赖注入传入 use_cases。此重构涉及核心会话逻辑，建议在测试覆盖保护下分批进行。

### 6.2 后续 P2 项（已规划，未实施）

- OpenTelemetry 分布式追踪（替代手动 trace_id）
- JWT 认证（替代静态 API Key，支持过期与刷新）
- Redis 分布式速率限制（替代内存令牌桶，支持多实例）
- CI 自动构建并推送 Docker 镜像到镜像仓库
