"""流水线主流程：一轮对话的完整 run() 实现。"""
from __future__ import annotations

import asyncio
import time

from src.infrastructure.logging import get_logger
from src.infrastructure.monitoring import get_metrics
from src.use_cases.pipeline.prompt_cache import (
    PROMPT_CACHE_TTL,
    _fetch_profile_summary,
    _get_prompt_cache,
)
from src.use_cases.pipeline.signals import DEFAULT_MEMORY_SEARCH_KEYWORDS
from src.use_cases.pipeline.types import PipelineResult, PipelineState

logger = get_logger(__name__)


class RunnerMixin:
    """组装 prompt、启动 4 个 Worker 并等待一轮对话结束。"""

    async def run(self, iat_text: str, system_prompt: str = "") -> PipelineResult:
        """
        运行完整流水线

        Args:
            iat_text: ASR识别的文本
            system_prompt: 系统提示词

        Returns:
            PipelineResult
        """
        start_time = time.time()
        # 业务指标：Pipeline 启动
        _pipeline_track_status = "completed"
        logger.info(f"[Pipeline] run() 被调用, iat_text='{iat_text[:30] if iat_text else '空'}', ltm={'有' if self.ltm_service else '无'}")
        try:
            get_metrics().track_pipeline_run("started")
        except Exception:
            pass
        self.tts_playback_done.clear()
        self.tts_drain_ack.clear()
        self.tts_audio_ended.clear()
        self.queues.clear_all()
        self.splitter.reset()

        await self.set_tts_playing(True)
        await self.set_device_buffer(self.config.client_max_buffer)
        self.tts_drain_ack.clear()

        from src.domain.entities import SessionState
        await self.fsm.set(SessionState.LLM)

        llm = self.llm_processor
        self._tool_manager = getattr(llm, "tool_manager", None)
        memory_enabled = True
        memory_max = 10
        if self.user_config:
            if getattr(self.user_config, "llm_memory_enabled", None) is not None:
                memory_enabled = self.user_config.llm_memory_enabled
            if getattr(self.user_config, "llm_memory_max_messages", None) is not None:
                memory_max = self.user_config.llm_memory_max_messages

        # 优先使用 user_config.llm_system_prompt（支持热重载），回退到 LLM 处理器内置值
        _user_sp = ""
        if self.user_config and getattr(self.user_config, "llm_system_prompt", None):
            _user_sp = self.user_config.llm_system_prompt
        _llm_sp = llm.system_prompt if hasattr(llm, "system_prompt") else ""
        sp = system_prompt or _user_sp or _llm_sp

        # === 静态块前置 ===
        # system prompt 的拼装顺序对 LLM 供应商的前缀缓存（如 DeepSeek 上下文缓存）
        # 至关重要：所有逐字节稳定的内容（回复风格/工具规则、设备能力边界、设备 ID）
        # 必须在最前，多轮对话间才能命中缓存，显著降低 TTFT 与费用。
        # 动态内容（skill/记忆/画像）放在后部，也更贴近对话消息、利于模型注意力。
        # 注入回复风格要求（静态字符串）
        sp = sp + self._reply_style

        # 注入设备能力边界（插件商店语义）：设置过插件白名单的设备，未列入的插件功能不可用
        try:
            _tm = getattr(llm, "tool_manager", None)
            if _tm is not None and hasattr(_tm, "_enabled_plugins"):
                _installed = _tm._enabled_plugins
                if _installed is not None and len(_installed) > 0:
                    _cap_note = (f"\n\n【设备能力边界】本设备仅启用插件: {'、'.join(sorted(_installed))}。"
                                 "用户询问的功能如果不在上述插件能力或系统自带能力范围内，"
                                 "直接回答\"该功能未安装/设备暂不支持\"，"
                                 "绝不可以用猜测、编造或历史经验回答，也不要假装执行了操作。")
                    sp = sp + _cap_note
        except Exception:
            pass

        # 设备 ID（静态）
        sp = sp + f"\nDevice ID: {self.device_id}"

        # === 动态块：skill 目录/长期记忆/画像/相关记忆四路并行获取 ===
        # 串行执行时这段是 ASR 完成→LLM 请求发出之间的主要额外延迟。
        _prompt_t0 = time.time()

        _pcache = _get_prompt_cache(self.device_id)

        async def _skill_catalog_block() -> str:
            """Skill 目录（按用户输入动态检索；缓存键含 query，逐查询重渲染）"""
            try:
                from src.use_cases import skill_system
                _skills = getattr(self.user_config, 'skills', None) if self.user_config else None
                _disabled = getattr(self.user_config, 'disabled_skills', None) if self.user_config else None
                _skill_key = f"{self.device_id}:{_skills}:{_disabled}:{iat_text}"
                if self._cached_skill_catalog is None or getattr(self, '_skill_cache_key', '') != _skill_key:
                    catalog = skill_system.render_skills_catalog(
                        device_id=self.device_id,
                        skills=_skills,
                        disabled_skills=_disabled,
                        query=iat_text,
                    )
                    self._cached_skill_catalog = catalog
                    self._skill_cache_key = _skill_key
                else:
                    catalog = self._cached_skill_catalog
                return ("\n\n" + catalog) if (catalog and sp) else catalog
            except Exception as e:
                logger.debug(f"[Pipeline] 注入 Skill 目录失败: {e}")
                return ""

        async def _ltm_catalog_block() -> str:
            if not self.ltm_service:
                return ""
            _now = time.time()
            if _pcache.ltm_catalog is not None and (_now - _pcache.ltm_catalog_ts) < PROMPT_CACHE_TTL:
                _catalog = _pcache.ltm_catalog
            else:
                _catalog = await self.ltm_service.get_summary_catalog(self.device_id)
                _pcache.ltm_catalog = _catalog
                _pcache.ltm_catalog_ts = _now
            if not _catalog:
                return ""
            return (
                "\n\n[Long-term Memory Summary Labels]\n"
                "用户提到相关话题时，主动调用 memory_recall 回忆（标签见下）：\n"
                f"{_catalog}\n"
                "[/Long-term Memory]"
            )

        async def _profile_block() -> str:
            _now = time.time()
            if _pcache.profile_summary is not None and (_now - _pcache.profile_ts) < PROMPT_CACHE_TTL:
                _profile_summary = _pcache.profile_summary
            else:
                _profile_summary = await _fetch_profile_summary(self.device_id)
                _pcache.profile_summary = _profile_summary
                _pcache.profile_ts = _now
            if not _profile_summary or _profile_summary == "暂无用户信息":
                return ""
            return (
                "\n\n[User Profile]\n"
                "以下是该用户的画像信息，帮助你在回答时更个性化：\n"
                f"{_profile_summary}\n"
                "[/User Profile]"
            )

        async def _memory_block() -> str:
            if not (self.ltm_service and iat_text and len(iat_text) > 3):
                return ""
            _now = time.time()
            if _pcache.ltm_items is not None and (_now - _pcache.ltm_items_ts) < PROMPT_CACHE_TTL:
                _all_items = _pcache.ltm_items
            else:
                _all_items = await self.ltm_service.list_all(self.device_id)
                _pcache.ltm_items = _all_items
                _pcache.ltm_items_ts = _now
            if not _all_items:
                return ""
            _search = iat_text.lower()
            _matched = []
            for _item in _all_items:
                _content = _item.content.lower()
                _score = 0
                # 整词匹配（中文按字符连续匹配）
                for w in (self.memory_search_keywords or DEFAULT_MEMORY_SEARCH_KEYWORDS):
                    if w in _search or w in _content:
                        _score += 1
                # 关键词字段匹配
                if _item.keywords:
                    for kw in _item.keywords:
                        if kw.lower() in _search:
                            _score += 2
                        if kw.lower() in _content:
                            _score += 1
                if _score > 0:
                    _matched.append((_score, _item))
            _matched.sort(key=lambda x: -x[0])
            if not _matched:
                logger.info(f"[Pipeline] 无匹配记忆 (len={len(_all_items)}, search='{iat_text[:30]}')")
                return ""
            logger.info(f"[Pipeline] 自动注入 {len(_matched)} 条相关记忆")
            _mem_block = "\n\n[Relevant Memories]\n以下是和你当前话题相关的记忆，回答时可以自然联系：\n"
            for _score, _m in _matched[:3]:
                _mem_block += f"- {_m.content}\n"
            return _mem_block + "[/Relevant Memories]"

        _ltm_result, _profile_result, _skill_result, _memory_result = await asyncio.gather(
            _ltm_catalog_block(), _profile_block(), _skill_catalog_block(), _memory_block(),
            return_exceptions=True,
        )
        # 拼装顺序（与获取并行解耦）：稳定块（LTM/画像）在前扩大前缀缓存命中面，
        # 逐查询变化的块（skill/相关记忆）最后，贴近对话消息
        for _name, _res in (("LTM", _ltm_result), ("画像", _profile_result),
                            ("Skill", _skill_result), ("记忆", _memory_result)):
            if isinstance(_res, asyncio.CancelledError):
                # 中断打断 prompt 组装时保持取消语义（gather 会吞掉 CancelledError）
                raise _res
            if isinstance(_res, BaseException):
                logger.debug(f"[Pipeline] {_name} 注入失败: {_res}")
            elif _res:
                sp = sp + _res

        # 最终长度提醒：置于 system prompt 最末尾（所有注入块之后），
        # 利用模型对 prompt 末尾的高权重重新压住回复长度（技能等块会把回复带长）
        sp = sp + self._reply_style_tail

        self._perf["prompt_assembly_ms"] = int((time.time() - _prompt_t0) * 1000)
        logger.info(f"[Pipeline] prompt 组装完成: {self._perf['prompt_assembly_ms']}ms（含 skill/记忆/画像目录）")

        if memory_enabled and self.conversation_memory:
            self.conversation_memory.max_messages = memory_max
            # 性能优化：异步延迟加载历史消息，避免阻塞事件循环
            await self.conversation_memory.ensure_loaded()
            messages = self.conversation_memory.build_messages(sp, iat_text)
        else:
            messages = [
                {"role": "system", "content": sp},
                {"role": "user", "content": iat_text},
            ]

        # 诊断：prompt 体积（TTFT 与 prompt 大小强相关，体积随会话/记忆增长时
        # 会在性能报告里直接暴露出来）
        self._perf["prompt_chars"] = len(sp)
        self._perf["history_chars"] = sum(
            len(m.get("content") or "") for m in messages if isinstance(m, dict)
        )

        # 调试：system prompt 含长期记忆、用户画像等隐私内容，仅 debug 级别打印前 500 字符，
        # 避免隐私泄露和每轮全量打印导致日志暴涨
        logger.debug(f"[Prompt] system prompt 共 {len(sp)} 字符: {sp[:500]}...")

        await self.fsm.set(SessionState.TTS)
        # play_audio 和 tts_chunk_start 延迟到第一帧音频数据到达时再发送
        # 避免 LLM+TTS 耗时超过客户端看门狗超时（10秒）
        self._play_audio_sent = False

        volc_tts = self.tts_processor
        # 并行启动 TTS 建连和 LLM（减少 150-400ms 串行延迟）
        tts_session_fut = asyncio.create_task(volc_tts.create_session(cancel_event=self.cancel_event, tool_manager=self._tool_manager))
        # LLM 可以立即开始，不需要等 TTS 建连
        t_llm = asyncio.create_task(self._llm_task(llm, messages))
        t_splitter = asyncio.create_task(self._splitter_task())
        t_sender = asyncio.create_task(self._sender_task())

        # 等待 TTS 建连完成（此时 LLM 可能已经在产出 token）
        tts_session = None
        try:
            tts_session = await tts_session_fut
        except Exception as e:
            logger.error(f"[Pipeline] TTS 预连接失败，将自行创建: {e}")

        self.state = PipelineState.RUNNING
        full_text = ""
        stop_pipeline = False
        self._total_duration_ms = 0.0  # 重置累计TTS音频总时长
        self._cumulative_duration_ms = 0.0  # 重置累计实际时长（字级时间戳绝对流位置基准）

        try:
            t_tts = asyncio.create_task(self._tts_task(volc_tts, tts_session))
            self._tasks = [t_llm, t_splitter, t_tts, t_sender]
            logger.info("[Pipeline] 4-Worker 已启动")

            done, pending = await asyncio.wait(
                self._tasks, return_when=asyncio.FIRST_EXCEPTION
            )

            for t in pending:
                t.cancel()

            from src.use_cases.tools_system import StopPipeline
            for t in done:
                exc = t.exception()
                if isinstance(exc, StopPipeline):
                    stop_pipeline = True
                    logger.info("[Pipeline] Worker 抛出 StopPipeline")
                elif exc and not isinstance(exc, asyncio.CancelledError):
                    logger.error(f"[Pipeline] Worker 异常: {exc}")

            for t in pending:
                try:
                    await t
                except (asyncio.CancelledError, StopPipeline):
                    pass
                except Exception as e:
                    logger.error(f"[Pipeline] Worker 清理异常: {e}")

            try:
                full_text = t_llm.result()
            except (asyncio.CancelledError, StopPipeline):
                pass
            except Exception as e:
                logger.debug(f"[Pipeline] 获取 LLM 结果异常: {e}")

        except asyncio.CancelledError:
            _pipeline_track_status = "error"
            logger.info("[Pipeline] 被取消")
            for t in self._tasks:
                if not t.done():
                    t.cancel()
        except StopPipeline:
            logger.info("[Pipeline] 工具请求停止 Pipeline")
            stop_pipeline = True
            for t in self._tasks:
                if not t.done():
                    t.cancel()
        except Exception as e:
            _pipeline_track_status = "error"
            logger.error(f"[Pipeline] 异常: {e}")
            for t in self._tasks:
                if not t.done():
                    t.cancel()

        # 注意：不在 Pipeline 结束时设置 tts_playing=False
        # 应该等客户端确认播放完成（client_out_audio_over）后再设置
        # 避免状态不一致导致无法启动下一轮 ASR

        if stop_pipeline:
            logger.info("[Pipeline] StopPipeline: 工具已接管音频通道，跳过 end_frame/tts_real_end")
        elif self.cancel_event.is_set():
            # cancel_event 在 send_session_end 时被设置，表示会话已结束或新唤醒已打断
            # 此时再发送 end_frame 会占用 channel，导致新唤醒的"叮"无法及时发送而超时
            logger.info("[Pipeline] cancel_event 已设置，跳过 end_frame/tts_real_end")
        elif self._play_audio_sent:
            # status="02"：继续对话语义，设备 drain 后不会恢复唤醒/闪"等待唤醒"，直接进入下一轮聆听
            await self.channel.send_bytes(self.voice_generator.make_end_frame(self.config.tts_session_id, status="02"))
            await asyncio.sleep(0.05)
            await self.channel.send_json({"type": "session_status", "status": "tts_real_end"})
            logger.info("[Pipeline] 已发送 end_frame + tts_real_end")
        else:
            logger.info("[Pipeline] 未发送任何音频帧，跳过 end_frame/tts_real_end")

        duration = time.time() - start_time
        self.state = PipelineState.STOPPED

        # 业务指标：Pipeline 执行结束（completed / error）
        try:
            get_metrics().track_pipeline_run(_pipeline_track_status, duration)
        except Exception:
            pass

        # 累计总音频时长（从实例变量获取）
        total_duration_ms = self._total_duration_ms
        logger.info(f"[Pipeline] 总音频时长: {total_duration_ms}ms ({total_duration_ms/1000:.1f}s)")

        # 关闭预创建的 TTS session（如果 _tts_task 没有关闭它）
        if tts_session is not None:
            try:
                await tts_session.close()
            except Exception as e:
                logger.debug(f"[Pipeline] 关闭预创建 TTS session 失败: {e}")

        return PipelineResult(
            state=self.state,
            duration=duration,
            full_text=full_text,
            stop_pipeline=stop_pipeline,
            total_duration_ms=total_duration_ms,
        )
