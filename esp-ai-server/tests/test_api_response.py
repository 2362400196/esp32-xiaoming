"""统一 API 响应模型与速率限制器测试"""
from __future__ import annotations

import time

import pytest

from src.infrastructure.api_response import (
    ApiResponse,
    RateLimiter,
    error,
    get_rate_limiter,
    init_rate_limiter,
    success,
)


# ============================================================
# ApiResponse 模型
# ============================================================

class TestApiResponse:
    def test_default_values(self):
        r = ApiResponse()
        assert r.code == 0
        assert r.message == "ok"
        assert r.data is None

    def test_success_serialization_matches_dict(self):
        """序列化结果与现有路由字典结构一致"""
        r = ApiResponse(code=0, message="ok", data={"count": 3})
        dumped = r.model_dump()
        assert dumped == {"code": 0, "message": "ok", "data": {"count": 3}}

    def test_error_serialization(self):
        r = ApiResponse(code=1, message="not found", data=None)
        dumped = r.model_dump()
        assert dumped == {"code": 1, "message": "not found", "data": None}

    def test_data_can_be_list(self):
        r = ApiResponse(data=[1, 2, 3])
        assert r.data == [1, 2, 3]

    def test_data_can_be_string(self):
        r = ApiResponse(data="hello")
        assert r.data == "hello"

    def test_extra_forbid(self):
        with pytest.raises(Exception):
            ApiResponse(unknown_field="x")


# ============================================================
# success / error 工厂函数
# ============================================================

class TestFactoryFunctions:
    def test_success_default(self):
        assert success() == {"code": 0, "message": "ok", "data": None}

    def test_success_with_data(self):
        assert success(data=[1, 2]) == {"code": 0, "message": "ok", "data": [1, 2]}

    def test_success_with_message(self):
        assert success(message="done") == {"code": 0, "message": "done", "data": None}

    def test_error_default(self):
        assert error("fail") == {"code": 1, "message": "fail", "data": None}

    def test_error_with_code(self):
        assert error("not found", code=404) == {"code": 404, "message": "not found", "data": None}

    def test_error_with_data(self):
        assert error("fail", data={"hint": "x"}) == {"code": 1, "message": "fail", "data": {"hint": "x"}}


# ============================================================
# RateLimiter
# ============================================================

class TestRateLimiter:
    def test_disabled_when_zero(self):
        rl = RateLimiter(max_rpm=0)
        assert rl.enabled is False
        allowed, retry = rl.allow("1.2.3.4")
        assert allowed is True
        assert retry == 0.0

    def test_disabled_when_negative(self):
        rl = RateLimiter(max_rpm=-5)
        assert rl.enabled is False

    def test_enabled_when_positive(self):
        rl = RateLimiter(max_rpm=60)
        assert rl.enabled is True

    def test_allows_within_limit(self):
        rl = RateLimiter(max_rpm=10)
        for _ in range(10):
            allowed, _ = rl.allow("1.2.3.4")
            assert allowed is True

    def test_blocks_over_limit(self):
        rl = RateLimiter(max_rpm=3)
        for _ in range(3):
            assert rl.allow("1.2.3.4")[0] is True
        allowed, retry = rl.allow("1.2.3.4")
        assert allowed is False
        assert retry > 0

    def test_separate_ips_independent(self):
        rl = RateLimiter(max_rpm=2)
        assert rl.allow("1.1.1.1")[0] is True
        assert rl.allow("1.1.1.1")[0] is True
        assert rl.allow("1.1.1.1")[0] is False  # 1.1.1.1 exhausted
        assert rl.allow("2.2.2.2")[0] is True   # 2.2.2.2 still has tokens

    def test_retry_after_decreases_after_wait(self):
        rl = RateLimiter(max_rpm=60)  # 1 token/sec
        # 耗尽
        for _ in range(60):
            rl.allow("1.2.3.4")
        allowed1, retry1 = rl.allow("1.2.3.4")
        assert allowed1 is False
        assert retry1 > 0
        time.sleep(1.1)
        allowed2, retry2 = rl.allow("1.2.3.4")
        assert allowed2 is True
        assert retry2 == 0.0

    def test_gc_cleans_expired_buckets(self):
        rl = RateLimiter(max_rpm=60)
        rl._BUCKET_TTL = 0.01  # 立即过期
        rl._GC_INTERVAL = 0
        rl.allow("1.2.3.4")
        assert "1.2.3.4" in rl._buckets
        time.sleep(0.05)
        rl.allow("2.2.2.2")  # 触发 GC
        assert "1.2.3.4" not in rl._buckets

    def test_refill_does_not_exceed_capacity(self):
        rl = RateLimiter(max_rpm=5)
        # 消费 2 个
        rl.allow("1.1.1.1")
        rl.allow("1.1.1.1")
        time.sleep(0.1)
        rl.allow("1.1.1.1")
        # 桶容量不应超过 5
        bucket = rl._buckets["1.1.1.1"]
        assert bucket.tokens <= 5.0 + 0.001


# ============================================================
# 全局单例
# ============================================================

class TestGlobalSingleton:
    def test_init_returns_limiter(self):
        rl = init_rate_limiter(max_rpm=0)
        assert rl.enabled is False

    def test_get_returns_same_instance(self):
        init_rate_limiter(max_rpm=10)
        assert get_rate_limiter() is get_rate_limiter()

    def test_get_without_init_returns_disabled(self):
        # 重置单例
        import src.infrastructure.api_response as mod
        mod._rate_limiter = None
        rl = get_rate_limiter()
        assert rl.enabled is False

    def test_init_with_positive_enables(self):
        rl = init_rate_limiter(max_rpm=100)
        assert rl.enabled is True
        # 清理，避免影响其他测试
        init_rate_limiter(max_rpm=0)
