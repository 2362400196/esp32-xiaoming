"""临时诊断脚本：通过 Adjudicator 模拟沙箱 TTS 流程，验证裁决器 WS 层能否收到火山数据。"""
import asyncio
import io
import json
import struct
import uuid

from src.infrastructure.plugin_host.adjudicator import Adjudicator

API_KEY = "a0cee1c3-ce76-4919-9e71-701191700839"
RESOURCE_ID = "seed-tts-2.0"
VOICE_TYPE = "zh_female_vv_uranus_bigtts"
URL = "wss://openspeech.bytedance.com/api/v3/tts/unidirectional/stream"

MSG_TYPE_FULL_CLIENT_REQUEST = 0b1
MSG_TYPE_AUDIO_ONLY_SERVER = 0b1011
MSG_TYPE_FULL_SERVER_RESPONSE = 0b1001
MSG_TYPE_ERROR = 0b1111
FLAG_NO_SEQ = 0
FLAG_WITH_EVENT = 0b100

EVENT_FINISH_SESSION = 102
EVENT_SESSION_FAILED = 153
EVENT_TTS_SENTENCE_END = 351


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


async def main():
    adj = Adjudicator("tts_volcengine", ["network"])
    ctx = None  # ws 操作不使用 ctx

    headers = {
        "X-Api-Key": API_KEY,
        "X-Api-Resource-Id": RESOURCE_ID,
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }
    print("通过裁决器连接火山 TTS ...")
    sid = await adj._op_ws_connect({"url": URL, "headers": headers}, ctx)
    print(f"连接成功: {sid}")

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
    import base64
    await adj._op_ws_send({"session_id": sid, "data": base64.b64encode(frame).decode("ascii")}, ctx)
    print("已发送请求帧，开始 ws_recv 轮询（模拟插件 get_audio）...")

    audio_total = 0
    for i in range(20):
        result = await adj._op_ws_recv({"session_id": sid, "timeout": 0.5}, ctx)
        if result is None:
            print(f"[{i}] ws_recv 超时（None）")
            continue
        data = base64.b64decode(result)
        print(f"[{i}] ws_recv 收到 {len(data)} bytes")
        # 简单解析：只看前 4 字节类型
        if len(data) >= 2:
            mtype = data[1] >> 4
            if mtype == MSG_TYPE_AUDIO_ONLY_SERVER:
                plen = struct.unpack(">I", data[-4:])[0] if len(data) >= 4 else 0
                audio_total += len(data) - 12
                print(f"  AUDIO 帧, 总数据 {len(data)}B")
            elif mtype == MSG_TYPE_FULL_SERVER_RESPONSE:
                print(f"  FULL_RESP 帧")
            elif mtype == MSG_TYPE_ERROR:
                print(f"  ERROR 帧")
                break

    print(f"总音频: {audio_total} bytes")
    try:
        await adj._op_ws_close({"session_id": sid}, ctx)
    except Exception:
        pass
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
