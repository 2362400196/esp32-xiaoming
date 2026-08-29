"""微信消息回调处理（wechat_bot 插件）

从 src/infrastructure/web.py lifespan 的闭包迁移而来（一切皆插件）：
- on_wechat_message：绑定/解绑、配对码绑定、消息转发设备、
  LLM 回复（插件 LLM 与直连 LLM 双分支）、语音模式、上下文历史
- on_wechat_image：图片消息 AI 视觉识别

闭包捕获的依赖（app / settings / bind_mgr / registry）改为函数内部获取，
处理逻辑原样保留，行为与迁移前一致。
"""
from __future__ import annotations

import asyncio

from src.infrastructure.logging import get_logger
from src.infrastructure.task_manager import background_task

logger = get_logger(__name__)


async def on_wechat_message(bot, chat_id, sender_id, message_id, text, context_token):
    """微信消息回调：查找绑定的设备并转发，然后通过 LLM（含工具）回复"""
    from src.infrastructure.config import get_settings
    from src.infrastructure.web import get_app
    from src.use_cases.wechat_binding import get_wechat_binding_manager

    app = get_app()
    bind_mgr = get_wechat_binding_manager()

    import re
    text_stripped = (text or "").strip()
    binding = bind_mgr.get_by_wechat(chat_id)

    # 已绑定用户发送「解绑」→ 解除该微信的绑定
    if binding and text_stripped == "解绑":
        bind_mgr.unbind_by_wechat(chat_id)
        try:
            await bot.send_text(chat_id, "已解绑设备。如需重新绑定，请在 Web 控制台「微信绑定」页生成新的配对码，然后在微信中发送：绑定 <配对码>")
        except Exception:
            pass
        logger.info(f"[WeChat] 微信已解绑: wechat={chat_id[:16]}")
        return

    if not binding:
        # 安全修复：不再自动绑定，改为「配对码」绑定流程
        m = re.match(r"^绑定\s*([A-Za-z0-9]{4,8})$", text_stripped)
        if m:
            from src.use_cases.wechat_binding import consume_pairing_code
            device_key = consume_pairing_code(m.group(1))
            if device_key:
                mac = ""
                from src.use_cases.sdk.infrastructure import get_device_registry
                registry = get_device_registry()
                if registry:
                    entry = registry.resolve(device_key)
                    if entry:
                        mac = entry.get("mac", "") or entry.get("device_id", "") or ""
                bind_mgr.bind(chat_id, sender_id, device_key, device_mac=mac)
                binding = bind_mgr.get_by_wechat(chat_id)
                try:
                    await bot.send_text(chat_id, "绑定成功，现在可以开始对话了")
                except Exception:
                    pass
                logger.info(f"[WeChat] 配对码绑定: wechat={chat_id[:16]} → device={device_key[:16]}")
            else:
                try:
                    await bot.send_text(chat_id, "配对码无效或已过期，请在 Web 控制台重新生成")
                except Exception:
                    pass
                return
        else:
            try:
                await bot.send_text(
                    chat_id,
                    "该微信尚未绑定设备。请先在 Web 控制台「微信绑定」页选择设备并生成配对码（10 分钟有效），然后在微信中发送：绑定 <配对码>",
                )
            except Exception:
                pass
            logger.info(f"[WeChat] 未绑定的微信消息: {chat_id[:16]}")
            return
    await bind_mgr.send_wechat_message_to_device(
        binding.device_key, chat_id, sender_id, text
    )
    logger.info(f"[WeChat] 微信消息已转发给设备 {binding.device_key[:16]}: {text[:60]}")

    # 使用完整 LLM（含工具）回复微信消息
    try:
        # 优先复用设备 session 的 llm_processor（与语音对话使用相同配置）
        from src.interfaces.llm_gateways import OpenAILLMGateway, create_llm_gateway
        from src.use_cases.sdk.infrastructure import get_device_registry
        from src.use_cases.tools_system import PerUserToolManager
        settings = get_settings()

        registry = get_device_registry()
        device_channel = None
        device_llm = None
        if registry:
            entry = registry.resolve(binding.device_key)
            if entry and isinstance(entry, dict):
                device_channel = entry.get('channel')
                device_llm = entry.get('session', None)
                if device_llm:
                    device_llm = getattr(device_llm, 'llm_processor', None)

        # 安全修复：无论设备是否在线，WeChat 一律构造独立的受限 tool_manager，
        # 不复用设备 session 的 tool_manager（避免微信侧触发 execute_lua 等设备控制类工具）
        shared_tm = getattr(app.state, 'shared_tool_manager', None)
        if not shared_tm:
            logger.warning(f"[WeChat] 工具管理器不可用")
            return
        shared_tm.ensure_discovered()
        device_tool_mgr = PerUserToolManager(
            shared=shared_tm,
            channel=device_channel,  # 设备在线时为 WS channel，离线为 None
            device_id=binding.device_mac,
            disabled_tools=["execute_lua", "send_device_command", "send_device_command_ack", "stop_lua"],
        )
        logger.info(f"[WeChat] 使用受限工具管理器（已禁用设备控制类工具），channel={device_channel}")

        # 微信侧上下文仅用于 LLM 对话，无设备语音播报
        device_model = None
        use_plugin_llm = False
        plugin_llm_config = None
        if device_llm:
            # 设备在线时，从 session 的 llm_processor 获取配置，创建独立网关（避免修改共享对象）
            wechat_prompt = device_llm.system_prompt or ""
            if hasattr(device_llm, "api_key"):
                # 直连 LLM 网关（OpenAI 兼容）
                llm_api_key = device_llm.api_key or settings.llm.api_key
                llm_base_url = device_llm.base_url or settings.llm.base_url
                llm_model = device_llm.model or settings.llm.model
                logger.info(f"[WeChat] 使用设备 session 的 LLM 配置（含 MCP 工具）")
            else:
                # 插件 LLM 网关（PluginLLMGateway 没有 api_key 属性）：
                # 必须走插件 LLM 路径——回退到全局 api_key 通常为空，
                # OpenAILLMGateway 会返回 "LLM not configured" mock 响应（历史 bug：微信不回复）
                use_plugin_llm = True
                plugin_llm_config = dict(getattr(device_llm, "config", {}) or {})
                logger.info(f"[WeChat] 使用设备的插件 LLM 网关（微信侧走插件 LLM 路径）")
        else:
            # 设备不在线时，使用全局/数据库中的 LLM 配置
            # 从数据库加载设备 LLM 配置
            wechat_prompt = ""
            llm_api_key = settings.llm.api_key
            llm_base_url = settings.llm.base_url
            llm_model = settings.llm.model
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

        # ── 注入设备能力边界、技能目录、长期记忆等上下文 ──
        try:
            from src.use_cases import skill_system

            # 设备能力边界
            _tm = device_tool_mgr
            if _tm is not None and hasattr(_tm, '_enabled_plugins'):
                _installed = _tm._enabled_plugins
                if _installed is not None and len(_installed) > 0:
                    _cap_note = (f"\n\n【设备能力边界】本设备仅启用插件: {'、'.join(sorted(_installed))}。"
                                 "用户询问的功能如果不在上述插件能力或系统自带能力范围内，"
                                 "直接回答\"该功能未安装/设备暂不支持\"，"
                                 "绝不可以用猜测、编造或历史经验回答，也不要假装执行了操作。")
                    wechat_prompt = (wechat_prompt + _cap_note) if wechat_prompt else _cap_note

            # Skill 目录（按消息内容动态检索）
            skill_catalog = skill_system.render_skills_catalog(device_id=binding.device_key, query=text)
            if skill_catalog:
                wechat_prompt = wechat_prompt + "\n\n" + skill_catalog if wechat_prompt else skill_catalog

            # 长期记忆摘要标签
            try:
                from src.use_cases.memory import LongTermMemoryServiceImpl
                from src.infrastructure.db.repositories.ltm_repository import SqlLongTermMemoryRepository
                _ltm_repo = SqlLongTermMemoryRepository()
                _ltm = LongTermMemoryServiceImpl(repository=_ltm_repo)
                _catalog = await _ltm.get_summary_catalog(binding.device_key)
                if _catalog:
                    _ltm_block = (
                        "\n\n[Long-term Memory Summary Labels]\n"
                        "用户提到相关话题时，主动调用 memory_recall 回忆（标签见下）：\n"
                        f"{_catalog}\n"
                        "[/Long-term Memory]"
                    )
                    wechat_prompt = wechat_prompt + _ltm_block if wechat_prompt else _ltm_block
            except Exception as e:
                logger.debug(f"[WeChat] LTM 注入失败: {e}")

            # 用户画像
            try:
                from src.plugins.growth.engine.user_profile import UserProfileService
                _profile_svc = UserProfileService("")
                _profile_summary = await _profile_svc.get_profile_summary(binding.device_key)
                if _profile_summary and _profile_summary != "暂无用户信息":
                    _profile_block = (
                        "\n\n[User Profile]\n"
                        "以下是该用户的画像信息，帮助你在回答时更个性化：\n"
                        f"{_profile_summary}\n"
                        "[/User Profile]"
                    )
                    wechat_prompt = wechat_prompt + _profile_block if wechat_prompt else _profile_block
            except Exception as e:
                logger.debug(f"[WeChat] 用户画像注入失败: {e}")
        except Exception as e:
            logger.warning(f"[WeChat] 注入上下文失败: {e}")

        # WeChat 专属后缀（在注入之后追加，确保不被覆盖）
        wechat_prompt += " 用户通过微信和你聊天，请用自然口语化的微信聊天风格回复。日常闲聊回复严格控制在 1-3 句话、80 字以内，仅当用户明确要求详细说明时才放宽。可以适当使用emoji表情符号让回复更生动亲切。不要使用[e:情绪]标签。"

        if use_plugin_llm:
            # 插件 LLM：复制设备的插件配置（模型等），system_prompt 换成微信侧拼装版，
            # tool_manager 用受限版（禁用设备控制类工具）
            from src.interfaces.plugin_gateways import PluginLLMGateway
            _plugin_cfg = dict(plugin_llm_config or {})
            _plugin_cfg["system_prompt"] = wechat_prompt
            llm_with_tools = PluginLLMGateway(config=_plugin_cfg, tool_manager=device_tool_mgr)
        else:
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
        if not hasattr(bot.state, 'voice_mode'):
            bot.state.voice_mode = {}
        if "打开语音模式" in text:
            bot.state.voice_mode[chat_id] = True
            logger.info(f"[WeChat] 语音模式已开启")
        elif "关闭语音模式" in text:
            bot.state.voice_mode[chat_id] = False
            logger.info(f"[WeChat] 语音模式已关闭")

        # 构建对话上下文
        context_text = text
        history = bot.state.conversation_history.get(chat_id, [])
        if history:
            context_lines = ["以下是历史对话上下文："]
            for msg in history[-6:]:  # 最近 3 轮
                role = "用户" if msg["role"] == "user" else "助手"
                context_lines.append(f"{role}: {msg['content'][:100]}")
            context_lines.append(f"\n新的用户消息：{text}")
            context_text = "\n".join(context_lines)

        # 在上下文中注明当前（已更新后的）语音模式
        is_voice_mode = bot.state.voice_mode.get(chat_id, False)
        if is_voice_mode:
            context_text += "\n[当前语音模式已开启，回复会自动语音播报]"
        else:
            context_text += "\n[当前语音模式已关闭，仅文字回复]"

        # 收集工具 LLM 回复（带 30 秒超时）
        logger.info(f"[WeChat] 开始 LLM 处理消息: {text[:50]}")
        full_reply = ""
        try:
            async def _collect_reply():
                r = ""
                if use_plugin_llm:
                    # 插件 LLM 网关：stream_chat(messages)（无工具调用循环，插件内部自理）
                    messages = [
                        {"role": "system", "content": wechat_prompt},
                        {"role": "user", "content": context_text},
                    ]
                    async for chunk in llm_with_tools.stream_chat(messages, device_id=binding.device_key):
                        if chunk:
                            r += chunk
                else:
                    async for chunk in llm_with_tools.stream_with_tools(context_text, device_id=binding.device_key):
                        if chunk:
                            r += chunk
                return r
            full_reply = await asyncio.wait_for(_collect_reply(), timeout=30.0)
        except asyncio.TimeoutError:
            logger.warning(f"[WeChat] LLM 处理超时 (30s)")
        except Exception as stream_err:
            logger.error(f"[WeChat] LLM 流式处理异常: {stream_err}", exc_info=True)
        logger.info(f"[WeChat] LLM 处理完成，回复长度: {len(full_reply)}")

        if full_reply and not full_reply.startswith("LLM not configured"):
            import re
            clean_reply = re.sub(r'\[e:[^\]]*\]', '', full_reply).strip() or full_reply
            # 语音模式下加标识
            is_voice = bot.state.voice_mode.get(chat_id, False) if hasattr(bot.state, 'voice_mode') else False
            display_reply = clean_reply + (" 🔊" if is_voice else "")
            await bot.send_text(chat_id, display_reply)
            logger.info(f"[WeChat] LLM 回复已发送: {clean_reply[:80]}")

            # 保存对话上下文（最多 10 轮）
            if not hasattr(bot.state, 'conversation_history'):
                bot.state.conversation_history = {}
            history = bot.state.conversation_history.setdefault(chat_id, [])
            history.append({"role": "user", "content": text})
            history.append({"role": "assistant", "content": clean_reply})
            if len(history) > 20:
                bot.state.conversation_history[chat_id] = history[-20:]

            # 回复设备语音：语音模式下所有回复都 TTS 播报
            try:
                need_speak = bot.state.voice_mode.get(chat_id, False)
                if need_speak:
                    speaker = getattr(app.state, 'speaker', None)
                    if speaker and device_channel:
                        # TTS 播报为后台任务，通过 task_manager 持有引用，失败记 ERROR 日志
                        background_task(speaker.speak(
                            binding.device_key, clean_reply,
                            user_config=device_model,
                        ), name="wechat_device_tts")
                        logger.info(f"[WeChat] 已触发设备 TTS 播放")
            except Exception as tts_err:
                logger.warning(f"[WeChat] 设备 TTS 播放失败: {tts_err}")
    except Exception as llm_err:
        logger.error(f"[WeChat] LLM 工具回复失败: {llm_err}", exc_info=True)


async def on_wechat_image(bot, chat_id, sender_id, message_id, payload):
    """微信图片消息回调：调用视觉 LLM 识别"""
    from src.infrastructure.web import get_app

    app = get_app()
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
            await bot.send_text(wechat_chat_id, clean or reply)
            logger.info(f"[WeChat] 图片识别结果已发送: {clean[:80]}")
    except Exception as e:
        err_str = str(e)
        if "image_url" in err_str or "vision" in err_str.lower() or "400" in err_str:
            await bot.send_text(wechat_chat_id, "抱歉，当前模型不支持图片识别功能 🤖 请用文字描述你的需求")
            logger.info(f"[WeChat] 当前模型不支持图片识别")
        else:
            logger.error(f"[WeChat] 图片识别失败: {e}")
