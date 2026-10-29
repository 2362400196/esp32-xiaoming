"""WS 会话初始化：网关创建、Session 组装与设备注册。"""
from __future__ import annotations

import asyncio

from src.infrastructure.config import get_settings
from src.infrastructure.db.repositories.short_term_memory_repo import SqlShortTermMemoryRepository
from src.infrastructure.logging import get_logger, set_device_id, set_session_id, set_trace_id
from src.infrastructure.monitoring import get_metrics
from src.infrastructure.task_manager import background_task
from src.infrastructure.web import get_app, get_device_registry
from src.interfaces.gateways import create_asr_gateway
from src.interfaces.llm_gateways import create_llm_gateway
from src.interfaces.plugin_gateways import (
    create_plugin_asr_gateway,
    create_plugin_llm_gateway,
    create_plugin_tts_gateway,
)
from src.interfaces.tts_gateways import VoiceGenerator, create_tts_gateway
from src.use_cases.session import Session
from src.use_cases.session_fsm import SessionFSM, WSChannel
from src.use_cases.tools_system import PerUserToolManager, _shared_tool_manager

from .helpers import _get_wake_enable_audio

logger = get_logger(__name__)


class SetupMixin:
    """连接初始化相关方法。"""

    async def initialize(self) -> None:
        """初始化会话：接收连接、创建网关、Session、启动后台任务

        对应原 handle_websocket 中 websocket.accept() 之后到主循环之前的全部逻辑。
        """
        settings = self.settings
        websocket = self.websocket
        device_key = self.device_key
        device_mac = self.device_mac
        device_firmware_version = self.device_firmware_version
        device_bin_id = self.device_bin_id
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
            # 标记共享全局 MCP 池：设备断连 cleanup 时只清引用、不 close 池
            # （池生命周期归 app.state 全局管理，否则会误杀所有在线设备的 MCP 连接）
            tool_mgr._shares_global_mcp = True
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
                from src.plugins.growth.engine import GrowthSystem
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
                bin_id=device_bin_id,
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

