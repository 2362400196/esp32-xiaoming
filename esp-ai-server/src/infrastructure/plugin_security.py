"""插件安全门禁（Plugin Security）。

三层防护：
    1. 静态审计（AST）：加载插件前扫描 plugin.py 及同目录模块，提取其实际
       使用的"危险能力集合"，与 manifest.permissions 声明比对——未声明的
       能力直接拒绝加载（比声明式权限强，因为审计的是真实代码行为）。
    2. 运行时守卫（contextvars）：插件工具执行时把当前插件的权限上下文
       注入 contextvar，SDK 层（http_request / send_device_command /
       get_ltm_service 等）据此做二次拦截，即使插件动态 import 绕过静态
       审计也无法越权调用 SDK 能力。
    3. 脱敏：对密钥类配置值提供掩码输出，防止日志/界面泄露。

权限模型（manifest.permissions 取值）：
    - network    出站网络访问（SDK http_request / http_get_json / 直接 httpx/requests/socket）
    - device     设备指令下发（SDK send_device_command / send_instruct / request_device_result）
    - ltm        长期记忆存取（SDK get_ltm_service）
    - file_read  读文件
    - file_write 写文件
    - subprocess 子进程执行
    - exec       动态代码执行（eval/exec/compile）
    - db         数据库访问（sqlite3/sqlalchemy 等）
    - env_read   读取环境变量

内置插件必须声明其 SDK 能力（network/device/ltm），官方插件仓库同规则。
"""

from __future__ import annotations

import ast
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


# ════════════════════════════════════════════════════════════
# 1. 静态审计（AST）
# ════════════════════════════════════════════════════════════

# SDK 提供的"受控能力"函数名：走这些入口的能力由运行时守卫按权限拦截，
# 不属于静态审计的危险 API（它们本身就是白名单通道）。
_SDK_FUNCTIONS = frozenset({
    "send_instruct", "send_device_command", "send_device_command_ack",
    "request_device_result", "get_plugin_config_or_env",
    "http_request", "http_get_json", "get_ltm_service", "get_default_ltm_service",
    "get_diary_repository", "get_device_repository", "skill_catalog_text",
    "get_device_key", "resolve_device_key", "mask_secret",
})

# 危险调用前缀（完整属性名）→ 所需权限。
# 匹配规则：某 AST 调用/属性的完整名以任此前缀开头即命中。
_DANGEROUS_ATTRS: dict[str, str] = {
    "httpx": "network",
    "requests": "network",
    "aiohttp": "network",
    "urllib.request": "network",
    "urlopen": "network",
    "socket": "network",
    "websockets": "network",
    "subprocess": "subprocess",
    "os.system": "subprocess",
    "os.popen": "subprocess",
    "os.spawn": "subprocess",
    "os.exec": "subprocess",
    "eval": "exec",
    "exec": "exec",
    "compile": "exec",
    "__import__": "exec",
    "sqlite3": "db",
    "sqlalchemy": "db",
    "psycopg": "db",
    "pymysql": "db",
    "MySQLdb": "db",
    "os.environ": "env_read",
    "os.getenv": "env_read",
}

# 精确函数名 → 所需权限（Call 的 func 为裸名时使用）
_DANGEROUS_FUNCS: dict[str, str] = {
    "eval": "exec",
    "exec": "exec",
    "compile": "exec",
    "urlopen": "network",
    "getenv": "env_read",
}

# 文件读写：仅当调用 open / Path.open / Path.read_*/write_* 时触发。
_FILE_READ_METHODS = ("read_text", "read_bytes", "readlines")
_FILE_WRITE_METHODS = ("write_text", "write_bytes", "touch", "unlink", "rename", "rmdir", "mkdir")


class _AuditVisitor(ast.NodeVisitor):
    """遍历 AST，收集插件实际使用的能力集合。"""

    def __init__(self) -> None:
        self.used: set[str] = set()

    def _attr_fullname(self, node: ast.AST) -> str:
        parts = []
        cur = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))

    def visit_Call(self, node: ast.Call) -> None:
        self._visit_call_target(node.func, node)
        self.generic_visit(node)

    def _visit_call_target(self, func: ast.AST, call: ast.Call) -> None:
        full = self._attr_fullname(func)
        if not full:
            return
        leaf = full.split(".")[-1]
        # SDK 通道豁免（运行时守卫负责按权限拦截）
        if leaf in _SDK_FUNCTIONS:
            return
        # 危险属性前缀匹配
        for prefix, perm in _DANGEROUS_ATTRS.items():
            if full.startswith(prefix) or full == prefix:
                self.used.add(perm)
                break
        # 裸函数名匹配
        if leaf in _DANGEROUS_FUNCS and "." not in full:
            self.used.add(_DANGEROUS_FUNCS[leaf])
        # open()：根据 mode 判断读/写
        if leaf == "open":
            mode = "r"
            if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
                mode = str(call.args[1].value)
            for kw in call.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode = str(kw.value.value)
            self.used.add("file_read")
            if any(c in mode for c in ("w", "a", "x", "+")):
                self.used.add("file_write")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        full = self._attr_fullname(node)
        # Path 对象方法：read_text/read_bytes/readlines 是读，write_* 是写
        if node.attr in _FILE_READ_METHODS:
            self.used.add("file_read")
        elif node.attr in _FILE_WRITE_METHODS:
            self.used.add("file_write")
        # os.environ / os.getenv 属性链
        if full in ("os.environ",) or full.startswith("os.environ."):
            self.used.add("env_read")
        if full.startswith("os.getenv"):
            self.used.add("env_read")
        self.generic_visit(node)


def audit_plugin_source(source: str) -> set[str]:
    """静态审计一段 Python 源码，返回其使用的能力集合。

    语法错误返回空集合（该插件后续会在 import 阶段被拒绝，审计不重复报错）。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    visitor = _AuditVisitor()
    visitor.visit(tree)
    return visitor.used


def audit_plugin_dir(plugin_dir: Path) -> dict[str, set[str]]:
    """静态审计插件目录下所有 .py 文件，返回 {文件名: 能力集合}。

    只审计插件目录内的模块；SDK（src/use_cases/_plugin_helpers.py）不在其中。
    """
    result: dict[str, set[str]] = {}
    if not plugin_dir.is_dir():
        return result
    for py in sorted(plugin_dir.glob("*.py")):
        try:
            result[py.name] = audit_plugin_source(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as e:
            result[py.name] = set()
            logger.warning(f"[插件安全] {py.name} 语法解析失败（加载阶段会再报错）: {e}")
    return result


def check_permissions(plugin_dir: Path, declared: list[str]) -> tuple[bool, list[str]]:
    """校验插件目录实际使用的能力是否全部声明在 manifest.permissions 中。

    Returns:
        (是否通过, 未声明的能力列表)
    """
    declared_set = set(declared or [])
    used: set[str] = set()
    for _fname, caps in audit_plugin_dir(plugin_dir).items():
        used |= caps
    undeclared = sorted(used - declared_set)
    return (not undeclared), undeclared


# ════════════════════════════════════════════════════════════
# 2. 运行时权限守卫（contextvars）
# ════════════════════════════════════════════════════════════


@dataclass
class PluginPermCtx:
    plugin: str
    permissions: frozenset[str]


_plugin_ctx: ContextVar[PluginPermCtx | None] = ContextVar(
    "plugin_perm_ctx", default=None
)


def set_plugin_context(plugin: str, permissions: list[str]) -> ContextVar[PluginPermCtx]:
    """进入插件工具执行上下文（工具执行前调用）。返回 token 供恢复。"""
    return _plugin_ctx.set(PluginPermCtx(plugin, frozenset(permissions or [])))


def reset_plugin_context(token) -> None:
    """退出插件工具执行上下文。"""
    _plugin_ctx.reset(token)


def current_plugin() -> PluginPermCtx | None:
    """当前正在执行的插件上下文（非插件调用返回 None）。"""
    return _plugin_ctx.get()


def require_permission(perm: str, what: str = "") -> None:
    """运行时权限检查（SDK 能力入口调用）。

    非插件调用（context 为空）不强制——允许 CLI/手动/内置工具使用。
    插件调用必须声明对应权限，否则抛 PermissionError。
    """
    ctx = _plugin_ctx.get()
    if ctx is None:
        return
    if perm not in ctx.permissions:
        detail = f"（{what}）" if what else ""
        raise PermissionError(
            f"插件「{ctx.plugin}」未声明 {perm} 权限，已阻止该操作{detail}"
        )


# ════════════════════════════════════════════════════════════
# 环境变量读取白名单（get_plugin_config_or_env 使用）
# ════════════════════════════════════════════════════════════

# 允许读取的环境变量前缀（全局），加上 <plugin_id>_ 前缀
_ALLOWED_ENV_PREFIXES = ("PLUGIN_",)


def env_var_allowed(plugin_id: str, env_var: str) -> bool:
    """环境变量读取白名单：仅允许插件命名空间（<plugin_id>_）或 PLUGIN_ 前缀。

    防止插件通过 get_plugin_config_or_env 读取任意敏感环境变量（API Key 等）。
    管理员可用 PLUGIN_ENV_ALLOWLIST（逗号分隔）显式放行个别变量（如 AMAP_WEATHER_KEY）。
    """
    if not env_var:
        return False
    upper = env_var.upper()
    if upper.startswith(f"{plugin_id.upper()}_") or upper.startswith(_ALLOWED_ENV_PREFIXES):
        return True
    import os
    allow = os.environ.get("PLUGIN_ENV_ALLOWLIST", "")
    if allow:
        return env_var.upper() in {v.strip().upper() for v in allow.split(",") if v.strip()}
    return False


# ════════════════════════════════════════════════════════════
# 3. 脱敏
# ════════════════════════════════════════════════════════════

_SECRET_SUFFIXES = ("key", "token", "secret", "password", "passwd", "appid", "secret_id", "secret_key")


def is_secret_key(key: str) -> bool:
    """判断配置键是否为敏感字段（按后缀约定 + 常见英文命名）。"""
    k = (key or "").lower().replace("-", "_")
    return any(k == s or k.endswith("_" + s) for s in _SECRET_SUFFIXES)


def mask_secret(value, visible=4) -> str:
    """掩码敏感值：只保留尾部可见字符，其余用 * 代替。

    "sk-abc123456" -> "**********3456"
    """
    s = str(value)
    if not s:
        return ""
    if len(s) <= visible:
        return "*" * len(s)
    return "*" * (len(s) - visible) + s[-visible:]


def mask_dict_secrets(data: dict) -> dict:
    """对字典中的敏感键值做脱敏（用于日志/接口展示）。"""
    out = {}
    for k, v in data.items():
        if is_secret_key(str(k)) and v:
            out[k] = mask_secret(v)
        else:
            out[k] = v
    return out
