"""插件加载器：扫描 plugins/ 目录，加载插件，支持热加载与子进程沙箱。

插件约定：
  src/plugins/<插件名>/plugin.py        # 内置插件（受信任，进程内加载）
  data/plugins/installed/<插件名>/plugin.py  # 下载安装的插件（不受信任，子进程沙箱）
    - 模块内用 @tool() 装饰器定义 LLM 工具（tools_system.tool）
    - 加载后工具自动注册进全局工具表，无需改 builtin_tools.py

安全模型：
  - 内置插件：进程内加载（随源码分发、代码审查可审计），运行时 contextvar 守卫
  - 已安装插件：独立子进程沙箱（import 白名单 + 审计钩子 + 文件命名空间 + SDK RPC
    权限裁决），与内置插件共用同一套权限模型（manifest.permissions）

加载优先级：
  - 同名插件，INSTALLED_PLUGINS_DIR 优先于 PLUGINS_DIR（下载版本覆盖内置）
  - 每个插件目录必须包含 manifest.json，从中读取元数据

热加载：
  - reload_plugins() 重新加载所有插件（先注销该插件旧工具，再重新执行模块）
  - reload_single_plugin(name) 仅重载单个插件（安装/更新后调用）
  - 服务器提供 POST /api/v1/plugins/reload 接口，改插件代码后无需重启服务器

注意：本模块的加载函数均为 async（子进程沙箱需要事件循环），调用方需 await。
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

from src.infrastructure.logging import get_logger
from src.use_cases.tools_system import (
    get_all_tools,
    get_tool,
    is_builtin_tool,
    register_tool,
    unregister_tool,
)

logger = get_logger(__name__)

# 内置插件目录（随源码分发）
PLUGINS_DIR = Path(__file__).resolve().parent.parent / "plugins"

# 项目根目录（esp-ai-server/）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 下载安装的插件目录（运行时创建）
INSTALLED_PLUGINS_DIR = _PROJECT_ROOT / "data" / "plugins" / "installed"

# 插件包缓存目录（上传的 zip / 下载的 zip 临时存放）
PLUGINS_CACHE_DIR = _PROJECT_ROOT / "data" / "plugins" / "cache"

# 插件运行日志持久化目录（plugin.log 文件存储，跨重启存活）
PLUGINS_STATE_DIR = _PROJECT_ROOT / "data" / "plugins" / "state"

# 已加载插件 → 它注册的工具名列表（热加载时先注销旧工具，避免残留）
_loaded_tools: dict[str, list[str]] = {}

# 插件 → 能力声明（manifest.json 的 requires 字段，如 ["display"]）
_plugin_meta: dict[str, dict] = {}

# 插件 → 来源标识（"built-in" / "installed"）
_plugin_source: dict[str, str] = {}

# 插件 → 版本号（manifest.json 的 version 字段）
_plugin_version: dict[str, str] = {}

# 插件 → PluginManifest 对象（所有插件都有）
_plugin_manifest: dict[str, object] = {}

# 插件 → importlib 模块名（卸载时从 sys.modules 清理，确保重新加载生效）
_plugin_module_names: dict[str, str] = {}

# 插件 → 已加入 sys.path 的目录（支持 plugin.py 同目录 import 其他模块）
_plugin_syspaths: dict[str, str] = {}

# 插件 → 是否为可选插件（manifest.json 的 optional: true，默认不安装）
_plugin_optional: dict[str, bool] = {}

# 工具名 → 所属插件名（避免重复遍历 _loaded_tools，且消除重名归属歧义）
_tool_owner: dict[str, str] = {}

# ── 服务插件注册表 ──────────────────────────────────────────
# service_type: str → {provider_name: plugin_name}
# 如 {"llm": {"openai": "llm_openai", "deepseek": "llm_deepseek"},
#     "tts": {"volcengine": "tts_volcengine"},
#     "asr": {"tencent": "asr_tencent"}}
_service_registry: dict[str, dict[str, str]] = {}


def register_service(service_type: str, provider_name: str, plugin_name: str) -> None:
    """注册服务插件到全局注册表。"""
    if service_type not in _service_registry:
        _service_registry[service_type] = {}
    _service_registry[service_type][provider_name] = plugin_name


def unregister_service(service_type: str, provider_name: str) -> None:
    """注销服务插件。"""
    providers = _service_registry.get(service_type)
    if providers:
        providers.pop(provider_name, None)
        if not providers:
            _service_registry.pop(service_type, None)


def get_service_plugin(service_type: str, provider_name: str | None = None) -> str | None:
    """获取服务插件名称。provider_name 为 None 时返回第一个注册的插件。"""
    providers = _service_registry.get(service_type)
    if not providers:
        return None
    if provider_name:
        return providers.get(provider_name)
    # 返回第一个注册的
    return next(iter(providers.values()))


def get_service_providers(service_type: str) -> list[str]:
    """获取某服务类型的所有已注册 Provider 名称列表。"""
    providers = _service_registry.get(service_type)
    return list(providers.keys()) if providers else []


def has_service_plugin(service_type: str) -> bool:
    """检查是否有某类型的服务插件已注册。"""
    return service_type in _service_registry and bool(_service_registry[service_type])


def _register_plugin_services(plugin_name: str, manifest: object) -> None:
    """从 manifest 的 provides 字段注册服务。"""
    provides = getattr(manifest, "provides", None) or {}
    if not provides:
        return
    for service_type, providers in provides.items():
        for provider_name in providers:
            register_service(service_type, provider_name, plugin_name)
            logger.info(
                f"[插件服务] {plugin_name} 注册 {service_type} 服务: {provider_name}"
            )


def _unregister_plugin_services(plugin_name: str, manifest: object) -> None:
    """从 manifest 的 provides 字段注销服务。"""
    provides = getattr(manifest, "provides", None) or {}
    if not provides:
        return
    for service_type, providers in provides.items():
        for provider_name in providers:
            unregister_service(service_type, provider_name)
            logger.info(
                f"[插件服务] {plugin_name} 注销 {service_type} 服务: {provider_name}"
            )


def _resolve_plugin_dir(plugin_name: str) -> tuple[Path | None, str]:
    """解析插件目录：优先 installed，其次 built-in。

    Returns:
        (plugin_dir, source) 或 (None, "") 表示未找到
    """
    installed_dir = INSTALLED_PLUGINS_DIR / plugin_name
    if (installed_dir / "plugin.py").is_file():
        return installed_dir, "installed"
    builtin_dir = PLUGINS_DIR / plugin_name
    if (builtin_dir / "plugin.py").is_file():
        return builtin_dir, "built-in"
    return None, ""


def _security_gate(plugin_name: str, plugin_dir: Path) -> bool:
    """加载前安全门禁：静态审计 + 签名校验。失败返回 False。"""
    try:
        from src.infrastructure.plugin_security import check_permissions
        from src.infrastructure.plugin_manifest import load_manifest_from_dir
        manifest_pre = load_manifest_from_dir(plugin_dir)
        declared_perms = list(getattr(manifest_pre, "permissions", None) or [])
        audit_ok, undeclared = check_permissions(plugin_dir, declared_perms)
        if not audit_ok:
            logger.error(
                f"[插件安全] {plugin_name} 使用了未声明的能力 {undeclared}，拒绝加载。"
                f"请在 manifest.json 的 permissions 中声明。"
            )
            return False
        if manifest_pre is not None and not manifest_pre.verify_package(plugin_dir):
            logger.error(
                f"[插件安全] {plugin_name} v{manifest_pre.version} 签名/文件校验失败，拒绝加载"
            )
            return False
    except Exception as e:
        logger.error(f"[插件安全] 插件 {plugin_name} 加载前校验异常: {e}")
        return False
    return True


async def _load_plugin(plugin_name: str) -> bool:
    """加载单个插件（installed 走子进程沙箱，built-in 走进程内加载）。

    Returns:
        是否成功加载
    """
    plugin_dir, source = _resolve_plugin_dir(plugin_name)
    if plugin_dir is None:
        logger.warning(f"[插件] 缺少 plugin.py: {plugin_name}")
        return False

    plugin_file = plugin_dir / "plugin.py"

    # ── 安全门禁 1：静态审计 + 签名校验（在 import 执行前）──
    if not _security_gate(plugin_name, plugin_dir):
        return False

    # 加载该插件的历史日志到内存（跨重启存活）
    try:
        from src.infrastructure.plugin_log_store import load_all_from_file
        load_all_from_file(plugin_name)
    except Exception:
        pass

    # ── 安全门禁 2：工具名冲突检测（AST 提取声明工具名，与其它插件及系统工具比对）──
    try:
        declared_tools = _extract_tool_names(plugin_file)
        conflicts = []
        for t in declared_tools:
            if t in _tool_owner and _tool_owner[t] != plugin_name:
                conflicts.append((t, f"插件 {_tool_owner[t]}"))
            elif is_builtin_tool(t):
                conflicts.append((t, "系统/内置工具"))
        if conflicts:
            logger.error(
                f"[插件] {plugin_name} 的工具名 {[c[0] for c in conflicts]} "
                f"已被占用（{sorted({c[1] for c in conflicts})}），拒绝加载"
            )
            return False
    except SyntaxError as e:
        logger.error(f"[插件] {plugin_name} plugin.py 语法错误: {e}")
        return False

    if source == "installed":
        return await _load_installed_plugin(plugin_name, plugin_dir)
    return _load_builtin_plugin(plugin_name, plugin_dir, plugin_file)


def _load_builtin_plugin(plugin_name: str, plugin_dir: Path, plugin_file: Path) -> bool:
    """内置插件：进程内加载（受信任，仅做权限上下文守卫）。"""
    module_name = f"esp_ai_plugins_{plugin_name}"
    try:
        before = set(get_all_tools().keys())
        if str(plugin_dir) not in sys.path:
            sys.path.insert(0, str(plugin_dir))
            _plugin_syspaths[plugin_name] = str(plugin_dir)
        spec = importlib.util.spec_from_file_location(module_name, plugin_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        after = set(get_all_tools().keys())
        _loaded_tools[plugin_name] = sorted(after - before)

        for tname in _loaded_tools[plugin_name]:
            _tool_owner[tname] = plugin_name

        _record_meta(plugin_name, plugin_dir)
        _register_plugin_services(plugin_name, _plugin_manifest.get(plugin_name))
        logger.info(
            f"[插件] 已加载: {plugin_name}（来源: built-in，版本: {_plugin_version[plugin_name]}，"
            f"工具: {_loaded_tools[plugin_name]}，名称: {_plugin_meta[plugin_name].get('name', plugin_name)}）"
        )
        return True
    except Exception as e:
        logger.error(f"[插件] 加载失败 {plugin_name}: {e}")
        return False


async def _load_installed_plugin(plugin_name: str, plugin_dir: Path) -> bool:
    """已安装插件：子进程沙箱加载（不可信代码在独立进程内执行）。"""
    from src.infrastructure.plugin_host.supervisor import get_plugin_supervisor
    from src.infrastructure.plugin_manifest import load_manifest_from_dir

    manifest = load_manifest_from_dir(plugin_dir)
    supervisor = get_plugin_supervisor()
    tools = await supervisor.load_plugin(plugin_name, plugin_dir, manifest)
    if not tools:
        logger.error(f"[插件] 沙箱加载失败 {plugin_name}")
        return False

    _loaded_tools[plugin_name] = sorted(tools)
    for t in tools:
        _tool_owner[t] = plugin_name
    _record_meta(plugin_name, plugin_dir)
    _register_plugin_services(plugin_name, _plugin_manifest.get(plugin_name))
    logger.info(
        f"[插件] 已加载: {plugin_name}（来源: installed，版本: {_plugin_version[plugin_name]}，"
        f"工具: {_loaded_tools[plugin_name]}，名称: {_plugin_meta[plugin_name].get('name', plugin_name)}，沙箱运行）"
    )
    return True


def _record_meta(plugin_name: str, plugin_dir: Path) -> None:
    """从 manifest.json 记录插件元数据。"""
    from src.infrastructure.plugin_manifest import load_manifest_from_dir

    manifest = load_manifest_from_dir(plugin_dir)
    if manifest is not None:
        _plugin_manifest[plugin_name] = manifest
        _plugin_meta[plugin_name] = manifest.to_meta_dict()
        _plugin_version[plugin_name] = manifest.version
        _plugin_optional[plugin_name] = manifest.optional
    else:
        logger.warning(f"[插件] {plugin_name} 无 manifest.json，元数据缺失")
        _plugin_meta[plugin_name] = {}
        _plugin_version[plugin_name] = "1.0.0"
        _plugin_optional[plugin_name] = False
    _plugin_source[plugin_name] = "installed" if (INSTALLED_PLUGINS_DIR / plugin_name).is_dir() else "built-in"
    _plugin_module_names[plugin_name] = (
        f"esp_ai_installed_plugin_{plugin_name}"
        if _plugin_source[plugin_name] == "installed"
        else f"esp_ai_plugins_{plugin_name}"
    )


async def _unload_plugin(plugin_name: str) -> None:
    """注销插件注册过的工具（热加载前清理，避免残留旧版本工具）。

    内置插件：注销工具 + 清理 sys.modules / sys.path。
    已安装插件：停止子进程沙箱 + 注销工具。
    """
    old_tools = _loaded_tools.pop(plugin_name, [])
    old_source = _plugin_source.pop(plugin_name, None)
    old_manifest = _plugin_manifest.pop(plugin_name, None)
    _plugin_meta.pop(plugin_name, None)
    _plugin_version.pop(plugin_name, None)
    _plugin_optional.pop(plugin_name, None)
    module_name = _plugin_module_names.pop(plugin_name, None)

    # 注销服务注册
    if old_manifest is not None:
        _unregister_plugin_services(plugin_name, old_manifest)

    if old_source == "installed" or (INSTALLED_PLUGINS_DIR / plugin_name).is_dir():
        try:
            from src.infrastructure.plugin_host.supervisor import get_plugin_supervisor
            await get_plugin_supervisor().unload_plugin(plugin_name)
        except Exception as e:
            logger.warning(f"[插件] 停止沙箱进程异常 {plugin_name}: {e}")

    removed = []
    for name in old_tools:
        if unregister_tool(name):
            removed.append(name)
            if _tool_owner.get(name) == plugin_name:
                _tool_owner.pop(name, None)
    if removed:
        logger.info(f"[插件] 已卸载 {plugin_name} 的工具: {removed}")

    if module_name and module_name in sys.modules:
        del sys.modules[module_name]

    added = _plugin_syspaths.pop(plugin_name, None)
    if added and added in sys.path:
        try:
            sys.path.remove(added)
        except ValueError:
            pass


async def reload_single_plugin(plugin_name: str) -> bool:
    """重载单个插件（安装/更新后调用）。

    先卸载旧工具 → 再重新加载。返回是否成功。
    """
    if plugin_name in _loaded_tools:
        await _unload_plugin(plugin_name)
    return await _load_plugin(plugin_name)


def get_plugin_of_tool(tool_name: str) -> str | None:
    """工具名 → 所属插件名（无归属返回 None，内置工具不属于任何插件）。"""
    return _tool_owner.get(tool_name)


def get_plugin_requires(plugin_name: str) -> list[str]:
    """插件的能力要求（manifest.json 的 requires 字段，如 ["display"]）。"""
    return list(_plugin_meta.get(plugin_name, {}).get("requires", []) or [])


def get_loaded_plugins() -> list[str]:
    return list(_loaded_tools.keys())


def get_plugin_source(plugin_name: str) -> str:
    """获取插件来源（"built-in" / "installed"）。未加载返回 "built-in"。"""
    return _plugin_source.get(plugin_name, "built-in")


def get_plugin_version(plugin_name: str) -> str:
    """获取插件版本号。未加载返回 "1.0.0"。"""
    return _plugin_version.get(plugin_name, "1.0.0")


def get_plugin_manifest(plugin_name: str):
    """获取插件 manifest 对象（无 manifest 返回 None）。"""
    return _plugin_manifest.get(plugin_name)


def is_builtin_plugin(plugin_name: str) -> bool:
    """判断插件是否为内置插件（不可卸载）。

    内置插件指 src/plugins/ 目录下的插件。
    """
    builtin_dir = PLUGINS_DIR / plugin_name
    return (builtin_dir / "plugin.py").is_file()


def is_installed_plugin(plugin_name: str) -> bool:
    """判断插件是否为已安装插件（data/plugins/installed/ 目录下）。"""
    installed_dir = INSTALLED_PLUGINS_DIR / plugin_name
    return installed_dir.is_dir()


def _available_plugins_info() -> list[dict]:
    """返回所有已加载插件的基本信息（名称、来源、版本）。"""
    out = []
    for name in sorted(_loaded_tools.keys()):
        out.append({
            "name": name,
            "source": _plugin_source.get(name, "built-in"),
            "version": _plugin_version.get(name, "1.0.0"),
        })
    return out


def is_optional_plugin(plugin_name: str) -> bool:
    """判断插件是否为可选插件（manifest.json 声明了 optional: true）。"""
    return _plugin_optional.get(plugin_name, False)


def get_optional_plugins_info() -> list[dict]:
    """返回所有可选插件的信息（含元数据）。"""
    out = []
    for name in sorted(_plugin_optional.keys()):
        if _plugin_optional.get(name):
            meta = _plugin_meta.get(name, {})
            out.append({
                "name": name,
                "version": _plugin_version.get(name, "1.0.0"),
                "source": _plugin_source.get(name, "built-in"),
                "title": meta.get("name", name),
                "description": meta.get("description", ""),
                "requires": meta.get("requires", []),
                "config_fields": meta.get("config_fields", []),
            })
    return out


async def load_plugins() -> list[str]:
    """首次加载：扫描并加载所有插件，返回成功加载的插件名列表。

    扫描顺序：先 INSTALLED_PLUGINS_DIR（优先级高），再 PLUGINS_DIR。
    同名插件只加载一次（installed 优先）。
    """
    loaded = []
    seen: set[str] = set()

    # 初始化插件日志持久化目录，并加载历史日志到内存
    PLUGINS_STATE_DIR.mkdir(parents=True, exist_ok=True)
    from src.infrastructure.plugin_log_store import set_state_dir
    set_state_dir(str(PLUGINS_STATE_DIR))

    if INSTALLED_PLUGINS_DIR.is_dir():
        for entry in sorted(INSTALLED_PLUGINS_DIR.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name in seen:
                continue
            if await _load_plugin(entry.name):
                loaded.append(entry.name)
                seen.add(entry.name)
    else:
        logger.info(f"[插件] 已安装插件目录不存在，跳过: {INSTALLED_PLUGINS_DIR}")

    if PLUGINS_DIR.is_dir():
        for entry in sorted(PLUGINS_DIR.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name in seen:
                logger.info(f"[插件] 内置插件 {entry.name} 已被 installed 版本覆盖，跳过")
                continue
            if await _load_plugin(entry.name):
                loaded.append(entry.name)
                seen.add(entry.name)
    else:
        logger.info(f"[插件] 内置插件目录不存在，跳过: {PLUGINS_DIR}")

    return loaded


async def reload_plugins() -> dict:
    """热加载：卸载全部插件旧工具 → 重新加载全部插件（事务回滚）。

    任一插件加载失败时，自动回滚恢复该插件之前的工具注册，
    避免"部分插件丢失"导致系统处于半损坏状态。

    返回统计信息供 HTTP 接口返回。
    """
    result = {"reloaded": [], "failed": [], "rolled_back": [], "tools": []}

    snapshot = _snapshot_registry()

    for plugin_name in list(_loaded_tools.keys()):
        await _unload_plugin(plugin_name)

    seen: set[str] = set()

    if INSTALLED_PLUGINS_DIR.is_dir():
        for entry in sorted(INSTALLED_PLUGINS_DIR.iterdir()):
            if not entry.is_dir() or entry.name in seen:
                continue
            if await _load_plugin(entry.name):
                result["reloaded"].append(entry.name)
                seen.add(entry.name)
            else:
                result["failed"].append(entry.name)

    if PLUGINS_DIR.is_dir():
        for entry in sorted(PLUGINS_DIR.iterdir()):
            if not entry.is_dir() or entry.name in seen:
                continue
            if await _load_plugin(entry.name):
                result["reloaded"].append(entry.name)
                seen.add(entry.name)
            else:
                result["failed"].append(entry.name)

    if result["failed"]:
        _restore_registry(snapshot, failed_names=set(result["failed"]))
        result["rolled_back"] = list(result["failed"])

    result["tools"] = sorted(get_all_tools().keys())
    return result


# ──────────────────────────────────────────────────────────
# 事务回滚辅助
# ──────────────────────────────────────────────────────────

def _snapshot_registry() -> dict:
    """快照当前插件注册状态（工具对象 + 插件元数据）。"""
    return {
        "tools": {name: get_tool(name) for name in list(get_all_tools().keys())},
        "loaded_tools": {k: list(v) for k, v in _loaded_tools.items()},
        "tool_owner": dict(_tool_owner),
        "plugin_meta": {k: dict(v) for k, v in _plugin_meta.items()},
        "plugin_source": dict(_plugin_source),
        "plugin_version": dict(_plugin_version),
        "plugin_manifest": dict(_plugin_manifest),
        "plugin_module_names": dict(_plugin_module_names),
        "plugin_syspaths": dict(_plugin_syspaths),
    }


def _restore_registry(snapshot: dict, failed_names: set[str]) -> None:
    """回滚失败的插件：恢复其加载前注册的工具与插件元数据。

    成功加载的插件不受影响（保留新版本）。
    """
    for plugin_name in failed_names:
        current_tools = _loaded_tools.pop(plugin_name, [])
        for t in current_tools:
            unregister_tool(t)
            if _tool_owner.get(t) == plugin_name:
                _tool_owner.pop(t, None)
        old_tools = snapshot["loaded_tools"].get(plugin_name, [])
        for t in old_tools:
            td = snapshot["tools"].get(t)
            if td is not None:
                register_tool(td)
            _tool_owner[t] = plugin_name
        if old_tools:
            _loaded_tools[plugin_name] = list(old_tools)
        if plugin_name in snapshot["plugin_meta"]:
            _plugin_meta[plugin_name] = dict(snapshot["plugin_meta"][plugin_name])
        if plugin_name in snapshot["plugin_source"]:
            _plugin_source[plugin_name] = snapshot["plugin_source"][plugin_name]
        if plugin_name in snapshot["plugin_version"]:
            _plugin_version[plugin_name] = snapshot["plugin_version"][plugin_name]
        if plugin_name in snapshot["plugin_manifest"]:
            _plugin_manifest[plugin_name] = snapshot["plugin_manifest"][plugin_name]
        if plugin_name in snapshot["plugin_module_names"]:
            _plugin_module_names[plugin_name] = snapshot["plugin_module_names"][plugin_name]
        if plugin_name in snapshot["plugin_syspaths"]:
            _plugin_syspaths[plugin_name] = snapshot["plugin_syspaths"][plugin_name]
    if failed_names:
        logger.warning(
            f"[插件] 热加载失败已回滚: {sorted(failed_names)}"
        )


# ──────────────────────────────────────────────────────────
# AST 工具名提取（加载前冲突检测）
# ──────────────────────────────────────────────────────────

def _extract_tool_names(plugin_file: Path) -> list[str]:
    """解析 plugin.py，提取 @tool(...) 装饰器声明的工具名（不执行代码）。

    工具名 = 装饰器 name= 参数（若提供）否则函数名。
    """
    source = plugin_file.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(source)
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            dname = ""
            if isinstance(dec, ast.Call):
                target = dec.func
            else:
                target = dec
            if isinstance(target, ast.Name):
                dname = target.id
            elif isinstance(target, ast.Attribute):
                dname = target.attr
            if dname != "tool":
                continue
            tool_name = node.name
            if isinstance(dec, ast.Call):
                for kw in dec.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                        tool_name = str(kw.value.value)
            names.append(tool_name)
    return names