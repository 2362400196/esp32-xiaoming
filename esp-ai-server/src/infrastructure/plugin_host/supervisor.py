"""主进程侧插件监管器（Plugin Supervisor）：管理子进程沙箱的生命周期与 RPC。

职责：
    - 每个已安装（第三方）插件一个独立子进程（spawn + 协议）
    - 加载：启动子进程 → 等待 ready（工具 schema）→ 注册工具
    - 调用：主进程 stub → RPC call → 子进程执行 → 结果回传
    - SDK：子进程 SDK 请求 → 裁决器按 manifest 权限裁决并执行
    - 生命周期：超时杀进程重启、崩溃检测、优雅/强制关闭

内置插件仍走进程内加载（受信任、随源码分发），本模块只管理已安装插件。
"""

from __future__ import annotations

import asyncio
import inspect
import os
import subprocess
import sys
import typing
from pathlib import Path
from typing import Any

from src.infrastructure.logging import get_logger
from src.infrastructure.plugin_host.adjudicator import Adjudicator, CallContext, PermissionDenied
from src.infrastructure.plugin_host.protocol import MAX_MSG_BYTES, ProtocolError, decode, encode
from src.infrastructure.plugin_log_store import add_log as _add_plugin_log
from src.use_cases.tools_system import ToolDefinition, register_tool, unregister_tool

logger = get_logger(__name__)

# 项目根（esp-ai-server/），子进程启动 PYTHONPATH 指向此处
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# 单次工具调用超时（秒）——子进程内 runner 还有独立超时兜底
CALL_TIMEOUT = 130.0
# 启动超时（等待 ready 消息）
START_TIMEOUT = 20.0
# 子进程内存上限（MB），超过则终止
MEMORY_LIMIT_MB = 512
# 内存监控间隔（秒）
MEM_CHECK_INTERVAL = 15.0
# 自动重启最大尝试次数
MAX_RESTART_ATTEMPTS = 3
# 重启退避间隔（秒）
RESTART_BACKOFF_BASE = 2.0

_plugin_supervisor: "PluginSupervisor | None" = None


def get_plugin_supervisor() -> "PluginSupervisor":
    """获取全局 PluginSupervisor 单例。"""
    global _plugin_supervisor
    if _plugin_supervisor is None:
        _plugin_supervisor = PluginSupervisor()
    return _plugin_supervisor


class SandboxedPlugin:
    """单个插件的子进程沙箱实例。"""

    def __init__(self, plugin_id: str, plugin_dir: Path, manifest) -> None:
        self.plugin_id = plugin_id
        self.plugin_dir = plugin_dir
        self.manifest = manifest
        perms = list(getattr(manifest, "permissions", None) or [])
        self.adjudicator = Adjudicator(plugin_id, perms)
        self.allow_file_read = "file_read" in perms
        self.allow_file_write = "file_write" in perms
        self._proc: asyncio.subprocess.Process | None = None
        self._ready_future: asyncio.Future | None = None
        self._pending_calls: dict[int, asyncio.Future] = {}
        self._active_calls: dict[int, CallContext] = {}
        self._write_lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()
        self._call_id = 0
        self.tools: dict[str, dict] = {}
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._memmon_task: asyncio.Task | None = None
        self._restart_attempts = 0
        self._auto_restarting = False
        self.crashed = False

    # ── 生命周期 ────────────────────────────────────────────

    async def start(self) -> bool:
        """启动子进程并等待 ready。成功返回 True。"""
        async with self._start_lock:
            if self._proc is not None and self._proc.returncode is None:
                return True
            return await self._spawn()

    async def _spawn(self) -> bool:
        self.crashed = False
        self._call_id = 0
        env = dict(os.environ)
        env["PYTHONPATH"] = str(_PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONUNBUFFERED"] = "1"
        # 子进程 stdio 固定 UTF-8（避免 Windows 本地编码破坏 RPC 中的中文消息）
        env["PYTHONIOENCODING"] = "utf-8"
        # 确保子进程不继承服务器端口等无关变量（沙箱内还会二次擦除）
        cmd = [
            sys.executable, "-m", "src.infrastructure.plugin_host.runner",
            str(self.plugin_dir), self.plugin_id,
            "1" if self.allow_file_read else "0",
            "1" if self.allow_file_write else "0",
        ]
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(self.plugin_dir),
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=creationflags,
            )
        except OSError as e:
            logger.error(f"[插件沙箱] 启动子进程失败 {self.plugin_id}: {e}")
            _add_plugin_log(self.plugin_id, "error", f"子进程启动失败: {e}")
            return False

        self._ready_future = asyncio.get_running_loop().create_future()
        self._reader_task = asyncio.create_task(self._reader_loop())
        self._stderr_task = asyncio.create_task(self._stderr_loop())
        self._memmon_task = asyncio.create_task(self._memmon_loop())
        try:
            ok = await asyncio.wait_for(self._ready_future, timeout=START_TIMEOUT)
            if not ok:
                logger.error(f"[插件沙箱] 插件 {self.plugin_id} 子进程启动失败（提前退出）")
                await self.stop()
                return False
            self.tools = self._ready_tools
            logger.info(
                f"[插件沙箱] {self.plugin_id} 子进程就绪（{len(self.tools)} 个工具）"
            )
            return True
        except asyncio.TimeoutError:
            logger.error(f"[插件沙箱] 插件 {self.plugin_id} 启动超时，终止进程")
            await self.stop()
            return False

    async def stop(self) -> None:
        """停止子进程（强制终止 + 清理挂起调用）。"""
        proc = self._proc
        self._proc = None
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            except ProcessLookupError:
                pass
        self._fail_pending_calls(f"插件 {self.plugin_id} 已停止")
        if self._reader_task is not None:
            self._reader_task.cancel()
            self._reader_task = None
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            self._stderr_task = None
        if self._memmon_task is not None:
            self._memmon_task.cancel()
            self._memmon_task = None

    async def restart(self) -> bool:
        """崩溃后重启。返回是否成功。"""
        await self.stop()
        return await self.start()

    # ── 读写 ────────────────────────────────────────────────

    async def _write(self, msg: dict) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise ConnectionError(f"插件 {self.plugin_id} 子进程未运行")
        async with self._write_lock:
            try:
                raw = encode(msg)
            except ProtocolError as e:
                raise ConnectionError(f"消息过大（>{MAX_MSG_BYTES//1024}KB），已阻止发送: {e}")
            self._proc.stdin.write(raw.encode("utf-8"))
            await self._proc.stdin.drain()

    def _next_call_id(self) -> int:
        self._call_id += 1
        return self._call_id

    # ── 读取循环 ────────────────────────────────────────────

    async def _reader_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            while True:
                raw = await proc.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    msg = decode(line)
                except ProtocolError:
                    continue
                await self._dispatch(msg)
        except (asyncio.CancelledError, OSError, ValueError):
            pass
        finally:
            # 进程退出：失败所有挂起调用；若尚未 ready，立即结束启动等待
            self._fail_pending_calls(f"插件 {self.plugin_id} 子进程已退出")
            self.crashed = self._proc is not None and self._proc.returncode not in (0, None)
            if self._ready_future is not None and not self._ready_future.done():
                self._ready_future.set_result(False)
            if self.crashed:
                _add_plugin_log(self.plugin_id, "error",
                    f"子进程异常退出（code={self._proc.returncode if self._proc else '?'}）")
            # 非正常退出时自动重启
            if self.crashed and not self._auto_restarting:
                asyncio.create_task(self._auto_restart())

    async def _stderr_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            while True:
                raw = await proc.stderr.readline()
                if not raw:
                    break
                text = raw.decode("utf-8", "replace").rstrip()
                if not text:
                    continue
                logger.debug(f"[插件沙箱:{self.plugin_id}] {text}")
                _add_plugin_log(self.plugin_id, "stderr", text)
        except (asyncio.CancelledError, OSError, ValueError):
            pass

    async def _memmon_loop(self) -> None:
        """周期性检查子进程内存占用，超限则终止。"""
        try:
            import psutil
        except ImportError:
            return
        while True:
            try:
                await asyncio.sleep(MEM_CHECK_INTERVAL)
                proc = self._proc
                if proc is None or proc.returncode is not None:
                    continue
                try:
                    p = psutil.Process(proc.pid)
                    mem_mb = p.memory_info().rss / (1024 * 1024)
                    if mem_mb > MEMORY_LIMIT_MB:
                        logger.warning(
                            f"[插件沙箱] {self.plugin_id} 内存 {mem_mb:.0f}MB 超限"
                            f"（>{MEMORY_LIMIT_MB}MB），终止进程"
                        )
                        proc.kill()
                        await proc.wait()
                        break
                except (psutil.NoSuchProcess, ProcessLookupError):
                    break
            except asyncio.CancelledError:
                break
            except Exception:
                continue

    async def _auto_restart(self) -> None:
        """子进程异常退出后自动重启（带退避）。"""
        if self._auto_restarting:
            return
        self._auto_restarting = True
        try:
            while self._restart_attempts < MAX_RESTART_ATTEMPTS:
                self._restart_attempts += 1
                backoff = RESTART_BACKOFF_BASE * self._restart_attempts
                logger.info(
                    f"[插件沙箱] {self.plugin_id} 自动重启"
                    f"（第{self._restart_attempts}次，{backoff:.0f}s 后）"
                )
                await asyncio.sleep(backoff)
                ok = await self._spawn()
                if ok:
                    logger.info(f"[插件沙箱] {self.plugin_id} 自动重启成功")
                    self._restart_attempts = 0
                    break
            else:
                logger.error(
                    f"[插件沙箱] {self.plugin_id} 自动重启失败"
                    f"（已达{MAX_RESTART_ATTEMPTS}次上限）"
                )
        finally:
            self._auto_restarting = False

    async def _dispatch(self, msg: dict) -> None:
        mtype = msg.get("type")
        if mtype == "ready":
            self._ready_tools = msg.get("tools") or []
            if self._ready_future is not None and not self._ready_future.done():
                self._ready_future.set_result(True)
        elif mtype == "result":
            rid = msg.get("id")
            fut = self._pending_calls.pop(rid, None)
            self._active_calls.pop(rid, None)
            if fut is not None and not fut.done():
                fut.set_result(msg.get("result") or {})
        elif mtype == "sdk_request":
            asyncio.create_task(self._handle_sdk_request(msg))
        elif mtype == "pong":
            pass

    async def _handle_sdk_request(self, msg: dict) -> None:
        op = msg.get("op", "")
        params = msg.get("params") or {}
        cctx = self._active_calls.get(msg.get("call"))
        if cctx is None:
            cctx = CallContext(call_id=-1)
        try:
            result = await self.adjudicator.handle(op, params, cctx)
            reply = {"ok": True, "result": result}
        except PermissionDenied as e:
            reply = {"ok": False, "error": f"PermissionError: {e}"}
            _add_plugin_log(self.plugin_id, "warn", f"SDK {op} 权限被拒: {e}")
        except Exception as e:
            logger.warning(f"[插件沙箱] SDK 操作 {op} 执行异常: {e}")
            reply = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            _add_plugin_log(self.plugin_id, "error", f"SDK {op} 异常: {type(e).__name__}: {e}")
        try:
            await self._write({"type": "sdk_reply", "id": msg.get("id"), **reply})
        except ConnectionError:
            pass

    # ── 工具调用 ────────────────────────────────────────────

    async def call_tool(self, tool_name: str, args: dict, ctx: CallContext) -> str:
        if self._proc is None or (self._proc.returncode is not None):
            if not await self.start():
                return f"工具 {tool_name} 执行异常: 插件 {self.plugin_id} 沙箱进程不可用"
        call_id = self._next_call_id()
        fut = asyncio.get_running_loop().create_future()
        self._pending_calls[call_id] = fut
        self._active_calls[call_id] = ctx
        try:
            await self._write({"type": "call", "id": call_id, "tool": tool_name, "args": args})
        except ConnectionError as e:
            self._pending_calls.pop(call_id, None)
            self._active_calls.pop(call_id, None)
            return f"工具 {tool_name} 执行异常: {e}"
        try:
            reply = await asyncio.wait_for(fut, timeout=CALL_TIMEOUT)
        except asyncio.TimeoutError:
            self._pending_calls.pop(call_id, None)
            self._active_calls.pop(call_id, None)
            logger.error(f"[插件沙箱] 工具 {tool_name} 调用超时，终止进程 {self.plugin_id}")
            _add_plugin_log(self.plugin_id, "error", f"工具 {tool_name} 调用超时（>{CALL_TIMEOUT}s）")
            await self.stop()
            return f"工具 {tool_name} 执行异常: 调用超时（沙箱已终止）"
        result = reply or {}
        if result.get("stop"):
            from src.use_cases.tools_system import StopPipeline
            raise StopPipeline()
        if not result.get("ok"):
            err_msg = result.get('error', '未知错误')
            _add_plugin_log(self.plugin_id, "error", f"工具 {tool_name} 执行异常: {err_msg}")
            return f"工具 {tool_name} 执行异常: {err_msg}"
        value = result.get("value")
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        import json
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)

    def _fail_pending_calls(self, reason: str) -> None:
        for fut in list(self._pending_calls.values()):
            if not fut.done():
                fut.set_result({"ok": False, "error": reason})
        self._pending_calls.clear()
        self._active_calls.clear()


class PluginSupervisor:
    """管理所有沙箱化插件的集合。"""

    def __init__(self) -> None:
        self._plugins: dict[str, SandboxedPlugin] = {}

    def has(self, plugin_id: str) -> bool:
        return plugin_id in self._plugins

    async def load_plugin(self, plugin_id: str, plugin_dir: Path, manifest) -> list[str]:
        """启动插件沙箱并注册工具。返回工具名列表（空表示失败）。"""
        sp = SandboxedPlugin(plugin_id, plugin_dir, manifest)
        if not await sp.start():
            return []
        registered = []
        try:
            for t in sp.tools:
                td = self._build_tool_definition(plugin_id, t)
                register_tool(td)
                registered.append(td.name)
        except Exception as e:
            logger.error(f"[插件沙箱] 注册工具失败，回滚 {plugin_id}: {e}")
            for name in registered:
                try:
                    unregister_tool(name)
                except Exception:
                    pass
            await sp.stop()
            return []
        self._plugins[plugin_id] = sp
        return registered

    async def unload_plugin(self, plugin_id: str) -> None:
        sp = self._plugins.pop(plugin_id, None)
        if sp is None:
            return
        for name in sp.tools:
            try:
                unregister_tool(name)
            except Exception:
                pass
        await sp.stop()

    async def reload_plugin(self, plugin_id: str, plugin_dir: Path, manifest) -> list[str]:
        await self.unload_plugin(plugin_id)
        return await self.load_plugin(plugin_id, plugin_dir, manifest)

    def get_plugin(self, plugin_id: str) -> SandboxedPlugin | None:
        return self._plugins.get(plugin_id)

    async def call_tool(self, plugin_id: str, tool_name: str, args: dict,
                        tool_manager=None, channel=None, ctx=None, fsm=None) -> str:
        sp = self._plugins.get(plugin_id)
        if sp is None:
            return f"工具 {tool_name} 执行异常: 插件 {plugin_id} 沙箱未加载"
        cctx = self._build_call_context(sp, tool_manager, channel, ctx, fsm)
        return await sp.call_tool(tool_name, args, cctx)

    async def shutdown(self) -> None:
        for sp in list(self._plugins.values()):
            await sp.stop()
        self._plugins.clear()

    # ── 工具定义构造 ────────────────────────────────────────

    def _build_tool_definition(self, plugin_id: str, tinfo: dict) -> ToolDefinition:
        schema = tinfo.get("schema") or {"type": "object", "properties": {}}
        params = self._build_signature(schema)
        annotations: dict[str, Any] = {}
        for p in params:
            annotations[p.name] = p.annotation

        async def stub(*args, **kwargs):
            tm = kwargs.pop("tool_manager", None)
            ch = kwargs.pop("channel", None)
            c = kwargs.pop("ctx", None)
            fm = kwargs.pop("fsm", None)
            return await self.call_tool(plugin_id, tinfo["name"], kwargs, tm, ch, c, fm)

        stub.__name__ = tinfo["name"]
        stub.__signature__ = inspect.Signature(params)
        stub.__annotations__ = annotations
        return ToolDefinition(
            name=tinfo["name"],
            description=tinfo.get("description") or tinfo["name"],
            func=stub,
            parameters=schema,
            cache=bool(tinfo.get("cache", True)),
        )

    @staticmethod
    def _build_signature(schema: dict) -> list[inspect.Parameter]:
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        params: list[inspect.Parameter] = []
        type_map = {"string": str, "integer": int, "number": float, "boolean": bool,
                    "array": list, "object": dict}
        for name, prop in props.items():
            ann = type_map.get(prop.get("type"), str)
            if name in required:
                default = inspect.Parameter.empty
            else:
                default = prop.get("default", None)
            params.append(inspect.Parameter(
                name, inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=default, annotation=ann,
            ))
        for extra in ("tool_manager", "channel", "ctx", "fsm"):
            params.append(inspect.Parameter(
                extra, inspect.Parameter.KEYWORD_ONLY, default=None, annotation=Any,
            ))
        return params

    @staticmethod
    def _build_call_context(sp: SandboxedPlugin, tool_manager, channel, ctx, fsm) -> CallContext:
        device_key = ""
        plugin_config: dict = {}
        user_config = None
        if tool_manager is not None:
            user_config = getattr(tool_manager, "user_config", None)
            try:
                from src.use_cases._plugin_helpers import resolve_device_key
                device_key = resolve_device_key("", tool_manager) or ""
            except Exception:
                device_key = ""
            try:
                ucfg = getattr(user_config, "plugin_configs", None) or {}
                plugin_config = dict(ucfg.get(sp.plugin_id, {}) or {})
            except Exception:
                plugin_config = {}
        return CallContext(
            call_id=0, tool_manager=tool_manager, channel=channel,
            ctx=ctx, fsm=fsm, device_key=device_key, plugin_config=plugin_config,
            user_config=user_config,
        )