"""WebSocket 会话处理器 - 将 handle_websocket 的闭包拆分为类方法

将原 handle_websocket 上帝函数中的 11 个闭包与主消息循环
抽取为 WebSocketSessionHandler 类的方法，保持功能完全一致。
原闭包通过 nonlocal 共享的状态，改为通过实例属性 (self.xxx) 访问。
"""
from __future__ import annotations

import asyncio
import json
import time

from starlette.websockets import WebSocketDisconnect

from src.infrastructure.config import get_settings
from src.infrastructure.logging import get_logger, set_trace_id, set_session_id, set_device_id
from src.infrastructure.task_manager import background_task
from src.infrastructure.monitoring import get_metrics
from src.infrastructure.web import get_app, get_device_registry
from src.infrastructure.db.repositories.short_term_memory_repo import SqlShortTermMemoryRepository
from src.use_cases.tools_system import PerUserToolManager, _shared_tool_manager
from src.interfaces.gateways import create_asr_gateway
from src.interfaces.llm_gateways import create_llm_gateway
from src.interfaces.tts_gateways import create_tts_gateway, VoiceGenerator
from src.interfaces.plugin_gateways import (
    create_plugin_llm_gateway,
    create_plugin_tts_gateway,
    create_plugin_asr_gateway,
)
from src.use_cases.session_fsm import WSChannel, SessionFSM
from src.domain.entities import SessionState
from src.use_cases.session import Session, AUDIO_QUEUE_MAX_SIZE

logger = get_logger(__name__)


def _get_wake_enable_audio(settings, user_config=None) -> bool:
    """读取设备级 enable_audio，回退全局"""
    default = settings.wakeup.enable_audio
    if user_config and hasattr(user_config, 'wakeup_config') and user_config.wakeup_config:
        val = user_config.wakeup_config.get('enable_audio')
        if val is not None:
            return val
    return default


def _log_perf_report(session, result, pipeline, asr_text: str) -> None:
    """打印一轮对话的性能分析报告到终端（调试用）"""
    try:
        now = time.time()
        rt = session.runtime

        asr_ms = None
        if rt.asr_start_time and rt.asr_last_result_time:
            asr_ms = (rt.asr_last_result_time - rt.asr_start_time) * 1000

        perf = getattr(pipeline, "_perf", {}) if pipeline else {}

        # 首响延迟 = ASR 识别完成 → 第一段回复音频发送到设备（真正的响应性能）
        resp_ms = None
        first_audio_sent = perf.get("first_audio_sent")
        if first_audio_sent and rt.asr_last_result_time:
            resp_ms = (first_audio_sent - rt.asr_last_result_time) * 1000

        llm_ms = llm_ttft_ms = None
        if perf.get("llm_start") and perf.get("llm_end"):
            llm_ms = (perf["llm_end"] - perf["llm_start"]) * 1000
            if perf.get("llm_first_token"):
                llm_ttft_ms = (perf["llm_first_token"] - perf["llm_start"]) * 1000

        tts_ms = None
        if perf.get("tts_start") and perf.get("tts_end"):
            tts_ms = (perf["tts_end"] - perf["tts_start"]) * 1000

        pipeline_ms = (result.duration * 1000) if result else None
        audio_ms = (result.total_duration_ms) if result else 0
        full_text = (result.full_text or "") if result else ""

        e2e_ms = None
        if rt.asr_start_time:
            e2e_ms = (now - rt.asr_start_time) * 1000

        def _fmt(ms):
            return f"{ms:.0f}ms" if ms is not None else "n/a"

        lines = [
            "═" * 64,
            f"[Perf] 对话性能报告  session={session.session_id}  device={session.device_id[:16]}"
            + ("  ⚠️ 本轮被中断（无完整 result，部分指标缺失）" if result is None else ""),
            f"  用户输入 : \"{asr_text[:40]}\"",
        ]
        if asr_ms is not None:
            lines.append(f"  ASR 识别 : {_fmt(asr_ms)}")
        lines.append(
            f"  LLM 生成 : {_fmt(llm_ms)}   (首token {_fmt(llm_ttft_ms)}, "
            f"输出 {perf.get('llm_chars', 0)}字/{perf.get('llm_sentences', 0)}句)"
        )
        lines.append(
            f"  TTS 合成 : {_fmt(tts_ms)}   ({perf.get('tts_chunks', 0)}块, 共{audio_ms:.0f}ms音频)"
        )
        if resp_ms is not None:
            lines.append(f"  首响延迟 : {_fmt(resp_ms)}   (ASR完成→首帧音频)")
        if perf.get("prompt_assembly_ms") is not None:
            lines.append(
                f"  Prompt组装: {_fmt(perf.get('prompt_assembly_ms'))}  "
                f"(system {perf.get('prompt_chars', 0)}字/含历史 {perf.get('history_chars', 0)}字)"
            )
        lines.append(f"  Pipeline : {_fmt(pipeline_ms)}   (总耗时)")
        if e2e_ms is not None:
            lines.append(f"  端到端   : {_fmt(e2e_ms)}   (ASR开始→播放完成)")
        lines.append(f"  回复     : \"{full_text[:60]}\"")
        lines.append("═" * 64)
        logger.info("\n" + "\n".join(lines))
    except Exception as e:
        logger.debug(f"[Perf] 报告生成失败: {e}")


class WebSocketSessionHandler:
    """处理单个设备 WebSocket 会话的完整生命周期

    将原 handle_websocket 函数中的闭包与主循环重构为类方法。
    原闭包通过 nonlocal 共享的变量（tts_done_waiter、pipeline_task、
    call_times、_growth_cooldown_task 等）在此通过实例属性访问。
    """

    def __init__(self, websocket, device_key, device_mac, device_firmware_version, trace_id) -> None:
        self.websocket = websocket
        self.device_key = device_key
        self.device_mac = device_mac
        self.device_firmware_version = device_firmware_version
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

    async def initialize(self) -> None:
        """初始化会话：接收连接、创建网关、Session、启动后台任务

        对应原 handle_websocket 中 websocket.accept() 之后到主循环之前的全部逻辑。
        """
        settings = self.settings
        websocket = self.websocket
        device_key = self.device_key
        device_mac = self.device_mac
        device_firmware_version = self.device_firmware_version
        trace_id = self.trace_id

        # 将 trace_id / device_id 写入 contextvar，确保本会话所有日志都携带这些字段。
        # 必须在第一条日志之前设置（下方的 accept 日志即依赖之）。
        try:
            set_trace_id(trace_id)
        except Exception:
            pass
        try:
            set_device_id(device_mac or device_key)
        except Exception:
            pass
        # 业务指标：WebSocket 连接打开
        try:
            get_metrics().track_ws_connection_opened()
        except Exception:
            pass

        is_multi_mode = settings.deploy_mode == "multi"
        self.is_multi_mode = is_multi_mode
        user_config = self.user_config

        await websocket.accept()
        logger.info(f"[WS] Connection accepted for device: {device_key[:16]}")

        channel = WSChannel()
        fsm = SessionFSM(on_change=lambda s: self._broadcast_device_state(True, s.value))
        channel.bind(websocket)
        self.channel = channel
        self.fsm = fsm

        shared_tool_mgr = getattr(get_app().state, 'shared_tool_manager', _shared_tool_manager)
        shared_tool_mgr.ensure_discovered()
        tool_mgr = PerUserToolManager(shared=shared_tool_mgr, channel=channel, device_id=device_mac)
        tool_mgr.user_config = user_config
        self.tool_mgr = tool_mgr

        if user_config:
            if getattr(user_config, "disabled_tools", None):
                tool_mgr._disabled_tools = set(user_config.disabled_tools)
            # 设备级插件白名单：None/空 = 无限制（插件全部启用），非空 = 仅白名单内生效
            if getattr(user_config, "enabled_plugins", None):
                tool_mgr._enabled_plugins = set(user_config.enabled_plugins)
                logger.info(f"[WS] 设备插件白名单: {sorted(tool_mgr._enabled_plugins)}")
            else:
                logger.info("[WS] 设备插件白名单: 无限制（所有插件启用）")
            # 设备级插件配置（天气 Key 等）
            if getattr(user_config, "plugin_configs", None):
                tool_mgr.plugin_configs = dict(user_config.plugin_configs)
                logger.info(f"[WS] 设备插件配置: {list(tool_mgr.plugin_configs.keys())}")
            # 设备能力：优先固件 URL 上报（has_display=0/1），其次设备配置 has_display；
            # 均缺失时默认有屏（向后兼容，不隐藏任何工具）
            reported = getattr(self, "reported_has_display", None)
            if reported is not None:
                tool_mgr.device_has_display = reported
            elif getattr(user_config, "has_display", None) is not None:
                tool_mgr.device_has_display = bool(user_config.has_display)
            logger.info(f"[WS] 设备屏幕能力: has_display={tool_mgr.device_has_display}")
            if getattr(user_config, "skills", None):
                tool_mgr.active_skills = set(user_config.skills)

        # 设备连接/重连时同步显示配置（机器人模式/屏保）。
        # 若设备在离线期间被改过这些配置，指令无法下发，重连后需按服务端 DB 状态重新同步，
        # 否则设备会一直停留在旧的机器人模式状态。
        if user_config:
            display_sync = {
                "robot_mode": "true" if str(getattr(user_config, "robot_mode", "false")) in ("true", "1") else "false",
                "screensaver_enabled": "true" if str(getattr(user_config, "screensaver_enabled", "true")) in ("true", "1") else "false",
                "screensaver_timeout": str(getattr(user_config, "screensaver_timeout", "30") or "30"),
            }
            try:
                from src.use_cases.sdk.device import send_device_command
                await send_device_command(tool_mgr, "update_config", display_sync)
                logger.info(f"[WS] 已同步显示配置到设备: {display_sync}")
            except Exception as e:
                logger.warning(f"[WS] 同步显示配置失败: {e}")

        user_mcp_servers = user_config.mcp_servers if user_config and user_config.mcp_servers else None
        _disabled_mcp_servers = getattr(user_config, 'disabled_mcp_servers', None) if user_config else None
        _disabled_mcp_tools = getattr(user_config, 'disabled_mcp_tools', None) if user_config else None

        # 调试日志：检查配置加载
        logger.info(f"[WS] MCP config: servers={list(user_mcp_servers.keys()) if user_mcp_servers else None}, disabled_servers={_disabled_mcp_servers}, disabled_tools={_disabled_mcp_tools}")

        startup_tool_mgr = getattr(get_app().state, 'tool_manager', None)
        if user_mcp_servers:
            # 后台初始化 MCP，避免阻塞事件循环导致设备 HTTP 请求超时
            self._mcp_init_task = background_task(
                tool_mgr.initialize_mcp(user_mcp_servers, disabled_servers=_disabled_mcp_servers, disabled_tools=_disabled_mcp_tools),
                name="mcp_init",
            )
        elif startup_tool_mgr and startup_tool_mgr._mcp_tool_map:
            tool_mgr._mcp_clients = startup_tool_mgr._mcp_clients
            tool_mgr._mcp_pools = startup_tool_mgr._mcp_pools
            tool_mgr._circuit_breakers = startup_tool_mgr._circuit_breakers
            # 过滤禁用的服务器和工具
            _ds = set(_disabled_mcp_servers or [])
            _dt = _disabled_mcp_tools or {}
            schemas = {}
            tool_map = {}
            for sname, slist in startup_tool_mgr._mcp_tool_schemas.items():
                if sname in _ds:
                    continue
                server_disabled = set(_dt.get(sname, []) or [])
                filtered = [s for s in slist if s["function"]["name"] not in server_disabled]
                schemas[sname] = filtered
            for fname, val in startup_tool_mgr._mcp_tool_map.items():
                if isinstance(val, tuple):
                    sname = val[0]
                    if sname not in _ds and fname not in set(_dt.get(sname, []) or []):
                        tool_map[fname] = val
                else:
                    tool_map[fname] = val
            tool_mgr._mcp_tool_schemas = schemas
            tool_mgr._mcp_tool_map = tool_map
            logger.info(f"[WS] Reusing pre-connected MCP clients ({len(tool_mgr._mcp_tool_map)} tools, filtered)")
        else:
            mcp_cfg = getattr(settings, 'mcp', None)
            if mcp_cfg:
                servers = mcp_cfg.get_servers() if hasattr(mcp_cfg, 'get_servers') else {}
                if servers:
                    # 后台初始化 MCP，避免阻塞事件循环
                    background_task(tool_mgr.initialize_mcp(servers), name="mcp_init")

        asr_client = None
        try:
            # 优先尝试 ASR 服务插件
            asr_plugin_config = {}
            if is_multi_mode and user_config and user_config.asr_provider:
                user_asr_cfg = user_config.get_asr_config(user_config.asr_provider) or {}
                asr_plugin_config = {
                    "api_key": user_asr_cfg.get("api_key", ""),
                    "resource_id": user_asr_cfg.get("resource_id", "volc.bigasr.sauc.duration"),
                    "model": user_asr_cfg.get("model_name", "bigmodel"),
                    "app_id": user_asr_cfg.get("app_id", ""),
                }
            else:
                asr_plugin_config = {
                    "api_key": settings.asr.volcengine_api_key,
                    "resource_id": settings.asr.volcengine_resource_id,
                    "model": settings.asr.volcengine_model,
                }
            asr_client = create_plugin_asr_gateway(config=asr_plugin_config)
            if asr_client is None:
                # 回退到传统网关
                if is_multi_mode and user_config and user_config.asr_provider:
                    asr_provider = user_config.asr_provider
                    user_asr_cfg = user_config.get_asr_config(asr_provider) or {}
                    asr_config = {
                        "provider": asr_provider,
                        "api_key": user_asr_cfg.get("api_key", ""),
                        "resource_id": user_asr_cfg.get("resource_id", "volc.bigasr.sauc.duration"),
                        "model_name": user_asr_cfg.get("model_name", "bigmodel"),
                        "app_id": user_asr_cfg.get("app_id", ""),
                        "secret_id": user_asr_cfg.get("secret_id", ""),
                        "secret_key": user_asr_cfg.get("secret_key", ""),
                        "engine_model_type": user_asr_cfg.get("engine_model_type", "16k_zh"),
                        "enable_pool": user_asr_cfg.get("enable_pool", settings.asr.enable_pool),
                        "no_speech_timeout": user_asr_cfg.get("no_speech_timeout"),
                        "silence_timeout": user_asr_cfg.get("silence_timeout"),
                        "max_concurrency": user_asr_cfg.get("max_concurrency"),
                        "pool_max_size": user_asr_cfg.get("pool_max_size"),
                        "pool_min_size": user_asr_cfg.get("pool_min_size"),
                        "pool_heartbeat_interval": user_asr_cfg.get("pool_heartbeat_interval"),
                        "pool_idle_timeout": user_asr_cfg.get("pool_idle_timeout"),
                        "pool_connection_timeout": user_asr_cfg.get("pool_connection_timeout"),
                    }
                else:
                    asr_config = {
                        "provider": settings.asr.provider,
                        "app_id": settings.asr.tencent_app_id,
                        "secret_id": settings.asr.tencent_secret_id,
                        "secret_key": settings.asr.tencent_secret_key,
                        "engine_model_type": settings.asr.tencent_engine,
                        "api_key": settings.asr.volcengine_api_key,
                        "resource_id": settings.asr.volcengine_resource_id,
                        "model_name": settings.asr.volcengine_model,
                        "enable_pool": settings.asr.enable_pool,
                    }
                asr_client = create_asr_gateway(provider=asr_config["provider"], config=asr_config)
                logger.info(f"[WS] ASR client created (mode={'multi' if is_multi_mode else 'single'})")
            else:
                logger.info("[WS] 使用 ASR 插件网关")
        except Exception as e:
            logger.warning(f"[WS] ASR client initialization failed: {e}")
        if asr_client and getattr(asr_client, 'is_plugin', False):
            asr_client.set_tool_manager(tool_mgr)
        self.asr_client = asr_client

        llm_processor = None
        try:
            # 优先尝试 LLM 服务插件
            llm_plugin_config = {}
            if is_multi_mode and user_config and user_config.llm_api_key:
                llm_plugin_config = {
                    "api_key": user_config.llm_api_key,
                    "base_url": user_config.llm_base_url or "",
                    "model": user_config.llm_model or "",
                    "system_prompt": user_config.llm_system_prompt or "",
                }
            else:
                llm_plugin_config = {
                    "api_key": settings.llm.api_key,
                    "base_url": settings.llm.base_url,
                    "model": settings.llm.model,
                    "system_prompt": settings.llm.system_prompt,
                }
            llm_processor = create_plugin_llm_gateway(config=llm_plugin_config, tool_manager=tool_mgr)
            if llm_processor is None:
                # 回退到传统网关
                if is_multi_mode and user_config and user_config.llm_api_key:
                    llm_config = {
                        "api_key": user_config.llm_api_key,
                        "base_url": user_config.llm_base_url or "",
                        "model": user_config.llm_model or "",
                        "system_prompt": user_config.llm_system_prompt or "",
                    }
                    logger.info(f"[WS] LLM using user_config: api_key={'***' + llm_config['api_key'][-4:] if llm_config['api_key'] else 'EMPTY'}, model={llm_config['model']}")
                else:
                    llm_config = {
                        "api_key": settings.llm.api_key,
                        "base_url": settings.llm.base_url,
                        "model": settings.llm.model,
                        "system_prompt": settings.llm.system_prompt,
                    }
                    logger.info(f"[WS] LLM using global settings: api_key={'***' + llm_config['api_key'][-4:] if llm_config['api_key'] else 'EMPTY'}")
                llm_processor = create_llm_gateway(config=llm_config, tool_manager=tool_mgr)
            else:
                logger.info("[WS] 使用 LLM 插件网关")
        except Exception as e:
            logger.warning(f"[WS] LLM processor initialization failed: {e}")
            llm_processor = None
        self.llm_processor = llm_processor

        tts_processor = None
        try:
            # 优先尝试 TTS 服务插件
            tts_plugin_config = {}
            if is_multi_mode and user_config and user_config.tts_config:
                user_tts_cfg = user_config.tts_config
                tts_plugin_config = {
                    "api_key": user_tts_cfg.get("api_key", ""),
                    "resource_id": user_tts_cfg.get("resource_id", ""),
                    "voice_type": user_tts_cfg.get("voice_type", ""),
                    "sample_rate": self.spk_sample_rate or settings.tts.sample_rate or 24000,
                    "speed_ratio": user_tts_cfg.get("speed_ratio", 1.0),
                    "volume_ratio": user_tts_cfg.get("volume_ratio", 1.0),
                    "pitch_ratio": user_tts_cfg.get("pitch_ratio", 1.0),
                }
            else:
                tts_plugin_config = {
                    "api_key": settings.tts.api_key,
                    "resource_id": settings.tts.resource_id or "",
                    "voice_type": settings.tts.voice_type or "BV001_streaming",
                    "sample_rate": self.spk_sample_rate or settings.tts.sample_rate or 24000,
                    "speed_ratio": settings.tts.speed_ratio or 1.0,
                    "volume_ratio": settings.tts.volume_ratio or 1.0,
                    "pitch_ratio": settings.tts.pitch_ratio or 1.0,
                }
            tts_processor = create_plugin_tts_gateway(config=tts_plugin_config)
            if tts_processor is None:
                # 回退到传统网关
                if is_multi_mode and user_config and user_config.tts_config:
                    user_tts_cfg = user_config.tts_config
                    tts_config = {
                        "api_key": user_tts_cfg.get("api_key", ""),
                        "resource_id": user_tts_cfg.get("resource_id", ""),
                        "voice_type": user_tts_cfg.get("voice_type", ""),
                        "sample_rate": self.spk_sample_rate or settings.tts.sample_rate or 24000,
                        "speed_ratio": user_tts_cfg.get("speed_ratio", 1.0),
                        "volume_ratio": user_tts_cfg.get("volume_ratio", 1.0),
                        "pitch_ratio": user_tts_cfg.get("pitch_ratio", 1.0),
                        "explicit_dialect": user_tts_cfg.get("explicit_dialect", ""),
                        "enable_pool": user_tts_cfg.get("enable_pool", settings.tts.enable_pool),
                        # 设备级 TTS 连接池参数（回退全局）
                        "pool_max_size": user_tts_cfg.get("pool_max_size"),
                        "pool_min_size": user_tts_cfg.get("pool_min_size"),
                        "pool_heartbeat_interval": user_tts_cfg.get("pool_heartbeat_interval"),
                        "pool_idle_timeout": user_tts_cfg.get("pool_idle_timeout"),
                        "pool_connection_timeout": user_tts_cfg.get("pool_connection_timeout"),
                    }
                else:
                    tts_config = {
                        "api_key": settings.tts.api_key,
                        "resource_id": settings.tts.resource_id or "",
                        "voice_type": settings.tts.voice_type or "BV001_streaming",
                        "sample_rate": self.spk_sample_rate or settings.tts.sample_rate or 24000,
                        "speed_ratio": settings.tts.speed_ratio or 1.0,
                        "volume_ratio": settings.tts.volume_ratio or 1.0,
                        "pitch_ratio": settings.tts.pitch_ratio or 1.0,
                        "explicit_dialect": settings.tts.explicit_dialect or "",
                        "enable_pool": settings.tts.enable_pool,
                    }
                tts_processor = create_tts_gateway(config=tts_config)
            else:
                logger.info("[WS] 使用 TTS 插件网关")
        except Exception as e:
            logger.warning(f"[WS] TTS processor initialization failed: {e}")
            tts_processor = None
        self.tts_processor = tts_processor

        voice_generator = VoiceGenerator()
        self.voice_generator = voice_generator

        # 性能优化：将 LTM 服务、Growth 系统、Skill catalog 预渲染三个独立任务并行化
        # 这三个任务之间没有依赖关系，串行执行耗时 ~100-200ms，并行后 ~50-80ms

        async def _init_ltm_service():
            _ltm = None
            try:
                from src.infrastructure.db.repositories.ltm_repository import SqlLongTermMemoryRepository
                from src.use_cases.memory import LongTermMemoryServiceImpl
                _ltm_repo = SqlLongTermMemoryRepository()
                _ltm = LongTermMemoryServiceImpl(repository=_ltm_repo)
            except Exception as e:
                logger.debug(f"[WS] 长期记忆服务初始化失败: {e}")
            return _ltm

        async def _init_growth_system(ltm_svc):
            _growth = None
            try:
                from src.use_cases.growth import GrowthSystem
                _growth = GrowthSystem(
                    data_dir="src/data",
                    llm_call_func=self._llm_call_for_growth,
                    memory_service=ltm_svc,
                )
                logger.info(f"[WS] Growth system initialized for device: {device_key[:16]}, cooldown={self._growth_cooldown_seconds}s")
            except Exception as e:
                logger.warning(f"[WS] Growth system initialization failed: {e}")
            return _growth

        def _precompute_skill_catalog():
            try:
                from src.use_cases import skill_system
                _skills = getattr(user_config, 'skills', None) if user_config else None
                _disabled = getattr(user_config, 'disabled_skills', None) if user_config else None
                return skill_system.render_skills_catalog(
                    device_id=device_key,
                    skills=_skills,
                    disabled_skills=_disabled,
                )
            except Exception as e:
                logger.debug(f"[WS] Skill catalog pre-render failed: {e}")
                return ""

        # ── 组合根：创建AI成长系统 ────────────────────────
        self._growth_cooldown_seconds = settings.growth_cooldown_seconds  # 从配置读取冷却时间

        # 并行执行：LTM 服务初始化 + Skill catalog 预渲染
        # 使用 asyncio.gather 而非 create_task，便于测试 mock
        _ltm_service, _precomputed_skill_catalog = await asyncio.gather(
            _init_ltm_service(),
            asyncio.to_thread(_precompute_skill_catalog),
        )
        self._ltm_service = _ltm_service
        tool_mgr.ltm_service = _ltm_service

        # Growth 系统依赖 LTM 服务，在 LTM 完成后启动
        self._growth_system = await _init_growth_system(_ltm_service)

        _settings = get_settings()
        # 无人说话超时：设备级 asr_config 优先，回退全局
        _no_speech_timeout = _settings.asr.no_speech_timeout
        _silence_timeout = _settings.asr.silence_timeout
        if is_multi_mode and user_config and user_config.asr_provider:
            _uasr = user_config.get_asr_config(user_config.asr_provider) or {}
            if _uasr.get("no_speech_timeout") is not None:
                _no_speech_timeout = _uasr["no_speech_timeout"]
            if _uasr.get("silence_timeout") is not None:
                _silence_timeout = _uasr["silence_timeout"]
        session = Session(
            device_id=device_key,
            ltm_service=_ltm_service,
            channel=channel,
            fsm=fsm,
            voice_generator=voice_generator,
            llm_processor=llm_processor,
            tts_processor=tts_processor,
            asr_client=asr_client,
            tool_mgr=tool_mgr,
            user_config=user_config,
            client_max_buffer=self.client_audio_buffer_size,
            no_speech_timeout=_no_speech_timeout,
            silence_timeout=_silence_timeout,
            memory_repository=SqlShortTermMemoryRepository(),
        )

        session.trace_id = trace_id
        self.session = session

        # 将 session_id 写入 contextvar，使后续日志（含 Pipeline/ASR/LLM/TTS）携带 session_id
        try:
            set_session_id(session.session_id)
        except Exception:
            pass

        # 预渲染 skill catalog（已在上面并行任务中完成，直接使用结果）
        if _precomputed_skill_catalog:
            session._precomputed_skill_catalog = _precomputed_skill_catalog
            logger.info(f"[WS] Skill catalog pre-rendered ({len(_precomputed_skill_catalog)} chars)")

        registry = get_device_registry()
        if registry:
            mac_addr = device_mac
            await registry.register(
                device_key, channel, session, fsm,
                user_config=user_config,
                asr_client=asr_client,
                tool_manager=tool_mgr,
                mac=mac_addr,
                firmware_version=device_firmware_version,
            )

        # 设备上线 → 推送 Web 前端
        self._broadcast_device_state(True, "idle")

        if asr_client:
            background_task(session.pre_connect_asr(), name="pre_connect_asr")

        # 预热唤醒音频缓存，避免首次唤醒时 585ms TTS 合成延迟
        if _get_wake_enable_audio(settings, user_config):
            wam = getattr(get_app().state, 'wake_audio_manager', None)
            if wam:
                background_task(wam.ensure_cache(user_config=user_config), name="wake_audio_cache")

        # 启动空闲保活任务
        self.keepalive_task = background_task(self.idle_keepalive(), name="idle_keepalive")

        await channel.send_json({"type": "play_audio_ws_conntceed"})
        logger.info(f"[WS] Sent play_audio_ws_conntceed, waiting for device response...")

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

    def on_asr_text(self, text: str) -> None:
        """ASR 文本回调"""
        # 注意：空文本（ASR 流结束/静音帧）不覆盖已有识别结果！
        # 否则用户说完话后 ASR 收到结束帧回调空串，把"现在音量多少"覆盖成空，
        # VAD 结束时 final text 为空 → 识别成功却无任何回复（实测 bug）。
        if text:
            self.session.runtime.asr_full_text = text
            self.session.runtime.asr_last_result_time = time.time()
            # 实时下发 ASR 中间结果，屏幕边听边显示（VAD 结束后不再发，避免覆盖 LLM 字幕）
            if not self.session.runtime.asr_processed:
                try:
                    background_task(self._send_iat_partial(text), name="send_iat_partial")
                except RuntimeError:
                    pass

    async def _send_iat_partial(self, text: str) -> None:
        try:
            await self.channel.send_json({"type": "instruct", "command_id": "on_iat_cb", "data": text})
        except Exception as e:
            logger.debug(f"[VAD] 发送 ASR 中间结果失败: {e}")

    async def on_vad_end(self) -> None:
        """VAD 结束回调"""
        session = self.session
        channel = self.channel
        fsm = self.fsm
        settings = self.settings
        user_config = self.user_config

        async with self._vad_end_lock:
            if session.runtime.asr_processed:
                return
            session.runtime.asr_processed = True

        if self.tts_done_waiter and not self.tts_done_waiter.done():
            self.tts_done_waiter.cancel()
            self.tts_done_waiter = None

        try:
            await channel.send_json({"type": "session_status", "status": "iat_end"})
        except Exception as e:
            logger.warning(f"[VAD] Send iat_end failed: {e}")
            return

        await asyncio.sleep(0.03)
        text = session.runtime.asr_full_text
        logger.info(f"[VAD] ASR final text: {text}")

        await session.drain_asr()
        if not text.strip():
            await session.send_session_end()
            return

        rate_limit = user_config.rate_limit_rpm if user_config and user_config.rate_limit_rpm is not None else settings.rate_limit.max_rpm
        if rate_limit > 0:
            now = time.time()
            self.call_times = [t for t in self.call_times if now - t < 60]
            if len(self.call_times) >= rate_limit:
                logger.warning(f"[RateLimit] Device exceeded {rate_limit} calls/minute")
                await session.send_session_end()
                return
            self.call_times.append(now)

        try:
            await channel.send_json({"type": "instruct", "command_id": "on_iat_cb", "data": text})
            await asyncio.sleep(0.03)
        except Exception as e:
            logger.warning(f"[VAD] Send instruct failed: {e}")
            return

        session.tts_playback_done.clear()
        self.pipeline_task = background_task(session.run_pipeline(text), name="run_pipeline")
        self.tts_done_waiter = background_task(self._on_tts_complete(), name="tts_complete_waiter")

    def _trigger_growth(self) -> None:
        """触发成长任务（冷却期后执行）"""
        session = self.session
        if not self._growth_system or not session.conversation_memory or not session.conversation_memory.messages:
            return

        self._growth_last_messages = list(session.conversation_memory.messages)

        # 取消之前的冷却定时器
        if self._growth_cooldown_task and not self._growth_cooldown_task.done():
            self._growth_cooldown_task.cancel()

        # 启动新的冷却定时器
        self._growth_cooldown_task = background_task(
            self._growth_cooldown_timer(self.device_key, self._growth_last_messages),
            name="growth_cooldown",
        )
        logger.info(f"[Growth] 已启动成长任务冷却定时器（{self._growth_cooldown_seconds}秒）: {self.device_key[:16]}")

    async def _on_tts_complete(self) -> None:
        """TTS 完成回调"""
        session = self.session
        fsm = self.fsm
        try:
            logger.info(f"[Session:{session.session_id}] Waiting for pipeline to complete...")
            # 动态 pipeline 超时：TTS 合成期间持续产出音频，超时随合成进度延长。
            # 基础 30s + 已合成音频时长×1.5 + 15s 余量，
            # 避免长故事/长回答（LLM 10s + 串行 TTS 合成 + 音频按播放速率发送）被 30s 硬超时误杀。
            _pipeline = session._current_pipeline
            _deadline = time.time() + 30.0
            result = None
            try:
                while True:
                    _remaining = _deadline - time.time()
                    if _remaining <= 0:
                        logger.warning(f"[Session:{session.session_id}] Pipeline timeout, cancelling and moving on")
                        self.pipeline_task.cancel()
                        try:
                            await self.pipeline_task
                        except asyncio.CancelledError:
                            pass
                        except Exception as e:
                            logger.debug(f"[Session:{session.session_id}] Pipeline cancel cleanup error: {e}")
                        result = None
                        break
                    try:
                        # shield 防止 wait_for 超时误取消 pipeline_task（外部 cancel 仍会传播）
                        result = await asyncio.wait_for(
                            asyncio.shield(self.pipeline_task), timeout=min(_remaining, 1.0)
                        )
                        break
                    except asyncio.TimeoutError:
                        # 每 5s 检查一次：若 TTS 仍在产出音频，按已合成时长延长 deadline
                        _est_audio_s = 0.0
                        if _pipeline is not None:
                            _est_audio_s = getattr(_pipeline, "_total_duration_ms", 0) / 1000.0
                        if _est_audio_s > 0:
                            _new_deadline = time.time() + max(30.0, _est_audio_s * 1.5 + 15.0)
                            if _new_deadline > _deadline:
                                _deadline = _new_deadline
            except asyncio.CancelledError:
                # pipeline 被外部取消（如 client_out_audio_over 或新 start 命令）
                logger.info(f"[Session:{session.session_id}] Pipeline cancelled externally")
                result = None

            stop_pipeline = getattr(result, 'stop_pipeline', False) if result else False

            if stop_pipeline:
                logger.info(f"[Session:{session.session_id}] Pipeline 被 StopPipeline 终止，工具已接管，不启动下一轮 ASR")
                self._trigger_growth()
                await fsm.set(SessionState.IDLE)
                session.tts_playback_done.set()
                return

            # 获取音频总时长（毫秒）
            total_duration_ms = getattr(result, 'total_duration_ms', 0) if result else 0
            audio_duration_s = total_duration_ms / 1000.0

            # 如果 Pipeline 被取消或未产生任何音频，跳过 TTS 播放等待（设备不会回 client_out_audio_over）
            if not result or total_duration_ms == 0:
                logger.info(f"[Session:{session.session_id}] Pipeline 无音频输出 (cancelled={result is None}), 跳过 TTS 播放等待")
                _log_perf_report(session, result, _pipeline, session.runtime.asr_full_text)
                session.tts_playback_done.set()
                self._trigger_growth()
                if not session._closed and fsm.get() != SessionState.IDLE:
                    # 新一轮唤醒流程进行中（新 start 命令取消了本 pipeline）：
                    # 不在此启动下一轮 ASR，由 _do_wake_start 在唤醒音频播完后统一启动，
                    # 避免双重启动竞态导致音频发往被取消的旧会话
                    if self._new_wake_pending:
                        logger.info(f"[Session:{session.session_id}] 新一轮唤醒流程进行中，跳过 _start_next_asr（由 _do_wake_start 启动 ASR）")
                        return
                    await self._start_next_asr()
                elif fsm.get() == SessionState.IDLE:
                    logger.info(f"[Session:{session.session_id}] Session is IDLE, skip next ASR")
                return

            # 动态计算 TTS 播放完成超时时间
            _settings = get_settings()
            base_timeout = _settings.session.tts_playback_base_timeout
            max_timeout = _settings.session.tts_playback_max_timeout
            duration_multiplier = _settings.session.tts_playback_duration_multiplier

            # 计算动态超时：基础时间 + 音频时长 × 乘数
            dynamic_timeout = base_timeout + audio_duration_s * duration_multiplier
            # 限制最大超时
            dynamic_timeout = min(dynamic_timeout, max_timeout)

            logger.info(f"[Session:{session.session_id}] Pipeline completed, audio_duration={audio_duration_s:.1f}s, dynamic_timeout={dynamic_timeout:.1f}s, waiting for TTS playback done")
            self._trigger_growth()
            try:
                await asyncio.wait_for(session.tts_playback_done.wait(), timeout=dynamic_timeout)
            except asyncio.TimeoutError:
                logger.warning(f"[Session:{session.session_id}] TTS playback done timeout ({dynamic_timeout:.1f}s), proceeding anyway")
            logger.info(f"[Session:{session.session_id}] TTS playback done, fsm={fsm.get()}, closed={session._closed}")
            _log_perf_report(session, result, _pipeline, session.runtime.asr_full_text)

            # 检查是否有 WeChat 回复待发送
            if result and result.full_text:
                await self._send_wechat_reply_if_needed(result.full_text)

            if not session._closed and fsm.get() != SessionState.IDLE:
                await self._start_next_asr()
            elif fsm.get() == SessionState.IDLE:
                logger.info(f"[Session:{session.session_id}] Session is IDLE, skip next ASR")
        except asyncio.CancelledError:
            logger.info(f"[Session:{session.session_id}] _on_tts_complete cancelled")
            pass
        except Exception as e:
            logger.error(f"[TTS] Complete callback error: {e}", exc_info=True)
            # 即使出错也尝试启动下一轮 ASR，避免卡死
            try:
                if not session._closed and fsm.get() != SessionState.IDLE:
                    if self._new_wake_pending:
                        logger.info(f"[Session:{session.session_id}] 新一轮唤醒流程进行中，跳过恢复启动 ASR")
                        return
                    logger.info(f"[Session:{session.session_id}] Attempting recovery: starting next ASR after error")
                    await self._start_next_asr()
            except Exception as e2:
                logger.error(f"[Session:{session.session_id}] Recovery failed: {e2}")

    async def _start_next_asr(self):
        """启动下一轮 ASR"""
        session = self.session
        fsm = self.fsm
        channel = self.channel
        asr_client = self.asr_client
        if fsm.get() == SessionState.ASR:
            logger.info(f"[Session:{session.session_id}] Already in ASR state, skip")
            return

        if asr_client:
            session.cancel_pre_asr()
            await session.pre_connect_asr()

        await fsm.set(SessionState.ASR)
        self._start_asr_session()
        # 让出事件循环，确保 ASR 任务启动
        await asyncio.sleep(0)
        await channel.send_json({"type": "session_status", "status": "iat_start"})
        logger.info(f"[Session:{session.session_id}] Next round ASR started")

    async def _do_wake_start(self) -> None:
        """唤醒处理"""
        session = self.session
        fsm = self.fsm
        channel = self.channel
        settings = self.settings
        user_config = getattr(self.session, 'user_config', self.user_config)

        # 性能：设备唤醒到用户开口之间有 1-2 秒（唤醒提示音播放），
        # 用这个空档后台预取 prompt 组装素材（LTM 目录/记忆条目/用户画像），
        # 使本轮及后续 60s 内对话的首响延迟不再包含这些 DB 读。
        try:
            from src.use_cases.pipeline import prewarm_prompt_caches
            background_task(
                prewarm_prompt_caches(session.device_id or self.device_key, session.ltm_service),
                name="prompt_prewarm",
            )
        except Exception as e:
            logger.debug(f"[Session:{session.session_id}] prompt 预热启动失败: {e}")

        wam = getattr(get_app().state, 'wake_audio_manager', None)
        wake_ok = True
        try:
            if wam and _get_wake_enable_audio(settings, user_config):
                # 注意：_wake_audio_played 已在 start 命令处理时 clear()

                # 本轮唤醒轮次号，用于防止上一轮迟到的 client_out_audio_over 串扰
                session._wake_audio_round += 1
                current_round = session._wake_audio_round

                try:
                    played = await wam.play(channel, user_config=user_config)
                except Exception as e:
                    logger.warning(f"[Session:{session.session_id}] Wake audio send failed: {e}")
                    # play() 失败时也要 set 事件，否则会话卡死
                    session._wake_audio_played.set()
                    return
                if session._closed:
                    logger.warning(f"[Session:{session.session_id}] Session closed during wake audio, aborting")
                    return
                if not played:
                    # TTS 合成失败/无音频：跳过等待，直接进入 ASR，避免 10s 卡顿
                    logger.warning(f"[Session:{session.session_id}] Wake audio unavailable, skipping wait")
                    session._wake_audio_played.set()
                # 与 play() 内部判定保持一致（user_config 优先），避免播放与等待状态不一致
                play_enabled = wam._get_wakeup_cfg(user_config, 'play_enabled', settings.wakeup.audio_play_enabled)
                if play_enabled:
                    session._waiting_wake_audio = True  # 标记正在等待唤醒音频完成
                    session._wake_audio_expected_round = current_round
                    try:
                        await asyncio.wait_for(session._wake_audio_played.wait(), timeout=10.0)
                    except asyncio.TimeoutError:
                        logger.warning(f"[Session:{session.session_id}] Wake audio wait timeout")
                        wake_ok = False
                    finally:
                        session._waiting_wake_audio = False  # 清除标志
                else:
                    session._wake_audio_played.set()

            if not wake_ok:
                logger.warning(f"[Session:{session.session_id}] Wake audio failed, sending session_end")
                await session.send_session_end()
                return

            if session._closed:
                logger.warning(f"[Session:{session.session_id}] Session closed before ASR start, aborting")
                return

            logger.info(f"[Session:{session.session_id}] Wake audio complete, starting ASR")
            await fsm.set(SessionState.ASR)
            self._start_asr_session()
            # 让出事件循环，确保 ASR 任务启动
            await asyncio.sleep(0)
            try:
                await channel.send_json({"type": "session_status", "status": "iat_start"})
                logger.info(f"[Session:{session.session_id}] iat_start sent to device")
            except Exception as e:
                logger.warning(f"[Session:{session.session_id}] Failed to send iat_start: {e}")
                return
        except asyncio.CancelledError:
            # 被新的 start 命令取消，清理 _waiting_wake_audio 标志
            session._waiting_wake_audio = False
            logger.info(f"[Session:{session.session_id}] Wake start task cancelled")
            raise
        finally:
            # 唤醒流程结束（正常/失败/取消），清除新一轮唤醒标志
            self._new_wake_pending = False

    def _start_asr_session(self) -> None:
        """启动 ASR 会话"""
        session = self.session
        asr_client = self.asr_client
        # 幂等保护：已有活跃 ASR 任务（或正在启动）时跳过重复启动。
        # 防止 _start_next_asr（旧 pipeline 取消触发）与 _do_wake_start（唤醒音频播完触发）
        # 双重启动竞态：旧会话被取消后音频发往已关闭连接，新会话无输入 → 识别空文本断连。
        if self._asr_starting or (session.runtime.asr_task and not session.runtime.asr_task.done()):
            logger.info(f"[Session:{session.session_id}] ASR 已活跃，跳过重复启动")
            return
        self._asr_starting = True
        session.runtime.asr_start_time = time.time()
        session.runtime.asr_last_result_time = None
        session.runtime.asr_full_text = ""
        if asr_client:
            session.runtime.asr_stop_event = asyncio.Event()
            task = background_task(session.start_asr(self.on_asr_text, self.on_vad_end), name="start_asr")
            task.add_done_callback(self._on_asr_start_done)
        else:
            # 无 ASR 客户端：没有启动任务可回调，立即清除标志避免卡死
            self._asr_starting = False
        background_task(session.start_watchdog(self.on_vad_end), name="session_watchdog")

    def _on_asr_start_done(self, task: asyncio.Task) -> None:
        """start_asr 启动任务完成回调，清除同步启动标志"""
        self._asr_starting = False
        if task.cancelled():
            logger.info(f"[Session:{self.session.session_id}] ASR 启动任务已取消")
        elif task.exception():
            logger.warning(f"[Session:{self.session.session_id}] ASR 启动任务异常: {task.exception()}")

    async def _play_connect_audio(self) -> None:
        """播放连接音频"""
        channel = self.channel
        fsm = self.fsm
        voice_generator = self.voice_generator
        session = self.session
        await channel.send_json({"type": "stc_time", "stc_time": str(int(time.time()))})
        # 性能优化：将 sleep 从 0.3+0.1+0.1+0.1+0.5+0.1=1.2s 压缩到 0.4s
        # 设备端处理这些命令很快，不需要过长等待
        await asyncio.sleep(0.1)
        await channel.send_json({"type": "play_audio", "tts_task_id": "0001"})
        await channel.send_json({"type": "session_status", "status": "tts_chunk_start"})
        await channel.send_bytes(voice_generator.make_end_frame("0001"))
        await channel.send_json({"type": "session_status", "status": "tts_chunk_end"})
        await asyncio.sleep(0.2)
        # 仅在没有活跃会话时发送 session_end，避免与真实会话的 session_end 冲突
        if fsm.get() == SessionState.IDLE:
            await channel.send_json({"type": "session_status", "status": "session_end"})
            await channel.send_text("session_end")
        else:
            logger.info(f"[Session:{session.session_id}] Skip connect audio session_end, session already active (fsm={fsm.get()})")

    async def idle_keepalive(self):
        """空闲保活"""
        session = self.session
        fsm = self.fsm
        channel = self.channel
        device_key = self.device_key
        count = 0
        while not session._closed:
            interval = 1 if fsm.get() == SessionState.TTS else 3
            await asyncio.sleep(interval)
            if session._closed:
                break

            # 连接已死（发送循环标记 connected=False）→ 心跳已无法送达，
            # 立即停止并交给 run() 主循环关闭会话，让设备尽快感知并重连
            if not channel.connected:
                logger.warning(f"[Keepalive] {device_key[:8]} 连接已断开，停止心跳")
                break

            registry = get_device_registry()
            if registry:
                pending = registry.get_pending_ota(device_key)
                if pending:
                    try:
                        channel.send_json_nowait(pending)
                        registry.set_ota_updating(device_key, True)
                        registry.set_pending_ota(device_key, None)
                        logger.info(f"[Keepalive] 发送OTA指令: {pending}")
                        continue
                    except Exception as e:
                        logger.error(f"[Keepalive] 发送OTA失败: {e}")

                pending_wifi = registry.get_pending_wifi_config(device_key)
                if pending_wifi:
                    try:
                        channel.send_json_nowait(pending_wifi)
                        registry.set_pending_wifi_config(device_key, None)
                        logger.info(f"[Keepalive] 发送WiFi配置指令: {pending_wifi}")
                        continue
                    except Exception as e:
                        logger.error(f"[Keepalive] 发送WiFi配置失败: {e}")

                pending_instruct = registry.get_pending_instruct(device_key)
                if pending_instruct:
                    try:
                        channel.send_json_nowait(pending_instruct)
                        registry.set_pending_instruct(device_key, None)
                        logger.info(f"[Keepalive] 发送指令: {pending_instruct.get('command_id', '')}")
                        continue
                    except Exception as e:
                        logger.error(f"[Keepalive] 发送指令失败: {e}")

            channel.send_json_nowait({"type": "keepalive", "ts": int(time.time())})
            count += 1
            if count % 10 == 0:
                logger.info(f"[Keepalive] {device_key[:8]}: {count} times")

    async def _llm_call_for_growth(self, system_prompt: str, user_prompt: str) -> str:
        """成长系统用的LLM调用函数 - 复用主流程LLM gateway的客户端配置"""
        llm_processor = self.llm_processor
        user_config = self.user_config
        if not llm_processor:
            raise RuntimeError("LLM processor not available")

        try:
            # 复用主流程的 client + model 解析，确保 device_config 中的 base_url 正确生效
            client, model, _ = llm_processor._resolve_config(user_config)

            if client is not None:
                # 传统直连模式：有 OpenAI client 可以直接调用
                response = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.3,
                    max_tokens=4000,
                )

                result = response.choices[0].message.content or ""
                logger.debug(f"[Growth] LLM直接调用返回: {result[:200]}")
                return result

        except Exception as e:
            logger.error(f"[Growth] LLM直接调用失败: {e}")

        # 插件模式或直接调用失败：回退到 stream_chat 收集完整结果
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        result = ""
        async for token in llm_processor.stream_chat(messages, user_config=user_config):
            if isinstance(token, str) and not token.startswith("[LLM"):
                result += token
        if not result and llm_processor:
            # 如果仍然为空，可能是 LLM 插件返回了错误，记录一下
            logger.warning(f"[Growth] LLM返回为空，可能是插件配置问题")
        return result

    async def _growth_cooldown_timer(self, device_id: str, messages: list) -> None:
        """冷却定时器 - 等待一段时间后执行成长任务"""
        await asyncio.sleep(self._growth_cooldown_seconds)
        if self._growth_system:
            try:
                await self._growth_system.on_conversation_end(device_id, messages)
                logger.info(f"[Growth] 成长任务完成: {device_id[:16]}")
            except Exception as e:
                logger.warning(f"[Growth] 成长任务失败: {e}")

    async def run(self) -> None:
        """主消息循环 - 接收并分发设备消息

        对应原 handle_websocket 中 try 块内的 while 主循环。
        """
        session = self.session
        fsm = self.fsm
        channel = self.channel
        websocket = self.websocket
        device_key = self.device_key
        tool_mgr = self.tool_mgr
        asr_client = self.asr_client
        settings = self.settings

        while not session._closed:
            try:
                message = await websocket.receive()
                if isinstance(message, dict):
                    msg_type = message.get("type", "")
                    if msg_type in ("websocket.disconnect", "websocket.close"):
                        logger.info(f"[WS] Received disconnect: {msg_type}")
                        break

                    if "text" in message:
                        try:
                            data = json.loads(message["text"])
                        except Exception:
                            continue
                        t = data.get("type", "")
                        # 调试：记录所有设备消息
                        if t == "instruct":
                            logger.info(f"[WS] 收到 instruct: command_id={data.get('command_id')}")

                        # 业务指标：记录收到的 WebSocket 文本消息（按业务类型分类）
                        try:
                            get_metrics().track_ws_message_received(t or "unknown")
                        except Exception:
                            pass

                        if t == "ping":
                            channel.send_json_nowait({"type": "pong"})
                        elif t == "pong":
                            pass
                        elif t == "ota_progress":
                            progress = float(data.get("data", 0))
                            device_id_ota = data.get("device_id", device_key)
                            registry = get_device_registry()
                            if registry:
                                registry.update_ota_progress(device_key, progress)
                            logger.info(f"[OTA] 设备 {device_id_ota} 升级进度: {progress}%")
                        elif t == "ota_update_error":
                            device_id_ota = data.get("device_id", device_key)
                            registry = get_device_registry()
                            if registry:
                                registry.set_ota_updating(device_key, False)
                            logger.warning(f"[OTA] 设备 {device_id_ota} 升级失败")
                        elif t == "firmware_version":
                            fw_version = data.get("version", "")
                            registry = get_device_registry()
                            if registry and registry.has(device_key):
                                device = registry.resolve(device_key)
                                if device:
                                    device["firmware_version"] = fw_version
                                    logger.info(f"[WS] 设备 {device_key[:16]} firmware版本: {fw_version}")
                        elif t == "lua_result" or (t == "instruct" and data.get("command_id") == "lua_result"):
                            raw_data = data.get("data", "")
                            logger.info(f"[Lua] 设备返回结果: {raw_data[:200]}")
                            if tool_mgr and tool_mgr._pending_lua_future and not tool_mgr._pending_lua_future.done():
                                if isinstance(raw_data, str) and raw_data.startswith("error:"):
                                    tool_mgr._pending_lua_future.set_result(f"[Lua Error]\n{raw_data[6:]}")
                                elif isinstance(raw_data, str):
                                    tool_mgr._pending_lua_future.set_result(raw_data)
                                elif isinstance(raw_data, dict):
                                    output = raw_data.get("output", str(raw_data))
                                    success = raw_data.get("success", True)
                                    if success:
                                        tool_mgr._pending_lua_future.set_result(output)
                                    else:
                                        tool_mgr._pending_lua_future.set_result(f"[Lua Error]\n{output}")
                                tool_mgr._pending_lua_future = None
                        elif t == "device_state_result" or (t == "instruct" and data.get("command_id") == "device_state_result"):
                            # 设备状态查询回复（get_volume/get_brightness 内置工具）
                            raw_data = data.get("data", "")
                            logger.info(f"[WS] 设备状态回复: {raw_data[:200]}")
                            if tool_mgr and tool_mgr._pending_device_state_future and not tool_mgr._pending_device_state_future.done():
                                tool_mgr._pending_device_state_future.set_result(str(raw_data))
                                tool_mgr._pending_device_state_future = None
                        elif t == "instruct_ack" or (t == "instruct" and data.get("command_id") == "instruct_ack"):
                            # 设备指令 ack 确认（send_device_command_ack 等待的回执）
                            ack_data = data.get("data", "")
                            logger.info(f"[WS] 设备指令 ack: {ack_data}")
                            if (
                                tool_mgr
                                and tool_mgr._pending_command_ack_future
                                and not tool_mgr._pending_command_ack_future.done()
                            ):
                                tool_mgr._pending_command_ack_future.set_result(str(ack_data))
                                tool_mgr._pending_command_ack_future = None
                        elif t == "start":
                            if self.wake_start_task and not self.wake_start_task.done():
                                logger.info(f"[Session:{session.session_id}] Duplicate start ignored: wake flow already running")
                                continue
                            if session._waiting_wake_audio:
                                logger.info(f"[Session:{session.session_id}] Duplicate start ignored: waiting wake audio completion")
                                continue

                            if fsm.get() == SessionState.ASR:
                                logger.info(f"[Session:{session.session_id}] Duplicate start during ASR: resetting session and restarting")
                                # 结束当前 ASR 会话，重置 FSM 到 IDLE
                                await session.send_session_end()
                                # 继续执行下面的正常 start 流程，重新开始会话

                            logger.info("[WS] Received start command")

                            # 标记新一轮唤醒流程进行中：旧 pipeline 被取消时，
                            # _on_tts_complete 不应再启动下一轮 ASR（由 _do_wake_start 负责）
                            self._new_wake_pending = True

                            # 立即清除唤醒音频事件，防止上一轮迟到的 client_out_audio_over 触发
                            session._wake_audio_played.clear()

                            # 取消连接问候音频任务，避免其 session_end 与真实会话冲突
                            if self.connect_audio_task and not self.connect_audio_task.done():
                                logger.info(f"[Session:{session.session_id}] Cancelling connect audio on start")
                                self.connect_audio_task.cancel()
                                self.connect_audio_task = None

                            # 取消旧的 pipeline 任务
                            if self.pipeline_task and not self.pipeline_task.done():
                                logger.info(f"[Session:{session.session_id}] Cancelling old pipeline on new start")
                                self.pipeline_task.cancel()
                                self.pipeline_task = None

                            if session.tts_playing:
                                logger.info(f"[Session:{session.session_id}] Interrupting TTS")
                                if self.tts_done_waiter and not self.tts_done_waiter.done():
                                    self.tts_done_waiter.cancel()
                                    self.tts_done_waiter = None
                                await session.interrupt()
                                try:
                                    await asyncio.wait_for(session.tts_playback_done.wait(), timeout=0.5)
                                except asyncio.TimeoutError:
                                    pass
                            else:
                                if self.tts_done_waiter and not self.tts_done_waiter.done():
                                    self.tts_done_waiter.cancel()
                                    self.tts_done_waiter = None

                            await channel.send_json({"type": "session_start", "session_id": "0001"})
                            session.tts_playback_done.set()
                            session.tts_audio_ended.set()
                            session.tts_playback_done.clear()
                            session.tts_audio_ended.clear()

                            if asr_client:
                                session.cancel_pre_asr()
                                background_task(session.pre_connect_asr(), name="pre_connect_asr")

                            if _get_wake_enable_audio(settings, self.user_config):
                                # 取消旧的唤醒任务，避免多个 task 竞争 _waiting_wake_audio 标志
                                if self.wake_start_task and not self.wake_start_task.done():
                                    self.wake_start_task.cancel()
                                self.wake_start_task = background_task(self._do_wake_start(), name="wake_start")
                            else:
                                # 无唤醒音频：直接启动 ASR，唤醒流程标志在此清除
                                self._new_wake_pending = False
                                await fsm.set(SessionState.ASR)
                                self._start_asr_session()
                                await asyncio.sleep(0.1)
                                await channel.send_json({"type": "session_status", "status": "iat_start"})
                                logger.info(f"[Session:{session.session_id}] iat_start sent (no wake audio)")

                        elif t == "iat_end":
                            if not session.runtime.asr_processed:
                                background_task(self.on_vad_end(), name="on_vad_end")

                        elif t == "play_audio_ws_conntceed":
                            self.connect_audio_task = background_task(self._play_connect_audio(), name="play_connect_audio")
                            logger.info("[WS] Device ready")

                        elif t == "client_out_audio_over":
                            logger.info(f"[WS] Received client_out_audio_over, tts_playing={session.tts_playing}, fsm={fsm.get()}, waiting_wake={session._waiting_wake_audio}, tts_playback_done={session.tts_playback_done.is_set()}")
                            # 只在 _do_wake_start 正在等待唤醒音频完成时才 set _wake_audio_played
                            # 额外校验轮次号，防止上一轮迟到的 client_out_audio_over 串扰本轮唤醒
                            # 这解决了"第二次唤醒只播尾音"的问题
                            if (session._waiting_wake_audio
                                and not session._wake_audio_played.is_set()
                                and getattr(session, '_wake_audio_expected_round', 0) == getattr(session, '_wake_audio_round', 0)):
                                session._wake_audio_played.set()
                            # 播放完成上报必须对应一次已下发的音频（_pending_out_audio_over），
                            # 否则是迟到的/意外的上报——忽略之，防止误取消新一轮 pipeline
                            if not session._pending_out_audio_over:
                                logger.debug(f"[Session:{session.session_id}] 无进行中的音频播放，忽略此次 client_out_audio_over")
                                continue
                            session._pending_out_audio_over = False
                            session.tts_playback_done.set()
                            await session.set_tts_playing(False)
                            # 如果 pipeline 还在运行（如看门狗超时导致客户端提前结束），取消 pipeline
                            if self.pipeline_task and not self.pipeline_task.done():
                                logger.info(f"[Session:{session.session_id}] client_out_audio_over while pipeline still running, cancelling pipeline")
                                self.pipeline_task.cancel()
                            # 注意：收到 client_out_audio_over 表示客户端音频播放完成
                            # 此时应该检查 FSM 状态并准备下一轮 ASR
                            # 修复：不要因为 FSM 是 IDLE 就跳过，而是检查会话是否已关闭
                            if session._closed:
                                logger.info(f"[Session:{session.session_id}] Session is closed, skip next ASR")
                            elif fsm.get() == SessionState.IDLE:
                                logger.info(f"[Session:{session.session_id}] FSM is IDLE, but session not closed, checking if should start next ASR")
                                # 如果 FSM 是 IDLE 但会话未关闭，可能是 Pipeline 提前结束
                                # 尝试启动下一轮 ASR
                                if session.runtime.asr_processed and session.runtime.audio_queue is None:
                                    session.runtime.asr_processed = False
                                    session.runtime.audio_queue = asyncio.Queue(maxsize=AUDIO_QUEUE_MAX_SIZE)
                                    logger.info(f"[Session:{session.session_id}] TTS playback done, pre-created audio queue (IDLE state)")
                            elif session.runtime.asr_processed and session.runtime.audio_queue is None:
                                session.runtime.asr_processed = False
                                session.runtime.audio_queue = asyncio.Queue(maxsize=AUDIO_QUEUE_MAX_SIZE)
                                logger.info(f"[Session:{session.session_id}] TTS playback done, pre-created audio queue")

                        elif t == "client_out_audio_ing":
                            pass

                        elif t == "music_play_next":
                            # 设备音乐自然播放结束，请求下一首随机歌曲（自动续播）
                            logger.info(f"[WS] 收到 music_play_next，自动续播下一首随机歌曲")
                            if channel and self.tool_mgr:
                                # 在后台任务中执行，避免阻塞消息循环
                                async def _play_next():
                                    try:
                                        from src.plugins.media_player.plugin import play_random_music_to_channel
                                        success = await play_random_music_to_channel(channel, tool_manager=self.tool_mgr)
                                        if not success:
                                            logger.warning("[WS] 自动续播失败，音乐服务不可用或音乐库为空")
                                            await channel.send_json({
                                                "type": "instruct",
                                                "command_id": "stop_music",
                                            })
                                    except Exception as e:
                                        logger.error(f"[WS] 自动续播异常: {e}", exc_info=True)
                                # 通过 task_manager 执行，持有引用且异常有日志
                                background_task(_play_next(), name="music_play_next")
                            else:
                                logger.warning("[WS] music_play_next 但 channel/user_config 不可用")

                        elif t == "client_available_audio":
                            value = int(data.get("value", 10240))
                            await session.set_device_buffer(value)
                            if session._current_pipeline is not None:
                                await session._current_pipeline.set_device_buffer(value)
                            session.tts_drain_ack.set()

                        elif t == "session_stop":
                            logger.info(f"[WS] Session stop request: {data.get('session_id', 'unknown')}")
                            session.runtime.asr_processed = True
                            await session.drain_asr()
                            if session.tts_playing:
                                await session.interrupt()
                            await fsm.set(SessionState.IDLE)
                            await channel.send_json({"type": "session_stop_ack", "session_id": "0001"})

                    elif "bytes" in message:
                        # 业务指标：记录收到的 WebSocket 二进制（音频）消息
                        try:
                            get_metrics().track_ws_message_received("audio_bytes")
                        except Exception:
                            pass
                        if session.can_queue_audio():
                            audio_data = message["bytes"]
                            session.audio_processor.process_audio_chunk(audio_data)
                            session.runtime.asr_last_audio_time = time.time()
                            await session.queue_audio(audio_data)
                        elif fsm.get() == SessionState.IDLE:
                            pass
                        else:
                            logger.debug(f"[Session:{session.session_id}] Audio dropped: can_queue_audio=False, fsm={fsm.get()}, asr_task={'None' if session.runtime.asr_task is None else 'done' if session.runtime.asr_task.done() else 'running'}, audio_queue={'None' if session.runtime.audio_queue is None else 'ok'}, asr_processed={session.runtime.asr_processed}")

            except WebSocketDisconnect as e:
                logger.info(f"[WS] Client disconnected (code={e.code})")
                break
            except OSError as e:
                logger.warning(f"[WS] OS error: {type(e).__name__}: {e}")
                break
            except Exception as e:
                logger.error(f"[WS] Unknown error: {type(e).__name__}: {e}", exc_info=True)
                break

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
                await registry.unregister(self.device_key)
        except Exception as e:
            logger.warning(f"[WS] 设备注销失败: {e}")

        # 设备离线 → 推送 Web 前端
        self._broadcast_device_state(False, "idle")

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

    async def _send_wechat_reply_if_needed(self, reply_text: str) -> None:
        """LLM 回复完成后，如果有待发送的 WeChat 消息，回复给微信用户"""
        try:
            from src.infrastructure.web import get_device_registry, get_app
            registry = get_device_registry()
            if not registry:
                return
            entry = registry.resolve(self.device_key)
            if not entry or not isinstance(entry, dict):
                return
            wechat_chat_id = entry.get('wechat_chat_id', '')
            reply_pending = entry.get('wechat_reply_pending', False)
            if not wechat_chat_id or not reply_pending:
                return
            entry['wechat_reply_pending'] = False
            bot = getattr(get_app().state, 'wechat_bot', None)
            if bot and hasattr(bot, 'send_text') and reply_text:
                await bot.send_text(wechat_chat_id, reply_text)
                logger.info(f"[WeChat] LLM 回复已发送到微信 {wechat_chat_id[:20]}: {reply_text[:60]}")
        except Exception as e:
            logger.error(f"[WeChat] 发送 LLM 回复到微信失败: {e}", exc_info=True)


