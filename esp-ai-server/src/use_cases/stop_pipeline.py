"""StopPipeline 异常

当 LLM 工具需要接管音频通道（如媒体播放器播放音乐）时抛出此异常，
终止当前 Pipeline 执行，由上层逻辑决定是否启动下一轮 ASR。
"""


class StopPipeline(Exception):
    """Pipeline 停止信号：工具已接管音频通道，无需继续执行 LLM 回复流程。"""
    pass