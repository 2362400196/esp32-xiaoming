"""子进程入口：加载插件并服务 RPC 调用。

由主进程通过 `python -m src.infrastructure.plugin_host.runner <plugin_dir> <plugin_id> <allow_file>` 启动。

流程：
    1. 解析参数
    2. 安装沙箱（环境擦除 + import 白名单 + 审计钩子）
    3. 注入 SDK 桩模块
    4. 加载插件目录下的 plugin.py（@tool 注册到本地 _TOOLS）
    5. 上报 ready（含工具 schema）
    6. 进入 asyncio 事件循环，服务 call / sdk_reply / ping

失败时向 stderr 打印错误并以非零码退出，主进程据此判定加载失败。
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import traceback
from pathlib import Path

from . import client
from . import sandbox
from . import sdk_shim
from .protocol import encode

# 插件模块注册到的名称（主进程注销时保持一致）
MODULE_PREFIX = "esp_ai_sandbox_plugin_"

# 工具调用超时（秒）：防止插件死循环/无限阻塞
CALL_TIMEOUT = 120.0


def _log(msg: str) -> None:
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def main() -> int:
    if len(sys.argv) < 4:
        sys.stderr.write("usage: runner <plugin_dir> <plugin_id> <allow_file>\n")
        return 2
    plugin_dir = Path(sys.argv[1]).resolve()
    plugin_id = sys.argv[2]
    allow_file = sys.argv[3].lower() in ("1", "true", "yes")

    # 事件循环须在沙箱安装前创建：Windows ProactorEventLoop 初始化会创建内部
    # socketpair（_make_self_pipe），安装审计钩子后会拦截 socket 导致崩溃。
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    if not (plugin_dir / "plugin.py").is_file():
        sys.stderr.write(f"plugin.py 不存在: {plugin_dir}\n")
        return 2

    # 1. 沙箱
    state_dir = _state_dir(plugin_dir)
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        state_dir = plugin_dir
    diag = sandbox.install_sandbox(plugin_dir, state_dir, allow_file)
    _log(f"[sandbox] installed: {diag}")
    # 禁止字节码缓存写入（避免在插件目录写 __pycache__，也减少文件系统操作面）
    sys.dont_write_bytecode = True

    # 2. SDK 桩
    src_dir = str(Path(__file__).resolve().parent.parent.parent)  # esp-ai-server/src
    sdk_shim.install_shims(plugin_id, src_dir)

    # 3. 加载插件
    sys.path.insert(0, str(plugin_dir))
    try:
        _load_plugin_module(plugin_dir, plugin_id)
    except sandbox.SandboxImportError as e:
        sys.stderr.write(f"[load] 插件 import 被沙箱拦截: {e}\n")
        return 3
    except Exception as e:
        sys.stderr.write(f"[load] 插件加载失败: {e}\n")
        traceback.print_exc()
        return 3

    # 4. 上报 ready
    tools = sdk_shim.get_all_tools()
    sys.stdout.write(encode({
        "type": "ready",
        "plugin": plugin_id,
        "tools": sorted(tools.values(), key=lambda t: t["name"]),
    }))
    sys.stdout.flush()

    # 5. 事件循环
    client.set_call_handler(lambda msg: _on_call(msg))
    try:
        loop.run_until_complete(_serve())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()
    return 0


def _state_dir(plugin_dir: Path) -> Path:
    """插件专属状态目录（data/plugins/state/<id>/）。"""
    base = plugin_dir.parent.parent / "state"
    return base / plugin_dir.name


def _load_plugin_module(plugin_dir: Path, plugin_id: str) -> None:
    module_name = MODULE_PREFIX + plugin_id
    spec = importlib.util.spec_from_file_location(module_name, plugin_dir / "plugin.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法创建插件模块 spec: {plugin_id}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)


def _on_call(msg: dict) -> None:
    """处理主进程下发的工具调用（在事件循环线程执行）。"""
    loop = asyncio.get_running_loop()
    task = loop.create_task(_run_call(msg))
    # 让任务异常不打断循环
    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)


async def _run_call(msg: dict) -> None:
    call_id = msg.get("id")
    tool_name = msg.get("tool", "")
    args = msg.get("args") or {}
    tools = sdk_shim.get_all_tools()
    tdef = tools.get(tool_name)
    if tdef is None:
        _emit_result(call_id, {"ok": False, "error": f"子进程内未找到工具: {tool_name}"})
        return

    token = client.call_id_ctx.set(call_id)
    try:
        try:
            if tdef["is_coro"]:
                result = await asyncio.wait_for(_call_func(tools, tool_name, args), CALL_TIMEOUT)
            else:
                result = await asyncio.wait_for(
                    asyncio.to_thread(_call_sync_func, tools, tool_name, args), CALL_TIMEOUT
                )
            _emit_result(call_id, {"ok": True, "value": str(result), "stop": False})
        except sdk_shim.StopPipeline:
            _emit_result(call_id, {"ok": True, "value": None, "stop": True})
        except asyncio.TimeoutError:
            _emit_result(call_id, {"ok": False, "error": f"工具 {tool_name} 调用超时（>{CALL_TIMEOUT}s）"})
        except Exception as e:
            _emit_result(call_id, {"ok": False, "error": f"{type(e).__name__}: {e}"})
    finally:
        client.call_id_ctx.reset(token)


async def _call_func(tools, tool_name, args):
    func = sdk_shim.get_tool_func(tool_name)
    return await func(**args)


def _call_sync_func(tools, tool_name, args):
    func = sdk_shim.get_tool_func(tool_name)
    return func(**args)


def _emit_result(call_id, result: dict) -> None:
    sys.stdout.write(encode({"type": "result", "id": call_id, "result": result}))
    sys.stdout.flush()


async def _serve() -> None:
    loop = asyncio.get_running_loop()
    client.start_reader(loop)
    # 事件循环一直运行，直到 stdin 关闭（主进程退出/重启时终止）
    stop = loop.create_future()

    async def _watch_stdin_closed() -> None:
        # 唯一 stdin 读取者是 client 的 reader 线程，EOF 由它置位（避免双读线程抢消息）
        await asyncio.to_thread(client.get_eof_event().wait)
        if not stop.done():
            stop.set_result(True)

    loop.create_task(_watch_stdin_closed())
    try:
        await stop
    except asyncio.CancelledError:
        pass
    # 取消所有运行中的任务
    for task in asyncio.all_tasks():
        if task is not asyncio.current_task():
            task.cancel()


if __name__ == "__main__":
    sys.exit(main())