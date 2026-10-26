# -*- coding: utf-8 -*-
"""分析 ESP_AI_ASR_DUMP 落盘的 ASR 上行 PCM。

用法：
    python scripts/_asr_dump_analyze.py [pcm 文件或 logs/asr_dump 目录]

输出：
- 时长、整体音量
- 每 64ms 一格的响度包络（0-9，越大越响），用来一眼看出"人声在什么位置"
- 检测到的人声段（连续 > 门限的帧）
- 同名 .wav（16k/16bit/单声道），可直接播放核对

纯标准库，不依赖 numpy。
"""
from __future__ import annotations

import sys
import wave
from array import array
from pathlib import Path

SAMPLE_RATE = 16000
FRAME_MS = 32          # 设备每包 1024 bytes = 32ms
SPEECH_DBFS = -45.0    # 判定"有声音"的门限
ENV_MS = 64            # 包络一格的最小粒度


def _db(pcm: array, start: int, end: int) -> float:
    """返回 [start, end) 区间的 RMS 电平（dBFS，满量程 32768）"""
    n = end - start
    if n <= 0:
        return -120.0
    acc = 0
    for i in range(start, end):
        v = pcm[i]
        acc += v * v
    rms = (acc / n) ** 0.5
    if rms <= 1e-9:
        return -120.0
    import math

    return 20.0 * math.log10(rms / 32768.0)


def analyze(path: Path) -> None:
    raw = path.read_bytes()
    pcm = array("h")
    pcm.frombytes(raw[: len(raw) // 2 * 2])
    total_s = len(pcm) / SAMPLE_RATE
    print(f"\n=== {path.name} ===")
    print(f"时长 {total_s:.2f}s  样本 {len(pcm)}  文件 {len(raw)} bytes")

    frame = SAMPLE_RATE * FRAME_MS // 1000
    levels = []
    for i in range(0, len(pcm) - frame + 1, frame):
        levels.append(_db(pcm, i, i + frame))
    if not levels:
        print("音频太短，无法分析")
        return

    loud = [d for d in levels if d > SPEECH_DBFS]
    print(f"整体峰值电平 {max(levels):.1f} dBFS，>{SPEECH_DBFS:.0f}dBFS 的帧占 "
          f"{len(loud)}/{len(levels)}（{len(loud) * FRAME_MS / 1000:.2f}s）")

    # 包络：每格 ENV_MS，取格内最大值
    step = max(1, ENV_MS // FRAME_MS)
    env = []
    for i in range(0, len(levels), step):
        peak = max(levels[i:i + step])
        norm = max(0.0, min(1.0, (peak + 70.0) / 70.0))  # -70..0 dBFS → 0..1
        env.append(str(min(9, int(norm * 10))))
    print("包络(-70..0dBFS, 每格 " + str(ENV_MS) + "ms):")
    for i in range(0, len(env), 50):
        seg = "".join(env[i:i + 50])
        print(f"  {i * ENV_MS / 1000:6.2f}s |{seg}")

    # 人声段
    segs = []
    start = None
    for idx, d in enumerate(levels):
        if d > SPEECH_DBFS and start is None:
            start = idx
        elif d <= SPEECH_DBFS and start is not None:
            if idx - start >= 3:  # 至少 96ms 才算一段
                segs.append((start * FRAME_MS / 1000, idx * FRAME_MS / 1000))
            start = None
    if start is not None:
        segs.append((start * FRAME_MS / 1000, len(levels) * FRAME_MS / 1000))
    if segs:
        print("候选人声段: " + ", ".join(f"{a:.2f}~{b:.2f}s" for a, b in segs))
    else:
        print("候选人声段: 无（整段低于门限）")

    wav_path = path.with_suffix(".wav")
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    print(f"wav 已写入: {wav_path}")


def main() -> None:
    args = sys.argv[1:]
    target = Path(args[0]) if args else Path(__file__).resolve().parents[1] / "logs" / "asr_dump"
    files = [target] if target.is_file() else sorted(target.glob("*.pcm"))
    if not files:
        print(f"没有找到 pcm 文件: {target}")
        return
    for f in files:
        analyze(f)


if __name__ == "__main__":
    main()
