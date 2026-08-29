"""成长系统插件：用户画像、情绪分析、日记生成、自学习技能。"""

import json

from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import (
    get_device_key,
    get_user_profile_summary,
    llm_generate,
)


@tool()
async def get_diary_entries(limit: int = 999, tool_manager=None) -> str:
    """获取日记列表，返回包含完整内容的日记条目 JSON。"""
    from src.plugins.growth.engine.diary_service import DiaryService
    device_id = getattr(tool_manager, 'device_id', '') or get_device_key(tool_manager)
    if not device_id:
        return json.dumps({"success": False, "error": "未获取到设备信息"})
    diary_svc = DiaryService()
    entries = await diary_svc.get_all_entries(device_id)
    diary_list = [{"date": e.date, "content": e.content} for e in entries[-limit:]]
    diary_list.reverse()
    return json.dumps({"success": True, "count": len(diary_list), "diaries": diary_list}, ensure_ascii=False)


@tool()
async def get_user_profile_analysis(tool_manager=None) -> str:
    """获取当前用户的画像分析，包括性格特征、兴趣爱好、说话风格等。"""
    profile = await get_user_profile_summary(tool_manager=tool_manager)
    return profile if profile else "暂无用户画像数据，多在对话中才会逐步建立"


@tool()
async def get_emotion_trend(days: int = 7, tool_manager=None) -> str:
    """查看用户最近的情绪变化趋势。
    参数:
        days: 分析最近几天的情绪，默认 7 天
    """
    from src.plugins.growth.engine.emotion_analyzer import EmotionAnalyzer
    from src.plugins.growth.engine.diary_service import DiaryService
    device_key = get_device_key(tool_manager)
    if not device_key:
        return "未获取到设备信息"

    # 通过日记服务获取最近的情绪记录
    diary_svc = DiaryService()
    records = await diary_svc.get_recent(device_key, days)
    if not records:
        return f"最近 {days} 天没有情绪记录"

    analyzer = EmotionAnalyzer()
    trend = await analyzer.analyze_trend(records)
    if not trend:
        return "暂时无法分析情绪趋势"

    return (
        f"最近 {days} 天情绪趋势：\n"
        f"  总体情绪：{trend.get('overall', '未知')}\n"
        f"  情绪变化：{trend.get('change', '平稳')}\n"
        f"  积极次数：{trend.get('positive_count', 0)}\n"
        f"  消极次数：{trend.get('negative_count', 0)}\n"
        f"  {trend.get('summary', '')}"
    )


@tool()
async def get_diary_summary(days: int = 7, tool_manager=None) -> str:
    """查看最近生成的日记摘要。
    参数:
        days: 最近几天，默认 7 天
    """
    from src.plugins.growth.engine.diary_service import DiaryService
    device_key = get_device_key(tool_manager)
    if not device_key:
        return "未获取到设备信息"
    diary_svc = DiaryService()
    records = await diary_svc.get_recent(device_key, days)
    if not records:
        return f"最近 {days} 天没有日记记录"
    total = len(records)
    summary = await llm_generate(
        f"以下是对应用户最近 {days} 天的 {total} 条日记：\n" +
        "\n".join(r.get("content", "")[:100] for r in records[-10:]) +
        "\n\n请用两句话总结这些日记的主要内容。",
        tool_manager=tool_manager,
    )
    return f"最近 {days} 天共 {total} 条日记\n{summary}"


@tool()
async def analyze_conversation_quality(tool_manager=None) -> str:
    """分析最近的对话质量，给出改进建议。"""
    from src.plugins.growth.engine.self_learning import SelfLearningService
    from src.plugins.growth.engine.diary_service import DiaryService
    device_key = get_device_key(tool_manager)
    if not device_key:
        return "未获取到设备信息"
    diary_svc = DiaryService()
    records = await diary_svc.get_recent(device_key, 3)
    if not records:
        return "最近对话较少，暂无法分析"

    # 用 LLM 分析对话质量
    recent = [r.get("content", "") for r in records[:5]]
    result = await llm_generate(
        "以下是最近的一些对话记录：\n" +
        "\n".join(recent) +
        "\n\n请分析对话质量，给出改进建议。",
        tool_manager=tool_manager,
    )
    return result


@tool()
async def get_self_learned_skills(tool_manager=None) -> str:
    """查看从对话中自学习到的新技能。"""
    from src.use_cases import skill_system
    from src.use_cases._plugin_helpers import get_device_key
    device_key = get_device_key(tool_manager)
    catalog = skill_system.get_catalog(device_key)
    if not catalog:
        return "还没有自学习的技能"
    # 只显示自学习技能（device_id 不为空）
    self_learned = [s for s in catalog if s.device_id]
    if not self_learned:
        return "还没有自学习的技能"
    lines = [f"· {s.id}：{s.description}" for s in self_learned]
    return "自学习技能列表：\n" + "\n".join(lines)