"""测试子进程是否能正常启动和调用工具"""
import asyncio
import json
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

async def test():
    from src.infrastructure.plugin_host.supervisor import SandboxedPlugin, CallContext

    class MockManifest:
        def __init__(self):
            self.permissions = ["network", "env_read"]

    project_root = Path(__file__).resolve().parent
    plugin_dir = project_root / "data" / "plugins" / "installed" / "llm_openai"
    plugin_id = "llm_openai"
    manifest = MockManifest()

    sp = SandboxedPlugin(plugin_id, plugin_dir, manifest)

    print(f"启动子进程: {plugin_id}")
    ok = await sp.start()
    print(f"启动结果: {ok}")

    if not ok:
        print("子进程启动失败")
        return

    print(f"子进程 PID: {sp._proc.pid if sp._proc else 'N/A'}")
    print(f"已注册工具: {[t['name'] for t in sp.tools] if sp.tools else 'none'}")

    ctx = CallContext(call_id=0)
    messages = [{"role": "user", "content": "你好"}]
    config = {
        "api_key": "sk-test-key",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat"
    }

    print("\n测试调用 llm_openai_start_chat (预期会因 api_key 无效而失败，但不应崩溃)...")
    try:
        result = await sp.call_tool(
            "llm_openai_start_chat",
            {"messages": messages, "config": config},
            ctx,
        )
        print(f"结果: {result[:200] if result else 'None'}")
    except Exception as e:
        print(f"调用异常: {type(e).__name__}: {e}")

    await asyncio.sleep(1)
    if sp._proc and sp._proc.returncode is None:
        print(f"子进程仍在运行 ✓")
    else:
        code = sp._proc.returncode if sp._proc else 'N/A'
        print(f"子进程已退出，returncode={code} ✗")

    await sp.stop()
    print("测试完成")

if __name__ == "__main__":
    asyncio.run(test())