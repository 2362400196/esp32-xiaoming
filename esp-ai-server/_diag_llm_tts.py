"""综合诊断脚本：验证 LLM 插件和 TTS 插件在沙箱 RPC 链路下的实际行为。

1. LLM: 通过 supervisor 沙箱调用 llm_openai_start_chat，检查 HTTP 请求是否成功、返回什么。
2. TTS: 通过 supervisor 沙箱调用 tts_volcengine_start_synthesis + get_audio，检查是否收到音频。
3. 通过 service_plugin_adapter 的 call_llm_chat / call_tts_synthesize（主进程实际使用路径）验证完整链路。
"""
import asyncio
import base64
import json
import sys
import traceback

sys.path.insert(0, ".")

LLM_CONFIG = {
    "api_key": "sk-6781167b62014f92bd4d314c90cfb48e",
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-v4-flash",
}
TTS_CONFIG = {
    "api_key": "a0cee1c3-ce76-4919-9e71-701191700839",
    "resource_id": "seed-tts-2.0",
    "voice_type": "zh_female_vv_uranus_bigtts",
    "sample_rate": 24000,
    "speed_ratio": 1.0,
    "volume_ratio": 1.0,
    "pitch_ratio": 1.0,
}


async def diag_llm():
    print("=" * 60)
    print("诊断 1: LLM 插件沙箱调用")
    print("=" * 60)
    from src.infrastructure.plugin_host.supervisor import get_plugin_supervisor
    supervisor = get_plugin_supervisor()
    sp = supervisor.get_plugin("llm_openai")
    if sp is None:
        print("!! llm_openai 插件未加载到 supervisor")
        return
    print(f"插件已加载: {sp.plugin_id}, proc={sp._proc is not None}")

    ctx = supervisor._build_call_context(sp, None, None, None, None)
    messages = [
        {"role": "system", "content": "你是一个测试助手，请简短回答。"},
        {"role": "user", "content": "你好，请回复'测试成功'四个字"},
    ]
    print(f"调用 llm_openai_start_chat, config.model={LLM_CONFIG['model']}")
    result = await sp.call_tool(
        "llm_openai_start_chat",
        {"messages": messages, "config": LLM_CONFIG},
        ctx,
    )
    print(f"start_chat 返回: {result[:500]}")
    try:
        parsed = json.loads(result)
    except Exception:
        parsed = {}
    chat_id = parsed.get("chat_id", "")
    if not chat_id:
        print("!! 未获得 chat_id，LLM 调用失败")
        return
    print(f"chat_id: {chat_id}, 开始轮询 get_next ...")
    text = ""
    for i in range(100):
        chunk = await sp.call_tool("llm_openai_get_next", {"chat_id": chat_id}, ctx)
        try:
            cp = json.loads(chunk)
        except Exception:
            cp = {}
        if cp.get("done"):
            break
        token = cp.get("token", "")
        if token:
            text += token
    print(f"LLM 完整回复 ({len(text)} 字符): {text[:200]}")
    await sp.call_tool("llm_openai_end_chat", {"chat_id": chat_id}, ctx)


async def diag_tts():
    print()
    print("=" * 60)
    print("诊断 2: TTS 插件沙箱调用")
    print("=" * 60)
    from src.infrastructure.plugin_host.supervisor import get_plugin_supervisor
    supervisor = get_plugin_supervisor()
    sp = supervisor.get_plugin("tts_volcengine")
    if sp is None:
        print("!! tts_volcengine 插件未加载到 supervisor")
        return
    print(f"插件已加载: {sp.plugin_id}, proc={sp._proc is not None}")

    ctx = supervisor._build_call_context(sp, None, None, None, None)
    text = "你好，今天天气怎么样"
    print(f"调用 tts_volcengine_start_synthesis, text='{text}'")
    result = await sp.call_tool(
        "tts_volcengine_start_synthesis",
        {"text": text, "config": TTS_CONFIG},
        ctx,
    )
    print(f"start_synthesis 返回: {result[:300]}")
    try:
        parsed = json.loads(result)
    except Exception:
        parsed = {}
    syn_id = parsed.get("syn_id", "")
    if not syn_id:
        print("!! 未获得 syn_id，TTS 调用失败")
        return
    print(f"syn_id: {syn_id}, 开始轮询 get_audio ...")
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


async def diag_adapter():
    print()
    print("=" * 60)
    print("诊断 3: 主进程适配器链路 (call_llm_chat / call_tts_synthesize)")
    print("=" * 60)
    from src.interfaces.service_plugin_adapter import call_llm_chat, call_tts_synthesize
    from src.use_cases.tools_system import create_tool_manager

    # 用真实 tool_manager 模拟主进程
    tm = create_tool_manager()
    print(f"tool_manager: {tm}")

    print("\n--- call_llm_chat ---")
    messages = [
        {"role": "system", "content": "你是一个测试助手，请简短回答。"},
        {"role": "user", "content": "你好，请回复'测试成功'四个字"},
    ]
    text = ""
    try:
        async for token in call_llm_chat(messages, LLM_CONFIG, tm):
            print(f"  token: {token!r}")
            if not token.startswith("[LLM"):
                text += token
    except Exception as e:
        print(f"!! call_llm_chat 异常: {e}")
        traceback.print_exc()
    print(f"LLM 适配器完整回复 ({len(text)} 字符): {text[:200]}")

    print("\n--- call_tts_synthesize ---")
    total_audio = 0
    try:
        async for chunk in call_tts_synthesize("你好，今天天气怎么样", TTS_CONFIG, tm):
            if chunk:
                total_audio += len(chunk)
                print(f"  收到音频 {len(chunk)} bytes (累计 {total_audio})")
    except Exception as e:
        print(f"!! call_tts_synthesize 异常: {e}")
        traceback.print_exc()
    print(f"TTS 适配器总音频: {total_audio} bytes")


async def main():
    from src.infrastructure.plugin_loader import load_plugins
    print("加载插件 ...")
    loaded = await load_plugins()
    print(f"已加载插件: {loaded}")
    try:
        await diag_llm()
    except Exception as e:
        print(f"!! LLM 诊断异常: {e}")
        traceback.print_exc()
    try:
        await diag_tts()
    except Exception as e:
        print(f"!! TTS 诊断异常: {e}")
        traceback.print_exc()
    try:
        await diag_adapter()
    except Exception as e:
        print(f"!! 适配器诊断异常: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
