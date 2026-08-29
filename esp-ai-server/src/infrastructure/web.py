"""
Web - Web服务器和路由（新架构完整版）

基于FastAPI构建REST API和WebSocket端点

完整集成了所有新架构模块：
- ASR/LLM/TTS网关
- Pipeline流水线
- WebSocket处理器
- Session管理器
- 工具系统
- 辅助服务

路由按业务域拆分到 src/infrastructure/routes/ 目录下各模块，
由 _register_routes 统一通过 app.include_router() 注册各路由模块的 router。
"""
from __future__ import annotations

import contextvars
import os
import asyncio
import socket
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.infrastructure.api_response import init_rate_limiter
from src.infrastructure.config import get_settings
from src.infrastructure.logging import get_logger, trace_id_var
from src.infrastructure.task_manager import background_task

logger = get_logger(__name__)

# trace_id_var 统一从 logging 模块导入（见上方 import），避免出现两个独立的
# ContextVar 实例导致中间件设置的 trace_id 无法被网关层读取。


@asynccontextmanager
async def lifespan(app: FastAPI):
    from src.infrastructure.concurrency import init_concurrency_control, shutdown

    logger.info("=" * 60)
    logger.info("[Startup] Initializing ESP AI Server (Clean Architecture)")
    logger.info("=" * 60)

    # 初始化并发控制
    init_concurrency_control()
    logger.info("[Concurrency] 并发控制模块初始化成功")

    # 初始化敏感字段落盘加密（FIELD_ENCRYPTION_KEY，未配置时由调用方降级明文）
    from src.infrastructure.crypto import init_crypto
    init_crypto(get_settings().field_encryption_key)
    logger.info("[Crypto] 字段加密模块已初始化")

    logger.info("[Trace] Trace ID middleware enabled")
    logger.info("[Metrics] Prometheus /metrics endpoint exposed")

    firmware_dir = Path(__file__).parent.parent / "firmware"
    firmware_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/firmware", StaticFiles(directory=str(firmware_dir), html=False), name="firmware")
    logger.info(f"[Static] Firmware directory mounted: /firmware -> {firmware_dir}")

    # 启动时迁移旧格式表情目录（meta 写入 DB）
    from src.infrastructure.emo_pack import migrate_old_format
    await migrate_old_format()

    emos_dir = Path(__file__).parent.parent / "emos"
    if emos_dir.exists():
        app.mount("/emos", StaticFiles(directory=str(emos_dir)), name="emos")
        logger.info(f"[Static] Emotion resources mounted: /emos -> {emos_dir}")

    try:
        from src.interfaces.gateways import create_asr_gateway
        settings = get_settings()
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
        app.state.asr_gateway = create_asr_gateway(provider=asr_config["provider"], config=asr_config)
        logger.info("[Gateway] ASR gateway initialized")
    except Exception as e:
        logger.warning(f"[Gateway] ASR gateway initialization failed: {e}")
        app.state.asr_gateway = None

    try:
        from src.interfaces.llm_gateways import create_llm_gateway
        settings = get_settings()
        llm_config = {
            "api_key": settings.llm.api_key,
            "base_url": settings.llm.base_url,
            "model": settings.llm.model,
            "system_prompt": settings.llm.system_prompt,
        }
        app.state.llm_gateway = create_llm_gateway(config=llm_config)
        logger.info("[Gateway] LLM gateway initialized")
    except Exception as e:
        logger.warning(f"[Gateway] LLM gateway initialization failed: {e}")
        app.state.llm_gateway = None

    try:
        from src.interfaces.tts_gateways import create_tts_gateway
        settings = get_settings()
        tts_config = {
            "api_key": settings.tts.api_key,
            "resource_id": settings.tts.resource_id or "",
            "voice_type": settings.tts.voice_type or "BV001_streaming",
            "speed_ratio": settings.tts.speed_ratio or 1.0,
            "volume_ratio": settings.tts.volume_ratio or 1.0,
            "pitch_ratio": settings.tts.pitch_ratio or 1.0,
            "enable_pool": settings.tts.enable_pool,
        }
        app.state.tts_gateway = create_tts_gateway(config=tts_config)
        logger.info("[Gateway] TTS gateway initialized")
    except Exception as e:
        logger.warning(f"[Gateway] TTS gateway initialization failed: {e}")
        app.state.tts_gateway = None

    try:
        from src.use_cases.tools_system import create_tool_manager, _shared_tool_manager
        tool_manager = create_tool_manager()
        app.state.tool_manager = tool_manager
        app.state.shared_tool_manager = _shared_tool_manager
        logger.info(f"[Tool] Tool manager initialized")

        # 加载插件：扫描 src/plugins/*/plugin.py 动态注册 LLM 工具
        # （@tool() 注册进全局工具表，LLM 会话前生效）
        try:
            from src.infrastructure.plugin_loader import load_plugins
            loaded = await load_plugins()
            logger.info(f"[插件] 启动加载完成，共 {len(loaded)} 个插件: {loaded}")
        except Exception as pe:
            logger.warning(f"[插件] 加载失败: {pe}")

        # 启动时初始化 Skill 系统
        try:
            from src.use_cases import skill_system
            import os
            skills_dir = os.path.join(os.path.dirname(__file__), "..", "skills")
            data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
            skill_system.init(skills_dir, data_dir=data_dir)
            logger.info("[SkillSystem] Skill 系统启动初始化完成")
        except Exception as se:
            logger.warning(f"[SkillSystem] 启动初始化失败: {se}")

        mcp_cfg = getattr(settings, 'mcp', None)
        if mcp_cfg:
            mcp_servers = mcp_cfg.get_servers() if hasattr(mcp_cfg, 'get_servers') else {}
            if mcp_servers:
                try:
                    await tool_manager.initialize_mcp(mcp_servers)
                    logger.info("[Tool] MCP servers pre-connected at startup")
                except Exception as mcp_err:
                    logger.warning(f"[Tool] MCP pre-connect failed (will retry on first call): {mcp_err}")
    except Exception as e:
        logger.warning(f"[Tool] Tool manager initialization failed: {e}")
        app.state.tool_manager = None

    try:
        from src.use_cases.auxiliary_services import (
            DeviceRegistry,
            WakeAudioManager,
            create_speaker,
            create_auth_service,
        )
        _device_registry = DeviceRegistry()
        _wake_audio_manager = WakeAudioManager()
        app.state.device_registry = _device_registry
        app.state.wake_audio_manager = _wake_audio_manager
        app.state.speaker = create_speaker(_device_registry, _wake_audio_manager)
        app.state.auth_service = create_auth_service()

        # Web 前端设备状态实时推送中心
        from src.use_cases.web_state_hub import WebStateHub
        app.state.web_state_hub = WebStateHub()
        logger.info("[WebState] Web 前端设备状态推送中心已初始化")

        # 启动闹钟/提醒管理器
        try:
            from src.use_cases.alarm_manager import get_alarm_manager
            alarm_mgr = get_alarm_manager()
            alarm_mgr.set_registry(_device_registry)
            await alarm_mgr.load_from_db()  # 从 DB 加载持久化的闹钟
            await alarm_mgr.start()
            logger.info("[Alarm] 闹钟管理器已启动")
        except Exception as e:
            logger.warning(f"[Alarm] 闹钟管理器启动失败: {e}")

        # AI 主动推送系统已迁入 proactive_brain 插件（由插件 on_startup 钩子启动）

        logger.info("[Services] Auxiliary services initialized")
    except Exception as e:
        logger.warning(f"[Services] Auxiliary services initialization failed: {e}")

    # 启动微信 Bot（如果配置了）
    # 消息处理回调（绑定/解绑/配对码、设备转发、LLM 回复、语音模式、上下文历史）
    # 已完整迁入 wechat_bot 插件：src/plugins/wechat_bot/handler.py（一切皆插件）
    try:
        # 初始化微信 Bot（加载持久化 token 或 .env 配置）
        # 注意：必须用 wechat_bot.py 的单例访问器，绝不能直接 WeChatBot(bot_config)——
        # 否则与 sdk/infrastructure.get_wechat_bot() 各持一个实例，
        # 同一 token 双轮询会导致微信服务端 -14 session timeout、token 被误判失效
        from src.use_cases.wechat_bot import get_or_create_bot
        bot = get_or_create_bot()
        app.state.wechat_bot = bot

        from src.use_cases.wechat_binding import get_wechat_binding_manager
        bind_mgr = get_wechat_binding_manager()
        app.state.wechat_binding_manager = bind_mgr

        # 注册消息/图片回调（由 wechat_bot 插件提供，共用逻辑，无论是否启用）
        from src.plugins.wechat_bot.handler import on_wechat_message, on_wechat_image
        bot.on_message = on_wechat_message
        bot.on_attachment = on_wechat_image

        # 自动启动轮询（get_or_create_bot 构造时已从 .env/持久化文件加载 token：
        # 有 token 则 configured=True，无 token 需扫码登录）
        if bot.state.configured:
            await bot.start()
        else:
            logger.info("[WeChatBot] 微信 Bot 已创建（无 token，需扫码登录）")

    except Exception as e:
        logger.warning(f"[WeChatBot] 初始化失败: {e}")

    logger.info("=" * 60)
    logger.info("[Startup] All components initialized successfully!")
    logger.info("=" * 60)

    yield

    logger.info("=" * 60)
    logger.info("[Shutdown] Starting graceful shutdown...")
    logger.info("=" * 60)

    # ── 阶段 1：停业务入口，防止新的后台任务继续产生 ──
    # 必须最先关闭微信 Bot（停止轮询），并取消所有后台任务：
    # 设备断连通知、闹钟触发等 fire-and-forget 任务如果在网关关闭后
    # 才执行，会撞上已关闭的 HTTP 客户端/TTS 报错刷屏（历史日志可见）
    if hasattr(app.state, 'wechat_bot') and app.state.wechat_bot:
        try:
            await app.state.wechat_bot.stop()
            logger.info("[Shutdown] WeChat Bot closed")
        except Exception as e:
            logger.error(f"[Shutdown] Error closing WeChat Bot: {e}")

    from src.infrastructure.task_manager import cancel_all
    try:
        cancel_all()
        # 让已取消的任务完成收尾（有界等待，避免卡死关闭流程）
        await asyncio.sleep(0.3)
        logger.info("[Shutdown] Background tasks cancelled")
    except Exception as e:
        logger.error(f"[Shutdown] Error cancelling background tasks: {e}")

    # ── 阶段 2：关闭设备会话（会话内的 pipeline/ASR 已被 cancel_all 波及）──
    registry = get_device_registry()
    if registry:
        try:
            await registry.close_all()
            logger.info("[Shutdown] Device sessions closed")
        except Exception as e:
            logger.error(f"[Shutdown] Error closing device sessions: {e}")

    # ── 阶段 3：关闭底层网关与连接池（此时已无业务在途）──
    if hasattr(app.state, 'tts_gateway') and app.state.tts_gateway:
        try:
            await app.state.tts_gateway.close()
            logger.info("[Shutdown] TTS gateway closed")
        except Exception as e:
            logger.error(f"[Shutdown] Error closing TTS gateway: {e}")

    from src.interfaces.gateways import TencentASRGateway, VolcEngineASRGateway
    try:
        await TencentASRGateway.close_pool()
        await VolcEngineASRGateway.close_pool()
        logger.info("[Shutdown] ASR pools closed")
    except Exception as e:
        logger.error(f"[Shutdown] Error closing ASR pools: {e}")

    from src.interfaces.tts_gateways import VolcEngineTTSGateway
    try:
        await VolcEngineTTSGateway.close_pool()
        logger.info("[Shutdown] TTS pool closed")
    except Exception as e:
        logger.error(f"[Shutdown] Error closing TTS pool: {e}")

    if hasattr(app.state, 'tool_manager') and app.state.tool_manager:
        try:
            await app.state.tool_manager.cleanup()
            logger.info("[Shutdown] Tool manager closed")
        except Exception as e:
            logger.error(f"[Shutdown] Error closing tool manager: {e}")

    # 清理 ASR 网关
    if hasattr(app.state, 'asr_gateway') and app.state.asr_gateway:
        try:
            if hasattr(app.state.asr_gateway, 'close'):
                await app.state.asr_gateway.close()
                logger.info("[Shutdown] ASR gateway closed")
        except Exception as e:
            logger.error(f"[Shutdown] Error closing ASR gateway: {e}")

    # 清理 LLM 网关（aclose 释放 AsyncOpenAI 的 SSL 连接，
    # 避免进程退出时 GC 报 'Event loop is closed'）
    if hasattr(app.state, 'llm_gateway') and app.state.llm_gateway:
        try:
            if hasattr(app.state.llm_gateway, 'aclose'):
                await app.state.llm_gateway.aclose()
                logger.info("[Shutdown] LLM gateway closed")
        except Exception as e:
            logger.error(f"[Shutdown] Error closing LLM gateway: {e}")

    # 清理共享工具管理器
    if hasattr(app.state, 'shared_tool_manager') and app.state.shared_tool_manager:
        try:
            if hasattr(app.state.shared_tool_manager, 'cleanup'):
                await app.state.shared_tool_manager.cleanup()
                logger.info("[Shutdown] Shared tool manager closed")
        except Exception as e:
            logger.error(f"[Shutdown] Error closing shared tool manager: {e}")

    # 关闭并发控制模块（线程池，最后关）
    shutdown()
    logger.info("[Shutdown] Concurrency module closed")

    logger.info("[Shutdown] Graceful shutdown complete")


_app_instance: FastAPI | None = None


def get_app() -> FastAPI | None:
    return _app_instance


def get_speaker():
    """获取 Speaker 实例（模块级，供 interfaces/ 使用）"""
    app = get_app()
    return app.state.speaker if app and hasattr(app.state, 'speaker') else None


def get_device_registry():
    """获取 DeviceRegistry 实例（模块级，供 interfaces/ 使用）"""
    app = get_app()
    return app.state.device_registry if app and hasattr(app.state, 'device_registry') else None


def get_web_state_hub():
    """获取 WebStateHub 实例（模块级，供 interfaces/ 使用）"""
    app = get_app()
    return app.state.web_state_hub if app and hasattr(app.state, 'web_state_hub') else None


def get_auth_service():
    """获取 AuthService 实例（模块级，供 interfaces/ 使用）"""
    app = get_app()
    return app.state.auth_service if app and hasattr(app.state, 'auth_service') else None


def create_app() -> FastAPI:
    global _app_instance
    settings = get_settings()

    # OpenAPI 文档分组：与 src/infrastructure/routes/ 下各路由模块的 tags 对齐
    openapi_tags = [
        {"name": "system", "description": "系统级路由：健康检查、监控指标、运行统计"},
        {"name": "devices", "description": "设备管理：在线列表、详情、唤醒/播放/停止控制、OTA、固件、工具查询"},
        {"name": "mcp", "description": "MCP 外部工具配置管理：服务器增删改查、工具启停、工具列表查询"},
        {"name": "skills", "description": "技能（Skill）管理：查询、创建、更新、删除、启停、重载"},
        {"name": "emos", "description": "表情包管理：表情包 CRUD、GIF 上传、设备激活表情包"},
        {"name": "growth", "description": "AI 成长系统：设备日记、用户画像、情绪历史"},
        {"name": "marketplace", "description": "云市场：开发者认证、插件上传/下载、评论、分类聚合"},
        {"name": "admin", "description": "管理员后台：用户管理、设备管理、系统统计"},
        {"name": "wechat", "description": "微信集成：设备绑定配对码管理"},
    ]

    app = FastAPI(
        title="ESP AI Server",
        description=(
            "基于 FastAPI + asyncio 的 ESP32 智能语音后端服务，提供 ASR → LLM → TTS 全链路流式处理。"
            "\n\n## 主要能力"
            "\n- WebSocket 实时语音交互（设备连接）"
            "\n- REST API 设备控制与配置管理"
            "\n- MCP 外部工具集成"
            "\n- 技能（Skill）系统"
            "\n- 表情包管理"
            "\n- AI 成长系统（日记/画像/情绪）"
            "\n\n## 认证"
            "\n- 设备 WebSocket：URL `?key=<AUTH_API_KEY>`"
            "\n- REST API：`X-API-Key` 或 `Authorization: Bearer <ADMIN_API_KEY>`"
            "\n\n## 文档"
            "\n- Swagger UI: `/docs`"
            "\n- ReDoc: `/redoc`"
        ),
        version="3.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_tags=openapi_tags,
    )

    # CORS 中间件：允许前端跨域调用 REST API
    # 安全优先：cors_origins 为空列表时不添加 CORS 中间件（拒绝所有跨域请求），
    # 生产环境需通过 CORS_ORIGINS 显式配置允许的域名。
    cors_origins = list(getattr(settings.server, "cors_origins", []) or [])
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        logger.info(f"[CORS] Middleware enabled, allowed origins: {cors_origins}")
    else:
        logger.info("[CORS] Middleware disabled (cors_origins is empty, no cross-origin requests allowed)")

    # 速率限制器：按客户端 IP 限流，max_rpm<=0 时禁用（零开销）
    try:
        rate_limit_rpm = int(getattr(settings.rate_limit, "max_rpm", 0) or 0)
    except (TypeError, ValueError):
        rate_limit_rpm = 0
    init_rate_limiter(max_rpm=rate_limit_rpm)

    app.middleware("http")(trace_id_middleware)

    # 全局异常处理：捕获所有未处理异常，返回标准化错误响应（携带 trace_id）
    _register_exception_handlers(app)

    _register_routes(app)
    app.router.lifespan_context = lifespan

    _app_instance = app
    return app


async def trace_id_middleware(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-Id") or str(uuid.uuid4())
    request.state.trace_id = trace_id
    token = trace_id_var.set(trace_id)
    start = time.time()

    # 速率限制：仅对 REST API 生效（WebSocket 不走 HTTP 中间件）
    from src.infrastructure.api_response import get_rate_limiter
    limiter = get_rate_limiter()
    if limiter.enabled:
        client_ip = _get_client_ip(request)
        allowed, retry_after = limiter.allow(client_ip)
        if not allowed:
            retry_after_int = max(1, int(retry_after) + 1)
            logger.warning(f"[RateLimit] 客户端 {client_ip} 被限流，trace_id={trace_id}")
            return JSONResponse(
                status_code=429,
                content={"code": 1, "message": "Too many requests, please retry later", "data": None},
                headers={
                    "Retry-After": str(retry_after_int),
                    "X-Trace-Id": trace_id,
                },
            )

    try:
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        response.headers["X-Response-Time"] = f"{(time.time() - start) * 1000:.1f}ms"
        return response
    finally:
        trace_id_var.reset(token)


def _get_client_ip(request: Request) -> str:
    """提取客户端真实 IP（优先从 X-Forwarded-For / X-Real-IP 取）"""
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        # X-Forwarded-For: client, proxy1, proxy2 -> 取第一个
        return xff.split(",")[0].strip()
    xri = request.headers.get("X-Real-IP")
    if xri:
        return xri.strip()
    if request.client:
        return request.client.host
    return "unknown"


def _register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器

    - HTTPException：保持 FastAPI 默认行为，但补充 trace_id 到响应头。
    - 兜底 Exception：记录 ERROR 日志（含 trace_id），返回标准化 500 响应，
      避免堆栈信息泄露给客户端。
    """

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request: Request, exc: HTTPException):
        trace_id = getattr(request.state, "trace_id", "") or ""
        # HTTPException 统一用 {code, message, data} 封装，code 非 0
        code = 1 if exc.status_code >= 400 else 0
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": code, "message": str(exc.detail), "data": None},
            headers={"X-Trace-Id": trace_id} if trace_id else None,
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):
        trace_id = getattr(request.state, "trace_id", "") or ""
        logger.error(
            f"[Unhandled] 未处理异常 trace_id={trace_id} path={request.url.path}: "
            f"{type(exc).__name__}: {exc}",
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "code": 1,
                "message": "Internal server error",
                "data": None,
            },
            headers={"X-Trace-Id": trace_id} if trace_id else None,
        )


async def _add_skill_to_device(device_id: str, skill_name: str) -> None:
    """把技能写入设备的 skills 列表，并热重载在线设备配置。

    阶段 3：改为调用 DeviceRepository.add_skill_to_device（异步）。
    """
    try:
        from src.infrastructure.db.repositories.device_repository import DeviceRepository
        repo = DeviceRepository()
        await repo.add_skill_to_device(device_id, skill_name)
    except Exception as e:
        logger.warning(f"[Web] DB 添加技能到设备失败: {e}")
    # 热重载在线设备的配置
    _hot_reload_device_config(device_id)


async def _remove_skill_from_all_devices(skill_name: str) -> None:
    """从所有设备的 skills 列表中移除技能。

    阶段 3：改为调用 DeviceRepository.remove_skill_from_all_devices（异步）。
    """
    try:
        from src.infrastructure.db.repositories.device_repository import DeviceRepository
        repo = DeviceRepository()
        await repo.remove_skill_from_all_devices(skill_name)
    except Exception as e:
        logger.warning(f"[Web] DB 从所有设备移除技能失败: {e}")


# 设备配置版本缓存：device_id -> last seen updated_at（用于热重载时对比 DB 变更）
_device_config_versions: dict[str, float] = {}


def _check_device_config_unchanged(device_id: str) -> bool:
    """对比 DB 中设备的 updated_at，判断配置是否未变更。

    DB 查询失败时返回 False（保守策略：宁可多重载，不漏重载）。
    """
    try:
        from src.infrastructure.db.compat.sync_session import get_sync_session
        from src.infrastructure.db.models.device import DeviceModel
        from sqlalchemy import select, or_

        with get_sync_session() as session:
            result = session.execute(
                select(DeviceModel.updated_at).where(
                    or_(
                        DeviceModel.device_id == device_id,
                        DeviceModel.device_key == device_id,
                        DeviceModel.mac_address == device_id,
                    )
                )
            )
            row = result.first()
            if row is None:
                return False  # 设备不在 DB 中，交给后续逻辑处理
            updated_at = row[0]
            ts = updated_at.timestamp() if hasattr(updated_at, "timestamp") else float(updated_at)
            if _device_config_versions.get(device_id) == ts:
                return True  # 配置未变更，跳过重载
            _device_config_versions[device_id] = ts
            return False
    except Exception:
        return False


def _hot_reload_device_config(device_id: str, force: bool = False) -> None:
    """热重载在线设备的 user_config，让新技能和 MCP 配置立即生效。

    阶段 3：数据源改为 DB（通过 load_devices()），并对比 updated_at 跳过未变更的设备。
    
    force: 为 True 时跳过 updated_at 检查，强制重载（MCP 工具开关等场景需要，
           因为异步事务尚未 commit 时同步 session 读不到最新 updated_at）。
    """
    try:
        # 对比 updated_at：如果设备配置未变更，跳过重载
        # force=True 时跳过检查（MCP 路由等可能需要异步事务提交后才能读到最新时间戳）
        if not force and _check_device_config_unchanged(device_id):
            from src.infrastructure.logging import get_logger as _gl2
            _gl2(__name__).debug(f"[HotReload] 设备配置未变更，跳过重载: {device_id}")
            return

        from src.infrastructure.device_api import get_device_registry, resolve_device_id
        registry = get_device_registry()
        if not registry:
            return
        # device_id 通常是 MAC，转为 device_key 用于 registry 查找
        device_key = resolve_device_id(device_id)
        if not device_key:
            return
        d = registry.resolve(device_key)
        if not d:
            return
        from src.use_cases.auxiliary_services import load_devices
        dm = load_devices()
        # 用 device_key（API key）查找配置
        fresh_config = dm.resolve(device_key)
        if not fresh_config:
            # 回退：用 MAC 直接查找
            fresh_config = dm.devices.get(device_id)
        if fresh_config:
            d["user_config"] = fresh_config
            if d.get("tool_manager"):
                d["tool_manager"].user_config = fresh_config
                # 同步设备级插件白名单与屏幕能力（热重载后立即生效）
                tool_mgr = d["tool_manager"]
                if getattr(fresh_config, "enabled_plugins", None):
                    tool_mgr._enabled_plugins = set(fresh_config.enabled_plugins)
                    from src.infrastructure.logging import get_logger as _gl
                    _gl(__name__).info(f"[HotReload] 设备插件白名单已更新: {sorted(tool_mgr._enabled_plugins)}")
                elif getattr(tool_mgr, "_enabled_plugins", None) is not None:
                    # 白名单被清空 → 恢复"无限制"（所有插件启用）
                    tool_mgr._enabled_plugins = None
                # 插件安装列表变化 → 失效工具 schema 缓存，让 LLM 下次会话看到最新工具集
                if hasattr(tool_mgr, "invalidate_schema_cache"):
                    tool_mgr.invalidate_schema_cache()
                # 同步设备级插件配置（天气 Key 等）
                if getattr(fresh_config, "plugin_configs", None):
                    tool_mgr.plugin_configs = dict(fresh_config.plugin_configs)
                if getattr(fresh_config, "has_display", None) is not None:
                    tool_mgr.device_has_display = bool(fresh_config.has_display)
                
                # 重新初始化 MCP 连接
                user_mcp_servers = getattr(fresh_config, 'mcp_servers', None)
                disabled_mcp_servers = getattr(fresh_config, 'disabled_mcp_servers', None)
                disabled_mcp_tools = getattr(fresh_config, 'disabled_mcp_tools', None)
                
                if user_mcp_servers:
                    import asyncio
                    try:
                        # 清理旧的 MCP 连接
                        tool_mgr = d["tool_manager"]
                        for client in getattr(tool_mgr, '_mcp_clients', []):
                            try:
                                # 清理任务通过 task_manager 持有引用，失败记 ERROR 日志
                                background_task(client.disconnect(), name="mcp_client_disconnect")
                            except Exception as e:
                                logger.debug(f"[Config] 关闭 MCP client 异常: {e}")
                        for pool in getattr(tool_mgr, '_mcp_pools', {}).values():
                            try:
                                background_task(pool.close(), name="mcp_pool_close")
                            except Exception as e:
                                logger.debug(f"[Config] 关闭 MCP pool 异常: {e}")
                        
                        # 清理工具映射
                        tool_mgr._mcp_clients = []
                        tool_mgr._mcp_pools = {}
                        tool_mgr._mcp_tool_schemas = {}
                        tool_mgr._mcp_tool_map = {}
                        
                        # 重新初始化 MCP（_hot_reload_device_config 由 async HTTP 路由调用，loop 必然在运行）
                        loop = asyncio.get_running_loop()
                        # task_manager 持有任务引用防止 GC，失败记 ERROR 日志
                        background_task(
                            tool_mgr.initialize_mcp(
                                user_mcp_servers,
                                disabled_servers=disabled_mcp_servers,
                                disabled_tools=disabled_mcp_tools
                            ),
                            name="mcp_reinit",
                        )
                        from src.infrastructure.logging import get_logger
                        logger = get_logger(__name__)
                        logger.info(f"[HotReload] MCP 配置已重新加载: {device_id}, servers={list(user_mcp_servers.keys())}")
                    except Exception as e:
                        from src.infrastructure.logging import get_logger
                        logger = get_logger(__name__)
                        logger.warning(f"[HotReload] MCP 重新初始化失败: {e}")
                
            if d.get("session"):
                d["session"].user_config = fresh_config
    except Exception as e:
        from src.infrastructure.logging import get_logger
        logger = get_logger(__name__)
        logger.warning(f"[HotReload] 热重载失败: {e}")


def _register_routes(app: FastAPI) -> None:
    """注册所有路由：设备 API、WebSocket、以及按业务域拆分的路由模块"""
    # 设备管理路由（OTA/WiFi/instruct 等，由 device_api 模块维护）
    from src.infrastructure.device_api import register_device_routes
    register_device_routes(app)

    # WebSocket 端点
    from src.interfaces.websocket_handler import handle_websocket
    app.websocket("/")(handle_websocket)
    app.websocket("/connect_espai_node")(handle_websocket)

    # Web 前端设备状态实时推送端点（JWT 认证，?token=<access_token>）
    @app.websocket("/ws/web")
    async def web_state_ws(websocket: WebSocket):
        token = websocket.query_params.get("token", "")
        user = None
        if token:
            try:
                from src.infrastructure.security_jwt import decode_token
                payload = decode_token(token)
                if payload.get("type") == "access" and payload.get("sub"):
                    from src.infrastructure.db.session import get_session_ctx
                    from src.infrastructure.db.models import UserModel
                    from sqlalchemy import select
                    async with get_session_ctx() as session:
                        result = await session.execute(select(UserModel).where(UserModel.id == payload["sub"]))
                        user = result.scalar_one_or_none()
            except Exception:
                user = None
        if user is None:
            await websocket.close(code=4401)
            return

        await websocket.accept()
        hub = get_web_state_hub()
        if hub:
            await hub.register(websocket)
        try:
            while True:
                # 持续接收以检测断开；客户端不发消息时阻塞等待
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            if hub:
                await hub.unregister(websocket)

    # 按业务域拆分的路由模块（统一使用 app.include_router）
    from src.infrastructure.routes.system import router as system_router
    app.include_router(system_router)

    from src.infrastructure.routes.devices import router as devices_router
    app.include_router(devices_router)

    from src.infrastructure.routes.skills import router as skills_router
    app.include_router(skills_router)

    from src.infrastructure.routes.emos import router as emos_router
    app.include_router(emos_router)

    from src.infrastructure.routes.growth import router as growth_router
    app.include_router(growth_router)

    # 闹钟插件路由
    from src.infrastructure.routes.alarm import router as alarm_router
    app.include_router(alarm_router)

    # 用户认证路由
    from src.infrastructure.routes.auth import router as auth_router
    app.include_router(auth_router)

    # 插件管理路由（热加载）
    from src.infrastructure.routes.plugins import router as plugins_router
    app.include_router(plugins_router)

    # 插件前端页面路由（静态文件托管 + 页面列表 API）
    from src.infrastructure.routes.plugin_frontend import router as plugin_frontend_router
    app.include_router(plugin_frontend_router)

    # 云市场路由（开发者认证、插件上传/下载、评论、分类）
    from src.infrastructure.routes.marketplace import router as marketplace_router
    app.include_router(marketplace_router)

    # 管理员后台路由
    from src.infrastructure.routes.admin import router as admin_router
    app.include_router(admin_router)

    # 微信集成路由（配对码绑定流程）
    from src.infrastructure.routes.wechat import router as wechat_router
    app.include_router(wechat_router)


def get_server_ips() -> list[str]:
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        ips.append(local_ip)
        ips.append("127.0.0.1")
    except Exception as e:
        logger.debug(f"[Server] 获取本机 IP 失败: {e}")
    return ips


__all__ = [
    "create_app",
    "get_app",
    "lifespan",
    "trace_id_var",
    "get_server_ips",
    # 供路由模块使用的辅助函数
    "get_device_registry",
    "get_web_state_hub",
    "get_speaker",
    "get_auth_service",
    "_add_skill_to_device",
    "_remove_skill_from_all_devices",
    "_hot_reload_device_config",
]
