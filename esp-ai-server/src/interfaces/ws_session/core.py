"""WS 会话处理器核心：实例状态、设备状态广播与资源清理。"""
from __future__ import annotations

import asyncio

from src.domain.entities import SessionState
from src.infrastructure.config import get_settings
from src.infrastructure.logging import get_logger
from src.infrastructure.monitoring import get_metrics
from src.infrastructure.task_manager import background_task
from src.use_cases.sdk.events import EVENT_SESSION_END, publish

from .asr import AsrMixin
from .growth import GrowthMixin
from .keepalive import KeepaliveMixin
from .messages import MessageLoopMixin
from .setup import SetupMixin
from .tts import TtsMixin
from .wake import WakeMixin
from .wechat import WechatMixin

logger = get_logger(__name__)


class WebSocketSessionHandler(
    SetupMixin,
    AsrMixin,
    TtsMixin,
    WakeMixin,
    GrowthMixin,
    KeepaliveMixin,
    MessageLoopMixin,
    WechatMixin,
):
    """处理单个设备 WebSocket 会话的完整生命周期

    将原 handle_websocket 函数中的闭包与主循环重构为类方法。
    原闭包通过 nonlocal 共享的变量（tts_done_waiter、pipeline_task、
    call_times、_growth_cooldown_task 等）在此通过实例属性访问。

    实现按职责拆分在 ws_session 子包的各个 Mixin 中：
    - setup: 连接初始化（网关/Session/注册）
    - asr: ASR 文本、VAD 结束与下一轮启动
    - tts: TTS 完成回调与流水线等待
    - wake: 唤醒流程与连接问候音频
    - growth: AI 成长任务
    - keepalive: 空闲心跳与待下发指令
    - messages: 设备消息主循环
    - wechat: 微信回复
    """

    def __init__(self, websocket, device_key, device_mac, device_firmware_version, trace_id, device_bin_id="") -> None:
        self.websocket = websocket
        self.device_key = device_key
        self.device_mac = device_mac
        self.device_firmware_version = device_firmware_version
        self.device_bin_id = device_bin_id
        self.trace_id = trace_id
        self.settings = get_settings()

        # 会话状态（在 initialize 中赋值）
        self.client_audio_buffer_size = 10240
        self.spk_sample_rate = 0  # 设备喇叭采样率（连接时从 URL 解析，0=服务端默认）
        self.is_multi_mode = False
        self.user_config = None
        self.channel = None
        self.fsm = None
        self.tool_mgr = None
        self.asr_client = None
        self.llm_processor = None
        self.tts_processor = None
        self.voice_generator = None
        self._ltm_service = None
        self._growth_system = None
        self._growth_cooldown_seconds = 0
        self.session = None
        self._vad_end_lock = asyncio.Lock()  # 防止 on_vad_end 竞态

        # 任务引用（原闭包通过 nonlocal 共享）
        self.call_times = []
        self.tts_done_waiter = None
        self.pipeline_task = None  # 当前 pipeline 任务引用，供 client_out_audio_over 取消
        self.keepalive_task = None
        self._growth_cooldown_task = None  # 冷却定时器
        self._growth_last_messages = []  # 暂存最近消息
        self.connect_audio_task = None
        self.wake_start_task = None
        self._asr_starting = False  # ASR 启动同步标志，防止 _start_asr_session 双重启动竞态
        self._new_wake_pending = False  # 新一轮 start 流程进行中，抑制旧 pipeline 取消后的 _start_next_asr
        # 后台任务引用（防止被 GC 回收导致协程中途取消且无告警；
        # 短生命周期后台任务统一走 task_manager.background_task，由其持有引用并记录异常）
        self._mcp_init_task = None


    def _broadcast_device_state(self, online: bool, state: str = "idle") -> None:
        """推送设备状态到 Web 前端（实时更新设备屏幕图标）"""
        try:
            from src.infrastructure.web import get_web_state_hub
            hub = get_web_state_hub()
            if hub:
                device_id = self.device_mac or self.device_key
                background_task(
                    hub.broadcast_device_state(device_id, online, state),
                    name="broadcast_device_state",
                )
        except Exception:
            pass


    async def cleanup(self) -> None:
        """清理资源 - 取消所有后台任务，关闭会话，注销设备

        对应原 handle_websocket 中 finally 块。
        对各属性做空值检查，保证在 initialize 部分失败时也能安全调用。
        """
        if self.pipeline_task and not self.pipeline_task.done():
            self.pipeline_task.cancel()
        if self.tts_done_waiter and not self.tts_done_waiter.done():
            self.tts_done_waiter.cancel()
        if self.wake_start_task and not self.wake_start_task.done():
            self.wake_start_task.cancel()
        if self.keepalive_task and not self.keepalive_task.done():
            self.keepalive_task.cancel()
        # 清理成长冷却定时器
        if self._growth_cooldown_task and not self._growth_cooldown_task.done():
            self._growth_cooldown_task.cancel()
        # 清理连接音频任务
        if self.connect_audio_task and not self.connect_audio_task.done():
            self.connect_audio_task.cancel()

        # 注销设备注册
        try:
            from src.infrastructure.web import get_device_registry, get_app
            registry = get_device_registry()
            if registry:
                # 传入 self.session 做属主校验：设备断电重连时新会话会先 register 覆盖条目，
                # 旧 handler 迟到的 cleanup 不能注销/杀掉新会话
                await registry.unregister(self.device_key, session=self.session)
        except Exception as e:
            logger.warning(f"[WS] 设备注销失败: {e}")

        # 设备离线 → 推送 Web 前端
        self._broadcast_device_state(False, "idle")

        # 设备会话结束（连接清理）→ 发布事件（publish 内部容错）
        publish(EVENT_SESSION_END, device_key=self.device_key)

        # 设备断连 → 推送微信通知
        try:
            from src.infrastructure.web import get_app
            from src.use_cases.wechat_binding import get_wechat_binding_manager
            bind_mgr = get_wechat_binding_manager()
            binding = bind_mgr.get_by_device_key(self.device_key)
            if binding:
                bot = getattr(get_app().state, 'wechat_bot', None)
                if bot and hasattr(bot, 'send_text'):
                    notify_text = f"⚠️ 设备「{binding.alias or self.device_key[:8]}」已离线，可能原因：网络断开或断电。"
                    # 断连通知为 fire-and-forget，通过 task_manager 包装持有引用，失败记 ERROR 日志
                    background_task(bot.send_text(binding.wechat_chat_id, notify_text), name="wechat_offline_notify")
                    logger.info(f"[WeChat] 已推送设备断连通知到微信")
        except Exception as notify_err:
            logger.debug(f"[WeChat] 推送断连通知失败: {notify_err}")

        # 关闭会话
        if self.session is not None:
            await self.session.close()

        # 业务指标：WebSocket 连接关闭
        try:
            get_metrics().track_ws_connection_closed()
        except Exception:
            pass

        logger.info(f"[WS] Session closed: {self.device_key[:16]}")

        if self.fsm is not None:
            await self.fsm.set(SessionState.IDLE)
        if self.channel is not None:
            await self.channel.close()

