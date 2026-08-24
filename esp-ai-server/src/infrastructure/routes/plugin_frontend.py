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
from src.infrastructure.plugin_loader import (
    PLUGINS_DIR,
    INSTALLED_PLUGINS_DIR,
    _plugin_meta,
    _loaded_tools,
)

logger = get_logger(__name__)

router = APIRouter()

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


@router.get("/api/v1/plugins/frontend-pages", tags=["plugin-frontend"])
async def list_frontend_pages():
    """列出所有注册了前端页面的插件。"""
    try:
        pages = _get_frontend_plugins()
        return {"code": 0, "message": "ok", "data": pages}
    except Exception as e:
        logger.error(f"[插件前端] 获取页面列表失败: {e}")
        return {"code": 1, "message": str(e), "data": None}


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

    # 为 HTML 文件注入全局滚动条样式、统一 viewport 和 box-sizing
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
async def plugin_exec(name: str, body: ExecRequest):
    """通用插件 exec 桥梁 — 前端调用插件后端能力。

    插件通过在 plugin.py 中定义 ``frontend_api`` 字典来暴露方法给前端。
    前端通过此接口调用插件后端方法，无需为每个插件注册独立 HTTP 路由。
    """
    import importlib
    try:
        from src.infrastructure.plugin_loader import _loaded_tools
        if name not in _loaded_tools:
            return {"code": 1, "message": f"插件不存在: {name}", "data": None}

        plugin_module = importlib.import_module(f"src.plugins.{name}.plugin")
        if not hasattr(plugin_module, 'frontend_api'):
            return {"code": 1, "message": "该插件没有暴露前端 API", "data": None}

        frontend_api = plugin_module.frontend_api
        if body.method not in frontend_api:
            return {"code": 1, "message": f"方法 '{body.method}' 不存在", "data": None}

        fn = frontend_api[body.method]
        result = await fn(**body.args)
        return {"code": 0, "message": "ok", "data": result}
    except Exception as e:
        logger.error(f"[PluginExec] {name}.{body.method} 失败: {e}")
        return {"code": 1, "message": str(e), "data": None}