"""计费系统

- 单价配置：数据库单行 JSON（BillingConfigModel），管理员后台可改
- 用量统计：BillingAccumulator 按会话累计 ASR 时长(分钟) / LLM tokens / TTS 字数
- 费用计算：单价 × 用量（ASR 按小时、LLM 按千 tokens、TTS 按千字），单位元
- 峰谷计费：仅作用于 LLM（DeepSeek 官方峰谷价差），峰时段按原价、
  其余时间为谷时按折扣计费，支持多段峰时段（可跨零点），
  按会话关闭时刻判断峰谷，记录 llm_offpeak 审计标记
- 设备级记账：记录带 device_id，统计接口按设备汇总 + 总费用

ASR 按时长计费（火山引擎流式语音识别按小时计费），时长取自 ASR 响应
audio_info.duration（毫秒），记录与展示单位为分钟；LLM 按 API 返回 tokens；
TTS 按合成文本字数。
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select

from src.infrastructure.db.models import BillingConfigModel, BillingRecordModel
from src.infrastructure.db.session import get_session_ctx
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)

# 计费配置默认值（ASR 元/小时、LLM 元/百万tokens、TTS 元/千字）
BILLING_CONFIG_DEFAULTS = {
    "enabled": True,
    "asr_price_per_hour": 1.0,     # ASR 元/小时（火山流式语音识别约 1 元/小时）
    # DeepSeek V4 定价（元/百万 tokens，高峰价；谷时 = 高峰价 × offpeak_discount）
    "llm_input_price_per_mtokens": 3.0,               # 输入（缓存未命中）
    "llm_input_cache_hit_price_per_mtokens": 0.10,    # 输入（缓存命中）
    "llm_output_price_per_mtokens": 9.0,              # 输出
    "tts_price_per_kchars": 0.5,   # TTS 元/千字
    # 峰谷计费（仅 LLM）：峰时段按原价，谷时价格 = 高峰价 × offpeak_discount
    "peak_offpeak_enabled": True,   # 峰谷计费开关（默认开启）
    "offpeak_discount": 0.5,        # 谷时折扣（DeepSeek 高峰价约为谷时的 2 倍）
    "peak_windows": [["09:00", "12:00"], ["14:00", "18:00"]],  # 峰时段（HH:MM，支持跨零点）
}

BILLING_CONFIG_KEYS = set(BILLING_CONFIG_DEFAULTS)


async def get_billing_config() -> dict:
    """读取计费配置（合并默认值）"""
    try:
        async with get_session_ctx() as session:
            result = await session.execute(
                select(BillingConfigModel).where(BillingConfigModel.id == 1)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return dict(BILLING_CONFIG_DEFAULTS)
            stored = json.loads(row.config_json or "{}")
            merged = dict(BILLING_CONFIG_DEFAULTS)
            merged.update({k: v for k, v in stored.items() if k in BILLING_CONFIG_KEYS})
            return merged
    except Exception as e:
        logger.warning(f"[Billing] 读取计费配置失败: {e}")
        return dict(BILLING_CONFIG_DEFAULTS)


async def save_billing_config(data: dict) -> dict:
    """保存计费配置（白名单过滤 + 类型校验），返回合并后的完整配置"""
    async with get_session_ctx() as session:
        result = await session.execute(
            select(BillingConfigModel).where(BillingConfigModel.id == 1)
        )
        row = result.scalar_one_or_none()
        stored = json.loads(row.config_json) if row and row.config_json else {}
        for k, v in data.items():
            if k not in BILLING_CONFIG_KEYS:
                continue
            if k in ("enabled", "peak_offpeak_enabled"):
                stored[k] = bool(v)
            elif k == "peak_windows":
                cleaned = _clean_peak_windows(v)
                if cleaned:
                    stored[k] = cleaned
            else:
                try:
                    stored[k] = max(0.0, float(v))
                except (TypeError, ValueError):
                    continue
        if row is None:
            row = BillingConfigModel(id=1, config_json=json.dumps(stored, ensure_ascii=False))
            session.add(row)
        else:
            row.config_json = json.dumps(stored, ensure_ascii=False)
        merged = dict(BILLING_CONFIG_DEFAULTS)
        merged.update({k: v for k, v in stored.items() if k in BILLING_CONFIG_KEYS})
        return merged


def _is_valid_hhmm(value: str) -> bool:
    """校验 HH:MM 时间格式"""
    try:
        hh, mm = value.split(":")
        return 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59
    except (ValueError, AttributeError):
        return False


def _clean_peak_windows(value) -> list:
    """清洗峰时段列表：只保留合法的 [start, end] 时间对，返回空列表表示全部非法"""
    if not isinstance(value, list) or not value:
        return []
    cleaned = []
    for w in value:
        if (
            isinstance(w, (list, tuple))
            and len(w) == 2
            and isinstance(w[0], str)
            and isinstance(w[1], str)
            and _is_valid_hhmm(w[0])
            and _is_valid_hhmm(w[1])
        ):
            cleaned.append([w[0], w[1]])
    return cleaned


class BillingAccumulator:
    """按会话累计用量并计算费用

    生命周期与 Session 一致：每轮 ASR/LLM/TTS 结束后累加，
    Session.close() 时保存一条计费记录。
    """

    def __init__(self, device_id: str, session_id: str):
        self.device_id = device_id
        self.session_id = session_id
        self.asr_minutes = 0.0
        self.llm_input_tokens = 0
        self.llm_output_tokens = 0
        self.llm_cache_hit_tokens = 0
        self.tts_chars = 0

    def add_asr(self, minutes: float) -> None:
        """累加 ASR 音频时长（分钟），按火山引擎按时长计费口径"""
        self.asr_minutes += max(0.0, float(minutes))

    def add_llm(self, output_tokens: int, input_tokens: int = 0, cache_hit_tokens: int = 0) -> None:
        self.llm_output_tokens += max(0, int(output_tokens))
        self.llm_input_tokens += max(0, int(input_tokens))
        self.llm_cache_hit_tokens += max(0, int(cache_hit_tokens))

    def add_tts(self, chars: int) -> None:
        self.tts_chars += max(0, int(chars))

    def reset(self) -> None:
        """清零累计用量（每轮对话保存后调用，开始新一轮累计）"""
        self.asr_minutes = 0.0
        self.llm_input_tokens = 0
        self.llm_output_tokens = 0
        self.llm_cache_hit_tokens = 0
        self.tts_chars = 0

    async def save_record_and_reset(self, now: datetime | None = None) -> bool:
        """保存当前累计用量为一条记录，然后重置累计器。

        每轮对话结束调用：本轮用量独立成一条记录，避免设备常在线时
        多轮对话混在同一会话、迟迟不落库。
        """
        if self.asr_minutes <= 0 and self.llm_output_tokens <= 0 and self.llm_input_tokens <= 0 and self.tts_chars <= 0:
            self.reset()
            return False
        ok = await self.save_record(now)
        self.reset()
        return ok

    @staticmethod
    def _is_peak(config: dict, now: datetime | None = None) -> bool:
        """判断当前时刻是否处于任一峰时段（支持跨零点窗口）"""
        if not config.get("peak_offpeak_enabled", False):
            return False
        now = now or datetime.now()
        cur = now.hour * 60 + now.minute
        for w in config.get("peak_windows", []):
            try:
                sh, sm = map(int, str(w[0]).split(":"))
                eh, em = map(int, str(w[1]).split(":"))
            except (ValueError, AttributeError, IndexError):
                continue
            start = sh * 60 + sm
            end = eh * 60 + em
            if start <= end:
                if start <= cur < end:
                    return True
            else:
                # 跨零点：如 22:00-06:00
                if cur >= start or cur < end:
                    return True
        return False

    @staticmethod
    def _is_offpeak(config: dict, now: datetime | None = None) -> bool:
        """判断当前时刻是否为谷时（峰谷开启且不在任一峰时段内）"""
        if not config.get("peak_offpeak_enabled", False):
            return False
        return not BillingAccumulator._is_peak(config, now)

    def calculate(self, config: dict, now: datetime | None = None) -> dict:
        """按单价计算费用（元），保留 6 位小数

        LLM 按 DeepSeek V4 三档单价计费（元/百万 tokens）：
        - 输入（缓存未命中）：llm_input_price_per_mtokens
        - 输入（缓存命中）：llm_input_cache_hit_price_per_mtokens
        - 输出：llm_output_price_per_mtokens
        峰谷计费仅作用于 LLM：谷时价格 = 高峰价 × offpeak_discount。
        """
        offpeak = self._is_offpeak(config, now)
        llm_factor = float(config.get("offpeak_discount", 1.0)) if offpeak else 1.0
        # ASR 单价按小时，时长按分钟：分钟 / 60 = 小时数
        asr_cost = self.asr_minutes / 60.0 * float(config.get("asr_price_per_hour", 0))
        cache_miss = max(0, self.llm_input_tokens - self.llm_cache_hit_tokens)
        llm_input_cost = (
            cache_miss / 1_000_000.0 * float(config.get("llm_input_price_per_mtokens", 0))
            + self.llm_cache_hit_tokens / 1_000_000.0 * float(config.get("llm_input_cache_hit_price_per_mtokens", 0))
        ) * llm_factor
        llm_output_cost = (
            self.llm_output_tokens / 1_000_000.0 * float(config.get("llm_output_price_per_mtokens", 0))
        ) * llm_factor
        llm_cost = llm_input_cost + llm_output_cost
        tts_cost = self.tts_chars / 1000.0 * float(config.get("tts_price_per_kchars", 0))
        return {
            "asr_cost": round(asr_cost, 6),
            "llm_cost": round(llm_cost, 6),
            "tts_cost": round(tts_cost, 6),
            "total_cost": round(asr_cost + llm_cost + tts_cost, 6),
            "llm_offpeak": offpeak,
        }

    async def save_record(self, now: datetime | None = None) -> bool:
        """保存计费记录（异步，失败仅记日志不阻断会话）"""
        # 无任何用量（如会话关闭时累计器已被每轮保存重置）则跳过，避免产生全 0 噪音记录
        if self.asr_minutes <= 0 and self.llm_output_tokens <= 0 and self.llm_input_tokens <= 0 and self.tts_chars <= 0:
            return False
        try:
            config = await get_billing_config()
            if not config.get("enabled", True):
                return False
            costs = self.calculate(config, now)
            async with get_session_ctx() as session:
                record = BillingRecordModel(
                    device_id=self.device_id,
                    session_id=self.session_id,
                    asr_minutes=self.asr_minutes,
                    llm_input_tokens=self.llm_input_tokens,
                    llm_output_tokens=self.llm_output_tokens,
                    llm_cache_hit_tokens=self.llm_cache_hit_tokens,
                    tts_chars=self.tts_chars,
                    asr_cost=costs["asr_cost"],
                    llm_cost=costs["llm_cost"],
                    tts_cost=costs["tts_cost"],
                    total_cost=costs["total_cost"],
                    llm_offpeak=costs["llm_offpeak"],
                )
                session.add(record)
            logger.info(
                f"[Billing] 会话 {self.session_id} 计费: "
                f"ASR {self.asr_minutes:.1f}分钟/{costs['asr_cost']}元, "
                f"LLM 输入{self.llm_input_tokens}(缓存命中{self.llm_cache_hit_tokens})/"
                f"输出{self.llm_output_tokens}tokens/{costs['llm_cost']}元{'（谷时）' if costs['llm_offpeak'] else ''}, "
                f"TTS {self.tts_chars}字/{costs['tts_cost']}元, 合计 {costs['total_cost']}元"
            )
            return True
        except Exception as e:
            logger.warning(f"[Billing] 保存计费记录失败: {e}")
            return False


__all__ = [
    "BillingAccumulator",
    "BILLING_CONFIG_DEFAULTS",
    "BILLING_CONFIG_KEYS",
    "get_billing_config",
    "save_billing_config",
]
