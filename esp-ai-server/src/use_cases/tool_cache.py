"""ToolCache - 工具调用结果缓存

缓存 LLM 工具调用的返回结果，避免相同参数重复执行。
默认 TTL 300 秒，支持最大缓存条目数限制和 LRU 淘汰。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any, Optional


class ToolCache:
    """工具调用结果缓存，支持 TTL 和 LRU 淘汰。

    用于缓存 LLM 工具调用的返回结果，
    在相同参数重复调用时直接返回缓存结果，避免重复执行。
    cache=False 的工具跳过缓存（如含屏幕显示的查询工具）。
    """

    def __init__(self, ttl: int = 300, max_size: int = 1000):
        self._ttl = ttl
        self._max_size = max_size
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0

    def _generate_key(self, tool_name: str, arguments: dict) -> str:
        key_str = f"{tool_name}:{json.dumps(arguments, sort_keys=True)}"
        return hashlib.md5(key_str.encode()).hexdigest()

    async def get(self, tool_name: str, arguments: dict) -> Optional[Any]:
        key = self._generate_key(tool_name, arguments)

        async with self._lock:
            if key in self._cache:
                timestamp, result = self._cache[key]
                if time.time() - timestamp < self._ttl:
                    self._hits += 1
                    return result
                else:
                    del self._cache[key]

        self._misses += 1
        return None

    async def set(self, tool_name: str, arguments: dict, result: Any) -> None:
        key = self._generate_key(tool_name, arguments)

        async with self._lock:
            if len(self._cache) >= self._max_size:
                oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][0])
                del self._cache[oldest_key]

            self._cache[key] = (time.time(), result)

    async def clear(self) -> None:
        async with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def get_stats(self) -> dict:
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "ttl": self._ttl,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": hit_rate,
        }


__all__ = ["ToolCache"]