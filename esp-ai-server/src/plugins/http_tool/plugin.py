import json

from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import http_request as _http_request, json_dumps

@tool()
async def http_request(url: str, method: str = "GET", headers: str = "", body: str = "") -> str:
    """发送 HTTP 请求获取接口数据。支持 GET 和 POST 方法。

    参数:
        url: 完整的请求 URL
        method: 请求方法，GET 或 POST（默认 GET）
        headers: 自定义请求头，JSON 格式字符串，如 '{"Authorization": "Bearer xxx"}'
        body: POST 请求体（method 为 POST 时有效），字符串格式
    """
    # 设置请求头
    hdrs = {}
    if headers:
        try:
            hdrs = json.loads(headers)
        except Exception:
            pass

    # POST 请求体
    content = None
    if method.upper() == "POST" and body:
        content = body.encode("utf-8")
        hdrs["Content-Type"] = "application/json"

    resp, err = await _http_request(method.upper(), url, headers=hdrs, content=content, timeout=10)
    if err:
        return f"HTTP 请求失败: {err}"

    status = resp.status_code
    text = resp.text
    content_type = resp.headers.get("Content-Type", "")

    # 如果是 JSON 响应，格式化输出
    if "application/json" in content_type:
        try:
            parsed = json.loads(text)
            text = json_dumps(parsed, indent=2)
        except Exception:
            pass

    # 超长结果截断
    if len(text) > 3000:
        text = text[:3000] + f"\n...（结果过长，已截断至 3000 字，完整长度 {len(text)} 字）"

    return f"HTTP {status}\n\n{text}"
