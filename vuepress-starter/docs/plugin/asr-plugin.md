# ASR 插件开发教程
::: tip 先看这个
编写前建议先阅读 [插件开发教程](./plugin-dev.md) 了解插件基础概念，以及 [插件公共工具库（Plugin SDK）](./plugin-sdk.md) 了解 SDK 提供的 WebSocket 封装。
:::

ASR 插件把外部语音识别服务接入系统：设备采集的麦克风音频实时流给插件，插件返回识别文本。本篇以火山引擎为例给出可直接改编的完整实现。

开发者只需要关心两件事：**按契约实现 5 个工具**（下文表格），以及**对接你选择的 ASR 厂商协议**（直接改编文中的完整示例）。系统如何调度插件、如何与设备对接，框架已全部处理，无需了解。

先读 [插件开发教程](./plugin-dev.md) 了解基础概念，SDK 的 WebSocket 封装见 [Plugin SDK](./plugin-sdk.md)。

## 一、工具约定（系统契约）

系统通过 `service_plugin_adapter.py` 调用 ASR 插件，**工具名必须严格遵循以下约定**（插件 id 前缀 + 固定后缀）：

| 工具全名 | 参数 | 返回 |
|---------|------|------|
| `{id}_start_session` | `config: dict` | `{"session_id": str, "error": str\|null}` |
| `{id}_send_audio` | `session_id: str, audio: str`（base64） | `{"text": str, "is_final": bool, "error": str\|null}` |
| `{id}_get_result` | `session_id: str` | `{"text": str, "is_final": bool, "error": str\|null}` |
| `{id}_end_session` | `session_id: str` | `{"final_text": str, "error": str\|null}` |
| `{id}_prewarm`（可选） | `config: dict` | `{"created": int, "error": str\|null}` |

::: warning 工具名必须匹配
插件加载器会校验：声明 `provides.asr` 的插件**必须**实现 `start_session`、`send_audio`、`get_result`、`end_session` 四个后缀工具，否则该服务不会被注册，并会在日志中报错：

```
[插件] asr_xxx 声明提供 asr 服务，但缺少必需工具 [...]。请按约定实现 [...]，该服务未注册。
```
:::

### 1.1 返回值约定

所有 ASR 工具返回**结构化 dict**（而非文本），统一格式：

```python
# 开始类
{"session_id": str, "error": str | None}
# 传输/查询类
{"text": str, "is_final": bool, "error": str | None}
# 结束类
{"final_text": str, "error": str | None}
```

- 成功时 `error` 为 `None`，失败时返回可读的中文错误
- 上层根据 `error` 判断是否继续，`is_final` 为 `True` 表示该句已定稿

::: warning 必须 `cache=False`
ASR 工具**全部**要设 `@tool(cache=False)`。默认缓存会在相同参数下 300 秒内跳过函数体，导致第二次识别直接返回旧结果。
:::

## 二、完整代码实现

下面以**火山引擎 ASR 插件**（`asr_volcengine`）为例，给出完整可运行的实现。这是系统内置的参考实现，可直接作为模板。

### 2.1 文件结构

```
asr_volcengine/
├── manifest.json    # 插件元数据（声明 provides.asr）
└── plugin.py        # 工具实现
```

### 2.2 manifest.json

```json
{
    "id": "asr_volcengine",
    "name": "火山引擎 ASR 提供商",
    "version": "1.0.0",
    "author": "system",
    "description": "通过火山引擎 ASR WebSocket 接口提供实时语音识别服务",
    "api_version": "1.0",
    "optional": true,
    "permissions": ["network"],
    "provides": {
        "asr": ["volcengine"]
    }
}
```

字段说明：

- `permissions: ["network"]`：WebSocket 连接需要 `network` 权限
- `provides: {"asr": ["volcengine"]}`：声明本插件提供 `asr` 服务，Provider 名为 `volcengine`。系统按此注册服务，`volcengine` 可用于多 Provider 路由
- `optional: true`：该插件为可选服务，不强制安装

::: tip 关于 config_fields（可省略）
ASR/LLM/TTS 服务插件**不需要**在 manifest 中声明 `config_fields`。这类服务的配置由框架统一管理：设备配置通过接口保存到 `devices.plugin_configs`，运行时框架自动合并进插件的 `config` 参数，插件用 `config.get("api_key")` 读取即可。

声明 `config_fields` 仅有两个作用：① 配置保存接口的键名白名单校验（防止拼错键名）；② 前端配置表单的字段元数据（标签/类型/默认值）。对服务插件而言这两者都不是必需的，因此可以省略，配置保存接口会接受任意键。
:::

### 2.3 plugin.py 完整代码

```python
"""火山引擎 ASR 服务插件。

使用 WebSocket SDK 连接火山引擎 ASR 服务（SAUC 协议），实现流式语音识别。
插件开发者只需关注协议拼装和解析，SDK 封装了 WebSocket 连接管理。
"""

from __future__ import annotations

import asyncio
import json
import struct
import uuid

from src.use_cases.sdk.tools import tool
from src.use_cases._plugin_helpers import ws_connect, ws_send, ws_recv, ws_close, ws_prewarm

# 火山引擎 ASR SAUC 地址
ASR_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"

# 会话缓存：session_id → {"ws_id": str, "current_text": str, "is_final": bool}
_sessions: dict[str, dict] = {}

# 互斥锁：防止多个协程并发 ws_recv 导致 "cannot call recv while another coroutine is running"
_ws_recv_lock = asyncio.Lock()


def _make_header(message_type: int, flags: int = 0) -> bytes:
    """构造 SAUC 协议 4 字节头部。"""
    version = 0x1 << 4
    header_size = 0x1 << 0
    byte0 = (version | header_size).to_bytes(1, "big")
    byte1 = ((message_type << 4) | flags).to_bytes(1, "big")
    serialization = 0x1 << 4  # JSON
    compression = 0x0 << 0
    byte2 = (serialization | compression).to_bytes(1, "big")
    byte3 = (0).to_bytes(1, "big")
    return byte0 + byte1 + byte2 + byte3


def _make_payload(data: dict) -> bytes:
    """构造 SAUC 协议 payload：4 字节长度 + JSON 数据。"""
    json_bytes = json.dumps(data).encode("utf-8")
    return struct.pack(">I", len(json_bytes)) + json_bytes


def _parse_response(data: bytes) -> dict | None:
    """解析 SAUC 协议响应帧。"""
    if len(data) < 12:
        return None
    payload_size = struct.unpack(">I", data[8:12])[0]
    if len(data) < 12 + payload_size:
        return None
    payload = data[12:12 + payload_size]
    try:
        return json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _extract_text(result: dict) -> str:
    """从 ASR 结果中提取文本。"""
    result_data = result.get("result", {})
    texts = result_data.get("texts", [])
    if texts:
        return texts[0].get("text", "")
    return result_data.get("text", "")


def _is_final(result: dict) -> bool:
    """判断 ASR 结果是否为最终结果。"""
    if result.get("is_final"):
        return True
    result_data = result.get("result", {})
    additions = result_data.get("additions", {})
    if additions.get("definite"):
        return True
    utterances = result_data.get("utterances", [])
    for utt in utterances:
        if utt.get("definite") and utt.get("text"):
            return True
    return False


@tool(cache=False)
async def asr_volcengine_prewarm(config: dict | None = None,
                                 tool_manager=None) -> dict:
    """预热 ASR WebSocket 连接池（设备连接时调用，确保首次语音输入免建连）。

    Args:
        config: 配置，包含 api_key, resource_id

    Returns:
        {"created": int, "error": str|null}
    """
    cfg = config or {}
    api_key = cfg.get("api_key", "")
    resource_id = cfg.get("resource_id", "volc.bigasr.sauc.duration")

    if not api_key:
        return {"created": 0, "error": "api_key 未配置"}

    headers = {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": resource_id,
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }
    try:
        created = await ws_prewarm(ASR_URL, headers, count=2,
                                   pool_headers=["X-Api-Key", "X-Api-Resource-Id"])
        return {"created": created, "error": None}
    except Exception as e:
        return {"created": 0, "error": f"预热失败: {e}"}


@tool(cache=False)
async def asr_volcengine_start_session(config: dict | None = None,
                                       tool_manager=None) -> dict:
    """开始 ASR 识别会话，返回 session_id。

    Args:
        config: 配置，包含 api_key, resource_id, model_name

    Returns:
        {"session_id": str, "error": str|null}
    """
    cfg = config or {}
    api_key = cfg.get("api_key", "")
    resource_id = cfg.get("resource_id", "volc.bigasr.sauc.duration")
    model_name = cfg.get("model_name", "bigmodel")

    if not api_key:
        return {"session_id": "", "error": "api_key 未配置"}

    headers = {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": resource_id,
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }

    # 先触发后台预取（为下次会话提前建连，预取 2 个保证池中有备用），再取当前连接
    try:
        asyncio.get_running_loop().create_task(
            ws_prewarm(ASR_URL, headers, count=2,
                       pool_headers=["X-Api-Key", "X-Api-Resource-Id"])
        )
    except Exception:
        pass

    # 从框架预热池取连接（prewarm 模式：取预热连接，会话结束真正关闭）
    try:
        ws_id = await ws_connect(ASR_URL, headers, pool="prewarm",
                                 pool_headers=["X-Api-Key", "X-Api-Resource-Id"])
    except Exception as e:
        return {"session_id": "", "error": f"WebSocket 连接失败: {e}"}

    # 发送初始化配置（SAUC 协议：message_type=1）
    config_request = _make_header(message_type=1, flags=0)
    config_payload = _make_payload({
        "user": {"uid": "esp-ai"},
        "audio": {
            "format": "pcm",
            "rate": 16000,
            "bits": 16,
            "channel": 1,
        },
        "request": {
            "model_name": model_name,
            "enable_itn": False,
            "enable_punc": False,
            "end_window_size": 400,
            "vad_segment_duration": 2000,
            "force_to_speech_time": 1000,
        },
    })
    await ws_send(ws_id, config_request + config_payload)

    sess_id = uuid.uuid4().hex[:8]
    _sessions[sess_id] = {
        "ws_id": ws_id,
        "current_text": "",
        "is_final": False,
        "buffer": [],
    }
    return {"session_id": sess_id, "error": None}


@tool(cache=False)
async def asr_volcengine_send_audio(session_id: str, audio: str,
                                    tool_manager=None) -> dict:
    """发送音频数据分片，返回当前识别结果。

    Args:
        session_id: 会话 ID（由 start_session 返回）
        audio: base64 编码的音频数据（16bit PCM，16000Hz 单声道）

    Returns:
        {"text": str, "is_final": bool, "error": str|null}
    """
    import base64

    session = _sessions.get(session_id)
    if not session:
        return {"text": "", "is_final": True, "error": "session not found"}

    audio_bytes = base64.b64decode(audio)

    # 发送音频数据（SAUC 协议：message_type=2），不等待结果
    audio_header = _make_header(message_type=2)
    audio_payload = struct.pack(">I", len(audio_bytes)) + audio_bytes
    try:
        await ws_send(session["ws_id"], audio_header + audio_payload)
    except Exception as e:
        return {"text": session["current_text"], "is_final": True,
                "error": f"发送音频失败: {e}"}

    return {"text": session["current_text"], "is_final": session.get("is_final", False), "error": None}


@tool(cache=False)
async def asr_volcengine_get_result(session_id: str, tool_manager=None) -> dict:
    """获取当前识别结果。

    Args:
        session_id: 会话 ID

    Returns:
        {"text": str, "is_final": bool, "error": str|null}
    """
    session = _sessions.get(session_id)
    if not session:
        return {"text": "", "is_final": True, "error": "session not found"}

    # 尝试接收最新结果
    try:
        data = await ws_recv(session["ws_id"], timeout=0.1)
        if data:
            result = _parse_response(data)
            if result:
                text = _extract_text(result)
                if text:
                    session["current_text"] = text
                if _is_final(result):
                    session["is_final"] = True
    except Exception as e:
        # 连接已断开等致命错误：不再吞掉，让上层立即终止会话
        return {"text": session["current_text"], "is_final": True,
                "error": f"接收失败: {e}"}

    return {
        "text": session["current_text"],
        "is_final": session.get("is_final", False),
        "error": None,
    }


@tool(cache=False)
async def asr_volcengine_end_session(session_id: str,
                                     tool_manager=None) -> dict:
    """结束 ASR 会话，返回最终识别结果。

    Args:
        session_id: 会话 ID

    Returns:
        {"final_text": str, "error": str|null}
    """
    session = _sessions.pop(session_id, None)
    if not session:
        return {"final_text": "", "error": "session not found"}

    # 发送结束信号（SAUC 协议：message_type=2, flags=2）
    # 注意：结束帧也必须带 4 字节 payload 长度前缀（值为 0），
    # 否则火山报 "parse payload size failed: body too short" 并强制断连
    try:
        end_frame = _make_header(message_type=2, flags=2) + struct.pack(">I", 0)
        await ws_send(session["ws_id"], end_frame)
    except Exception as e:
        return {"final_text": session["current_text"], "error": f"发送结束帧失败: {e}"}

    # 读取最终结果
    final_text = session["current_text"]
    try:
        while True:
            data = await ws_recv(session["ws_id"], timeout=0.5)
            if data is None:
                break
            result = _parse_response(data)
            if result:
                text = _extract_text(result)
                if text:
                    final_text = text
                if _is_final(result) or result.get("code") == 0:
                    break
    except Exception:
        pass

    # 关闭连接
    try:
        await ws_close(session["ws_id"])
    except Exception:
        pass

    return {"final_text": final_text, "error": None}
```

## 三、关键点与常见坑

### 3.1 音频格式必须匹配

火山 ASR 要求 **16bit PCM / 16kHz / 单声道**。设备端麦克风采集后需转成该格式，再 base64 编码传给 `send_audio`。格式不匹配会导致识别结果乱码或识别失败。

### 3.2 结束帧的坑

**结束帧也必须带 4 字节 payload 长度前缀（值为 0）**，否则火山报 `parse payload size failed: body too short` 并强制断连：

```python
end_frame = _make_header(message_type=2, flags=2) + struct.pack(">I", 0)
```

### 3.3 增量结果 vs 最终结果

`get_result` 返回的 `text` 是**累计文本**（服务端回传的是全量，不是增量），`is_final` 为 `True` 时表示该句已定稿。上层拿到 `is_final=True` 后即可停止轮询，进入 LLM 阶段。

### 3.4 连接池预热（可选但强烈推荐）

ASR 连接建立耗时约几百毫秒，直接影响**首字延迟**。参考实现通过 `ws_prewarm` 在设备连接时预热连接池，并在每次 `start_session` 时后台预取 2 个连接：

```python
# 设备连接时预热（prewarm 工具，由框架在设备连接时调用）
created = await ws_prewarm(ASR_URL, headers, count=2,
                           pool_headers=["X-Api-Key", "X-Api-Resource-Id"])

# start_session 时从预热池取连接
ws_id = await ws_connect(ASR_URL, headers, pool="prewarm",
                         pool_headers=["X-Api-Key", "X-Api-Resource-Id"])
```

- `pool="prewarm"`：从预热池取连接，会话结束后真正关闭（ASR 连接是一次性的）
- `pool_headers`：指定哪些 header 参与连接池分组，避免不同 API Key 的连接混用

## 四、安装与配置

### 4.1 打包上传

将 `manifest.json` 和 `plugin.py` 打成 zip 包：

::: code-tabs#shell
@tab bash
```bash
cd asr_volcengine
zip -r asr_volcengine-1.0.0.zip manifest.json plugin.py
```
@tab PowerShell
```powershell
Compress-Archive -Path manifest.json,plugin.py -DestinationPath asr_volcengine-1.0.0.zip
```
:::

登录 Web 管理界面 → **插件市场 → 开发者** tab → 开启开发者模式 → 拖入 zip 上传。

### 4.2 配置 API Key

安装后在设备级插件配置中填写：

| 配置项 | 说明 |
|--------|------|
| `api_key` | 火山引擎语音服务 API Key |
| `resource_id` | 资源 ID，如 `volc.bigasr.sauc.duration` |
| `model` | 模型名，如 `volc.asr.222222222` |

### 4.3 验证生效

上传并配置后，查看服务端日志确认服务已注册：

```
[插件服务] asr_volcengine 注册 asr 服务: volcengine
[WS] 使用 ASR 插件网关
```

设备连接时日志出现 `[WS] 使用 ASR 插件网关` 即表示插件模式生效。若日志出现"缺少必需工具"报错，说明工具名不符合约定，服务未注册。

## 五、调试与排错

### 5.1 日志

插件中可用 `logging.getLogger("plugin.<插件id>")` 打日志，管理员可在 Web 界面查看插件日志：

```python
import logging
logger = logging.getLogger("plugin.asr_volcengine")

logger.info(f"收到 {len(data)} bytes, 前16字节: {data[:16].hex()}")
logger.info(f"解析结果: type={msg['type']}, event={msg['event']}")
```

### 5.2 常见问题

| 现象 | 原因 | 排查 |
|------|------|------|
| 连接失败 | API Key 错误 / 网络不通 | 检查 `config` 里的 `api_key`，确认服务地址可达 |
| 识别无结果 | 协议帧拼错 | 打印收发帧的 hex 前 16 字节，对照协议文档 |
| 第二次调用返回旧结果 | 忘了 `cache=False` | 所有 ASR 工具必须 `@tool(cache=False)` |
| 报 `cannot call recv while another coroutine is running` | 并发 recv | 用 `asyncio.Lock()` 保护 `ws_recv` |
| 报 `parse payload size failed: body too short` | 结束帧少了长度前缀 | 结束帧必须带 `struct.pack(">I", 0)` |
| 识别文本乱码 | 音频格式不匹配 | 确认 16bit PCM / 16kHz / 单声道 |
| 会话 ID 无效 | 会话被清理 | 确认 `start_session` 返回的 ID 与后续调用一致 |
| 首字延迟高 | 未预热连接 | 实现 `prewarm` 工具 + `pool="prewarm"` 取连接 |

## 六、接入其他 ASR 厂商

换厂商只需替换协议层，工具约定和 manifest 结构不变：

1. 修改 `ASR_URL` 为厂商的 WebSocket 地址
2. 重写 `_make_header` / `_make_payload` / `_parse_response` 适配厂商协议
3. 调整 `_extract_text` / `_is_final` 适配厂商结果结构
4. 修改 manifest 的 `provides.asr` 为厂商 Provider 名（如 `tencent`、`aliyun`）

::: tip 多 Provider 路由
系统支持同时安装多个 ASR 插件，通过 `provides.asr` 中的 Provider 名区分。多设备模式下，可在数据库 `devices` 表中为单个设备配置 `asr_provider` 指定用哪个 Provider。
:::

## 参考实现

| 文件 | 说明 |
|------|------|
| `data/plugins/installed/asr_volcengine/plugin.py` | 火山引擎 ASR 插件完整实现（本教程参考） |
| `src/interfaces/plugin_gateways.py` | `PluginASRGateway` 插件网关包装器 |
| `src/interfaces/service_plugin_adapter.py` | 服务插件适配器（工具调用约定） |
| `src/infrastructure/plugin_loader.py` | 服务注册与必需工具校验 |
| `src/use_cases/sdk/ws.py` | WebSocket SDK（`ws_connect`/`ws_send`/`ws_recv`/`ws_close`/`ws_prewarm`） |
