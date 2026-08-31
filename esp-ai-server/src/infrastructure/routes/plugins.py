"""插件管理路由：热加载、插件列表、设备级插件启用控制、插件包安装/卸载/更新"""

import asyncio
import inspect
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select

from src.infrastructure.db.models.device import DeviceModel
from src.infrastructure.db.models.user import UserModel
from src.infrastructure.db.session import get_session_ctx

from src.infrastructure.logging import get_logger
from src.infrastructure.security_jwt import get_current_user, get_current_user_optional, require_admin
from src.infrastructure.routes._deps import check_device_owner as _check_device_owner

logger = get_logger(__name__)

router = APIRouter()


class DevicePluginsRequest(BaseModel):
    """设备启用插件列表（空列表 = 全部启用，与未配置一致）"""
    enabled_plugins: list[str] = []


@router.post("/api/v1/plugins/reload")
async def reload_plugins(request: Request, _admin=Depends(require_admin)):
    """热加载全部插件：卸载旧工具 → 重新加载（改插件代码后调用，无需重启服务器）。
    管理员专属（影响所有设备的工具列表）。
    用法: curl -X POST http://<server>:8088/api/v1/plugins/reload"""
    from src.infrastructure.plugin_loader import reload_plugins

    result = await reload_plugins()

    # 失效工具 schema 缓存（下次 LLM 会话自动重建，使新工具对模型可见）
    tm = getattr(request.app.state, "tool_manager", None)
    if tm is not None and hasattr(tm, "invalidate_schema_cache"):
        tm.invalidate_schema_cache()
    from src.use_cases.tools_system import _shared_tool_manager
    if _shared_tool_manager is not None and hasattr(_shared_tool_manager, "invalidate_schema_cache"):
        _shared_tool_manager.invalidate_schema_cache()

    logger.info(f"[插件] 热加载完成: {result}")
    return {"code": 0, "message": "ok", "data": result}


def _available_plugins() -> list[dict]:
    """可用插件列表（含中文名、简介、工具与能力要求），供设备插件管理展示"""
    from src.infrastructure.plugin_loader import (
        get_loaded_plugins,
        get_plugin_requires,
        get_plugin_source,
        get_plugin_version,
        is_system_plugin,
        _loaded_tools,
        _plugin_meta,
    )
    from src.use_cases.tools_system import get_tool

    out = []
    for name in sorted(get_loaded_plugins()):
        meta = _plugin_meta.get(name, {})
        tools = []
        for tname in _loaded_tools.get(name, []):
            td = get_tool(tname)
            desc = (td.description or "").strip().split("\n")[0] if td else ""
            tools.append({"name": tname, "description": desc})
        out.append({
            "name": name,
            "title": meta.get("name") or name,          # 中文名
            "icon": meta.get("icon") or "🧩",            # 商品图标（emoji）
            "description": meta.get("description") or "",  # 中文简介
            "tools": tools,
            "requires": get_plugin_requires(name),
            "config_fields": meta.get("config_fields") or [],  # 需用户配置的字段声明
            "source": get_plugin_source(name),   # built-in / installed
            "version": get_plugin_version(name),  # 插件版本号
            "system": is_system_plugin(name),     # 系统核心插件（始终可用，不可卸载）
        })
    return out


@router.get("/api/v1/plugins")
async def list_plugins(user=Depends(get_current_user)):
    """列出所有已加载插件（名称、工具列表、能力要求）。"""
    return {"code": 0, "message": "ok", "data": _available_plugins()}


@router.get("/api/v1/devices/{device_id}/plugins")
async def get_device_plugins(device_id: str, user=Depends(get_current_user)):
    """查询设备当前启用的插件白名单。
    返回 enabled_plugins（null/空 = 全部启用）及可用插件列表。"""
    if not await _check_device_owner(device_id, user):
        raise HTTPException(403, "Device not bound to you")
    from src.infrastructure.db.repositories.device_repository import DeviceRepository
    config = await DeviceRepository().get_device_config(device_id)
    if config is None:
        return {"code": 1, "message": f"设备不存在: {device_id}", "data": None}
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "device_id": device_id,
            "enabled_plugins": config.get("enabled_plugins"),
            "plugin_configs": config.get("plugin_configs") or {},
            "available_plugins": _available_plugins(),
        },
    }


class PluginConfigRequest(BaseModel):
    """插件配置项值（仅接受插件声明过的字段）"""
    config: dict = {}


@router.put("/api/v1/devices/{device_id}/plugins/{plugin_name}/config")
async def set_plugin_config(
    device_id: str,
    plugin_name: str,
    body: PluginConfigRequest,
    user=Depends(get_current_user),
):
    """保存设备级插件配置（如天气插件的高德 API Key）。
    用法: PUT /api/v1/devices/<device_id>/plugins/weather/config
      {"config": {"amap_key": "xxx"}}"""
    if not await _check_device_owner(device_id, user):
        raise HTTPException(403, "Device not bound to you")

    # 校验插件存在 + 只接受声明过的配置字段
    plugins = {p["name"]: p for p in _available_plugins()}
    if plugin_name not in plugins:
        return {"code": 1, "message": f"未知插件: {plugin_name}", "data": None}
    declared = {f["key"] for f in plugins[plugin_name].get("config_fields", [])}
    unknown = [k for k in body.config.keys() if k not in declared]
    # 仅当插件声明了 config_fields 才做白名单校验；
    # 未声明的插件接受任意键，避免开发者漏配 config_fields 后配置存不进去
    if declared and unknown:
        return {"code": 1, "message": f"未知配置项: {unknown}（本插件支持: {sorted(declared)}）", "data": None}

    from src.infrastructure.db.repositories.device_repository import DeviceRepository
    repo = DeviceRepository()
    found = await repo.find_by_mac(device_id)
    if found is None:
        found = await repo.find_by_key(device_id)
    if found is None:
        return {"code": 1, "message": f"设备不存在: {device_id}", "data": None}
    real_device_id = found[0]

    # 合并到该插件的配置（保留其他插件的配置）
    config_dict = await repo.get_device_config(real_device_id) or {}
    merged_plugin_configs = dict(config_dict.get("plugin_configs") or {})
    merged_plugin_configs[plugin_name] = {**merged_plugin_configs.get(plugin_name, {}), **body.config}
    updated = await repo.update_device_partial(
        real_device_id, {"plugin_configs": merged_plugin_configs}
    )
    if updated is None:
        return {"code": 1, "message": f"设备不存在: {device_id}", "data": None}

    # 热重载在线设备（同步 tool_mgr.plugin_configs，立即生效）
    from src.infrastructure.web import _hot_reload_device_config
    _hot_reload_device_config(device_id)

    logger.info(f"[插件] 设备 {device_id} 插件「{plugin_name}」配置已保存: {body.config} -> DB: {merged_plugin_configs.get(plugin_name)}")
    return {"code": 0, "message": "ok", "data": {"plugin": plugin_name, "saved_keys": sorted(body.config.keys())}}


class PluginToolCallRequest(BaseModel):
    """通用插件工具调用参数"""
    args: dict = {}
    device_id: str = ""


@router.post("/api/v1/plugins/{plugin_name}/tool/{tool_name}")
async def call_plugin_tool(
    plugin_name: str,
    tool_name: str,
    body: PluginToolCallRequest,
    user=Depends(get_current_user),
):
    """通用插件工具调用接口：前端通过此接口调用插件 @tool() 函数。
    
    插件内部使用 SDK（http_get_json 等）获取数据，API Key 不暴露到前端。
    用法: POST /api/v1/plugins/weather/tool/test_weather_query
      {"args": {"city": "北京"}, "device_id": "D8:3B:DA:6D:D9:3C"}
    """
    from src.use_cases.tools_system import get_tool
    td = get_tool(tool_name)
    if td is None:
        return {"code": 1, "message": f"插件 {plugin_name} 未找到工具 {tool_name}", "data": None}

    # 构建 tool_manager 上下文（注入设备 ID 和设备插件配置，用于 KV 按设备隔离）
    class _MockToolManager:
        """模拟 PerUserToolManager.get_plugin_config，让插件 SDK 读到配置"""
        def __init__(self):
            self.plugin_configs = {}
            self.device_id = ""
            self.channel = None
        def get_plugin_config(self, plugin: str, key: str, default: str = "") -> str:
            return str((self.plugin_configs.get(plugin) or {}).get(key) or default)

    tool_manager = _MockToolManager()

    device_id = body.device_id or ""
    if device_id:
        tool_manager.device_id = device_id  # 注入设备 ID，使 KV 存储按设备隔离
        if not await _check_device_owner(device_id, user):
            raise HTTPException(403, "Device not bound to you")
        from src.infrastructure.db.repositories.device_repository import DeviceRepository
        repo = DeviceRepository()
        found = await repo.find_by_mac(device_id)
        if found is None:
            found = await repo.find_by_key(device_id)
        if found:
            real_device_id = found[0]
            config_dict = await repo.get_device_config(real_device_id) or {}
            tool_manager.plugin_configs = config_dict.get("plugin_configs") or {}

        # 设备在线时复用其真实会话的 tool_manager（带 channel）：
        # 让"运行测试"的设备指令真正下发到硬件，而不是被"设备未连接"挡住
        try:
            from src.infrastructure.web import get_device_registry
            registry = get_device_registry()
            entry = registry.resolve(device_id) if registry else None
            if entry and isinstance(entry, dict):
                real_tm = entry.get("tool_manager")
                if real_tm is not None:
                    tool_manager = real_tm
        except Exception as e:
            logger.debug(f"[插件工具调用] 复用设备 tool_manager 失败（回退 Mock）: {e}")

    # 调用插件工具函数（注入插件上下文，使 kv_set/kv_get 能找到正确的插件 ID）
    from src.infrastructure.plugin_security import set_plugin_context, reset_plugin_context
    from src.infrastructure.plugin_loader import _plugin_meta
    # 从 manifest 读取插件权限，用于设置上下文
    meta = _plugin_meta.get(plugin_name, {})
    perms = meta.get("permissions") or []
    if not isinstance(perms, list):
        perms = []
    perm_token = set_plugin_context(plugin_name, perms)

    # 参数白名单过滤：只保留工具函数签名中声明的参数，防止参数注入。
    # tool_manager/channel/ctx/fsm 等框架保留参数由服务端注入，禁止通过 body.args 覆盖
    try:
        sig = inspect.signature(td.func)
    except (TypeError, ValueError):
        sig = None
    reserved = {"self", "cls", "tool_manager", "channel", "ctx", "fsm"}
    if sig is not None:
        sig_params = set(sig.parameters)
        has_var_kw = any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        extra = [
            k for k in body.args
            if k in reserved or (not has_var_kw and k not in sig_params)
        ]
        if extra:
            logger.debug(f"[插件工具调用] {plugin_name}/{tool_name} 丢弃未声明的参数: {extra}")
        kwargs = {
            k: v for k, v in body.args.items()
            if k not in reserved and (has_var_kw or k in sig_params)
        }
        # 框架注入的上下文参数：仅当函数声明了对应形参时才传入
        if "tool_manager" in sig_params:
            kwargs["tool_manager"] = tool_manager
    else:
        # 无法内省签名时退回原始行为（保守起见仍剔除保留参数）
        kwargs = {k: v for k, v in body.args.items() if k not in reserved}
        kwargs["tool_manager"] = tool_manager
    from src.use_cases.tools_system import StopPipeline
    try:
        result = td.func(**kwargs)
        if asyncio.iscoroutine(result):
            result = await result
    except StopPipeline as e:
        # 工具主动接管屏幕/音频通道而终止流程（如倒计时结束播报）。
        # 这是正常结束而非错误：运行测试直调工具时返回可读提示，避免 500。
        msg = str(e).strip() or "工具已接管屏幕/音频通道，流程结束"
        return {"code": 0, "message": "ok", "data": f"[StopPipeline] {msg}"}
    finally:
        reset_plugin_context(perm_token)

    import json
    try:
        data = json.loads(result)
        return {"code": 0, "message": "ok", "data": data}
    except (json.JSONDecodeError, TypeError):
        return {"code": 0, "message": "ok", "data": result}


@router.put("/api/v1/devices/{device_id}/plugins")
async def set_device_plugins(
    device_id: str,
    body: DevicePluginsRequest,
    user=Depends(get_current_user),
):
    """设置设备启用哪些插件（设备级插件白名单）。
    用法: PUT /api/v1/devices/<device_id>/plugins
      {"enabled_plugins": ["weather", "system_basic"]}   # 只启用这两个插件
      {"enabled_plugins": []}                            # 全部启用（清除白名单）
    校验插件名存在；设置后在线设备立即生效（热重载）。"""
    if not await _check_device_owner(device_id, user):
        raise HTTPException(403, "Device not bound to you")

    # 校验插件名是否真实存在（空列表 = 清除白名单，跳过校验）
    if body.enabled_plugins:
        loaded = {p["name"] for p in _available_plugins()}
        unknown = [p for p in body.enabled_plugins if p not in loaded]
        if unknown:
            return {"code": 1, "message": f"未知插件: {unknown}（可用: {sorted(loaded)}）", "data": None}

    from src.infrastructure.db.repositories.device_repository import DeviceRepository
    repo = DeviceRepository()
    # 兼容 mac / device_key / device_id 查找，解析出 DB 真实 device_id 再更新
    found = await repo.find_by_mac(device_id)
    if found is None:
        found = await repo.find_by_key(device_id)
    if found is None:
        return {"code": 1, "message": f"设备不存在: {device_id}", "data": None}
    real_device_id = found[0]
    # 空列表写 []（不能用 None——_deep_merge 会跳过 None 导致卸载全部不生效）
    updated = await repo.update_device_partial(
        real_device_id, {"enabled_plugins": body.enabled_plugins or []}
    )
    if updated is None:
        return {"code": 1, "message": f"设备不存在: {device_id}", "data": None}

    # 热重载在线设备（更新 tool_manager 白名单，立即生效）
    from src.infrastructure.web import _hot_reload_device_config
    _hot_reload_device_config(device_id)

    logger.info(f"[插件] 设备 {device_id} 启用插件白名单: {body.enabled_plugins}")
    return {"code": 0, "message": "ok", "data": {"device_id": device_id, "enabled_plugins": body.enabled_plugins}}


# ════════════════════════════════════════════════════════════
# 插件包管理 API（安装 / 卸载 / 更新 / 已安装列表）
# ════════════════════════════════════════════════════════════

def _invalidate_tool_schema_cache(request: Request) -> None:
    """失效工具 schema 缓存（安装/卸载/更新后调用，使变更对 LLM 可见）。

    需要同时失效三层缓存：
    1. 全局 tool_manager（app.state）
    2. 共享 _shared_tool_manager
    3. 每个设备的 PerUserToolManager（独立的 schema 缓存）
    """
    # 1. 全局 tool_manager
    tm = getattr(request.app.state, "tool_manager", None)
    if tm is not None and hasattr(tm, "invalidate_schema_cache"):
        tm.invalidate_schema_cache()

    # 2. 共享 _shared_tool_manager
    from src.use_cases.tools_system import _shared_tool_manager
    if _shared_tool_manager is not None and hasattr(_shared_tool_manager, "invalidate_schema_cache"):
        _shared_tool_manager.invalidate_schema_cache()

    # 3. 所有设备的 PerUserToolManager（关键：设备级缓存也需失效）
    registry = getattr(request.app.state, "device_registry", None)
    if registry is not None:
        invalidated = 0
        for device_id, device_info in registry._devices.items():
            device_tm = device_info.get("tool_manager")
            if device_tm is not None and hasattr(device_tm, "invalidate_schema_cache"):
                device_tm.invalidate_schema_cache()
                invalidated += 1
        if invalidated:
            logger.info(f"[插件] 已失效 {invalidated} 个设备的工具 schema 缓存")


@router.get("/api/v1/plugins/installed")
async def list_installed_plugins(_admin=Depends(require_admin)):
    """列出所有已安装插件（含版本、来源、工具列表）。

    扫描 data/plugins/installed/ 目录，读取每个插件的 manifest.json。
    返回 data 为数组，每项含 name/version/source/tools/loaded 等字段。
    """
    from src.infrastructure.plugin_manager import get_plugin_manager
    manager = get_plugin_manager()
    installed = await asyncio.to_thread(manager.list_installed)

    # 反查使用情况：哪些设备启用了该插件（enabled_plugins 含 slug/名称），
    # 连同归属用户一起返回，供管理后台展示"谁在用/谁装的"
    async with get_session_ctx() as session:
        rows = (await session.execute(
            select(DeviceModel, UserModel)
            .outerjoin(UserModel, DeviceModel.user_id == UserModel.id)
            .where(DeviceModel.enabled_plugins.isnot(None))
        )).all()
    usage: dict[str, list] = {}
    for device, user in rows:
        for slug in (device.enabled_plugins or []):
            usage.setdefault(slug, []).append({
                "device_id": device.device_id,
                "device_name": device.name,
                "owner_email": user.email if user else "",
                "owner_nickname": user.nickname if user else "",
            })
    for p in installed:
        p["used_by"] = usage.get(p.get("slug") or p.get("name"), []) + usage.get(p.get("name"), [])

    return {"code": 0, "message": "ok", "data": installed}


@router.get("/api/v1/plugins/updates")
async def check_plugin_updates(_admin=Depends(require_admin)):
    """检查所有已安装插件是否有可更新的新版本。

    向市场 API 查询每个已安装插件的最新版本，与本地版本比较。
    返回 data 为数组，每项含 name/current_version/latest_version/has_update。
    """
    from src.infrastructure.plugin_manager import get_plugin_manager
    manager = get_plugin_manager()
    updates = await manager.check_updates()
    return {"code": 0, "message": "ok", "data": updates}


@router.post("/api/v1/plugins/install")
async def install_plugin(
    request: Request,
    file: UploadFile = File(..., description="插件 zip 包"),
    _admin=Depends(require_admin),
):
    """从上传的 zip 包安装插件。

    接受 multipart/form-data 上传的 zip 文件，安装流程：
    1. 保存 zip 到 CACHE_DIR
    2. 读取并验证 manifest.json
    3. 校验 zip 内含 plugin.py
    4. 解压到 INSTALLED_DIR/{plugin_id}/
    5. 调用 plugin_loader 加载插件
    6. 返回安装结果

    用法: curl -X POST -F "file=@weather.zip" http://<server>:8088/api/v1/plugins/install
    """
    from src.infrastructure.plugin_manager import get_plugin_manager
    from src.infrastructure.plugin_loader import PLUGINS_CACHE_DIR

    if not file.filename or not file.filename.lower().endswith(".zip"):
        return {"code": 1, "message": "请上传 .zip 格式的插件包", "data": None}

    # 1. 保存上传的 zip 到缓存目录（限大小，防 zip 炸弹）
    from src.infrastructure.plugin_manager import MAX_PLUGIN_ZIP_BYTES
    PLUGINS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # 使用原始文件名，避免冲突加时间戳后缀
    import time
    safe_name = Path(file.filename).name  # 防路径穿越
    cache_path = PLUGINS_CACHE_DIR / f"{int(time.time())}_{safe_name}"

    content = await file.read(MAX_PLUGIN_ZIP_BYTES + 1)
    if len(content) > MAX_PLUGIN_ZIP_BYTES:
        return {
            "code": 1,
            "message": f"插件包过大（>{MAX_PLUGIN_ZIP_BYTES // (1024 * 1024)}MB），拒绝安装",
            "data": None,
        }
    cache_path.write_bytes(content)
    logger.info(f"[插件] 上传 zip 已保存: {cache_path}（{len(content)} 字节）")

    # 2. 安装
    manager = get_plugin_manager()
    result = await manager.install_from_zip(cache_path, installed_by=_admin.email)

    # 3. 清理缓存 zip
    try:
        if cache_path.exists():
            cache_path.unlink()
    except OSError:
        pass

    if result.get("success"):
        # 失效工具 schema 缓存
        _invalidate_tool_schema_cache(request)
        return {"code": 0, "message": result.get("message", "安装成功"), "data": result}
    else:
        return {"code": 1, "message": result.get("message", "安装失败"), "data": result}


@router.delete("/api/v1/plugins/{name}")
async def uninstall_plugin(name: str, request: Request, _admin=Depends(require_admin)):
    """卸载插件。

    流程：
    1. 校验非内置插件（内置插件不可卸载）
    2. 注销插件工具
    3. 删除 INSTALLED_DIR/{name}/ 目录

    用法: curl -X DELETE http://<server>:8088/api/v1/plugins/weather
    """
    from src.infrastructure.plugin_manager import get_plugin_manager
    manager = get_plugin_manager()
    result = await manager.uninstall(name)

    if result.get("success"):
        # 失效工具 schema 缓存
        _invalidate_tool_schema_cache(request)
        return {"code": 0, "message": result.get("message", "卸载成功"), "data": result}
    else:
        return {"code": 1, "message": result.get("message", "卸载失败"), "data": result}


@router.post("/api/v1/plugins/{name}/update")
async def update_plugin(
    name: str, request: Request, _admin=Depends(require_admin)
):
    """更新插件到最新版本。

    从市场下载最新版 zip → 卸载旧版 → 安装新版。
    用法: curl -X POST http://<server>:8088/api/v1/plugins/weather/update
    """
    from src.infrastructure.plugin_manager import get_plugin_manager
    manager = get_plugin_manager()
    result = await manager.update_plugin(name)

    if result.get("success"):
        # 失效工具 schema 缓存
        _invalidate_tool_schema_cache(request)
        return {"code": 0, "message": result.get("message", "更新成功"), "data": result}
    else:
        return {"code": 1, "message": result.get("message", "更新失败"), "data": result}


class PluginCodeReq(BaseModel):
    """插件源码更新请求"""
    plugin_code: str = ""
    files: list[dict] = []


@router.get("/api/v1/plugins/{name}/source")
async def get_local_plugin_source(name: str, _admin=Depends(require_admin)):
    """获取本地插件的源码（所有文本文件，含 plugin.py 和 manifest.json）。"""
    from src.infrastructure.plugin_loader import _resolve_plugin_dir

    plugin_dir, source = _resolve_plugin_dir(name)
    if plugin_dir is None:
        return {"code": 1, "message": f"插件不存在: {name}", "data": None}

    files = []
    for f in sorted(plugin_dir.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(plugin_dir).as_posix()
        try:
            content = f.read_text(encoding="utf-8")
            files.append({"name": rel, "content": content})
        except UnicodeDecodeError:
            # 二进制文件（如图标 png/jpg）以 base64 返回，编辑后重新打包时保留
            import base64
            files.append({
                "name": rel,
                "content": base64.b64encode(f.read_bytes()).decode("ascii"),
                "binary": True,
            })

    plugin_file = plugin_dir / "plugin.py"
    manifest_file = plugin_dir / "manifest.json"

    plugin_code = plugin_file.read_text(encoding="utf-8") if plugin_file.is_file() else ""
    manifest_raw = manifest_file.read_text(encoding="utf-8") if manifest_file.is_file() else "{}"

    try:
        import json
        manifest = json.loads(manifest_raw)
    except Exception:
        manifest = {}

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "name": name,
            "source": source,
            "files": files,
            "plugin_code": plugin_code,
            "manifest_raw": manifest_raw,
            "manifest": manifest,
        },
    }


@router.put("/api/v1/plugins/{name}/source")
async def update_local_plugin_source(
    name: str,
    body: PluginCodeReq,
    request: Request,
    _admin=Depends(require_admin),
):
    """更新本地插件的源码（plugin.py / manifest.json / 任意文本文件）并热重载。

    仅支持已安装插件（data/plugins/installed/），不支持修改内置插件源码。
    修改后自动热重载，无需重启服务器。
    """
    from src.infrastructure.plugin_loader import INSTALLED_PLUGINS_DIR, reload_single_plugin

    plugin_dir = INSTALLED_PLUGINS_DIR / name
    if not plugin_dir.is_dir():
        return {"code": 1, "message": f"已安装插件不存在: {name}（仅支持修改已安装插件）", "data": None}

    # 兼容旧调用：只有 plugin_code 时视为仅更新 plugin.py
    if body.files:
        plugin_dir.mkdir(parents=True, exist_ok=True)
        for item in body.files:
            fname = str(item.get("name") or "").strip().lstrip("/")
            if not fname or ".." in Path(fname).parts:
                return {"code": 1, "message": f"非法文件名: {fname}", "data": None}
            target = (plugin_dir / fname).resolve()
            if not str(target).startswith(str(plugin_dir.resolve())):
                return {"code": 1, "message": f"非法文件名: {fname}", "data": None}
            target.parent.mkdir(parents=True, exist_ok=True)
            if item.get("binary"):
                import base64
                try:
                    target.write_bytes(base64.b64decode(str(item.get("content") or "")))
                except Exception:
                    continue
            else:
                target.write_text(str(item.get("content") or ""), encoding="utf-8")
    elif body.plugin_code:
        plugin_file = plugin_dir / "plugin.py"
        plugin_file.write_text(body.plugin_code, encoding="utf-8")
    else:
        return {"code": 1, "message": "没有可写入的内容", "data": None}

    success = await reload_single_plugin(name)
    try:
        _invalidate_tool_schema_cache(request)
    except Exception as cache_e:
        logger.warning(f"[插件] 失效缓存异常: {cache_e}")

    logger.info(f"[插件] 源码已更新: {name}, 热重载: {'成功' if success else '失败'}")
    return {
        "code": 0,
        "message": "源码已保存并热重载" if success else "源码已保存，但热重载失败，请检查代码语法",
        "data": {"name": name, "reloaded": success},
    }


class CreateLocalPluginReq(BaseModel):
    """从代码创建本地插件（不上架市场）"""
    slug: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    plugin_code: str = ""
    manifest: dict = {}
    files: list[dict] = []


@router.post("/api/v1/plugins/create-local")
async def create_local_plugin(
    body: CreateLocalPluginReq,
    request: Request,
    _admin=Depends(require_admin),
):
    """从代码直接创建本地插件（无需上传 zip，不上架市场）。

    在 data/plugins/installed/{slug}/ 下创建目录，写入 manifest.json 和 plugin.py，
    然后热重载。适用于开发者先本地测试，测试完毕后再上架市场。
    """
    import json
    import re

    from src.infrastructure.plugin_loader import INSTALLED_PLUGINS_DIR, reload_single_plugin
    from src.infrastructure.plugin_manifest import PluginManifest

    slug = body.slug.lower().strip()
    if not re.match(r'^[a-z][a-z0-9_-]*$', slug):
        return {"code": 1, "message": f"slug 非法（需以字母开头，仅含小写字母/数字/_/-）: {body.slug}", "data": None}

    if not body.name.strip():
        return {"code": 1, "message": "插件名称不能为空", "data": None}

    if not body.plugin_code.strip() and not body.files:
        return {"code": 1, "message": "plugin.py 代码不能为空", "data": None}

    plugin_dir = INSTALLED_PLUGINS_DIR / slug
    if plugin_dir.exists():
        return {"code": 1, "message": f"插件已存在: {slug}（如需更新请使用编辑功能）", "data": None}

    # 构建 manifest
    manifest = body.manifest or {}
    manifest["id"] = slug
    manifest["name"] = body.name.strip()
    manifest["version"] = body.version or "1.0.0"
    manifest["description"] = body.description or ""
    manifest.setdefault("api_version", "1.0")

    # 校验 manifest（校验失败属客户端输入问题 → 400）
    try:
        m = PluginManifest(**manifest)
        m.validate_compatibility()
    except Exception as e:
        raise HTTPException(400, f"manifest 校验失败: {e}")

    # 创建目录和文件
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if body.files:
        for item in body.files:
            fname = str(item.get("name") or "").strip().lstrip("/")
            if not fname or ".." in Path(fname).parts:
                return {"code": 1, "message": f"非法文件名: {fname}", "data": None}
            target = (plugin_dir / fname).resolve()
            if not str(target).startswith(str(plugin_dir.resolve())):
                return {"code": 1, "message": f"非法文件名: {fname}", "data": None}
            target.parent.mkdir(parents=True, exist_ok=True)
            if item.get("binary"):
                import base64
                try:
                    target.write_bytes(base64.b64decode(str(item.get("content") or "")))
                except Exception:
                    continue
            else:
                target.write_text(str(item.get("content") or ""), encoding="utf-8")
    else:
        (plugin_dir / "plugin.py").write_text(body.plugin_code, encoding="utf-8")

    # 热重载
    success = await reload_single_plugin(slug)
    _invalidate_tool_schema_cache(request)

    logger.info(f"[插件] 本地创建: {slug}, 热重载: {'成功' if success else '失败'}")
    return {
        "code": 0,
        "message": f"插件已创建并{'热重载成功' if success else '已创建（热重载失败，请检查代码语法）'}",
        "data": {"slug": slug, "name": body.name, "reloaded": success},
    }


# ════════════════════════════════════════════════════════════
# 插件日志 API（开发者调试用）
# ════════════════════════════════════════════════════════════


@router.get("/api/v1/plugins/{name}/logs")
async def get_plugin_logs(
    name: str,
    limit: int = Query(100, ge=1, le=500, description="返回条数（最新在前）"),
    level: str | None = Query(None, description="按级别过滤: debug/info/warn/error/stderr"),
    _admin=Depends(require_admin),
):
    """查询插件运行日志（加载错误、工具异常、SDK 错误、开发者自定义日志）。

    用法: GET /api/v1/plugins/weather/logs?limit=50&level=error
    """
    from src.infrastructure.plugin_log_store import get_logs
    entries = get_logs(name, limit=limit, level=level)
    return {"code": 0, "message": "ok", "data": entries}


@router.delete("/api/v1/plugins/{name}/logs")
async def clear_plugin_logs(name: str, _admin=Depends(require_admin)):
    """清空插件日志。"""
    from src.infrastructure.plugin_log_store import clear_logs
    count = clear_logs(name)
    return {"code": 0, "message": f"已清除 {count} 条日志", "data": {"cleared": count}}


# ════════════════════════════════════════════════════════════
# 可选插件 API（商店安装/卸载）
# ════════════════════════════════════════════════════════════


@router.get("/api/v1/plugins/optional")
async def list_optional_plugins(user=Depends(get_current_user_optional)):
    """列出所有可选插件（已安装的包括 enabled_plugins 状态）。

    可选插件是内置但默认不启用的插件，需用户从商店安装后使用。
    """
    from src.infrastructure.plugin_loader import get_optional_plugins_info

    plugins = get_optional_plugins_info()

    # 获取用户第一个设备的 enabled_plugins（未登录时返回空集合）
    enabled_set = set()
    if user:
        enabled_set = await _get_user_enabled_plugins(user)
    for p in plugins:
        p["installed"] = p["name"] in enabled_set

    return {"code": 0, "message": "ok", "data": plugins}


@router.post("/api/v1/plugins/optional/{name}/install")
async def install_optional_plugin(
    name: str,
    user=Depends(get_current_user),
    device_id: str | None = None,
):
    """安装可选插件（启用该插件在设备上的工具）。

    可选参数 device_id 指定目标设备，默认使用用户第一个设备。
    """
    from src.infrastructure.plugin_loader import is_optional_plugin, is_system_plugin

    if not is_optional_plugin(name):
        return {"code": 1, "message": f"插件「{name}」不是可选插件", "data": None}
    if is_system_plugin(name):
        return {"code": 1, "message": f"「{name}」是系统核心插件，随服务器提供，无需安装", "data": None}

    enabled = await _update_device_plugins(user, name, install=True, device_id=device_id)
    return {"code": 0, "message": f"「{name}」已安装", "data": {"enabled_plugins": sorted(enabled)}}


def _clear_plugin_data(plugin_name: str) -> None:
    """清空插件的所有配置数据（KV + 文件 + 数据库关联数据）。"""
    import os, shutil
    from src.infrastructure.plugin_loader import _PROJECT_ROOT

    # 1. KV 文件：按设备目录 glob 删除（data/plugins/kv/{device_id}/{plugin_name}.json）
    #    修复旧逻辑只删全局文件的 bug；同时保留全局文件清理（兼容单设备场景）
    kv_root = _PROJECT_ROOT / "data" / "plugins" / "kv"
    if kv_root.is_dir():
        for kv_file in kv_root.glob(f"*/{plugin_name}.json"):
            try:
                kv_file.unlink()
            except OSError as e:
                logger.warning(f"[卸载] 删除设备 KV 文件失败: {kv_file}: {e}")
    kv_path = kv_root / f"{plugin_name}.json"
    if kv_path.is_file():
        try:
            kv_path.unlink()
        except OSError:
            pass

    # 2. 插件数据目录
    data_dir = _PROJECT_ROOT / "data" / "plugins" / "data" / plugin_name
    if data_dir.is_dir():
        shutil.rmtree(data_dir, ignore_errors=True)

    # 3. 插件特有的全局数据
    if plugin_name == "wechat_bot":
        _clear_wechat_data(_PROJECT_ROOT)


def _clear_wechat_data(project_root) -> None:
    """清空微信插件特有的全局数据（统一数据文件）。"""
    import os, logging
    logger = logging.getLogger(__name__)

    # 删除统一数据文件
    data_file = project_root / "data" / "wechat_bot_data.json"
    if data_file.is_file():
        try:
            data_file.unlink()
            logger.info(f"[卸载] 已清除微信数据文件: {data_file}")
        except OSError as e:
            logger.warning(f"[卸载] 清除微信数据文件失败: {e}")

    # 清理旧格式遗留文件
    for old in ["wechat_token.json", "wechat_bindings.json"]:
        p = project_root / "data" / old
        if p.is_file():
            try:
                p.unlink()
            except OSError:
                pass

    # 重置内存中的微信绑定管理器
    try:
        from src.use_cases.wechat_binding import get_wechat_binding_manager
        mgr = get_wechat_binding_manager()
        for device_key in list(mgr._bindings.keys()):
            mgr.unbind(device_key)
        logger.info("[卸载] 已清空内存中的微信绑定关系")
    except Exception as e:
        logger.warning(f"[卸载] 清空内存微信绑定失败: {e}")


@router.post("/api/v1/plugins/optional/{name}/uninstall")
async def uninstall_optional_plugin(
    name: str,
    user=Depends(get_current_user),
    device_id: str | None = None,
):
    """卸载可选插件。

    系统插件（author=system 或提供 asr/llm/tts 核心服务）→ 拒绝卸载（核心服务，随服务器提供）。
    用户安装的插件 → 禁用 + 停止子进程 + 删除插件目录。
    """
    from src.infrastructure.plugin_loader import (
        is_optional_plugin,
        is_system_plugin,
        get_plugin_source,
        _unload_plugin,
    )
    from src.infrastructure.plugin_loader import INSTALLED_PLUGINS_DIR
    import shutil

    if not is_optional_plugin(name):
        return {"code": 1, "message": f"插件「{name}」不是可选插件", "data": None}
    if is_system_plugin(name):
        return {"code": 1, "message": f"「{name}」是系统核心插件，不可卸载", "data": None}

    # 先从设备禁用（当前用户的设备）
    enabled = await _update_device_plugins(user, name, install=False, device_id=device_id)

    # 从所有设备的 enabled_plugins 白名单移除该插件（清理失败不影响卸载主流程）
    try:
        affected = await _remove_plugin_from_all_devices(name)
        for dev_id in affected:
            try:
                from src.infrastructure.web import _hot_reload_device_config
                _hot_reload_device_config(dev_id)
            except Exception:
                pass
        if affected:
            logger.info(f"[卸载] 已从 {len(affected)} 个设备的启用列表移除插件: {name}")
    except Exception as e:
        logger.warning(f"[卸载] 清理设备启用列表失败（不影响卸载）: {e}")

    # 用户安装的插件：禁用 + 停止子进程 + 删除插件目录
    source = get_plugin_source(name)
    deleted = False
    if source == "installed":
        # 先停止插件子进程，避免 Windows 文件占用（WinError 32）
        await _unload_plugin(name)
        # 清空插件配置数据（KV + 数据目录）
        _clear_plugin_data(name)
        plugin_dir = INSTALLED_PLUGINS_DIR / name
        if plugin_dir.is_dir():
            # Windows 下文件句柄释放可能有延迟，重试删除
            for _attempt in range(5):
                try:
                    shutil.rmtree(plugin_dir)
                    deleted = True
                    break
                except OSError:
                    await asyncio.sleep(0.3)
            if not deleted:
                logger.warning(f"[卸载] 插件目录删除失败（文件占用）: {plugin_dir}")

    msg = f"「{name}」已卸载"
    if deleted:
        msg += "（插件目录已删除）"
    return {"code": 0, "message": msg, "data": {"enabled_plugins": sorted(enabled), "deleted": deleted}}


async def _get_user_enabled_plugins(user) -> set[str]:
    """获取用户第一个设备的 enabled_plugins 集合。"""
    from src.infrastructure.db.session import get_session_ctx
    from src.infrastructure.db.models.device import DeviceModel
    from sqlalchemy import select
    async with get_session_ctx() as session:
        result = await session.execute(
            select(DeviceModel).where(DeviceModel.user_id == user.id).limit(1)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return set()
        enabled = model.enabled_plugins or []
        return set(enabled)


async def _remove_plugin_from_all_devices(plugin_name: str) -> list[str]:
    """从所有设备的 enabled_plugins 白名单中移除该插件（卸载时调用，直接 DB 更新）。

    Returns:
        受影响的设备 device_id 列表（用于热重载在线设备）。
    """
    from src.infrastructure.db.session import get_session_ctx
    from src.infrastructure.db.models.device import DeviceModel
    from sqlalchemy import select

    affected: list[str] = []
    async with get_session_ctx() as session:
        result = await session.execute(select(DeviceModel))
        for model in result.scalars():
            enabled = model.enabled_plugins or []
            if plugin_name in enabled:
                model.enabled_plugins = [p for p in enabled if p != plugin_name]
                session.add(model)
                affected.append(model.device_id)
    return affected


async def _update_device_plugins(user, plugin_name: str, install: bool, device_id: str | None = None) -> list[str]:
    """为用户的设备添加/移除可选插件。"""
    from src.infrastructure.db.session import get_session_ctx
    from src.infrastructure.db.models.device import DeviceModel
    from sqlalchemy import select

    async with get_session_ctx() as session:
        if device_id:
            result = await session.execute(
                select(DeviceModel).where(
                    DeviceModel.device_id == device_id,
                    DeviceModel.user_id == user.id,
                )
            )
        else:
            result = await session.execute(
                select(DeviceModel).where(DeviceModel.user_id == user.id).limit(1)
            )
        model = result.scalar_one_or_none()
        if model is None:
            raise HTTPException(404, "设备不存在")

        enabled = set(model.enabled_plugins or [])
        if install:
            enabled.add(plugin_name)
        else:
            enabled.discard(plugin_name)

        model.enabled_plugins = list(enabled)
        session.add(model)

    # 热重载在线设备
    from src.infrastructure.web import _hot_reload_device_config
    _hot_reload_device_config(model.device_id)

    return list(enabled)
