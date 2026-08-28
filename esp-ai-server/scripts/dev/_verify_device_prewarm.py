"""验证设备连接预热效果：预热后首次 ASR 会话应秒取连接。

模拟真实流程：
  1. 设备连接 → 调用 asr_volcengine_prewarm（预热 2 个连接）
  2. 首次语音输入 → asr_volcengine_start_session（应从预热池秒取）
  3. 对比：无预热时的首次建连延迟

用法：在 esp-ai-server 目录下运行
  .venv\\Scripts\\python.exe _verify_device_prewarm.py
"""
import asyncio
import json
import sys
import time

sys.path.insert(0, ".")

ASR_CONFIG = {
    "api_key": "a0cee1c3-ce76-4919-9e71-701191700839",
    "resource_id": "volc.bigasr.sauc.duration",
    "model_name": "bigmodel",
}


def _fmt(ms):
    return f"{ms:8.2f} ms"


def _parse(result):
    try:
        return json.loads(result)
    except Exception:
        return {}


async def main():
    from src.infrastructure.plugin_loader import load_plugins
    from src.infrastructure.plugin_host.supervisor import get_plugin_supervisor

    print("加载插件（启动沙箱子进程）...")
    await load_plugins()
    supervisor = get_plugin_supervisor()
    sp_asr = supervisor.get_plugin("asr_volcengine")
    if sp_asr is None:
        print("!! asr_volcengine 沙箱未加载")
        return
    ctx = supervisor._build_call_context(sp_asr, None, None, None, None)

    # ── 场景 A：无预热，首次建连（对照） ──
    print("\n[场景 A] 无预热：首次 start_session（应新建连接）")
    t0 = time.perf_counter()
    r = await sp_asr.call_tool("asr_volcengine_start_session", {"config": ASR_CONFIG}, ctx)
    dt_a = (time.perf_counter() - t0) * 1000
    p = _parse(r)
    sess = p.get("session_id", "")
    print(f"  start_session: {_fmt(dt_a)}  session_id={sess}")
    if sess:
        await sp_asr.call_tool("asr_volcengine_end_session", {"session_id": sess}, ctx)
    await asyncio.sleep(1.0)

    # ── 场景 B：设备连接预热 → 首次会话 ──
    print("\n[场景 B] 设备连接预热：prewarm → start_session（应从预热池秒取）")
    t0 = time.perf_counter()
    r = await sp_asr.call_tool("asr_volcengine_prewarm", {"config": ASR_CONFIG}, ctx)
    dt_p = (time.perf_counter() - t0) * 1000
    p = _parse(r)
    print(f"  prewarm: {_fmt(dt_p)}  created={p.get('created')}")

    t0 = time.perf_counter()
    r = await sp_asr.call_tool("asr_volcengine_start_session", {"config": ASR_CONFIG}, ctx)
    dt_b = (time.perf_counter() - t0) * 1000
    p = _parse(r)
    sess = p.get("session_id", "")
    print(f"  start_session（预热后）: {_fmt(dt_b)}  session_id={sess}")
    if sess:
        await sp_asr.call_tool("asr_volcengine_end_session", {"session_id": sess}, ctx)

    print("\n" + "=" * 60)
    print(f"首次建连（对照）: {_fmt(dt_a)}")
    print(f"预热后首次会话 : {_fmt(dt_b)}")
    print(f"改善           : {_fmt(dt_a - dt_b)}")


if __name__ == "__main__":
    asyncio.run(main())
