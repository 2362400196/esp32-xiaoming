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

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path

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

    return FileResponse(str(requested), media_type=media_type)