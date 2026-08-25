"""服务插件适配器：Session/Pipeline 与 ASR/LLM/TTS 插件之间的桥梁。

插件开发者只需在 plugin.py 中按约定实现工具函数，无需关心框架内部。
SDK 层（ws_connect / http_request 等）由框架提供，插件通过 SDK 调用 Provider API。

工具约定：
  LLM 插件:
    llm_start_chat(messages, config) -> {"chat_id": str, "error": str|null}
    llm_get_next(chat_id) -> {"token": str, "done": bool, "error": str|null}
    llm_end_chat(chat_id) -> {}

  TTS 插件:
    tts_start_synthesis(text, config) -> {"syn_id": str, "error": str|null}
    tts_get_audio(syn_id) -> {"audio_base64": str, "done": bool, "error": str|null}
    tts_end_synthesis(syn_id) -> {}

  ASR 插件:
    asr_start_session(config) -> {"session_id": str, "error": str|null}
    asr_send_audio(session_id, audio_base64) -> {"text": str, "is_final": bool, "error": str|null}
    asr_send_audio_end(session_id) -> {}
    asr_get_result(session_id) -> {"text": str, "is_final": bool, "error": str|null}
    asr_end_session(session_id) -> {"final_text": str, "error": str|null}
"""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any, AsyncIterator

from src.infrastructure.logging import get_logger
from src.infrastructure.plugin_loader import (
    get_service_plugin,
    get_service_providers,
    has_service_plugin,
)
from src.use_cases.tools_system import StopPipeline

logger = get_logger(__name__)

# 工具调用最大轮数（执行工具后回传 LLM 继续生成）
MAX_TOOL_ROUNDS = 10


# ═══════════════════════════════════════════════════════════════
# 工具调用统一入口（沙箱 + 内置插件通用）
# ═══════════════════════════════════════════════════════════════


async def _call_plugin_tool(
    plugin_name: str,
    tool_suffix: str,
    args: dict,
    tool_manager=None,
) -> Any:
    """调用插件工具函数，同时支持沙箱（第三方）和内置两种插件模式。

    - 沙箱插件：通过 supervisor RPC 调用
    - 内置插件：从工具注册表获取函数，进程内直接调用
    """
    # 1. 先尝试沙箱（第三方安装的插件 → 子进程）
    from src.infrastructure.plugin_host.supervisor import get_plugin_supervisor
    supervisor = get_plugin_supervisor()
    sp = supervisor.get_plugin(plugin_name)
    if sp is not None:
        # 沙箱模式：通过 supervisor 的 RPC 调用
        ctx = supervisor._build_call_context(sp, tool_manager, None, None, None)
        return await sp.call_tool(
            f"{plugin_name}_{tool_suffix}",
            args,
            ctx,
        )

    # 2. 回退到内置插件（进程内直接调用 @tool 函数）
    from src.use_cases.tools_system import get_tool
    tool_def = get_tool(f"{plugin_name}_{tool_suffix}")
    if tool_def is None:
        return None

    func = tool_def.func
    if inspect.iscoroutinefunction(func):
        return await func(**args, tool_manager=tool_manager)
    return func(**args, tool_manager=tool_manager)


# ═══════════════════════════════════════════════════════════════
# 公共查询
# ═══════════════════════════════════════════════════════════════


def has_llm_plugin() -> bool:
    """是否有 LLM 服务插件已安装。"""
    return has_service_plugin("llm")


def has_tts_plugin() -> bool:
    """是否有 TTS 服务插件已安装。"""
    return has_service_plugin("tts")


def has_asr_plugin() -> bool:
    """是否有 ASR 服务插件已安装。"""
    return has_service_plugin("asr")


def get_llm_providers() -> list[str]:
    """获取所有已注册的 LLM Provider 名称。"""
    return get_service_providers("llm")


def get_tts_providers() -> list[str]:
    """获取所有已注册的 TTS Provider 名称。"""
    return get_service_providers("tts")


def get_asr_providers() -> list[str]:
    """获取所有已注册的 ASR Provider 名称。"""
    return get_service_providers("asr")


# ═══════════════════════════════════════════════════════════════
# LLM 适配器
# ═══════════════════════════════════════════════════════════════


def _extract_user_text(messages: list) -> str:
    """从 messages 中提取最近一条用户消息文本（用于工具检索）。"""
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            return msg.get("content", "") or ""
    return ""


def _get_relevant_tools_param(tool_manager, user_text: str = ""):
    """根据用户查询获取相关工具的 schema（工具检索降维）。"""
    if not tool_manager:
        return None
    if hasattr(tool_manager, "get_relevant_tools_schema"):
        schemas = tool_manager.get_relevant_tools_schema(user_text)
    else:
        schemas = tool_manager.get_all_tools_schema()
    return schemas if schemas else None


async def call_llm_chat(
    messages: list[dict],
    config: dict | None = None,
    tool_manager=None,
    provider: str | None = None,
) -> AsyncIterator[str]:
    """通过 LLM 服务插件流式调用对话，逐 token 产出（含工具调用链）。

    Args:
        messages: 对话消息列表
        config: 插件配置（如 api_key, model, base_url 等）
        tool_manager: 工具管理器
        provider: 指定 Provider 名称，为 None 时用第一个注册的

    Yields:
        逐 token 文本
    """
    plugin_name = get_service_plugin("llm", provider)
    if not plugin_name:
        yield "[LLM not configured: no LLM service plugin installed]"
        return

    # 工具检索：根据用户查询预筛选相关工具，传给插件加入请求
    user_text = _extract_user_text(messages)
    tools_param = _get_relevant_tools_param(tool_manager, user_text)
    if tools_param:
        config = dict(config or {})
        config["tools"] = tools_param

    round_num = 0
    failed_tool_calls: set = set()

    while round_num < MAX_TOOL_ROUNDS:
        round_num += 1

        # 1. 开始对话（支持沙箱和内置两种模式）
        result = await _call_plugin_tool(
            plugin_name, "start_chat",
            {"messages": messages, "config": config or {}},
            tool_manager,
        )
        if result is None:
            yield "[LLM not configured: plugin not loaded]"
            return
        try:
            parsed = json.loads(result) if isinstance(result, str) else result
        except (json.JSONDecodeError, TypeError):
            parsed = {}
        if isinstance(parsed, dict) and parsed.get("error"):
            yield f"[LLM error: {parsed['error']}]"
            return
        # 如果 result 是字符串但非 JSON（如沙箱崩溃错误），记录真实错误
        if isinstance(result, str) and not isinstance(parsed, dict):
            logger.error(f"[PluginLLM] LLM 插件返回非 JSON 错误: {result[:200]}")
            yield f"[LLM error: {result[:200]}]"
            return
        chat_id = parsed.get("chat_id") if isinstance(parsed, dict) else None
        if not chat_id:
            logger.error(f"[PluginLLM] LLM 插件返回空 chat_id，原始结果: {str(result)[:200]}")
            yield "[LLM error: no chat_id returned]"
            return

        full_text = ""
        raw_tool_calls: dict[int, dict] = {}
        # 2. 轮询获取结果
        try:
            while True:
                chunk = await _call_plugin_tool(
                    plugin_name, "get_next",
                    {"chat_id": chat_id},
                    tool_manager,
                )
                try:
                    chunk_parsed = json.loads(chunk) if isinstance(chunk, str) else chunk
                except (json.JSONDecodeError, TypeError):
                    chunk_parsed = {}
                if isinstance(chunk_parsed, dict):
                    if chunk_parsed.get("error"):
                        yield f"[LLM error: {chunk_parsed['error']}]"
                        break
                    token = chunk_parsed.get("token", "")
                    if token:
                        full_text += token
                        yield token
                    # 收集工具调用（插件按 index 分片累积后一次性返回）。
                    # 注意：插件在 finish_reason 时一次性返回 tool_calls + done=True，
                    # 必须先收集 tool_calls 再判断 done，否则工具调用会被丢弃。
                    for tc in chunk_parsed.get("tool_calls") or []:
                        idx = tc.get("index", len(raw_tool_calls))
                        raw_tool_calls[idx] = tc
                    if chunk_parsed.get("done"):
                        break
                else:
                    break
        finally:
            # 3. 清理
            try:
                await _call_plugin_tool(
                    plugin_name, "end_chat",
                    {"chat_id": chat_id},
                    tool_manager,
                )
            except Exception:
                pass

        if not raw_tool_calls:
            break

        # 工具调用前发送即时反馈（设备端显示"正在处理中"）
        if tool_manager and getattr(tool_manager, "channel", None):
            try:
                _tool_names = [tc["function_name"] for tc in raw_tool_calls.values()]
                await tool_manager.channel.send_json({
                    "type": "instruct",
                    "command_id": "on_tool_status",
                    "data": f"正在执行: {', '.join(_tool_names)}...",
                })
                logger.info(f"[PluginLLM] 已发送工具调用反馈: {', '.join(_tool_names)}")
            except Exception as _fb_err:
                logger.debug(f"[PluginLLM] 发送工具调用反馈失败: {_fb_err}")

        # 4. 构造 assistant 消息（含 tool_calls）追加到 messages
        assistant_msg = {
            "role": "assistant",
            "content": full_text or None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["function_name"],
                        "arguments": tc["arguments"],
                    },
                }
                for tc in raw_tool_calls.values()
            ],
        }
        messages.append(assistant_msg)

        # 5. 执行工具，结果追加为 tool 消息
        for tc_data in raw_tool_calls.values():
            try:
                func_args = json.loads(tc_data["arguments"]) if tc_data["arguments"] else {}
            except json.JSONDecodeError:
                func_args = {}

            logger.info(f"[PluginLLM] Calling tool: {tc_data['function_name']}({func_args})")

            tool_key = (tc_data["function_name"], json.dumps(func_args, sort_keys=True, ensure_ascii=False))
            if tool_key in failed_tool_calls:
                tool_result = ("This operation was already attempted but the service is unavailable, "
                               "please inform the user that this operation cannot be completed and do not try calling this tool again")
            elif tool_manager:
                try:
                    tool_result = await tool_manager.call_tool(tc_data["function_name"], func_args)
                except StopPipeline:
                    logger.info("[PluginLLM] StopPipeline raised during tool call")
                    yield "__STOP_PIPELINE__"
                    return
                except Exception as e:
                    logger.error(f"[PluginLLM] Tool execution exception: {e}")
                    tool_result = f"Tool execution exception: {e}"
            else:
                tool_result = f"Tool manager not initialized, cannot call {tc_data['function_name']}"

            if ("unavailable" in str(tool_result) or "failed" in str(tool_result)
                    or "暂不可用" in str(tool_result) or "失败" in str(tool_result)):
                failed_tool_calls.add(tool_key)

            logger.info(f"[PluginLLM] Tool {tc_data['function_name']} returned: {str(tool_result)[:200]}")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc_data["id"],
                    "content": str(tool_result),
                }
            )

        # 所有工具执行完毕，清除客户端工具状态显示
        if tool_manager and getattr(tool_manager, "channel", None):
            try:
                await tool_manager.channel.send_json({
                    "type": "instruct",
                    "command_id": "on_tool_status",
                    "data": "",
                })
                logger.info("[PluginLLM] 工具执行完毕，已发送清除指令")
            except Exception as _clr_err:
                logger.debug(f"[PluginLLM] 发送清除指令失败: {_clr_err}")


# ═══════════════════════════════════════════════════════════════
# TTS 适配器
# ═══════════════════════════════════════════════════════════════


async def call_tts_synthesize(
    text: str,
    config: dict | None = None,
    tool_manager=None,
    provider: str | None = None,
) -> AsyncIterator[bytes]:
    """通过 TTS 服务插件合成语音，逐音频块产出。

    Args:
        text: 待合成文本
        config: 插件配置
        tool_manager: 工具管理器
        provider: 指定 Provider 名称

    Yields:
        逐音频块（bytes）
    """
    plugin_name = get_service_plugin("tts", provider)
    if not plugin_name:
        return

    import base64

    # 1. 开始合成（支持沙箱和内置两种模式）
    result = await _call_plugin_tool(
        plugin_name, "start_synthesis",
        {"text": text, "config": config or {}},
        tool_manager,
    )
    if result is None:
        return
    try:
        parsed = json.loads(result) if isinstance(result, str) else result
    except (json.JSONDecodeError, TypeError):
        parsed = {}
    if isinstance(parsed, dict) and parsed.get("error"):
        logger.error(f"[TTS Plugin] 合成失败: {parsed['error']}")
        return
    syn_id = parsed.get("syn_id") if isinstance(parsed, dict) else None
    if not syn_id:
        return

    # 2. 轮询获取音频
    try:
        while True:
            chunk = await _call_plugin_tool(
                plugin_name, "get_audio",
                {"syn_id": syn_id},
                tool_manager,
            )
            try:
                chunk_parsed = json.loads(chunk) if isinstance(chunk, str) else chunk
            except (json.JSONDecodeError, TypeError):
                chunk_parsed = {}
            if isinstance(chunk_parsed, dict):
                if chunk_parsed.get("error") or chunk_parsed.get("done"):
                    break
                audio_b64 = chunk_parsed.get("audio_base64", "")
                if audio_b64:
                    yield base64.b64decode(audio_b64)
            else:
                break
    finally:
        # 3. 清理
        try:
            await _call_plugin_tool(
                plugin_name, "end_synthesis",
                {"syn_id": syn_id},
                tool_manager,
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
# ASR 适配器
# ═══════════════════════════════════════════════════════════════


class ASRPluginSession:
    """ASR 插件会话句柄，管理 ASR 生命周期。"""

    def __init__(self, plugin_name: str, session_id: str):
        self.plugin_name = plugin_name
        self.session_id = session_id
        self._closed = False

    async def send_audio(self, audio_data: bytes, tool_manager=None) -> dict:
        """发送音频数据到 ASR 插件。"""
        if self._closed:
            return {"text": "", "is_final": True}
        import base64
        result = await _call_plugin_tool(
            self.plugin_name, "send_audio",
            {"session_id": self.session_id, "audio": base64.b64encode(audio_data).decode("ascii")},
            tool_manager,
        )
        if result is None:
            return {"text": "", "is_final": True, "error": "plugin not loaded"}
        try:
            parsed = json.loads(result) if isinstance(result, str) else result
        except (json.JSONDecodeError, TypeError):
            parsed = {}
        return parsed if isinstance(parsed, dict) else {}

    async def get_result(self, tool_manager=None) -> dict:
        """获取 ASR 识别结果。"""
        if self._closed:
            return {"text": "", "is_final": True}
        result = await _call_plugin_tool(
            self.plugin_name, "get_result",
            {"session_id": self.session_id},
            tool_manager,
        )
        if result is None:
            return {"text": "", "is_final": True, "error": "plugin not loaded"}
        try:
            parsed = json.loads(result) if isinstance(result, str) else result
        except (json.JSONDecodeError, TypeError):
            parsed = {}
        return parsed if isinstance(parsed, dict) else {}

    async def close(self, tool_manager=None) -> str:
        """关闭 ASR 会话，返回最终文本。"""
        if self._closed:
            return ""
        self._closed = True
        result = await _call_plugin_tool(
            self.plugin_name, "end_session",
            {"session_id": self.session_id},
            tool_manager,
        )
        if result is None:
            return ""
        try:
            parsed = json.loads(result) if isinstance(result, str) else result
        except (json.JSONDecodeError, TypeError):
            parsed = {}
        if isinstance(parsed, dict):
            return parsed.get("final_text", "")
        return ""


async def create_asr_session(
    config: dict | None = None,
    tool_manager=None,
    provider: str | None = None,
) -> ASRPluginSession | None:
    """创建 ASR 识别会话。返回 ASRPluginSession 句柄。"""
    plugin_name = get_service_plugin("asr", provider)
    if not plugin_name:
        return None

    result = await _call_plugin_tool(
        plugin_name, "start_session",
        {"config": config or {}},
        tool_manager,
    )
    if result is None:
        return None
    try:
        parsed = json.loads(result) if isinstance(result, str) else result
    except (json.JSONDecodeError, TypeError):
        parsed = {}
    if isinstance(parsed, dict) and parsed.get("error"):
        logger.error(f"[ASR Plugin] 创建会话失败: {parsed['error']}")
        return None
    session_id = parsed.get("session_id") if isinstance(parsed, dict) else None
    if not session_id:
        return None
    return ASRPluginSession(plugin_name, session_id)