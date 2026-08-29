"""插件生命周期钩子、单插件热重载回滚与 sys.modules 子模块清理测试。

覆盖：
  1. 内置插件 on_startup / on_shutdown 被正确调用（加载成功后 / 卸载时）
  2. reload_single_plugin 加载失败时回滚工具注册表（插件不再"重载失败即消失"）
  3. 卸载时清理插件加载新增的 sys.modules 子模块（兄弟模块）
  4. AlarmManager.start/stop 幂等
"""

import asyncio
import json
import shutil
import sys

import pytest

from src.infrastructure import plugin_loader as loader
from src.use_cases.tools_system import get_tool, register_tool, unregister_tool


# ── 测试用内置插件源码模板 ──────────────────────────────────

def _make_plugin_source(tool_name: str, calls_literal: str, import_sibling: str = "") -> str:
    return f'''\
"""测试用生命周期插件"""
calls = {calls_literal}

from src.use_cases.tools_system import tool
{import_sibling}

@tool(name="{tool_name}", description="lifecycle test tool")
async def {tool_name}() -> str:
    return "ok"


async def on_startup():
    calls.append("startup")


async def on_shutdown():
    calls.append("shutdown")
'''


def _write_plugin(plugin_dir, source: str, manifest: dict | None = None):
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.py").write_text(source, encoding="utf-8")
    if manifest is not None:
        (plugin_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )


def _cleanup_plugin_state(plugin_name: str, plugin_dir):
    """测试后清理全局注册状态与临时目录。"""
    for t in loader._loaded_tools.pop(plugin_name, []):
        unregister_tool(t)
        loader._tool_owner.pop(t, None)
    loader._plugin_meta.pop(plugin_name, None)
    loader._plugin_version.pop(plugin_name, None)
    loader._plugin_source.pop(plugin_name, None)
    loader._plugin_manifest.pop(plugin_name, None)
    loader._plugin_optional.pop(plugin_name, None)
    loader._plugin_submodules.pop(plugin_name, None)
    module_name = loader._plugin_module_names.pop(plugin_name, None)
    if module_name and module_name in sys.modules:
        del sys.modules[module_name]
    for sub in [k for k in sys.modules if k.startswith("lc_sub_helper_")]:
        del sys.modules[sub]
    added = loader._plugin_syspaths.pop(plugin_name, None)
    if added and added in sys.path:
        sys.path.remove(added)
    shutil.rmtree(plugin_dir, ignore_errors=True)


# ── 1. 生命周期钩子 ─────────────────────────────────────────

def test_builtin_plugin_lifecycle_hooks(tmp_path):
    """加载成功后调用 on_startup，卸载时调用 on_shutdown。"""
    plugin_name = "lc_hook_plugin"
    calls = []
    plugin_dir = tmp_path / plugin_name
    source = _make_plugin_source("lc_hook_echo", repr(calls))
    _write_plugin(plugin_dir, source)

    async def scenario():
        # 直接走内置加载（_load_builtin_plugin 现为 async）
        ok = await loader._load_builtin_plugin(
            plugin_name, plugin_dir, plugin_dir / "plugin.py"
        )
        assert ok, "插件应加载成功"
        # 模块内的 calls 列表（模块执行时以字面量重建，需从模块对象取）
        mod = sys.modules[f"esp_ai_plugins_{plugin_name}"]
        assert mod.calls == ["startup"], f"on_startup 应被调用一次: {mod.calls}"

        # 卸载时调用 on_shutdown
        await loader._unload_plugin(plugin_name)
        assert mod.calls == ["startup", "shutdown"], f"on_shutdown 应被调用: {mod.calls}"

        # 卸载后工具被注销
        assert get_tool("lc_hook_echo") is None

    try:
        asyncio.run(scenario())
    finally:
        _cleanup_plugin_state(plugin_name, plugin_dir)


def test_lifecycle_hook_exception_does_not_break_load(tmp_path):
    """on_startup 抛异常不影响加载成功（容错）。"""
    plugin_name = "lc_hook_bad_plugin"
    plugin_dir = tmp_path / plugin_name
    source = (
        "from src.use_cases.tools_system import tool\n"
        "\n"
        "@tool(name='lc_hook_bad_echo', description='lifecycle test')\n"
        "async def lc_hook_bad_echo() -> str:\n"
        "    return 'ok'\n"
        "\n"
        "async def on_startup():\n"
        "    raise RuntimeError('boom')\n"
    )
    _write_plugin(plugin_dir, source)

    async def scenario():
        ok = await loader._load_builtin_plugin(
            plugin_name, plugin_dir, plugin_dir / "plugin.py"
        )
        assert ok, "on_startup 异常不应导致加载失败"
        assert get_tool("lc_hook_bad_echo") is not None
        await loader._unload_plugin(plugin_name)

    try:
        asyncio.run(scenario())
    finally:
        _cleanup_plugin_state(plugin_name, plugin_dir)


# ── 2. 单插件热重载回滚 ─────────────────────────────────────

def test_reload_single_plugin_rollback(tmp_path, monkeypatch):
    """重载失败（语法错误）时回滚：旧工具仍在注册表中，插件不消失。"""
    plugin_name = "rl_rollback_plugin"
    plugin_root = tmp_path / "plugins_root"
    plugin_dir = plugin_root / plugin_name
    source = (
        "from src.use_cases.tools_system import tool\n"
        "\n"
        "@tool(name='rl_rollback_echo', description='rollback test')\n"
        "async def rl_rollback_echo() -> str:\n"
        "    return 'ok'\n"
    )
    manifest = {
        "id": plugin_name,
        "name": plugin_name,
        "version": "1.0.0",
        "author": "test",
        "description": "reload rollback test",
        "api_version": "1.0",
        "permissions": [],
    }
    _write_plugin(plugin_dir, source, manifest)
    # 让 _resolve_plugin_dir 找到该"内置"插件
    monkeypatch.setattr(loader, "PLUGINS_DIR", plugin_root)

    async def scenario():
        # 首次加载成功
        assert await loader._load_plugin(plugin_name)
        assert get_tool("rl_rollback_echo") is not None

        # 写入语法错误的 plugin.py 后热重载 → 失败
        (plugin_dir / "plugin.py").write_text("def broken(:", encoding="utf-8")
        ok = await loader.reload_single_plugin(plugin_name)
        assert ok is False, "语法错误的重载应失败"

        # 回滚：旧工具仍注册、插件仍在已加载列表
        assert get_tool("rl_rollback_echo") is not None, "重载失败后旧工具应被回滚保留"
        assert plugin_name in loader._loaded_tools, "重载失败后插件不应从注册表消失"

        # 清理
        await loader._unload_plugin(plugin_name)

    try:
        asyncio.run(scenario())
    finally:
        _cleanup_plugin_state(plugin_name, plugin_dir)


# ── 3. sys.modules 子模块清理 ───────────────────────────────

def test_unload_removes_plugin_submodules(tmp_path):
    """卸载插件时，加载期间新增到 sys.modules 的兄弟模块应被一并清理。"""
    plugin_name = "lc_sub_plugin"
    sibling_mod = "lc_sub_helper_a1b2c3"
    plugin_dir = tmp_path / plugin_name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    # 兄弟模块（插件目录加入 sys.path 后 import 会进入 sys.modules）
    (plugin_dir / f"{sibling_mod}.py").write_text("VALUE = 42\n", encoding="utf-8")
    source = _make_plugin_source(
        "lc_sub_echo", "[]", import_sibling=f"import {sibling_mod}"
    )
    _write_plugin(plugin_dir, source)

    async def scenario():
        ok = await loader._load_builtin_plugin(
            plugin_name, plugin_dir, plugin_dir / "plugin.py"
        )
        assert ok
        # 加载时记录了新增子模块
        subs = loader._plugin_submodules.get(plugin_name, [])
        assert sibling_mod in subs, f"兄弟模块应被记录到 _plugin_submodules: {subs}"
        assert sibling_mod in sys.modules, "兄弟模块应已进入 sys.modules"

        await loader._unload_plugin(plugin_name)
        assert sibling_mod not in sys.modules, "卸载后兄弟模块应从 sys.modules 清理"

    try:
        asyncio.run(scenario())
    finally:
        _cleanup_plugin_state(plugin_name, plugin_dir)


# ── 4. AlarmManager start/stop 幂等 ────────────────────────

def test_alarm_manager_start_stop_idempotent():
    """重复 start / stop 无副作用（插件钩子与 web.py 双启动安全）。"""
    from src.use_cases.alarm_manager import get_alarm_manager

    async def scenario():
        mgr = get_alarm_manager()
        try:
            await mgr.start()
            task1 = mgr._task
            await mgr.start()  # 重复启动：不应创建新任务
            assert mgr._task is task1
            await mgr.stop()
            assert mgr._task is None
            await mgr.stop()  # 重复停止：无异常
            assert mgr._task is None
        finally:
            await mgr.stop()

    asyncio.run(scenario())
