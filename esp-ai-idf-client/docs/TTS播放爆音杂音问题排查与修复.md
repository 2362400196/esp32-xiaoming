# TTS 播放爆音杂音问题排查与修复

## 背景

本次问题发生在 `esp-ai-idf-client` 客户端播放服务端 TTS 音频时。现象是设备能收到 TTS，也能出声，但播放过程中出现明显爆音、杂音，听感像 MP3 数据流被破坏或解码器收到脏数据。

涉及项目：

- 客户端：`esp-ai-idf-client`
- 服务端：`esp-ai-server`
- 客户端关键文件：`main/websocket.c`、`main/audio.c`
- 服务端关键文件：`src/interfaces/tts_gateways.py`、`src/use_cases/pipeline.py`、`src/use_cases/voice_generator.py`

## 最终结论

根因是客户端没有正确处理 ESP-IDF WebSocket 的二进制消息分片。

服务端发送的 TTS 音频帧格式是：

```text
session_id(4 bytes) + status(2 bytes) + mp3_audio_data
```

客户端旧逻辑在每次 `WEBSOCKET_EVENT_DATA` 到来时，都直接把当前 `data_ptr` 的前 6 字节当作协议头解析，然后把后面的内容当 MP3 数据写入播放器。

但 ESP-IDF WebSocket 客户端可能会把同一条 binary message 拆成多个事件回调：

```text
完整消息:
0010 00 [MP3 bytes...]

事件 1:
payload_offset = 0
data_len = 16384

事件 2:
payload_offset = 16384
data_len = ...
```

旧逻辑会把事件 2 的前 6 个 MP3 字节误当成协议头丢掉，导致 MP3 字节流损坏。MP3 解码器继续寻找同步字并尝试解码残缺数据，最终表现为爆音、杂音、破裂声。

修复方式是在客户端增加 WebSocket binary message 重组逻辑：只有当 `payload_offset + data_len` 拼满 `payload_len` 后，才解析前 6 字节协议头并送入 MP3 解码链路。

## 排查过程

### 1. 先确认音频格式是否匹配

客户端 `main/config.h` 中配置：

```c
#define AUDIO_SAMPLE_RATE    24000
#define AUDIO_BITS_PER_SAMPLE 16
#define AUDIO_CHANNELS       1
```

服务端 `src/interfaces/tts_gateways.py` 中火山 TTS 请求参数：

```python
"audio_params": {
    "format": "mp3",
    "sample_rate": 24000,
    ...
}
```

客户端 WebSocket URL 也声明了：

```text
spk_sample_rate=24000
spk_channels=1
spk_format=mp3
```

因此采样率、声道数、编码格式基本匹配，不像是 16k/24k 播放速率不一致导致的问题。

### 2. 确认客户端播放链路

客户端播放链路大致如下：

```text
websocket_event_handler
  -> 收到 binary TTS frame
  -> audio_spk_write()
  -> StreamBuffer
  -> spk_task()
  -> Helix MP3 decode
  -> i2s_channel_write()
```

`main/audio.c` 中已经使用 Helix MP3 解码器，并且 I2S 输出配置为 24kHz、16bit、mono。播放链路整体是合理的。

### 3. 发现高风险点：二进制事件没有分片重组

旧版 `main/websocket.c` 的二进制消息处理逻辑是：

```c
if (data->data_len >= 6) {
    memcpy(session_id, data->data_ptr, 4);
    memcpy(status, data->data_ptr + 4, 2);

    const uint8_t *audio_data = data->data_ptr + 6;
    size_t audio_len = data->data_len - 6;
    audio_spk_write(audio_data, audio_len);
}
```

这段逻辑默认每次事件回调都是一条完整的业务帧。

但 ESP-IDF WebSocket 的事件数据结构中有：

- `payload_len`：完整 WebSocket message 的总长度
- `payload_offset`：当前分片在完整 message 中的偏移
- `data_len`：当前事件分片长度

如果 `payload_offset > 0`，说明当前回调不是业务帧开头，而是同一条 WebSocket message 的后续分片。后续分片不包含业务协议头，前 6 字节本身就是 MP3 数据。

旧逻辑在这种情况下会破坏 MP3 流。

### 4. 为什么会表现为爆音/杂音

MP3 是压缩帧格式，解码器依赖同步字和连续帧数据。丢掉任意几个字节可能造成：

- 当前帧解码失败；
- 解码器跳到错误同步位置；
- 部分帧被错误解码为异常 PCM；
- I2S 输出短时高幅度跳变；
- 听感上出现“啪”“刺啦”“爆裂”等杂音。

这类问题不一定每次都稳定复现，因为是否分片取决于 WebSocket buffer、网络栈、服务端发送块大小和当前负载。

## 修改内容

修改文件：

```text
esp-ai-idf-client/main/websocket.c
```

新增了 binary message 重组状态：

```c
static uint8_t *s_bin_msg_buf = NULL;
static size_t s_bin_msg_buf_cap = 0;
static size_t s_bin_msg_expected_len = 0;
static size_t s_bin_msg_received_len = 0;
```

新增完整消息处理函数：

```c
static void handle_audio_binary_message(const uint8_t *payload, size_t len)
```

这个函数只处理完整业务帧，职责包括：

- 校验长度是否至少 6 字节；
- 解析 `session_id` 和 `status`；
- 提取 MP3 音频数据；
- 跳过 ID3v2 tag；
- 调用 `audio_spk_write()` 写入播放缓冲；
- 收到 `03` 结束帧时调用 `audio_spk_wait_drain()` 并启动播放完成检测。

新增 WebSocket 分片重组函数：

```c
static void handle_audio_binary_event(const esp_websocket_event_data_t *data)
```

核心逻辑：

```text
如果 payload_offset == 0 且 data_len == payload_len:
    当前事件就是完整消息，直接处理

否则:
    按 payload_len 分配/复用重组缓冲区
    按 payload_offset 把当前分片 memcpy 到对应位置
    等 received_len >= expected_len 后，再处理完整消息
```

然后在 WebSocket binary 分支中优先调用：

```c
handle_audio_binary_event(data);
break;
```

这样旧的“每个事件直接解析前 6 字节”的路径不会再执行。

## 验证结果

用户重新编译并运行后，TTS 播放恢复正常，爆音和杂音消失。

这验证了根因确实是 WebSocket binary message 分片导致 MP3 数据流被破坏，而不是 TTS 采样率、I2S 参数或服务端音频格式本身的问题。

## 经验总结

### 1. WebSocket message 和 event callback 不是一回事

业务协议通常定义在“完整 WebSocket message”上，但 ESP-IDF 的事件回调可能只给出其中一个片段。

处理 binary 协议时，不能只看 `data_len`，必须结合：

- `payload_len`
- `payload_offset`
- `data_len`

### 2. 压缩音频对丢字节很敏感

PCM 丢几个字节可能只是轻微噪声或声道错位，但 MP3 丢字节会破坏帧结构，症状会更明显。

因此 MP3/AAC/Opus 这类压缩格式在传输层必须保证字节流完整。

### 3. 播放问题要先分层判断

本次排查顺序比较有效：

```text
服务端 TTS 格式
  -> 客户端声明能力
  -> WebSocket 帧封装
  -> 客户端 WebSocket 接收
  -> MP3 解码
  -> I2S 输出
```

先排除了格式不匹配，再定位到传输层分片处理，避免误改 I2S 和解码器。

## 后续建议

1. 可以把旧的不可达 binary 解析代码清理掉，让 `websocket.c` 更干净。
2. 可以在调试日志中临时打印 `payload_len/payload_offset/data_len`，方便确认是否发生分片。
3. 服务端也可以限制单个 WebSocket binary frame 大小，减少客户端重组内存压力。
4. 如果后续支持音乐播放或更大音频块，应把这套重组逻辑抽成通用 binary frame parser。
5. 当前文件中部分中文注释显示为乱码，建议后续统一保存为 UTF-8，避免补丁和日志排查困难。

