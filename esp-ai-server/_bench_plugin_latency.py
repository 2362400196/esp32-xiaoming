"""插件化链路延迟基准测试（新代码 esp）

测量各环节延迟：
  1. RPC 基础往返延迟（子进程空工具调用）
  2. base64 编解码延迟（不同数据大小）
  3. 大数据 RPC 传输延迟（模拟音频数据跨进程传输）
  4. TTS 链路：ws_connect 连接建立 / start_synthesis / get_audio（含 ws_recv RPC）
  5. LLM 链路：start_chat（含 http_stream_open）/ get_next（含 http_stream_read）
  6. ASR 链路：start_session（含 ws_connect）/ send_audio（含 ws_send RPC）

用法：在 esp-ai-server 目录下运行
  .venv\\Scripts\\python.exe _bench_plugin_latency.py
"""
import asyncio
import base64
import json
import statistics
import sys
import time

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
ASR_CONFIG = {
    "api_key": "a0cee1c3-ce76-4919-9e71-701191700839",
    "resource_id": "volc.bigasr.sauc.duration",
    "model_name": "bigmodel",
}


def _fmt(ms):
    return f"{ms:8.2f} ms"


def _stats(vals):
    if not vals:
        return "n/a"
    return (f"min={_fmt(min(vals))}  avg={_fmt(statistics.mean(vals))}  "
            f"p50={_fmt(statistics.median(vals))}  max={_fmt(max(vals))}")


def _parse(result):
    try:
        return json.loads(result)
    except Exception:
        return {}


# ════════════════════════════════════════════════════════════
# 1. RPC 基础往返延迟
# ════════════════════════════════════════════════════════════

async def bench_rpc_roundtrip(sp, ctx, n=30):
    print("\n" + "=" * 70)
    print("1. RPC 基础往返延迟（子进程空工具调用，不含网络）")
    print("=" * 70)
    # 用 tts_get_audio 对不存在的 session：子进程内快速返回，纯 RPC 往返
    vals = []
    for _ in range(n):
        t0 = time.perf_counter()
        await sp.call_tool("tts_volcengine_get_audio", {"syn_id": "nonexistent"}, ctx)
        vals.append((time.perf_counter() - t0) * 1000)
    print(f"  RPC 往返 (get_audio 空调用): {_stats(vals)}")


# ════════════════════════════════════════════════════════════
# 2. base64 编解码延迟
# ════════════════════════════════════════════════════════════

def bench_base64():
    print("\n" + "=" * 70)
    print("2. base64 编解码延迟（跨进程音频传输的固定开销）")
    print("=" * 70)
    for size_kb in (1, 4, 16, 64, 256):
        data = bytes(range(256)) * (size_kb * 1024 // 256)
        # 编码
        enc_vals = []
        for _ in range(50):
            t0 = time.perf_counter()
            b64 = base64.b64encode(data)
            enc_vals.append((time.perf_counter() - t0) * 1000)
        # 解码
        dec_vals = []
        for _ in range(50):
            t0 = time.perf_counter()
            base64.b64decode(b64)
            dec_vals.append((time.perf_counter() - t0) * 1000)
        print(f"  {size_kb:4d} KB: 编码 avg={_fmt(statistics.mean(enc_vals))}  "
              f"解码 avg={_fmt(statistics.mean(dec_vals))}")


# ════════════════════════════════════════════════════════════
# 3. 大数据 RPC 传输延迟（模拟音频数据）
# ════════════════════════════════════════════════════════════

async def bench_rpc_transfer(sp, ctx, n=10):
    print("\n" + "=" * 70)
    print("3. 大数据 RPC 传输延迟（asr_send_audio 传不同大小数据，含 base64+JSON+stdio）")
    print("=" * 70)
    for size_kb in (1, 4, 16, 64):
        audio_b64 = base64.b64encode(bytes(range(256)) * (size_kb * 1024 // 256)).decode("ascii")
        vals = []
        for _ in range(n):
            t0 = time.perf_counter()
            await sp.call_tool(
                "asr_volcengine_send_audio",
                {"session_id": "nonexistent", "audio": audio_b64},
                ctx,
            )
            vals.append((time.perf_counter() - t0) * 1000)
        print(f"  {size_kb:4d} KB 音频: {_stats(vals)}")


# ════════════════════════════════════════════════════════════
# 4. TTS 链路
# ════════════════════════════════════════════════════════════

async def bench_tts(sp, ctx):
    print("\n" + "=" * 70)
    print("4. TTS 链路（火山引擎，真实网络）")
    print("=" * 70)
    text = "你好，今天天气怎么样，我们一起去公园散步吧。"

    # 4.1 首次 start_synthesis（含 ws_connect 连接建立）
    t0 = time.perf_counter()
    r = await sp.call_tool("tts_volcengine_start_synthesis", {"text": text, "config": TTS_CONFIG}, ctx)
    t_connect = (time.perf_counter() - t0) * 1000
    p = _parse(r)
    syn_id = p.get("syn_id", "")
    print(f"  首次 start_synthesis（含 WS 连接建立）: {_fmt(t_connect)}  syn_id={syn_id}")
    if not syn_id:
        print(f"  !! 失败: {r[:200]}")
        return

    # 4.2 get_audio 轮询（含 ws_recv RPC），统计首帧延迟和每帧延迟
    total_audio = 0
    frame_vals = []
    first_frame = None
    done = False
    for i in range(50):
        t0 = time.perf_counter()
        chunk = await sp.call_tool("tts_volcengine_get_audio", {"syn_id": syn_id}, ctx)
        dt = (time.perf_counter() - t0) * 1000
        cp = _parse(chunk)
        if cp.get("error"):
            print(f"  [{i}] error: {cp['error']}")
            break
        if cp.get("done"):
            done = True
            break
        audio_b64 = cp.get("audio_base64", "")
        if audio_b64:
            nbytes = len(base64.b64decode(audio_b64))
            total_audio += nbytes
            if first_frame is None:
                first_frame = dt
            frame_vals.append(dt)
    print(f"  TTS 首帧延迟（TTFB，含 ws_recv RPC）: {_fmt(first_frame) if first_frame else 'n/a'}")
    print(f"  TTS 每帧 get_audio 延迟（含 ws_recv RPC）: {_stats(frame_vals)}")
    print(f"  TTS 总音频: {total_audio} bytes, done={done}")
    await sp.call_tool("tts_volcengine_end_synthesis", {"syn_id": syn_id}, ctx)

    # 4.3 后续 start_synthesis（连接复用，不含 ws_connect）
    t0 = time.perf_counter()
    r2 = await sp.call_tool("tts_volcengine_start_synthesis", {"text": text, "config": TTS_CONFIG}, ctx)
    t_reuse = (time.perf_counter() - t0) * 1000
    p2 = _parse(r2)
    syn2 = p2.get("syn_id", "")
    print(f"  后续 start_synthesis（连接复用）: {_fmt(t_reuse)}")
    if syn2:
        await sp.call_tool("tts_volcengine_end_synthesis", {"syn_id": syn2}, ctx)


# ════════════════════════════════════════════════════════════
# 5. LLM 链路
# ════════════════════════════════════════════════════════════

async def bench_llm(sp, ctx):
    print("\n" + "=" * 70)
    print("5. LLM 链路（DeepSeek，真实网络，SSE 流式）")
    print("=" * 70)
    messages = [
        {"role": "system", "content": "你是一个测试助手，请简短回答。"},
        {"role": "user", "content": "请用一句话介绍你自己。"},
    ]

    # 5.1 start_chat（含 http_stream_open）
    t0 = time.perf_counter()
    r = await sp.call_tool("llm_openai_start_chat", {"messages": messages, "config": LLM_CONFIG}, ctx)
    t_start = (time.perf_counter() - t0) * 1000
    p = _parse(r)
    chat_id = p.get("chat_id", "")
    print(f"  start_chat（含 HTTP 流打开）: {_fmt(t_start)}  chat_id={chat_id}")
    if not chat_id:
        print(f"  !! 失败: {r[:200]}")
        return

    # 5.2 get_next 轮询（含 http_stream_read RPC），统计首 token 和每 token 延迟
    text = ""
    token_vals = []
    first_token = None
    for i in range(200):
        t0 = time.perf_counter()
        chunk = await sp.call_tool("llm_openai_get_next", {"chat_id": chat_id}, ctx)
        dt = (time.perf_counter() - t0) * 1000
        cp = _parse(chunk)
        if cp.get("done"):
            break
        token = cp.get("token", "")
        if token:
            text += token
            if first_token is None:
                first_token = dt
            token_vals.append(dt)
    print(f"  LLM 首 token 延迟（TTFT，含 http_stream_read RPC）: {_fmt(first_token) if first_token else 'n/a'}")
    print(f"  LLM 每 token get_next 延迟（含 http_stream_read RPC）: {_stats(token_vals)}")
    print(f"  LLM 完整回复 ({len(text)} 字符): {text[:80]}")
    await sp.call_tool("llm_openai_end_chat", {"chat_id": chat_id}, ctx)


# ════════════════════════════════════════════════════════════
# 6. ASR 链路
# ════════════════════════════════════════════════════════════

async def bench_asr(sp, ctx):
    print("\n" + "=" * 70)
    print("6. ASR 链路（火山引擎，真实网络）")
    print("=" * 70)

    # 6.1 start_session（含 ws_connect 连接建立）
    t0 = time.perf_counter()
    r = await sp.call_tool("asr_volcengine_start_session", {"config": ASR_CONFIG}, ctx)
    t_start = (time.perf_counter() - t0) * 1000
    p = _parse(r)
    sess_id = p.get("session_id", "")
    print(f"  start_session（含 WS 连接建立）: {_fmt(t_start)}  session_id={sess_id}")
    if not sess_id:
        print(f"  !! 失败: {r[:200]}")
        return

    # 6.2 send_audio（含 ws_send RPC），模拟 1KB 音频块
    audio_b64 = base64.b64encode(bytes(range(256)) * 4).decode("ascii")  # 1KB
    vals = []
    for _ in range(10):
        t0 = time.perf_counter()
        await sp.call_tool("asr_volcengine_send_audio", {"session_id": sess_id, "audio": audio_b64}, ctx)
        vals.append((time.perf_counter() - t0) * 1000)
    print(f"  send_audio 1KB（含 ws_send RPC）: {_stats(vals)}")

    # 6.3 get_result（含 ws_recv RPC）
    vals = []
    for _ in range(10):
        t0 = time.perf_counter()
        await sp.call_tool("asr_volcengine_get_result", {"session_id": sess_id}, ctx)
        vals.append((time.perf_counter() - t0) * 1000)
    print(f"  get_result（含 ws_recv RPC）: {_stats(vals)}")

    await sp.call_tool("asr_volcengine_end_session", {"session_id": sess_id}, ctx)


# ════════════════════════════════════════════════════════════
# 7. 连接池复用 / 预热效果（改造后）
# ════════════════════════════════════════════════════════════

ASR_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
TTS_URL = "wss://openspeech.bytedance.com/api/v3/tts/unidirectional/stream"


async def bench_connection_pool(sp_tts, sp_asr, ctx_tts, ctx_asr):
    print("\n" + "=" * 70)
    print("7. 连接池复用 / 预热效果（改造后）")
    print("=" * 70)

    # 7.1 TTS 连接池复用（reuse 模式）：连续 3 次合成，第 1 次建连，后续复用池
    if sp_tts:
        print("  -- TTS 连接池复用（reuse 模式）--")
        text = "你好，今天天气怎么样。"
        for i in range(3):
            t0 = time.perf_counter()
            r = await sp_tts.call_tool(
                "tts_volcengine_start_synthesis", {"text": text, "config": TTS_CONFIG}, ctx_tts
            )
            dt = (time.perf_counter() - t0) * 1000
            p = _parse(r)
            syn = p.get("syn_id", "")
            print(f"    start_synthesis #{i + 1}: {_fmt(dt)}  syn_id={syn}")
            if syn:
                await sp_tts.call_tool("tts_volcengine_end_synthesis", {"syn_id": syn}, ctx_tts)

    # 7.2 ASR 预热池（prewarm 模式）：第 1 次建连，后台预取；后续从预热池秒取
    if sp_asr:
        print("  -- ASR 预热池（prewarm 模式，会话间隔 0.5s 模拟真实场景）--")
        for i in range(3):
            t0 = time.perf_counter()
            r = await sp_asr.call_tool(
                "asr_volcengine_start_session", {"config": ASR_CONFIG}, ctx_asr
            )
            dt = (time.perf_counter() - t0) * 1000
            p = _parse(r)
            sess = p.get("session_id", "")
            print(f"    start_session #{i + 1}: {_fmt(dt)}  session_id={sess}")
            if sess:
                await sp_asr.call_tool("asr_volcengine_end_session", {"session_id": sess}, ctx_asr)
            await asyncio.sleep(0.5)


# ════════════════════════════════════════════════════════════

async def main():
    from src.infrastructure.plugin_loader import load_plugins
    from src.infrastructure.plugin_host.supervisor import get_plugin_supervisor

    print("加载插件（启动沙箱子进程）...")
    t0 = time.perf_counter()
    loaded = await load_plugins()
    print(f"  已加载插件: {loaded}  (耗时 {_fmt((time.perf_counter() - t0) * 1000)})")

    supervisor = get_plugin_supervisor()
    sp_tts = supervisor.get_plugin("tts_volcengine")
    sp_llm = supervisor.get_plugin("llm_openai")
    sp_asr = supervisor.get_plugin("asr_volcengine")
    print(f"  tts_volcengine 沙箱: {'已加载' if sp_tts else '未加载'}")
    print(f"  llm_openai 沙箱:    {'已加载' if sp_llm else '未加载'}")
    print(f"  asr_volcengine 沙箱: {'已加载' if sp_asr else '未加载'}")

    # 纯机制测量（不依赖网络）
    bench_base64()
    if sp_tts:
        ctx = supervisor._build_call_context(sp_tts, None, None, None, None)
        await bench_rpc_roundtrip(sp_tts, ctx)
    if sp_asr:
        ctx = supervisor._build_call_context(sp_asr, None, None, None, None)
        await bench_rpc_transfer(sp_asr, ctx)

    # 真实链路测量（依赖网络）
    if sp_tts:
        ctx = supervisor._build_call_context(sp_tts, None, None, None, None)
        try:
            await bench_tts(sp_tts, ctx)
        except Exception as e:
            import traceback
            print(f"  !! TTS 链路异常: {e}")
            traceback.print_exc()
    if sp_llm:
        ctx = supervisor._build_call_context(sp_llm, None, None, None, None)
        try:
            await bench_llm(sp_llm, ctx)
        except Exception as e:
            import traceback
            print(f"  !! LLM 链路异常: {e}")
            traceback.print_exc()
    if sp_asr:
        ctx = supervisor._build_call_context(sp_asr, None, None, None, None)
        try:
            await bench_asr(sp_asr, ctx)
        except Exception as e:
            import traceback
            print(f"  !! ASR 链路异常: {e}")
            traceback.print_exc()

    # 连接池复用 / 预热效果
    ctx_tts = supervisor._build_call_context(sp_tts, None, None, None, None) if sp_tts else None
    ctx_asr = supervisor._build_call_context(sp_asr, None, None, None, None) if sp_asr else None
    try:
        await bench_connection_pool(sp_tts, sp_asr, ctx_tts, ctx_asr)
    except Exception as e:
        import traceback
        print(f"  !! 连接池测试异常: {e}")
        traceback.print_exc()

    print("\n" + "=" * 70)
    print("测试完成")


if __name__ == "__main__":
    asyncio.run(main())
