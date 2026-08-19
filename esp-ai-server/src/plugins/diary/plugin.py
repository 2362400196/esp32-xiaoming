from datetime import datetime

from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import resolve_device_key, get_diary_repository

@tool()
async def read_diary(days: int = 7, tool_manager=None) -> str:
    """读取用户的日记本内容。
    日记由成长系统自动记录每次对话的摘要和重要信息。
    参数:
        days: 获取最近几天的日记，默认 7 天
    """
    device_id = resolve_device_key(None, tool_manager)
    if not device_id:
        return "错误：无法获取设备ID"

    from src.infrastructure.db.repositories.growth_repositories import DiaryRepository
    repo = DiaryRepository()
    repo = get_diary_repository()
    entries = await repo.get_recent(device_id, limit=days)
    if not entries:
        return "还没有日记内容，多和我聊聊天就会自动记录啦～"

    result = []
    for e in entries:
        result.append(f"=== {e['date']} ===\n{e['content']}")
    return "\n\n".join(result)


@tool()
async def write_diary(content: str, tool_manager=None) -> str:
    """手动写一篇日记。当你想要记录今天的心情、想法或重要的事情时使用。
    参数:
        content: 日记内容（Markdown 格式）
    """
    device_id = resolve_device_key(None, tool_manager)
    if not device_id:
        return "错误：无法获取设备ID"

    from datetime import datetime
    repo = get_diary_repository()
    today = datetime.now().strftime("%Y-%m-%d")
    await repo.upsert_entry(device_id, today, content, append=False)
    return f"日记已保存: {today}"


@tool()
async def search_diary(keyword: str, tool_manager=None) -> str:
    """搜索日记内容。从日记中查找包含特定关键词的记录。
    参数:
        keyword: 要搜索的关键词，如"开心"、"难过"、"妈妈"等
    """
    device_id = resolve_device_key(None, tool_manager)
    if not device_id:
        return "错误：无法获取设备ID"

    repo = get_diary_repository()
    entries = await repo.search(device_id, keyword)
    if not entries:
        return f"没有找到包含「{keyword}」的日记"

    result = [f"找到 {len(entries)} 篇包含「{keyword}」的日记：\n"]
    for e in entries:
        result.append(f"=== {e['date']} ===\n{e['content']}\n")
    return "\n".join(result)
