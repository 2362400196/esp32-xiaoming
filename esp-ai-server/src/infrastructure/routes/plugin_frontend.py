"""插件前端 UI 路由

插件可以自带前端页面（frontend/ 目录），通过以下方式集成到主应用：
1. 插件静态文件托管：GET /api/v1/plugins/{name}/frontend/{path}
2. 插件页面列表：GET /api/v1/plugins/frontend-pages

插件 manifest.json 中声明 frontend 相关字段：
  {
    "frontend": true,
    "frontend_config": {
      "nav_label": "MCP",          // 导航栏显示名
      "nav_icon": "server",        // 预置图标名
      "width": "full"              // full | narrow
    }
  }
"""

import re

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse, HTMLResponse
from pathlib import Path
from pydantic import BaseModel

from src.infrastructure.logging import get_logger
from src.infrastructure.security_jwt import get_current_user
from src.infrastructure.db.models.user import UserModel
from src.infrastructure.plugin_loader import (
    PLUGINS_DIR,
    INSTALLED_PLUGINS_DIR,
    _plugin_meta,
    _loaded_tools,
    _tool_owner,
)
from src.use_cases.tools_system import get_tool

logger = get_logger(__name__)

router = APIRouter()

# ============================================================
# 插件页共享主题（单一事实源）
# 插件页面在 iframe 中加载，继承不到主站 CSS 变量；历史上各页面
# 各自硬编码主题并逐渐漂移（背景/玻璃/圆角/阴影/字体与主站不搭）。
# 现由服务端在返回 HTML 时自动注入 <link>，本文件是唯一事实源：
# 修改主题只需改这里的 _THEME_CSS，所有插件页面即时生效。
# token 值与主站 esp-ai-web/src/style.css 对齐。
# ============================================================
_THEME_CSS = """:root{
  --mint:#10b981;--mint-deep:#059669;
  --mint-soft:rgba(16,185,129,0.12);--mint-border:rgba(16,185,129,0.35);
  --text-main:#12212e;--text-sub:#5b6b78;--text-light:#8fa0ad;
  --bg:#e9f0f4;--border:rgba(0,0,0,0.06);
  --danger:#ef4444;--danger-soft:rgba(239,68,68,0.1);
  --radius:18px;--radius-sm:12px;--radius-xs:8px;
  --shadow:0 2px 10px rgba(23,52,74,0.06);
  --shadow-lg:0 10px 32px rgba(23,52,74,0.10);
  --glass:linear-gradient(155deg,rgba(255,255,255,0.72),rgba(255,255,255,0.38));
  --glass-border:rgba(255,255,255,0.72);
}
body{
  background:var(--bg);color:var(--text-main);
  font-family:'PingFang SC','HarmonyOS Sans SC','Microsoft YaHei',system-ui,sans-serif;
}"""
_THEME_LINK = '<link rel="stylesheet" href="/api/v1/plugins/theme.css">'

# 预置图标映射（名称 → SVG 路径，前端渲染时使用）
PRESET_ICONS = {
    "server": "mcp",
    "message": "wechat",
    "clock": "alarm",
    "chart": "skills",
    "settings": "control",
    "cloud": "remote_config",
    "bell": "proactive_brain",
    "star": "growth",
    "grid": "store",
    "tool": "tool",
}

def _resolve_frontend_dir(plugin_name: str) -> Path | None:
    """解析插件前端目录：优先 installed，其次 built-in。"""
    installed = INSTALLED_PLUGINS_DIR / plugin_name / "frontend"
    if installed.is_dir():
        return installed
    builtin = PLUGINS_DIR / plugin_name / "frontend"
    if builtin.is_dir():
        return builtin
    return None


def _get_frontend_plugins() -> list[dict]:
    """返回所有声明了前端页面的插件列表。"""
    pages = []
    for name in sorted(_loaded_tools.keys()):
        meta = _plugin_meta.get(name)
        if meta is None:
            continue
        if not meta.get("frontend"):
            continue
        fc = meta.get("frontend_config", {}) or {}
        frontend_dir = _resolve_frontend_dir(name)
        if frontend_dir is None:
            continue
        pages.append({
            "name": name,
            "title": meta.get("name", name),
            "nav_label": fc.get("nav_label", meta.get("name", name)),
            "nav_icon": fc.get("nav_icon", ""),
            "width": fc.get("width", "full"),
            "entry": f"/api/v1/plugins/{name}/frontend/index.html",
        })
    return pages


@router.get("/api/v1/plugins/{name}/tools", tags=["plugin-frontend"])
async def list_plugin_tools(
    name: str,
    user: UserModel = Depends(get_current_user),
):
    """列出插件注册的全部工具及其 schema（开发者运行测试用）"""
    tool_names = _loaded_tools.get(name) or []
    tools = []
    for tn in tool_names:
        td = get_tool(tn)
        if td is None:
            continue
        schema = td.to_openai_schema()
        # openai 格式的 parameters 嵌在 function 层下
        fn = schema.get("function") or {}
        tools.append({
            "name": fn.get("name", td.name),
            "description": fn.get("description", ""),
            "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
        })
    return {"code": 0, "message": "ok", "data": tools}


@router.get("/api/v1/plugins/theme.css", tags=["plugin-frontend"])
async def serve_plugin_theme():
    """插件页共享主题（单一事实源，见 _THEME_CSS 注释）。iframe 内同源可直接引用。"""
    from fastapi.responses import Response
    return Response(
        content=_THEME_CSS,
        media_type="text/css; charset=utf-8",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.get("/api/v1/plugins/frontend-pages", tags=["plugin-frontend"])
async def list_frontend_pages():
    """列出所有注册了前端页面的插件。"""
    pages = _get_frontend_plugins()
    return {"code": 0, "message": "ok", "data": pages}


@router.get("/api/v1/plugins/{name}/frontend/{path:path}", tags=["plugin-frontend"])
async def serve_plugin_frontend(name: str, path: str):
    """提供插件前端静态文件（index.html / .js / .css / 图片等）。"""
    frontend_dir = _resolve_frontend_dir(name)
    if frontend_dir is None:
        raise HTTPException(404, f"插件「{name}」没有前端页面")

    # 默认入口
    if not path or path == "":
        path = "index.html"

    # 路径穿越防护
    requested = (frontend_dir / path).resolve()
    if not str(requested).startswith(str(frontend_dir.resolve())):
        raise HTTPException(403, "非法路径")

    if not requested.is_file():
        raise HTTPException(404, f"文件不存在: {path}")

    # 根据扩展名设置 Content-Type
    ext = requested.suffix.lower()
    media_types = {
        ".html": "text/html; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".ico": "image/x-icon",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
        ".map": "application/json",
    }
    media_type = media_types.get(ext, "application/octet-stream")

    # 为 HTML 文件注入全局滚动条样式、统一 viewport 和 box-sizing、共享主题
    if ext == ".html":
        try:
            content = requested.read_text("utf-8")
            inject = (
                '<style>'
                '*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}'
                'html{scrollbar-width:thin;scrollbar-color:rgba(16,185,129,0.2)transparent}'
                'body{overflow-x:hidden}'
                '::-webkit-scrollbar{width:4px}'
                '::-webkit-scrollbar-track{background:transparent}'
                '::-webkit-scrollbar-thumb{background:rgba(16,185,129,0.2);border-radius:2px}'
                '::-webkit-scrollbar-thumb:hover{background:rgba(16,185,129,0.4)}'
                '</style>'
                # 共享主题放在页面自身 <style> 之后（同优先级按文档顺序取胜），
                # 用于纠正各页面漂移的主题 token（值见 _THEME_CSS）
                + _THEME_LINK
            )
            # 注入到 </head> 之前，若无 head 则注入到 <title> 之后
            if "</head>" in content:
                content = content.replace("</head>", inject + "</head>")
            else:
                content = content.replace("<title>", inject + "<title>", 1)
            return HTMLResponse(
                content=content,
                media_type=media_type,
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
            )
        except Exception as e:
            logger.warning(f"[插件前端] 注入样式失败: {e}")

    return FileResponse(str(requested), media_type=media_type)


class ExecRequest(BaseModel):
    """插件 exec 请求体"""
    method: str
    args: dict = {}


@router.post("/api/v1/plugins/{name}/exec", tags=["plugin-frontend"])
async def plugin_exec(
    name: str,
    body: ExecRequest,
    user: UserModel = Depends(get_current_user),  # 鉴权：exec 可执行插件后端方法，必须登录
):
    """通用插件 exec 桥梁 — 前端调用插件后端能力。

    插件通过在 plugin.py 中定义 ``frontend_api`` 字典来暴露方法给前端。
    前端通过此接口调用插件后端方法，无需为每个插件注册独立 HTTP 路由。
    需 JWT 用户认证（前端页面调用时携带 Bearer Token）。
    """
    from src.infrastructure.plugin_loader import _loaded_tools, get_plugin_module
    if name not in _loaded_tools:
        return {"code": 1, "message": f"插件不存在: {name}", "data": None}

    # 复用 plugin_loader 已加载的模块实例（esp_ai_plugins_* 合成模块名）。
    # 不能用 importlib.import_module("src.plugins.{name}.plugin") 再导入一次：
    # 那会创建第二个模块实例、重复执行 @tool() 装饰器，
    # 与已注册的同名工具冲突（"插件不允许覆盖系统工具"误报）。
    plugin_module = get_plugin_module(name)
    if not hasattr(plugin_module, 'frontend_api'):
        return {"code": 1, "message": "该插件没有暴露前端 API", "data": None}

    frontend_api = plugin_module.frontend_api
    if body.method not in frontend_api:
        return {"code": 1, "message": f"方法 '{body.method}' 不存在", "data": None}

    fn = frontend_api[body.method]

    # 设置插件权限上下文：exec 桥等同插件后端调用，
    # SDK 能力入口（require_permission）据此校验 manifest 声明的权限，
    # 防止前端 exec 绕过权限检查（无上下文时静默放行）。
    from src.infrastructure.plugin_security import set_plugin_context, reset_plugin_context
    from src.infrastructure.plugin_loader import _plugin_meta
    meta = _plugin_meta.get(name, {}) or {}
    perms = meta.get("permissions") or []
    if not isinstance(perms, list):
        perms = []
    perm_token = set_plugin_context(name, perms)
    try:
        result = await fn(**body.args)
    finally:
        reset_plugin_context(perm_token)
    return {"code": 0, "message": "ok", "data": result}