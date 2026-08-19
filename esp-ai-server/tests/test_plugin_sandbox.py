"""子进程沙箱端到端测试：真实启动子进程、RPC 往返、权限拦截、停止流程。

运行前提：本测试会在 data/plugins/installed/ 下创建临时插件并清理。
"""

import asyncio
import json
import shutil

import pytest

from src.infrastructure import plugin_loader as loader
from src.infrastructure.plugin_host.supervisor import get_plugin_supervisor
from src.infrastructure.plugin_loader import _unload_plugin, _loaded_tools
from src.use_cases.tools_system import StopPipeline, get_tool

PLUGIN_ID = "demo_sandbox"

PLUGIN_PY = '''\
from src.use_cases.tools_system import tool, StopPipeline
from src.use_cases._plugin_helpers import get_ltm_service, http_get_json

@tool(name="sbx_echo", description="echo test")
async def sbx_echo(message: str = "hi") -> str:
    return f"echo:{message}"

@tool(name="sbx_ltm", description="ltm permission test")
async def sbx_ltm() -> str:
    svc = get_ltm_service()
    await svc.store({"text": "hello", "device_id": "demo"})
    return "stored"

@tool(name="sbx_http", description="http permission test")
async def sbx_http() -> str:
    data, err = await http_get_json("http://127.0.0.1:9/x")
    return f"data={data} err={err}"

@tool(name="sbx_stop", description="stop pipeline test")
async def sbx_stop() -> str:
    raise StopPipeline()
'''

MANIFEST = {
    "id": PLUGIN_ID,
    "name": PLUGIN_ID,
    "version": "1.0.0",
    "author": "test",
    "description": "sandbox e2e test",
    "api_version": "1.0",
    "requires": [],
    "permissions": [],
}


class _UserConfig:
    key = "bound_demo"
    device_id = "demo"


class _ToolManager:
    user_config = _UserConfig()
    plugin_configs = {}

    def get_plugin_config(self, plugin, key, default=""):
        return self.plugin_configs.get(plugin, {}).get(key, default)


@pytest.fixture()
def sandbox_plugin():
    plugin_dir = loader.INSTALLED_PLUGINS_DIR / PLUGIN_ID
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.py").write_text(PLUGIN_PY, encoding="utf-8")
    (plugin_dir / "manifest.json").write_text(
        json.dumps(MANIFEST, ensure_ascii=False), encoding="utf-8"
    )
    yield plugin_dir
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(_unload_plugin(PLUGIN_ID))
    shutil.rmtree(plugin_dir, ignore_errors=True)
    shutil.rmtree(loader.INSTALLED_PLUGINS_DIR.parent / "state" / PLUGIN_ID, ignore_errors=True)


def test_sandbox_full_roundtrip(sandbox_plugin):
    async def scenario():
        loaded = await loader.load_plugins()
        assert PLUGIN_ID in loaded
        sp = get_plugin_supervisor().get_plugin(PLUGIN_ID)
        assert sp is not None
        assert {t["name"] for t in sp.tools} == {"sbx_echo", "sbx_ltm", "sbx_http", "sbx_stop"}

        tm = _ToolManager()

        # 普通工具 RPC 往返
        r = await get_tool("sbx_echo").func(message="hi", tool_manager=tm)
        assert r == "echo:hi"

        # 未声明权限 → SDK 调用被拒绝（PermissionError 语义）
        r2 = await get_tool("sbx_ltm").func(tool_manager=tm)
        assert "PermissionError" in r2, r2

        # 未声明 network 权限 → HTTP 被拒（SSRF/权限裁决）
        r3 = await get_tool("sbx_http").func(tool_manager=tm)
        assert "PermissionError" in r3, r3

        # StopPipeline 传播
        with pytest.raises(StopPipeline):
            await get_tool("sbx_stop").func(tool_manager=tm)

        # 卸载：沙箱进程被停止、工具注销
        await _unload_plugin(PLUGIN_ID)
        assert PLUGIN_ID not in _loaded_tools
        assert get_plugin_supervisor().get_plugin(PLUGIN_ID) is None
        assert get_tool("sbx_echo") is None

    asyncio.run(scenario())


def test_sandbox_import_blocklist(sandbox_plugin):
    """沙箱子进程禁止导入服务器内部模块与危险模块（启动即拒绝加载）。"""
    from src.infrastructure.plugin_host import sandbox as sb

    assert "subprocess" in sb._BLOCKED_MODULES
    assert "importlib" in sb._BLOCKED_MODULES
    assert "socket" in sb._BLOCKED_MODULES
    assert "src.use_cases.tools_system" not in sb._BLOCKED_MODULES

    # 在子进程内验证 import 拦截：用 os.system 直接调用 runner 会触发 audit 钩子，
    # 这里改为通过 loader 加载一个会 import 危险模块的插件，应被拒绝。
    async def scenario():
        bad_dir = loader.INSTALLED_PLUGINS_DIR / "demo_badimport"
        bad_dir.mkdir(parents=True, exist_ok=True)
        (bad_dir / "plugin.py").write_text(
            "import subprocess\nfrom src.use_cases.tools_system import tool\n"
            "@tool(name='bad')\nasync def bad(): return 'x'\n",
            encoding="utf-8",
        )
        (bad_dir / "manifest.json").write_text(
            json.dumps({**MANIFEST, "id": "demo_badimport"}, ensure_ascii=False),
            encoding="utf-8",
        )
        try:
            ok = await loader._load_plugin("demo_badimport")
            assert not ok, "含 subprocess import 的插件应被沙箱拒绝"
        finally:
            await _unload_plugin("demo_badimport")
            shutil.rmtree(bad_dir, ignore_errors=True)
            shutil.rmtree(loader.INSTALLED_PLUGINS_DIR.parent / "state" / "demo_badimport",
                          ignore_errors=True)

    asyncio.run(scenario())