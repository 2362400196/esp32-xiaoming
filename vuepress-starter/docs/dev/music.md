# 音乐播放协议

## 概述

音乐播放功能通过"语音点歌"实现完整链路：用户说出歌名 → ASR 识别 → LLM 调用 `play_music` 工具 → 外部音乐 API 搜索 → WebSocket 下发播放指令与歌词 → 设备 HTTP 流式播放并同步显示歌词。

当用户未指定歌名（如"随便放一首"、"播放音乐"）时，`play_music` 工具自动调用 `/random` 接口随机推荐一首歌，流程与点歌一致。

整个流程涉及三个层面：外部音乐搜索 API、服务端到设备的 WebSocket 指令协议、客户端歌词显示机制。

```
用户说"播放姑娘别哭泣"
  → ASR 识别文本
  → LLM 调用 play_music(song="姑娘别哭泣", artist="小阿七")
  → 服务端请求外部音乐 API:
      GET http://<music-api>/stream_pcm?song=姑娘别哭泣&artist=小阿七
      → 返回 {success, title, artist, audio_url, lyric_url, duration}
  → 服务端下载歌词: GET <lyric_url> → LRC 文本 → parse_lrc() 解析
  → WebSocket 依次下发:
      1. play_music(audio_url)      → 设备启动 HTTP 流式播放
      2. music_meta(title,...)       → 设备准备歌词接收
      3. lyric_line × N             → 设备逐行存储歌词
  → raise StopPipeline()            → 停止 TTS，独占音频通道
  → 设备定时器每 200ms 匹配歌词时间轴 → 屏幕滚动显示当前歌词行

用户说"随便放一首"
  → LLM 调用 play_music(song="")   ← song 留空
  → 服务端请求: GET http://<music-api>/random
  → 后续流程与点歌一致
```

---

## 音乐服务器 API

音乐播放依赖一个外部 HTTP 服务提供音乐文件管理和搜索能力。默认端口 `2233`。

### 接口一览

| 接口 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 健康检查 |
| `/stream_pcm?song=&artist=` | GET | 搜索歌曲（被服务端 `play_music` 工具调用）|
| `/random` | GET | 随机推荐一首歌（用户未指定歌名时调用）|
| `/api/songs` | GET | 获取所有歌曲列表 |
| `/music/:filename` | GET | 流式播放 MP3 文件（被设备 HTTP 客户端调用）|
| `/lyrics/:filename` | GET | 获取 LRC 歌词文件 |
| `/api/scan` | POST | 重新扫描音乐目录 |

### 部署方式

```bash
# 启动音乐服务
node server.js
```

音乐文件放在 `music/` 目录，支持 `.mp3` / `.ogg` / `.wav`。歌词文件放在 `lyrics/` 目录，文件名与音乐文件相同，后缀 `.lrc`。

文件名格式建议：`歌手 - 歌名.mp3`，服务端会自动解析出歌手和歌名。

---

## 音乐搜索 API

音乐搜索服务是一个独立的 HTTP 服务，默认运行在 `2233` 端口。服务端通过 `MUSIC_API_URL` 配置其地址。

### 搜索接口

```
GET <MUSIC_API_URL>/stream_pcm?song=<URL编码的歌名>&artist=<URL编码的歌手名>
```

**请求参数**：

| 参数 | 位置 | 必填 | 说明 |
|------|------|------|------|
| `song` | Query | 是 | 歌名，需 URL 编码（`urllib.parse.quote`）。若为空则改用 `/random` 接口 |
| `artist` | Query | 否 | 歌手名称，需 URL 编码，用于精确匹配同名歌曲的不同版本 |

**请求示例**：

```
GET http://192.168.31.176:2233/stream_pcm?song=唯一&artist=邓紫棋
```

**响应格式**（JSON）：

```json
{
  "success": true,
  "title": "姑娘别哭泣",
  "artist": "小阿七",
  "audio_url": "http://192.168.31.176:2233/music/xxx.mp3",
  "lyric_url": "http://192.168.31.176:2233/lyrics/姑娘别哭泣.lrc",
  "duration": 193
}
```

**字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | bool | 搜索是否成功，`false` 表示未找到歌曲 |
| `title` | string | 歌曲名称 |
| `artist` | string | 歌手名称，未知时为 `"未知"` |
| `audio_url` | string | MP3 音频直链，设备通过 HTTP 流式下载播放 |
| `lyric_url` | string | LRC 歌词文件 URL，为空则无歌词 |
| `duration` | int | 歌曲时长（秒） |

**失败响应**：

```json
{
  "success": false
}
```

> 服务端对 API 请求设置 10 秒超时。网络失败时 `play_music` 工具返回 `"音乐搜索服务暂不可用，请告知用户稍后重试"`，LLM 会将该信息转述给用户。

### 随机推荐接口

当用户未指定歌名（如"随便放一首"、"播放音乐"）时，`play_music` 工具的 `song` 参数留空，服务端转而调用随机推荐接口：

```
GET <MUSIC_API_URL>/random
```

无需任何参数，服务端从音乐库中随机选取一首歌曲返回。响应格式与搜索接口完全相同：

```json
{
  "success": true,
  "title": "晴天",
  "artist": "周杰伦",
  "audio_url": "http://192.168.31.176:2233/music/周杰伦 - 晴天.mp3",
  "lyric_url": "http://192.168.31.176:2233/lyrics/晴天.lrc",
  "duration": 269
}
```

> 随机推荐接口同样设置 10 秒超时。失败时 `play_music` 工具返回 `"随机推荐失败，音乐库可能为空，请稍后重试"`。

### 歌词接口

歌词通过 `lyric_url` 字段提供的独立 URL 获取，返回标准 LRC 格式纯文本：

```
GET <lyric_url>
```

**响应示例**（LRC 文本）：

```
[ti:姑娘别哭泣]
[ar:小阿七]
[00:00.00]姑娘别哭泣 - 小阿七
[00:12.50]我的心里住着一个你
[00:18.30]你说遇到的人全都像你
...
```

> 歌词下载设置 6 秒超时。下载或解析失败时返回空列表，不影响音乐播放，仅歌词不显示。

---

## LRC 歌词格式

### 格式规范

LRC 是行业标准的时间标签歌词格式，每行结构为：

```
[mm:ss.xx]歌词文本
```

| 字段 | 格式 | 说明 |
|------|------|------|
| `mm` | 1-3 位数字 | 分钟，范围 0-999 |
| `ss` | 2 位数字 | 秒，范围 00-59 |
| `xx` | 2-3 位数字 | 百分秒，2 位表示百分之一秒，3 位表示千分之一秒 |
| 歌词文本 | 任意字符串 | 该时间点对应的歌词内容 |

**支持的格式变体**：

```
[00:12.50]文本       ← 2 位百分秒（×10 = 500ms）
[00:12.500]文本      ← 3 位毫秒（×1 = 500ms）
[01:05.00]文本       ← 整秒
[1:05.00]文本        ← 分钟不补零
```

### 解析规则

服务端使用正则表达式解析 LRC：

```python
pattern = re.compile(r"\[(\d{1,3}):(\d{2})(?:\.(\d{2,3}))?\]\s*(.*)")
```

解析后转换为毫秒时间戳：

```python
time_ms = minutes * 60000 + seconds * 1000 + fraction_ms
```

百分秒部分的换算：

| 小数位数 | 含义 | 换算系数 | 示例 |
|---------|------|---------|------|
| 2 位 | 百分之一秒 | ×10 | `.50` → 500ms |
| 3 位 | 毫秒 | ×1 | `.500` → 500ms |

> 服务端正则 `(\d{2,3})` 仅匹配 2-3 位小数，**不支持 1 位小数**（如 `.5`），1 位小数的行会被跳过。

解析结果按 `time_ms` 升序排列，空行被过滤。ID 标签行（如 `[ti:]`、`[ar:]`）因不匹配时间格式被自动跳过。

### 时间偏移

歌词整体时间偏移通过 `LYRICS_OFFSET` 配置（单位：毫秒），用于修正歌词与音频的不同步问题：

```python
# 每行歌词的实际时间 = 原始时间 + 偏移量
line_time = original_time_ms + lyrics_offset
```

偏移量通过 `music_meta` 指令的 `lyric_offset_ms` 字段下发给设备，设备无需额外处理（服务端已在下发前加上偏移）。

---

## WebSocket 播放协议

服务端通过 WebSocket `instruct` 消息向设备下发音乐播放相关指令。所有指令格式统一为：

```json
{
  "type": "instruct",
  "command_id": "<指令名>",
  "data": "<数据内容>"
}
```

### play_music — 播放指令

```json
{
  "type": "instruct",
  "command_id": "play_music",
  "data": "http://192.168.31.176:2233/music/xxx.mp3"
}
```

`data` 字段为纯字符串，直接是 MP3 音频的 HTTP URL。设备收到后启动 HTTP 流式下载播放。

**设备端处理**（IDF 客户端，`audio_commands.c`）：

仅调用 `network_audio_play(url)` 启动 HTTP 流式播放（内部创建 FreeRTOS 任务）。IDF 客户端不在 `play_music` 指令中记录播放起始时间或重置歌词状态——进度定时器由第一条 `lyric_line` 到达时启动（见下文）。

### music_meta — 歌曲元信息

```json
{
  "type": "instruct",
  "command_id": "music_meta",
  "data": "{\"title\":\"姑娘别哭泣\",\"artist\":\"小阿七\",\"duration\":193,\"lyric_url\":\"http://...\",\"lyric_count\":48,\"lyric_offset_ms\":400}"
}
```

`data` 字段为 JSON 字符串，包含歌曲完整元信息：

| 字段 | 类型 | 说明 |
|------|------|------|
| `title` | string | 歌曲名称 |
| `artist` | string | 歌手名称 |
| `duration` | int | 歌曲时长（秒） |
| `lyric_url` | string | 歌词文件 URL（供设备后续扩展使用） |
| `lyric_count` | int | 即将下发的 `lyric_line` 指令总数 |
| `lyric_offset_ms` | int | 歌词时间偏移量（毫秒），已应用到实际下发的歌词时间中 |

**设备端处理**（IDF 客户端，`lyric_commands.c`）：

1. 解析 `data` JSON 字符串，提取 `title`/`song_name` 与 `artist`
2. 调用 `eeui_port_music_set_song_info(song, artist)` 设置歌曲信息
3. **不读取** `duration`、`lyric_count`、`lyric_offset_ms`（这些字段仅服务端使用，偏移量已在下发前应用到歌词时间中）

### lyric_line — 歌词行

```json
{
  "type": "instruct",
  "command_id": "lyric_line",
  "data": "{\"index\":0,\"time\":0,\"text\":\"姑娘别哭泣 - 小阿七\"}"
}
```

服务端按顺序逐行下发，共下发 `lyric_count` 次。`data` 字段为 JSON 字符串：

| 字段 | 类型 | 说明 |
|------|------|------|
| `index` | int | 歌词行索引，从 0 开始递增 |
| `time` | int | 该行歌词的时间戳（毫秒），已包含 `lyric_offset_ms` 偏移 |
| `text` | string | 歌词文本内容 |

**设备端处理**（IDF 客户端，`lyric_commands.c`）：

1. 解析 JSON 提取 `time` 和 `text`
2. 调用 `add_lyric(time, text)` 存入歌词缓冲区（`s_lyrics_text[]`/`s_lyrics_time[]`），内部用冒泡排序保持时间递增
3. **不比较 `lyric_count`**——第一条歌词到达即启动进度定时器 `start_progress_timer()`，并立即显示第一条歌词

### music_gen_ing — AI 创作中状态

```json
{
  "type": "instruct",
  "command_id": "music_gen_ing",
  "data": ""
}
```

用于 AI 音乐生成场景，通知设备进入"歌曲创作中"状态。`data` 字段为空字符串。

> 注意：此指令不由 `play_music` 工具发送；当前服务端代码中未实现 AI 音乐生成流程，该指令暂无发送方（设备端已支持处理）。

**设备端处理**（IDF 客户端，`callback_commands.c`）：

1. 切换表情为"无情绪"：`display_show_emotion("无情绪")`
2. 状态栏显示"歌曲创作中"：`display_show_status("歌曲创作中")`

### music_end — 播放结束

```json
{
  "type": "instruct",
  "command_id": "music_end",
  "data": ""
}
```

音乐播放结束时通知客户端清理歌词状态并隐藏播放器界面。`data` 字段为空字符串。注意：服务端 `play_music` 流程**不会自动发送** `music_end`，仅在睡眠定时器触发等场景由服务端下发，常规播放结束依赖设备端播放完成回调。

**设备端处理**（IDF 客户端，`lyric_commands.c`，`cmd_music_end`）：

1. 将进度推进到末尾：`eeui_port_music_update_progress(total_ms, total_ms)`
2. 调用 `reset_all()` 停止进度定时器、释放所有 `s_lyrics_text[i]` 内存、重置 `s_lyrics_count`/`s_current_lyric_index`/`s_start_time_us`/`s_total_ms`
3. 隐藏播放器覆盖层：`eeui_port_hide_music_player()`（由下一次 `play_music` 指令触发重建）

### stop_music — 停止播放

```json
{
  "type": "instruct",
  "command_id": "stop_music",
  "data": ""
}
```

停止网络音乐播放（服务端睡眠定时器触发或主动停止时下发，`alarm_manager` / 会话停止流程会发送该指令）。

### 指令时序

服务端按下述顺序发送指令，中间无额外等待：

```
1. play_music(audio_url)              ← 立即开始播放
2. music_meta(meta_json)              ← 准备接收歌词
3. lyric_line(line_0)                 ← 第 0 行
4. lyric_line(line_1)                 ← 第 1 行
   ...
N. lyric_line(line_{count-1})         ← 最后一行
   raise StopPipeline()               ← 停止 TTS pipeline
   ...（播放进行中，设备 200ms 定时器驱动歌词滚动）...
   music_end                          ← 播放结束时下发，客户端清理并隐藏播放器
```

> 所有指令通过 `channel.send_json()` 异步发送。`play_music` 必须最先发送，确保设备在接收歌词期间已经开始播放音频。发送完成后 `raise StopPipeline()` 终止 LLM → TTS pipeline，避免 TTS 语音与音乐争抢音频通道。

---

## 客户端歌词显示机制

以下为 IDF 客户端（`lyric_commands.c`）的实现。

### 状态变量

| 变量 | 类型 | 作用 |
|------|------|------|
| `s_lyrics_text[200]` | `char*` 数组 | 歌词文本缓冲区，`MAX_LYRICS = 200` |
| `s_lyrics_time[200]` | `uint32_t` 数组 | 各行歌词的时间戳（毫秒） |
| `s_lyrics_count` | `int` | 已存入的歌词行数 |
| `s_current_lyric_index` | `int` | 当前显示的歌词行索引，`-1` 表示未开始显示 |
| `s_start_time_us` | `uint64_t` | 进度定时器启动时刻（`esp_timer_get_time()`，微秒） |
| `s_total_ms` | `uint32_t` | 歌曲总时长（毫秒），初始 `300000`，随歌词时间动态增长 |
| `s_progress_timer` | `esp_timer_handle_t` | 200ms 周期定时器句柄 |
| `s_lyric_mutex` | `SemaphoreHandle_t` | 互斥锁，保护歌词数组与进度状态 |

### 时间对齐算法

歌词显示由 200ms 周期定时器回调 `progress_timer_cb` 驱动：

```
elapsed = (esp_timer_get_time() - s_start_time_us) / 1000   // 毫秒
if elapsed > s_total_ms: elapsed = s_total_ms

从前向后遍历 s_lyrics_time，找到第一个 time > elapsed 的行
→ new_index = 该行下标 - 1
若所有行 time 都 <= elapsed → new_index = s_lyrics_count - 1（最后一行）
```

从前向后遍历：找到第一个时间点超过当前播放进度的歌词行，其前一行即为当前应显示的歌词。

### 渲染逻辑

```
┌─ s_start_time_us == 0 或 s_total_ms == 0?
│   └─ 是 → return（定时器尚未启动）
│
├─ 计算 elapsed，从前向后遍历定位 new_index
│
└─ new_index != s_current_lyric_index 且 new_index >= 0?
    └─ 是 → 更新 s_current_lyric_index
            调用 eeui_port_music_update_lyrics(current, next) 刷新当前歌词
    └─ 否 → 跳过（避免每 200ms 重复刷新相同歌词）

（每次回调末尾）调用 eeui_port_music_update_progress(elapsed, total_ms) 更新进度条
```

**关键设计**：

- 歌词索引变化时才调用 `eeui_port_music_update_lyrics()`，避免每 200ms 重复渲染相同内容
- 所有共享状态访问（歌词数组、`s_total_ms`、`s_current_lyric_index`）均在 `s_lyric_mutex` 互斥锁保护下进行，防止 `music_end` 释放内存时定时器回调 use-after-free
- 进度定时器在**第一条 `lyric_line` 到达时**启动（`start_progress_timer()`），而非 `play_music` 指令到达时
- `s_total_ms` 随歌词时间动态增长：每收到一行歌词，若 `time + 10000 > s_total_ms` 则更新

### 启动与清理

**启动**（`lyric_line` 处理中，第一条歌词到达）：

1. 记录 `s_start_time_us = esp_timer_get_time()`
2. 创建并启动 200ms 周期定时器 `s_progress_timer`
3. 立即显示第一条歌词：`eeui_port_music_update_lyrics(s_lyrics_text[0], next)`，置 `s_current_lyric_index = 0`

**清理**（`music_end` 指令到达，`cmd_music_end`）：

1. 进度推进到末尾：`eeui_port_music_update_progress(total_ms, total_ms)`
2. `reset_all()`：停止定时器、释放所有 `s_lyrics_text[i]` 内存、重置 `s_lyrics_count = 0`、`s_current_lyric_index = -1`、`s_start_time_us = 0`、`s_total_ms = 300000`
3. 隐藏播放器覆盖层：`eeui_port_hide_music_player()`（下一次 `play_music` 触发重建）

---

## 配置说明

### 全局配置

通过 `.env` 文件配置，作用于所有设备：

```ini
# 音乐播放配置
MUSIC_API_URL=http://192.168.31.176:2233
LYRICS_OFFSET=400
```

| 环境变量 | 对应配置项 | 默认值 | 说明 |
|---------|-----------|--------|------|
| `MUSIC_API_URL` | `music.api_url` | `""` | 音乐搜索 API 地址，为空则禁用音乐功能 |
| `LYRICS_OFFSET` | `music.lyrics_offset` | `0` | 歌词时间偏移（毫秒），正值延后显示，负值提前 |

### 按设备配置（数据库）

通过 API 或 App 为设备设置 `music` 字段，优先级高于全局配置：

```json
{
  "api_url": "http://192.168.31.176:2233",
  "lyrics_offset": 0
}
```

在 App 的「我的 → 音乐服务配置」中填写地址即可自动保存到设备数据库。

### 配置优先级

```
设备 music_config.api_url > 全局 MUSIC_API_URL
设备 music_config.lyrics_offset > 全局 LYRICS_OFFSET
```

若两者均未配置，`play_music` 工具返回 `"音乐服务未配置，请告知管理员在 .env 中设置 MUSIC_API_URL"`。

---

## StopPipeline 与音频通道独占

`play_music` 工具发送完所有指令后抛出 `StopPipeline` 异常，终止 LLM → TTS pipeline，防止 TTS 语音总结（如"好的，马上为你播放"）与音乐争抢 I2S 音频通道。

异常传播链路：

```
play_music() raise StopPipeline
  ↓
tool_manager.call_tool()  except StopPipeline: raise   ← 透传
  ↓
openai_llm.stream_chat()  except StopPipeline: raise   ← 重新抛出
  ↓
pipeline.llm_pipeline()   except StopPipeline: raise   ← 穿透
  ↓
ws_session_handler         except StopPipeline:
  - 取消正在进行的 TTS 任务
  - 排空音频队列
  - 不触发 ASR 重启（让设备专注播放音乐）
```

> 音乐播放结束后，设备不会自动重启 ASR。用户需通过唤醒词或按键重新唤醒设备，进入下一轮对话。

---

## 完整交互时序

```
服务端                                     设备
  │                                        │
  │  LLM 调用 play_music("姑娘别哭泣")      │
  │                                        │
  │  GET /stream_pcm?song=姑娘别哭泣       │
  │  ← {success, audio_url, lyric_url,...} │
  │                                        │
  │  GET <lyric_url>                       │
  │  ← LRC 歌词文本                        │
  │  parse_lrc() → 48 行                   │
  │                                        │
  │  ── play_music(audio_url) ────────→    │  on_command("play_music")
  │                                        │  └─ network_audio_play(url)
  │                                        │     └─ HTTP 流式下载 → 解码播放
  │                                        │
  │  ── music_meta(meta) ─────────────→    │  on_command("music_meta")
  │                                        │  └─ eeui_port_music_set_song_info(title, artist)
  │                                        │     （不读取 duration/lyric_count/lyric_offset_ms）
  │                                        │
  │  ── lyric_line(0) ────────────────→    │  on_command("lyric_line")
  │  ── lyric_line(1) ────────────────→    │  └─ add_lyric(time, text) 存入缓冲区
  │  ...                                   │     第一条到达 → start_progress_timer()
  │  ── lyric_line(47) ───────────────→    │  └─ 歌词持续接收
  │                                        │
  │  raise StopPipeline()                  │
  │  停止 TTS，不生成语音总结               │
  │                                        │
  │                                        │  progress_timer_cb (每 200ms)
  │                                        │  │
  │                                        │  ├─ t=0ms:    "姑娘别哭泣 - 小阿七"
  │                                        │  ├─ t=12500ms: "我的心里住着一个你"
  │                                        │  ├─ t=18300ms: "你说遇到的人全都像你"
  │                                        │  └─ ...
  │                                        │
  │  ── music_end（睡眠定时器 / 停止流程触发）→ │  on_command("music_end")
  │                                        │  └─ reset_all() + eeui_port_hide_music_player()
```

---

## 自定义音乐服务接入

若使用自建的音乐服务，需实现以下两个接口：

### 搜索接口

```
GET <your-server>/stream_pcm?song=<URL编码歌名>&artist=<URL编码歌手名>
```

返回格式必须包含以下字段：

```json
{
  "success": true,
  "title": "歌曲名",
  "artist": "歌手",
  "audio_url": "http://your-server/path/to/song.mp3",
  "lyric_url": "http://your-server/path/to/lyrics.lrc",
  "duration": 200
}
```

- `audio_url` 必须是设备可直接 HTTP GET 的 MP3 直链
- `lyric_url` 可为空字符串（无歌词）
- `success` 为 `false` 时服务端返回"未找到歌曲"

### 歌词接口

```
GET <lyric_url>
```

返回标准 LRC 格式纯文本，编码 UTF-8。

### 接入步骤

1. 部署音乐服务，确保设备网络可访问 `audio_url` 和 `lyric_url`
2. 在 `.env` 中设置 `MUSIC_API_URL` 指向你的服务地址
3. 如需歌词偏移修正，设置 `LYRICS_OFFSET`（单位毫秒）
4. 重启服务端使配置生效
5. 对设备说"播放 XXX"测试完整链路

> `audio_url` 指向的 MP3 文件需支持 HTTP Range 请求（流式下载）。若服务器仅支持完整下载，设备会等待整个文件下载完成后才开始播放，首音延迟较高。
