import json

from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import get_plugin_config_or_env, http_request, json_loads

@tool()
async def get_quote(tool_manager=None) -> str:
    """获取B站今日热榜时调用。"""
    # 读取插件配置（配置 → 环境变量 → 默认值 三级回退）
    api_url = get_plugin_config_or_env(
        tool_manager, "quote", "api_url",
        env_var="QUOTE_API_URL",
        default="https://uapis.cn/api/v1/misc/hotboard?type=bilibili",
    )
    timeout = int(get_plugin_config_or_env(tool_manager, "quote", "timeout", default="15"))
    max_items = int(get_plugin_config_or_env(tool_manager, "quote", "max_items", default="10"))

    # SDK 统一封装超时与异常处理，返回 (response, error)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    resp, err = await http_request("GET", api_url, headers=headers, timeout=timeout)
    if err:
        return f"获取热榜失败: {err}"

    # 解析 JSON，只提取摘要信息避免响应体过大导致协议层消息超限
    try:
        data = json_loads(resp.text)
    except json.JSONDecodeError as e:
        return f"热榜数据解析失败: {e}"

    items = data.get("list") or data.get("data") or []
    if not items:
        return "今日热榜为空"

    lines = []
    for item in items[:max_items]:
        rank = item.get("index", item.get("rank", ""))
        title = item.get("title", "未知")
        hot = item.get("hot_value", item.get("hot", ""))
        lines.append(f"  {rank}. {title}（{hot}）")

    return "今日B站热榜：\n" + "\n".join(lines)