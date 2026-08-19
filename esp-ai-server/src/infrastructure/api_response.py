"""统一 API 响应模型与速率限制

提供：
- ``ApiResponse``：标准化 REST API 响应封装（``{code, message, data}``）。
  与现有路由返回的字典结构完全一致，便于逐步迁移而不破坏前端契约。
- ``success`` / ``error``：构造响应的快捷工厂函数。
- ``RateLimiter``：基于令牌桶的内存级速率限制器，按客户端 IP 维度限流。
  当 ``max_rpm <= 0`` 时自动禁用（零开销直通）。

设计目标：
- 零破坏性：``ApiResponse`` 序列化结果与现有 ``{"code":0,"message":"ok","data":...}``
  字典逐字节一致，路由可按需迁移。
- 可观测：速率限制触发时记录 WARNING 并返回 429，响应头携带 ``Retry-After``。
- 无外部依赖：不引入 redis 等中间件，适合单机/中小规模部署。
"""
from __future__ import annotations

import time
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


# ============================================================
# 统一响应模型
# ============================================================

class ApiResponse(BaseModel):
    """标准化 REST API 响应封装

    约定：
    - ``code == 0`` 表示成功，非 0 表示失败。
    - ``message`` 为人类可读的提示信息。
    - ``data`` 为业务数据，失败时通常为 ``None``。

    序列化结果与现有路由返回的字典结构一致，可直接替换 ``return {...}``。
    """

    code: int = Field(default=0, description="业务状态码，0=成功，非 0=失败")
    message: str = Field(default="ok", description="提示信息")
    data: Optional[Any] = Field(default=None, description="业务数据")

    model_config = {"extra": "forbid"}


def success(data: Any = None, message: str = "ok") -> dict:
    """构造成功响应字典

    返回普通 dict 而非 ApiResponse 实例，便于现有路由零改动直接 ``return``。
    """
    return {"code": 0, "message": message, "data": data}


def error(message: str, code: int = 1, data: Any = None) -> dict:
    """构造失败响应字典"""
    return {"code": code, "message": message, "data": data}


# ============================================================
# 速率限制器（令牌桶，按客户端 IP）
# ============================================================

class _TokenBucket:
    """单客户端令牌桶

    桶容量 = max_rpm，每秒补充 max_rpm/60 个令牌。
    线程安全由 GIL 保证（仅 asyncio 协程访问，无真并行）。
    """

    __slots__ = ("capacity", "refill_rate", "tokens", "last_refill")

    def __init__(self, capacity: int, refill_rate: float) -> None:
        self.capacity = float(capacity)
        self.refill_rate = refill_rate  # tokens per second
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now

    def consume(self, tokens: float = 1.0) -> bool:
        """尝试消费令牌，成功返回 True"""
        self._refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    def retry_after_seconds(self, tokens: float = 1.0) -> float:
        """估算还需多少秒才能凑够 tokens 个令牌"""
        self._refill()
        deficit = tokens - self.tokens
        if deficit <= 0:
            return 0.0
        return deficit / self.refill_rate if self.refill_rate > 0 else 1.0


class RateLimiter:
    """基于客户端 IP 的速率限制器

    - ``max_rpm <= 0`` 时禁用，``allow`` 永远返回 True（零开销）。
    - 每个客户端 IP 独立维护令牌桶。
    - 定期清理超过 10 分钟未访问的桶，防止内存泄漏。
    """

    # 清理间隔（秒）
    _GC_INTERVAL = 300
    # 桶闲置过期时间（秒）
    _BUCKET_TTL = 600

    def __init__(self, max_rpm: int = 0) -> None:
        self.max_rpm = max_rpm
        self._enabled = max_rpm > 0
        self._buckets: dict[str, _TokenBucket] = {}
        self._last_access: dict[str, float] = {}
        self._refill_rate = (max_rpm / 60.0) if self._enabled else 0.0
        self._last_gc = time.monotonic()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def allow(self, client_id: str) -> tuple[bool, float]:
        """检查客户端是否被允许访问

        Returns:
            (allowed, retry_after_seconds)
        """
        if not self._enabled:
            return True, 0.0

        now = time.monotonic()
        # 惰性 GC
        if now - self._last_gc > self._GC_INTERVAL:
            self._gc(now)

        bucket = self._buckets.get(client_id)
        if bucket is None:
            bucket = _TokenBucket(self.max_rpm, self._refill_rate)
            self._buckets[client_id] = bucket

        self._last_access[client_id] = now
        if bucket.consume(1.0):
            return True, 0.0
        return False, bucket.retry_after_seconds(1.0)

    def _gc(self, now: float) -> None:
        """清理过期桶"""
        expired = [cid for cid, ts in self._last_access.items() if now - ts > self._BUCKET_TTL]
        for cid in expired:
            self._buckets.pop(cid, None)
            self._last_access.pop(cid, None)
        self._last_gc = now
        if expired:
            logger.debug(f"[RateLimit] 清理 {len(expired)} 个过期限流桶，当前活跃 {len(self._buckets)}")


# 模块级单例：由 web.py 在应用启动时初始化
_rate_limiter: Optional[RateLimiter] = None


def init_rate_limiter(max_rpm: int = 0) -> RateLimiter:
    """初始化全局速率限制器（应用启动时调用）"""
    global _rate_limiter
    _rate_limiter = RateLimiter(max_rpm=max_rpm)
    if _rate_limiter.enabled:
        logger.info(f"[RateLimit] 速率限制已启用，上限 {max_rpm} req/min/IP")
    else:
        logger.info("[RateLimit] 速率限制未启用（max_rpm<=0）")
    return _rate_limiter


def get_rate_limiter() -> RateLimiter:
    """获取全局速率限制器实例"""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(max_rpm=0)
    return _rate_limiter


__all__ = [
    "ApiResponse",
    "success",
    "error",
    "RateLimiter",
    "init_rate_limiter",
    "get_rate_limiter",
]
