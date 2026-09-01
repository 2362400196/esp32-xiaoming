import asyncio
import json
import time

from openai import APIConnectionError, APIError, APITimeoutError, AsyncOpenAI, RateLimitError

from src.infrastructure.logging import get_logger, trace_id_var
from src.infrastructure.config import get_settings
from src.infrastructure.monitoring import (
    LLM_COMPLETION_DURATION,
    LLM_COMPLETION_TOTAL,
    LLM_FIRST_TOKEN_LATENCY,
    get_metrics,
)
from src.use_cases.tools_system import StopPipeline

logger = get_logger(__name__)

MAX_TOOL_ROUNDS = 10
LLM_MAX_RETRIES = 3
LLM_RETRY_DELAY = 1.5
# 单次请求超时：流式对话最长也要在 2 分钟内判定失败（SDK 默认 600s 太长，会拖死会话）
LLM_REQUEST_TIMEOUT = 120.0

SEP = "=" * 50
THIN_SEP = "-" * 50


class OpenAILLMGateway:

    def __init__(self, config=None, tool_manager=None):
        self.tool_manager = tool_manager
        settings = get_settings()
        
        self.api_key = (config or {}).get("api_key", "") or settings.llm.api_key
        self.base_url = (config or {}).get("base_url", "") or settings.llm.base_url
        self.model = (config or {}).get("model", "") or settings.llm.model
        self.system_prompt = (config or {}).get("system_prompt", "") or settings.llm.system_prompt
        self.temperature = (config or {}).get("temperature", 0.7)
        self.max_tokens = (config or {}).get("max_tokens", 2000)

        self.client = None
        if self.api_key:
            self.client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url or None,
                timeout=LLM_REQUEST_TIMEOUT,
                max_retries=0,  # 重试由 _retry 统一处理，避免 openai SDK 默认 2 次叠加
            )

    async def aclose(self) -> None:
        """关闭底层 HTTP 客户端（释放 SSL 连接）。

        不关闭的话，进程退出时 GC 回收残存 transport 会在已关闭的事件循环上
        调 __del__ → 'Event loop is closed' 报错刷屏。
        """
        if self.client is not None:
            try:
                await self.client.close()
            except Exception as e:
                logger.debug(f"[LLM] 关闭 AsyncOpenAI 客户端异常: {e}")
            self.client = None

    def _resolve_config(self, user_config=None, device_id=None):
        api_key = self.api_key
        base_url = self.base_url
        model = self.model
        system_prompt = self.system_prompt

        if user_config:
            if isinstance(user_config, dict):
                api_key = user_config.get("api_key", api_key)
                base_url = user_config.get("base_url", base_url)
                model = user_config.get("model", model)
                system_prompt = user_config.get("system_prompt", system_prompt)
                if device_id:
                    device_overrides = user_config.get("device_overrides", {}).get(device_id, {})
                    model = device_overrides.get("model", model)
                    system_prompt = device_overrides.get("system_prompt", system_prompt)
            else:
                if getattr(user_config, "llm_api_key", None):
                    api_key = user_config.llm_api_key
                if getattr(user_config, "llm_base_url", None):
                    base_url = user_config.llm_base_url
                if getattr(user_config, "llm_model", None):
                    model = user_config.llm_model
                if getattr(user_config, "llm_system_prompt", None):
                    system_prompt = user_config.llm_system_prompt
                if device_id:
                    effective_model = getattr(user_config, "get_effective_llm_model", lambda x: None)(device_id)
                    effective_system_prompt = getattr(user_config, "get_effective_llm_system_prompt", lambda x: None)(device_id)
                    if effective_model:
                        model = effective_model
                    if effective_system_prompt:
                        system_prompt = effective_system_prompt

        client = self.client
        if api_key and (api_key != self.api_key or base_url != self.base_url):
            client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url or None,
                timeout=LLM_REQUEST_TIMEOUT,
                max_retries=0,
            )

        return client, model, system_prompt

    async def _retry(self, fn, *args, **kwargs):
        last_exc = None
        for attempt in range(LLM_MAX_RETRIES):
            try:
                return await fn(*args, **kwargs)
            except RateLimitError as e:
                wait = LLM_RETRY_DELAY * (2 ** attempt)
                logger.warning(f"[LLM] Rate limit (429), attempt {attempt + 1}/{LLM_MAX_RETRIES}, waiting {wait:.1f}s: {e}")
                await asyncio.sleep(wait)
                last_exc = e
            except (APIConnectionError, APITimeoutError) as e:
                wait = LLM_RETRY_DELAY * (2 ** attempt)
                logger.warning(f"[LLM] Connection/timeout error, attempt {attempt + 1}/{LLM_MAX_RETRIES}, waiting {wait:.1f}s: {e}")
                await asyncio.sleep(wait)
                last_exc = e
            except APIError as e:
                if getattr(e, "status_code", 500) >= 500:
                    wait = LLM_RETRY_DELAY * (2 ** attempt)
                    logger.warning(f"[LLM] Server error (5xx), attempt {attempt + 1}/{LLM_MAX_RETRIES}, waiting {wait:.1f}s: {e}")
                    await asyncio.sleep(wait)
                    last_exc = e
                else:
                    raise
        raise last_exc or RuntimeError("LLM retry exhausted")

    def _get_tools_param(self):
        if not self.tool_manager:
            return None
        schemas = self.tool_manager.get_all_tools_schema()
        return schemas if schemas else None

    def _get_relevant_tools_param(self, user_text: str = ""):
        """根据用户查询获取相关工具的 schema（工具检索降维）。

        当 tool_manager 支持 get_relevant_tools_schema 时使用预筛选，
        否则回退到全部工具。
        """
        if not self.tool_manager:
            return None
        if hasattr(self.tool_manager, "get_relevant_tools_schema"):
            schemas = self.tool_manager.get_relevant_tools_schema(user_text)
        else:
            schemas = self.tool_manager.get_all_tools_schema()
        return schemas if schemas else None

    @staticmethod
    def _extract_user_text(messages: list) -> str:
        """从 messages 中提取最近一条用户消息文本（用于工具检索）。"""
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                return msg.get("content", "") or ""
        return ""

    def _build_kwargs(self, messages, stream=True, model=None, tools_param=None):
        kwargs = {
            "model": model or self.model,
            "messages": messages,
            "stream": stream,
        }
        tp = tools_param if tools_param is not None else self._get_tools_param()
        if tp:
            kwargs["tools"] = tp
            kwargs["tool_choice"] = "auto"
        return kwargs

    async def stream_chat(self, messages, user_config=None, device_id=None):
        client, model, system_prompt = self._resolve_config(user_config, device_id)

        if not client:
            yield "LLM not configured - this is a mock response"
            return

        # 业务指标：LLM 请求计时起点
        _llm_track_start = time.time()
        _llm_track_status = "success"
        # 计费：累计本轮所有 LLM 调用的 tokens（finally 中暴露给 pipeline）
        total_tokens = 0          # 输出 tokens
        total_input_tokens = 0    # 输入 tokens（含缓存命中）
        total_cache_hit_tokens = 0  # 输入中命中缓存的部分
        # 向下游 LLM 服务传播 trace_id（从 contextvar 读取）
        _trace_headers = {}
        try:
            _tid = trace_id_var.get()
            if _tid:
                _trace_headers["X-Trace-Id"] = _tid
        except Exception:
            pass

        try:
            logger.info(f"{SEP}")
            logger.info("[OpenAI LLM] Starting conversation (with tool chain support)...")

            # 工具检索：根据用户查询预筛选相关工具，减少 LLM 选择空间
            _user_text = self._extract_user_text(messages)
            tools_param = self._get_relevant_tools_param(_user_text)
            round_num = 0
            failed_tool_calls: set = set()

            while round_num < MAX_TOOL_ROUNDS:
                round_num += 1
                is_first = round_num == 1

                if is_first:
                    response = await self._retry(
                        lambda: client.chat.completions.create(
                            model=model,
                            messages=messages,
                            stream=True,
                            # 计费：流式必须显式请求 usage，否则末尾 chunk 不返回 tokens 统计
                            stream_options={"include_usage": True},
                            extra_headers=_trace_headers,
                            **({"tools": tools_param, "tool_choice": "auto"} if tools_param else {}),
                        )
                    )

                    full_text = ""
                    chunk_count = 0
                    reasoning_content = ""
                    raw_tool_calls: dict[int, dict] = {}
                    _tool_call_feedback_sent = False  # 标记是否已发送工具调用反馈

                    logger.info("[OpenAI LLM Pipeline streaming output started]")
                    async for chunk in response:
                        # 计费：usage 通常出现在空 choices 的末尾 chunk，需先于 delta 判空捕获
                        if hasattr(chunk, "usage") and chunk.usage:
                            total_tokens += (chunk.usage.completion_tokens or 0)
                            total_input_tokens += (chunk.usage.prompt_tokens or 0)
                            total_cache_hit_tokens += (getattr(chunk.usage, "prompt_cache_hit_tokens", None) or 0)

                        delta = chunk.choices[0].delta if chunk.choices else None
                        if not delta:
                            continue

                        if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                            reasoning_content += delta.reasoning_content

                        if delta.tool_calls:
                            # 首次检测到工具调用时立即发送反馈
                            # 用 on_tool_status 指令，绝不碰 on_llm_cb/tts_duration，避免干扰 TTS 文字同步
                            if not _tool_call_feedback_sent and self.tool_manager and self.tool_manager.channel:
                                _tool_call_feedback_sent = True
                                try:
                                    await self.tool_manager.channel.send_json({
                                        "type": "instruct",
                                        "command_id": "on_tool_status",
                                        "data": "正在处理中，请稍候...",
                                    })
                                    logger.info("[OpenAI LLM] 检测到工具调用，已发送即时反馈")
                                except Exception as _fb_err:
                                    logger.debug(f"[OpenAI LLM] 发送即时反馈失败: {_fb_err}")

                            for tc in delta.tool_calls:
                                idx = tc.index
                                if idx not in raw_tool_calls:
                                    raw_tool_calls[idx] = {"id": "", "function_name": "", "arguments": ""}
                                if tc.id:
                                    raw_tool_calls[idx]["id"] = tc.id
                                if tc.function:
                                    if tc.function.name:
                                        raw_tool_calls[idx]["function_name"] = tc.function.name
                                    if tc.function.arguments:
                                        raw_tool_calls[idx]["arguments"] += tc.function.arguments

                        if delta.content:
                            if raw_tool_calls:
                                chunk_count += 1
                                full_text += delta.content
                                yield delta.content
                            else:
                                # 无工具调用时也逐 chunk 流式输出：LLM 边生成边送入分句/TTS，
                                # 避免"卡很久才开始第一句"（原实现缓存到 LLM 结束才一次性输出，
                                # 长回答/长故事时用户要等 LLM 全部生成完才听到第一句）
                                full_text += delta.content
                                yield delta.content

                    logger.info(f"[OpenAI LLM Pipeline complete] {chunk_count} chunks total")

                    if not raw_tool_calls:
                        # 没有工具调用：文本已在流式循环中逐 chunk 输出

                        # LLM 没调用工具，检测文本中是否写了函数名并自动执行
                        import re as _re
                        _m = _re.search(r'read_?skill_?document\s*\(\s*["\']?(\w+)["\']?\s*\)', full_text)
                        if _m:
                            _sid = _m.group(1)
                            logger.info(f"[OpenAI LLM] 检测到文本中的 read_skill_document，自动执行: {_sid}")
                            raw_tool_calls[0] = {"id": "_auto_", "function_name": "read_skill_document", "arguments": f'{{"skill_id":"{_sid}"}}'}
                        else:
                            logger.info(f"{SEP}")
                            return

                    logger.info(
                        f"[OpenAI LLM] Tool calls detected (round {round_num}): "
                        f"{[v['function_name'] for v in raw_tool_calls.values()]}"
                    )

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
                    if reasoning_content:
                        assistant_msg["reasoning_content"] = reasoning_content
                    messages.append(assistant_msg)

                    # 工具调用前发送反馈
                    # 用 on_tool_status 指令，绝不碰 on_llm_cb/tts_duration，避免干扰 TTS 文字同步
                    _tool_names = [tc["function_name"] for tc in raw_tool_calls.values()]
                    if self.tool_manager and self.tool_manager.channel:
                        try:
                            _feedback = f"正在执行: {', '.join(_tool_names)}..."
                            await self.tool_manager.channel.send_json({
                                "type": "instruct",
                                "command_id": "on_tool_status",
                                "data": _feedback,
                            })
                            logger.info(f"[OpenAI LLM] 已发送工具调用反馈: {_feedback}")
                        except Exception as _fb_err:
                            logger.debug(f"[OpenAI LLM] 发送工具调用反馈失败: {_fb_err}")

                    for tc_data in raw_tool_calls.values():
                        try:
                            func_args = json.loads(tc_data["arguments"]) if tc_data["arguments"] else {}
                        except json.JSONDecodeError:
                            func_args = {}

                        logger.info(f"[OpenAI LLM] Calling tool: {tc_data['function_name']}({func_args})")

                        tool_key = (tc_data["function_name"], json.dumps(func_args, sort_keys=True, ensure_ascii=False))
                        if tool_key in failed_tool_calls:
                            logger.info(f"[OpenAI LLM] Tool {tc_data['function_name']} already failed, skipping retry")
                            tool_result = "This operation was already attempted but the service is unavailable, please inform the user that this operation cannot be completed and do not try calling this tool again"
                        elif self.tool_manager:
                            try:
                                tool_result = await self.tool_manager.call_tool(tc_data["function_name"], func_args)
                            except StopPipeline:
                                logger.info("[OpenAI LLM] StopPipeline raised during tool call")
                                yield "__STOP_PIPELINE__"
                                return
                            except Exception as e:
                                logger.error(f"[OpenAI LLM] Tool execution exception: {e}")
                                tool_result = f"Tool execution exception: {e}"
                        else:
                            tool_result = f"Tool manager not initialized, cannot call {tc_data['function_name']}"

                        if "unavailable" in str(tool_result) or "failed" in str(tool_result) or "暂不可用" in str(tool_result) or "失败" in str(tool_result):
                            failed_tool_calls.add(tool_key)

                        logger.info(f"[OpenAI LLM] Tool {tc_data['function_name']} returned: {str(tool_result)[:200]}")
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_data["id"],
                                "content": str(tool_result),
                            }
                        )

                    # 所有工具执行完毕，清除客户端工具状态显示
                    if self.tool_manager and self.tool_manager.channel:
                        try:
                            await self.tool_manager.channel.send_json({
                                "type": "instruct",
                                "command_id": "on_tool_status",
                                "data": "",
                            })
                            logger.info("[OpenAI LLM] 工具执行完毕，已发送清除指令")
                        except Exception as _clr_err:
                            logger.debug(f"[OpenAI LLM] 发送清除指令失败: {_clr_err}")
                else:
                    logger.info(f"[OpenAI LLM] Tool loop round {round_num} (streaming)...")

                    response = await self._retry(
                        lambda _tools_param=tools_param, _model=model: client.chat.completions.create(
                            model=_model,
                            messages=messages,
                            stream=True,
                            # 计费：流式必须显式请求 usage，否则末尾 chunk 不返回 tokens 统计
                            stream_options={"include_usage": True},
                            extra_headers=_trace_headers,
                            **({"tools": _tools_param, "tool_choice": "auto"} if _tools_param else {}),
                        )
                    )

                    full_text = ""
                    chunk_count = 0
                    reasoning_content = ""
                    raw_tool_calls: dict[int, dict] = {}

                    logger.info(f"[OpenAI LLM Pipeline streaming output started (round {round_num})]")
                    async for chunk in response:
                        # 计费：usage 通常出现在空 choices 的末尾 chunk，需先于 delta 判空捕获
                        if hasattr(chunk, "usage") and chunk.usage:
                            total_tokens += (chunk.usage.completion_tokens or 0)
                            total_input_tokens += (chunk.usage.prompt_tokens or 0)
                            total_cache_hit_tokens += (getattr(chunk.usage, "prompt_cache_hit_tokens", None) or 0)

                        delta = chunk.choices[0].delta if chunk.choices else None
                        if not delta:
                            continue

                        if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                            reasoning_content += delta.reasoning_content

                        if delta.tool_calls:
                            for tc in delta.tool_calls:
                                idx = tc.index
                                if idx not in raw_tool_calls:
                                    raw_tool_calls[idx] = {"id": "", "function_name": "", "arguments": ""}
                                if tc.id:
                                    raw_tool_calls[idx]["id"] = tc.id
                                if tc.function:
                                    if tc.function.name:
                                        raw_tool_calls[idx]["function_name"] = tc.function.name
                                    if tc.function.arguments:
                                        raw_tool_calls[idx]["arguments"] += tc.function.arguments

                        if delta.content:
                            chunk_count += 1
                            full_text += delta.content
                            yield delta.content

                    logger.info(f"[OpenAI LLM Pipeline complete (round {round_num})] {chunk_count} chunks total")

                    if not raw_tool_calls:
                        # 没有工具调用，文本已在上面的流式循环中逐字 yield，这里直接结束
                        logger.info(f"[OpenAI LLM] Final response (round {round_num}): {full_text[:200]}")
                        logger.info(f"{SEP}")
                        return

                    logger.info(
                        f"[OpenAI LLM] Tool calls detected (round {round_num}): "
                        f"{[v['function_name'] for v in raw_tool_calls.values()]}"
                    )

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
                    if reasoning_content:
                        assistant_msg["reasoning_content"] = reasoning_content
                    messages.append(assistant_msg)

                    for tc_data in raw_tool_calls.values():
                        try:
                            func_args = json.loads(tc_data["arguments"]) if tc_data["arguments"] else {}
                        except json.JSONDecodeError:
                            func_args = {}

                        logger.info(f"[OpenAI LLM] Calling tool: {tc_data['function_name']}({func_args})")

                        tool_key = (tc_data["function_name"], json.dumps(func_args, sort_keys=True, ensure_ascii=False))
                        if tool_key in failed_tool_calls:
                            logger.info(f"[OpenAI LLM] Tool {tc_data['function_name']} already failed, skipping retry")
                            tool_result = "This operation was already attempted but the service is unavailable, please inform the user that this operation cannot be completed and do not try calling this tool again"
                        elif self.tool_manager:
                            try:
                                tool_result = await self.tool_manager.call_tool(tc_data["function_name"], func_args)
                            except StopPipeline:
                                logger.info("[OpenAI LLM] StopPipeline raised during tool call (streaming)")
                                yield "__STOP_PIPELINE__"
                                return
                            except Exception as e:
                                logger.error(f"[OpenAI LLM] Tool execution exception: {e}")
                                tool_result = f"Tool execution exception: {e}"
                        else:
                            tool_result = f"Tool manager not initialized, cannot call {tc_data['function_name']}"

                        if "unavailable" in str(tool_result) or "failed" in str(tool_result) or "暂不可用" in str(tool_result) or "失败" in str(tool_result):
                            failed_tool_calls.add(tool_key)

                        logger.info(f"[OpenAI LLM] Tool {tc_data['function_name']} returned: {str(tool_result)[:200]}")
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_data["id"],
                                "content": str(tool_result),
                            }
                        )

                    # 所有工具执行完毕，清除客户端工具状态显示
                    if self.tool_manager and self.tool_manager.channel:
                        try:
                            await self.tool_manager.channel.send_json({
                                "type": "instruct",
                                "command_id": "on_tool_status",
                                "data": "",
                            })
                            logger.info("[OpenAI LLM] 工具执行完毕，已发送清除指令")
                        except Exception as _clr_err:
                            logger.debug(f"[OpenAI LLM] 发送清除指令失败: {_clr_err}")

            yield "Maximum tool call rounds reached, please simplify your request."
            logger.info(f"{SEP}")

        except StopPipeline:
            raise
        except Exception as e:
            _llm_track_status = "error"
            logger.error(f"[OpenAI LLM] Streaming request exception (after {LLM_MAX_RETRIES} retries): {e}")
            yield f"LLM error: {str(e)}"
        finally:
            # 计费：暴露本轮累计 tokens，供 pipeline 读取
            self.last_completion_tokens = total_tokens
            self.last_prompt_tokens = total_input_tokens
            self.last_cache_hit_tokens = total_cache_hit_tokens
            # 业务指标：LLM 请求结果与耗时
            try:
                get_metrics().track_llm_request(self.model or "openai", _llm_track_status, time.time() - _llm_track_start)
            except Exception:
                pass

    async def process_text(self, text, user_config=None, device_id=None):
        client, model, system_prompt = self._resolve_config(user_config, device_id)

        if not client:
            return "LLM not configured - this is a mock response"

        try:
            logger.info(f"{SEP}")
            logger.info("[OpenAI LLM] Requesting LLM...")
            messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": text}]

            async def _call():
                return await client.chat.completions.create(model=model, messages=messages, stream=False)

            response = await self._retry(_call)
            llm_response = response.choices[0].message.content
            logger.info("[OpenAI LLM Response]")
            logger.info(llm_response)
            logger.info(f"{SEP}")
            return llm_response
        except Exception as e:
            logger.error(f"[OpenAI LLM] Request exception (after {LLM_MAX_RETRIES} retries): {e}")
            return f"LLM request failed: {str(e)}"

    async def generate_response_stream(self, text, user_config=None, device_id=None):
        client, model, system_prompt = self._resolve_config(user_config, device_id)

        if not client:
            yield "LLM not configured - this is a mock response"
            return

        start_time = time.time()
        first_token_time = None
        status = "success"

        try:
            logger.info(f"{SEP}")
            logger.info("[OpenAI LLM] Streaming request to LLM...")
            messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": text}]

            async def _call():
                return await client.chat.completions.create(model=model, messages=messages, stream=True)

            response = await self._retry(_call)

            full_text = ""
            chunk_count = 0
            raw_tool_calls = {}
            total_tokens = 0

            logger.info("[OpenAI LLM Pipeline streaming output started]")
            async for chunk in response:
                if first_token_time is None:
                    first_token_time = time.time()
                delta = chunk.choices[0].delta if chunk.choices else None
                if not delta:
                    continue

                if hasattr(chunk, "usage") and chunk.usage:
                    total_tokens += (chunk.usage.completion_tokens or 0)

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in raw_tool_calls:
                            raw_tool_calls[idx] = {"id": "", "function_name": "", "arguments": ""}
                        if tc.id:
                            raw_tool_calls[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                raw_tool_calls[idx]["function_name"] = tc.function.name
                            if tc.function.arguments:
                                raw_tool_calls[idx]["arguments"] += tc.function.arguments

                if delta.content:
                    chunk_count += 1
                    full_text += delta.content
                    yield delta.content

            logger.info(f"[OpenAI LLM Pipeline complete] {chunk_count} chunks total")

            if raw_tool_calls:
                logger.info(f"[OpenAI LLM] Tool calls detected: {[v['function_name'] for v in raw_tool_calls.values()]}")
                status = "tool_call"

                tool_results = []
                for tc_data in raw_tool_calls.values():
                    result = await self._execute_tool_calls(
                        [
                            type(
                                "TC",
                                (),
                                {
                                    "id": tc_data["id"],
                                    "function": type(
                                        "FN", (), {"name": tc_data["function_name"], "arguments": tc_data["arguments"]}
                                    ),
                                },
                            )
                        ]
                    )
                    tool_results.append(result)

                if full_text:
                    yield THIN_SEP
                    yield full_text

                yield tool_results[0] if tool_results else ""
                raise StopPipeline()
            else:
                logger.info(f"[OpenAI LLM] Streaming output complete: {full_text[:200]}...")
                logger.info(f"{SEP}")

        except StopPipeline:
            raise
        except Exception as e:
            status = "error"
            logger.error(f"[OpenAI LLM] Streaming request exception (after {LLM_MAX_RETRIES} retries): {e}")
            yield f"LLM request failed: {str(e)}"
        finally:
            duration = time.time() - start_time
            LLM_COMPLETION_DURATION.labels(status=status).observe(duration)
            LLM_COMPLETION_TOTAL.labels(status=status).inc()
            if first_token_time is not None:
                first_token_latency = first_token_time - start_time
                LLM_FIRST_TOKEN_LATENCY.observe(first_token_latency)

    async def _execute_tool_calls(self, tool_calls):
        messages = []
        for tc in tool_calls:
            func_name = tc.function.name
            try:
                func_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                func_args = {}

            logger.info(f"[OpenAI LLM] Calling tool: {func_name}({func_args})")

            if self.tool_manager:
                try:
                    tool_result = await self.tool_manager.call_tool(func_name, func_args)
                except StopPipeline:
                    raise
            else:
                tool_result = f"Tool manager not initialized, cannot call {func_name}"

            logger.info(f"[OpenAI LLM] Tool {func_name} returned: {tool_result[:200]}")

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result,
                }
            )
        return json.dumps(messages, ensure_ascii=False)

    async def stream_with_tools(self, text, user_config=None, device_id=None):
        client, model, system_prompt = self._resolve_config(user_config, device_id)

        if not client:
            yield "LLM not configured - this is a mock response"
            return

        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": text}]

        # 工具检索：根据用户查询预筛选相关工具
        _relevant_tools = self._get_relevant_tools_param(text)

        for round_num in range(MAX_TOOL_ROUNDS):
            try:
                kwargs = self._build_kwargs(messages, stream=False, model=model, tools_param=_relevant_tools)
                logger.info(f"{SEP}")
                logger.info(f"[OpenAI LLM] Pipeline non-streaming request (round {round_num + 1})...")

                async def _call_non_stream(_kwargs=kwargs, _client=client):
                    return await _client.chat.completions.create(**_kwargs)

                response = await self._retry(_call_non_stream)
                message = response.choices[0].message

                if message.tool_calls:
                    tool_calls = message.tool_calls

                    if message.content:
                        if hasattr(message, "reasoning_content") and message.reasoning_content:
                            logger.info("[OpenAI LLM] Replaced with non-streaming message (with reasoning_content)")
                        yield message.content

                    assistant_msg = {"role": "assistant", "content": message.content or ""}
                    if hasattr(message, "reasoning_content") and message.reasoning_content:
                        assistant_msg["reasoning_content"] = message.reasoning_content
                    tool_calls_list = []
                    for tc in tool_calls:
                        tool_calls_list.append(
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                        )
                    assistant_msg["tool_calls"] = tool_calls_list
                    messages.append(assistant_msg)

                    try:
                        tool_result = await self._execute_tool_calls(tool_calls)
                        tool_msgs = json.loads(tool_result) if isinstance(tool_result, str) else tool_result
                        messages.extend(tool_msgs if isinstance(tool_msgs, list) else [tool_msgs])
                    except StopPipeline:
                        raise
                    except Exception as e:
                        logger.error(f"[OpenAI LLM] Tool call exception: {e}")
                        yield f"Tool call failed: {str(e)}"
                        return
                else:
                    llm_response = message.content
                    logger.info(f"[OpenAI LLM] Final response: {llm_response[:200]}")
                    logger.info(f"{SEP}")
                    yield llm_response
                    return

            except StopPipeline:
                raise
            except Exception as e:
                logger.error(f"[OpenAI LLM] Tool loop exception (after {LLM_MAX_RETRIES} retries): {e}")
                yield f"LLM request failed: {str(e)}"
                return

        yield "Maximum tool call rounds reached, please simplify your request."

    async def generate(self, messages, **kwargs):
        user_config = kwargs.get("user_config")
        device_id = kwargs.get("device_id")
        client, model, system_prompt = self._resolve_config(user_config, device_id)

        if not client:
            return "LLM not configured - this is a mock response"

        api_messages = (
            [{"role": "system", "content": system_prompt}] + messages
            if not any(m.get("role") == "system" for m in messages)
            else messages
        )

        async def _call():
            return await client.chat.completions.create(
                model=model,
                messages=api_messages,
                stream=False,
                temperature=kwargs.get("temperature", self.temperature),
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
            )

        response = await self._retry(_call)
        return response.choices[0].message.content

    async def generate_stream(self, messages, **kwargs):
        user_config = kwargs.get("user_config")
        device_id = kwargs.get("device_id")
        client, model, system_prompt = self._resolve_config(user_config, device_id)

        if not client:
            yield "LLM not configured - this is a mock response"
            return

        api_messages = (
            [{"role": "system", "content": system_prompt}] + messages
            if not any(m.get("role") == "system" for m in messages)
            else messages
        )

        tools = kwargs.get("tools")
        if tools is None:
            _user_text = self._extract_user_text(api_messages)
            tools = self._get_relevant_tools_param(_user_text)

        async def _call():
            create_kwargs = {
                "model": model,
                "messages": api_messages,
                "stream": True,
                "temperature": kwargs.get("temperature", self.temperature),
                "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            }
            if tools:
                create_kwargs["tools"] = tools
                create_kwargs["tool_choice"] = "auto"
            return await client.chat.completions.create(**create_kwargs)

        response = await self._retry(_call)

        raw_tool_calls = {}
        async for chunk in response:
            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                continue

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in raw_tool_calls:
                        raw_tool_calls[idx] = {"id": "", "function_name": "", "arguments": ""}
                    if tc.id:
                        raw_tool_calls[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            raw_tool_calls[idx]["function_name"] = tc.function.name
                        if tc.function.arguments:
                            raw_tool_calls[idx]["arguments"] += tc.function.arguments

            if delta.content:
                yield delta.content

        if raw_tool_calls:
            yield json.dumps({
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
                ]
            })

    async def call_tool(self, tool_name, arguments, **kwargs):
        if self.tool_manager:
            try:
                return await self.tool_manager.call_tool(tool_name, arguments)
            except StopPipeline:
                raise
            except Exception as e:
                return {"error": f"Tool execution failed: {e}"}
        tool_gateway = kwargs.get("tool_gateway")
        if tool_gateway:
            return await tool_gateway.execute_tool(tool_name, arguments)
        return {"error": "Tool manager not configured"}


def create_llm_gateway(config=None, tool_manager=None):
    return OpenAILLMGateway(config=config, tool_manager=tool_manager)
