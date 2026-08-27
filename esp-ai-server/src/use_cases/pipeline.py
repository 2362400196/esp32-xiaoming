"""
Pipeline Use Cases - 核心流水线业务逻辑

与旧架构(app/session/session.py)完全对齐的4-Worker并发流水线：
- LLM Worker → Splitter → TTS Worker → Sender Worker
- 三级背压队列 (text_queue, audio_queue, send_queue)
- 支持中断/取消、StopPipeline异常、TTS session复用
- 完整的监控指标和错误恢复
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Optional

from src.domain.exceptions import PipelineError
from src.infrastructure.logging import get_logger
from src.infrastructure.monitoring import get_metrics
from src.use_cases.queues import BackpressureQueues
from src.use_cases.voice_generator import VoiceGenerator

if TYPE_CHECKING:
    from src.interfaces.llm_gateways import OpenAILLMGateway
    from src.interfaces.tts_gateways import VolcEngineTTSGateway
    from src.use_cases.auxiliary_services import ConversationMemory
    from src.use_cases.memory import LongTermMemoryServiceImpl
    from src.use_cases.session_fsm import SessionFSM, WSChannel

logger = get_logger(__name__)


# MP3 帧头解析：按比特率表计算每帧时长，累加得到总时长（支持 CBR/VBR）
# 注意：MPEG2/2.5 Layer III 的比特率仅为 MPEG1 的一半（8~160kbps）
_MP3_BITRATE = {
    (3, 1): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0],  # MPEG1 L3
    (2, 1): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],      # MPEG2 L3
    (0, 1): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],      # MPEG2.5 L3
}
_MP3_SAMPLE_RATE = {
    3: [44100, 48000, 32000, 0],  # MPEG1
    2: [22050, 24000, 16000, 0],  # MPEG2
    0: [11025, 12000, 8000, 0],   # MPEG2.5
}


def mp3_duration_ms(data: bytes) -> int:
    """解析 MP3 帧头计算总时长（ms）。仅处理 Layer III（TTS 输出格式）。"""
    if not data:
        return 0
    total_ms = 0
    pos = 0
    n = len(data)
    while pos + 4 <= n:
        if data[pos] != 0xFF or (data[pos + 1] & 0xE0) != 0xE0:
            pos += 1
            continue
        b1 = data[pos + 1]
        b2 = data[pos + 2]
        version = (b1 >> 3) & 0x03  # 3=MPEG1, 2=MPEG2, 0=MPEG2.5
        layer = (b1 >> 1) & 0x03    # 1=Layer III
        if version == 1 or layer != 1:
            pos += 1
            continue
        bitrate_idx = (b2 >> 4) & 0x0F
        sample_idx = (b2 >> 2) & 0x03
        padding = (b2 >> 1) & 0x01
        bitrate_kbps = _MP3_BITRATE.get((version, layer), [0] * 16)[bitrate_idx]
        sample_rate = _MP3_SAMPLE_RATE.get(version, [0] * 4)[sample_idx]
        if bitrate_kbps == 0 or sample_rate == 0:
            pos += 1
            continue
        if version == 3:
            frame_len = 144 * bitrate_kbps * 1000 // sample_rate + padding
            samples = 1152
        else:
            frame_len = 72 * bitrate_kbps * 1000 // sample_rate + padding
            samples = 576
        if frame_len <= 0:
            pos += 1
            continue
        total_ms += samples * 1000 // sample_rate
        pos += frame_len
    return total_ms


class SentenceSplitter:
    """句子分割器：将流式token组装成完整句子"""

    def __init__(self):
        self.buffer = ""

    def feed(self, token: str) -> list:
        if not token:
            return []

        self.buffer += token
        sentences = []

        # 硬切分点：句号、问号、感叹号
        if any(p in self.buffer for p in ["。", "！", "？", ".", "!", "?"]):
            parts = re.split(r"([。！？.!?])", self.buffer)
            tmp = ""
            for p in parts:
                tmp += p
                if p in "。！？.!?":
                    stripped = tmp.strip()
                    if stripped and len(stripped) > 1:
                        sentences.append(stripped)
                    tmp = ""
            self.buffer = tmp

        # 软切分点：逗号、分号（子句长度 >= 2 时切分，让首句更快产出送入 TTS）
        # 性能优化：从 4 字符降到 2 字符，首句 TTS 提前 ~500ms 启动
        if not sentences and any(p in self.buffer for p in ["，", "；", ","]):
            # 找最后一个软切分点
            last_soft = -1
            for i, ch in enumerate(self.buffer):
                if ch in "，；,":
                    last_soft = i
            if last_soft >= 0 and last_soft >= 1:  # 子句至少 2 个字符（索引>=1）
                sentence = self.buffer[:last_soft + 1].strip()
                if sentence and len(sentence) > 1:
                    sentences.append(sentence)
                self.buffer = self.buffer[last_soft + 1:]

        return sentences

    def flush(self) -> str:
        remaining = self.buffer.strip()
        self.buffer = ""
        return remaining if remaining and len(remaining) > 1 else ""

    def reset(self):
        self.buffer = ""


class PipelineState(Enum):
    IDLE = auto()
    RUNNING = auto()
    STOPPING = auto()
    STOPPED = auto()
    ERROR = auto()


@dataclass
class PipelineConfig:
    max_queue_size: int = 100
    llm_timeout: float = 30.0
    tts_timeout: float = 20.0
    enable_tts_session_reuse: bool = True
    tts_session_id: str = "0010"
    text_send_delay: int = 1
    client_max_buffer: int = 10240


@dataclass
class PipelineResult:
    state: PipelineState
    duration: float = 0.0
    total_sentences: int = 0
    total_audio_chunks: int = 0
    full_text: str = ""
    error: Optional[str] = None
    stop_pipeline: bool = False
    total_duration_ms: float = 0.0  # 总音频时长（毫秒）


class ConversationPipeline:
    """
    对话流水线：4-Worker并发架构（与旧架构完全对齐）

    架构：
    LLM Worker  → text_queue  → Splitter → audio_queue → TTS Worker → send_queue → Sender Worker

    特性：
    - 4个asyncio.Task并发运行
    - 三级背压队列（drop_oldest / block / block）
    - 支持cancel_event中断
    - 支持StopPipeline异常（工具接管音频通道）
    - TTS session复用
    - 文本延迟发送（与音频同步）
    """

    def __init__(
        self,
        llm_processor: Optional["OpenAILLMGateway"],
        tts_processor: Optional["VolcEngineTTSGateway"],
        channel: "WSChannel",
        fsm: "SessionFSM",
        voice_generator: Optional[VoiceGenerator] = None,
        config: Optional[PipelineConfig] = None,
        conversation_memory: Optional["ConversationMemory"] = None,
        user_config: Optional[dict] = None,
        cancel_event: Optional[asyncio.Event] = None,
        device_id: str = "",
        ltm_service: Optional["LongTermMemoryServiceImpl"] = None,
        max_sentences: int = 100,
    ) -> None:
        self.llm_processor = llm_processor
        self.tts_processor = tts_processor
        self.channel = channel
        self.fsm = fsm
        self.voice_generator = voice_generator or VoiceGenerator()
        self.config = config or PipelineConfig()
        self.conversation_memory = conversation_memory
        self.user_config = user_config
        self.device_id = device_id
        self.ltm_service = ltm_service

        self.queues = BackpressureQueues()
        self.splitter = SentenceSplitter()
        self.cancel_event = cancel_event if cancel_event is not None else asyncio.Event()

        self._tts_playing = False
        self._tts_playing_lock = asyncio.Lock()
        self.tts_playback_done = asyncio.Event()
        self.tts_drain_ack = asyncio.Event()
        self.tts_audio_ended = asyncio.Event()
        self._last_emotion = None
        self._device_buffer = self.config.client_max_buffer
        self._buffer_lock = asyncio.Lock()
        self.max_sentences = max_sentences

        self.state = PipelineState.IDLE
        self._tasks: list[asyncio.Task] = []
        # 后台任务引用（防止被 GC 回收导致协程中途取消且无告警）
        self._bg_tasks: set = set()
        self._total_duration_ms = 0.0  # 累计TTS音频总时长
        self._cumulative_duration_ms = 0.0  # 已合成句子累计实际时长，用于字级时间戳换算绝对流位置
        self._perf: dict = {}  # 性能分析计时数据（LLM/TTS 各环节耗时）

        # system prompt 缓存：回复要求基本不变，避免每次 run() 都重新拼接
        self._cached_reply_style: str = ""
        # 性能优化：缓存 LTM summary catalog，避免每次 run() 都查 DB
        self._cached_ltm_catalog: Optional[str] = None
        self._ltm_catalog_cache_time: float = 0.0
        self._ltm_catalog_ttl: float = 60.0  # 缓存 60 秒
        self._reply_style = (
            "\n\n[回复要求]\n"
            "- 日常闲聊时回复要简短自然，像真人聊天一样，一般 1-2 句话说完，不要长篇大论\n"
            "- 用口语化的方式说话，像朋友聊天\n"
            "- 不要每次都加表情符号\n"
            "- 不要说'好的'、'没问题'这种废话，直接回答\n"
            "- 如果用户明确要求讲故事、详细说明或长内容（如'讲个故事''说详细点'），可以生成完整的长内容，不要截断\n"
            "[/回复要求]\n"
            "\n[工具调用规则]\n"
            "- 你拥有可用的工具函数（tool functions）。当用户请求**操作类任务**（如调整音量/开关灯/播放音乐/查询信息/执行代码等）时，**必须通过调用对应的工具函数来完成**，不能只口头回复。\n"
            "- 如果用户的问题只需要知识和对话就能回答（如闲聊/问意见/讲故事），则正常用文字回复，不需要调用工具。\n"
            "- 调用工具后，根据工具返回的结果组织回答，输出给用户。\n"
            "- 当用户要求记住客观事实、偏好、身份信息等长期信息时（如'帮我记住/记录一下我爱吃西瓜'），使用 memory_store 存为长期记忆，不要用 write_diary。write_diary 只用于记录心情、想法、经历等日记内容。\n"
            "[/工具调用规则]"
        )

    @property
    def tts_playing(self):
        return self._tts_playing

    async def set_tts_playing(self, value: bool):
        async with self._tts_playing_lock:
            self._tts_playing = value

    @property
    def device_buffer(self):
        return self._device_buffer

    async def set_device_buffer(self, value: int):
        async with self._buffer_lock:
            self._device_buffer = value

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
                sp = (sp + _cap_note) if sp else _cap_note
        except Exception:
            pass

        # 注入 Skill 目录（按用户输入动态检索，控制提示词体积）
        try:
            from src.use_cases import skill_system
            _skills = getattr(self.user_config, 'skills', None) if self.user_config else None
            _disabled = getattr(self.user_config, 'disabled_skills', None) if self.user_config else None
            skill_catalog = skill_system.render_skills_catalog(
                device_id=self.device_id,
                skills=_skills,
                disabled_skills=_disabled,
                query=iat_text,
            )
            if skill_catalog:
                sp = sp + "\n\n" + skill_catalog if sp else skill_catalog
        except Exception as e:
            logger.debug(f"[Pipeline] 注入 Skill 目录失败: {e}")

        # 注入长期记忆摘要标签目录 + 设备 ID
        try:
            _device_info = f"\nDevice ID: {self.device_id}"
            if self.ltm_service:
                # 性能优化：使用缓存的 LTM catalog，避免每次 run() 都查 DB
                _now = time.time()
                _catalog = None
                if self._cached_ltm_catalog is not None and (_now - self._ltm_catalog_cache_time) < self._ltm_catalog_ttl:
                    _catalog = self._cached_ltm_catalog
                else:
                    _catalog = await self.ltm_service.get_summary_catalog(self.device_id)
                    self._cached_ltm_catalog = _catalog
                    self._ltm_catalog_cache_time = _now
                if _catalog:
                    _ltm_block = (
                        "\n\n[Long-term Memory Summary Labels]\n"
                        "用户提到相关话题时，主动调用 memory_recall 回忆（标签见下）：\n"
                        f"{_catalog}\n"
                        "[/Long-term Memory]"
                        f"{_device_info}"
                    )
                    sp = sp + _ltm_block
                else:
                    sp = sp + _device_info
            else:
                sp = sp + _device_info
        except Exception as e:
            logger.debug(f"[Pipeline] LTM 注入失败: {e}")

        # 注入用户画像（让 LLM 了解用户的背景信息）
        try:
            from src.use_cases.growth.user_profile import UserProfileService
            _profile_svc = UserProfileService("")
            _profile = await _profile_svc.get_profile(self.device_id)
            _profile_summary = await _profile_svc.get_profile_summary(self.device_id)
            if _profile_summary and _profile_summary != "暂无用户信息":
                _profile_block = (
                    "\n\n[User Profile]\n"
                    "以下是该用户的画像信息，帮助你在回答时更个性化：\n"
                    f"{_profile_summary}\n"
                    "[/User Profile]"
                )
                sp = sp + _profile_block
        except Exception as e:
            logger.debug(f"[Pipeline] 用户画像注入失败: {e}")

        # 注入回复风格要求（使用缓存的静态字符串）
        sp = sp + self._reply_style

        # 根据用户输入自动搜索相关记忆，注入上下文
        try:
            if self.ltm_service and iat_text and len(iat_text) > 3:
                _all_items = await self.ltm_service.list_all(self.device_id)
                if _all_items:
                    _search = iat_text.lower()
                    _matched = []
                    for _item in _all_items:
                        _content = _item.content.lower()
                        _score = 0
                        # 整词匹配（中文按字符连续匹配）
                        for w in ["工作", "累", "职业", "上班", "外卖", "代码", "顾客", "编程",
                                   "猫", "宠物", "玩具", "天气", "下雨", "送餐", "跑外卖"]:
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
                    if _matched:
                        _mem_block = "\n\n[Relevant Memories]\n以下是和你当前话题相关的记忆，回答时可以自然联系：\n"
                        for _score, _m in _matched[:3]:
                            _mem_block += f"- {_m.content}\n"
                        _mem_block += "[/Relevant Memories]"
                        sp = sp + _mem_block
                        logger.info(f"[Pipeline] 自动注入 {len(_matched)} 条相关记忆")
                    else:
                        logger.info(f"[Pipeline] 无匹配记忆 (len={len(_all_items)}, search='{iat_text[:30]}')")
        except Exception as e:
            logger.warning(f"[Pipeline] 记忆搜索注入失败: {e}")

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

        # 调试：打印完整系统提示词到终端，便于人工检查提示词体积与内容
        logger.info(f"[Prompt] ===== 系统提示词开始 ({len(sp)} 字符) =====\n{sp}\n===== 系统提示词结束 =====")

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
        total_sentences = 0
        total_audio_chunks = 0
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

    async def _llm_task(self, llm, messages):
        """LLM Worker：流式生成 → 分句 → text_queue"""
        seq_id = 0
        full_text = ""
        self._hard_sentence_count = 0
        fed_chars = 0
        _perf = self._perf
        _perf["llm_start"] = time.time()
        _perf["llm_first_token"] = 0.0
        from src.use_cases.tools_system import StopPipeline
        try:
            async for token in llm.stream_chat(messages):
                if self.cancel_event.is_set():
                    logger.info("[Pipeline] LLM 收到取消信号")
                    break

                if token == "__STOP_PIPELINE__":
                    logger.info("[Pipeline] LLM 发出 StopPipeline 信号")
                    raise StopPipeline()

                if token.startswith("LLM error"):
                    logger.error(f"[Pipeline] LLM 错误: {token}")
                    break

                if not _perf["llm_first_token"]:
                    _perf["llm_first_token"] = time.time()

                full_text += token
                sentences = self.splitter.feed(token)
                for sentence in sentences:
                    if self.cancel_event.is_set():
                        break
                    # 上限按完整句子（句号/感叹号/问号结尾）计数，而非逗号软切分片段，
                    # 避免"哈哈，"这类称呼片段浪费句数预算导致回复被截断。
                    # fed_chars>0 保证首句始终送入 TTS，避免单句超长时整轮静音
                    if self._hard_sentence_count >= self.max_sentences or (fed_chars > 0 and fed_chars + len(sentence) > self.MAX_CHARS):
                        logger.debug(f"[Pipeline] 超过回复上限，丢弃后续片段: {sentence[:30]}...")
                        continue
                    await self.queues.text.put((seq_id, sentence))
                    logger.debug(f"[Pipeline] 句子 #{seq_id} 入 text_queue: {sentence[:50]}...")
                    seq_id += 1
                    fed_chars += len(sentence)
                    if sentence[-1] in "。！？.!?":
                        self._hard_sentence_count += 1

            if not self.cancel_event.is_set():
                remaining = self.splitter.flush()
                if remaining and self._hard_sentence_count < self.max_sentences and (fed_chars == 0 or fed_chars + len(remaining) <= self.MAX_CHARS):
                    await self.queues.text.put((seq_id, remaining))
                    seq_id += 1

        except StopPipeline:
            raise
        except Exception as e:
            logger.error(f"[Pipeline] LLM 任务异常: {e}")
        finally:
            self.queues.text.put_nowait((-1, None))
            _perf["llm_end"] = time.time()
            _perf["llm_chars"] = len(full_text)
            _perf["llm_sentences"] = seq_id
            logger.info(f"[Pipeline] LLM 结束，共 {seq_id} 句，full_text={len(full_text)}字符")

        memory_enabled = True
        if self.user_config and getattr(self.user_config, "llm_memory_enabled", None) is not None:
            memory_enabled = self.user_config.llm_memory_enabled
        _mem = self.conversation_memory
        _log_ctx = f"mem_enabled={memory_enabled} full_text_len={len(full_text)} conv_mem={_mem is not None}"
        if _mem:
            _log_ctx += f" _msgs={len(_mem._messages)} repo={_mem._repository is not None}"
        logger.info(f"[Pipeline] 记忆检查: {_log_ctx}")
        if memory_enabled and full_text and self.conversation_memory:
            # 取最后一条 user 消息（即当前轮用户输入，而非历史中最旧的）
            iat_text = ""
            if messages:
                for _m in reversed(messages):
                    if isinstance(_m, dict) and _m.get("role") == "user":
                        iat_text = _m.get("content", "")
                        break
                logger.info(f"[Pipeline] 记忆: messages共{len(messages)}条, user_msg_len={len(iat_text)}")
            if iat_text:
                self.conversation_memory.add_user_message(iat_text)
                self.conversation_memory.add_assistant_message(full_text)

            # 异步触发长期记忆自动提取
            if self.device_id and iat_text and self.ltm_service:
                _device_id = self.device_id
                _user_text = iat_text

                async def _do_auto_extract():
                    try:
                        # 过滤简短闲聊（少于10个字或只有打招呼内容），不浪费 token
                        _user_text_clean = _user_text.strip()
                        if len(_user_text_clean) < 10 or _user_text_clean in ("你好", "你好呀", "hi", "hello", "在吗", "在不在"):
                            return
                        catalog = await self.ltm_service.get_summary_catalog(_device_id)
                        if not catalog:
                            return
                        summaries = await self.ltm_service.auto_extract(
                            _device_id,
                            _user_text,
                            lambda sys_p, usr_p: (
                                self.llm_processor.generate([
                                    {"role": "system", "content": sys_p},
                                    {"role": "user", "content": usr_p},
                                ])
                            ),
                        )
                        if summaries:
                            logger.info(f"[LTM] 自动提取: {summaries}")
                    except Exception as e:
                        logger.debug(f"[LTM] 自动提取摘要失败: {e}")

                _t = asyncio.create_task(_do_auto_extract())
                self._bg_tasks.add(_t)
                _t.add_done_callback(self._bg_tasks.discard)

        return full_text

    async def _splitter_task(self):
        """Splitter Worker：text_queue → audio_queue（合并短块，减少 TTS 请求数）

        首句立即发出保证首响延迟；后续软切分短句累积合并，
        遇到硬切分（。！？）或达到长度阈值时一次性发出。
        """
        pending = ""
        pending_seq = -1
        first_emitted = False
        try:
            while True:
                if self.cancel_event.is_set():
                    return

                seq_id, sentence = await self.queues.text.get()
                try:
                    if seq_id == -1 or sentence is None:
                        if pending:
                            await self.queues.audio.put((pending_seq, pending, pending))
                            pending = ""
                        await self.queues.audio.put((-1, None, None))
                        return

                    if not sentence.strip() or len(sentence.strip()) <= 1:
                        continue

                    if not first_emitted:
                        await self.queues.audio.put((seq_id, sentence, sentence))
                        first_emitted = True
                        continue

                    if not pending:
                        pending_seq = seq_id
                    pending += sentence
                    is_hard_stop = sentence[-1] in "。！？.!?"
                    if is_hard_stop or len(pending) >= self.MERGE_THRESHOLD:
                        await self.queues.audio.put((pending_seq, pending, pending))
                        pending = ""
                finally:
                    self.queues.text.task_done()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[Pipeline] Splitter 任务异常: {e}")

    MERGE_THRESHOLD = 40  # 短句合并长度阈值（字符），减少 TTS 请求数
    MAX_CHARS = 2000  # 回复合成字符上限（兜底，防止单个超长句）

    EMOTION_KEYWORDS: dict = {
        "快乐": ["哈哈", "开心", "高兴", "太好了", "棒", "妙", "不错", "喜欢", "爱", "谢谢", "恭喜", "nice", "good", "很好", "太棒了", "真不错", "赞"],
        "伤心": ["难过", "伤心", "哭", "难过死了", "糟糕", "惨", "绝望", "失落", "抑郁", "呜呜", "可怜", "悲伤", "心痛", "泪"],
        "愤怒": ["生气", "愤怒", "气死", "讨厌", "滚", "烦", "恶心", "无语", "扯淡", "胡扯", "滚开", "岂有此理", "惹", "火大", "暴怒", "恼火", "不爽"],
        "意外": ["真的假的", "不可能", "居然", "竟然", "天哪", "我的天", "没想到", "出乎意料", "哇塞"],
        "否定": ["拒绝", "否认"],
    }

    NEGATION_PREFIXES = ["不", "没", "别", "不太", "并不", "没有", "从未", "未必", "绝不", "从不"]

    # 过滤 Markdown 和特殊符号（工具调用结果常带这些）
    MARKDOWN_CLEANER = re.compile(r'(\*\*|__|\*|_|`|#{1,6}\s*|~~)(.*?)\1')
    LINE_CLEANER = re.compile(r'^[-*]\s+|^\d+\.\s+', re.MULTILINE)

    EMOTION_TAG_RE = re.compile(r'\[e:([^\]]+)\]')

    @staticmethod
    def _parse_emotion_tag(text: str) -> tuple[str, str]:
        """从 LLM 回复解析 [e:情绪] 标签，返回 (纯文本, 情绪)"""
        m = ConversationPipeline.EMOTION_TAG_RE.search(text)
        if m:
            emotion = m.group(1).strip()
            # 移除所有 [e:情绪] 标签（LLM 可能把标签放在开头/中间/末尾），保留其余文本。
            # 原实现只在标签位于末尾时正确：标签在开头时 text[:m.start()] 为空，
            # 调用方回退到原文，导致 "[e:无情绪]这回真调好了" 这类回复把标签念出来。
            clean = ConversationPipeline.EMOTION_TAG_RE.sub('', text).strip()
            clean = clean.rstrip('，。！？；,')
            return clean, emotion
        return text, ""

    @staticmethod
    def _keyword_detect(text: str) -> str:
        """关键词兜底检测"""
        text_lower = text.lower()
        for emotion, keywords in ConversationPipeline.EMOTION_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in text_lower:
                    return emotion
        return ""

    def _detect_and_send_emotion(self, sentence_text: str) -> str:
        """解析情绪标签发送，无标签时关键词兜底，都无则发无情绪"""
        clean_text, emotion = self._parse_emotion_tag(sentence_text)
        if not emotion:
            emotion = self._keyword_detect(sentence_text)
        if not emotion:
            emotion = "无情绪"
            # 无情绪不覆盖上次表情，避免打断当前情绪显示
        if emotion != self._last_emotion and emotion != "无情绪":
            self._last_emotion = emotion
            _t = asyncio.create_task(self._send_emotion_task(emotion))
            self._bg_tasks.add(_t)
            _t.add_done_callback(self._bg_tasks.discard)
        elif emotion == "无情绪" and self._last_emotion is None:
            self._last_emotion = emotion
        # 兜底：即使清理后为空（如回复只有标签），也返回去标签后的文本，
        # 避免回退原文把 [e:xxx] 念出来（后续 TTS 前有空文本过滤，不会合成空音频）
        return clean_text if clean_text else ConversationPipeline.EMOTION_TAG_RE.sub('', sentence_text).strip()

    async def _send_emotion_task(self, emotion: str):
        try:
            await self.channel.send_json({
                "type": "emotion",
                "data": emotion
            })
            logger.info(f"[Pipeline] 已发送表情: {emotion}")
            # 同步推送情绪到 Web 前端（设备屏幕实时显示情绪表情）
            try:
                from src.infrastructure.web import get_web_state_hub
                hub = get_web_state_hub()
                if hub and self.device_id:
                    await hub.broadcast_device_state(self.device_id, True, "idle", emotion)
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"[Pipeline] 发送表情失败: {e}")

    async def _tts_task(self, volc_tts, session):
        """TTS Worker：audio_queue → TTS合成 → send_queue"""
        _perf = self._perf
        _perf["tts_start"] = time.time()
        _tts_chunks = 0
        _tts_bytes = 0
        own_session = session is None
        if own_session:
            try:
                session = await volc_tts.create_session(cancel_event=self.cancel_event, tool_manager=self._tool_manager)
            except Exception as e:
                logger.error(f"[Pipeline] TTS 创建 session 失败: {e}")
                await self.queues.send.put((-1, None, None))
                return
        try:
            while True:
                if self.cancel_event.is_set():
                    await self.queues.send.put((-1, None, None))
                    return

                seq_id, sentence_text, _ = await self.queues.audio.get()

                if self.cancel_event.is_set():
                    self.queues.audio.task_done()
                    await self.queues.send.put((-1, None, None))
                    return

                if seq_id == -1 or sentence_text is None:
                    self.queues.audio.task_done()
                    await self.queues.send.put((-1, None, None))
                    return

                if not sentence_text.strip() or len(sentence_text.strip()) <= 1:
                    self.queues.audio.task_done()
                    continue

                # 过滤 Markdown 格式化符号和内部标记
                sentence_text = self.MARKDOWN_CLEANER.sub(r'\2', sentence_text)
                sentence_text = self.LINE_CLEANER.sub('', sentence_text)
                sentence_text = re.sub(r'\[secret:\d+\]', '', sentence_text)
                sentence_text = sentence_text.replace('\n\n', '\n').replace('  ', ' ').strip()

                sentence_text = self._detect_and_send_emotion(sentence_text)

                logger.info(f"[Pipeline] TTS 合成 #{seq_id}: {sentence_text[:60]}...")

                # 保存原始文本，估算 TTS 时长，立刻发给发送器
                original_text = sentence_text
                tts_duration_ms = 0
                if original_text:
                    cn_chars = sum(1 for c in original_text if '\u4e00' <= c <= '\u9fff')
                    # 标点单独计费，避免被当作英文(90ms/字)重复累加导致估算偏长、字幕滞后
                    punct_chars = sum(1 for c in original_text if c in "，。！？,.!?；;：:、…")
                    en_chars = len(original_text) - cn_chars - punct_chars
                    tts_duration_ms = int(cn_chars * 230 + en_chars * 90)
                    # 标点停顿补偿：TTS 在逗号/句号等处有自然语气停顿，纯字符估算偏短
                    tts_duration_ms += original_text.count("，") * 250
                    tts_duration_ms += original_text.count("。") * 400
                    tts_duration_ms += original_text.count("！") * 400
                    tts_duration_ms += original_text.count("？") * 400
                    tts_duration_ms += original_text.count(",") * 250
                    tts_duration_ms += original_text.count(".") * 300
                    tts_duration_ms += original_text.count("!") * 300
                    tts_duration_ms += original_text.count("?") * 300
                    if tts_duration_ms < 500:
                        tts_duration_ms = 500
                    logger.info(f"[Pipeline] TTS #{seq_id} {len(original_text)}字(中{cn_chars}英{en_chars}), 估 {tts_duration_ms}ms")
                    # 合成前直接发送字幕和估算时长，不等音频帧，避免被音频队列阻塞。
                    # 字幕先到、音频后播；合成完成后会下发该句真实时长（tts_duration）修正。
                    payload = json.dumps({"text": original_text, "duration_ms": tts_duration_ms, "seq": seq_id}, ensure_ascii=False)
                    await self.channel.send_json({"type": "instruct", "command_id": "on_llm_cb", "data": payload})
                total_audio_bytes = 0
                audio_data = bytearray()
                subtitle_end_ms = 0  # 本句字幕末字 end_ms（句内累计），用于时长兜底
                try:
                    async for event in session.synthesize(sentence_text, cancel_event=self.cancel_event):
                        if self.cancel_event.is_set():
                            break
                        if isinstance(event, bytes):
                            # 插件 TTS 网关：直接产出音频字节，无字幕事件
                            audio_chunk = event
                        elif event.kind == "subtitle":
                            # 字级时间戳：换算为绝对流位置（相对整轮播放起点）后下发，
                            # 设备端按实际播放位置直接比对，不受语气快慢/情感停顿影响
                            words = event.data.get("words", [])
                            if words:
                                for w in words:
                                    if w.get("end_ms", 0) > subtitle_end_ms:
                                        subtitle_end_ms = w["end_ms"]
                                base = int(self._cumulative_duration_ms)
                                abs_words = [{
                                    "word": w["word"],
                                    "start_ms": w["start_ms"] + base,
                                    "end_ms": w["end_ms"] + base,
                                } for w in words]
                                await self.channel.send_json({
                                    "type": "instruct",
                                    "command_id": "tts_subtitle",
                                    "data": json.dumps({"seq": seq_id, "words": abs_words}, ensure_ascii=False),
                                })
                                logger.info(f"[Pipeline] TTS #{seq_id} 字幕 {len(abs_words)} 字, 流基准 {base}ms")
                            continue
                        else:
                            audio_chunk = event.data
                        if audio_chunk:
                            total_audio_bytes += len(audio_chunk)
                            audio_data.extend(audio_chunk)
                            _tts_chunks += 1
                            _tts_bytes += len(audio_chunk)
                            frame = self.voice_generator.make_tts_frame(
                                self.config.tts_session_id, audio_chunk, "00"
                            )
                            await self.queues.send.put((seq_id, frame, sentence_text))
                            sentence_text = None
                except asyncio.CancelledError:
                    self.queues.audio.task_done()
                    raise
                except Exception as e:
                    logger.error(f"[Pipeline] TTS 合成 #{seq_id} 异常: {e}")
                    await self.queues.send.put((seq_id, b"", None))

                # TTS 合成完成，解析 MP3 帧头得到该句真实时长；
                # 用字幕末字 endTime 兜底：音频收集不全或 MP3 解析失败时仍能给出准确时长
                actual_ms = mp3_duration_ms(bytes(audio_data)) if audio_data else 0
                if subtitle_end_ms > actual_ms:
                    actual_ms = subtitle_end_ms
                if actual_ms > 0:
                    self._total_duration_ms += actual_ms
                    self._cumulative_duration_ms += actual_ms
                    logger.info(f"[Pipeline] TTS #{seq_id} 实际时长: {tts_duration_ms}ms → {actual_ms}ms, 累计 {self._total_duration_ms}ms")
                    # 下发该句真实时长（带 seq），设备端按 seq 更新对应句子槽
                    await self.channel.send_json({
                        "type": "instruct",
                        "command_id": "tts_duration",
                        "data": json.dumps({"seq": seq_id, "duration_ms": actual_ms}),
                    })
                elif tts_duration_ms > 0:
                    self._total_duration_ms += tts_duration_ms
                    self._cumulative_duration_ms += tts_duration_ms

                self.queues.audio.task_done()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[Pipeline] TTS 任务异常: {e}")
        finally:
            _perf["tts_end"] = time.time()
            _perf["tts_chunks"] = _tts_chunks
            _perf["tts_audio_bytes"] = _tts_bytes
            if own_session and session:
                try:
                    await session.close()
                except Exception as e:
                    logger.debug(f"[Pipeline] 关闭 TTS session 异常: {e}")

    async def _sender_task(self):
        """Sender Worker：send_queue → 发送音频到客户端
        字幕和时长信息已由 _tts_task 直接发送，不再经过此队列。"""
        total_sent = 0
        frame_count = 0
        client_max_buffer = self.config.client_max_buffer
        # 按播放速率(1x)节流发送音频，避免发送超前导致：
        # 1) 客户端缓冲被打满 → 播放卡顿
        # 2) WiFi 半双工下音频抢占语音数据通道
        # 不依赖客户端 client_available_audio 上报（客户端已禁用该上报）。
        send_start_time = None
        sent_audio_ms_total = 0.0
        TARGET_AUDIO_LEAD_MS = 300   # 允许发送超前播放的最大毫秒数
        AUDIO_BITRATE_KBPS = 64      # MP3 发送比特率（与客户端 spk_bitrate=64 一致）

        try:
            while True:
                if self.cancel_event.is_set():
                    return

                item = await self.queues.send.get()
                seq_id, audio, sentence_text = item[0], item[1], item[2]

                if self.cancel_event.is_set():
                    self.queues.send.task_done()
                    return

                if seq_id == -1 or audio is None:
                    logger.info(f"[Pipeline] Sender 结束，{frame_count}帧/{total_sent}B")
                    self.queues.send.task_done()
                    return

                if not audio:
                    self.queues.send.task_done()
                    continue

                try:
                    # 第一帧实际音频数据到达时，发送 play_audio 和 tts_chunk_start
                    if not self._play_audio_sent:
                        self._play_audio_sent = True
                        self._perf["first_audio_sent"] = time.time()
                        await self.channel.send_json({"type": "play_audio", "tts_task_id": self.config.tts_session_id})
                        # 等待客户端处理 play_audio 并上报缓冲区状态，最多 50ms
                        wait_start = time.time()
                        while self._device_buffer >= client_max_buffer and time.time() - wait_start < 0.05:
                            await asyncio.sleep(0.01)
                        await self.channel.send_json({"type": "session_status", "status": "tts_chunk_start"})
                        logger.info(f"[Pipeline] 发送 play_audio + tts_chunk_start，device_buffer={self._device_buffer}")

                    if self.cancel_event.is_set():
                        self.queues.send.task_done()
                        return

                    await self.channel.send_bytes(audio)
                    total_sent += len(audio)
                    frame_count += 1

                    if frame_count % 50 == 0:
                        logger.info(f"[Pipeline] Sender: {frame_count}帧/{total_sent}B")

                except Exception as e:
                    logger.debug(f"[Pipeline] Sender 发送失败: {e}")
                    self.queues.send.task_done()
                    return

                # 流控：按音频播放速率(1x)节流，允许 TARGET_AUDIO_LEAD_MS 超前。
                # 帧时长按 MP3 比特率估算：frame_ms = bytes * 8 / bitrate_kbps
                if send_start_time is None:
                    send_start_time = time.time()
                frame_audio_ms = len(audio) * 8.0 / AUDIO_BITRATE_KBPS
                sent_audio_ms_total += frame_audio_ms
                elapsed_real_ms = (time.time() - send_start_time) * 1000.0
                overrun_ms = sent_audio_ms_total - elapsed_real_ms
                if overrun_ms > TARGET_AUDIO_LEAD_MS:
                    await asyncio.sleep((overrun_ms - TARGET_AUDIO_LEAD_MS) / 1000.0)

                # 兜底：客户端若仍上报 client_available_audio，保留缓冲满保护
                if self._device_buffer < client_max_buffer * 0.1:
                    await asyncio.sleep(0.5)
                elif self._device_buffer < client_max_buffer * 0.3:
                    await asyncio.sleep(0.2)

                self.queues.send.task_done()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[Pipeline] Sender 异常: {e}")

    async def interrupt(self):
        """中断当前流水线"""
        logger.info("[Pipeline] 执行硬中断...")
        self.cancel_event.set()

        self.queues.clear_all()
        self.splitter.reset()

        await self.set_tts_playing(False)
        self.tts_playback_done.set()
        self.tts_audio_ended.set()

        if getattr(self, '_play_audio_sent', False):
            await self.channel.send_bytes(
                self.voice_generator.make_end_frame(self.config.tts_session_id)
            )
            try:
                await self.channel.send_json({"type": "session_status", "status": "tts_real_end"})
            except Exception as e:
                logger.debug(f"[Pipeline] 发送中断结束状态失败: {e}")

        for t in self._tasks:
            if not t.done():
                t.cancel()
        self._tasks.clear()

        logger.info("[Pipeline] 硬中断完成")


def create_pipeline(
    llm_processor,
    tts_processor,
    channel,
    fsm,
    voice_generator: VoiceGenerator = None,
    config: dict = None,
    conversation_memory=None,
    user_config=None,
) -> ConversationPipeline:
    pipeline_config = PipelineConfig(**(config or {}))
    return ConversationPipeline(
        llm_processor=llm_processor,
        tts_processor=tts_processor,
        channel=channel,
        fsm=fsm,
        voice_generator=voice_generator,
        config=pipeline_config,
        conversation_memory=conversation_memory,
        user_config=user_config,
    )


__all__ = [
    "ConversationPipeline",
    "SentenceSplitter",
    "PipelineConfig",
    "PipelineResult",
    "PipelineState",
    "create_pipeline",
]
