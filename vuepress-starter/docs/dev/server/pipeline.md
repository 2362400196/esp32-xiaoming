# Pipeline 流式处理详解

## 概述

Pipeline 是服务端把 LLM 文本输出实时转化为 TTS 音频并推送到设备的核心流水线。它把一个完整的"听—想—说"周期拆解成四个异步 Worker，通过三级背压队列串联，使 LLM 产出、句子切分、TTS 合成、网络发送四件事并行推进，而不是串行等待。

整个流水线的目标是把首句语音延迟压到最低，同时在长文本场景下不会把客户端的音频缓冲塞爆。本文从架构、分句策略、`run` 方法的七个阶段、首句加速、流量控制、时长估算、`StopPipeline` 中断机制到配置项依次展开。

## 四 Worker 并发架构

### 流水线图

```
LLM Worker ──text_queue──▶ Splitter Worker ──audio_queue──▶ TTS Worker ──send_queue──▶ Sender Worker
  (token)                   (sentence)                     (audio chunk)              (WS frame)
```

四个 Worker 都是 `asyncio.Task`，由 `run` 方法并行启动。每一级之间通过独立的队列解耦，前一级慢时后一级可以继续消费已积累的数据，反之亦然。

### Worker 职责

| Worker | 上游队列 | 下游队列 | 核心职责 |
|---|---|---|---|
| LLM Worker | — | `text_queue` | `llm.stream_chat` 拉取 token，喂给 `SentenceSplitter`，把成句写入队列 |
| Splitter Worker | `text_queue` | `audio_queue` | 过滤空句（`len <= 1`），透传哨兵，不参与切分逻辑 |
| TTS Worker | `audio_queue` | `send_queue` | Markdown 清理、情绪检测、TTS 合成、时长估算与修正 |
| Sender Worker | `send_queue` | WSChannel | 文本/时长帧、音频帧、首帧 `play_audio`、基于 `device_buffer` 的流量控制 |

### 三级背压队列

`BackpressureQueues` 提供三个独立队列，容量与满策略各不相同，对应不同的反压需求：

| 队列名 | maxsize | 满策略 | 哨兵 | 用途 |
|---|---|---|---|---|
| `text` | 10 | `drop_oldest` | `(-1, None)` | LLM 产 token 远快于下游时丢最旧句，避免堆积 |
| `audio` | 20 | `block` | `(-1, None, None)` | TTS 合成耗时较长，阻塞上游使其降速 |
| `send` | 256 | `block` | `(-1, None, None)` | 网络抖动缓冲，阻塞 TTS Worker |

`drop_oldest` 仅出现在 `text` 队列：LLM 一次可能吐出大量 token，若坚持 block 会让 LLM 卡住甚至触发超时，丢最旧句比丢当前句更可接受，因为旧句对应的音频已经接近过期。`audio` 和 `send` 用 `block` 是因为这两级直接关联音频质量，丢帧会产生可感知的卡顿。

哨兵逐级透传：LLM 结束后向 `text_queue` 投 `(-1, None)`；Splitter 把有效句转为三元组 `(seq_id, sentence, sentence)` 入 `audio_queue`，哨兵以三元组 `(-1, None, None)` 透传；TTS 再透传给 `send_queue`，Sender 收到哨兵后开始收尾。

## SentenceSplitter 分句策略

`SentenceSplitter` 维护一个内部 `buffer`，每次 `feed(token)` 把 token 追加到 buffer，然后尝试切分。切分模式分三种：

### 切分模式

| 切分类型 | 触发标点 | 阈值条件 | 行为 |
|---|---|---|---|
| 硬切分 | `。！？.!?` | 句子 `len > 1` | `re.split` 按标点分段，逐段 `strip` 后入列 |
| 软切分 | `，；,` | 子句长度 ≥ 2（`last_soft >= 1`）且 `len > 1` | 取最后一个软切分点切分，剩余留在 buffer |
| flush | — | `len > 1` | LLM 结束后由 `_llm_task` 调用 `splitter.flush()` 冲刷残余 buffer |

### 阈值与首句加速

软切分阈值从早期的 4 字符降到 2 字符，这是首句加速的核心策略之一。LLM 输出通常是"嗯，好的，我来帮你看看"这样的口语化短句，4 字符阈值下要等到"嗯，好的，我"（4 个软切分字符后）才能切出第一句，2 字符阈值下到"嗯，好的"即可触发，TTS Worker 因此提前约 500ms 拿到首句音频。

`last_soft >= 1` 表示 buffer 中至少已经有一个软切分点可以回退切分；`len > 1` 用于过滤掉单个标点的噪声句。flush 在 LLM 结束后一次性把残余 buffer 推出去，避免最后一段卡在内部状态里。

### 切分示例

```
feed("嗯，")        → buffer="嗯，"，last_soft=1 但 len=2，触发软切分 → 输出 "嗯，"
feed("好的，我")    → buffer="好的，我"，last_soft=2(len>=2) 触发 → 输出 "好的，"，留 "我"
feed("帮你看。")    → buffer="我帮你看。"，遇到 "。" 触发硬切分 → 输出 "我帮你看。"
flush()             → buffer 已空，无输出
```

## 流式处理流程

`run` 方法是 Pipeline 的主入口，按顺序分为七个阶段。

### 阶段一 准备

进入 `run` 后首先做一次状态重置与上下文构建：

- 清理信号：`tts_playback_done` / `tts_drain_ack` / `tts_audio_ended` 三个 `asyncio.Event` 全部 `clear()`，避免上一轮的残留信号干扰
- 队列清空：`queues.clear_all()`，`splitter.reset()` 让 splitter 回到初始 buffer 状态
- 状态机推进：`set_tts_playing(True)`，`set_device_buffer(client_max_buffer)`，`fsm.set(LLM)`
- **system prompt 构建**：按优先级 `user_config.llm_system_prompt` → LLM 内置 prompt → 注入 **skill catalog**（带 `_skill_cache_key` 缓存）→ 注入 **LTM summary catalog**（`_ltm_catalog_ttl=60s` 缓存）→ 注入 **用户画像**（`UserProfileService.get_profile_summary`）→ 注入 **相关记忆**（按关键词匹配自动注入 `[Relevant Memories]`）→ 拼接 `_reply_style`
- 消息列表：`conversation_memory.build_messages(sp, iat_text)` 把 system prompt 与用户输入组装成 LLM 可消费的 messages
- `fsm.set(TTS)`，`self._play_audio_sent = False`（首帧音频才发 `play_audio`，见阶段六）

### 阶段二 并行启动

这是首句加速的关键阶段。四个 Worker 不串行 `await`，而是用 `create_task` 几乎同时调度：

```python
tts_session_fut = create_task(volc_tts.create_session(...))  # TTS 预建连
t_llm      = create_task(self._llm_task(llm, messages))      # LLM 立即开始
t_splitter = create_task(self._splitter_task())
t_sender   = create_task(self._sender_task())
tts_session = await tts_session_fut  # 等建连，此时 LLM 可能已在产 token
t_tts = create_task(self._tts_task(volc_tts, tts_session))
```

`volc_tts.create_session` 是一次 TCP/TLS 握手 + 鉴权，耗时不可忽略。把它和 LLM 的首 token 等待并行后，TTS 建连的延迟被 LLM 的思考延迟掩盖，整体减少 150-400ms 的串行等待。`t_tts` 必须等 `tts_session_fut` 完成后才能启动，因为它依赖建好的 session 对象。

### 阶段三 _llm_task

`async for token in llm.stream_chat(messages)` 驱动整个流水线的源头：

- 特殊 token 处理：`token == "__STOP_PIPELINE__"` → `raise StopPipeline`；`token.startswith("LLM error")` → `break` 中断
- 切分入列：`splitter.feed(token)` 返回句子列表，逐句 `queues.text.put((seq_id, sentence))`，`seq_id` 单调递增，供 Sender 识别新句与去重（判断 TEXT 帧是否已发）
- 收尾：流结束后 `splitter.flush()` 冲刷残余 buffer，`finally` 块中 `queues.text.put_nowait((-1, None))` 投放哨兵
- 记忆写入：`add_user_message(iat_text)` + `add_assistant_message(full_text)`，并异步触发 `ltm_service.auto_extract` 抽取长期记忆

`full_text` 是所有 token 拼接的完整回复文本。注意：触发 `StopPipeline` 中断时 `full_text` 无法取回（返回空串），仅在正常结束时包含完整文本。

### 阶段四 _splitter_task

`_splitter_task` 是最薄的一层，职责单一：

- 从 `text_queue` 取出 `(seq_id, sentence)`
- 过滤 `len(sentence) <= 1` 的空句（标点残留、空白）
- 有效句 `queues.audio.put((seq_id, sentence, sentence))`（三元组，第二、三项相同），哨兵以 `(-1, None, None)` 透传到 `audio_queue`

切分逻辑全部在 `SentenceSplitter` 内部完成，本 Worker 不参与切分，只做形态转换和过滤。

### 阶段五 _tts_task

`audio_queue` 到 `send_queue` 的转换，承担最多职责：

1. 文本预处理：`MARKDOWN_CLEANER` 移除 Markdown 标记，`LINE_CLEANER` 清理 Markdown 列表项前缀（`-` / `*` / 数字项），`[secret:\d+]` 正则移除敏感标记（换行合并由 `replace('\n\n','\n')` 完成）
2. 情绪检测：`_parse_emotion_tag` 解析 `[e:情绪]` 标签，未命中时 `_keyword_detect` 关键词兜底；情绪变化时 `send_json({"type":"emotion"})` 推给客户端
3. TTS 时长估算：`cn_chars * 230 + en_chars * 90` ms，下限 500ms，估算值立即随文本下发
4. 合成前先发文本/时长：`queues.send.put((seq_id, b"TEXT", payload, tts_duration_ms))` 与 `b"DURATION"` 帧，让 Sender 在 TTS 合成的同时把文字与预期时长推给设备，设备可提前排版
5. 合成循环：`async for audio_chunk in session.synthesize(sentence_text, cancel_event=...)`，每帧 `voice_generator.make_tts_frame(tts_session_id, chunk, "00")` 入 `send_queue`
6. **时长修正**：按字节数估算 `est_by_bytes = total_audio_bytes * 8 // 64`（假设 64kbps CBR），当 `est_by_bytes > 500` 且与初始估算偏差 >200ms 时覆盖原值
7. 累计时长：`self._total_duration_ms += tts_duration_ms`（未修正时累加的是估算值）

`cancel_event` 让 TTS 合成可被外部中断，配合 `StopPipeline` 实现"边取消边停止"。

### 阶段六 _sender_task

`send_queue` 到 WSChannel 的最后一棒，涉及帧协议与流量控制：

- **b"TEXT" 帧**：`send_json({"type":"instruct","command_id":"on_llm_cb","data": payload})`，`payload` 为含 `text` + `duration_ms` 的 JSON 串，且仅当文本长度 `> 10` 时发送
- **b"DURATION" 帧**：`send_json({"type":"instruct","command_id":"tts_duration","data": str(duration_ms)})`，且仅当 `duration_ms > 0` 时发送，让设备更新进度条/时长显示
- **首帧音频延迟发 play_audio**：`if not self._play_audio_sent` 时发 `play_audio`，然后等客户端上报 buffer（最多 150ms），再发 `tts_chunk_start`。这个延迟避免 LLM+TTS 耗时超过客户端 10s 看门狗：若早早发 `play_audio` 再等音频，设备会因长时间无音频数据触发看门狗复位
- 文本延迟发送：`text_send_delay=1`（默认），`pending_duration > 0` 时按 `text_delay_frames >= 1` 触发，否则 `>= 6`。这是为了对齐音频到达时间，避免文字先于音频一大段出现
- 音频帧：`channel.send_bytes(audio)` 直接发原始字节

流量控制见下一节专门展开。

### 阶段七 结束处理

`asyncio.wait(self._tasks, return_when=FIRST_EXCEPTION)` 等任意 task 完成（含异常）：

- pending 任务全部 `cancel`
- 检查 done 中是否含 `StopPipeline` 异常 → `stop_pipeline=True`
- `stop_pipeline=True`：跳过 `end_frame`（工具已接管音频通道，发 end_frame 会冲突）
- `_play_audio_sent=True`：发 `make_end_frame(tts_session_id)` + `tts_real_end`，通知设备本轮音频结束
- `_play_audio_sent=False`：跳过 end_frame（本轮未发任何音频帧，例如 LLM 直接返回 error）
- 返回 `PipelineResult(state, duration, full_text, stop_pipeline, total_duration_ms)`

`PipelineResult` 中的 `stop_pipeline` 字段是后续 Session 状态机决定下一轮行为的关键信号。

## 首句加速策略

用户体验的命脉在于听到第一个字的总延迟，Pipeline 用四层手段叠加优化：

1. **并行启动 TTS 建连与 LLM**：见阶段二，把建连延迟埋进 LLM 首 token 等待，节省 150-400ms
2. **软切分阈值降低**：从 4 字符降到 2 字符，让首句 TTS 提前约 500ms 启动
3. **首块 ASR 小缓冲**：ASR 侧用较小首块缓冲快速识别出第一段语音后立即触发 Pipeline，详细策略见 `session-engine.md`
4. _play_audio_sent 延迟机制：不在 Pipeline 启动时立即发 `play_audio`，而是延迟到首帧音频真正合成完成时再发，规避客户端 10s 看门狗

四层叠加后，从用户开口到听到第一个字的总延迟被压缩到秒级以内。

## 流量控制

Sender Worker 的主流控是**按播放速率（64kbps）节流**：用 `frame_audio_ms = len(audio) * 8.0 / 64` 累计已发送音频时长，当超前量超过 `TARGET_AUDIO_LEAD_MS = 500ms` 时 sleep 等待，让发送速率匹配设备播放速率。

`self._device_buffer`（初值 `client_max_buffer=10240`）仅作为**兜底保护**保留两档策略，防止设备缓冲耗尽：

| 剩余空间比例 | sleep 时长 | 含义 |
|---|---|---|
| `< 10%` | 0.5s | 几乎满，暂停发送 |
| `< 30%` | 0.2s | 较满，慢速发送 |

> 客户端 `client_available_audio` 上报当前已禁用，服务端保留该处理分支仅作兜底（`pipeline.py` 注释明确"不依赖客户端上报"）。

### 文本延迟发送

正常情况下，TTS Worker 会在合成前**预发 TEXT 帧**（`b"TEXT"`），Sender 收到后直接转发 `on_llm_cb`，文字无需延迟。`text_delay_frames` 仅在 TEXT 帧缺失时作为兜底路径：

- `text_send_delay=1` 默认开启
- `pending_duration > 0`（已有待播音频）时按 `text_delay_frames >= 1` 触发发文本，即每来一帧音频就发一段文字
- `pending_duration <= 0`（暂无音频）时按 `text_delay_frames >= 6` 触发，减缓文字推送

这样文字与音频在时间轴上保持紧耦合，用户看到字幕的同时听到语音。

## TTS 时长估算

客户端的进度条和预计时长显示需要在音频到达前就准备好，因此 Pipeline 在 TTS 阶段同步下发时长，并在合成完成后用实际字节数修正。

### 初始估算公式

```
est_duration_ms = max(500, cn_chars * 230 + en_chars * 90)
```

中文字符按 230ms/字、英文字符按 90ms/字估算，对应中文约 4.3 字/秒、英文约 11 字/秒的口语播报速率。下限 500ms 避免极短句估出负数或零值。

### 按字节数修正

TTS 合成完成后用实际音频字节数反推时长：

```
est_by_bytes = total_audio_bytes * 8 // 64
```

假设编码为 64kbps CBR（Constant Bitrate），字节数乘 8 转比特再除以 64000 bit/s 得到毫秒。当 `abs(est_by_bytes - 初始估算) > 200ms` 时用字节数估算覆盖原值。

修正机制的必要性：标点停顿、数字读法、多音字等都会让实际时长偏离字符估算，200ms 是可感知差异的阈值，超过则修正以让客户端进度条更准。

`self._total_duration_ms` 累加每句修正后的时长，作为 `PipelineResult.total_duration_ms` 返回，供上层做整轮统计。

## StopPipeline 机制

`StopPipeline` 是工具接管音频通道时的中断信号，区别于 LLM 正常结束。

### 触发链路

```
LLM 输出 "__STOP_PIPELINE__" token
        ↓
_llm_task raise StopPipeline
        ↓
run 捕获（FIRST_EXCEPTION）→ cancel 全部 tasks → stop_pipeline=True
        ↓
跳过 end_frame / tts_real_end
        ↓
PipelineResult.stop_pipeline=True 返回 Session
        ↓
Session._on_vad_end_auto / _on_vad_end_cycle 检测 → fsm.set(IDLE) → 不启动下一轮 ASR
ws_session_handler._on_tts_complete 检测 → _trigger_growth() + IDLE
```

### 异常处理

`_llm_task` 检测到 `token == "__STOP_PIPELINE__"` 时主动 `raise StopPipeline`，这不是错误而是受控中断。`run` 用 `FIRST_EXCEPTION` 等待策略捕获，区分两种 done 情况：

- 含 `StopPipeline` 异常 → `stop_pipeline=True`，跳过 end_frame
- 其他异常 → 走错误处理路径

`__STOP_PIPELINE__` 通常出现在工具调用场景：LLM 决定调用一个会自己产生音频的工具（如播放音乐、播报预设音频），此时 Pipeline 必须让出音频通道，否则会出现两路音频叠加。

### 与正常结束的区别

| 维度 | 正常结束 | StopPipeline |
|---|---|---|
| 触发 | LLM 流自然结束 | LLM 输出特殊 token |
| end_frame | 发（若 `_play_audio_sent`） | 跳过 |
| `tts_real_end` | 发 | 跳过 |
| 下一轮 ASR | 自动启动 | 不启动（工具接管） |
| `PipelineResult.stop_pipeline` | False | True |

跳过 `end_frame` 的原因是工具会自己发音频帧与结束帧，Pipeline 再发一次会让设备收到两个 end_frame 导致状态错乱。

## PipelineConfig 配置项

以下默认值定义了 Pipeline 的运行参数，调用方可按需覆盖：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `tts_session_id` | "0010" | TTS session 标识，用于帧头 |
| `text_send_delay` | 1 | 文本延迟发送档位（0=关闭，1=开启） |
| `client_max_buffer` | 10240 | 客户端音频缓冲区字节数，初始化 `device_buffer` |

> 注：`max_queue_size` / `llm_timeout` / `tts_timeout` / `enable_tts_session_reuse` 为 PipelineConfig 中保留但当前**未生效**的字段（队列大小硬编码于 `BackpressureQueues`，超时在网关内部硬编码，TTS session 每轮新建）。`client_max_buffer` 应与设备实际 `AUDIO_BUFFER_SIZE` 一致，否则流量控制会基于错误基准计算。
