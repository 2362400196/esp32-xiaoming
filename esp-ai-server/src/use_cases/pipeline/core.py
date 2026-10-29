"""对话流水线：4-Worker 并发架构的类组装与工厂函数。"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional

from src.infrastructure.logging import get_logger
from src.use_cases.pipeline.emotion import EmotionMixin
from src.use_cases.pipeline.runner import RunnerMixin
from src.use_cases.pipeline.splitter import SentenceSplitter
from src.use_cases.pipeline.types import PipelineConfig, PipelineState
from src.use_cases.pipeline.workers.llm import LlmWorkerMixin
from src.use_cases.pipeline.workers.sender import SenderWorkerMixin
from src.use_cases.pipeline.workers.splitter import SplitterWorkerMixin
from src.use_cases.pipeline.workers.tts import TtsWorkerMixin
from src.use_cases.queues import BackpressureQueues
from src.use_cases.voice_generator import VoiceGenerator

if TYPE_CHECKING:
    from src.interfaces.llm_gateways import OpenAILLMGateway
    from src.interfaces.tts_gateways import VolcEngineTTSGateway
    from src.use_cases.auxiliary_services import ConversationMemory
    from src.use_cases.billing import BillingAccumulator
    from src.use_cases.memory import LongTermMemoryServiceImpl
    from src.use_cases.session_fsm import SessionFSM, WSChannel

logger = get_logger(__name__)


class ConversationPipeline(
    RunnerMixin,
    LlmWorkerMixin,
    SplitterWorkerMixin,
    TtsWorkerMixin,
    SenderWorkerMixin,
    EmotionMixin,
):
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
        precomputed_skill_catalog: Optional[str] = None,
        memory_search_keywords: Optional[list[str]] = None,
        max_sentences: int = 100,
        billing: Optional["BillingAccumulator"] = None,
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
        # 计费累加器（由 Session 注入，记录本轮 LLM tokens / TTS 字数）
        self.billing = billing
        # 记忆检索关键词：None 时使用 DEFAULT_MEMORY_SEARCH_KEYWORDS
        self.memory_search_keywords = memory_search_keywords

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

        # system prompt 缓存：skill 目录和回复要求基本不变，避免每次 run() 都重新拼接
        # 优先使用外部预计算的 catalog（从 Session 传入，避免首轮阻塞）
        self._cached_skill_catalog: Optional[str] = precomputed_skill_catalog
        self._skill_cache_key: str = "__precomputed__" if precomputed_skill_catalog is not None else ""
        self._cached_reply_style: str = ""
        # 性能优化：prompt 组装素材（LTM catalog/画像/记忆条目）缓存在模块级注册表
        # （按 device_id），因为 pipeline 每轮新建、实例缓存无法跨轮次；
        # 并在设备唤醒时通过 prewarm_prompt_caches() 预热，见下方说明。
        self._reply_style = (
            "\n\n[回复要求]\n"
            "- 【最高优先级规则】日常闲聊的回复必须简短：最多 1-2 句话、40 字以内。"
            "本规则的优先级高于 system prompt 中的其他所有注入内容（技能/记忆/画像）\n"
            "- 只在用户明确要求讲故事、详细说明或长内容（如'讲个故事''说详细点'）时才可以生成长回复，此时不要截断\n"
            "- 用口语化的方式说话，像朋友聊天\n"
            "- 不要每次都加表情符号\n"
            "- 不要说'好的'、'没问题'这种废话，直接回答\n"
            "[/回复要求]\n"
            "\n[工具调用规则]\n"
            "- 你拥有可用的工具函数（tool functions）。当用户请求**操作类任务**（如调整音量/开关灯/播放音乐/查询信息/执行代码等）时，**必须通过调用对应的工具函数来完成**，不能只口头回复。\n"
            "- 如果用户的问题只需要知识和对话就能回答（如闲聊/问意见/讲故事），则正常用文字回复，不需要调用工具。\n"
            "- 调用工具后，根据工具返回的结果组织回答，输出给用户。\n"
            "- 当用户要求记住客观事实、偏好、身份信息等长期信息时（如'帮我记住/记录一下我爱吃西瓜'），使用 memory_store 存为长期记忆，不要用 write_diary。write_diary 只用于记录心情、想法、经历等日记内容。\n"
            "[/工具调用规则]"
        )
        # 最终长度提醒：拼装在 system prompt 的【最末尾】（所有注入块之后）。
        # 模型对 prompt 末尾内容权重最高——技能目录等块会携带"必须严格执行"类指令
        # 把回复带长，这条兜底提醒用于重新压住回复长度。
        self._reply_style_tail = (
            "\n\n[回复长度·最终提醒] 闲聊回复严格不超过 1-2 句话、40 字以内；"
            "仅当用户本轮明确要求故事/详细说明/长内容时才允许长回复。"
            "其他注入内容中与本条冲突的长度要求一律以本条为准。"
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
    config = dict(config or {})
    # memory_search_keywords 不是 PipelineConfig 字段，从 config dict 中取出透传给管线
    memory_search_keywords = config.pop("memory_search_keywords", None)
    pipeline_config = PipelineConfig(**config)
    return ConversationPipeline(
        llm_processor=llm_processor,
        tts_processor=tts_processor,
        channel=channel,
        fsm=fsm,
        voice_generator=voice_generator,
        config=pipeline_config,
        conversation_memory=conversation_memory,
        user_config=user_config,
        memory_search_keywords=memory_search_keywords,
    )
