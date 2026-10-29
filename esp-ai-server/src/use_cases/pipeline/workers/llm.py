"""LLM Worker：流式生成 → 分句 → text_queue。"""
from __future__ import annotations

import asyncio
import time

from src.infrastructure.logging import get_logger
from src.use_cases.pipeline.signals import LLM_ERROR_PREFIX, STOP_PIPELINE_SENTINEL

logger = get_logger(__name__)


class LlmWorkerMixin:
    """LLM Worker：调用 LLM 并把增量文本切分入队。"""

    MAX_CHARS = 2000  # 回复合成字符上限（兜底，防止单个超长句）

    async def _llm_task(self, llm, messages):
        """LLM Worker：流式生成 → 分句 → text_queue"""
        seq_id = 0
        full_text = ""
        self._hard_sentence_count = 0
        fed_chars = 0
        _perf = self._perf
        _perf["llm_start"] = time.time()
        _perf["llm_first_token"] = 0.0
        from src.use_cases.tools_system import StopPipeline
        try:
            async for token in llm.stream_chat(messages):
                if self.cancel_event.is_set():
                    logger.info("[Pipeline] LLM 收到取消信号")
                    break

                if token == STOP_PIPELINE_SENTINEL:
                    logger.info("[Pipeline] LLM 发出 StopPipeline 信号")
                    raise StopPipeline()

                if token.startswith(LLM_ERROR_PREFIX):
                    logger.error(f"[Pipeline] LLM 错误: {token}")
                    break

                if not _perf["llm_first_token"]:
                    _perf["llm_first_token"] = time.time()

                full_text += token
                sentences = self.splitter.feed(token)
                for sentence in sentences:
                    if self.cancel_event.is_set():
                        break
                    # 上限按完整句子（句号/感叹号/问号结尾）计数，而非逗号软切分片段，
                    # 避免"哈哈，"这类称呼片段浪费句数预算导致回复被截断。
                    # fed_chars>0 保证首句始终送入 TTS，避免单句超长时整轮静音
                    if self._hard_sentence_count >= self.max_sentences or (fed_chars > 0 and fed_chars + len(sentence) > self.MAX_CHARS):
                        logger.debug(f"[Pipeline] 超过回复上限，丢弃后续片段: {sentence[:30]}...")
                        continue
                    await self.queues.text.put((seq_id, sentence))
                    logger.debug(f"[Pipeline] 句子 #{seq_id} 入 text_queue: {sentence[:50]}...")
                    seq_id += 1
                    fed_chars += len(sentence)
                    if sentence[-1] in "。！？.!?":
                        self._hard_sentence_count += 1

            if not self.cancel_event.is_set():
                remaining = self.splitter.flush()
                if remaining and self._hard_sentence_count < self.max_sentences and (fed_chars == 0 or fed_chars + len(remaining) <= self.MAX_CHARS):
                    await self.queues.text.put((seq_id, remaining))
                    seq_id += 1

        except StopPipeline:
            raise
        except Exception as e:
            logger.error(f"[Pipeline] LLM 任务异常: {e}")
        finally:
            self.queues.text.put_nowait((-1, None))
            _perf["llm_end"] = time.time()
            _perf["llm_chars"] = len(full_text)
            _perf["llm_sentences"] = seq_id
            # 计费：累加 LLM tokens（网关已按本轮所有调用累计 completion/prompt/cache_hit）
            if self.billing is not None:
                _llm_tokens = getattr(llm, "last_completion_tokens", 0) or 0
                _llm_input = getattr(llm, "last_prompt_tokens", 0) or 0
                _llm_cache_hit = getattr(llm, "last_cache_hit_tokens", 0) or 0
                self.billing.add_llm(output_tokens=_llm_tokens, input_tokens=_llm_input, cache_hit_tokens=_llm_cache_hit)
            logger.info(f"[Pipeline] LLM 结束，共 {seq_id} 句，full_text={len(full_text)}字符")

        memory_enabled = True
        if self.user_config and getattr(self.user_config, "llm_memory_enabled", None) is not None:
            memory_enabled = self.user_config.llm_memory_enabled
        _mem = self.conversation_memory
        _log_ctx = f"mem_enabled={memory_enabled} full_text_len={len(full_text)} conv_mem={_mem is not None}"
        if _mem:
            _log_ctx += f" _msgs={len(_mem._messages)} repo={_mem._repository is not None}"
        logger.info(f"[Pipeline] 记忆检查: {_log_ctx}")
        if memory_enabled and full_text and self.conversation_memory:
            # 取最后一条 user 消息（即当前轮用户输入，而非历史中最旧的）
            iat_text = ""
            if messages:
                for _m in reversed(messages):
                    if isinstance(_m, dict) and _m.get("role") == "user":
                        iat_text = _m.get("content", "")
                        break
                logger.info(f"[Pipeline] 记忆: messages共{len(messages)}条, user_msg_len={len(iat_text)}")
            if iat_text:
                self.conversation_memory.add_user_message(iat_text)
                self.conversation_memory.add_assistant_message(full_text)

            # 异步触发长期记忆自动提取
            if self.device_id and iat_text and self.ltm_service:
                _device_id = self.device_id
                _user_text = iat_text

                async def _do_auto_extract():
                    try:
                        # 过滤简短闲聊（少于10个字或只有打招呼内容），不浪费 token
                        _user_text_clean = _user_text.strip()
                        if len(_user_text_clean) < 10 or _user_text_clean in ("你好", "你好呀", "hi", "hello", "在吗", "在不在"):
                            return
                        catalog = await self.ltm_service.get_summary_catalog(_device_id)
                        if not catalog:
                            return
                        summaries = await self.ltm_service.auto_extract(
                            _device_id,
                            _user_text,
                            lambda sys_p, usr_p: (
                                self.llm_processor.generate([
                                    {"role": "system", "content": sys_p},
                                    {"role": "user", "content": usr_p},
                                ])
                            ),
                        )
                        if summaries:
                            logger.info(f"[LTM] 自动提取: {summaries}")
                    except Exception as e:
                        logger.debug(f"[LTM] 自动提取摘要失败: {e}")

                _t = asyncio.create_task(_do_auto_extract())
                self._bg_tasks.add(_t)
                _t.add_done_callback(self._bg_tasks.discard)

        return full_text
