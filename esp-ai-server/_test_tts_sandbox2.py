"""最小化独立测试：只启动 tts_volcengine 沙箱子进程，测完整 TTS 流程。"""
import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

TTS_CONFIG = {
    "api_key": "a0cee1c3-ce76-4919-9e71-701191700839",
    "resource_id": "seed-tts-2.0",
    "voice_type": "zh_female_vv_uranus_bigtts",
    "sample_rate": 24000,
    "speed_ratio": 1.0,
    "volume_ratio": 1.0,
    "pitch_ratio": 1.0,
}


async def main():
    from src.infrastructure.plugin_host.supervisor import SandboxedPlugin

    plugin_dir = Path("data/plugins/installed/tts_volcengine").resolve()
    manifest = json.loads((plugin_dir / "manifest.json").read_text(encoding="utf-8"))
    sp = SandboxedPlugin("tts_volcengine", plugin_dir, type("M", (), manifest)())
    print(f"启动沙箱子进程 ...")
    ok = await sp.start()
    print(f"启动: {ok}, tools: {[t.get('name') for t in sp.tools]}")
    if not ok:
        return

    ctx = None
    text = "欢哥，"
    print(f"调用 start_synthesis, text='{text}'")
    result = await sp.call_tool(
        "tts_volcengine_start_synthesis", {"text": text, "config": TTS_CONFIG}, ctx
    )
    print(f"start_synthesis 返回: {result[:300]}")
    try:
        parsed = json.loads(result)
    except Exception:
        parsed = {}
    syn_id = parsed.get("syn_id", "")
    if not syn_id:
        print("!! 未获得 syn_id")
        await sp.stop()
        return
    print(f"syn_id: {syn_id}, 轮询 get_audio ...")
    total_audio = 0
    for i in range(30):
        chunk = await sp.call_tool("tts_volcengine_get_audio", {"syn_id": syn_id}, ctx)
        try:
            cp = json.loads(chunk)
        except Exception:
            cp = {}
        if cp.get("error"):
            print(f"  [{i}] error: {cp['error']}")
            break
        if cp.get("done"):
            print(f"  [{i}] done")
            break
        audio_b64 = cp.get("audio_base64", "")
        if audio_b64:
            n = len(base64.b64decode(audio_b64))
            total_audio += n
            print(f"  [{i}] 收到音频 {n} bytes (累计 {total_audio})")
    print(f"TTS 总音频: {total_audio} bytes")
    await sp.call_tool("tts_volcengine_end_synthesis", {"syn_id": syn_id}, ctx)
    await sp.stop()
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
