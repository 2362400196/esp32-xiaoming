"""流水线流内控制信号与错误 token 约定。

LLM 网关/插件适配器通过 token 流中的字面量传递停止/错误信号，
两侧必须保持一致，不要在流中新增裸字符串信号。
"""
from __future__ import annotations

# 流内控制信号常量：LLM 网关（src/interfaces/llm_gateways.py）以这些字面量在 token 流中
# 传递停止/错误信号，两侧必须保持一致，不要在流中新增裸字符串信号。
STOP_PIPELINE_SENTINEL = "__STOP_PIPELINE__"  # LLM 发出此 token 表示工具请求停止 Pipeline
LLM_ERROR_PREFIX = "LLM error"  # LLM 产出以此前缀开头的 token 表示流式生成出错

# LLM 供应商 402（余额不足/欠费）的友好播报：不念报错细节，只播这句
LLM_INSUFFICIENT_BALANCE_REPLY = "大模型欠费啦"

# 402 识别标记：优先看异常对象的 status_code，其次匹配各供应商错误文本的固定格式
_LLM_402_MARKERS = (
    "HTTP 402", "Error code: 402", "402 Payment Required",
    "Insufficient Balance", "insufficient balance", "余额不足", "欠费",
)


def llm_stream_error_token(exc_or_text) -> str:
    """LLM 网关/插件适配器把异常转为流内 token 的统一出口。

    - 402/余额不足/欠费 → 返回友好提示（无前缀），pipeline 按正常文本走 TTS 播报
    - 其他错误 → 返回带 LLM_ERROR_PREFIX 前缀的 token，pipeline 识别后静默终止
    与 LLM_ERROR_PREFIX / STOP_PIPELINE_SENTINEL 同属流内信号约定，两侧保持一致。
    """
    text = str(exc_or_text)
    status = getattr(exc_or_text, "status_code", None)
    if status == 402 or any(marker in text for marker in _LLM_402_MARKERS):
        return LLM_INSUFFICIENT_BALANCE_REPLY
    return f"{LLM_ERROR_PREFIX}: {text}"

# 记忆检索默认关键词（历史遗留：偏向特定用户场景），
# 可通过 ConversationPipeline(memory_search_keywords=[...]) 按用户配置覆盖
DEFAULT_MEMORY_SEARCH_KEYWORDS: list[str] = [
    "工作", "累", "职业", "上班", "外卖", "代码", "顾客", "编程",
    "猫", "宠物", "玩具", "天气", "下雨", "送餐", "跑外卖",
]
