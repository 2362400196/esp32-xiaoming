# 扩展 ASR/LLM/TTS 方案

小明同学 采用工厂模式 + 抽象基类设计，开发者可以方便地接入新的 ASR、LLM、TTS 厂商。

## ASR 语音识别

### 接口说明

ASR 网关位于 `src/interfaces/asr/` 目录，所有实现需继承 `BaseASRGateway`：

```
src/interfaces/asr/
├── base.py          # 抽象基类（含连接池可选支持）
├── factory.py       # 工厂函数
├── volcengine.py    # 火山引擎（支持连接池）
├── tencent.py       # 腾讯云（无连接池）
├── aliyun.py        # 阿里云（无连接池）
└── xunfei.py        # 讯飞（无连接池）
```

### 基类方法

```python
from src.interfaces.asr.base import BaseASRGateway

class MyASRGateway(BaseASRGateway):
    binary_protocol: bool = False  # 是否二进制协议
    _enable_pool: bool = False     # 是否启用连接池（火山引擎支持，腾讯默认禁用）

    def _build_url(self) -> str:
        """构建 WebSocket 连接 URL"""
        ...

    def _get_headers(self) -> dict:
        """获取请求头"""
        ...

    async def init_connection(self, ws) -> bool:
        """连接建立后的初始化握手"""
        ...

    async def send_audio_data(self, ws, audio_data: bytes) -> None:
        """发送音频数据（二进制或 JSON 帧，取决于协议）"""
        ...

    async def send_audio_end(self, ws) -> None:
        """发送音频结束标志"""
        ...

    def parse_response(self, response) -> dict | None:
        """解析服务端响应，返回识别结果"""
        ...

    async def disconnect(self) -> None:
        """关闭连接（ASRRepository 要求）"""
        ...
```

> **连接池说明**：火山引擎 ASR 支持连接池（`_enable_pool=True`），可复用 WebSocket 连接降低首字延迟。腾讯 ASR 硬编码禁用连接池（`_enable_pool=False`），每次识别新建连接，功能完整正常。`ASR_POOL_ENABLED=true` 仅对火山引擎生效，对其他 ASR 透明无影响。

### 实现示例

```python
# src/interfaces/asr/my_provider.py

from src.interfaces.asr.base import BaseASRGateway
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)

class MyASRGateway(BaseASRGateway):
    """自定义 ASR 网关"""

    def _build_url(self) -> str:
        api_key = self.config.get("api_key")
        return f"wss://asr.my-provider.com/v1/stream?key={api_key}"

    def _get_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.config.get('api_key')}"}

    async def recognize(self, audio_stream, **kwargs):
        async for audio_chunk in audio_stream:
            # 发送音频到 ASR 服务
            # 接收识别结果
            yield "识别文本"

    async def close(self):
        pass
```

### 注册到工厂

编辑 `src/interfaces/asr/factory.py`：

```python
from src.interfaces.asr.my_provider import MyASRGateway

def create_asr_gateway(provider: str = None, config: dict = None) -> BaseASRGateway:
    ...
    elif provider == "my_provider":
        my_config = {
            "api_key": config.get("api_key") or settings.asr.my_provider_api_key,
        }
        return MyASRGateway(my_config)
    ...
```

### 环境变量配置

在 `.env` 中添加：

```bash
ASR_PROVIDER=my_provider
ASR_MY_PROVIDER_API_KEY=your-api-key
```

### 连接池支持（可选）

如果自定义 ASR 支持 WebSocket 连接复用，可继承 `ConnectionPoolBase` 实现连接池：

```python
from src.infrastructure.connection_pool import ConnectionPoolBase

class MyASRConnectionPool(ConnectionPoolBase):
    def __init__(self, api_key: str, **kwargs):
        super().__init__(pool_name="my_asr", **kwargs)
        self._api_key = api_key

    async def _create_connection(self):
        """创建新连接，返回连接对象本身（池内部用 ConnectionWrapper 包装）"""
        return await websockets.connect(f"wss://asr.my-provider.com/v1/stream?key={self._api_key}")

    async def _heartbeat(self, conn) -> None:
        """发送心跳（如需要）"""
        ...

    async def _is_healthy(self, conn) -> bool:
        """检查连接是否健康"""
        return not conn.closed

    async def _close_connection(self, conn) -> None:
        """关闭连接"""
        await conn.close()
```

在网关中启用连接池：

```python
class MyASRGateway(BaseASRGateway):
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.api_key = config.get("api_key", "")
        settings = get_settings()
        self._enable_pool = config.get("enable_pool", settings.asr.enable_pool) and bool(self.api_key)

    @classmethod
    def get_pool(cls, config: dict = None) -> MyASRConnectionPool | None:
        if cls._pool is None or cls._pool.is_closed:
            cls._pool = MyASRConnectionPool(
                api_key=config.get("api_key", ""),
                max_size=settings.asr.pool_max_size,
                min_size=settings.asr.pool_min_size,
            )
        return cls._pool
```

> **注意**：不支持连接池的 ASR 无需实现上述代码。设置 `_enable_pool = False` 后，系统会在每次识别时新建连接，功能完全正常。`ASR_POOL_ENABLED=true` 对不支持连接池的 ASR 透明无影响。

---

## LLM 大语言模型

### 接口说明

LLM 网关位于 `src/interfaces/llm_gateways.py`，当前仅内置 `OpenAILLMGateway`（兼容所有 OpenAI 格式的 API，如 DeepSeek、GPT 等）。领域层定义了 `LLMRepository` 抽象基类，但 `OpenAILLMGateway` 尚未继承它，这是已知的架构债，后续版本会统一。

### 核心常量

| 常量 | 值 | 说明 |
|------|-----|------|
| `MAX_TOOL_ROUNDS` | 10 | 工具调用最大轮次，超过后强制结束并返回提示 |
| `LLM_MAX_RETRIES` | 3 | API 调用失败重试次数 |
| `LLM_RETRY_DELAY` | 1.5 | 退避基数，指数退避 `1.5 * 2^attempt` |

### 核心方法

```python
class OpenAILLMGateway:
    def __init__(self, config=None, tool_manager=None):
        """
        config 字段：
        - api_key: API 密钥
        - base_url: API 地址
        - model: 模型名
        - system_prompt: 系统提示词
        - temperature: 温度参数（默认 0.7）
        - max_tokens: 最大 Token（默认 2000）
        """

    async def stream_chat(self, messages, user_config=None, device_id=None):
        """主流式方法（含工具调用循环），yield str"""
        pass

    async def process_text(self, text, user_config=None, device_id=None) -> str:
        """非流式生成"""
        pass

    async def generate(self, messages, **kwargs) -> str:
        """通用非流式生成"""
        pass

    async def generate_stream(self, messages, **kwargs):
        """通用流式生成，末尾 yield 工具调用 JSON"""
        pass

    async def generate_response_stream(self, text, ...):
        """流式 + Prometheus 指标"""
        pass

    async def call_tool(self, tool_name, arguments, **kwargs):
        """调用工具"""
        pass
```

### stream_chat yield 协议

`stream_chat` 是 Pipeline 调用的核心方法，yield 的全部是 `str` 类型：

| yield 值 | 含义 |
|----------|------|
| `delta.content`（文本片段） | LLM 流式输出的增量文本 |
| `"__STOP_PIPELINE__"` | 工具调用抛出 `StopPipeline`，通知上游终止 Pipeline |
| `"LLM error: {e}"` | 异常后错误文本 |
| `"LLM not configured - this is a mock response"` | 未配置 api_key |
| `"Maximum tool call rounds reached..."` | 超过 10 轮工具调用 |

### 工具调用循环（Function Calling）

`stream_chat` 内置工具调用循环，最多 10 轮：

```
用户消息 → LLM 流式生成
              ↓
         收集 delta.content（yield 给上游）+ delta.tool_calls
              ↓
         有 tool_calls?
         ├─ 否 → 正则检测 read_skill_document("xxx") → 自动构造工具调用
         │       否则 return（结束）
         └─ 是 → 构造 assistant_msg（含 tool_calls）append 到 messages
              ↓
         对每个 tool_call：
         ├─ (name, args) 在 failed_tool_calls 中 → 跳过
         └─ 调用 tool_manager.call_tool(name, args)
              ├─ 抛出 StopPipeline → yield "__STOP_PIPELINE__" → return
              └─ 结果含 "unavailable/失败" → 加入 failed_tool_calls
              ↓
         messages.append({"role":"tool", "tool_call_id":..., "content":...})
              ↓
         再次流式调用 LLM（带工具结果）→ 循环
```

工具调用的 JSON 格式遵循 OpenAI Function Calling 标准：

```json
{"id":"call_xxx","type":"function","function":{"name":"...","arguments":"{...}"}}
```

流式中 `delta.tool_calls` 按 `tc.index` 聚合，`arguments` 为分片累加的字符串拼接。

### 关键特性

| 特性 | 说明 |
|------|------|
| **失败去重** | `failed_tool_calls: set` 记录 `(name, args_json)`，结果含 "unavailable/failed/暂不可用/失败" 时加入，后续同参数调用直接返回"不可用"提示 |
| **即时反馈** | 首次检测到 tool_calls 时，通过 `channel.send_json` 发送 `on_tool_status` 指令反馈"正在处理中..."，避免干扰 TTS 文字同步 |
| **reasoning_content** | 兼容 DeepSeek 等推理模型，`hasattr(delta, "reasoning_content")` 检测 |
| **trace_id 传播** | 从 contextvar 读取 trace_id，放入 `X-Trace-Id` header 传给下游 LLM |
| **重试策略** | 捕获 `RateLimitError`、`APIConnectionError`、`APITimeoutError`、5xx `APIError`，指数退避；4xx 直接抛出 |
| **按设备覆盖** | `_resolve_config` 支持 `user_config` 为 dict 或对象，支持 `device_overrides[device_id]` 按设备覆盖 model/system_prompt |

### StopPipeline 异常处理

工具执行抛出 `StopPipeline`（定义于 `stop_pipeline.py`，从 `tools_system.py` 重新导出）时，`stream_chat` 捕获后 `yield "__STOP_PIPELINE__"` 并 `return`。外层 `except StopPipeline: raise` 向上传播，不让通用 `Exception` 捕获吞掉。详见 [Pipeline 流式处理](./pipeline.md#stoppipeline-机制)。

### 实现自定义 LLM

```python
# src/interfaces/my_llm_gateway.py

class CustomLLMGateway:
    def __init__(self, config=None, tool_manager=None):
        self.api_key = config.get("api_key", "")
        self.base_url = config.get("base_url", "")
        self.model = config.get("model", "")
        self.system_prompt = config.get("system_prompt", "")
        self.temperature = config.get("temperature", 0.7)
        self.tool_manager = tool_manager

    async def stream_chat(self, messages, user_config=None, device_id=None):
        """实现流式对话逻辑
        必须支持工具调用循环（参考 OpenAILLMGateway）
        yield str 类型：文本片段 或 "__STOP_PIPELINE__" 或 "LLM error: ..."
        """
        # 1. 构建请求参数
        # 2. 调用 API
        # 3. 流式 yield 文本片段
        # 4. 检测 tool_calls，调用 tool_manager.call_tool
        # 5. 工具结果注入后再次调用 LLM
        yield "回复内容"
```

### 注册工厂

`create_llm_gateway()`（`llm_gateways.py` 约第 813 行）当前**不读取 provider**，任何情况下都返回 `OpenAILLMGateway`（兼容所有 OpenAI 格式 API，如 DeepSeek、GPT）：

```python
def create_llm_gateway(config=None, tool_manager=None):
    # 当前实现：直接返回 OpenAILLMGateway
    return OpenAILLMGateway(config=config, tool_manager=tool_manager)
```

> `LLM_PROVIDER` 环境变量当前对工厂无效；如需接入自定义协议，需自行在 `create_llm_gateway` 中增加分支。

### 环境变量配置

在 `.env` 中添加：

```bash
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://api.your-provider.com/v1
LLM_MODEL=your-model-name
```

多设备模式下，可在数据库 `devices` 表中为单个设备配置独立的 LLM 参数（`llm_api_key`、`llm_base_url`、`llm_model`、`llm_system_prompt`），优先级高于全局环境变量。

---

## TTS 语音合成

### 接口说明

TTS 网关位于 `src/interfaces/tts_gateways.py`，领域层定义了 `TTSRepository` 抽象基类，抽象方法为 `synthesize(text)` 和 `synthesize_stream(text)`。当前内置 `VolcEngineTTSGateway`（火山引擎），基于火山引擎 V3 二进制 WebSocket 协议实现流式合成。

### 抽象基类

```python
# domain/repositories.py
class TTSRepository(ABC):
    @abstractmethod
    async def synthesize(self, text: str) -> bytes:
        """同步合成，返回完整音频"""
        ...

    @abstractmethod
    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """流式合成，yield bytes 音频块"""
        ...
```

### VolcEngineTTSGateway 实现要点

| 特性 | 说明 |
|------|------|
| **协议** | 火山引擎 V3 二进制 WebSocket 协议（`Message.marshal/unmarshal`） |
| **连接地址** | `wss://openspeech.bytedance.com/api/v3/tts/unidirectional/stream` |
| **音频格式** | MP3，采样率 24000Hz |
| **yield 类型** | `bytes`（MP3 音频块，来自 `msg.payload`） |
| **消息类型** | `FullClientRequest`、`FullServerResponse`、`AudioOnlyServer`、`Error` |
| **事件类型** | `StartConnection`、`SessionStarted/Finished/Failed`、`TTSResponse` |

### 流式合成协议

`synthesize_stream(text, cancel_event=None) -> AsyncIterator[bytes]` 的接收循环：

```
建立 WebSocket 连接 → 发送 StartConnection 请求
  ↓
接收消息循环：
  ├─ AudioOnlyServer → yield msg.payload（MP3 音频块）
  ├─ FullServerResponse + SessionFinished → return（合成完成）
  └─ SessionFailed / Error → return（记录错误）
```

请求体结构：

```json
{
  "user": {"uid": "uuid"},
  "req_params": {
    "speaker": "voice_type",
    "audio_params": {
      "format": "mp3",
      "sample_rate": 24000,
      "speed_ratio": 1.0,
      "volume_ratio": 1.0,
      "pitch_ratio": 1.0
    },
    "text": "合成文本"
  }
}
```

### 连接超时与重试

| 参数 | 值 | 说明 |
|------|-----|------|
| `_connection_timeout` | 15s | 建立连接超时 |
| `_message_timeout` | 20s | 单条消息接收超时 |
| `_ping_interval` | 30s | WebSocket 心跳间隔 |
| `_max_retries` | 3 | 连接异常重试次数 |

### 连接池机制

`VolcEngineTTSConnectionPool` 继承 `ConnectionPoolBase`，支持 WebSocket 连接复用：

| 方法 | 说明 |
|------|------|
| `get_pool()` | 类方法，单例获取连接池，首次创建时 `asyncio.create_task(pool.warm_up())` 预热 |
| `synthesize_stream_with_pool()` | 连接池版本，异常时回退到普通 `synthesize_stream` |
| `TTSSession` | 会话封装，支持 `_reconnect()`（关闭旧 WS → 新建），`_is_expired(max_idle=30s)` 过期检测 |

连接池参数（`pool_max_size`、`pool_min_size`、`heartbeat_interval`、`idle_timeout`、`connection_timeout`）由 settings 配置。

### 时长估算

TTS 网关层不实现时长估算，由上层 Pipeline 处理。Pipeline 中的估算公式：

```
estimated_duration_ms = cn_chars * 230 + en_chars * 90
```

下限 500ms。合成完成后按实际音频字节数修正（假设 64kbps CBR）：`est_by_bytes = total_audio_bytes * 8 // 64`，偏差 >200ms 时覆盖估算值。详见 [Pipeline 流式处理](./pipeline.md#tts-时长估算)。

### 实现自定义 TTS

```python
# src/interfaces/my_tts_gateway.py

from typing import AsyncIterator
from src.domain.repositories import TTSRepository

class CustomTTSGateway(TTSRepository):
    def __init__(self, config: dict = None):
        self.api_key = config.get("api_key", "")
        self.voice_type = config.get("voice_type", "")
        self.speed = config.get("speed_ratio", 1.0)

    async def synthesize(self, text: str) -> bytes:
        """同步合成，返回完整音频字节"""
        # 1. 调用 TTS API
        # 2. 收集所有音频块
        return b"complete_audio_data"

    async def synthesize_stream(self, text: str, cancel_event=None) -> AsyncIterator[bytes]:
        """流式合成，yield bytes 音频块
        Pipeline 会调用此方法，每帧音频通过 voice_generator.make_tts_frame 包装后入队
        """
        # 1. 建立 WebSocket 或 HTTP 流式连接
        # 2. 流式接收音频数据
        async for chunk in audio_stream:
            if cancel_event and cancel_event.is_set():
                break
            yield chunk  # bytes 类型
```

### 注册工厂

`create_tts_gateway()`（`tts_gateways.py` 约第 853 行）当前**仅内置火山引擎分支**，provider 取任何其他值也返回 `VolcEngineTTSGateway`：

```python
def create_tts_gateway(config: dict | None = None):
    # 当前实现：仅支持火山引擎
    return VolcEngineTTSGateway(config=config)
```

> `TTS_PROVIDER=custom` 当前不会创建自定义 TTS；如需接入自定义 TTS，需在 `create_tts_gateway` 中增加分支。

### 环境变量配置

在 `.env` 中添加：

```bash
TTS_VOLCENGINE_API_KEY=your-api-key
TTS_VOLCENGINE_VOICE_TYPE=your-voice-id
```

多设备模式下，可在数据库 `devices` 表中为单个设备配置 `tts_config`（含 `provider`、`api_key`、`voice_type`、`speed_ratio` 等字段），优先级高于全局环境变量。

---

## 音频格式规范

| 参数 | ASR 输入 | TTS 输出 |
|------|---------|---------|
| 采样率 | 16000 Hz | 24000 Hz |
| 位深 | 16 bit | —（MP3 压缩格式）|
| 声道 | 单声道 | 单声道 |
| 编码 | PCM | MP3 |
| 帧大小 | 每帧约 320 字节（20ms）| —（MP3 帧）|

## 完整接入步骤

1. 在对应目录下创建实现文件
2. 实现抽象基类的所有抽象方法
3. 在工厂函数中添加分支
4. 在 `.env` 中配置厂商选择参数
5. 重启服务验证
