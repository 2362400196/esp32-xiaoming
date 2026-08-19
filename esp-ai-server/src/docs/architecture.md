# ESP-AI-Server 架构说明

## 一、项目概述

ESP-AI-Server 是一个面向 ESP32 等嵌入式设备的 AI 语音助手后端服务。设备通过 WebSocket 与服务端保持长连接，实现 **唤醒 → 语音识别(ASR) → 大模型对话(LLM) → 语音合成(TTS)** 的完整对话循环。

核心数据流：

```
ESP32 设备 ──WebSocket──▶ 服务端
                            │
                            ▼
                    ┌─── ASR 语音识别 ───┐
                    │   (火山引擎/腾讯云)  │
                    └────────┬───────────┘
                             │ 识别文本
                             ▼
                    ┌─── LLM 大模型 ─────┐
                    │   (OpenAI 兼容接口)  │
                    └────────┬───────────┘
                             │ 回复文本
                             ▼
                    ┌─── TTS 语音合成 ───┐
                    │   (火山引擎)        │
                    └────────┬───────────┘
                             │ 音频帧
                             ▼
                    ESP32 设备 ◀──WebSocket──
```

---

## 二、Clean Architecture 分层

项目遵循 Clean Architecture（整洁架构）原则，按依赖方向从内到外分为四层：

```
┌─────────────────────────────────────────────────────┐
│                   interfaces/                        │  ← 外层：适配器
│   (ASR/LLM/TTS 网关、WebSocket 控制器、认证)         │
├─────────────────────────────────────────────────────┤
│                 infrastructure/                      │  ← 框架层
│   (FastAPI 应用、配置、日志、DI 容器、监控)           │
├─────────────────────────────────────────────────────┤
│                   use_cases/                         │  ← 用例层（核心业务）
│   (Session、Pipeline、工具系统、队列、语音生成)       │
├─────────────────────────────────────────────────────┤
│                    domain/                           │  ← 领域层（最内层）
│   (实体、值对象、异常、仓储接口、领域服务接口)        │
└─────────────────────────────────────────────────────┘

依赖规则：外层可以依赖内层，内层不能依赖外层。
```

### 各层职责

| 层 | 目录 | 职责 | 关键文件 |
|---|---|---|---|
| **Domain** | `domain/` | 定义核心业务实体、异常、接口契约 | `entities.py`, `exceptions.py`, `repositories.py`, `services.py`, `value_objects.py` |
| **Use Cases** | `use_cases/` | 实现核心业务逻辑 | `session.py`, `pipeline.py`, `tools_system.py`, `session_fsm.py`, `queues.py` |
| **Infrastructure** | `infrastructure/` | 框架集成、配置、日志 | `web.py`, `config.py`, `logging.py`, `di_container.py`, `monitoring.py` |
| **Interfaces** | `interfaces/` | 外部服务适配器 | `gateways.py`, `asr_gateways.py`, `llm_gateways.py`, `tts_gateways.py` |

---

## 三、目录结构详解

```
src/
├── domain/                          # 领域层
│   ├── entities.py                  # 实体：Session, Device, Conversation, Message, SessionState
│   ├── exceptions.py                # 异常层级：DomainError → ASRError, LLMError, TTSError, PipelineError...
│   ├── repositories.py             # 仓储接口：ASRRepository, LLMRepository, TTSRepository, ToolRepository
│   ├── services.py                  # 领域服务接口：PipelineService, MemoryService, EmotionService, AuthService
│   └── value_objects.py             # 值对象：EmotionType, ASRProvider, LLMProvider, TTSProvider
│
├── use_cases/                       # 用例层
│   ├── session.py                   # Session 会话核心：ASR 流式循环、Watchdog、对话循环
│   ├── pipeline.py                  # 4-Worker 并发流水线：LLM → Splitter → TTS → Sender
│   ├── session_fsm.py               # 会话状态机 + WebSocket 通道
│   ├── session_management.py        # 会话管理器：创建/销毁/暂停/恢复、Watchdog
│   ├── tools_system.py              # 工具框架：@tool 装饰器、ToolManager、MCP、熔断器
│   ├── builtin_tools.py             # 内置工具：音量控制、播放音乐、获取时间、待机
│   ├── custom/                      # 自定义工具目录（开发者在此添加工具）
│   │   ├── __init__.py
│   │   └── example.py               # 示例工具
│   ├── queues.py                    # 三级背压队列：TextQueue → AudioQueue → SendQueue
│   ├── voice_generator.py           # TTS 音频帧生成器（二进制帧协议）
│   ├── auxiliary_services.py        # 辅助服务：设备注册表、唤醒音频、情绪检测、对话记忆
│   ├── dtos.py                      # 数据传输对象
│   └── ports.py                     # 输出端口接口
│
├── infrastructure/                  # 基础设施层
│   ├── web.py                       # FastAPI 应用、路由、WebSocket 处理器、启动生命周期
│   ├── config.py                    # 配置管理（pydantic-settings，兼容 .env）
│   ├── logging.py                   # 彩色日志系统（colorama + 上下文注入）
│   ├── connection_pool.py           # 通用连接池基类
│   ├── auth.py                      # JWT 认证
│   ├── di_container.py              # 依赖注入容器
│   └── monitoring.py                # Prometheus 监控指标
│
├── interfaces/                      # 接口适配层
│   ├── gateways.py                  # ASR 网关（火山引擎连接池 + 腾讯云）
│   ├── asr_gateways.py              # ASR 网关工厂
│   ├── llm_gateways.py              # LLM 网关（OpenAI 兼容，支持工具调用循环）
│   ├── tts_gateways.py              # TTS 网关（火山引擎，支持 session 复用）
│   ├── controllers.py               # REST 控制器
│   └── presenters.py                # 输出呈现器
│
└── main.py                          # 入口：创建 FastAPI 应用并启动
```

---

## 四、核心模块详解

### 4.1 会话状态机 (session_fsm.py)

管理每个设备连接的对话状态，确保状态转换合法：

```
IDLE ──→ ASR ──→ LLM ──→ TTS ──→ ASR (循环)
  ▲        │                       │
  └────────┴───────────────────────┘
              (无语音/会话结束)
```

**合法转换**：
- `IDLE → ASR`：开始语音识别
- `ASR → LLM`：识别完成，进入大模型
- `ASR → IDLE`：无语音/超时，回到空闲
- `LLM → TTS`：模型回复，开始合成语音
- `TTS → ASR`：语音播放完成，开始下一轮识别
- `TTS → IDLE`：会话结束

**WSChannel**：WebSocket 唯一收发入口，使用单写队列化避免并发写入冲突。支持 `send_json()`、`send_bytes()`、`send_text()` 三种消息类型，所有消息通过内部队列串行发送。

### 4.2 会话核心 (session.py)

每个设备连接对应一个 `Session` 实例，管理完整的对话循环：

- **`start_auto_conversation()`**：启动 ASR → Pipeline → 下一轮 ASR 的自动循环
- **`_asr_streaming_loop()`**：ASR 流式识别核心，使用 `send_audio` + `recv_audio` 两个并发任务直接管理 WebSocket
- **`send_session_end()`**：发送 `iat_end` + `session_end` 让设备停止录音并进入待机
- **`queue_audio()`**：接收设备音频数据，入队到 ASR 音频队列
- **Watchdog**：监控 `asr_start_time` 和 `asr_last_result_time`，超时未收到有效语音则自动结束会话

### 4.3 4-Worker 流水线 (pipeline.py)

将 LLM 对话拆分为 4 个并发 Worker，通过三级背压队列连接：

```
LLM Worker ──(text_queue)──▶ Splitter ──(audio_queue)──▶ TTS Worker ──(send_queue)──▶ Sender Worker
   │                            │                           │                          │
   │ 流式输出 token             │ 句子分割                  │ 语音合成                 │ 帧封装+发送
   │                            │ "你好。" → 一句           │ 文本 → PCM 音频          │ SID+状态+音频
   ▼                            ▼                           ▼                          ▼
```

**队列策略**：
- `text_queue`：drop_oldest（文本产出快，丢弃最旧）
- `audio_queue`：block（句子不能丢，阻塞等待）
- `send_queue`：block（音频不能丢，阻塞等待）

**中断机制**：设置 `cancel_event`，所有 Worker 检测到后立即停止。`StopPipeline` 异常由工具抛出，直接终止流水线。

### 4.4 工具系统 (tools_system.py + builtin_tools.py)

支持 LLM 调用内置工具和 MCP 外部工具：

**内置工具注册**：
```python
from src.use_cases.tools_system import tool

@tool()
async def set_volume(level: int, tool_manager=None) -> str:
    """设置设备音量"""
    ...
```

**自动发现**：启动时扫描 `builtin_tools.py` 和 `custom/` 目录，自动注册所有 `@tool()` 装饰的函数。

**参数自动注入**：函数签名中的特殊参数会自动注入：
- `tool_manager` → PerUserToolManager 实例
- `channel` → WSChannel 实例
- `fsm` → SessionFSM 实例

**参数类型自动转换**：LLM 返回的参数可能是字符串（如 `"80"` 而非 `80`），`_coerce_args()` 会根据函数签名的类型注解自动转换。

**MCP 工具**：支持通过 MCP (Model Context Protocol) 连接外部工具服务器，每个用户可配置独立的 MCP 服务。

**熔断器**：工具调用失败超过阈值后自动熔断，防止级联故障。

### 4.5 ASR 网关 (gateways.py)

**火山引擎 ASR**：
- 使用二进制协议（4 字节头 + message_type + payload）
- 支持连接池预热，避免首次请求延迟
- 连接池只创建裸 WebSocket，config 在实际使用时发送
- `init_connection()` 发送配置并等待 ACK 确认

**腾讯云 ASR**：
- 使用签名 URL 建立 WebSocket 连接
- 文本协议（JSON 消息）

### 4.6 LLM 网关 (llm_gateways.py)

- 基于 OpenAI 兼容接口
- 支持流式输出（streaming）
- 支持工具调用循环（tool loop）：LLM 返回工具调用 → 执行工具 → 将结果回传 LLM → 继续对话
- 最多 5 轮工具调用循环，防止无限递归

### 4.7 TTS 网关 (tts_gateways.py)

- 火山引擎 TTS，WebSocket 协议
- 支持 session 复用（同一连接可连续合成多段文本）
- 返回 PCM 原始音频数据

### 4.8 设备通信协议

设备与服务端通过 WebSocket 通信，支持两种消息格式：

**JSON 消息**（控制指令）：
```json
{"type": "session_status", "status": "iat_start"}
{"type": "play_audio", "tts_task_id": "0010"}
{"type": "instruct", "command_id": "set_volume", "data": "0.8"}
```

**二进制消息**（音频数据）：
```
[会话ID 4字节] [状态码 2字节] [音频数据 ...]
```

会话 ID：
- `"0001"` = SID_CONNECTED（连接/问候）
- `"0010"` = SID_TTS（TTS 语音）
- `"1001"` = SID_WAKE（唤醒）
- `"1002"` = SID_REST（休息/待机）

状态码：
- `"00"` = 正常数据
- `"03"` = 结束帧

---

## 五、启动流程

```
main.py
  └── create_app()
        ├── lifespan() 启动生命周期
        │     ├── 加载配置 (config.py)
        │     ├── 初始化日志 (logging.py)
        │     ├── 初始化 ASR 网关 + 连接池预热
        │     ├── 初始化 LLM 网关
        │     ├── 初始化 TTS 网关
        │     ├── 自动发现工具 (tools_system.auto_discover())
        │     └── 加载设备配置 (users.json)
        │
        └── WebSocket 端点 /ws
              ├── 设备认证
              ├── 创建 Session + FSM + WSChannel
              ├── 注册到 DeviceRegistry
              ├── 发送问候语
              └── 进入消息循环
                    ├── 二进制消息 → queue_audio()
                    ├── JSON 消息 → 事件处理
                    └── 心跳保活
```

---

## 六、配置系统

使用 `pydantic-settings` 的 `BaseSettings`，支持三种配置来源（优先级从高到低）：

1. **环境变量**（最高优先级）
2. **`.env` 文件**（项目根目录）
3. **默认值**（代码中定义）

关键配置项：

| 环境变量 | 说明 | 默认值 |
|---|---|---|
| `ASR_PROVIDER` | ASR 提供商 | `tencent` |
| `VOLCENGINE_API_KEY` | 火山引擎 API Key | - |
| `LLM_API_KEY` | LLM API Key | - |
| `LLM_BASE_URL` | LLM API 地址 | - |
| `LLM_MODEL` | LLM 模型名称 | - |
| `TTS_VOLCENGINE_API_KEY` | TTS API Key | - |
| `SERVER_PORT` | 服务端口 | `8088` |
| `NO_SPEECH_TIMEOUT` | 无语音超时(秒) | `5` |

---

## 七、日志系统

- **彩色输出**：按日志级别着色（DEBUG=青色, INFO=绿色, WARNING=黄色, ERROR=红色）
- **上下文注入**：每条日志自动包含 `[trace_id|session_id|device_id]`
- **colorama 兼容**：Windows 终端正常显示颜色
- **双格式**：控制台彩色文本 + 文件 JSON 格式

日志格式：
```
[12:00:00.123] [INFO] [trace_id|session_id|device_id] 消息内容
```
