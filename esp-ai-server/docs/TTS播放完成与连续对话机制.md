# TTS 播放完成与连续对话机制

## 1. 概述

本文档描述服务端如何通知设备 TTS 播放完成，以及如何实现连续对话（TTS 播放完成后自动进入下一轮 ASR）。

## 2. 完整流程

```
用户说话 → ASR 识别 → LLM 生成文本 → TTS 合成音频 → 发送音频帧 → 设备播放
                                                              ↓
                                                    发送 end_frame + tts_real_end
                                                              ↓
                                                    设备收到 tts_real_end
                                                              ↓
                                                    设备播放剩余缓冲区音频
                                                              ↓
                                                    设备发送 client_out_audio_over
                                                              ↓
                                                    服务端启动下一轮 ASR → 发送 iat_start
```

## 3. 服务端发送的关键消息

### 3.1 音频帧

服务端通过 WebSocket 二进制帧发送 TTS 音频数据，每帧包含：

| 字段 | 说明 |
|------|------|
| session_id | 会话 ID |
| 音频数据 | MP3 格式，24000Hz 采样率 |
| 序列号 | 帧序号，用于排序 |

### 3.2 end_frame

所有音频帧发送完毕后，服务端发送结束帧：

```json
// 二进制帧，由 voice_generator.make_end_frame(session_id) 生成
```

### 3.3 tts_real_end

结束帧发送后，服务端发送 TTS 结束状态：

```json
{
  "type": "session_status",
  "status": "tts_real_end"
}
```

设备收到 `tts_real_end` 后，知道不会再有新的音频数据，但缓冲区中可能还有未播放的音频。

### 3.4 iat_start

设备发送 `client_out_audio_over` 后，服务端发送 ASR 开始指令：

```json
{
  "type": "session_status",
  "status": "iat_start"
}
```

设备收到 `iat_start` 后，开始录音并上报音频流。

## 4. 设备端需要发送的消息

### 4.1 client_out_audio_over

设备在**音频实际播放完成后**发送此消息，通知服务端可以进入下一轮对话：

```json
{
  "type": "client_out_audio_over"
}
```

**关键**：必须在音频**完全播放完毕**后发送，而不是收到 `tts_real_end` 时立即发送。

### 4.2 client_available_audio

设备在播放音频期间，定期上报缓冲区使用量，服务端据此进行流量控制：

```json
{
  "type": "client_available_audio",
  "data": 5120
}
```

| 字段 | 说明 |
|------|------|
| data | 当前缓冲区已用字节数 |

服务端根据此值动态调整发送速率：
- 缓冲区使用率 ≤ 50%：正常发送（间隔 20ms）
- 缓冲区使用率 > 50%：减速发送（间隔 100ms）
- 缓冲区使用率 > 80%：暂停发送，等待设备消费

## 5. 设备端代码示例

### 5.1 tts_real_end 处理

```cpp
else if (status == "tts_real_end")
{
    tts_is_playing = false;

    // 等待音频实际播放完成，期间保持 WebSocket 活跃
    while (esp_ai.isSpeaking()) {
        webSocket_yw.loop();          // 保持 WebSocket 心跳
        vTaskDelay(pdMS_TO_TICKS(10)); // 让出 CPU
    }

    // 通知服务端音频播放完成
    JSONVar audio_over_msg;
    audio_over_msg["type"] = "client_out_audio_over";
    String sendData = JSON.stringify(audio_over_msg);
    webSocket_yw.sendTXT(sendData);
}
```

**注意**：
- `esp_ai.isSpeaking()` 检查播放器是否还在播放
- `webSocket_yw.loop()` 在等待期间保持 WebSocket 连接活跃，防止 idle 超时断开
- `vTaskDelay(pdMS_TO_TICKS(10))` 让出 CPU，避免阻塞其他任务

### 5.2 不等待播放完成的错误写法

```cpp
// ❌ 错误：收到 tts_real_end 立即发送，音频可能还在播放
else if (status == "tts_real_end")
{
    tts_is_playing = false;
    JSONVar audio_over_msg;
    audio_over_msg["type"] = "client_out_audio_over";
    webSocket_yw.sendTXT(JSON.stringify(audio_over_msg));
}
```

这会导致服务端在音频还没播放完时就启动 ASR，设备同时录音和播放，产生冲突。

### 5.3 阻塞等待的错误写法

```cpp
// ❌ 错误：awaitPlayerDone() 会阻塞，期间 WebSocket 心跳超时
else if (status == "tts_real_end")
{
    tts_is_playing = false;
    esp_ai.awaitPlayerDone();  // 阻塞！WebSocket 心跳停止
    JSONVar audio_over_msg;
    audio_over_msg["type"] = "client_out_audio_over";
    webSocket_yw.sendTXT(JSON.stringify(audio_over_msg));
}
```

这会导致设备在播放期间 WebSocket 心跳超时断开。

## 6. 服务端超时机制

服务端等待 `client_out_audio_over` 的超时时间为 **60 秒**：

```python
try:
    await asyncio.wait_for(
        ctx.tts_playback_done_event.wait(),
        timeout=60.0
    )
except asyncio.TimeoutError:
    warning("[TTS] 等待 client_out_audio_over 超时(60s)，强制继续")
```

超时后服务端会强制继续，启动下一轮 ASR。这通常意味着设备端没有正确发送 `client_out_audio_over`。

## 7. Keepalive 机制

服务端在 TTS 期间每 **1 秒**发送一次 keepalive，防止设备 idle 超时断开：

```json
{
  "type": "keepalive",
  "ts": 1714600000
}
```

非 TTS 期间间隔为 **3 秒**。

## 8. 故障排查

| 现象 | 可能原因 | 解决方案 |
|------|---------|---------|
| 设备长 TTS 期间断开 | 缓冲区溢出 | 检查 `client_available_audio` 是否正常上报 |
| 音频没播完就进入 ASR | `client_out_audio_over` 发送太早 | 确保等待 `isSpeaking()` 为 false 后再发送 |
| 60 秒超时强制继续 | 设备没发 `client_out_audio_over` | 检查设备端 `tts_real_end` 处理代码 |
| 设备播放期间断开 | WebSocket 心跳超时 | 确保等待播放期间调用 `webSocket_yw.loop()` |
| 短 TTS 正常，长 TTS 断开 | 发送速率过快 | 检查流量控制是否生效，`client_available_audio` 是否正常 |
