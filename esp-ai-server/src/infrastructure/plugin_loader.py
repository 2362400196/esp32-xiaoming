"""插件加载器：扫描 plugins/ 目录，动态加载插件模块，支持热加载。

插件约定：
  src/plugins/<插件名>/plugin.py        # 内置插件
  data/plugins/installed/<插件名>/plugin.py  # 下载安装的插件
    - 模块内用 @tool() 装饰器定义 LLM 工具（tools_system.tool）
    - 加载后工具自动注册进全局工具表，无需改 builtin_tools.py

加载优先级：
  - 同名插件，INSTALLED_PLUGINS_DIR 优先于 PLUGINS_DIR（下载版本覆盖内置）
  - 每个插件目录必须包含 manifest.json，从中读取元数据（name/description/requires/config_fields 等）

热加载：
  - reload_plugins() 重新加载所有插件（先注销该插件旧工具，再重新执行模块）
  - reload_single_plugin(name) 仅重载单个插件（安装/更新后调用）
  - 服务器提供 POST /api/v1/plugins/reload 接口，改插件代码后无需重启服务器
  - 注意：仅模块级代码（@tool 注册）热生效；模块内持有的连接/单例不会重建
"""

import importlib.util
import sys
from pathlib import Path

from src.infrastructure.logging import get_logger
from src.use_cases.tools_system import get_all_tools, unregister_tool

logger = get_logger(__name__)

# 内置插件目录（随源码分发）
PLUGINS_DIR = Path(__file__).resolve().parent.parent / "plugins"

# 项目根目录（esp-ai-server/）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 下载安装的插件目录（运行时创建）
INSTALLED_PLUGINS_DIR = _PROJECT_ROOT / "data" / "plugins" / "installed"

# 插件包缓存目录（上传的 zip / 下载的 zip 临时存放）
PLUGINS_CACHE_DIR = _PROJECT_ROOT / "data" / "plugins" / "cache"

# 已加载插件 → 它注册的工具名列表（热加载时先注销旧工具，避免残留）
_loaded_tools: dict[str, list[str]] = {}

# 插件 → 能力声明（manifest.json 的 requires 字段，如 ["display"]）
# 用于设备级过滤：无屏设备自动隐藏 requires=display 插件的工具
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


def _load_plugin(plugin_name: str) -> bool:
    """加载单个插件模块（动态 import，@tool() 自动注册）。

    加载优先级：INSTALLED_PLUGINS_DIR > PLUGINS_DIR。
    每个插件目录必须包含 manifest.json，从中读取元数据；无 manifest.json 则跳过。

    Returns:
        是否成功加载
    """
    plugin_dir, source = _resolve_plugin_dir(plugin_name)
    if plugin_dir is None:
        logger.warning(f"[插件] 缺少 plugin.py: {plugin_name}")
        return False

    plugin_file = plugin_dir / "plugin.py"
    # 不同来源使用不同模块名前缀，避免 sys.modules 缓存冲突
    if source == "installed":
        module_name = f"esp_ai_installed_plugin_{plugin_name}"
    else:
        module_name = f"esp_ai_plugins_{plugin_name}"

    try:
        # 记录加载前的工具集合，加载后 diff 出本插件注册的工具
        before = set(get_all_tools().keys())
        # 将插件目录加入 sys.path，支持 plugin.py 同目录 import（如 import utils）
        if str(plugin_dir) not in sys.path:
            sys.path.insert(0, str(plugin_dir))
            _plugin_syspaths[plugin_name] = str(plugin_dir)
        spec = importlib.util.spec_from_file_location(module_name, plugin_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        after = set(get_all_tools().keys())
        _loaded_tools[plugin_name] = sorted(after - before)

        # 从 manifest.json 读取元数据
        manifest = None
        meta = {}
        try:
            from src.infrastructure.plugin_manifest import load_manifest_from_dir
            manifest = load_manifest_from_dir(plugin_dir)
        except Exception:
            manifest = None

        if manifest is not None:
            meta = manifest.to_meta_dict()
            _plugin_manifest[plugin_name] = manifest
            _plugin_version[plugin_name] = manifest.version
        else:
            logger.warning(f"[插件] {plugin_name} 无 manifest.json，元数据缺失")
            _plugin_version[plugin_name] = "1.0.0"

        _plugin_meta[plugin_name] = meta
        _plugin_source[plugin_name] = source
        _plugin_module_names[plugin_name] = module_name

        logger.info(
            f"[插件] 已加载: {plugin_name}（来源: {source}，版本: {_plugin_version[plugin_name]}，"
            f"工具: {_loaded_tools[plugin_name]}，"
            f"名称: {meta.get('name', plugin_name)}，requires={meta.get('requires', [])}）"
        )
        return True
    except Exception as e:
        logger.error(f"[插件] 加载失败 {plugin_name}: {e}")
        return False


def _unload_plugin(plugin_name: str) -> None:
    """注销插件注册过的工具（热加载前清理，避免残留旧版本工具）。

    同时从 sys.modules 移除模块缓存，确保下次 import 重新执行模块代码。
    """
    old_tools = _loaded_tools.pop(plugin_name, [])
    _plugin_meta.pop(plugin_name, None)
    _plugin_source.pop(plugin_name, None)
    _plugin_version.pop(plugin_name, None)
    _plugin_manifest.pop(plugin_name, None)
    module_name = _plugin_module_names.pop(plugin_name, None)

    removed = []
    for name in old_tools:
        if unregister_tool(name):
            removed.append(name)
    if removed:
        logger.info(f"[插件] 已卸载 {plugin_name} 的工具: {removed}")

    # 清理 sys.modules 缓存，确保重新加载时重新执行模块代码
    if module_name and module_name in sys.modules:
        del sys.modules[module_name]

    # 清理该插件加入的 sys.path（同目录 import 支持）
    added = _plugin_syspaths.pop(plugin_name, None)
    if added and added in sys.path:
        try:
            sys.path.remove(added)
        except ValueError:
            pass


def reload_single_plugin(plugin_name: str) -> bool:
    """重载单个插件（安装/更新后调用）。

    先卸载旧工具 → 再重新加载。返回是否成功。
    """
    if plugin_name in _loaded_tools:
        _unload_plugin(plugin_name)
    return _load_plugin(plugin_name)


def get_plugin_of_tool(tool_name: str) -> str | None:
    """工具名 → 所属插件名（无归属返回 None，内置工具不属于任何插件）。"""
    for plugin_name, tools in _loaded_tools.items():
        if tool_name in tools:
            return plugin_name
    return None


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
    """返回所有已加载插件的基本信息（名称、来源、版本）。

    供管理 API 展示已安装插件列表使用。
    """
    out = []
    for name in sorted(_loaded_tools.keys()):
        out.append({
            "name": name,
            "source": _plugin_source.get(name, "built-in"),
            "version": _plugin_version.get(name, "1.0.0"),
        })
    return out


def load_plugins() -> list[str]:
    """首次加载：扫描并加载所有插件，返回成功加载的插件名列表。

    扫描顺序：先 INSTALLED_PLUGINS_DIR（优先级高），再 PLUGINS_DIR。
    同名插件只加载一次（installed 优先）。
    """
    loaded = []
    seen: set[str] = set()

    # 1. 先扫描已安装插件（优先级高）
    if INSTALLED_PLUGINS_DIR.is_dir():
        for entry in sorted(INSTALLED_PLUGINS_DIR.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name in seen:
                continue
            if _load_plugin(entry.name):
                loaded.append(entry.name)
                seen.add(entry.name)
    else:
        logger.info(f"[插件] 已安装插件目录不存在，跳过: {INSTALLED_PLUGINS_DIR}")

    # 2. 再扫描内置插件（跳过已从 installed 加载的同名插件）
    if PLUGINS_DIR.is_dir():
        for entry in sorted(PLUGINS_DIR.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name in seen:
                # installed 版本已加载，记录覆盖日志
                logger.info(f"[插件] 内置插件 {entry.name} 已被 installed 版本覆盖，跳过")
                continue
            if _load_plugin(entry.name):
                loaded.append(entry.name)
                seen.add(entry.name)
    else:
        logger.info(f"[插件] 内置插件目录不存在，跳过: {PLUGINS_DIR}")

    return loaded


def reload_plugins() -> dict:
    """热加载：卸载全部插件旧工具 → 重新加载全部插件。

    返回统计信息供 HTTP 接口返回。
    """
    result = {"reloaded": [], "failed": [], "tools": []}

    # 1. 先卸载所有旧插件工具（清理残留）
    for plugin_name in list(_loaded_tools.keys()):
        _unload_plugin(plugin_name)

    # 2. 重新加载全部插件（先 installed，再 built-in）
    seen: set[str] = set()

    if INSTALLED_PLUGINS_DIR.is_dir():
        for entry in sorted(INSTALLED_PLUGINS_DIR.iterdir()):
            if not entry.is_dir() or entry.name in seen:
                continue
            if _load_plugin(entry.name):
                result["reloaded"].append(entry.name)
                seen.add(entry.name)
            else:
                result["failed"].append(entry.name)

    if PLUGINS_DIR.is_dir():
        for entry in sorted(PLUGINS_DIR.iterdir()):
            if not entry.is_dir() or entry.name in seen:
                continue
            if _load_plugin(entry.name):
                result["reloaded"].append(entry.name)
                seen.add(entry.name)
            else:
                result["failed"].append(entry.name)

    result["tools"] = sorted(get_all_tools().keys())
    return result
