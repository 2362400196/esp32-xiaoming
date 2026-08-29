# TTS 插件开发教程
::: tip 先看这个
编写前建议先阅读 [插件开发教程](./plugin-dev.md) 了解插件基础概念，以及 [插件公共工具库（Plugin SDK）](./plugin-sdk.md) 了解 SDK 提供的 WebSocket 封装。
:::

TTS 插件把外部语音合成服务接入系统：系统把文本交给插件，插件返回 MP3 音频流给设备播报。本篇以火山引擎为例给出可直接改编的完整实现。

开发者只需要关心两件事：**按契约实现 3 个工具**（下文表格），以及**对接你选择的 TTS 服务**（直接改编文中的完整示例）。系统如何调度插件、音频如何下发设备，框架已全部处理，无需了解。

先读 [插件开发教程](./plugin-dev.md) 了解基础概念，SDK 的 WebSocket 封装见 [Plugin SDK](./plugin-sdk.md)。

## 一、工具约定（系统契约）

系统通过 `service_plugin_adapter.py` 调用 TTS 插件，**工具名必须严格遵循以下约定**（插件 id 前缀 + 固定后缀）：

| 工具全名 | 参数 | 返回 |
|---------|------|------|
| `{id}_start_synthesis` | `text: str, config: dict` | `{"syn_id": str, "error": str\|null}` |
| `{id}_get_audio` | `syn_id: str` | `{"audio_base64": str, "done": bool, "error": str\|null}` |
| `{id}_end_synthesis` | `syn_id: str` | `{}` |

::: warning 工具名必须匹配
插件加载器会校验：声明 `provides.tts` 的插件**必须**实现 `start_synthesis`、`get_audio`、`end_synthesis` 三个后缀工具，否则该服务不会被注册，并会在日志中报错：

```
[插件] tts_xxx 声明提供 tts 服务，但缺少必需工具 [...]。请按约定实现 [...]，该服务未注册。
```
:::

### 1.1 返回值约定

所有 TTS 工具返回**结构化 dict**（而非文本），统一格式：

```python
# 开始类
{"syn_id": str, "error": str | None}
# 传输类
{"audio_base64": str, "done": bool, "error": str | None}
# 结束类
{}
```

- 成功时 `error` 为 `None`，失败时返回可读的中文错误
- 上层根据 `error` 判断是否继续，`done` 为 `True` 表示合成完成

::: warning 必须 `cache=False`
TTS 工具**全部**要设 `@tool(cache=False)`。默认缓存会在相同参数下 300 秒内跳过函数体，导致第二次合成直接返回旧结果。
:::

## 二、完整代码实现

下面以**火山引擎 TTS 插件**（`tts_volcengine`）为例，给出完整可运行的实现。这是系统内置的参考实现，可直接作为模板。

### 2.1 文件结构

```
tts_volcengine/
├── manifest.json    # 插件元数据（声明 provides.tts）
└── plugin.py        # 工具实现
```

### 2.2 manifest.json

```json
{
    "id": "tts_volcengine",
    "name": "火山引擎 TTS 提供商",
    "version": "1.0.0",
    "author": "system",
    "description": "通过火山引擎 TTS WebSocket 接口提供语音合成服务",
    "api_version": "1.0",
    "optional": true,
    "permissions": ["network"],
    "provides": {
        "tts": ["volcengine"]
    }
}
```

字段说明：

- `permissions: ["network"]`：WebSocket 连接需要 `network` 权限
- `provides: {"tts": ["volcengine"]}`：声明本插件提供 `tts` 服务，Provider 名为 `volcengine`

::: tip 关于 config_fields（可省略）
ASR/LLM/TTS 服务插件**不需要**在 manifest 中声明 `config_fields`。这类服务的配置由框架统一管理：设备配置通过接口保存到 `devices.plugin_configs`，运行时框架自动合并进插件的 `config` 参数，插件用 `config.get("api_key")` 读取即可。

声明 `config_fields` 仅有两个作用：① 配置保存接口的键名白名单校验（防止拼错键名）；② 前端配置表单的字段元数据（标签/类型/默认值）。对服务插件而言这两者都不是必需的，因此可以省略，配置保存接口会接受任意键。
:::

### 2.3 plugin.py 完整代码

```python
"""火山引擎 TTS 服务插件。

使用 WebSocket SDK 连接火山引擎 TTS 服务（V3 双向流式协议），实现流式语音合成。
插件开发者只需关注协议拼装和解析，SDK 封装了 WebSocket 连接管理。
"""

from __future__ import annotations

import io
import json
import struct
import time
import uuid

from src.use_cases.sdk.tools import tool
from src.use_cases._plugin_helpers import ws_connect, ws_send, ws_recv, ws_close, json_dumps

import logging
logger = logging.getLogger("plugin.tts_volcengine")

# 火山引擎 TTS V3 协议地址
TTS_URL = "wss://openspeech.bytedance.com/api/v3/tts/unidirectional/stream"

# 会话缓存：syn_id → {"ws_id": str, "done": bool, "buffer": list}
_sessions: dict[str, dict] = {}

# ── 协议常量 ────────────────────────────────────────────────

MSG_TYPE_FULL_CLIENT_REQUEST = 0b1
MSG_TYPE_AUDIO_ONLY_CLIENT = 0b10
MSG_TYPE_FULL_SERVER_RESPONSE = 0b1001
MSG_TYPE_AUDIO_ONLY_SERVER = 0b1011
MSG_TYPE_FRONT_END_SERVER = 0b1100
MSG_TYPE_ERROR = 0b1111

FLAG_NO_SEQ = 0
FLAG_POSITIVE_SEQ = 0b1
FLAG_WITH_EVENT = 0b100

EVENT_FINISH_CONNECTION = 2
EVENT_CONNECTION_FINISHED = 52
EVENT_START_SESSION = 100
EVENT_FINISH_SESSION = 102
EVENT_SESSION_FINISHED = 152
EVENT_SESSION_FAILED = 153
EVENT_TTS_SENTENCE_START = 350
EVENT_TTS_SENTENCE_END = 351
EVENT_TTS_RESPONSE = 352
EVENT_TTS_ENDED = 359


def _build_message(type_: int, flags: int = 0, payload: bytes = b"",
                   event: int | None = None, session_id: str = "",
                   sequence: int = 0) -> bytes:
    """构造 TTS V3 协议帧。"""
    buf = io.BytesIO()

    # 4 字节头部
    version = 0x1 << 4
    header_size = 0x1 << 0
    byte0 = (version | header_size).to_bytes(1, "big")
    byte1 = ((type_ << 4) | flags).to_bytes(1, "big")
    serialization = 0x1 << 4  # JSON
    compression = 0x0 << 0
    byte2 = (serialization | compression).to_bytes(1, "big")
    byte3 = (0).to_bytes(1, "big")
    buf.write(byte0 + byte1 + byte2 + byte3)

    # WithEvent → 4 字节 event + session_id（某些事件省略 session_id）
    if flags & FLAG_WITH_EVENT:
        buf.write(struct.pack(">i", event or 0))
        # FinishConnection / StartConnection / ConnectionStarted / ConnectionFailed 跳过 session_id
        skip_events = {2, 1, 50, 51}
        if event not in skip_events:
            sid_bytes = session_id.encode("utf-8")
            buf.write(struct.pack(">I", len(sid_bytes)))
            if sid_bytes:
                buf.write(sid_bytes)

    # PositiveSeq → 4 字节 sequence
    if flags & FLAG_POSITIVE_SEQ:
        buf.write(struct.pack(">i", sequence))

    # payload
    buf.write(struct.pack(">I", len(payload)))
    if payload:
        buf.write(payload)

    return buf.getvalue()


def _parse_message(data: bytes) -> dict:
    """解析 TTS V3 协议帧，返回结构化字典。"""
    msg = {
        "type": None,
        "flags": 0,
        "event": None,
        "session_id": "",
        "connect_id": "",
        "sequence": 0,
        "payload": b"",
        "error_code": 0,
    }
    if len(data) < 3:
        msg["type"] = MSG_TYPE_ERROR
        return msg

    buf = io.BytesIO(data)
    byte0 = buf.read(1)[0]
    byte1 = buf.read(1)[0]
    byte2 = buf.read(1)[0]
    msg["type"] = byte1 >> 4
    msg["flags"] = byte1 & 0b00001111

    header_size = byte0 & 0b00001111
    read_size = 3
    if padding := (header_size * 4) - read_size:
        buf.read(padding)

    flags = msg["flags"]
    if flags & FLAG_WITH_EVENT:
        ev_bytes = buf.read(4)
        if len(ev_bytes) == 4:
            msg["event"] = struct.unpack(">i", ev_bytes)[0]
        event = msg["event"]
        # 跳过 session_id 的事件：StartConnection(1), FinishConnection(2),
        # ConnectionStarted(50), ConnectionFailed(51)
        if event not in (1, 2, 50, 51):
            sid_len_bytes = buf.read(4)
            if len(sid_len_bytes) == 4:
                sid_len = struct.unpack(">I", sid_len_bytes)[0]
                if sid_len > 0:
                    msg["session_id"] = buf.read(sid_len).decode("utf-8", errors="replace")
        # connect_id 仅 ConnectionStarted(50)/ConnectionFailed(51)/ConnectionFinished(52)
        if event in (50, 51, 52):
            cid_len_bytes = buf.read(4)
            if len(cid_len_bytes) == 4:
                cid_len = struct.unpack(">I", cid_len_bytes)[0]
                if cid_len > 0:
                    msg["connect_id"] = buf.read(cid_len).decode("utf-8", errors="replace")

    if msg["type"] == MSG_TYPE_ERROR:
        ec_bytes = buf.read(4)
        if len(ec_bytes) == 4:
            msg["error_code"] = struct.unpack(">I", ec_bytes)[0]
    elif flags & (FLAG_POSITIVE_SEQ):
        seq_bytes = buf.read(4)
        if len(seq_bytes) == 4:
            msg["sequence"] = struct.unpack(">i", seq_bytes)[0]

    # payload
    plen_bytes = buf.read(4)
    if len(plen_bytes) == 4:
        plen = struct.unpack(">I", plen_bytes)[0]
        if plen > 0:
            msg["payload"] = buf.read(plen)

    return msg


def _build_request_payload(config: dict, text: str) -> bytes:
    """构造 TTS 合成请求 JSON payload。"""
    request = {
        "user": {"uid": str(uuid.uuid4())},
        "req_params": {
            "speaker": config.get("voice_type", "BV001_streaming"),
            "audio_params": {
                "format": "mp3",
                "sample_rate": int(config.get("sample_rate", "24000")),
                "speed_ratio": float(config.get("speed_ratio", "1.0")),
                "volume_ratio": float(config.get("volume_ratio", "1.0")),
                "pitch_ratio": float(config.get("pitch_ratio", "1.0")),
            },
            "text": text,
        },
    }
    return json.dumps(request, ensure_ascii=False).encode("utf-8")


@tool(cache=False)
async def tts_volcengine_start_synthesis(text: str, config: dict | None = None,
                                         tool_manager=None) -> dict:
    """开始 TTS 语音合成，返回 syn_id。

    Args:
        text: 待合成文本
        config: 配置，包含 api_key, resource_id, voice_type 等

    Returns:
        {"syn_id": str, "error": str|null}
    """
    cfg = config or {}
    api_key = cfg.get("api_key", "")
    resource_id = cfg.get("resource_id", "")

    if not api_key:
        return {"syn_id": "", "error": "api_key 未配置"}

    headers = {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": resource_id or "volc.tts.222222222",
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }

    # 从框架连接池取连接（reuse 模式：优先复用，close 时归还）
    try:
        ws_id = await ws_connect(TTS_URL, headers, pool="reuse",
                                 pool_headers=["X-Api-Key", "X-Api-Resource-Id"])
    except Exception as e:
        return {"syn_id": "", "error": f"WebSocket 连接失败: {e}"}

    # 发送合成请求帧（FullClientRequest）
    payload = _build_request_payload(cfg, text)
    request_frame = _build_message(
        type_=MSG_TYPE_FULL_CLIENT_REQUEST,
        flags=FLAG_NO_SEQ,
        payload=payload,
    )
    try:
        await ws_send(ws_id, request_frame)
    except Exception as e:
        # 连接可能已被服务端关闭，重建后重试
        try:
            await ws_close(ws_id)
        except Exception:
            pass
        try:
            ws_id = await ws_connect(TTS_URL, headers, pool="reuse",
                                     pool_headers=["X-Api-Key", "X-Api-Resource-Id"])
        except Exception as e2:
            return {"syn_id": "", "error": f"WebSocket 连接失败: {e2}"}
        try:
            await ws_send(ws_id, request_frame)
        except Exception as e3:
            return {"syn_id": "", "error": f"发送请求失败: {e3}"}

    syn_id = uuid.uuid4().hex[:8]
    _sessions[syn_id] = {"ws_id": ws_id, "done": False, "buffer": []}
    return {"syn_id": syn_id, "error": None}


@tool(cache=False)
async def tts_volcengine_get_audio(syn_id: str, tool_manager=None) -> dict:
    """获取下一段音频数据。

    Args:
        syn_id: start_synthesis 返回的合成 ID

    Returns:
        {"audio_base64": str, "done": bool, "error": str|null}
    """
    import base64

    session = _sessions.get(syn_id)
    if not session:
        return {"audio_base64": "", "done": True, "error": "session not found"}

    # 优先从缓冲区取
    if session["buffer"]:
        return {"audio_base64": session["buffer"].pop(0), "done": False, "error": None}

    if session["done"]:
        return {"audio_base64": "", "done": True, "error": None}

    # 从 WebSocket 接收数据
    try:
        data = await ws_recv(session["ws_id"], timeout=0.5)
    except Exception as e:
        return {"audio_base64": "", "done": True, "error": f"接收失败: {e}"}

    if data is None:
        return {"audio_base64": "", "done": False, "error": None}

    # 解析 V3 协议帧
    logger.info(f"[TTS get_audio] 收到 {len(data)} bytes, 前16字节: {data[:16].hex()}")
    msg = _parse_message(data)
    logger.info(f"[TTS get_audio] 解析结果: type={msg['type']}, event={msg['event']}, "
                f"payload_len={len(msg.get('payload', b''))}")
    msg_type = msg.get("type")
    msg_event = msg.get("event")
    payload = msg.get("payload", b"")

    if msg_type == MSG_TYPE_ERROR:
        ec = msg.get("error_code", 0)
        session["done"] = True
        return {"audio_base64": "", "done": True, "error": f"服务端错误: code={ec}"}

    if msg_type == MSG_TYPE_AUDIO_ONLY_SERVER:
        # 音频数据
        if payload:
            audio_b64 = base64.b64encode(payload).decode("ascii")
            return {"audio_base64": audio_b64, "done": False, "error": None}
        return {"audio_base64": "", "done": False, "error": None}

    if msg_type == MSG_TYPE_FULL_SERVER_RESPONSE:
        if msg_event == EVENT_TTS_SENTENCE_END:
            # 句子结束，payload 可能包含额外音频数据
            if payload:
                audio_b64 = base64.b64encode(payload).decode("ascii")
                return {"audio_base64": audio_b64, "done": False, "error": None}
            return {"audio_base64": "", "done": False, "error": None}
        if msg_event == EVENT_FINISH_SESSION:
            session["done"] = True
            return {"audio_base64": "", "done": True, "error": None}
        if msg_event == EVENT_SESSION_FINISHED:
            # SessionFinished：火山服务端在音频全部下发后发送，标识合成完成
            session["done"] = True
            return {"audio_base64": "", "done": True, "error": None}
        if msg_event == EVENT_SESSION_FAILED:
            session["done"] = True
            payload_str = payload.decode("utf-8", errors="replace")
            return {"audio_base64": "", "done": True, "error": f"合成失败: {payload_str}"}
        if msg_event == EVENT_TTS_RESPONSE:
            # 响应帧，可能包含 MIME 类型信息
            return {"audio_base64": "", "done": False, "error": None}
        if msg_event == EVENT_TTS_ENDED:
            # 合成结束帧：所有音频已发送完毕，标记完成，避免调用方无限轮询
            session["done"] = True
            return {"audio_base64": "", "done": True, "error": None}
        if msg_event == EVENT_CONNECTION_FINISHED:
            # 服务端关闭连接，标记完成；连接归还池时由框架健康检查丢弃
            session["done"] = True
            return {"audio_base64": "", "done": True, "error": None}

    if msg_type == MSG_TYPE_FRONT_END_SERVER:
        # 前端结果帧
        return {"audio_base64": "", "done": False, "error": None}

    return {"audio_base64": "", "done": False, "error": None}


@tool(cache=False)
async def tts_volcengine_end_synthesis(syn_id: str, tool_manager=None) -> dict:
    """清理 TTS 合成会话，将连接归还框架连接池供后续句子复用。"""
    session = _sessions.pop(syn_id, None)
    if session:
        try:
            await ws_close(session["ws_id"])
        except Exception:
            pass
    return {}
```

## 三、关键点与常见坑

### 3.1 断线重连

发送请求失败时，连接可能已被服务端关闭。参考实现的处理：

```python
try:
    await ws_send(ws_id, request_frame)
except Exception:
    # 关闭旧连接，重建后重试
    await ws_close(ws_id)
    ws_id = await ws_connect(TTS_URL, headers, pool="reuse", ...)
    await ws_send(ws_id, request_frame)
```

### 3.2 音频分片拼接

`AudioOnlyServer` 帧的 payload 是**一段** MP3 音频，不是完整文件。上层需要把多次 `get_audio` 返回的音频块**拼接**后播放：

```python
# 上层（框架）处理逻辑
while True:
    chunk = await call_tts_synthesize(...)  # 逐块产出
    if not chunk:
        break
    audio_buffer += chunk                   # 拼接
```

### 3.3 超时轮询

`ws_recv` 超时返回 `None`，**不代表出错**，是"暂无新数据"。`get_audio` 应返回空音频 + `done=False`，让上层继续轮询：

```python
data = await ws_recv(session["ws_id"], timeout=0.5)
if data is None:
    return {"audio_base64": "", "done": False, "error": None}  # 继续轮询
```

### 3.4 会话清理

`end_synthesis` **不关闭连接**（连接归还连接池供复用），只清理会话缓存。连接的健康检查由框架连接池负责——服务端关闭的脏连接会在归还时被丢弃。

## 四、安装与配置

### 4.1 打包上传

将 `manifest.json` 和 `plugin.py` 打成 zip 包：

::: code-tabs#shell
@tab bash
```bash
cd tts_volcengine
zip -r tts_volcengine-1.0.0.zip manifest.json plugin.py
```
@tab PowerShell
```powershell
Compress-Archive -Path manifest.json,plugin.py -DestinationPath tts_volcengine-1.0.0.zip
```
:::

登录 Web 管理界面 → **插件市场 → 开发者** tab → 开启开发者模式 → 拖入 zip 上传。

### 4.2 配置参数

安装后在设备级插件配置中填写：

| 配置项 | 说明 |
|--------|------|
| `api_key` | 火山引擎语音服务 API Key |
| `resource_id` | 资源 ID，如 `volc.tts.222222222` |
| `voice_type` | 音色，如 `BV001_streaming` |
| `speed_ratio` | 语速（默认 1.0） |
| `volume_ratio` | 音量（默认 1.0） |
| `pitch_ratio` | 音调（默认 1.0） |

### 4.3 验证生效

上传并配置后，查看服务端日志确认服务已注册：

```
[插件服务] tts_volcengine 注册 tts 服务: volcengine
[WS] 使用 TTS 插件网关
```

设备连接时日志出现 `[WS] 使用 TTS 插件网关` 即表示插件模式生效。

## 五、调试与排错

### 5.1 日志

插件中可用 `logging.getLogger("plugin.<插件id>")` 打日志，管理员可在 Web 界面查看插件日志：

```python
import logging
logger = logging.getLogger("plugin.tts_volcengine")

logger.info(f"收到 {len(data)} bytes, 前16字节: {data[:16].hex()}")
logger.info(f"解析结果: type={msg['type']}, event={msg['event']}, payload_len={len(payload)}")
```

### 5.2 常见问题

| 现象 | 原因 | 排查 |
|------|------|------|
| 连接失败 | API Key 错误 / 网络不通 | 检查 `config` 里的 `api_key`，确认服务地址可达 |
| 合成无音频 | 协议帧拼错 | 打印收发帧的 hex 前 16 字节，对照协议文档 |
| 第二次合成返回旧结果 | 忘了 `cache=False` | 所有 TTS 工具必须 `@tool(cache=False)` |
| 每句都新建连接被限流 | 未用连接池 | 用 `pool="reuse"` 复用连接 |
| 无限轮询不结束 | 未处理结束事件 | 检查 `SessionFinished`/`TTSEnded`/`ConnectionFinished` 是否置 `done=True` |
| 音频播放异常 | 分片未拼接 | 确认上层拼接所有 `audio_base64` 分片 |
| 合成失败 | 音色/参数无效 | 检查 `voice_type` 是否存在，`SessionFailed` 事件会返回错误详情 |

## 六、接入其他 TTS 厂商

换厂商只需替换协议层，工具约定和 manifest 结构不变：

1. 修改 `TTS_URL` 为厂商的 WebSocket 地址
2. 重写 `_build_message` / `_parse_message` 适配厂商协议
3. 调整 `_build_request_payload` 适配厂商请求结构
4. 修改 manifest 的 `provides.tts` 为厂商 Provider 名

::: tip 多 Provider 路由
系统支持同时安装多个 TTS 插件，通过 `provides.tts` 中的 Provider 名区分。多设备模式下，可在数据库 `devices` 表中为单个设备配置 `tts_config`（含 `provider`、`voice_type` 等字段），优先级高于全局配置。
:::

## 参考实现

| 文件 | 说明 |
|------|------|
| `data/plugins/installed/tts_volcengine/plugin.py` | 火山引擎 TTS 插件完整实现（本教程参考） |
| `src/interfaces/plugin_gateways.py` | `PluginTTSGateway` / `PluginTTSSession` 插件网关包装器 |
| `src/interfaces/service_plugin_adapter.py` | 服务插件适配器（工具调用约定） |
| `src/infrastructure/plugin_loader.py` | 服务注册与必需工具校验 |
| `src/use_cases/sdk/ws.py` | WebSocket SDK（`ws_connect`/`ws_send`/`ws_recv`/`ws_close`） |
