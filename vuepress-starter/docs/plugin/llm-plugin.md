# LLM 插件开发教程
::: tip 先看这个
编写前建议先阅读 [插件开发教程](./plugin-dev.md) 了解插件基础概念，以及 [插件公共工具库（Plugin SDK）](./plugin-sdk.md) 了解 SDK 提供的流式 HTTP 封装。
:::

LLM 插件把外部大模型服务接入系统：系统把对话消息交给插件，插件流式返回模型输出（可含工具调用）。本篇以 OpenAI 兼容接口（HTTP SSE）为例给出可直接改编的完整实现。

开发者只需要关心两件事：**按契约实现 3 个工具**（下文表格），以及**对接你选择的模型服务**（直接改编文中的完整示例）。系统如何调度插件、工具调用链如何闭环，框架已全部处理，无需了解。

先读 [插件开发教程](./plugin-dev.md) 了解基础概念。

## 一、工具约定（系统契约）

系统通过 `service_plugin_adapter.py` 调用 LLM 插件，**工具名必须严格遵循以下约定**（插件 id 前缀 + 固定后缀）：

| 工具全名 | 参数 | 返回 |
|---------|------|------|
| `{id}_start_chat` | `messages: list, config: dict` | `{"chat_id": str, "error": str\|null}` |
| `{id}_get_next` | `chat_id: str` | `{"token": str, "tool_calls": list, "done": bool, "error": str\|null}` |
| `{id}_end_chat` | `chat_id: str` | `{}` |

::: warning 工具名必须匹配
插件加载器会校验：声明 `provides.llm` 的插件**必须**实现 `start_chat`、`get_next`、`end_chat` 三个后缀工具，否则该服务不会被注册，并会在日志中报错：

```
[插件] llm_xxx 声明提供 llm 服务，但缺少必需工具 [...]。请按约定实现 [...]，该服务未注册。
```
:::

### 1.1 返回值约定

所有 LLM 工具返回**结构化 dict**（而非文本），统一格式：

```python
# 开始类
{"chat_id": str, "error": str | None}
# 传输类
{"token": str, "tool_calls": list, "done": bool, "error": str | None}
# 结束类
{}
```

- `token`：本次读取到的文本增量（可能为空字符串）
- `tool_calls`：`finish_reason` 时一次性返回的完整工具调用列表
- `done`：`True` 表示流结束（`[DONE]` 或 `finish_reason`）
- 成功时 `error` 为 `None`，失败时返回可读的中文错误

::: warning 必须 `cache=False`
LLM 工具**全部**要设 `@tool(cache=False)`。默认缓存会在相同参数下 300 秒内跳过函数体，导致第二次对话直接返回旧结果。
:::

### 1.2 工具调用返回格式

`get_next` 在 `finish_reason` 时返回的 `tool_calls` 列表，每项格式：

```python
{
    "id": "call_xxx",              # 工具调用 ID
    "function_name": "get_weather", # 工具名
    "arguments": "{\"city\":\"北京\"}",  # 参数 JSON 字符串
    "index": 0,                     # 分片索引
}
```

::: warning 必须先收集 tool_calls 再判断 done
系统适配层会**先收集 `tool_calls` 再判断 `done`**。插件必须在 `finish_reason` 时一次性返回累积好的 `tool_calls` + `done=True`，否则工具调用会被丢弃。
:::

## 二、完整代码实现

下面以 **OpenAI 兼容 LLM 插件**（`llm_openai`）为例，给出完整可运行的实现。这是系统内置的参考实现，可直接作为模板，支持 DeepSeek、通义千问、Kimi 等所有 OpenAI 兼容接口。

### 2.1 文件结构

```
llm_openai/
├── manifest.json    # 插件元数据（声明 provides.llm）
└── plugin.py        # 工具实现
```

### 2.2 manifest.json

```json
{
    "id": "llm_openai",
    "name": "OpenAI 兼容 LLM 提供商",
    "version": "1.0.0",
    "author": "system",
    "description": "通过 OpenAI 兼容接口（SSE 流式）提供大语言模型对话服务",
    "api_version": "1.0",
    "optional": true,
    "permissions": ["network"],
    "provides": {
        "llm": ["openai"]
    }
}
```

字段说明：

- `permissions: ["network"]`：HTTP 请求需要 `network` 权限
- `provides: {"llm": ["openai"]}`：声明本插件提供 `llm` 服务，Provider 名为 `openai`

::: tip 关于 config_fields（可省略）
ASR/LLM/TTS 服务插件**不需要**在 manifest 中声明 `config_fields`。这类服务的配置由框架统一管理：设备配置通过接口保存到 `devices.plugin_configs`，运行时框架自动合并进插件的 `config` 参数，插件用 `config.get("api_key")` 读取即可。

声明 `config_fields` 仅有两个作用：① 配置保存接口的键名白名单校验（防止拼错键名）；② 前端配置表单的字段元数据（标签/类型/默认值）。对服务插件而言这两者都不是必需的，因此可以省略，配置保存接口会接受任意键。
:::

### 2.3 plugin.py 完整代码

```python
"""OpenAI 兼容 LLM 服务插件（真流式）。

通过 SDK 的 http_stream_open/read/close 以 SSE 方式逐 token 拉取 LLM 输出，
实现真流式（而非全量缓冲后逐字符模拟）。
"""

from __future__ import annotations

import json
import logging
import time
import uuid

from src.use_cases.sdk.tools import tool
from src.use_cases._plugin_helpers import (
    http_stream_open,
    http_stream_read,
    http_stream_close,
)

logger = logging.getLogger("plugin.llm_openai")

# 会话缓存：chat_id → {"stream_id": str, "done": bool, "error": str|None, ...}
_sessions: dict[str, dict] = {}


@tool(cache=False)
async def llm_openai_start_chat(messages: list, config: dict | None = None,
                                tool_manager=None) -> dict:
    """开始 LLM 对话（真流式），返回 chat_id。

    Args:
        messages: 对话消息列表 [{"role": "user", "content": "..."}, ...]
        config: 配置，包含 api_key, base_url, model

    Returns:
        {"chat_id": str, "error": str|null}
    """
    cfg = config or {}
    api_key = cfg.get("api_key", "")
    base_url = cfg.get("base_url", "https://api.openai.com/v1")
    model = cfg.get("model", "gpt-4o")

    if not api_key:
        return {"chat_id": "", "error": "api_key 未配置"}

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    # 工具调用：config["tools"] 由框架适配层传入（已按用户查询预筛选）
    tools = cfg.get("tools")
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    stream_id, err = await http_stream_open(
        "POST",
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        content=json.dumps(payload),
        timeout=30.0,
    )

    if err:
        return {"chat_id": "", "error": str(err)}

    chat_id = uuid.uuid4().hex[:8]
    _sessions[chat_id] = {
        "stream_id": stream_id,
        "done": False,
        "error": None,
        "start_time": time.time(),
        "first_token_logged": False,
        "reasoning_seen": False,
        "raw_tool_calls": {},  # index → {"id","function_name","arguments"}
    }
    return {"chat_id": chat_id, "error": None}


@tool(cache=False)
async def llm_openai_get_next(chat_id: str, tool_manager=None) -> dict:
    """获取下一个 token（从 SSE 流实时读取）。

    Args:
        chat_id: start_chat 返回的会话 ID

    Returns:
        {"token": str, "done": bool, "error": str|null}
    """
    session = _sessions.get(chat_id)
    if not session:
        return {"token": "", "done": True, "error": "session not found"}
    if session["error"]:
        return {"token": "", "done": True, "error": session["error"]}
    if session["done"]:
        return {"token": "", "done": True, "error": None}

    # 持续读取 SSE 行，直到拿到一段内容或流结束
    while True:
        line, err = await http_stream_read(session["stream_id"], timeout=0.3)
        if err:
            session["error"] = str(err)
            session["done"] = True
            return {"token": "", "done": True, "error": str(err)}
        if line is None:
            # 超时无新数据：LLM 仍在生成，返回空 token 保持轮询
            return {"token": "", "done": False, "error": None}

        line = line.strip()
        if not line or line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            session["done"] = True
            return {"token": "", "done": True, "error": None}

        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            continue

        choices = obj.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        # 诊断：检测推理模型（reasoning_content 先于 content 输出）
        reasoning = delta.get("reasoning_content") or ""
        if reasoning and not session["reasoning_seen"]:
            session["reasoning_seen"] = True
            logger.info("[llm_openai] 检测到 reasoning_content（模型在思考），首字延迟将包含推理耗时")
        # 工具调用：按 index 分片累积
        for tc in delta.get("tool_calls") or []:
            idx = tc.get("index", 0)
            if idx not in session["raw_tool_calls"]:
                session["raw_tool_calls"][idx] = {"id": "", "function_name": "", "arguments": ""}
            if tc.get("id"):
                session["raw_tool_calls"][idx]["id"] = tc["id"]
            fn = tc.get("function") or {}
            if fn.get("name"):
                session["raw_tool_calls"][idx]["function_name"] = fn["name"]
            if fn.get("arguments"):
                session["raw_tool_calls"][idx]["arguments"] += fn["arguments"]
        content = delta.get("content") or ""
        if content:
            if not session["first_token_logged"]:
                session["first_token_logged"] = True
                ttft = (time.time() - session["start_time"]) * 1000
                logger.info(
                    f"[llm_openai] 首 token 延迟: {ttft:.0f} ms "
                    f"(reasoning={'是' if session['reasoning_seen'] else '否'})"
                )
            return {"token": content, "done": False, "error": None}
        if choices[0].get("finish_reason"):
            session["done"] = True
            tool_calls = [
                {
                    "id": v["id"],
                    "function_name": v["function_name"],
                    "arguments": v["arguments"],
                    "index": i,
                }
                for i, v in sorted(session["raw_tool_calls"].items())
                if v["function_name"]
            ]
            return {"token": "", "tool_calls": tool_calls, "done": True, "error": None}


@tool(cache=False)
async def llm_openai_end_chat(chat_id: str, tool_manager=None) -> dict:
    """清理 LLM 会话并关闭流。"""
    session = _sessions.pop(chat_id, None)
    if session and session.get("stream_id"):
        try:
            await http_stream_close(session["stream_id"])
        except Exception:
            pass
    return {}
```

## 三、关键点与常见坑

### 3.1 真流式 vs 假流式

**必须用 `http_stream_open/read` 逐行读取响应体**（真流式）。不要用 `http_request` 一次性缓冲后逐字符模拟（假流式），假流式的首字延迟会很高，因为要等完整响应返回。

### 3.2 推理模型的 reasoning_content

部分模型（如 DeepSeek-R1）先输出 `reasoning_content`（思考过程）再输出 `content`（正式回复）。首字延迟会包含推理耗时。参考实现会检测并记录：

```python
reasoning = delta.get("reasoning_content") or ""
if reasoning and not session["reasoning_seen"]:
    session["reasoning_seen"] = True
    logger.info("检测到 reasoning_content（模型在思考），首字延迟将包含推理耗时")
```

### 3.3 工具调用顺序

**必须先收集 `tool_calls` 再判断 `done`**。如果先判断 `done` 返回，工具调用会被丢弃，导致 LLM 无法执行工具。

### 3.4 兼容性

OpenAI 兼容接口（DeepSeek、通义千问、Kimi 等）都可用此模板，只需改 `base_url` 和 `model`：

| 厂商 | base_url | 示例 model |
|------|----------|-----------|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| Kimi | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |

## 四、安装与配置

### 4.1 打包上传

将 `manifest.json` 和 `plugin.py` 打成 zip 包：

::: code-tabs#shell
@tab bash
```bash
cd llm_openai
zip -r llm_openai-1.0.0.zip manifest.json plugin.py
```
@tab PowerShell
```powershell
Compress-Archive -Path manifest.json,plugin.py -DestinationPath llm_openai-1.0.0.zip
```
:::

登录 Web 管理界面 → **插件市场 → 开发者** tab → 开启开发者模式 → 拖入 zip 上传。

### 4.2 配置参数

安装后在设备级插件配置中填写：

| 配置项 | 说明 |
|--------|------|
| `api_key` | 模型服务商 API Key |
| `base_url` | 接口地址，如 `https://api.deepseek.com/v1` |
| `model` | 模型名，如 `deepseek-chat` |

### 4.3 验证生效

上传并配置后，查看服务端日志确认服务已注册：

```
[插件服务] llm_openai 注册 llm 服务: openai
[WS] 使用 LLM 插件网关
```

设备连接时日志出现 `[WS] 使用 LLM 插件网关` 即表示插件模式生效。

## 五、调试与排错

### 5.1 日志

插件中可用 `logging.getLogger("plugin.<插件id>")` 打日志，管理员可在 Web 界面查看插件日志：

```python
import logging
logger = logging.getLogger("plugin.llm_openai")

logger.info(f"[llm_openai] 首 token 延迟: {ttft:.0f} ms")
logger.info("[llm_openai] 检测到 reasoning_content（模型在思考）")
```

### 5.2 常见问题

| 现象 | 原因 | 排查 |
|------|------|------|
| 连接失败 | API Key 错误 / 网络不通 | 检查 `config` 里的 `api_key`，确认 `base_url` 可达 |
| 无回复 | SSE 解析错误 | 打印原始 SSE 行，确认 `data:` 前缀解析正确 |
| 第二次对话返回旧结果 | 忘了 `cache=False` | 所有 LLM 工具必须 `@tool(cache=False)` |
| 工具不执行 | 未透传 `config["tools"]` | 确认 `start_chat` 把 `tools` 放进 payload |
| 工具调用被丢弃 | 先判断 done 再收集 tool_calls | 必须先收集 `tool_calls` 再返回 `done=True` |
| 首字延迟高 | 推理模型 / 假流式 | 确认用 `http_stream_open/read` 真流式；推理模型首字含思考耗时 |
| 无限轮询不结束 | 未处理 `[DONE]` | 确认 `[DONE]` 和 `finish_reason` 都置 `done=True` |

### 5.3 性能优化建议

| 优化项 | 说明 |
|--------|------|
| 回复长度控制 | 在系统提示词中约束回复长度（如"最多 25 字，一句话"），减少音频播放时间 |
| 首 token 延迟 | 优先选择非推理模型；减少上下文长度（记忆注入） |
| 连接复用 | 框架已实现 HTTP 连接池复用（keep-alive），无需插件处理 |

## 六、接入其他 LLM 厂商

换厂商只需改配置，代码完全复用：

1. 修改 manifest 的 `provides.llm` 为厂商 Provider 名
2. 在设备配置中填写对应厂商的 API Key、接口地址、模型名（保存到 `plugin_configs`，无需在 manifest 声明 `config_fields`）

::: tip 多 Provider 路由
系统支持同时安装多个 LLM 插件，通过 `provides.llm` 中的 Provider 名区分。多设备模式下，可在数据库 `devices` 表中为单个设备配置 `llm_api_key`、`llm_base_url`、`llm_model`、`llm_system_prompt`，优先级高于全局配置。
:::

## 参考实现

| 文件 | 说明 |
|------|------|
| `data/plugins/installed/llm_openai/plugin.py` | OpenAI 兼容 LLM 插件完整实现（本教程参考） |
| `src/interfaces/plugin_gateways.py` | `PluginLLMGateway` 插件网关包装器 |
| `src/interfaces/service_plugin_adapter.py` | 服务插件适配器（工具调用约定 + 工具调用链） |
| `src/infrastructure/plugin_loader.py` | 服务注册与必需工具校验 |
| `src/use_cases/sdk/http.py` | 流式 HTTP SDK（`http_stream_open`/`http_stream_read`/`http_stream_close`） |
