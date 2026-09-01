"""SDK 计费上报 - 插件主动上报本轮用量，接入框架计费系统。

插件在完成一次外部 AI 服务调用后，把实际用量上报给当前会话的计费累加器，
框架按配置单价计算费用并生成计费记录。适用于非火山/DeepSeek 的第三方服务
（服务商返回格式不同、框架无法自动解析用量时，由插件自行上报）。

用法（插件工具函数需声明 tool_manager 参数）：
    from src.use_cases.sdk.billing import add_asr, add_llm, add_tts

    @tool
    async def my_asr(audio: str, tool_manager=None):
        minutes = ...  # 从服务响应解析实际时长（分钟）
        add_asr(minutes, tool_manager=tool_manager)
        return result

计费口径与框架内置一致：
    - ASR 按时长（分钟）
    - LLM 按 tokens（输入/输出/缓存命中）
    - TTS 按字数
"""

from src.infrastructure.plugin_security import require_permission


def _get_billing(tool_manager):
    """从 tool_manager 读取当前会话的计费累加器（无会话时返回 None）。"""
    if tool_manager is None:
        return None
    return getattr(tool_manager, "billing", None)


def add_asr(minutes: float, tool_manager=None) -> None:
    """上报 ASR 用量（分钟）。"""
    require_permission("billing", "上报 ASR 计费用量")
    billing = _get_billing(tool_manager)
    if billing is not None:
        billing.add_asr(minutes)


def add_llm(input_tokens: int = 0, output_tokens: int = 0, cache_hit_tokens: int = 0, tool_manager=None) -> None:
    """上报 LLM 用量（tokens：输入/输出/缓存命中）。"""
    require_permission("billing", "上报 LLM 计费用量")
    billing = _get_billing(tool_manager)
    if billing is not None:
        billing.add_llm(output_tokens=output_tokens, input_tokens=input_tokens, cache_hit_tokens=cache_hit_tokens)


def add_tts(chars: int, tool_manager=None) -> None:
    """上报 TTS 用量（字数）。"""
    require_permission("billing", "上报 TTS 计费用量")
    billing = _get_billing(tool_manager)
    if billing is not None:
        billing.add_tts(chars)
