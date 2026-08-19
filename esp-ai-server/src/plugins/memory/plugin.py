from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import resolve_device_key, get_ltm_service, get_default_ltm_service
from src.domain.entities import MemoryItem
from src.domain.value_objects import MemoryQuery

@tool()
async def memory_store(
    content: str,
    device_id: str = "",
    tags: str = "",
    keywords: str = "",
    tool_manager=None,
) -> str:
    """存储一条长期记忆。将用户明确要求记住的耐久事实写入长期记忆。
    参数 content: 归一化的记忆事实（不要用用户原话，用第三人称简述）
    参数 device_id: 设备ID（可选，不填会自动从连接获取）
    参数 tags: 逗号分隔的摘要标签（1-3个，如 '饮食偏好,日常习惯'）
    参数 keywords: 逗号分隔的检索关键词（1-3个）"""

    device_id = resolve_device_key(device_id, tool_manager)
    if not device_id:
        return "错误：无法获取设备ID，请稍后再试"

    service = get_ltm_service(tool_manager)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    kw_list = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else []

    item = MemoryItem(
        device_id=device_id,
        content=content,
        tags=tag_list,
        keywords=kw_list,
        source="manual",
    )
    memory_id, changed = await service.store(item)
    if changed:
        return f"已记住: {content[:60]} (id={memory_id})"
    else:
        return f"该信息已存在于记忆中 (id={memory_id})"


@tool()
async def memory_recall(
    summary_labels: str,
    device_id: str = "",
    limit: int = 8,
    tool_manager=None,
) -> str:
    """回忆长期记忆中与某个话题相关的信息。当用户提到和以前相关的话题时，主动调用此工具。
    比如用户说"我家猫"→ 调用来回忆猫的名字。用户说"上次那个事"→ 调用来回忆上次的具体内容。
    参数 summary_labels: 逗号分隔的摘要标签（从标签目录中选最匹配的）
    参数 device_id: 设备ID（可选，不填会自动从连接获取）
    参数 limit: 最多返回条数，默认8"""

    device_id = resolve_device_key(device_id, tool_manager)
    if not device_id:
        return "错误：无法获取设备ID，请稍后再试"

    service = get_ltm_service(tool_manager)
    labels = [l.strip() for l in summary_labels.split(",") if l.strip()]
    query = MemoryQuery(
        device_id=device_id,
        summary_labels=tuple(labels),
        limit=limit,
    )
    items = await service.recall(query)
    if not items:
        return "未找到相关记忆"

    lines = [f"找到 {len(items)} 条相关记忆："]
    for item in items:
        lines.append(f"- [{item.memory_id}] {item.content}")
        if item.tags:
            lines.append(f"  标签: {','.join(item.tags)}")
    return "\n".join(lines)


@tool()
async def memory_list(device_id: str = "", tool_manager=None) -> str:
    """列出当前设备的所有长期记忆。
    参数 device_id: 设备ID（可选，不填会自动从连接获取）"""

    device_id = resolve_device_key(device_id, tool_manager)
    if not device_id:
        return "错误：无法获取设备ID，请稍后再试"

    service = get_ltm_service(tool_manager)
    items = await service.list_all(device_id)
    if not items:
        return "暂无长期记忆"

    lines = [f"共有 {len(items)} 条长期记忆："]
    for item in items:
        lines.append(f"- [{item.memory_id}] ({item.source}) {item.content}")
    return "\n".join(lines)


@tool()
async def memory_update(
    memory_id: str,
    device_id: str = "",
    content: str = "",
    tags: str = "",
    keywords: str = "",
    tool_manager=None,
) -> str:
    """更新一条长期记忆。先删除旧记忆，再写入新内容。
    参数 memory_id: 要更新的记忆ID
    参数 device_id: 设备ID（可选，不填会自动从连接获取）
    参数 content: 新的记忆内容（留空则保持原内容）
    参数 tags: 逗号分隔的摘要标签
    参数 keywords: 逗号分隔的检索关键词"""

    device_id = resolve_device_key(device_id, tool_manager)
    if not device_id:
        return "错误：无法获取设备ID，请稍后再试"

    service = get_ltm_service(tool_manager)
    patch = {}
    if content:
        patch["content"] = content
    if tags:
        patch["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
    if keywords:
        patch["keywords"] = [k.strip() for k in keywords.split(",") if k.strip()]

    changed = await service.update(memory_id, patch, device_id)
    if changed:
        return f"记忆已更新: {memory_id}"
    else:
        return f"更新失败: 未找到记忆 {memory_id}"


@tool()
async def memory_forget(memory_id: str, device_id: str = "", tool_manager=None) -> str:
    """删除一条长期记忆。
    参数 memory_id: 要删除的记忆ID
    参数 device_id: 设备ID（可选，不填会自动从连接获取）"""

    device_id = resolve_device_key(device_id, tool_manager)
    if not device_id:
        return "错误：无法获取设备ID，请稍后再试"

    service = get_ltm_service(tool_manager)
    item = await service.forget(memory_id, device_id)
    if item:
        return f"已删除记忆: {item.content[:60]}"
    else:
        return f"未找到记忆: {memory_id}"


# ════════════════════════════════════════════════════════════
# 设备配置读写工具
# ════════════════════════════════════════════════════════════
