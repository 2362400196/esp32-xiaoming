"""WS 会话 AI 成长任务：触发、冷却与 LLM 调用。"""
from __future__ import annotations

import asyncio

from src.infrastructure.logging import get_logger
from src.infrastructure.task_manager import background_task

logger = get_logger(__name__)


class GrowthMixin:
    """成长系统相关方法。"""

    def _trigger_growth(self) -> None:
        """触发成长任务（冷却期后执行）"""
        session = self.session
        if not self._growth_system or not session.conversation_memory or not session.conversation_memory.messages:
            return

        self._growth_last_messages = list(session.conversation_memory.messages)

        # 取消之前的冷却定时器
        if self._growth_cooldown_task and not self._growth_cooldown_task.done():
            self._growth_cooldown_task.cancel()

        # 启动新的冷却定时器
        self._growth_cooldown_task = background_task(
            self._growth_cooldown_timer(self.device_key, self._growth_last_messages),
            name="growth_cooldown",
        )
        logger.info(f"[Growth] 已启动成长任务冷却定时器（{self._growth_cooldown_seconds}秒）: {self.device_key[:16]}")


    async def _llm_call_for_growth(self, system_prompt: str, user_prompt: str) -> str:
        """成长系统用的LLM调用函数 - 复用主流程LLM gateway的客户端配置"""
        llm_processor = self.llm_processor
        user_config = self.user_config
        if not llm_processor:
            raise RuntimeError("LLM processor not available")

        try:
            # 复用主流程的 client + model 解析，确保 device_config 中的 base_url 正确生效
            client, model, _ = llm_processor._resolve_config(user_config)

            if client is not None:
                # 传统直连模式：有 OpenAI client 可以直接调用
                response = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.3,
                    max_tokens=4000,
                )

                result = response.choices[0].message.content or ""
                logger.debug(f"[Growth] LLM直接调用返回: {result[:200]}")
                return result

        except Exception as e:
            logger.error(f"[Growth] LLM直接调用失败: {e}")

        # 插件模式或直接调用失败：回退到 stream_chat 收集完整结果
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        result = ""
        async for token in llm_processor.stream_chat(messages, user_config=user_config):
            if isinstance(token, str) and not token.startswith("[LLM"):
                result += token
        if not result and llm_processor:
            # 如果仍然为空，可能是 LLM 插件返回了错误，记录一下
            logger.warning(f"[Growth] LLM返回为空，可能是插件配置问题")
        return result

    async def _growth_cooldown_timer(self, device_id: str, messages: list) -> None:
        """冷却定时器 - 等待一段时间后执行成长任务"""
        await asyncio.sleep(self._growth_cooldown_seconds)
        if self._growth_system:
            try:
                await self._growth_system.on_conversation_end(device_id, messages)
                logger.info(f"[Growth] 成长任务完成: {device_id[:16]}")
            except Exception as e:
                logger.warning(f"[Growth] 成长任务失败: {e}")

