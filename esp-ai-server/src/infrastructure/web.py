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
import socket
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.infrastructure.api_response import init_rate_limiter
from src.infrastructure.config import get_settings
from src.infrastructure.logging import get_logger, trace_id_var

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

        # 启动 AI 主动推送系统
        try:
            from src.use_cases.proactive_brain import ProactiveBrain
            _brain = ProactiveBrain()
            _brain.set_registry(_device_registry)
            await _brain.start()
            app.state.proactive_brain = _brain
            logger.info("[Proactive] AI主动推送系统已启动")
        except Exception as e:
            logger.warning(f"[Proactive] AI主动推送系统启动失败: {e}")

        logger.info("[Services] Auxiliary services initialized")
    except Exception as e:
        logger.warning(f"[Services] Auxiliary services initialization failed: {e}")

    # 启动微信 Bot（如果配置了）
    try:
        settings = get_settings()
        # 初始化微信 Bot（加载持久化 token 或 .env 配置）
        from src.use_cases.wechat_bot import WeChatBot, WeChatClientConfig
        cfg = settings.wechat_bot
        bot_config = WeChatClientConfig(
            token=cfg.token,
            base_url=cfg.base_url,
            cdn_base_url=cfg.cdn_base_url,
            account_id=cfg.account_id,
            app_id=cfg.app_id,
            client_version=cfg.client_version,
        )
        bot = WeChatBot(bot_config)
        app.state.wechat_bot = bot

        # 注册消息回调（共用逻辑，无论是否启用）
        from src.use_cases.wechat_binding import get_wechat_binding_manager
        bind_mgr = get_wechat_binding_manager()
        app.state.wechat_binding_manager = bind_mgr

        async def _on_wechat_message(bot_, chat_id, sender_id, message_id, text, context_token):
            """微信消息回调：查找绑定的设备并转发，然后通过 LLM（含工具）回复"""
            binding = bind_mgr.get_by_wechat(chat_id)
            if not binding:
                # 自动绑定到第一个可用的设备
                from src.infrastructure.web import get_device_registry
                registry = get_device_registry()
                if registry:
                    device_ids = registry.get_all_ids()
                    if device_ids:
                        first_id = device_ids[0]
                        entry = registry.resolve(first_id)
                        if entry:
                            mac = entry.get("mac", "") or entry.get("device_id", "") or first_id
                            device_key = first_id
                            bind_mgr.bind(chat_id, sender_id, device_key, device_mac=mac)
                            binding = bind_mgr.get_by_wechat(chat_id)
                            try:
                                await bot_.send_text(chat_id, "已自动绑定设备，现在可以开始对话了")
                            except Exception:
                                pass
                            logger.info(f"[WeChat] 自动绑定: wechat={chat_id[:16]} → device={device_key[:16]}")
                if not binding:
                    logger.info(f"[WeChat] 未绑定的微信消息: {chat_id[:16]}, 无在线设备可绑定")
                    return
            await bind_mgr.send_wechat_message_to_device(
                binding.device_key, chat_id, sender_id, text
            )
            logger.info(f"[WeChat] 微信消息已转发给设备 {binding.device_key[:16]}: {text[:60]}")

            # 使用完整 LLM（含工具）回复微信消息
            try:
                # 优先复用设备 session 的 llm_processor（与语音对话使用相同配置）
                from src.interfaces.llm_gateways import OpenAILLMGateway, create_llm_gateway
                from src.infrastructure.web import get_device_registry
                from src.use_cases.tools_system import PerUserToolManager
                settings = get_settings()

                registry = get_device_registry()
                device_tool_mgr = None
                device_channel = None
                device_llm = None
                if registry:
                    entry = registry.resolve(binding.device_key)
                    if entry and isinstance(entry, dict):
                        device_channel = entry.get('channel')
                        device_tool_mgr = entry.get('tool_manager')
                        device_llm = entry.get('session', None)
                        if device_llm:
                            device_llm = getattr(device_llm, 'llm_processor', None)

                if device_llm:
                    # 复用设备 session 的 llm_processor（配置完全一致）
                    llm_with_tools = device_llm
                    logger.info(f"[WeChat] 复用设备 session 的 llm_processor（含 MCP 工具）")
                else:
                    # 设备不在线时，创建独立的 LLM 网关
                    shared_tm = getattr(app.state, 'shared_tool_manager', None)
                    if not shared_tm:
                        logger.warning(f"[WeChat] 工具管理器不可用")
                        return

                    if not device_tool_mgr:
                        shared_tm.ensure_discovered()
                        device_tool_mgr = PerUserToolManager(shared=shared_tm, channel=device_channel, device_id=binding.device_mac)
                        logger.info(f"[WeChat] 使用共享工具管理器（无 MCP），channel={device_channel}")
                    else:
                        logger.info(f"[WeChat] 使用设备 session 的 tool_manager（含 MCP），channel={device_tool_mgr.channel}")

                    # 从数据库加载设备 LLM 配置
                    wechat_prompt = ""
                    llm_api_key = settings.llm.api_key
                    llm_base_url = settings.llm.base_url
                    llm_model = settings.llm.model
                    device_model = None
                    try:
                        import asyncio as _asyncio
                        from src.infrastructure.db.compat.sync_session import get_sync_session
                        from src.infrastructure.db.models.device import DeviceModel
                        from sqlalchemy import select

                        def _load_device_model():
                            with get_sync_session() as sess:
                                r = sess.execute(select(DeviceModel).where(
                                    DeviceModel.device_key == binding.device_key))
                                return r.scalar_one_or_none()

                        device_model = await _asyncio.to_thread(_load_device_model)
                        if device_model:
                            if device_model.llm_api_key:
                                llm_api_key = device_model.llm_api_key
                            if device_model.llm_base_url:
                                llm_base_url = device_model.llm_base_url
                            if device_model.llm_model:
                                llm_model = device_model.llm_model
                            if device_model.llm_system_prompt:
                                wechat_prompt = device_model.llm_system_prompt
                    except Exception as db_err:
                        logger.warning(f"[WeChat] 加载设备配置失败: {db_err}")

                    if not wechat_prompt:
                        wechat_prompt = settings.llm.system_prompt or "你是一个智能语音助手。"
                    wechat_prompt += " 用户通过微信和你聊天，请用自然口语化的微信聊天风格回复，控制在200字以内。可以适当使用emoji表情符号让回复更生动亲切。不要使用[e:情绪]标签。"

                    llm_with_tools = OpenAILLMGateway(
                        config={
                            "api_key": llm_api_key,
                            "base_url": llm_base_url,
                            "model": llm_model,
                            "system_prompt": wechat_prompt,
                        },
                        tool_manager=device_tool_mgr,
                    )

                # 语音模式开关检测（必须在 LLM 调用之前）
                if not hasattr(bot_.state, 'voice_mode'):
                    bot_.state.voice_mode = {}
                if "打开语音模式" in text:
                    bot_.state.voice_mode[chat_id] = True
                    logger.info(f"[WeChat] 语音模式已开启")
                elif "关闭语音模式" in text:
                    bot_.state.voice_mode[chat_id] = False
                    logger.info(f"[WeChat] 语音模式已关闭")

                # 构建对话上下文
                context_text = text
                history = bot_.state.conversation_history.get(chat_id, [])
                if history:
                    context_lines = ["以下是历史对话上下文："]
                    for msg in history[-6:]:  # 最近 3 轮
                        role = "用户" if msg["role"] == "user" else "助手"
                        context_lines.append(f"{role}: {msg['content'][:100]}")
                    context_lines.append(f"\n新的用户消息：{text}")
                    context_text = "\n".join(context_lines)

                # 在上下文中注明当前（已更新后的）语音模式
                is_voice_mode = bot_.state.voice_mode.get(chat_id, False)
                if is_voice_mode:
                    context_text += "\n[当前语音模式已开启，回复会自动语音播报]"
                else:
                    context_text += "\n[当前语音模式已关闭，仅文字回复]"

                # 收集工具 LLM 回复
                full_reply = ""
                async for chunk in llm_with_tools.stream_with_tools(context_text, device_id=binding.device_key):
                    if chunk:
                        full_reply += chunk

                if full_reply and not full_reply.startswith("LLM not configured"):
                    import re
                    clean_reply = re.sub(r'\[e:[^\]]*\]', '', full_reply).strip() or full_reply
                    # 语音模式下加标识
                    is_voice = bot_.state.voice_mode.get(chat_id, False) if hasattr(bot_.state, 'voice_mode') else False
                    display_reply = clean_reply + (" 🔊" if is_voice else "")
                    await bot_.send_text(chat_id, display_reply)
                    logger.info(f"[WeChat] LLM 回复已发送: {clean_reply[:80]}")

                    # 保存对话上下文（最多 10 轮）
                    if not hasattr(bot_.state, 'conversation_history'):
                        bot_.state.conversation_history = {}
                    history = bot_.state.conversation_history.setdefault(chat_id, [])
                    history.append({"role": "user", "content": text})
                    history.append({"role": "assistant", "content": clean_reply})
                    if len(history) > 20:
                        bot_.state.conversation_history[chat_id] = history[-20:]

                    # 回复设备语音：语音模式下所有回复都 TTS 播报
                    try:
                        need_speak = bot_.state.voice_mode.get(chat_id, False)
                        if need_speak:
                            speaker = getattr(app.state, 'speaker', None)
                            if speaker and device_channel:
                                import asyncio
                                asyncio.create_task(speaker.speak(
                                    binding.device_key, clean_reply,
                                    user_config=device_model,
                                ))
                                logger.info(f"[WeChat] 已触发设备 TTS 播放")
                    except Exception as tts_err:
                        logger.warning(f"[WeChat] 设备 TTS 播放失败: {tts_err}")
            except Exception as llm_err:
                logger.error(f"[WeChat] LLM 工具回复失败: {llm_err}", exc_info=True)

        bot.on_message = _on_wechat_message

        # 图片消息回调：AI 视觉识别
        async def _on_wechat_image(bot_, chat_id, sender_id, message_id, payload):
            """微信图片消息回调：调用视觉 LLM 识别"""
            if not payload or payload.get("type") != "image":
                return
            img_url = payload.get("data_url", "")
            wechat_chat_id = payload.get("chat_id", "") or chat_id
            if not img_url:
                return
            logger.info(f"[WeChat] 收到图片，调用视觉 LLM 识别")
            try:
                llm_raw = getattr(app.state, 'llm_gateway', None)
                if not llm_raw or not hasattr(llm_raw, 'generate'):
                    return
                messages = [
                    {"role": "system", "content": "请用简短的中文描述这张图片的内容，控制在100字以内。"},
                    {"role": "user", "content": [
                        {"type": "text", "text": "请描述这张图片"},
                        {"type": "image_url", "image_url": {"url": img_url}},
                    ]},
                ]
                reply = await llm_raw.generate(messages)
                if reply:
                    import re
                    clean = re.sub(r'\[e:[^\]]*\]', '', reply).strip()
                    await bot_.send_text(wechat_chat_id, clean or reply)
                    logger.info(f"[WeChat] 图片识别结果已发送: {clean[:80]}")
            except Exception as e:
                err_str = str(e)
                if "image_url" in err_str or "vision" in err_str.lower() or "400" in err_str:
                    await bot_.send_text(wechat_chat_id, "抱歉，当前模型不支持图片识别功能 🤖 请用文字描述你的需求")
                    logger.info(f"[WeChat] 当前模型不支持图片识别")
                else:
                    logger.error(f"[WeChat] 图片识别失败: {e}")

        bot.on_attachment = _on_wechat_image

        # 自动启动轮询
        if bot.state.configured:
            await bot.start()
            # logger.info("[WeChatBot] 微信 Bot 已启动（从文件恢复 token）")
        elif cfg.token:
            await bot.start()
            # logger.info("[WeChatBot] 微信 Bot 已启动（配置了 token）")
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

    # 清理 LLM 网关
    if hasattr(app.state, 'llm_gateway') and app.state.llm_gateway:
        try:
            if hasattr(app.state.llm_gateway, 'close'):
                await app.state.llm_gateway.close()
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

    # 关闭并发控制模块
    shutdown()
    logger.info("[Shutdown] Concurrency module closed")

    # 关闭微信 Bot
    if hasattr(app.state, 'wechat_bot') and app.state.wechat_bot:
        try:
            await app.state.wechat_bot.stop()
            logger.info("[Shutdown] WeChat Bot closed")
        except Exception as e:
            logger.error(f"[Shutdown] Error closing WeChat Bot: {e}")

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


def _hot_reload_device_config(device_id: str) -> None:
    """热重载在线设备的 user_config，让新技能和 MCP 配置立即生效。

    阶段 3：数据源改为 DB（通过 load_devices()），并对比 updated_at 跳过未变更的设备。
    """
    try:
        # 对比 updated_at：如果设备配置未变更，跳过重载
        if _check_device_config_unchanged(device_id):
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
                                asyncio.create_task(client.disconnect())
                            except Exception as e:
                                logger.debug(f"[Config] 关闭 MCP client 异常: {e}")
                        for pool in getattr(tool_mgr, '_mcp_pools', {}).values():
                            try:
                                asyncio.create_task(pool.close())
                            except Exception as e:
                                logger.debug(f"[Config] 关闭 MCP pool 异常: {e}")
                        
                        # 清理工具映射
                        tool_mgr._mcp_clients = []
                        tool_mgr._mcp_pools = {}
                        tool_mgr._mcp_tool_schemas = {}
                        tool_mgr._mcp_tool_map = {}
                        
                        # 重新初始化 MCP（_hot_reload_device_config 由 async HTTP 路由调用，loop 必然在运行）
                        loop = asyncio.get_running_loop()
                        _t = asyncio.create_task(
                            tool_mgr.initialize_mcp(
                                user_mcp_servers,
                                disabled_servers=disabled_mcp_servers,
                                disabled_tools=disabled_mcp_tools
                            )
                        )
                        # 保留任务引用防止 GC
                        _app = get_app()
                        if _app is not None:
                            if not hasattr(_app, '_bg_tasks'):
                                _app._bg_tasks = set()
                            _app._bg_tasks.add(_t)
                            _t.add_done_callback(_app._bg_tasks.discard)
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

    # 按业务域拆分的路由模块（统一使用 app.include_router）
    from src.infrastructure.routes.system import router as system_router
    app.include_router(system_router)

    from src.infrastructure.routes.devices import router as devices_router
    app.include_router(devices_router)

    from src.infrastructure.routes.skills import router as skills_router
    app.include_router(skills_router)

    from src.infrastructure.routes.mcp import router as mcp_router
    app.include_router(mcp_router)

    from src.infrastructure.routes.emos import router as emos_router
    app.include_router(emos_router)

    from src.infrastructure.routes.growth import router as growth_router
    app.include_router(growth_router)

    # 用户认证路由
    from src.infrastructure.routes.auth import router as auth_router
    app.include_router(auth_router)

    # 微信集成路由
    from src.infrastructure.routes.wechat import router as wechat_router
    app.include_router(wechat_router)

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
    "get_speaker",
    "get_auth_service",
    "_add_skill_to_device",
    "_remove_skill_from_all_devices",
    "_hot_reload_device_config",
]
