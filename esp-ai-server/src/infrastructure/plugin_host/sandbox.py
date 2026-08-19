"""子进程沙箱运行时防护（在插件子进程内生效）。

功能：
    1. 环境变量擦除：子进程只保留系统运行必需变量，插件无法读取服务器敏感
       环境变量（API Key 等）。
    2. sys.meta_path import 钩子：插件只能 import 受限标准库 / SDK 桩 /
       插件自带模块，禁止 importlib/ctypes/marshal/subprocess/socket/httpx
       及服务器内部模块。
    3. sys.addaudithook：拦截 os.system/subprocess/open/socket 等危险系统调用，
       即使插件通过动态构造/反射绕过 import 检查也无法越权。
    4. 文件系统命名空间：文件读写仅允许落在插件目录与专属状态目录内。

本模块只依赖标准库，保证子进程可独立启动。
"""

from __future__ import annotations

import builtins
import importlib.machinery
import importlib.util
import os
import site
import sys
from pathlib import Path
from typing import Any

# ════════════════════════════════════════════════════════════
# 1. 环境变量擦除
# ════════════════════════════════════════════════════════════

# 允许保留的环境变量（系统运行必需；不含任何服务器业务密钥）
_KEEP_ENV = frozenset({
    "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE",
    "HOMEPATH", "PATHEXT", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS",
    "PYTHONPATH", "PYTHONIOENCODING", "COMSPEC", "LC_ALL", "LANG", "TZ",
    "HOME", "APPDATA", "LOCALAPPDATA", "COMPUTERNAME", "USERNAME", "SESSIONNAME",
})

# 显式禁止的模块（即使落在系统路径内也拒绝）
_BLOCKED_MODULES = frozenset({
    "importlib", "importlib.util", "importlib.machinery", "importlib.abc",
    "importlib.metadata", "importlib.resources",
    "ctypes", "marshal", "pickle", "shelve",
    "subprocess", "multiprocessing", "socket", "ssl",
    "http.client", "http.server", "urllib.request", "urllib.response",
    "httpx", "requests", "aiohttp", "urllib3", "websockets", "websocket",
    "sqlite3", "sqlalchemy", "pymysql", "psycopg", "psycopg2", "MySQLdb", "aiomysql",
    "shutil", "tempfile", "pty", "pwd", "grp", "spwd", "resource", "pdb",
    "distutils", "setuptools", "pip", "site", "runpy", "trace",
    "smtplib", "ftplib", "telnetlib", "imaplib", "poplib",
    "msvcrt", "curses", "tkinter", "winreg",
    "zipfile", "tarfile", "gzip", "bz2", "lzma", "zlib",
    "configparser", "email", "platform", "gc", "signal",
})

# 直接放行的 stdlib 顶层模块（免于路径探测，快路径）
_ALLOWED_MODULES = frozenset({
    "json", "re", "datetime", "time", "uuid", "math", "random", "string",
    "collections", "functools", "itertools", "typing", "dataclasses", "enum",
    "decimal", "statistics", "hashlib", "hmac", "base64", "urllib",
    "html", "textwrap", "unicodedata", "calendar", "bisect", "heapq",
    "operator", "copy", "asyncio", "contextlib", "inspect", "traceback",
    "warnings", "copyreg", "numbers", "abc", "array", "binascii", "codecs",
    "fractions", "gettext", "keyword", "locale", "logging", "pathlib", "os",
    "io", "code", "dis", "errno", "stat", "stringprep", "struct", "sys",
    "types", "weakref", "atexit", "argparse", "threading", "_thread",
    "timeit", "textwrap", "difflib", "csv", "pprint", "secrets",
})

# 服务器内部模块前缀：插件一律禁止导入（SDK 由桩模块在 sys.modules 提供）
_SERVER_PREFIXES = ("src.", "src")

# 原始 sys.meta_path（安装沙箱前保存，用于探测模块位置而不触发本钩子）
_ORIGINAL_META_PATH = list(sys.meta_path)

# 安装后允许放行的额外模块名（由 SDK 桩注册，如 src.use_cases.tools_system）
_ALLOWED_EXTRA: set[str] = set()


def set_allowed_extra(names: list[str]) -> None:
    """注册允许导入的额外模块名（SDK 桩模块）。"""
    _ALLOWED_EXTRA.update(names)


def _is_stdlib_origin(origin: str | None) -> bool:
    """判断模块 origin 是否属于标准库目录（非 site-packages）。"""
    if not origin:
        return False
    try:
        origin = os.path.realpath(origin)
    except Exception:
        return False
    stdlib_dirs = []
    for base in (sys.base_prefix, sys.prefix):
        lib = os.path.join(base, "Lib") if os.name == "nt" else os.path.join(base, "lib")
        stdlib_dirs.append(lib)
    # 项目根（PYTHONPATH 中的服务器源码）也在白名单之外
    for lib in stdlib_dirs:
        if origin.startswith(lib):
            # 排除 site-packages（第三方库）
            for sp in site.getsitepackages():
                if origin.startswith(os.path.realpath(sp)):
                    return False
            usersp = site.getusersitepackages()
            if usersp and origin.startswith(os.path.realpath(usersp)):
                return False
            return True
    return False


def scrub_environment() -> list[str]:
    """清空环境变量，只保留系统运行必需项。返回被删除的键。"""
    removed = [k for k in list(os.environ.keys()) if k not in _KEEP_ENV]
    for k in removed:
        try:
            del os.environ[k]
        except KeyError:
            pass
    return removed


# ════════════════════════════════════════════════════════════
# 2. import 白名单钩子
# ════════════════════════════════════════════════════════════


class SandboxImportError(ImportError):
    """插件尝试导入被禁止的模块时抛出。"""


class _SandboxMetaPathFinder:
    """sys.meta_path 查找器：拦截插件对非白名单模块的导入。

    放行规则（依次）：
        1. 白名单 stdlib 顶层 → 交给默认查找器
        2. 插件自带模块（plugin_dir 下 .py）→ 放行
        3. 服务器内部模块（src.*）→ 拒绝
        4. 显式黑名单 → 拒绝
        5. 其余模块：用原始查找器探测，仅当落在标准库目录（非 site-packages）
           或插件目录内才放行；否则拒绝（拦截任意第三方库）。
    """

    def __init__(self, plugin_dir: Path) -> None:
        self.plugin_dir = str(plugin_dir.resolve())
        self._plugin_modules = {
            p.stem for p in plugin_dir.glob("*.py") if p.name != "__init__.py"
        }

    def find_spec(self, fullname, path=None, target=None):
        top = fullname.split(".")[0]
        # 1. 白名单 stdlib 快路径
        if top in _ALLOWED_MODULES or fullname in _ALLOWED_MODULES:
            return None
        # 2. 插件自带模块 / SDK 桩
        if fullname in self._plugin_modules or fullname in _ALLOWED_EXTRA:
            return None
        # 3. 服务器内部模块一律拒绝
        if fullname == "src" or fullname.startswith(_SERVER_PREFIXES[0]):
            raise SandboxImportError(f"插件禁止导入服务器内部模块: {fullname}")
        # 4. 显式黑名单
        if fullname in _BLOCKED_MODULES or top in _BLOCKED_MODULES:
            raise SandboxImportError(f"插件禁止导入模块: {fullname}")
        # 5. 用原始查找器探测模块位置
        for finder in _ORIGINAL_META_PATH:
            if finder is self:
                continue
            try:
                spec = finder.find_spec(fullname, path, target)
            except (ImportError, AttributeError, TypeError, ValueError):
                continue
            if spec is None:
                continue
            origin = getattr(spec, "origin", None)
            if origin and (_is_stdlib_origin(origin) or origin.startswith(self.plugin_dir)):
                return None
            raise SandboxImportError(
                f"插件禁止导入第三方/未知模块: {fullname}（{origin}）"
            )
        # 未找到 → 交给默认行为（ModuleNotFoundError）
        return None


# ════════════════════════════════════════════════════════════
# 3. 审计钩子（拦截危险系统调用）
# ════════════════════════════════════════════════════════════

_ALLOWED_FS_ROOTS: list[str] = []
_PLUGIN_ROOT: str = ""
_STATE_ROOT: str = ""


class SandboxAuditError(Exception):
    """审计钩子拦截了危险操作。"""


def _in_root(path: Any, root: str) -> bool:
    try:
        real = os.path.realpath(path)
    except Exception:
        return False
    return real == root or real.startswith(root + os.sep)


def _path_allowed(path: Any) -> bool:
    return any(_in_root(path, root) for root in _ALLOWED_FS_ROOTS)


def _is_write_mode(mode: Any, flags: Any) -> bool:
    if isinstance(mode, str) and any(c in mode for c in "wax+"):
        return True
    if isinstance(flags, int) and flags & (
        os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
    ):
        return True
    return False


def install_audit_hook(plugin_root: str, state_root: str, allow_file: bool) -> None:
    """安装 sys.addaudithook，拦截危险系统调用。

    Args:
        plugin_root: 插件目录（读取自身代码/自带数据始终放行）。
        state_root: 插件专属状态目录。
        allow_file: 是否声明了 file_read/file_write 权限（未声明时只能读取
            插件自身目录，任何写入与状态目录访问都会被拦截）。
    """
    global _ALLOWED_FS_ROOTS, _PLUGIN_ROOT, _STATE_ROOT
    _PLUGIN_ROOT = os.path.realpath(plugin_root)
    _STATE_ROOT = os.path.realpath(state_root)
    _ALLOWED_FS_ROOTS = [_PLUGIN_ROOT, _STATE_ROOT]

    def _is_stdlib_path(path: Any) -> bool:
        """判断路径是否位于标准库目录（import stdlib 模块时读取源码/字节码）。"""
        try:
            real = os.path.realpath(path)
        except Exception:
            return False
        stdlib_dirs = []
        for base in (sys.base_prefix, sys.prefix):
            lib = os.path.join(base, "Lib") if os.name == "nt" else os.path.join(base, "lib")
            stdlib_dirs.append(lib)
            stdlib_dirs.append(os.path.join(base, "Lib", "site-packages"))
        for lib in stdlib_dirs[:-1]:
            if real == lib or real.startswith(lib + os.sep):
                for sp in site.getsitepackages():
                    if real.startswith(os.path.realpath(sp)):
                        return False
                return True
        return False

    def _read_allowed(path: Any) -> bool:
        # 插件自身目录读取始终放行；状态目录读取需声明 file_read/file_write；
        # 标准库源码读取放行（import stdlib 模块的必经路径）
        return (_in_root(path, _PLUGIN_ROOT)
                or _is_stdlib_path(path)
                or (allow_file and _path_allowed(path)))

    def _hook(event: str, args: tuple[Any, ...]) -> None:
        if event == "open":
            if not args:
                return
            path = args[0]
            write = _is_write_mode(
                args[1] if len(args) > 1 else "r",
                args[2] if len(args) > 2 else 0,
            )
            if write:
                if not allow_file:
                    raise SandboxAuditError("插件未声明 file_write 权限，禁止写入文件")
                if not _path_allowed(path):
                    raise SandboxAuditError(f"写入操作超出沙箱目录: {path!r}")
            else:
                if not _read_allowed(path):
                    raise SandboxAuditError(
                        "插件未声明 file_read/file_write 权限，禁止读取该文件"
                    )
        elif event in ("os.system",):
            raise SandboxAuditError("沙箱禁止 os.system")
        elif event.startswith("subprocess.") or event.startswith("os.spawn") \
                or event.startswith("os.exec") or event == "os.posix_spawn":
            raise SandboxAuditError(f"沙箱禁止子进程/进程执行: {event}")
        elif event == "socket.__new__":
            raise SandboxAuditError("沙箱禁止 socket 连接")
        elif event.startswith("os.path.exists") or event.startswith("os.stat"):
            if args and not _read_allowed(args[0]):
                raise SandboxAuditError(
                    "插件未声明 file_read/file_write 权限，禁止访问该路径"
                )
        elif event in ("os.remove", "os.unlink", "os.rmdir", "os.removedirs",
                       "os.rename", "os.replace", "os.chmod", "os.chown",
                       "os.mkdir", "os.makedirs"):
            if not allow_file:
                raise SandboxAuditError(f"沙箱禁止文件系统写操作: {event}")
            if args and not _path_allowed(args[0]):
                raise SandboxAuditError(f"文件系统操作超出沙箱目录: {args[0]!r}")
        elif event in ("os.listdir", "os.scandir"):
            if args and not _path_allowed(args[0]):
                raise SandboxAuditError(f"目录操作超出沙箱目录: {args[0]!r}")
        elif event in ("ctypes.dlopen", "marshal.loads", "marshal.load"):
            raise SandboxAuditError(f"沙箱禁止低级动态加载: {event}")

    try:
        sys.addaudithook(_hook)
    except (TypeError, ValueError):
        # 老版本 Python 无 addaudithook 时退化为仅 import 白名单防护
        pass


# ════════════════════════════════════════════════════════════
# 4. 整体安装
# ════════════════════════════════════════════════════════════

# 需从 sys.modules 清除的攻击面模块：运行时（asyncio 等）可能已预导入，
# 若不清理，插件 `import subprocess` 会命中 sys.modules 缓存绕过 meta_path 钩子。
# importlib/marshal/signal/gc 等运行时必需模块保留，其危险操作由 audit 钩子兜底。
_PURGE_MODULES = frozenset({
    "subprocess", "multiprocessing", "socket", "ssl",
    "pickle", "shelve",
    "http", "urllib", "email", "smtplib", "ftplib", "telnetlib",
    "imaplib", "poplib", "webbrowser",
    "sqlite3", "zipfile", "tarfile", "gzip", "bz2", "lzma", "zlib",
    "configparser", "platform", "distutils", "setuptools", "pip",
    "pty", "pwd", "grp", "spwd", "resource", "pdb", "trace", "runpy",
    "shutil", "tempfile", "ctypes", "msvcrt", "curses", "tkinter",
    "winreg", "asyncore", "asynchat",
})


def _purge_dangerous_modules() -> None:
    """把攻击面模块从 sys.modules 置空，强制插件 import 走 meta_path 白名单。"""
    for top in _PURGE_MODULES:
        if top in sys.modules:
            sys.modules[top] = None
        prefix = top + "."
        for name in list(sys.modules):
            if name.startswith(prefix):
                sys.modules[name] = None


def install_sandbox(plugin_dir: Path, state_dir: Path, allow_file: bool) -> dict:
    """安装完整沙箱，返回诊断信息（供子进程上报）。

    Args:
        plugin_dir: 插件目录（允许读写的根之一）
        state_dir: 插件专属状态目录（允许读写的根之一）
        allow_file: 是否允许文件读写（manifest 声明 file_read/file_write 时 True）
    """
    removed_env = scrub_environment()
    # stdio 固定 UTF-8 + 行缓冲（RPC 消息含中文；避免 Windows 本地编码破坏协议）
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
            except Exception:
                try:
                    stream.reconfigure(encoding="utf-8", errors="replace")
                except Exception:
                    pass
    # 清掉被预导入的攻击面模块，强制插件 import 走白名单钩子
    _purge_dangerous_modules()
    finder = _SandboxMetaPathFinder(plugin_dir)
    sys.meta_path.insert(0, finder)
    install_audit_hook(str(plugin_dir), str(state_dir), allow_file)
    _lock_builtins()
    return {"scrubbed_env": len(removed_env), "plugin_dir": str(plugin_dir),
            "state_dir": str(state_dir), "allow_file": allow_file}


def _lock_builtins() -> None:
    """封锁 builtins 中会破坏 RPC 协议或泄露控制流的入口。"""
    for name in ("input", "breakpoint"):
        if hasattr(builtins, name):
            try:
                setattr(builtins, name, _blocked(name))
            except Exception:
                pass


def _blocked(name: str):
    def _deny(*args, **kwargs):
        raise SandboxAuditError(f"沙箱禁止 builtins.{name}")
    _deny.__name__ = f"blocked_{name}"
    return _deny