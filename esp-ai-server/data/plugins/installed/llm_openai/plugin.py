"""OpenAI 兼容 LLM 服务插件（真流式）。

通过 SDK 的 http_stream_open/read/close 以 SSE 方式逐 token 拉取 LLM 输出，
实现真流式（而非全量缓冲后逐字符模拟）。

工具约定：
  1. llm_openai_start_chat: 打开流式请求，返回 chat_id
  2. llm_openai_get_next: 从 SSE 流读取下一个 token
  3. llm_openai_end_chat: 关闭流并清理
"""

from __future__ import annotations

import json
import logging
import time
import uuid

from src.use_cases.tools_system import tool
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
    base_url = cfg.get("base_url", "https://api.deepseek.com/v1")
    model = cfg.get("model", "deepseek-v4-flash")

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
