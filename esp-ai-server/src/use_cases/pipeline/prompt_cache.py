"""Prompt 组装素材的模块级缓存（按 device_id）。

pipeline 每轮对话新建实例，实例级缓存无法跨轮次；放到模块级注册表后：
1) 同设备 60s 内的后续轮次直接命中，省去每轮 2-3 次 DB 读；
2) 设备唤醒时（用户开口前 1-2 秒）可通过 prewarm_prompt_caches()
   在唤醒提示音播放的空档里预取，首轮对话也能全量命中。
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


# ============================================================
# Prompt 组装素材缓存（按 device_id，模块级）
#
# pipeline 每轮对话新建实例，实例级缓存无法跨轮次；放到模块级注册表后：
# 1) 同设备 60s 内的后续轮次直接命中，省去每轮 2-3 次 DB 读；
# 2) 设备唤醒时（用户开口前 1-2 秒）可通过 prewarm_prompt_caches()
#    在唤醒提示音播放的空档里预取，首轮对话也能全量命中。
# 这些都是低频变化数据，60s 陈旧窗口对回复质量无可感知影响。
# ============================================================
PROMPT_CACHE_TTL = 60.0


@dataclass
class _PromptCache:
    ltm_catalog: Optional[str] = None
    ltm_catalog_ts: float = 0.0
    profile_summary: Optional[str] = None
    profile_ts: float = 0.0
    ltm_items: Optional[list] = None
    ltm_items_ts: float = 0.0


_prompt_caches: dict[str, _PromptCache] = {}


def _get_prompt_cache(device_id: str) -> _PromptCache:
    cache = _prompt_caches.get(device_id)
    if cache is None:
        cache = _prompt_caches[device_id] = _PromptCache()
    return cache


async def _fetch_profile_summary(device_id: str) -> str:
    """获取用户画像摘要（get_profile_summary 内部已含 get_profile，勿拆开重复调用）"""
    from src.plugins.growth.engine.user_profile import UserProfileService
    return await UserProfileService("").get_profile_summary(device_id)


async def prewarm_prompt_caches(device_id: str, ltm_service) -> None:
    """唤醒预热：在用户开口前并行预取 LTM 目录、记忆条目与用户画像。

    在 _do_wake_start 里以后台任务调用——设备播放唤醒提示音的 1-2 秒
    足够完成全部预取，使首轮对话的 prompt 组装接近 0ms。
    """
    try:
        cache = _get_prompt_cache(device_id)
        now = time.time()

        async def _catalog():
            if cache.ltm_catalog is None or (now - cache.ltm_catalog_ts) >= PROMPT_CACHE_TTL:
                cache.ltm_catalog = await ltm_service.get_summary_catalog(device_id)
                cache.ltm_catalog_ts = time.time()

        async def _items():
            if cache.ltm_items is None or (now - cache.ltm_items_ts) >= PROMPT_CACHE_TTL:
                cache.ltm_items = await ltm_service.list_all(device_id)
                cache.ltm_items_ts = time.time()

        async def _profile():
            if cache.profile_summary is None or (now - cache.profile_ts) >= PROMPT_CACHE_TTL:
                cache.profile_summary = await _fetch_profile_summary(device_id)
                cache.profile_ts = time.time()

        await asyncio.gather(_catalog(), _items(), _profile(), return_exceptions=True)
    except Exception as e:
        logger.debug(f"[Pipeline] 唤醒预热失败: {e}")
