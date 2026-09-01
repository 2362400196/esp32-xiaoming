"""插件网关包装器

实现与现有网关（OpenAILLMGateway / VolcEngineTTSGateway / BaseASRGateway）
相同的接口，但委托给 ServicePluginAdapter。

设计目标：
  插件开发者只需在 plugin.py 中实现工具函数，框架通过此包装器透明集成。
  Session/Pipeline 代码无需修改，因为包装器实现了相同的 duck-typing 接口。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator, Optional

from src.infrastructure.logging import get_logger
from src.infrastructure.monitoring import get_metrics
from src.interfaces.service_plugin_adapter import (
    call_llm_chat,
    call_tts_synthesize,
    create_asr_session,
    prewarm_asr,
    ASRPluginSession,
    has_llm_plugin,
    has_tts_plugin,
    has_asr_plugin,
)
from src.interfaces.tts_gateways import TTSSynthEvent

logger = get_logger(__name__)

# ═══════════════════════════════════════════════════════════════
# LLM 插件网关
# ═══════════════════════════════════════════════════════════════


class PluginLLMGateway:
    """LLM 插件网关包装器

    实现与 OpenAILLMGateway 兼容的 duck-typing 接口：
      - stream_chat(messages, user_config, device_id) -> AsyncIterator[str]
      - generate(messages, **kwargs) -> str
      - system_prompt / tool_manager 属性
      - _resolve_config(user_config, device_id) -> (None, None, system_prompt)

    Pipeline 和 Growth 系统可直接使用此对象，无需区分是插件还是直连模式。
    """

    def __init__(self, config: dict | None = None, tool_manager=None):
        self.config = dict(config or {})
        self.tool_manager = tool_manager
        self.system_prompt = (config or {}).get("system_prompt", "")

    def _resolve_config(self, user_config=None, device_id=None):
        """返回 (None, None, system_prompt)

        插件模式下没有 OpenAI client，返回 None 让调用方（如 Growth 系统）
        回退到 stream_chat 路径。
        """
        sp = self.system_prompt
        if user_config:
            if hasattr(user_config, "llm_system_prompt") and user_config.llm_system_prompt:
                sp = user_config.llm_system_prompt
        return None, None, sp

    async def stream_chat(self, messages, user_config=None, device_id=None):
        """流式对话 - 委托给 LLM 服务插件

        注意：与 OpenAILLMGateway.stream_chat 不同，此方法不处理工具调用链。
        插件目前只返回纯文本。如需工具调用支持，可在插件内部实现或后续扩展。
        """
        config = self._build_plugin_config(user_config)
        _start = time.time()
        _status = "success"
        # 计费：收集本轮 tokens，流结束后暴露给 pipeline
        _usage_sink: dict = {}

        try:
            async for token in call_llm_chat(messages, config, self.tool_manager, usage_sink=_usage_sink):
                if token.startswith("[LLM"):
                    if "error" in token:
                        _status = "error"
                        logger.warning(f"[PluginLLM] {token}")
                    yield token
                    if "not configured" in token:
                        return
                else:
                    yield token
        except Exception as e:
            _status = "error"
            logger.error(f"[PluginLLM] stream_chat 异常: {e}")
            yield f"LLM error: {str(e)}"
        finally:
            try:
                get_metrics().track_llm_request("plugin", _status, time.time() - _start)
            except Exception:
                pass
            # 计费：暴露本轮累计 tokens，供 pipeline 读取
            self.last_prompt_tokens = _usage_sink.get("input_tokens", 0)
            self.last_completion_tokens = _usage_sink.get("output_tokens", 0)
            self.last_cache_hit_tokens = _usage_sink.get("cache_hit_tokens", 0)

    async def generate(self, messages, **kwargs):
        """非流式生成 - 收集所有 token 后返回完整文本"""
        result = ""
        config = self._build_plugin_config(kwargs.get("user_config"))
        async for token in call_llm_chat(messages, config, self.tool_manager):
            if not token.startswith("[LLM"):
                result += token
        return result or "LLM not configured"

    def _build_plugin_config(self, user_config=None) -> dict:
        config = dict(self.config)
        if user_config:
            if hasattr(user_config, "llm_api_key") and user_config.llm_api_key:
                config["api_key"] = user_config.llm_api_key
            if hasattr(user_config, "llm_base_url") and user_config.llm_base_url:
                config["base_url"] = user_config.llm_base_url
            if hasattr(user_config, "llm_model") and user_config.llm_model:
                config["model"] = user_config.llm_model
            if hasattr(user_config, "llm_system_prompt") and user_config.llm_system_prompt:
                config["system_prompt"] = user_config.llm_system_prompt
        return config


# ═══════════════════════════════════════════════════════════════
# TTS 插件网关
# ═══════════════════════════════════════════════════════════════


class PluginTTSSession:
    """TTS 插件会话

    实现与 VolcEngineTTS session 兼容的接口：
      - synthesize(text, cancel_event) -> AsyncIterator[TTSSynthEvent]
      - close()
    """

    def __init__(self, config: dict | None = None, tool_manager=None):
        self._config = config or {}
        self._tool_manager = tool_manager

    async def synthesize(self, text: str, cancel_event=None, **kwargs) -> AsyncIterator[TTSSynthEvent]:
        """流式合成 - 委托给 TTS 服务插件，逐事件产出（audio/subtitle）"""
        try:
            async for event in call_tts_synthesize(
                text, self._config, self._tool_manager,
            ):
                if cancel_event and cancel_event.is_set():
                    break
                if event:
                    yield event
        except Exception as e:
            logger.error(f"[PluginTTS] synthesize 异常: {e}")

    async def close(self):
        pass


class PluginTTSGateway:
    """TTS 插件网关包装器

    实现与 VolcEngineTTSGateway 兼容的 duck-typing 接口：
      - create_session(cancel_event, tool_manager) -> PluginTTSSession
    """

    def __init__(self, config: dict | None = None):
        self.config = dict(config or {})

    async def create_session(self, cancel_event=None, tool_manager=None):
        """创建 TTS 合成会话"""
        return PluginTTSSession(config=self.config, tool_manager=tool_manager)


# ═══════════════════════════════════════════════════════════════
# ASR 插件网关
# ═══════════════════════════════════════════════════════════════


class PluginASRGateway:
    """ASR 插件网关包装器

    实现与 BaseASRGateway 兼容的 duck-typing 接口。
    注意：此网关不管理 WebSocket 连接，所有 WS 逻辑在插件内部。
    Session.py 的 _asr_streaming_loop 会检测 is_plugin 标志并走专有路径。

    属性:
      is_plugin: True，供 Session.py 检测
      binary_protocol: False，插件内部处理二进制协议
    """

    is_plugin: bool = True
    binary_protocol: bool = False
    _enable_pool: bool = False

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self._plugin_session: ASRPluginSession | None = None
        self._tool_manager = None
        self._audio_ended: bool = False          # 音频发送是否已结束
        self._final_text: str = ""               # 最终识别文本
        self._final_set: bool = False             # 是否已获取最终结果

    def set_tool_manager(self, tm):
        self._tool_manager = tm

    # ── BaseASRGateway 兼容方法 ────────────────────────────────

    def _build_url(self) -> str:
        return ""

    def _get_headers(self) -> dict:
        return {}

    async def init_connection(self, ws: Any) -> bool:
        """创建插件 ASR 会话。

        ws 参数保留以兼容接口，实际不使用。
        """
        # 上一轮可能残留已结束的标志位，新一轮必须重置
        self._audio_ended = False
        self._final_set = False
        self._final_text = ""
        self._plugin_session = await create_asr_session(
            self.config, self._tool_manager,
        )
        return self._plugin_session is not None

    async def send_audio_data(self, ws: Any, audio_data: bytes) -> None:
        """发送音频数据到插件，结果由 get_result 获取。"""
        if self._plugin_session and not self._audio_ended:
            result = await self._plugin_session.send_audio(audio_data, self._tool_manager)
            if isinstance(result, dict) and result.get("error"):
                logger.error(f"[PluginASR] 发送音频失败: {result['error']}")

    async def send_audio_end(self, ws: Any) -> str:
        """通知插件音频发送结束，关闭插件会话并缓存最终结果。"""
        if self._plugin_session and not self._audio_ended:
            self._audio_ended = True
            self._final_text = await self._plugin_session.close(self._tool_manager)
            self._plugin_session = None
            self._final_set = True
        return self._final_text

    def parse_response(self, response: Any) -> Optional[dict]:
        """插件模式下不应调用此方法，由专有循环处理。"""
        return None

    def take_pre_ws(self):
        """插件模式不支持预连接"""
        return None, None

    async def pre_connect(self):
        """设备连接时预热 ASR 连接池，确保首次语音输入免建连。

        预热在后台异步执行，不阻塞设备连接流程；连接由框架连接池统一管理。
        """
        async def _warm():
            try:
                created = await prewarm_asr(self.config, self._tool_manager)
                if created:
                    logger.info(f"[PluginASR] 设备连接预热 {created} 个 ASR 连接")
            except Exception as e:
                logger.debug(f"[PluginASR] 预热连接失败: {e}")

        try:
            asyncio.get_running_loop().create_task(_warm())
        except Exception:
            pass
        return None

    # ── 插件专有方法 ───────────────────────────────────────────

    async def plugin_get_result(self) -> dict:
        """获取当前 ASR 识别结果

        如果音频已结束且有最终文本 -> 返回 is_final=True
        如果会话活跃 -> 调用 get_result 轮询
        其他 -> 返回 is_final=True
        """
        if self._final_set:
            return {"text": self._final_text, "is_final": True}
        if self._plugin_session and not self._plugin_session._closed:
            return await self._plugin_session.get_result(self._tool_manager)
        return {"text": "", "is_final": True}

    def plugin_session_active(self) -> bool:
        return self._plugin_session is not None and not self._plugin_session._closed


# ═══════════════════════════════════════════════════════════════
# 工厂函数
# ═══════════════════════════════════════════════════════════════


def create_plugin_llm_gateway(config=None, tool_manager=None) -> PluginLLMGateway | None:
    """当 LLM 服务插件可用时创建插件网关，否则返回 None"""
    if has_llm_plugin():
        logger.info("[PluginGateway] 使用 LLM 插件网关")
        return PluginLLMGateway(config=config, tool_manager=tool_manager)
    return None


def create_plugin_tts_gateway(config=None) -> PluginTTSGateway | None:
    """当 TTS 服务插件可用时创建插件网关，否则返回 None"""
    if has_tts_plugin():
        logger.info("[PluginGateway] 使用 TTS 插件网关")
        return PluginTTSGateway(config=config)
    return None


def create_plugin_asr_gateway(config=None) -> PluginASRGateway | None:
    """当 ASR 服务插件可用时创建插件网关，否则返回 None"""
    if has_asr_plugin():
        logger.info("[PluginGateway] 使用 ASR 插件网关")
        return PluginASRGateway(config=config)
    return None