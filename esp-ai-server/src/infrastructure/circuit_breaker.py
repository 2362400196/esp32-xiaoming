"""通用熔断器

三态：CLOSED（正常）→ OPEN（熔断）→ HALF_OPEN（试探）→ CLOSED/HALF_OPEN

本模块提供独立于 MCP 工具系统的通用熔断器实现，
可被 TTS / ASR / LLM 等网关复用，避免下游服务故障级联。
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Any, Callable, Coroutine, TypeVar

from src.infrastructure.logging import get_logger

logger = get_logger("circuit_breaker")

T = TypeVar("T")


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpenError(Exception):
    """熔断器开启（OPEN）时调用被拒绝，抛出此异常"""

    pass


class CircuitBreaker:
    """通用熔断器

    状态机：
        CLOSED --失败次数达到 failure_threshold--> OPEN
        OPEN --经过 recovery_timeout--> HALF_OPEN（在 state 属性中惰性转换）
        HALF_OPEN --成功--> CLOSED
        HALF_OPEN --失败--> OPEN

    用法：
        breaker = CircuitBreaker(name="tts_volcengine", failure_threshold=5, recovery_timeout=60)
        try:
            result = await breaker.call(some_async_func, *args, **kwargs)
        except CircuitBreakerOpenError:
            # 熔断器开启，快速失败处理
            ...
    """

    def __init__(
        self,
        name: str = "",
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: type[Exception] | tuple[type[Exception], ...] = Exception,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0

    @property
    def state(self) -> CircuitState:
        """当前状态：访问时检查 OPEN 是否已到恢复时间，自动转为 HALF_OPEN"""
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time > self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                logger.info(f"[CircuitBreaker:{self.name}] OPEN -> HALF_OPEN")
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    async def call(self, func: Callable[..., Coroutine[Any, Any, T]], *args, **kwargs) -> T:
        """通过熔断器调用异步函数

        - 若熔断器为 OPEN，抛出 CircuitBreakerOpenError
        - 若 func 抛出 expected_exception，记录失败并重新抛出
        - 若 func 成功返回，记录成功
        """
        if self.state == CircuitState.OPEN:
            raise CircuitBreakerOpenError(f"Circuit breaker '{self.name}' is OPEN")

        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            logger.info(f"[CircuitBreaker:{self.name}] HALF_OPEN -> CLOSED")
        self._failure_count = 0

    def _on_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            logger.warning(f"[CircuitBreaker:{self.name}] HALF_OPEN -> OPEN")
        elif self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                f"[CircuitBreaker:{self.name}] CLOSED -> OPEN (failures={self._failure_count})"
            )

    def reset(self) -> None:
        """重置熔断器到 CLOSED 状态（主要用于测试或手动恢复）"""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0

    def record_success(self) -> None:
        """显式记录一次成功（用于流式 API 无法使用 call 包裹的场景）"""
        self._on_success()

    def record_failure(self) -> None:
        """显式记录一次失败（用于流式 API 无法使用 call 包裹的场景）"""
        self._on_failure()


__all__ = [
    "CircuitState",
    "CircuitBreaker",
    "CircuitBreakerOpenError",
]
