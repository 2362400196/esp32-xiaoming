"""WS 会话处理器的共享小工具。"""
from __future__ import annotations

import time

from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


def _get_wake_enable_audio(settings, user_config=None) -> bool:
    """读取设备级 enable_audio，回退全局"""
    default = settings.wakeup.enable_audio
    if user_config and hasattr(user_config, 'wakeup_config') and user_config.wakeup_config:
        val = user_config.wakeup_config.get('enable_audio')
        if val is not None:
            return val
    return default


def _log_perf_report(session, result, pipeline, asr_text: str) -> None:
    """打印一轮对话的性能分析报告到终端（调试用）"""
    try:
        now = time.time()
        rt = session.runtime

        asr_ms = None
        if rt.asr_start_time and rt.asr_last_result_time:
            asr_ms = (rt.asr_last_result_time - rt.asr_start_time) * 1000

        perf = getattr(pipeline, "_perf", {}) if pipeline else {}

        # 首响延迟 = ASR 识别完成 → 第一段回复音频发送到设备（真正的响应性能）
        resp_ms = None
        first_audio_sent = perf.get("first_audio_sent")
        if first_audio_sent and rt.asr_last_result_time:
            resp_ms = (first_audio_sent - rt.asr_last_result_time) * 1000

        llm_ms = llm_ttft_ms = None
        if perf.get("llm_start") and perf.get("llm_end"):
            llm_ms = (perf["llm_end"] - perf["llm_start"]) * 1000
            if perf.get("llm_first_token"):
                llm_ttft_ms = (perf["llm_first_token"] - perf["llm_start"]) * 1000

        tts_ms = None
        if perf.get("tts_start") and perf.get("tts_end"):
            tts_ms = (perf["tts_end"] - perf["tts_start"]) * 1000

        pipeline_ms = (result.duration * 1000) if result else None
        audio_ms = (result.total_duration_ms) if result else 0
        full_text = (result.full_text or "") if result else ""

        e2e_ms = None
        if rt.asr_start_time:
            e2e_ms = (now - rt.asr_start_time) * 1000

        def _fmt(ms):
            return f"{ms:.0f}ms" if ms is not None else "n/a"

        lines = [
            "═" * 64,
            f"[Perf] 对话性能报告  session={session.session_id}  device={session.device_id[:16]}"
            + ("  ⚠️ 本轮被中断（无完整 result，部分指标缺失）" if result is None else ""),
            f"  用户输入 : \"{asr_text[:40]}\"",
        ]
        if asr_ms is not None:
            lines.append(f"  ASR 识别 : {_fmt(asr_ms)}")
        lines.append(
            f"  LLM 生成 : {_fmt(llm_ms)}   (首token {_fmt(llm_ttft_ms)}, "
            f"输出 {perf.get('llm_chars', 0)}字/{perf.get('llm_sentences', 0)}句)"
        )
        lines.append(
            f"  TTS 合成 : {_fmt(tts_ms)}   ({perf.get('tts_chunks', 0)}块, 共{audio_ms:.0f}ms音频)"
        )
        if resp_ms is not None:
            lines.append(f"  首响延迟 : {_fmt(resp_ms)}   (ASR完成→首帧音频)")
        if perf.get("prompt_assembly_ms") is not None:
            lines.append(
                f"  Prompt组装: {_fmt(perf.get('prompt_assembly_ms'))}  "
                f"(system {perf.get('prompt_chars', 0)}字/含历史 {perf.get('history_chars', 0)}字)"
            )
        lines.append(f"  Pipeline : {_fmt(pipeline_ms)}   (总耗时)")
        if e2e_ms is not None:
            lines.append(f"  端到端   : {_fmt(e2e_ms)}   (ASR开始→播放完成)")
        lines.append(f"  回复     : \"{full_text[:60]}\"")
        lines.append("═" * 64)
        logger.info("\n" + "\n".join(lines))
    except Exception as e:
        logger.debug(f"[Perf] 报告生成失败: {e}")
