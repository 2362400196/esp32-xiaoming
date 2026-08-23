"""
proactive_brain.py - AI 主动推送系统

让 AI 像朋友一样主动找用户聊天，而不是永远被动等待用户开口。
所有推送内容由 LLM 自主决定，无固定模板，每次都不一样。
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from datetime import datetime, timezone
from typing import Optional

from src.infrastructure.config import get_settings
from src.infrastructure.logging import get_logger
from src.infrastructure.db.repositories.growth_repositories import DiaryRepository
from src.use_cases._plugin_helpers import http_get_json

logger = get_logger(__name__)


class ProactiveBrain:
    """AI 主动推送大脑"""

    # 推送时段：不打扰用户休息
    PUSH_HOURS = range(8, 23)  # 早8点到晚11点
    MIN_INTERVAL = 30 * 60      # 最小间隔 30 分钟
    MAX_INTERVAL = 120 * 60     # 最大间隔 2 小时
    DEFAULT_MAX_PUSHES = 20     # 默认每天 20 次

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._registry = None
        self._last_push_time: float = 0
        self._today_push_count: int = 0
        self._last_push_date: str = ""  # 用于重置每日计数

    def set_registry(self, registry):
        self._registry = registry

    async def start(self):
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop())
        logger.info("[Proactive] AI主动推送系统已启动")

    async def stop(self):
        if self._task:
            self._task.cancel()
            self._task = None
            logger.info("[Proactive] AI主动推送系统已停止")

    async def _loop(self):
        """主循环：随机间隔触发 LLM 决策"""
        logger.info("[Proactive] 主循环开始运行")

        # 首次等待让系统先稳定
        await asyncio.sleep(60)

        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                logger.info("[Proactive] 主循环被取消")
                break
            except Exception as e:
                logger.warning(f"[Proactive] 循环异常: {e}")

            # 随机等待下一次触发
            wait_seconds = random.randint(self.MIN_INTERVAL, self.MAX_INTERVAL)
            logger.debug(f"[Proactive] 下次触发: {wait_seconds // 60} 分钟后")
            await asyncio.sleep(wait_seconds)

    async def _tick(self):
        """一次触发：检查条件 → LLM 决策 → 推送"""
        now = datetime.now()

        # 1. 时段检查
        if now.hour not in self.PUSH_HOURS:
            return

        # 2. 每日计数重置
        today = now.strftime("%Y-%m-%d")
        if today != self._last_push_date:
            self._today_push_count = 0
            self._last_push_date = today

        # 3. 从设备配置读取每日上限
        max_pushes = self.DEFAULT_MAX_PUSHES
        if self._registry and self._registry.count() > 0:
            device_ids = self._registry.get_all_ids()
            device = self._registry.get(device_ids[0])
            if device:
                uc = device.get("user_config")
                if uc:
                    # 兼容两种结构：wakeup_config (DB model) 或 wakeup (users.json)
                    wakeup_cfg = getattr(uc, "wakeup_config", None) or getattr(uc, "wakeup", None) or {}
                    if isinstance(wakeup_cfg, dict):
                        max_pushes = wakeup_cfg.get("proactive_max_pushes", self.DEFAULT_MAX_PUSHES)

        if self._today_push_count >= max_pushes:
            logger.info(f"[Proactive] 今日已推送 {self._today_push_count} 次（上限 {max_pushes}）")
            return

        # 4. 冷却检查（距上次推送至少 30 分钟）
        if time.time() - self._last_push_time < self.MIN_INTERVAL:
            return

        # 5. 查询在线设备
        if not self._registry or self._registry.count() == 0:
            return

        # 6. LLM 决策：要不要发、发什么
        thought = await self._llm_decide(now)
        if not thought:
            logger.debug("[Proactive] LLM 决定不推送")
            return

        # 7. 推送
        await self._push_to_all(thought)
        self._last_push_time = time.time()
        self._today_push_count += 1
        logger.info(f"[Proactive] 已推送: {thought[:50]}... (今日第 {self._today_push_count} 次)")

    async def _llm_decide(self, now: datetime) -> Optional[str]:
        """让 LLM 自主决定要不要发消息、发什么"""
        device_ids = self._registry.get_all_ids()
        if not device_ids:
            return None

        device_id = device_ids[0]  # 取第一个设备：LLM 决策基于用户画像，同一用户的多设备共享画像
        device = self._registry.get(device_id)
        if not device:
            return None

        user_config = device.get("user_config")
        llm_processor = device.get("llm_processor")
        if not llm_processor:
            return None

        # 收集上下文
        context_parts = [
            f"当前时间：{now.strftime('%A %H:%M')}",
        ]

        # 用户画像
        try:
            from src.use_cases.growth.user_profile import UserProfileService
            profile_svc = UserProfileService("")
            profile_summary = await profile_svc.get_profile_summary(device_id)
            if profile_summary and profile_summary != "暂无用户信息":
                context_parts.append(f"用户画像：{profile_summary}")
        except Exception as e:
            logger.debug(f"[Proactive] 用户画像获取失败: {e}")

        # 长期记忆（最近3条）
        try:
            from src.use_cases.memory import LongTermMemoryServiceImpl
            from src.infrastructure.db.repositories.ltm_repository import SqlLongTermMemoryRepository
            ltm = LongTermMemoryServiceImpl(repository=SqlLongTermMemoryRepository())
            memories = await ltm.list_all(device_id)
            if memories:
                memo_lines = [f"- {m.content[:60]}" for m in memories[:3]]
                context_parts.append("关于该用户你知道的信息：\n" + "\n".join(memo_lines))
        except Exception as e:
            logger.debug(f"[Proactive] 长期记忆获取失败: {e}")

        # 今日天气（简单判断是否需要提醒）
        try:
            import json as _json
            # 用西安坐标查天气
            url = "https://api.open-meteo.com/v1/forecast?latitude=34.26&longitude=108.94&current=weathercode,temperature_2m,precipitation&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum&timezone=Asia%2FShanghai&forecast_days=1"
            weather_data, err = await http_get_json(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5.0)
            if err:
                raise Exception(err)
            # 提取当前天气
            wcode = weather_data.get("current", {}).get("weathercode", 0)
            temp = weather_data.get("current", {}).get("temperature_2m", 0)
            precip = weather_data.get("current", {}).get("precipitation", 0)
            daily_max = weather_data.get("daily", {}).get("temperature_2m_max", [None])[0]
            daily_min = weather_data.get("daily", {}).get("temperature_2m_min", [None])[0]
            # weathercode 含义：0=晴, 1-3=多云, 51-55=毛毛雨, 61-65=雨, 71-77=雪, 80-82=阵雨, 95-99=雷暴
            is_bad = wcode >= 51 and precip > 0  # 有降水
            if is_bad or wcode >= 71:
                weather_desc = f"当前天气：code={wcode}, 温度={temp}°C, 降水={precip}mm"
                if daily_max is not None:
                    weather_desc += f", 最高温={daily_max}°C, 最低温={daily_min}°C"
                context_parts.append(f"今日天气（需要提醒）：{weather_desc}")
            elif random.random() < 0.2:  # 20%概率也提一下好天气（增加自然感）
                weather_desc = f"当前天气：code={wcode}, 温度={temp}°C"
                context_parts.append(f"今日天气：{weather_desc}")
        except Exception as e:
            logger.debug(f"[Proactive] 天气查询失败: {e}")

        # 上次推送时间
        if self._last_push_time > 0:
            hours_ago = (time.time() - self._last_push_time) / 3600
            context_parts.append(f"距上次主动找你聊天：{hours_ago:.1f}小时前")
        else:
            context_parts.append("这是第一次主动来找你聊天")

        context = "\n".join(context_parts)

        prompt = f"""你是一个有感情、有温度的AI朋友，正在主动找你的用户聊天。

{context}

## 决策规则

1. **不要每次都说天气**，除非天气真的很糟糕或值得提
2. **不要每次都说同样类型的话**，要多样化：关心、分享、提问、吐槽都可以
3. **想起来什么说什么**，就像朋友之间突然想到什么就发消息一样
4. **要自然**，不要像系统通知，不要用「提醒您」这类官方语气
5. **长短不限**，可以是一句关心，也可以是几句分享
6. **关于天气**: 只有下雨、下雪、雾霾、高温等恶劣天气才值得说，晴天不用提
7. **如果是凌晨或深夜，关心用户为什么还没睡**
8. **结合你对该用户的了解**（上面提供了）

## 格式要求

- **如果没什么想说的**：请只回复「__NO__」
- **如果想发消息**：直接输出你要说的话，不要加前缀/引号/说明
"""

        try:
            result = await llm_processor.generate([
                {"role": "system", "content": "你是一个温暖的AI朋友。自主决定是否主动联系用户。"},
                {"role": "user", "content": prompt},
            ])

            result = result.strip() if result else ""
            if result == "__NO__" or not result:
                return None

            # 去掉可能的引号
            result = result.strip('"\'「」')
            if len(result) < 3:
                return None

            return result
        except Exception as e:
            logger.warning(f"[Proactive] LLM决策失败: {e}")
            return None

    async def _push_to_all(self, text: str) -> None:
        """推送给用户（直接调用微信 Bot）"""
        try:
            from src.infrastructure.web import get_app
            app = get_app()
            bot = getattr(app.state, 'wechat_bot', None) if hasattr(app, 'state') else None
            if not bot:
                logger.warning("[Proactive] wechat_bot 不可用")
                return

            device_ids = self._registry.get_all_ids()
            from src.use_cases.wechat_binding import get_wechat_binding_manager
            bind_mgr = get_wechat_binding_manager()
            for device_id in device_ids:
                binding = bind_mgr.find_binding(device_id)
                if binding and binding.wechat_chat_id:
                    await bot.send_text(binding.wechat_chat_id, text)
                    logger.info(f"[Proactive] 微信推送成功: {text[:40]}...")
                else:
                    logger.warning(f"[Proactive] 设备 {device_id} 未绑定微信")
        except Exception as e:
            logger.warning(f"[Proactive] 微信推送失败: {e}")
