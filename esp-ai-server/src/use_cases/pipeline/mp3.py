"""MP3 帧头解析与字级时间戳估算。"""
from __future__ import annotations

# MP3 帧头解析：按比特率表计算每帧时长，累加得到总时长（支持 CBR/VBR）
# 注意：MPEG2/2.5 Layer III 的比特率仅为 MPEG1 的一半（8~160kbps）
_MP3_BITRATE = {
    (3, 1): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0],  # MPEG1 L3
    (2, 1): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],      # MPEG2 L3
    (0, 1): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],      # MPEG2.5 L3
}
_MP3_SAMPLE_RATE = {
    3: [44100, 48000, 32000, 0],  # MPEG1
    2: [22050, 24000, 16000, 0],  # MPEG2
    0: [11025, 12000, 8000, 0],   # MPEG2.5
}


def mp3_duration_ms(data: bytes) -> int:
    """解析 MP3 帧头计算总时长（ms）。仅处理 Layer III（TTS 输出格式）。"""
    if not data:
        return 0
    total_ms = 0
    pos = 0
    n = len(data)
    while pos + 4 <= n:
        if data[pos] != 0xFF or (data[pos + 1] & 0xE0) != 0xE0:
            pos += 1
            continue
        b1 = data[pos + 1]
        b2 = data[pos + 2]
        version = (b1 >> 3) & 0x03  # 3=MPEG1, 2=MPEG2, 0=MPEG2.5
        layer = (b1 >> 1) & 0x03    # 1=Layer III
        if version == 1 or layer != 1:
            pos += 1
            continue
        bitrate_idx = (b2 >> 4) & 0x0F
        sample_idx = (b2 >> 2) & 0x03
        padding = (b2 >> 1) & 0x01
        bitrate_kbps = _MP3_BITRATE.get((version, layer), [0] * 16)[bitrate_idx]
        sample_rate = _MP3_SAMPLE_RATE.get(version, [0] * 4)[sample_idx]
        if bitrate_kbps == 0 or sample_rate == 0:
            pos += 1
            continue
        if version == 3:
            frame_len = 144 * bitrate_kbps * 1000 // sample_rate + padding
            samples = 1152
        else:
            frame_len = 72 * bitrate_kbps * 1000 // sample_rate + padding
            samples = 576
        if frame_len <= 0:
            pos += 1
            continue
        total_ms += samples * 1000 // sample_rate
        pos += frame_len
    return total_ms


_PUNCT_CHARS = set("，。！？、；：,.!?;:…—～·()（）《》<>「」【】\"'“”‘’")


def _estimate_word_timestamps(text: str, total_ms: int) -> list[dict]:
    """为无字级时间戳的 TTS 生成估算字级时间戳（句内相对毫秒）。

    切分：汉字逐字；连续英文字母/数字按词；标点并入前词（不占权重）。
    时间分配：按字符权重加权均分 total_ms，长词占更多时长，更贴近发音节奏。
    返回与火山 TTS 相同的 words 结构：{word, start_ms, end_ms}。
    """
    if not text or total_ms <= 0:
        return []

    words: list[dict] = []
    cur_word = ""
    cur_weight = 0

    def flush():
        nonlocal cur_word, cur_weight
        if cur_word:
            words.append({"word": cur_word, "weight": cur_weight})
            cur_word = ""
            cur_weight = 0

    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            flush()
            words.append({"word": ch, "weight": 1})
        elif ch in _PUNCT_CHARS or ch.isspace():
            # 标点/空白先落盘未决的英文词，再并入前词尾部（不占权重），保证拼接保真
            if cur_word:
                flush()
            if words:
                words[-1]["word"] += ch
            else:
                words.append({"word": ch, "weight": 0})
        elif ch.isalnum() or ch in "-_":
            cur_word += ch
            cur_weight += 1
        else:
            flush()
    flush()

    if not words:
        return []

    total_weight = sum(w["weight"] for w in words)
    if total_weight <= 0:
        total_weight = len(words)
        for w in words:
            w["weight"] = 1

    pos = 0
    out = []
    for w in words:
        span = int(total_ms * w["weight"] / total_weight)
        start_ms = pos
        end_ms = pos + span
        out.append({"word": w["word"], "start_ms": start_ms, "end_ms": end_ms})
        pos = end_ms
    if out:
        out[-1]["end_ms"] = total_ms  # 消除整数除法累计误差，末字对齐句尾
    return out
