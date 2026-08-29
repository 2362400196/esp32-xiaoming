"""SDK AI 服务与仓库 - LTM、LLM、TTS、Repository 工厂等"""

from src.infrastructure.plugin_security import require_permission
from src.use_cases.sdk.utils import get_device_key, resolve_device_key

_ltm_service: any = None


def get_default_ltm_service():
    """创建默认 LTM 服务（模块级单例，无注入时的回退）"""
    require_permission("ltm", "访问长期记忆")
    global _ltm_service
    if _ltm_service is None:
        from src.infrastructure.db.repositories.ltm_repository import SqlLongTermMemoryRepository
        from src.use_cases.memory import LongTermMemoryServiceImpl
        repo = SqlLongTermMemoryRepository()
        _ltm_service = LongTermMemoryServiceImpl(repository=repo)
    return _ltm_service


def get_ltm_service(tool_manager=None):
    """获取 LTM 服务：优先从 tool_manager 注入获取，无则用默认单例"""
    require_permission("ltm", "访问长期记忆")
    if tool_manager and hasattr(tool_manager, 'ltm_service') and tool_manager.ltm_service:
        return tool_manager.ltm_service
    return get_default_ltm_service()


def get_diary_repository():
    """获取日记仓储实例（延迟导入避免插件启动时加载 DB 依赖）。"""
    require_permission("db", "访问日记数据库")
    from src.infrastructure.db.repositories.growth_repositories import DiaryRepository
    return DiaryRepository()


def get_device_repository():
    """获取设备仓储实例（延迟导入避免插件启动时加载 DB 依赖）。"""
    require_permission("db", "访问设备数据库")
    from src.infrastructure.db.repositories.device_repository import DeviceRepository
    return DeviceRepository()


def skill_catalog_text(tool_manager) -> str:
    """渲染当前设备可用技能目录文本（过滤禁用技能），供 LLM 工具直接返回。"""
    from src.use_cases import skill_system

    device_key = get_device_key(tool_manager)
    catalog = skill_system.get_catalog(device_id=device_key)

    user_config = getattr(tool_manager, 'user_config', None) if tool_manager else None
    disabled_skills = getattr(user_config, 'disabled_skills', None) if user_config else None
    if disabled_skills:
        catalog = [e for e in catalog if e.id not in disabled_skills]

    if not catalog:
        return "当前没有可用的技能。"

    lines = ["## 可用技能列表\n"]
    for entry in catalog:
        badge = " [设备专属]" if entry.device_id else ""
        tags = f" [{', '.join(entry.tags)}]" if entry.tags else ""
        lines.append(f"- **{entry.id}**: {entry.description}{tags}{badge}")
    lines.append("")
    lines.append("提示: 使用 read_skill_document 工具(参数 skill_id)查看某个技能的详细使用说明，不要在回复中写出函数调用，要用 tool call API。")
    return "\n".join(lines)


def plugin_log(message: str, level: str = "info") -> None:
    """写入插件日志。"""
    from src.infrastructure.plugin_log_store import add_log
    from src.infrastructure.plugin_security import current_plugin
    ctx = current_plugin()
    plugin_id = ctx.plugin if ctx else "unknown"
    add_log(plugin_id, level, message)


async def llm_chat(messages: list, system_prompt: str | None = None, tool_manager=None) -> str:
    """调用 LLM 进行对话。

    Args:
        messages: 消息列表，每项 {"role": "user"/"assistant", "content": "..."}
        system_prompt: 可选，覆盖全局 system prompt
        tool_manager: 自动传入

    Returns:
        LLM 回复文本
    """
    require_permission("llm", "调用 LLM 对话")
    from src.interfaces.llm_gateways import create_llm_gateway
    llm = create_llm_gateway(config=None, tool_manager=tool_manager)
    user_config = None
    if tool_manager and hasattr(tool_manager, 'user_config') and tool_manager.user_config:
        user_config = tool_manager.user_config
    return await llm.generate(messages, user_config=user_config)


async def llm_generate(prompt: str, system_prompt: str | None = None, tool_manager=None) -> str:
    """简单文本生成（单轮对话）。"""
    messages = [{"role": "user", "content": prompt}]
    if system_prompt:
        messages.insert(0, {"role": "system", "content": system_prompt})
    return await llm_chat(messages, tool_manager=tool_manager)


async def tts_synthesize(text: str, voice: str | None = None, tool_manager=None) -> bytes:
    """文本转语音合成。

    Args:
        text: 要合成的文本
        voice: 可选，音色（如 "BV001_streaming"），不传使用全局配置
        tool_manager: 自动传入

    Returns:
        MP3 音频字节数据
    """
    require_permission("tts", "调用 TTS 语音合成")
    from src.interfaces.tts_gateways import create_tts_gateway
    config = {}
    if voice:
        config["voice_type"] = voice
    tts = create_tts_gateway(config)
    chunks = []
    async for chunk in tts.synthesize(text):
        if chunk:
            chunks.append(chunk)
    return b"".join(chunks)


async def get_user_profile_summary(device_key: str = "", tool_manager=None) -> str:
    """获取用户画像摘要。

    Args:
        device_key: 设备标识，为空时自动推断
        tool_manager: 自动传入

    Returns:
        用户画像摘要文本，如 "暂无用户信息"
    """
    require_permission("db", "访问用户画像")
    if not device_key and tool_manager:
        device_key = resolve_device_key("", tool_manager)
    if not device_key:
        return "暂无用户信息"
    from src.plugins.growth.engine.user_profile import UserProfileService
    svc = UserProfileService("")
    summary = await svc.get_profile_summary(device_key)
    return summary or "暂无用户信息"