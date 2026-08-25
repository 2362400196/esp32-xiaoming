"""临时诊断脚本：复现 tts_volcengine 插件的 TTS V3 协议流程，查看火山真实响应。"""
import asyncio
import io
import json
import struct
import uuid

import websockets

API_KEY = "a0cee1c3-ce76-4919-9e71-701191700839"
RESOURCE_ID = "seed-tts-2.0"
VOICE_TYPE = "zh_female_vv_uranus_bigtts"
URL = "wss://openspeech.bytedance.com/api/v3/tts/unidirectional/stream"

MSG_TYPE_FULL_CLIENT_REQUEST = 0b1
MSG_TYPE_AUDIO_ONLY_SERVER = 0b1011
MSG_TYPE_FULL_SERVER_RESPONSE = 0b1001
MSG_TYPE_FRONT_END_SERVER = 0b1100
MSG_TYPE_ERROR = 0b1111
FLAG_NO_SEQ = 0
FLAG_WITH_EVENT = 0b100

EVENT_FINISH_SESSION = 102
EVENT_SESSION_FAILED = 153
EVENT_TTS_SENTENCE_START = 350
EVENT_TTS_SENTENCE_END = 351
EVENT_TTS_RESPONSE = 352


def _build_message(type_, flags=0, payload=b"", event=None, session_id="", sequence=0):
    buf = io.BytesIO()
    version = 0x1 << 4
    header_size = 0x1 << 0
    byte0 = (version | header_size).to_bytes(1, "big")
    byte1 = ((type_ << 4) | flags).to_bytes(1, "big")
    serialization = 0x1 << 4
    compression = 0x0 << 0
    byte2 = (serialization | compression).to_bytes(1, "big")
    byte3 = (0).to_bytes(1, "big")
    buf.write(byte0 + byte1 + byte2 + byte3)
    if flags & FLAG_WITH_EVENT:
        buf.write(struct.pack(">i", event or 0))
        skip_events = {2, 1, 50, 51}
        if event not in skip_events:
            sid_bytes = session_id.encode("utf-8")
            buf.write(struct.pack(">I", len(sid_bytes)))
            if sid_bytes:
                buf.write(sid_bytes)
    if flags & 0b1:
        buf.write(struct.pack(">i", sequence))
    buf.write(struct.pack(">I", len(payload)))
    if payload:
        buf.write(payload)
    return buf.getvalue()


def _parse_message(data):
    msg = {"type": None, "flags": 0, "event": None, "session_id": "", "sequence": 0,
           "payload": b"", "error_code": 0}
    if len(data) < 3:
        msg["type"] = MSG_TYPE_ERROR
        return msg
    buf = io.BytesIO(data)
    byte0 = buf.read(1)[0]
    byte1 = buf.read(1)[0]
    byte2 = buf.read(1)[0]
    msg["type"] = byte1 >> 4
    msg["flags"] = byte1 & 0b00001111
    header_size = byte0 & 0b00001111
    read_size = 3
    if padding := (header_size * 4) - read_size:
        buf.read(padding)
    flags = msg["flags"]
    if flags & FLAG_WITH_EVENT:
        ev_bytes = buf.read(4)
        if len(ev_bytes) == 4:
            msg["event"] = struct.unpack(">i", ev_bytes)[0]
        event = msg["event"]
        if event not in (1, 2, 50, 51):
            sid_len_bytes = buf.read(4)
            if len(sid_len_bytes) == 4:
                sid_len = struct.unpack(">I", sid_len_bytes)[0]
                if sid_len > 0:
                    msg["session_id"] = buf.read(sid_len).decode("utf-8", errors="replace")
        if event in (50, 51, 52):
            cid_len_bytes = buf.read(4)
            if len(cid_len_bytes) == 4:
                cid_len = struct.unpack(">I", cid_len_bytes)[0]
                if cid_len > 0:
                    msg["connect_id"] = buf.read(cid_len).decode("utf-8", errors="replace")
    if msg["type"] == MSG_TYPE_ERROR:
        ec_bytes = buf.read(4)
        if len(ec_bytes) == 4:
            msg["error_code"] = struct.unpack(">I", ec_bytes)[0]
    elif flags & 0b1:
        seq_bytes = buf.read(4)
        if len(seq_bytes) == 4:
            msg["sequence"] = struct.unpack(">i", seq_bytes)[0]
    plen_bytes = buf.read(4)
    if len(plen_bytes) == 4:
        plen = struct.unpack(">I", plen_bytes)[0]
        if plen > 0:
            msg["payload"] = buf.read(plen)
    return msg


async def main():
    headers = {
        "X-Api-Key": API_KEY,
        "X-Api-Resource-Id": RESOURCE_ID,
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }
    print(f"连接 {URL} ...")
    ws = await websockets.connect(URL, additional_headers=headers, open_timeout=15)
    print("连接成功，发送合成请求 ...")

    request = {
        "user": {"uid": str(uuid.uuid4())},
        "req_params": {
            "speaker": VOICE_TYPE,
            "audio_params": {
                "format": "mp3",
                "sample_rate": 24000,
                "speed_ratio": 1.0,
                "volume_ratio": 1.0,
                "pitch_ratio": 1.0,
            },
            "text": "你好，今天天气怎么样",
        },
    }
    frame = _build_message(MSG_TYPE_FULL_CLIENT_REQUEST, FLAG_NO_SEQ,
                           json.dumps(request, ensure_ascii=False).encode("utf-8"))
    await ws.send(frame)
    print("已发送请求帧，开始接收 ...")

    audio_total = 0
    for i in range(30):
        try:
            data = await asyncio.wait_for(ws.recv(), timeout=3.0)
        except asyncio.TimeoutError:
            print(f"[{i}] 3s 超时，无数据")
            continue
        msg = _parse_message(data)
        mtype = msg["type"]
        event = msg["event"]
        plen = len(msg["payload"])
        if mtype == MSG_TYPE_ERROR:
            print(f"[{i}] ERROR: code={msg['error_code']}")
            break
        if mtype == MSG_TYPE_AUDIO_ONLY_SERVER:
            audio_total += plen
            print(f"[{i}] AUDIO: {plen} bytes (累计 {audio_total})")
        elif mtype == MSG_TYPE_FULL_SERVER_RESPONSE:
            extra = ""
            if event == EVENT_TTS_SENTENCE_END and plen:
                audio_total += plen
                extra = f" (含音频 {plen}B, 累计 {audio_total})"
            print(f"[{i}] FULL_RESP: event={event} payload_len={plen}{extra}")
            if event == EVENT_FINISH_SESSION:
                print("  会话结束")
                break
            if event == EVENT_SESSION_FAILED:
                print(f"  合成失败: {msg['payload'][:200]}")
                break
        elif mtype == MSG_TYPE_FRONT_END_SERVER:
            print(f"[{i}] FRONT_END: payload_len={plen}")
        else:
            print(f"[{i}] 其他: type={mtype} event={event} payload_len={plen}")

    print(f"总音频: {audio_total} bytes")
    try:
        await ws.close()
    except Exception:
        pass
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
