# 腾讯云 ASR VAD 处理注意事项

## 概述

本文档记录了在使用腾讯云 ASR 进行语音识别时，VAD（Voice Activity Detection，语音活动检测）处理的重要注意事项和已知问题。

## 腾讯云 ASR 响应格式

腾讯云 ASR 返回的响应是 JSON 格式，其中 `slice_type` 字段位于 `result` 对象内部，而不是直接在响应顶层。

### 正确的字段访问方式

```python
# 错误方式：result.get("slice_type") 始终返回 None
if result.get("slice_type") == 2:
    pass

# 正确方式：需要从 result["result"] 中获取
slice_type = result.get("result", {}).get("slice_type")
if slice_type == 2:
    pass
```

### slice_type 字段说明

| slice_type 值 | 含义 |
|---------------|------|
| 1 | 中间结果（partial result） |
| 2 | VAD 结束（end of speech） |

### 响应示例

```json
{
    "code": 0,
    "message": "success",
    "voice_id": "xxx-xxx-xxx",
    "result": {
        "slice_type": 2,
        "index": 0,
        "start_time": 0,
        "end_time": 1960,
        "voice_text_str": "你今天吃饭了没有？",
        "word_size": 0,
        "word_list": [],
        "emotion_type": null,
        "speaker_info": null
    }
}
```

## VAD 结束时设备通知

### 问题描述

当腾讯云检测到 VAD 结束时（即静音超过 `vad_silence_time` 配置的时间），服务端必须立即发送 `iat_end` 状态通知设备停止录音。

### 正确流程

1. 腾讯云返回 `slice_type=2` 的响应
2. 服务端检测到 VAD 结束
3. **立即**发送 `iat_end` 状态给设备端
4. 忽略后续收到的音频数据（设置 `asr_processed=True`）
5. 继续处理识别结果并发送 TTS 响应

### 关键代码逻辑

```python
# 在 on_vad_end 回调中
def on_vad_end():
    nonlocal asr_processed
    if not asr_processed:
        # 必须先设置标志，再发送消息
        asr_processed = True
        # 立即发送 iat_end 通知设备停止录音
        asyncio.create_task(on_vad_end_async())

async def on_vad_end_async():
    # 发送 iat_end 状态通知设备
    await websocket.send_json({"type": "session_status", "status": "iat_end"})
    # 然后执行后续的 ASR 结束和 TTS 响应逻辑
    asyncio.create_task(end_asr_and_send_response())
```

## asr_processed 标志管理

### 问题描述

`asr_processed` 标志用于防止重复处理音频数据。如果管理不当，会导致：

1. VAD 结束后仍然接收大量音频数据
2. 新的录音会话无法接收音频数据

### 正确的管理方式

#### 1. VAD 结束时立即设置

```python
def on_vad_end():
    nonlocal asr_processed
    if not asr_processed:
        asr_processed = True  # 立即设置
        asyncio.create_task(on_vad_end_async())
```

#### 2. 不要在异步函数中重复检查

```python
# 错误方式：在 on_vad_end_async 中再次检查
async def on_vad_end_async():
    nonlocal asr_processed
    if not asr_processed:  # 此时 asr_processed 已经是 True，不会执行
        asr_processed = True
        # 发送 iat_end...

# 正确方式：直接执行，不要重复检查
async def on_vad_end_async():
    # 直接发送 iat_end
    await websocket.send_json({"type": "session_status", "status": "iat_end"})
    # ...
```

#### 3. 新的录音会话开始时重置

```python
# 发送 iat_start 后重置标志
async def send_tts_response(websocket, ..., on_iat_start=None):
    # ... 处理 TTS 响应
    await websocket.send_json({"type": "session_status", "status": "iat_start"})
    # 重置标志，允许接收新的音频数据
    if on_iat_start:
        on_iat_start()
```

## 超时处理机制

### 问题描述

当用户唤醒设备后不说话时，系统需要能够正确超时并结束当前会话。

### 需要处理的超时场景

| 超时类型 | 触发条件 | 处理方式 |
|---------|---------|---------|
| 无音频超时 | ASR启动后 N 秒内无识别结果（基于 asr_start_time，不受设备音频包刷新影响） | 发送 session_end 结束会话 |
| 无ASR结果超时 | 2秒内没有新的ASR结果 | 发送当前识别结果 |
| 最大等待超时 | 超过最大等待时间（10秒） | 强制结束会话 |

### 关键实现

```python
# 需要记录 ASR 开始的绝对时间
asr_start_time = time.time()

async def check_no_asr_result_timeout():
    nonlocal last_asr_result_time, asr_processed, full_text, asr_start_time
    max_wait_time = 10  # 最大等待时间

    while not asr_processed:
        await asyncio.sleep(0.2)
        current_time = time.time()

        # 检查是否超过最大等待时间
        if asr_start_time and (current_time - asr_start_time) > max_wait_time:
            # 强制结束会话
            if not asr_processed:
                asr_processed = True
                asyncio.create_task(send_tts_response(websocket, iat_text=full_text))
            break

        # 检查是否2秒无ASR结果
        elif last_asr_result_time and (current_time - last_asr_result_time) > 2:
            # 发送当前识别结果
            if not asr_processed:
                asr_processed = True
                asyncio.create_task(send_tts_response(websocket, iat_text=full_text))
            break
```

## WebSocket 连接关闭

### 问题描述

腾讯云 ASR 的 WebSocket 连接关闭时，尝试访问 `ws.closed` 属性可能会报错。

### 错误信息

```
'ClientConnection' object has no attribute 'closed'
```

### 正确做法

```python
# 错误方式：检查 ws.closed 属性
finally:
    if ws and not ws.closed:
        await ws.close()

# 正确方式：直接尝试关闭
finally:
    if ws:
        try:
            await ws.close()
        except Exception as e:
            print(f"Error closing WebSocket: {e}")
```

## send_iat_end 参数控制

### 问题描述

在某些情况下（如 VAD 结束），`iat_end` 状态已经提前发送，如果再次在 `send_tts_response` 中发送会导致重复。

### 解决方案

在 `send_tts_response` 函数中添加 `send_iat_end` 参数：

```python
async def send_tts_response(websocket, session_id=SID_TTS, iat_text: str = "", send_iat_end: bool = True):
    if send_iat_end:
        await websocket.send_json({"type": "session_status", "status": "iat_end"})
        await asyncio.sleep(0.1)
    # ... 其他逻辑
```

调用时：

```python
# VAD 结束时：已经在 on_vad_end_async 中发送了 iat_end
await send_tts_response(websocket, iat_text=full_text, send_iat_end=False)

# 正常流程：需要发送 iat_end
await send_tts_response(websocket, iat_text=full_text)
```

## 完整流程图

```
设备唤醒 -> 发送 start -> 服务端开始 ASR 会话
                                    |
                                    v
                        腾讯云返回识别结果
                                    |
                                    v
                    收到 slice_type=2 (VAD结束)？
                        /                \
                       是                否
                        |                |
                        v                v
              发送 iat_end         检查超时
              设置asr_processed        |
              忽略后续音频          2秒无结果？
                        \              /
                         v            v
                          发送 TTS 响应
                          重置 asr_processed
                                    |
                                    v
                          发送 iat_start
                          开始新会话
```

## 配置参数

| 参数 | 值 | 说明 |
|------|-----|------|
| vad_silence_time | 2000ms | 腾讯云 VAD 静音检测时间 |
| NO_AUDIO_TIMEOUT | 5000ms | 本地无音频超时 |
| max_wait_time | 10s | ASR 最大等待时间 |
| no_asr_result_interval | 2s | 无 ASR 结果超时 |
