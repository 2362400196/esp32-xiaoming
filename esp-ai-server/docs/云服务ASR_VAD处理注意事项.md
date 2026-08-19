# 云服务 ASR VAD 处理注意事项

## 概述

本文档记录了在使用云服务（如腾讯云、阿里云等）进行语音识别时，VAD（Voice Activity Detection，语音活动检测）处理的重要注意事项和通用实现策略。

## 云服务 ASR 响应格式

### 通用响应结构

不同云服务的 ASR 响应格式可能不同，但通常都包含以下信息：

- **状态码**：表示请求是否成功
- **识别结果**：包含识别到的文本
- **VAD 状态**：指示语音活动的结束

### 腾讯云 ASR 响应示例

```json
{
    "code": 0,
    "message": "success",
    "voice_id": "xxx-xxx-xxx",
    "result": {
        "slice_type": 2,  // 1: 中间结果, 2: VAD结束
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

### 阿里云 ASR 响应示例

```json
{
    "TaskId": "xxx-xxx-xxx",
    "Code": 200,
    "Message": "success",
    "Result": {
        "Sentences": [
            {
                "Text": "你今天吃饭了没有？",
                "StartTime": 0,
                "EndTime": 1960
            }
        ],
        "EndOfSpeech": true  // 指示VAD结束
    }
}
```

### 通用处理策略

1. **统一响应解析**：为不同云服务实现统一的响应解析器
2. **VAD 结束检测**：根据不同云服务的响应格式检测 VAD 结束
3. **错误处理**：统一处理不同云服务的错误码

## VAD 结束时设备通知

### 问题描述

当云服务检测到 VAD 结束时（即静音超过配置的时间），服务端必须立即发送 `iat_end` 状态通知设备停止录音。

### 正确流程

1. 云服务返回 VAD 结束的响应
2. 服务端检测到 VAD 结束
3. **立即**发送 `iat_end` 状态给设备端
4. 忽略后续收到的音频数据（设置 `asr_processed=True`）
5. 继续处理识别结果并发送 TTS 响应

### 关键代码逻辑

```python
# 在 VAD 结束回调中
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

## WebSocket 连接管理

### 问题描述

不同云服务的 WebSocket 连接管理方式可能不同，需要注意：

- 连接关闭时的属性访问
- 异常处理
- 资源释放

### 正确做法

```python
# 错误方式：依赖特定云服务的属性
finally:
    if ws and not ws.closed:  # 可能不存在 closed 属性
        await ws.close()

# 正确方式：直接尝试关闭并捕获异常
finally:
    if ws:
        try:
            await ws.close()
        except Exception as e:
            print(f"Error closing WebSocket: {e}")
```

## 云服务适配层

为了支持不同的云服务，建议实现一个适配层：

```python
class ASRAdapter:
    """ASR 适配器基类"""
    async def recognize(self, audio_chunks, callback=None):
        raise NotImplementedError
    
    def detect_vad_end(self, response):
        """检测 VAD 结束"""
        raise NotImplementedError

class TencentASRAdapter(ASRAdapter):
    """腾讯云 ASR 适配器"""
    def detect_vad_end(self, response):
        slice_type = response.get("result", {}).get("slice_type")
        return slice_type == 2

class AliyunASRAdapter(ASRAdapter):
    """阿里云 ASR 适配器"""
    def detect_vad_end(self, response):
        return response.get("Result", {}).get("EndOfSpeech", False)
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
                        云服务返回识别结果
                                    |
                                    v
                    检测到 VAD 结束？
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
| VAD_SILENCE_TIME | 2000ms | VAD 静音检测时间（不同云服务可能有不同的配置方式） |
| NO_AUDIO_TIMEOUT | 5000ms | 本地无音频超时 |
| MAX_WAIT_TIME | 10s | ASR 最大等待时间 |
| NO_ASR_RESULT_INTERVAL | 2s | 无 ASR 结果超时 |

## 开发注意事项

### 1. 响应格式适配

- 为不同云服务实现统一的响应解析器
- 重点关注 VAD 结束的检测方式
- 处理不同云服务的错误码

### 2. 设备通信

- 及时通知设备停止录音
- 确保 `iat_end` 状态的正确发送
- 避免重复发送状态消息

### 3. 状态管理

- 正确管理 `asr_processed` 标志
- 确保新会话开始时重置所有状态
- 避免竞态条件

### 4. 超时处理

- 实现多种超时机制
- 处理无音频、无结果的情况
- 防止会话无限等待

### 5. 资源管理

- 正确关闭 WebSocket 连接
- 处理异常情况
- 释放占用的资源

## 示例代码结构

```python
# 1. 云服务适配器
class ASRAdapter:
    # 适配不同云服务的接口

# 2. 主处理逻辑
async def websocket_endpoint(websocket):
    # 初始化
    # 处理消息
    # 管理状态

# 3. 超时检查
async def check_timeouts():
    # 检查各种超时情况

# 4. VAD 处理
async def handle_vad_end():
    # 处理 VAD 结束事件

# 5. 响应发送
async def send_responses():
    # 发送各种响应
```

## 总结

无论使用哪种云服务，以下几点是通用的关键注意事项：

1. **及时通知设备**：VAD 结束后立即发送 `iat_end`
2. **状态管理**：正确管理 `asr_processed` 标志
3. **超时处理**：实现多种超时机制
4. **错误处理**：妥善处理异常情况
5. **响应适配**：统一处理不同云服务的响应格式

通过遵循这些注意事项，可以构建一个稳定、可靠的语音识别系统，无论使用哪个云服务提供商。