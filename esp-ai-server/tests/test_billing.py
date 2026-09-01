"""计费系统单元测试

覆盖：
- ``BillingAccumulator``：用量累计（ASR 字数 / LLM tokens / TTS 字数）+ 费用计算
- ``get_billing_config`` / ``save_billing_config``：配置读写（白名单过滤 + 数值校验）
- ``save_record``：会话关闭时保存计费记录

使用内存 SQLite（sqlite+aiosqlite:///:memory: + StaticPool），
参考 ``tests/test_growth_emo_skill_repos.py`` 的夹具模式（monkeypatch 覆盖全局 session factory）。
"""
from __future__ import annotations

from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.infrastructure.db.base import Base
from src.infrastructure.db.models.billing import BillingConfigModel, BillingRecordModel
from src.use_cases.billing import (
    BILLING_CONFIG_DEFAULTS,
    BillingAccumulator,
    get_billing_config,
    save_billing_config,
)


# ============================================================
# 异步夹具（:memory: + StaticPool）
# ============================================================

@pytest_asyncio.fixture
async def async_engine():
    """内存 SQLite 异步引擎（StaticPool 确保 :memory: 单连接复用）"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(async_engine, monkeypatch):
    """覆盖全局 async session factory，让计费模块读写内存 DB"""
    async_factory = async_sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    import src.infrastructure.db.engine as engine_mod
    monkeypatch.setattr(engine_mod, "_async_engine", async_engine)
    monkeypatch.setattr(engine_mod, "_async_session_factory", async_factory)
    yield async_factory


# ============================================================
# BillingAccumulator 纯逻辑
# ============================================================

class TestBillingAccumulator:
    def test_add_asr_accumulates(self):
        acc = BillingAccumulator("dev1", "sess1")
        acc.add_asr(10)
        acc.add_asr(25)
        assert acc.asr_minutes == 35

    def test_add_asr_ignores_negative(self):
        acc = BillingAccumulator("dev1", "sess1")
        acc.add_asr(-5)
        assert acc.asr_minutes == 0

    def test_add_llm_accumulates(self):
        acc = BillingAccumulator("dev1", "sess1")
        acc.add_llm(output_tokens=100, input_tokens=50, cache_hit_tokens=20)
        acc.add_llm(output_tokens=200, input_tokens=30)
        assert acc.llm_output_tokens == 300
        assert acc.llm_input_tokens == 80
        assert acc.llm_cache_hit_tokens == 20

    def test_add_tts_accumulates(self):
        acc = BillingAccumulator("dev1", "sess1")
        acc.add_tts(30)
        acc.add_tts(70)
        assert acc.tts_chars == 100

    def test_calculate_default_prices(self):
        acc = BillingAccumulator("dev1", "sess1")
        acc.add_asr(60)            # 60 分钟 = 1 小时 → 1.0 元
        acc.add_llm(output_tokens=1_000_000)  # 100万输出 tokens → 9.0 元
        acc.add_tts(1000)          # 1000 字 → 0.5 元
        # 固定峰时（10:00）避免测试依赖实时峰谷判断
        costs = acc.calculate(BILLING_CONFIG_DEFAULTS, now=datetime(2026, 9, 1, 10, 0))
        assert costs["asr_cost"] == 1.0
        assert costs["llm_cost"] == 9.0
        assert costs["tts_cost"] == 0.5
        assert costs["total_cost"] == 10.5

    def test_calculate_llm_input_output_cache(self):
        acc = BillingAccumulator("dev1", "sess1")
        # 输入 100 万（其中 60 万缓存命中、40 万未命中）+ 输出 100 万
        acc.add_llm(output_tokens=1_000_000, input_tokens=1_000_000, cache_hit_tokens=600_000)
        costs = acc.calculate(BILLING_CONFIG_DEFAULTS, now=datetime(2026, 9, 1, 10, 0))
        # 输入未命中: 40万/100万 * 3.0 = 1.2；输入命中: 60万/100万 * 0.1 = 0.06；输出: 9.0
        assert costs["llm_cost"] == round(1.2 + 0.06 + 9.0, 6)

    def test_calculate_asr_by_duration(self):
        acc = BillingAccumulator("dev1", "sess1")
        acc.add_asr(30)   # 半小时
        acc.add_asr(15)   # 15 分钟
        config = dict(BILLING_CONFIG_DEFAULTS)
        config["asr_price_per_hour"] = 2.0
        costs = acc.calculate(config)
        # (30+15)/60 * 2.0 = 1.5 元
        assert costs["asr_cost"] == 1.5

    def test_calculate_custom_prices(self):
        acc = BillingAccumulator("dev1", "sess1")
        acc.add_asr(30)   # 半小时
        acc.add_tts(2000)
        config = {
            "asr_price_per_hour": 1.0,
            "llm_input_price_per_mtokens": 0.0,
            "llm_input_cache_hit_price_per_mtokens": 0.0,
            "llm_output_price_per_mtokens": 0.0,
            "tts_price_per_kchars": 0.25,
        }
        costs = acc.calculate(config)
        assert costs["asr_cost"] == 0.5
        assert costs["tts_cost"] == 0.5
        assert costs["total_cost"] == 1.0

    def test_calculate_zero_usage(self):
        acc = BillingAccumulator("dev1", "sess1")
        costs = acc.calculate(BILLING_CONFIG_DEFAULTS)
        assert costs["total_cost"] == 0.0

    def test_peak_offpeak_enabled_by_default(self):
        assert BILLING_CONFIG_DEFAULTS["peak_offpeak_enabled"] is True
        assert BILLING_CONFIG_DEFAULTS["peak_windows"] == [["09:00", "12:00"], ["14:00", "18:00"]]

    def test_offpeak_disabled_when_switch_off(self):
        acc = BillingAccumulator("dev1", "sess1")
        acc.add_llm(output_tokens=1000)
        config = dict(BILLING_CONFIG_DEFAULTS)
        config["peak_offpeak_enabled"] = False
        costs = acc.calculate(config, now=datetime(2026, 9, 1, 8, 0))
        assert costs["llm_cost"] == round(1000 / 1_000_000 * 9.0, 6)
        assert costs["llm_offpeak"] is False

    def test_peak_windows_full_price_offpeak_discount(self):
        acc = BillingAccumulator("dev1", "sess1")
        acc.add_llm(output_tokens=1000)
        config = dict(BILLING_CONFIG_DEFAULTS)  # 峰时段 09:00-12:00、14:00-18:00
        peak = round(1000 / 1_000_000 * 9.0, 6)      # 原价
        offpeak = round(peak * 0.5, 6)               # 谷时半价
        # 峰时段：原价
        assert acc.calculate(config, now=datetime(2026, 9, 1, 10, 0))["llm_cost"] == peak
        assert acc.calculate(config, now=datetime(2026, 9, 1, 15, 0))["llm_cost"] == peak
        # 谷时（峰时段外）：半价
        assert acc.calculate(config, now=datetime(2026, 9, 1, 8, 0))["llm_cost"] == offpeak
        assert acc.calculate(config, now=datetime(2026, 9, 1, 13, 0))["llm_cost"] == offpeak
        assert acc.calculate(config, now=datetime(2026, 9, 1, 19, 0))["llm_cost"] == offpeak

    def test_offpeak_discount_applied_to_llm_only(self):
        acc = BillingAccumulator("dev1", "sess1")
        acc.add_asr(60)   # 1 小时 → 1.0 元
        acc.add_llm(output_tokens=1000)
        acc.add_tts(1000)
        config = dict(BILLING_CONFIG_DEFAULTS)
        config["offpeak_discount"] = 0.5
        peak = round(1000 / 1_000_000 * 9.0, 6)
        # 谷时（峰时段外）：LLM 半价，ASR/TTS 不变
        costs = acc.calculate(config, now=datetime(2026, 9, 1, 8, 0))
        assert costs["llm_offpeak"] is True
        assert costs["llm_cost"] == round(peak * 0.5, 6)
        assert costs["asr_cost"] == 1.0
        assert costs["tts_cost"] == 0.5
        assert costs["total_cost"] == round(1.0 + peak * 0.5 + 0.5, 6)
        # 峰时：LLM 原价
        costs = acc.calculate(config, now=datetime(2026, 9, 1, 10, 0))
        assert costs["llm_offpeak"] is False
        assert costs["llm_cost"] == peak
        assert costs["total_cost"] == round(1.0 + peak + 0.5, 6)

    def test_offpeak_cross_midnight_peak_window(self):
        acc = BillingAccumulator("dev1", "sess1")
        acc.add_llm(output_tokens=1000)
        config = dict(BILLING_CONFIG_DEFAULTS)
        config["peak_windows"] = [["22:00", "06:00"]]  # 跨零点峰时段
        # 峰时段：22:00-06:00
        assert acc.calculate(config, now=datetime(2026, 9, 1, 23, 30))["llm_offpeak"] is False
        assert acc.calculate(config, now=datetime(2026, 9, 1, 2, 0))["llm_offpeak"] is False
        # 谷时：峰时段外
        assert acc.calculate(config, now=datetime(2026, 9, 1, 12, 0))["llm_offpeak"] is True

    def test_offpeak_boundary(self):
        acc = BillingAccumulator("dev1", "sess1")
        acc.add_llm(output_tokens=1000)
        config = dict(BILLING_CONFIG_DEFAULTS)
        config["peak_windows"] = [["09:00", "12:00"]]
        # 峰时段含头不含尾：09:00 起为峰，12:00 起为谷
        assert acc.calculate(config, now=datetime(2026, 9, 1, 9, 0))["llm_offpeak"] is False
        assert acc.calculate(config, now=datetime(2026, 9, 1, 11, 59))["llm_offpeak"] is False
        assert acc.calculate(config, now=datetime(2026, 9, 1, 12, 0))["llm_offpeak"] is True
        assert acc.calculate(config, now=datetime(2026, 9, 1, 8, 59))["llm_offpeak"] is True


# ============================================================
# 配置读写
# ============================================================

class TestBillingConfig:
    @pytest.mark.asyncio
    async def test_get_defaults_when_no_row(self, db):
        config = await get_billing_config()
        assert config == BILLING_CONFIG_DEFAULTS

    @pytest.mark.asyncio
    async def test_save_and_get_roundtrip(self, db):
        saved = await save_billing_config({"asr_price_per_hour": 1.5, "enabled": False})
        assert saved["asr_price_per_hour"] == 1.5
        assert saved["enabled"] is False
        config = await get_billing_config()
        assert config["asr_price_per_hour"] == 1.5
        assert config["enabled"] is False
        # 未修改的字段保持默认
        assert config["llm_output_price_per_mtokens"] == BILLING_CONFIG_DEFAULTS["llm_output_price_per_mtokens"]

    @pytest.mark.asyncio
    async def test_llm_price_fields_roundtrip(self, db):
        saved = await save_billing_config({
            "llm_input_price_per_mtokens": 3.0,
            "llm_input_cache_hit_price_per_mtokens": 0.1,
            "llm_output_price_per_mtokens": 9.0,
        })
        assert saved["llm_input_price_per_mtokens"] == 3.0
        assert saved["llm_input_cache_hit_price_per_mtokens"] == 0.1
        assert saved["llm_output_price_per_mtokens"] == 9.0

    @pytest.mark.asyncio
    async def test_whitelist_rejects_unknown_keys(self, db):
        saved = await save_billing_config({"hacker_key": 999, "asr_price_per_hour": 0.3})
        assert "hacker_key" not in saved
        assert saved["asr_price_per_hour"] == 0.3

    @pytest.mark.asyncio
    async def test_invalid_number_ignored(self, db):
        saved = await save_billing_config({"asr_price_per_hour": "not-a-number"})
        assert saved["asr_price_per_hour"] == BILLING_CONFIG_DEFAULTS["asr_price_per_hour"]

    @pytest.mark.asyncio
    async def test_negative_price_clamped_to_zero(self, db):
        saved = await save_billing_config({"asr_price_per_hour": -1})
        assert saved["asr_price_per_hour"] == 0.0

    @pytest.mark.asyncio
    async def test_peak_offpeak_fields_roundtrip(self, db):
        saved = await save_billing_config({
            "peak_offpeak_enabled": True,
            "offpeak_discount": 0.4,
            "peak_windows": [["09:00", "12:00"], ["14:00", "18:00"]],
        })
        assert saved["peak_offpeak_enabled"] is True
        assert saved["offpeak_discount"] == 0.4
        assert saved["peak_windows"] == [["09:00", "12:00"], ["14:00", "18:00"]]
        config = await get_billing_config()
        assert config["peak_offpeak_enabled"] is True
        assert config["offpeak_discount"] == 0.4

    @pytest.mark.asyncio
    async def test_invalid_peak_windows_ignored(self, db):
        saved = await save_billing_config({
            "peak_windows": [["25:99", "abc"], "bad", [1, 2]],
        })
        assert saved["peak_windows"] == BILLING_CONFIG_DEFAULTS["peak_windows"]

    @pytest.mark.asyncio
    async def test_partial_valid_peak_windows_kept(self, db):
        saved = await save_billing_config({
            "peak_windows": [["09:00", "12:00"], ["bad", "x"], ["20:00", "22:00"]],
        })
        assert saved["peak_windows"] == [["09:00", "12:00"], ["20:00", "22:00"]]


# ============================================================
# 记录保存
# ============================================================

class TestSaveRecord:
    @pytest.mark.asyncio
    async def test_save_record_creates_row(self, db):
        acc = BillingAccumulator("dev1", "sess1")
        acc.add_asr(60)   # 1 小时
        acc.add_llm(output_tokens=500, input_tokens=300, cache_hit_tokens=100)
        acc.add_tts(200)
        ok = await acc.save_record(now=datetime(2026, 9, 1, 10, 0))
        assert ok is True

        async with db() as session:
            rows = (await session.execute(select(BillingRecordModel))).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.device_id == "dev1"
        assert row.session_id == "sess1"
        assert row.asr_minutes == 60
        assert row.llm_output_tokens == 500
        assert row.llm_input_tokens == 300
        assert row.llm_cache_hit_tokens == 100
        assert row.tts_chars == 200
        assert row.asr_cost == 1.0
        # LLM: 输出 500/100万*9 + 输入未命中 200/100万*3 + 命中 100/100万*0.1
        llm_cost = round(500 / 1_000_000 * 9.0 + 200 / 1_000_000 * 3.0 + 100 / 1_000_000 * 0.1, 6)
        assert row.llm_cost == llm_cost
        assert row.total_cost == round(1.0 + llm_cost + 0.1, 6)
        assert row.llm_offpeak is False

    @pytest.mark.asyncio
    async def test_save_record_stores_offpeak_flag(self, db):
        await save_billing_config({
            "peak_offpeak_enabled": True,
            "offpeak_discount": 0.5,
            "peak_windows": [["00:00", "00:00"]],  # 零长度峰时段 → 始终谷时
        })
        acc = BillingAccumulator("dev1", "sess1")
        acc.add_llm(output_tokens=1000)
        ok = await acc.save_record()
        assert ok is True

        async with db() as session:
            rows = (await session.execute(select(BillingRecordModel))).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.llm_offpeak is True
        assert row.llm_cost == round(1000 / 1_000_000 * 9.0 * 0.5, 6)

    @pytest.mark.asyncio
    async def test_save_record_skipped_when_disabled(self, db):
        await save_billing_config({"enabled": False})
        acc = BillingAccumulator("dev1", "sess1")
        acc.add_asr(100)
        ok = await acc.save_record()
        assert ok is False

        async with db() as session:
            rows = (await session.execute(select(BillingRecordModel))).scalars().all()
        assert len(rows) == 0


# ============================================================
# 每日费用汇总（/billing/daily）
# ============================================================

class TestDailyCost:
    @pytest.mark.asyncio
    async def test_daily_groups_by_local_date(self, db):
        from datetime import datetime, timedelta
        from src.infrastructure.routes.admin import admin_billing_daily

        now = datetime.now()
        today = now.replace(hour=12, minute=0, second=0, microsecond=0)
        yesterday = today - timedelta(days=1)
        async with db() as session:
            session.add_all([
                BillingRecordModel(device_id="dev1", session_id="s1", total_cost=1.0, created_at=today.timestamp()),
                BillingRecordModel(device_id="dev1", session_id="s2", total_cost=2.0, created_at=today.timestamp()),
                BillingRecordModel(device_id="dev1", session_id="s3", total_cost=0.5, created_at=yesterday.timestamp()),
            ])
            await session.commit()

        res = await admin_billing_daily(days=7, _=None)
        daily = res["data"]["daily"]
        assert len(daily) == 7
        assert daily[-1]["date"] == today.strftime("%Y-%m-%d")
        assert daily[-1]["total_cost"] == 3.0
        assert daily[-2]["date"] == yesterday.strftime("%Y-%m-%d")
        assert daily[-2]["total_cost"] == 0.5
        assert all(d["total_cost"] == 0.0 for d in daily[:-2])

    @pytest.mark.asyncio
    async def test_daily_empty_returns_zeros(self, db):
        from src.infrastructure.routes.admin import admin_billing_daily
        res = await admin_billing_daily(days=7, _=None)
        daily = res["data"]["daily"]
        assert len(daily) == 7
        assert all(d["total_cost"] == 0.0 for d in daily)
