"""技能系统插件：技能目录管理、创建、更新、删除。"""

from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import get_device_key


@tool()
async def list_available_skills(device_key: str = "", tool_manager=None) -> str:
    """列出当前设备可用的所有技能。
    参数:
        device_key: 设备标识，不传则自动使用当前设备
    """
    from src.use_cases.skill_system import get_catalog
    if not device_key:
        device_key = get_device_key(tool_manager)
    catalog = get_catalog(device_key)
    if not catalog:
        return "当前没有可用技能"
    lines = []
    for entry in catalog:
        tags = f"[{', '.join(entry.tags)}]" if entry.tags else ""
        lines.append(f"· {entry.name}：{entry.description} {tags}")
    return "可用技能列表：\n" + "\n".join(lines)


@tool()
async def get_skill_detail(skill_id: str, tool_manager=None) -> str:
    """查看某个技能的详细信息和文档。
    参数:
        skill_id: 技能 ID
    """
    from src.use_cases.skill_system import get_skill_document
    doc = get_skill_document(skill_id)
    if doc:
        return doc[:800] + ("..." if len(doc) > 800 else "")
    return f"未找到技能: {skill_id}"


@tool()
async def create_new_skill(
    name: str,
    description: str,
    instructions: str,
    category: str = "general",
    tool_manager=None,
) -> str:
    """创建一个新技能，让 LLM 学会做新的事情。
    参数:
        name: 技能名称，简短唯一，如"翻译"
        description: 技能描述，15字以内
        instructions: 技能详细指令，告诉 LLM 怎么做
        category: 分类，默认 general
    """
    from src.use_cases.skill_system import create_skill
    try:
        entry = create_skill(name, description, instructions, category=category)
        return f"技能「{name}」创建成功！（ID: {entry.skill_id}）"
    except Exception as e:
        return f"创建失败: {e}"


@tool()
async def delete_existing_skill(skill_id: str, tool_manager=None) -> str:
    """删除一个技能。
    参数:
        skill_id: 要删除的技能 ID
    """
    from src.use_cases.skill_system import delete_skill
    ok = delete_skill(skill_id)
    return f"技能已删除: {skill_id}" if ok else f"未找到技能: {skill_id}"