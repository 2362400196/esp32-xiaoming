"""
通用熔断器（src/infrastructure/circuit_breaker.py）单元测试

覆盖范围：
- CircuitState 枚举值
- CircuitBreakerOpenError 异常类型
- CircuitBreaker 构造与默认值
- 状态转换：CLOSED -> OPEN -> HALF_OPEN -> CLOSED/OPEN
- 失败计数与阈值
- 恢复超时（recovery_timeout）
- call() 方法：成功/失败/OPEN 拒绝/参数透传/expected_exception 过滤
- record_success / record_failure 显式记录（用于流式 API）
- reset() 重置
"""
import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
)


# ============================================================
# CircuitState 枚举
# ============================================================


class TestCircuitState:
    """CircuitState 枚举值测试"""

    def test_enum_has_three_states(self):
        assert CircuitState.CLOSED
        assert CircuitState.OPEN
        assert CircuitState.HALF_OPEN

    def test_enum_values(self):
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"

    def test_enum_distinct(self):
        states = {CircuitState.CLOSED, CircuitState.OPEN, CircuitState.HALF_OPEN}
        assert len(states) == 3


# ============================================================
# CircuitBreakerOpenError
# ============================================================


class TestCircuitBreakerOpenError:
    """CircuitBreakerOpenError 异常类型测试"""

    def test_is_exception_subclass(self):
        assert issubclass(CircuitBreakerOpenError, Exception)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(CircuitBreakerOpenError):
            raise CircuitBreakerOpenError("test")

    def test_caught_as_exception(self):
        # 应该也能被通用 Exception 捕获
        with pytest.raises(Exception):
            raise CircuitBreakerOpenError("test")

    def test_message_preserved(self):
        try:
            raise CircuitBreakerOpenError("breaker is open")
        except CircuitBreakerOpenError as e:
            assert "breaker is open" in str(e)


# ============================================================
# CircuitBreaker 构造与初始状态
# ============================================================


class TestCircuitBreakerInit:
    """CircuitBreaker 构造与初始状态测试"""

    def test_default_values(self):
        cb = CircuitBreaker()
        assert cb.name == ""
        assert cb.failure_threshold == 5
        assert cb.recovery_timeout == 60.0
        assert cb.expected_exception is Exception
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_custom_values(self):
        cb = CircuitBreaker(
            name="test_breaker",
            failure_threshold=10,
            recovery_timeout=30.0,
            expected_exception=ValueError,
        )
        assert cb.name == "test_breaker"
        assert cb.failure_threshold == 10
        assert cb.recovery_timeout == 30.0
        assert cb.expected_exception is ValueError

    def test_expected_exception_as_tuple(self):
        cb = CircuitBreaker(expected_exception=(ValueError, TypeError))
        assert cb.expected_exception == (ValueError, TypeError)

    def test_initial_state_closed(self):
        cb = CircuitBreaker(name="test")
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_int_recovery_timeout_accepted(self):
        # 用户配置中 recovery_timeout=60 是 int，应能正常工作
        cb = CircuitBreaker(recovery_timeout=60)
        assert cb.recovery_timeout == 60


# ============================================================
# 状态转换：CLOSED -> OPEN
# ============================================================


class TestClosedToOpenTransition:
    """CLOSED -> OPEN 状态转换测试"""

    async def test_single_failure_does_not_open(self):
        cb = CircuitBreaker(name="t", failure_threshold=3)
        with pytest.raises(RuntimeError):
            await cb.call(self._failing_func())
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 1

    async def test_failures_below_threshold_stays_closed(self):
        cb = CircuitBreaker(name="t", failure_threshold=5)

        for _ in range(4):
            with pytest.raises(RuntimeError):
                await cb.call(self._failing_func())
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 4

    async def test_failures_reach_threshold_opens(self):
        cb = CircuitBreaker(name="t", failure_threshold=3)

        for _ in range(3):
            with pytest.raises(RuntimeError):
                await cb.call(self._failing_func())
        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 3

    async def test_failures_exceed_threshold_still_open(self):
        cb = CircuitBreaker(name="t", failure_threshold=2)

        # 前 2 次失败使熔断器开启
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(self._failing_func())
        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 2

        # 后续调用应被熔断器拒绝（不再触达下游，抛出 CircuitBreakerOpenError）
        for _ in range(3):
            with pytest.raises(CircuitBreakerOpenError):
                await cb.call(self._failing_func())
        # failure_count 不应再增加（call 在 OPEN 状态下直接抛出，不调用 _on_failure）
        assert cb.failure_count == 2
        assert cb.state == CircuitState.OPEN

    async def test_threshold_one_opens_on_first_failure(self):
        cb = CircuitBreaker(name="t", failure_threshold=1)
        with pytest.raises(RuntimeError):
            await cb.call(self._failing_func())
        assert cb.state == CircuitState.OPEN

    def _failing_func(self):
        async def _fail():
            raise RuntimeError("boom")
        return _fail


# ============================================================
# OPEN 状态行为与拒绝调用
# ============================================================


class TestOpenStateBehavior:
    """OPEN 状态行为测试"""

    async def test_open_rejects_call_with_error(self):
        cb = CircuitBreaker(name="t", failure_threshold=1)
        with pytest.raises(RuntimeError):
            await cb.call(self._failing_func())
        assert cb.state == CircuitState.OPEN

        async def ok():
            return "ok"

        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(ok)

    async def test_open_error_message_contains_name(self):
        cb = CircuitBreaker(name="my_service", failure_threshold=1)
        with pytest.raises(RuntimeError):
            await cb.call(self._failing_func())

        try:
            await cb.call(self._ok_func())
        except CircuitBreakerOpenError as e:
            assert "my_service" in str(e)

    async def test_open_does_not_call_func(self):
        cb = CircuitBreaker(name="t", failure_threshold=1)
        with pytest.raises(RuntimeError):
            await cb.call(self._failing_func())

        call_count = {"n": 0}

        async def tracked():
            call_count["n"] += 1
            return "called"

        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(tracked)
        # 函数不应被执行
        assert call_count["n"] == 0

    def _failing_func(self):
        async def _fail():
            raise RuntimeError("boom")
        return _fail

    def _ok_func(self):
        async def _ok():
            return "ok"
        return _ok


# ============================================================
# 恢复超时：OPEN -> HALF_OPEN
# ============================================================


class TestRecoveryTimeout:
    """OPEN -> HALF_OPEN 恢复超时测试"""

    async def test_open_stays_open_before_timeout(self):
        cb = CircuitBreaker(name="t", failure_threshold=1, recovery_timeout=0.5)
        with pytest.raises(RuntimeError):
            await cb.call(self._failing_func())
        assert cb.state == CircuitState.OPEN

        # 等待 0.2s（未到 recovery_timeout）
        await asyncio.sleep(0.2)
        assert cb.state == CircuitState.OPEN

    async def test_open_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker(name="t", failure_threshold=1, recovery_timeout=0.3)
        with pytest.raises(RuntimeError):
            await cb.call(self._failing_func())
        assert cb.state == CircuitState.OPEN

        # 等待超过 recovery_timeout
        await asyncio.sleep(0.4)
        # 访问 state 属性会触发 OPEN -> HALF_OPEN 转换
        assert cb.state == CircuitState.HALF_OPEN

    async def test_half_open_allows_call(self):
        cb = CircuitBreaker(name="t", failure_threshold=1, recovery_timeout=0.3)
        with pytest.raises(RuntimeError):
            await cb.call(self._failing_func())
        await asyncio.sleep(0.4)

        # HALF_OPEN 状态下应允许调用
        result = await cb.call(self._ok_func())
        assert result == "ok"

    async def test_state_property_idempotent_in_half_open(self):
        cb = CircuitBreaker(name="t", failure_threshold=1, recovery_timeout=0.3)
        with pytest.raises(RuntimeError):
            await cb.call(self._failing_func())
        await asyncio.sleep(0.4)

        # 多次访问 state 不应再次触发转换
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.state == CircuitState.HALF_OPEN

    def _failing_func(self):
        async def _fail():
            raise RuntimeError("boom")
        return _fail

    def _ok_func(self):
        async def _ok():
            return "ok"
        return _ok


# ============================================================
# HALF_OPEN 状态转换
# ============================================================


class TestHalfOpenTransition:
    """HALF_OPEN -> CLOSED/OPEN 转换测试"""

    async def test_half_open_success_transitions_to_closed(self):
        cb = CircuitBreaker(name="t", failure_threshold=1, recovery_timeout=0.3)
        with pytest.raises(RuntimeError):
            await cb.call(self._failing_func())
        await asyncio.sleep(0.4)
        assert cb.state == CircuitState.HALF_OPEN

        # 成功调用 -> CLOSED
        result = await cb.call(self._ok_func())
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    async def test_half_open_failure_transitions_to_open(self):
        cb = CircuitBreaker(name="t", failure_threshold=1, recovery_timeout=0.3)
        with pytest.raises(RuntimeError):
            await cb.call(self._failing_func())
        await asyncio.sleep(0.4)
        assert cb.state == CircuitState.HALF_OPEN

        # 失败调用 -> OPEN
        with pytest.raises(RuntimeError):
            await cb.call(self._failing_func())
        assert cb.state == CircuitState.OPEN

    async def test_half_open_success_resets_failure_count(self):
        cb = CircuitBreaker(name="t", failure_threshold=2, recovery_timeout=0.3)
        # 累积 2 次失败使熔断器开启
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(self._failing_func())
        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 2

        await asyncio.sleep(0.4)
        assert cb.state == CircuitState.HALF_OPEN

        # 成功后 failure_count 应重置为 0
        await cb.call(self._ok_func())
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED

    async def test_full_recovery_cycle(self):
        """完整恢复周期：CLOSED -> OPEN -> HALF_OPEN -> CLOSED"""
        cb = CircuitBreaker(name="t", failure_threshold=2, recovery_timeout=0.3)

        # 1. 初始 CLOSED
        assert cb.state == CircuitState.CLOSED

        # 2. 失败 2 次 -> OPEN
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(self._failing_func())
        assert cb.state == CircuitState.OPEN

        # 3. 等待恢复 -> HALF_OPEN
        await asyncio.sleep(0.4)
        assert cb.state == CircuitState.HALF_OPEN

        # 4. 成功 -> CLOSED
        result = await cb.call(self._ok_func())
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    def _failing_func(self):
        async def _fail():
            raise RuntimeError("boom")
        return _fail

    def _ok_func(self):
        async def _ok():
            return "ok"
        return _ok


# ============================================================
# call() 方法行为
# ============================================================


class TestCallMethod:
    """call() 方法行为测试"""

    async def test_call_returns_result_on_success(self):
        cb = CircuitBreaker(name="t")

        async def func():
            return "result"

        result = await cb.call(func)
        assert result == "result"

    async def test_call_passes_args(self):
        cb = CircuitBreaker(name="t")

        async def func(a, b):
            return a + b

        result = await cb.call(func, 1, 2)
        assert result == 3

    async def test_call_passes_kwargs(self):
        cb = CircuitBreaker(name="t")

        async def func(*, x, y):
            return x * y

        result = await cb.call(func, x=3, y=4)
        assert result == 12

    async def test_call_passes_args_and_kwargs(self):
        cb = CircuitBreaker(name="t")

        async def func(a, b, *, c, d):
            return (a + b, c + d)

        result = await cb.call(func, 1, 2, c=3, d=4)
        assert result == (3, 7)

    async def test_call_reraises_exception(self):
        cb = CircuitBreaker(name="t")

        async def func():
            raise ValueError("bad")

        with pytest.raises(ValueError, match="bad"):
            await cb.call(func)

    async def test_call_records_success(self):
        cb = CircuitBreaker(name="t", failure_threshold=2)

        # 先累积一次失败
        with pytest.raises(RuntimeError):
            await cb.call(self._failing_func())
        assert cb.failure_count == 1

        # 成功调用应重置 failure_count
        await cb.call(self._ok_func())
        assert cb.failure_count == 0

    async def test_call_records_failure(self):
        cb = CircuitBreaker(name="t", failure_threshold=5)
        for i in range(3):
            with pytest.raises(RuntimeError):
                await cb.call(self._failing_func())
        assert cb.failure_count == 3

    async def test_expected_exception_filters_other_exceptions(self):
        # 只把 ValueError 视为失败；TypeError 不应被记录
        cb = CircuitBreaker(
            name="t",
            failure_threshold=1,
            expected_exception=ValueError,
        )

        async def raise_type_error():
            raise TypeError("not expected")

        # TypeError 不在 expected_exception 内，会直接抛出（不被 call 捕获）
        with pytest.raises(TypeError):
            await cb.call(raise_type_error)
        # 未被记录为失败
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED

    async def test_expected_exception_tuple(self):
        cb = CircuitBreaker(
            name="t",
            failure_threshold=1,
            expected_exception=(ValueError, KeyError),
        )

        async def raise_key_error():
            raise KeyError("key")

        with pytest.raises(KeyError):
            await cb.call(raise_key_error)
        assert cb.failure_count == 1

    async def test_call_with_mock_async_function(self):
        cb = CircuitBreaker(name="t")
        mock_func = AsyncMock(return_value="mocked")
        result = await cb.call(mock_func, "arg", kw="kwarg")
        assert result == "mocked"
        mock_func.assert_awaited_once_with("arg", kw="kwarg")

    def _failing_func(self):
        async def _fail():
            raise RuntimeError("boom")
        return _fail

    def _ok_func(self):
        async def _ok():
            return "ok"
        return _ok


# ============================================================
# record_success / record_failure 显式记录
# ============================================================


class TestExplicitRecording:
    """record_success / record_failure 显式记录测试（用于流式 API 场景）"""

    async def test_record_failure_increments_count(self):
        cb = CircuitBreaker(name="t", failure_threshold=3)
        cb.record_failure()
        assert cb.failure_count == 1
        assert cb.state == CircuitState.CLOSED

        cb.record_failure()
        assert cb.failure_count == 2
        assert cb.state == CircuitState.CLOSED

        cb.record_failure()
        assert cb.failure_count == 3
        assert cb.state == CircuitState.OPEN

    async def test_record_success_resets_count(self):
        cb = CircuitBreaker(name="t", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 2

        cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED

    async def test_record_success_in_half_open_transitions_to_closed(self):
        cb = CircuitBreaker(name="t", failure_threshold=1, recovery_timeout=0.3)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        await asyncio.sleep(0.4)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    async def test_record_failure_in_half_open_transitions_to_open(self):
        cb = CircuitBreaker(name="t", failure_threshold=1, recovery_timeout=0.3)
        cb.record_failure()
        await asyncio.sleep(0.4)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    async def test_explicit_recording_equivalent_to_call(self):
        # 显式记录与 call() 内部记录效果一致
        cb1 = CircuitBreaker(name="t1", failure_threshold=2)
        cb1.record_failure()
        cb1.record_failure()

        cb2 = CircuitBreaker(name="t2", failure_threshold=2)

        async def fail():
            raise RuntimeError()

        with pytest.raises(RuntimeError):
            await cb2.call(fail)
        with pytest.raises(RuntimeError):
            await cb2.call(fail)

        assert cb1.state == cb2.state
        assert cb1.failure_count == cb2.failure_count


# ============================================================
# reset() 方法
# ============================================================


class TestReset:
    """reset() 方法测试"""

    async def test_reset_from_open(self):
        cb = CircuitBreaker(name="t", failure_threshold=1)
        with pytest.raises(RuntimeError):
            await cb.call(self._failing_func())
        assert cb.state == CircuitState.OPEN

        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    async def test_reset_from_half_open(self):
        cb = CircuitBreaker(name="t", failure_threshold=1, recovery_timeout=0.3)
        with pytest.raises(RuntimeError):
            await cb.call(self._failing_func())
        await asyncio.sleep(0.4)
        assert cb.state == CircuitState.HALF_OPEN

        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    async def test_reset_from_closed(self):
        cb = CircuitBreaker(name="t", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 2

        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    async def test_reset_allows_calls_after_open(self):
        cb = CircuitBreaker(name="t", failure_threshold=1)
        with pytest.raises(RuntimeError):
            await cb.call(self._failing_func())
        assert cb.state == CircuitState.OPEN

        # 重置前应拒绝调用
        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(self._ok_func())

        cb.reset()

        # 重置后应允许调用
        result = await cb.call(self._ok_func())
        assert result == "ok"

    def _failing_func(self):
        async def _fail():
            raise RuntimeError("boom")
        return _fail

    def _ok_func(self):
        async def _ok():
            return "ok"
        return _ok


# ============================================================
# failure_count 属性
# ============================================================


class TestFailureCount:
    """failure_count 属性测试"""

    async def test_initial_failure_count_zero(self):
        cb = CircuitBreaker(name="t")
        assert cb.failure_count == 0

    async def test_failure_count_increments(self):
        cb = CircuitBreaker(name="t", failure_threshold=10)
        for i in range(1, 4):
            with pytest.raises(RuntimeError):
                await cb.call(self._failing_func())
            assert cb.failure_count == i

    async def test_failure_count_resets_on_success(self):
        cb = CircuitBreaker(name="t", failure_threshold=10)
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await cb.call(self._failing_func())
        assert cb.failure_count == 3

        await cb.call(self._ok_func())
        assert cb.failure_count == 0

    async def test_failure_count_resets_on_reset(self):
        cb = CircuitBreaker(name="t", failure_threshold=10)
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await cb.call(self._failing_func())
        cb.reset()
        assert cb.failure_count == 0

    def _failing_func(self):
        async def _fail():
            raise RuntimeError("boom")
        return _fail

    def _ok_func(self):
        async def _ok():
            return "ok"
        return _ok


# ============================================================
# 集成场景：模拟 TTS/ASR 网关的失败恢复
# ============================================================


class TestGatewaySimulation:
    """模拟 TTS/ASR 网关使用熔断器的集成场景"""

    async def test_tts_like_simulation_open_returns_empty(self):
        """模拟 TTS 网关：熔断器 OPEN 时返回空音频"""
        cb = CircuitBreaker(name="tts_sim", failure_threshold=3, recovery_timeout=0.3)

        async def tts_call():
            raise ConnectionError("TTS service down")

        # 累积 3 次失败使熔断器开启
        for _ in range(3):
            with pytest.raises(ConnectionError):
                await cb.call(tts_call)
        assert cb.state == CircuitState.OPEN

        # 模拟 TTS 网关在 OPEN 时返回空音频
        async def synthesize(text):
            if cb.state == CircuitState.OPEN:
                return b""
            try:
                return await cb.call(tts_call)
            except Exception:
                return b""

        result = await synthesize("hello")
        assert result == b""

    async def test_asr_like_simulation_open_returns_empty(self):
        """模拟 ASR 网关：熔断器 OPEN 时返回空文本"""
        cb = CircuitBreaker(name="asr_sim", failure_threshold=2, recovery_timeout=0.3)

        async def asr_call():
            raise OSError("ASR connection failed")

        # 累积 2 次失败使熔断器开启
        for _ in range(2):
            with pytest.raises(OSError):
                await cb.call(asr_call)
        assert cb.state == CircuitState.OPEN

        # 模拟 ASR 网关在 OPEN 时返回空文本
        async def recognize(audio):
            try:
                return await cb.call(asr_call)
            except CircuitBreakerOpenError:
                return ""
            except Exception:
                return ""

        result = await recognize(b"audio")
        assert result == ""

    async def test_tts_recovery_after_timeout(self):
        """模拟 TTS 网关：恢复超时后可正常调用"""
        cb = CircuitBreaker(name="tts_rec", failure_threshold=2, recovery_timeout=0.3)

        async def failing_tts():
            raise ConnectionError("down")

        async def ok_tts():
            return b"audio_bytes"

        # 失败 2 次 -> OPEN
        for _ in range(2):
            with pytest.raises(ConnectionError):
                await cb.call(failing_tts)
        assert cb.state == CircuitState.OPEN

        # 等待恢复
        await asyncio.sleep(0.4)
        assert cb.state == CircuitState.HALF_OPEN

        # 试探调用成功 -> CLOSED
        result = await cb.call(ok_tts)
        assert result == b"audio_bytes"
        assert cb.state == CircuitState.CLOSED

    async def test_consecutive_failures_dont_call_downstream(self):
        """熔断器 OPEN 后不应再调用下游服务（避免雪崩）"""
        cb = CircuitBreaker(name="cb", failure_threshold=2, recovery_timeout=10)
        call_count = {"n": 0}

        async def downstream():
            call_count["n"] += 1
            raise ConnectionError("down")

        # 前 2 次调用下游，都失败
        for _ in range(2):
            with pytest.raises(ConnectionError):
                await cb.call(downstream)
        assert call_count["n"] == 2
        assert cb.state == CircuitState.OPEN

        # 后续 5 次调用 - 不应触达下游
        for _ in range(5):
            with pytest.raises(CircuitBreakerOpenError):
                await cb.call(downstream)
        # 调用次数仍为 2
        assert call_count["n"] == 2
