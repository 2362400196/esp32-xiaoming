# ESP-AI-Server 开发者指南

> 本文档面向需要在 ESP-AI-Server 上开发新功能、修改现有逻辑的开发者。
> 请先阅读 `architecture.md` 了解整体架构设计。

---

## 一、目录结构与职责

```
src/
├── domain/                  # 领域层（最内层，零依赖）
│   ├── entities.py          # 实体：Session, Device, Conversation, Message
│   ├── exceptions.py        # 异常层级
│   ├── repositories.py      # 仓储接口（预留，未实现）
│   ├── services.py          # 领域服务接口
│   └── value_objects.py     # 值对象
│
├── use_cases/               # 用例层（核心业务逻辑）
│   ├── session.py           # 会话核心：ASR 流式循环、对话循环
│   ├── pipeline.py          # 4-Worker 流水线：LLM → Splitter → TTS → Sender
│   ├── session_fsm.py       # 状态机 + WebSocket 通道
│   ├── tools_system.py      # 工具框架：@tool 装饰器、ToolManager、MCP
│   ├── builtin_tools.py     # 内置工具
│   ├── custom/              # 自定义工具目录
│   ├── queues.py            # 三级背压队列
│   ├── voice_generator.py   # TTS 音频帧生成器
│   ├── device_registry.py   # 设备注册表
│   ├── device_config.py     # 设备配置模型 + 加载器
│   ├── wake_audio.py        # 唤醒音频管理器
│   ├── emotion.py           # 情绪检测与渲染
│   ├── image_sender.py      # 图片发送
│   ├── memory.py            # 对话记忆
│   ├── audio_processor.py   # 音频处理
│   ├── speaker.py           # 语音播报
│   ├── auth_service.py      # 认证服务
│   ├── ports.py             # 端口接口（预留）
│   └── dtos.py              # 数据传输对象（预留）
│
├── interfaces/              # 接口适配层（外部服务适配器）
│   ├── asr_gateways.py      # ASR 网关（火山引擎、腾讯云）
│   ├── llm_gateways.py      # LLM 网关（OpenAI 兼容）
│   ├── tts_gateways.py      # TTS 网关（火山引擎）
│   ├── websocket_handler.py # WebSocket 连接处理器
│   └── controllers.py       # REST 控制器（预留）
│
├── infrastructure/          # 基础设施层（框架、配置、IO）
│   ├── web.py               # FastAPI 应用、路由注册、启动生命周期
│   ├── config.py            # 配置管理（pydantic-settings）
│   ├── logging.py           # 日志系统
│   ├── device_api.py        # REST API 路由
│   ├── connection_pool.py   # 连接池
│   ├── concurrency.py       # 并发控制
│   ├── monitoring.py        # Prometheus 监控
│   ├── remote_config.py     # 远程配置
│   └── repositories.py      # 仓储实现（预留）
│
├── docs/                    # 文档
│   ├── architecture.md      # 架构设计
│   ├── developer-guide.md   # 本文件
│   └── device-api.md        # API 文档
│
└── main.py                  # 入口
```

### 依赖方向

```
domain  ←  use_cases  ←  interfaces  ←  infrastructure
(最内层)                                  (最外层)
```

**铁律**：内层不能 import 外层。详见下文"依赖规则"。

---

## 二、分层职责

### 2.1 Domain 层（`domain/`）

只包含纯 Python 数据类和接口定义。**不依赖任何其他层**。

```python
# ✅ 正确：纯数据类，无外部依赖
@dataclass
class Message:
    role: str
    content: str
    timestamp: float = field(default_factory=time.time)
```

**可以放什么**：
- 实体（Entity）：有唯一标识的业务对象
- 值对象（Value Object）：不可变的概念性对象
- 异常类
- 仓储接口（Repository Interface）

**不能放什么**：
- 数据库访问
- 网络请求
- 框架代码（FastAPI、aiohttp 等）

---

### 2.2 Use Cases 层（`use_cases/`）

核心业务逻辑。**可以引用 domain 层，不能引用 interfaces 或 infrastructure**。

```python
# ❌ 错误
from src.infrastructure.config import get_settings  # 内层不能 import 外层

# ✅ 正确：通过 __init__ 参数注入
class Pipeline:
    def __init__(self, config: dict, ...):
        self._config = config
```

**例外**：`get_settings()` 目前仍在多处使用，属于过渡状态。新代码应通过构造器注入配置。

**每个文件只放一个类/职责**（已经拆分完毕）：

| 文件 | 职责 |
|------|------|
| `session.py` | 会话生命周期管理 |
| `pipeline.py` | 4-Worker 流水线 |
| `device_registry.py` | 设备注册与查找 |
| `device_config.py` | 设备配置加载 |
| `speaker.py` | 语音播报与唤醒 |
| `wake_audio.py` | 唤醒音频合成与播放 |
| `auth_service.py` | 设备认证 |
| ... | ... |

---

### 2.3 Interfaces 层（`interfaces/`）

外部服务的适配器，将外部世界转化为 use_cases 能理解的调用。

```python
# 所有 ASR 厂商实现同一接口
class VolcEngineASRGateway:
    async def transcribe(self, audio: bytes) -> str: ...

class TencentASRGateway:
    async def transcribe(self, audio: bytes) -> str: ...
```

**职责**：
- ASR/LLM/TTS 网关实现
- WebSocket 连接处理器（`websocket_handler.py`）
- 请求/响应格式转换

---

### 2.4 Infrastructure 层（`infrastructure/`）

框架集成、配置、IO。**可以引用所有内层**。

```python
# ✅ 正确：基础设施层可以引用内层
from src.use_cases.device_registry import DeviceRegistry
from src.interfaces.websocket_handler import handle_websocket
```

**职责**：
- FastAPI 路由注册
- 配置加载（`.env`）
- 日志系统
- 数据库访问（预留）

---

## 三、依赖规则

### 3.1 基本原则

| 层 | 可以依赖 | 禁止依赖 |
|----|---------|---------|
| Domain | 无 | 所有外层 |
| Use Cases | Domain | Interfaces, Infrastructure |
| Interfaces | Domain, Use Cases | Infrastructure（最好通过 DI） |
| Infrastructure | 所有内层 | 无 |

### 3.2 配置读取规则

**新代码**：通过构造器注入配置，不要直接调用 `get_settings()`：

```python
# ✅ 正确
class MyService:
    def __init__(self, config: dict):
        self._timeout = config.get("timeout", 30)

# ❌ 错误
class MyService:
    def __init__(self):
        from src.infrastructure.config import get_settings
        self._timeout = get_settings().server.timeout
```

**为什么要禁止直接 import get_settings**：
- 导致 use_cases 层依赖 infrastructure
- 单元测试时需要 mock 全局单例
- 违反 Clean Architecture 的依赖方向

### 3.3 跨层调用

内层对外层的调用必须通过**依赖注入**或**接口反转**：

```python
# use_cases/speaker.py 需要发 WebSocket 消息
# ✅ 正确：通过接口抽象
class Speaker:
    def __init__(self, channel):  # channel 由外层注入
        self._channel = channel

# infrastructure/web.py 注入实现
speaker = Speaker(channel=WSChannel(websocket))
```

---

## 四、模块设计规范

### 4.1 文件原则

| 原则 | 说明 |
|------|------|
| **单一职责** | 一个文件只做一件事。超过 300 行考虑拆分 |
| **显式 import** | 不要用 `from x import *`，不要依赖 `__init__.py` 的 `__getattr__` 延迟加载 |
| **类型注解** | 所有函数参数和返回值必须有类型注解 |

### 4.2 新增功能流程

1. **确定归属层**：这个逻辑属于哪个层？
   - 数据模型 → `domain/`
   - 业务逻辑 → `use_cases/`
   - 外部服务适配 → `interfaces/`
   - 框架/配置/IO → `infrastructure/`
2. **定义接口**：在恰当的层定义接口（Port）
3. **实现**：在外层实现接口（Adapter）
4. **注册**：在 `infrastructure/web.py` 的 `_register_routes` 或 `lifespan` 中注册

### 4.3 新工具开发

在 `use_cases/builtin_tools.py` 或 `use_cases/custom/` 中添加：

```python
from src.use_cases.tools_system import tool

@tool()
async def my_tool(param1: str, param2: int = 0, tool_manager=None) -> str:
    """工具描述（LLM 会读取这个 docstring）"""
    # 实现逻辑
    return "结果"
```

### 4.4 新 REST API

在 `infrastructure/device_api.py` 中添加路由。如果是简单端点也可以在 `infrastructure/web.py` 的 `_register_routes` 中添加。

```python
@router.post("/devices/{mac}/my-action", response_model=DeviceControlResponse)
async def my_action(mac: str, x_api_key: str = Header(None)) -> DeviceControlResponse:
    await verify_api_key(x_api_key)
    # ... 实现
```

---

## 五、常见问题

### Q: 为什么我的代码不能 import `get_settings`？

`get_settings()` 在 `infrastructure/config.py` 中。如果你的代码在 `use_cases/` 或 `domain/` 中，不应该直接 import。改为通过构造器注入配置：

```python
class MyService:
    def __init__(self, api_key: str = "", timeout: int = 30):
        self._api_key = api_key
        self._timeout = timeout
```

### Q: WebSocket 处理器在哪里？

在 `src/interfaces/websocket_handler.py` 中。`infrastructure/web.py` 只负责注册路由：

```python
from src.interfaces.websocket_handler import handle_websocket
app.websocket("/")(handle_websocket)
```

### Q: 要添加一个新的 ASR 厂商怎么办？

1. 在 `interfaces/asr_gateways.py` 中实现网关
2. 在 `interfaces/gateways.py` 的 `create_asr_gateway()` 工厂函数中添加分支
3. `use_cases` 层无需改动

### Q: `auxiliary_services.py` 怎么是空的？

它现在是一个**向后兼容的 re-export 入口**。所有类已拆分到 `use_cases/` 下的独立文件：

| 原来在 auxiliary_services.py | 现在在 |
|---|---|
| `DeviceRegistry` | `use_cases/device_registry.py` |
| `DeviceConfig`, `DeviceManager`, `load_devices` | `use_cases/device_config.py` |
| `WakeAudioManager` | `use_cases/wake_audio.py` |
| `EmotionDetector`, `EmotionRenderer` | `use_cases/emotion.py` |
| `ImageSender` | `use_cases/image_sender.py` |
| `ConversationMemory` | `use_cases/memory.py` |
| `AudioProcessor` | `use_cases/audio_processor.py` |
| `Speaker` | `use_cases/speaker.py` |
| `AuthService` + 工厂函数 | `use_cases/auth_service.py` |

新代码请直接从对应文件 import：

```python
# ✅ 新代码
from src.use_cases.device_registry import DeviceRegistry
from src.use_cases.speaker import Speaker

# ❌ 旧方式（仍然可用但不推荐）
from src.use_cases.auxiliary_services import DeviceRegistry
```

---

## 六、启动流程

```
main.py
  └── create_app()
        ├── lifespan()  # 启动生命周期
        │     ├── 加载配置
        │     ├── 初始化日志
        │     ├── 初始化 ASR/LLM/TTS 网关
        │     ├── 自动发现工具
        │     └── 加载设备配置 (users.json)
        │
        └── _register_routes(app)
              ├── 注册 REST API（device_api.py）
              ├── 注册 WebSocket（websocket_handler.py）
              ├── 注册健康检查 /metrics /stats
              └── 注册简化版 API
```

---

## 七、测试

```bash
# 运行全部测试
pytest tests/

# 运行特定测试
pytest tests/test_pipeline.py -v
```

测试文件在 `tests/` 目录下，按模块命名。
