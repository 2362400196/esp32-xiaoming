"""
Skill Tools — 向 LLM 暴露技能管理工具

这些函数会通过 @tool() 自动注册到工具系统。
设备感知：如果当前连接有 device_key，只列出该设备可用的技能。
"""

from src.use_cases.tools_system import tool
from src.use_cases import skill_system
from src.use_cases._plugin_helpers import get_device_key, skill_catalog_text


@tool()
def list_skills(tool_manager=None) -> str:
    """列出设备上所有可用的技能(Skill)及其描述。当用户想了解设备能做什么时调用此工具，或在不确定使用哪个技能时查看可用选项。"""
    return skill_catalog_text(tool_manager)


@tool()
def read_skill_document(skill_id: str, tool_manager=None) -> str:
    """读取指定技能(Skill)的详细文档和使用说明。参数 skill_id 为技能名称（如 "weather_search"、"light_switch"）。阅读文档后请按说明步骤执行。"""
    # 检查是否被禁用
    user_config = getattr(tool_manager, 'user_config', None) if tool_manager else None
    disabled_skills = getattr(user_config, 'disabled_skills', None) if user_config else None
    if disabled_skills and skill_id in disabled_skills:
        return f"技能 '{skill_id}' 已被禁用。"
    doc = skill_system.get_skill_document(skill_id)
    if doc is None:
        device_key = get_device_key(tool_manager)
        available = [s.id for s in skill_system.get_catalog(device_id=device_key)]
        return f"技能 '{skill_id}' 不存在。可用技能: {', '.join(available)}"
    return doc