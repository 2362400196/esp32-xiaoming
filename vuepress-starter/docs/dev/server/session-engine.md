# 会话引擎与状态机

## 概述

会话引擎是服务端管理一次"听—想—说"对话周期的核心子系统，负责协调 ASR（语音识别）、LLM（大语言模型）、TTS（语音合成）三个子流程的执行顺序与并发约束，并在 WebSocket 长连接上完成音频上行、识别文本、合成音频下行的双向数据交换。它把一段语音交互抽象为一个有限状态机驱动的工作循环，让多个异步任务在同一连接上有序推进，而不至于在用户打断、超时、断线重连等场景下产生竞态。

整个会话引擎由四个紧密协作的组件构成：`SessionFSM` 维护会话当前所处阶段并校验状态迁移合法性；`Session` 聚合 ASR、LLM、TTS、工具管理、对话记忆等运行时对象，承载 ASR 流式循环与 Watchdog 守护逻辑；`WSChannel` 用双优先级队列管理向客户端的下行帧发送；`ws_session_handler` 负责连接生命周期管理、消息分发与回调编排。本文按状态机、Session 生命周期、WSChannel、连接生命周期、中断机制、设计要点的顺序逐一展开。

## 会话状态机 SessionFSM

`SessionFSM` 是会话引擎的中枢，定义了单次连接在任意时刻只能处于一种会话阶段。它通过显式的状态枚举和合法转换矩阵约束 ASR、LLM、TTS 三个子流程的执行顺序，避免在并发场景下出现"识别进行中又触发合成"这类非法组合。

### 状态枚举

状态枚举定义于 `domain/entities.py`，具体取值如下表。

| 状态 | 含义 | 是否启用 |
| --- | --- | --- |
| `IDLE` | 空闲，等待用户唤醒或开始下一轮 | 是 |
| `ASR` | 正在进行语音识别 | 是 |
| `LLM` | 正在等待大模型生成回复 | 是 |
| `TTS` | 正在合成或播放语音 | 是 |
| `INTERRUPTED` | 中断态 | 否（保留） |
| `CLOSED` | 关闭态 | 否（保留） |

`INTERRUPTED` 与 `CLOSED` 当前未在转换矩阵中使用，属于预留扩展位。实际运行中真正承担流转职责的是前四种状态。

### 状态转换矩阵

合法的状态迁移由 `VALID_TRANSITIONS` 字典约束，转换关系如下。

```
              +-----------------+
              |      IDLE       |<-------------+
              +-----------------+              |
                |            |                 |
        wake    |            | speak           |
        (ASR)   |            | (TTS)           |
                v            v                 |
              +-----------------+              |
   reset ---->|       ASR       |              |
              +-----------------+              |
                |            ^                 |
        text    |            | reset           |
        (LLM)   |            | (IDLE)          |
                v            +-----------------+
              +-----------------+
              |       LLM       |
              +-----------------+
                |
        done    |
        (TTS)   |
                v
              +-----------------+
              |       TTS       |---- next cycle (ASR) ---+
              +-----------------+                        |
                |                                       |
        done    |                                       |
        (IDLE)  |                                       |
                +---------------------------------------+
```

简化的转换矩阵如下。

```
IDLE → ASR, TTS
ASR  → LLM, IDLE
LLM  → TTS
TTS  → ASR, IDLE
```

`IDLE` 既可以进入 `ASR`（用户唤醒或开始新一轮识别），也可以直接进入 `TTS`（服务端主动播放提示音或唤醒音频）。`ASR` 在识别完成进入 `LLM`，或在用户停止说话且无有效文本时回到 `IDLE`。`LLM` 是单向过渡态，生成完毕即进入 `TTS`。`TTS` 播放结束后既可以启动下一轮 `ASR`（连续对话），也可以回到 `IDLE`（等待唤醒）。

### 状态转换触发点

状态切换分散在多个组件的回调链中，由各阶段任务完成或外部事件触发。下表列出了所有触发点及其所属方法。

| 触发方法 | 转换 | 触发场景 |
| --- | --- | --- |
| `ws_session_handler._do_wake_start` | `IDLE → ASR` | 唤醒音频播放完毕，开始第一轮识别 |
| `ws_session_handler._start_next_asr` | `* → ASR` | 上一轮 TTS 播放完成，启动下一轮识别 |
| `pipeline.run` | `→ LLM`, `→ TTS` | ASR 产出 IAT 文本后驱动流水线推进 |
| `session.send_session_end` | `→ IDLE` | 一轮识别结束，回写空闲态 |
| `session.interrupt` | （不改 FSM）| 用户硬中断：取消流水线任务、清空队列、发结束帧；回到 IDLE 由 `send_session_end` 完成 |
| `ws_session_handler.cleanup` | `→ IDLE` | 连接关闭时清理会话状态 |

### 并发安全设计

`SessionFSM.__init__` 中初始化状态为 `IDLE`，并持有一个 `asyncio.Lock`。`async set(new_state)` 在加锁后查询 `VALID_TRANSITIONS`，若目标状态不在当前状态的合法后继集合内，则记录一条 `error` 日志并忽略本次切换，状态保持不变。`get()` 与 `is_busy()`（判断 `state != IDLE`）为**直接读取，无锁**（锁仅用于 `set()` 写操作）。

这种"加锁 + 合法转换表"的设计让上层调用者可以放心地在任意协程中发起状态切换请求，非法迁移会被静默丢弃并留痕，而不会破坏状态机的不变量。

## Session 生命周期

`Session` 是会话引擎中最重的类，它把一次连接所需的全部运行时对象聚合在一起，并实现 ASR 流式循环、Watchdog 守护、流水线调度、中断处理等核心逻辑。本节先介绍其内部结构与运行时状态，再展开关键方法与三重超时机制。

### SessionRuntime 内部类

`SessionRuntime` 是 `Session` 的内部类，专门承载 ASR 阶段的运行时状态。每轮识别开始前会调用 `reset()` 把这些字段清零，避免上一轮的残留数据污染当前轮。其字段如下表。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `asr_full_text` | str | ASR 累计完整文本 |
| `asr_processed` | bool | 本轮文本是否已交付流水线处理 |
| `asr_start_time` | float | 本轮识别开始时间戳 |
| `asr_last_audio_time` | float | 最近一次收到音频的时间戳 |
| `asr_last_result_time` | float | 最近一次收到 ASR 结果的时间戳 |
| `asr_stop_event` | asyncio.Event | ASR 停止信号 |
| `asr_task` | asyncio.Task | ASR 主循环任务句柄 |
| `audio_queue` | asyncio.Queue | 上行音频缓冲队列 |
| `pre_asr_ws` | WebSocket | 预连接的 ASR WebSocket |
| `_pre_asr_time` | float | 预连接建立时间戳 |

`pre_asr_ws` 配合 `_pre_asr_time` 实现 ASR 预连接：在用户开口前提前建好 WebSocket，真正开始识别时直接取走复用。若预连接已建立超过 25 秒仍未被使用，则视为过期并丢弃，重新走正常建连流程，避免使用可能已被服务端关闭的连接。

### Session 聚合的组件

`Session` 在构造时注入并持有下列组件，它们共同构成一次会话的完整执行环境。

| 组件 | 角色 |
| --- | --- |
| `channel` | `WSChannel` 实例，负责下行帧发送 |
| `fsm` | `SessionFSM` 实例，状态机 |
| `voice_generator` | 语音生成器（唤醒音频、提示音） |
| `llm_processor` | LLM 调用封装 |
| `tts_processor` | TTS 合成封装 |
| `asr_client` | ASR 客户端 |
| `tool_mgr` | `PerUserToolManager`，工具调用管理 |
| `conversation_memory` | 对话记忆 |
| `queues` | `BackpressureQueues`，流水线背压队列 |
| `splitter` | `SentenceSplitter`，句子切分器 |
| `audio_processor` | 音频处理器 |

此外，`Session` 还维护一组并发原语用于跨任务同步：`cancel_event`（中断信号）、`tts_playback_done`（TTS 播放完成事件）、`tts_drain_ack` 与 `tts_audio_ended`（音频排空与结束确认）、`_tts_playing_lock`（TTS 播放状态锁）、`_buffer_lock`（缓冲区锁）。这些原语把多个异步任务串联成一条可观测、可中断的执行链。

### 核心方法列表

下表汇总 `Session` 暴露的关键方法及其职责。

| 方法 | 职责 |
| --- | --- |
| `start_asr(on_text, on_vad_end)` | 取消旧 ASR 任务，`runtime.reset()`，清空旧 `audio_queue`，取走预连接 WS（>25s 过期则丢弃），创建 `_asr_streaming_loop` 任务 |
| `_asr_streaming_loop` | ASR 主循环，管理 `send_audio`/`recv_audio`/`stop_waiter` 三任务并发 |
| `_connect_asr_ws` | 创建 ASR WebSocket，传播 `X-Trace-Id` 头，`max_size=20MB`，`ping_interval=None` |
| `pre_connect_asr` / `cancel_pre_asr` | ASR 预连接建立与取消 |
| `stop_asr` | 置 `asr_stop_event`，取消 `asr_task` 与 watchdog，清空 `audio_queue` |
| `drain_asr` | 向 `audio_queue` 投 `None` 哨兵并调用 `stop_asr` |
| `can_queue_audio` / `queue_audio` | 判定可入队条件并投递音频，积压 ≥10 时记日志 |
| `run_pipeline(iat_text)` | 构造 `PipelineConfig` 与 `ConversationPipeline`，调用 `pipeline.run()` |
| `interrupt` | 硬中断：`set cancel_event`、取消 pipeline 全部 `_tasks`、`stop_asr`、`queues.clear_all()`、`splitter.reset()`、置 `tts_playing=False`、发 `end_frame` + `tts_real_end` |
| `send_session_end` | 标记 `asr_processed=True`、发 `iat_end` → `drain_asr` → `fsm.set(IDLE)` → 发 `session_end`（JSON + text） |
| `start_auto_conversation` | 启动自动循环：`fsm.set(ASR)` → `pre_connect_asr` → `start_asr` → 发 `iat_start` → `start_watchdog` |
| `_start_next_cycle` | 下一轮循环；`StopPipeline` 时不再启动下一轮 |
| `start_watchdog(on_vad_end)` | 守护任务，三重超时检测 |
| `close` | 关闭会话，清理全部资源并上报 metrics |

### ASR 流式循环详解

`_asr_streaming_loop` 是 ASR 阶段的主循环，它把上行音频发送、下行结果接收、停止信号监听三件事拆成三个并发任务，用 `asyncio.wait(..., FIRST_COMPLETED)` 驱动，任一任务完成即重新评估循环条件。三个任务的分工如下。

| 任务 | 职责 |
| --- | --- |
| `send_audio` | 从 `audio_queue` 取音频块写入 ASR WebSocket |
| `recv_audio` | 从 ASR WebSocket 读取识别结果，回调 `on_text` |
| `stop_waiter` | 等待 `asr_stop_event`，触发后终止循环 |

这种三任务并发的结构让音频发送与结果接收互不阻塞：即使 ASR 服务端迟迟不下发结果，`send_audio` 仍能把客户端持续上行的音频及时推走，避免本地缓冲膨胀；反之，结果接收也不会被音频发送节奏拖慢。

断线重连是流式循环的关键容错能力。当 `recv_audio` 检测到**特定超时错误**时（二进制协议下响应含 `b"Timeout"`，最多重连 2 次；JSON 协议下预连接 WS 首包异常时重连一次）会重建 WebSocket；普通的 `ConnectionClosed` 不重连、直接结束本轮识别。重建的是新连接，未发送的音频不会自动补发。整个重连过程对上层回调透明，`on_text` 仍按原始顺序收到累计文本。

首块小缓冲策略用于降低首轮识别延迟。识别启动后的第一个音频块使用 3200 字节（约 100ms）的小缓冲快速发给 ASR 服务端，让服务端尽早进入识别状态；后续音频块切换为 6400 字节（约 200ms）的常规缓冲，在延迟与吞吐之间取得平衡。这种"首块小、后续大"的安排能让 ASR 服务端更快返回首个结果，缩短用户从开口到看到文字的等待时间。

协议层面，`_connect_asr_ws` 创建 WebSocket 时设置 `max_size=20MB` 以容纳较大的音频帧，`ping_interval=None` 关闭框架级心跳（由业务层自行管理保活），并把当前请求的 `X-Trace-Id` 头传播到 ASR 服务端，便于跨服务链路追踪。连接同时支持二进制与 JSON 两种协议，根据 ASR 服务端协商结果自适应选择。

### Watchdog 三重超时机制

`start_watchdog(on_vad_end)` 启动一个守护任务，对单轮 ASR 施加三重超时约束，覆盖"没人说话""说完了""说太久了"三类异常场景。三个超时参数如下表。

| 超时参数 | 默认值 | 触发条件 | 动作 |
| --- | --- | --- | --- |
| `no_speech_timeout` | 5.0s | 自识别开始起无音频或无有效语音 | 调用 `send_session_end` 结束本轮 |
| `silence_timeout` | 2.0s | 已有音频但持续静音 | 触发 `on_vad_end` 回调 |
| `max_asr_duration` | 30s | 单轮识别总时长超限 | 强制 `stop_asr` |

`no_speech_timeout` 通过比较 `asr_start_time` 与 `asr_last_audio_time` 判断用户是否开口，防止识别任务在用户始终未说话时长时间空转。`silence_timeout` 通过比较 `asr_last_audio_time` 与当前时间判断尾部静音，相当于服务端 VAD，在用户说完一句话后及时收尾并把控制权交给流水线。`max_asr_duration` 是兜底保护，避免因 ASR 服务端异常或客户端持续推流导致单轮识别无限期占用资源。

三重超时共同把单轮 ASR 的生命周期限制在可控范围内，任一超时触发都会以确定的方式结束本轮识别，使状态机能够回到 `IDLE` 或推进到 `LLM`。

## WSChannel 双队列设计

`WSChannel` 负责向客户端发送下行帧，是会话引擎中流量最密集的环节。它采用高、低优先级双队列结构，让控制帧（JSON/文本）始终能优先于音频帧（bytes）发出，避免大量音频数据把控制信令阻塞在队列尾部。

### _hi 与 _lo 队列设计原理

`_hi` 与 `_lo` 是两个独立的 `asyncio.Queue`，分别承载不同优先级的帧。

| 队列 | maxsize | 承载内容 | 优先级 |
| --- | --- | --- | --- |
| `_hi` | 64 | 控制帧（json / text） | 高 |
| `_lo` | 500 | 音频帧（bytes） | 低 |

控制帧（如 `session_end`、`iat_end`、中断信号）体积小但对实时性敏感，若被排在大量音频帧之后会导致客户端状态更新滞后。音频帧体积大且允许一定延迟，适合放在低优先级队列中按节奏发送。两个队列的容量差异（64 vs 500）也反映了这一取向：控制帧不需要大缓冲，音频帧需要足够容量平滑突发流量。

### _send_loop 逻辑流程

`_send_loop` 是发送循环的核心，通过"先非阻塞取高优先级，再限时阻塞取低优先级"的轮询策略实现优先级保障。流程如下。

```
        +----------------------+
        |  enter _send_loop    |
        +----------------------+
                 |
                 v
        +----------------------+ <----+
        |  get_nowait(_hi)     |      |
        +----------------------+      |
                 |                    |
          got item? --no--------------+
                 |yes                  |
                 v                    |
        +----------------------+      |
        | wait_for(_lo.get(),  |      |
        |    timeout=0.1s)     |      |
        +----------------------+      |
                 |                    |
          got item? --no(timeout)---->+
                 |yes                  |
                 v                    |
        +----------------------+      |
        | gen != _send_gen ?   |      |
        |   yes -> break       |      |
        +----------------------+      |
                 |                    |
                 v                    |
        +----------------------+      |
        | dispatch by kind:    |      |
        |  json  -> send_json  |      |
        |  bytes -> send_bytes |      |
        |  text  -> send_text  |      |
        +----------------------+      |
                 |                    |
                 +--------------------+
                  (loop back to top)
```

步骤1先用 `get_nowait` 非阻塞地从 `_hi` 取控制帧，若取到则直接进入分发；步骤2在 `_hi` 为空时用 `asyncio.wait_for(self._lo.get(), timeout=0.1)` 限时阻塞等待音频帧，100ms 超时后回到步骤1重新检查 `_hi`，避免低优先级队列长时间占用循环而错过新到达的控制帧；步骤3做代际检查，若 `_send_gen` 已变化说明发送循环被要求重启，立即 `break` 退出；步骤4按帧 `kind` 分发到 `send_json`/`send_bytes`/`send_text`。

### 代际重启机制

`_send_gen` 是一个单调递增的代际计数器，用于实现发送循环的"软重启"。`interrupt_send_loop()` 的处理流程是：先把 `_send_gen` 自增，再 `cancel` 旧的 `_send_loop` 任务，接着调用 `clear_queue()` 清空 `_hi` 与 `_lo` 两个队列，最后若连接仍处于 `connected` 状态则启动一个新的 `_send_loop` 任务。

> 注：`interrupt_send_loop()` / `clear_queue()` 当前代码中保留但尚无调用点；`Session.interrupt()` 通过 `queues.clear_all()` 清空流水线队列。

旧任务在被 cancel 后会因代际检查失败或 CancelledError 而退出，新任务从干净的队列开始工作。这种设计避免了直接复用旧任务带来的状态残留问题，也让中断操作可以在任意时刻安全调用。

### 流量控制说明

双队列本身提供了一定的背压能力：当 `_hi`（maxsize=64）或 `_lo`（maxsize=500）满时，`put` 操作会阻塞，从而反压上游生产者。对于必须立即投递且不可阻塞的场景，`WSChannel` 提供 `send_json_nowait`，内部用 `put_nowait` 投递。当 `_hi` 已满时，对 `keepalive` 这类低重要性的帧采取"弹一个再塞"策略：先丢弃队首一个旧帧腾出位置，再 `put_nowait` 新帧，保证最新的保活帧能进入队列。

设备端缓冲也参与流量控制：`client_max_buffer`（默认 10240 字节）是 **pipeline Sender** 判定是否继续向设备推送音频的阈值（按播放速率节流 + device_buffer 兜底）；`Session.can_queue_audio` 则只判断 ASR 音频入队条件（基于 ASR 任务运行状态），两者相互独立。

### 入口方法表

下表列出 `WSChannel` 对外暴露的发送入口及其目标队列与阻塞特性。

| 方法 | 目标队列 | 阻塞特性 |
| --- | --- | --- |
| `send_json` | `_hi` | 阻塞 `put` |
| `send_text` | `_hi` | 阻塞 `put` |
| `send_bytes` | `_lo` | 阻塞 `put` |
| `send_json_nowait` | `_hi` | `put_nowait`，满时对 keepalive 弹一个再塞 |
| `bind(websocket)` | - | 绑定 ws，`connected=True`，`_send_gen+=1`，创建 `_send_loop` task |
| `clear_queue()` | - | 清空 `_hi` + `_lo` |
| `interrupt_send_loop()` | - | `gen+1`、cancel 旧 task、`clear_queue()`、重启新 `_send_loop` |

## 连接生命周期

`ws_session_handler` 是 WebSocket 连接的顶层管理者，负责从连接建立到关闭的全流程编排。它的生命周期分为构造、`initialize`、`run`（主循环）、`cleanup` 四个阶段，本节聚焦 `initialize` 阶段、消息分发、`start` 命令处理、`client_out_audio_over` 处理以及贯穿其中的回调链。

### initialize 阶段步骤

`initialize` 阶段在 WebSocket 握手后执行，完成会话所需的全部资源准备。步骤顺序如下表。

| 步骤 | 动作 |
| --- | --- |
| 1 | `set_trace_id` / `set_device_id`，建立链路追踪与设备标识 |
| 2 | metrics track，上报连接指标 |
| 3 | `websocket.accept()`，完成 WS 握手 |
| 4 | 创建 `WSChannel` + `SessionFSM` + `channel.bind`，搭建下行通道与状态机 |
| 5 | 创建 `PerUserToolManager` |
| 6 | MCP 初始化，注册工具协议 |
| 7 | 三网关创建：ASR / LLM / TTS+VoiceGenerator |
| 8 | `asyncio.gather` 并行执行 `_init_ltm_service` 与 `_precompute_skill_catalog` |
| 9 | 构造 `Session`，注入上述组件 |
| 10 | `registry.register`，登记当前连接 |
| 11 | `session.pre_connect_asr()`，提前建立 ASR 连接 |
| 12 | 唤醒音频缓存预热 |
| 13 | 启动 `keepalive_task` |
| 14 | 发 `play_audio_ws_conntceed` 并等待客户端回复 |

其中步骤8的并行初始化把长耗时记忆服务初始化与技能目录预计算合并执行，缩短 `initialize` 总耗时。步骤11在会话正式开始前就建立 ASR 连接，使用户真正开口时无需等待建连。步骤14通过等待客户端回复确认下行通道可用，再进入主循环。

### 消息分发逻辑

`run` 主循环接收客户端消息并按类型分发。文本消息按 `type` 字段路由，二进制消息走音频入队路径。文本消息的分发规则如下表。

| type | 处理 |
| --- | --- |
| `ping` / `pong` | 心跳往返 |
| `ota_progress` | OTA 升级进度上报 |
| `ota_update_error` | OTA 升级错误 |
| `firmware_version` | 固件版本上报 |
| `lua_result` | Lua 脚本执行结果 |
| `start` | 开始会话命令，进入 `start` 处理流程 |
| `iat_end` | 识别结束 |
| `play_audio_ws_conntceed` | 下行音频通道就绪回复 |
| `client_out_audio_over` | 客户端音频播放完成 |
| `client_out_audio_ing` | 客户端正在播放音频 |
| `client_available_audio` | 客户端可接收音频 |
| `session_stop` | 停止会话 |

二进制消息先经 `Session.can_queue_audio` 判定是否可入队，再调用 `queue_audio` 投递。判定仅基于 ASR 任务运行状态与处理标志（`asr_task` 存在且未完成、`audio_queue` 非空、`asr_processed` 为假），**不涉及设备缓冲与 FSM 状态**；FSM 为 IDLE 时的丢弃逻辑在 `ws_session_handler` 中另行处理。

### start 命令处理流程

`start` 是客户端发起会话的入口命令，处理流程包含去重、状态收尾、中断处理、预连接重建与唤醒分支。具体步骤为：先对 `start` 做去重，避免重复触发；若当前 `FSM == ASR`，先调用 `send_session_end` 把上一轮识别收尾；重置相关状态；若 `tts_playing` 为真则调用 `interrupt` 中断正在进行的 TTS；发 `session_start` 通知客户端会话开始；`cancel_pre_asr` 后 `create_task(pre_connect_asr)` 重建预连接；最后根据 `wakeup.enable_audio` 分流——若启用唤醒音频则走 `_do_wake_start()`，否则直接 `fsm.set(ASR)` + `_start_asr_session()` + 发 `iat_start`。

`wakeup.enable_audio` 决定了首句交互的体验：启用时先播放一段唤醒音频再开始识别，给用户明确的反馈；不启用时直接进入识别，延迟更低。

### client_out_audio_over 处理流程

`client_out_audio_over` 表示客户端已完成一段音频的播放，是推进会话状态的关键事件。处理流程为：先做唤醒音频完成检测，识别这是否是唤醒音频播放结束；若是 TTS 音频完成，则 `tts_playback_done.set()` 并 `set_tts_playing(False)`；若 pipeline 仍在运行则 `cancel`（避免播放已结束但流水线仍在合成）；最后预创建下一轮的 `audio_queue`，为下一轮 ASR 做准备。

该事件是连接 TTS 播放与下一轮 ASR 的纽带，`tts_playback_done` 事件被 `_on_tts_complete` 回调等待，从而触发 `_start_next_asr`。

### 关键回调链

会话引擎的执行流由一组回调串联，理解这条链路是排查时序问题的关键。完整的回调链如下。

`on_asr_text` 触发后进入 `on_vad_end`：发 `iat_end` → `drain_asr` → 限流检查 → 发 `on_iat_cb` → `pipeline_task = create_task(session.run_pipeline)` → `tts_done_waiter = create_task(_on_tts_complete)`。

`_on_tts_complete` 等待 `pipeline_task` 完成：若收到 `StopPipeline` 则置 `IDLE` 并触发 `_trigger_growth`；否则等待 `tts_playback_done` 事件，再调用 `_start_next_asr` 推进下一轮。

`_do_wake_start` 负责首轮启动：播放唤醒音频 → 等待 `_wake_audio_played` 事件 → `fsm.set(ASR)` → `_start_asr_session`。

`_start_asr_session` 启动识别：`create_task(start_asr)` + `create_task(start_watchdog)`，把 ASR 主循环与守护任务一并拉起。

整条回调链把"识别完成 → 流水线处理 → TTS 合成 → 客户端播放 → 下一轮识别"串成一个闭环，每个环节通过事件或任务句柄与下一环节衔接，中断信号可以在任意环节注入并沿链路传播。

## 中断机制

中断机制是会话引擎应对用户打断、超时、异常关闭的关键能力。`Session.interrupt()` 实现硬中断，与流水线内部的 `StopPipeline` 在作用范围与触发方式上有明确区分。

### interrupt 硬中断流程

`interrupt()` 是面向整个会话的强制中断，执行步骤为：`set cancel_event` 置位全局取消信号；取消 pipeline 的全部 `_tasks`，终止流水线所有 Worker；调用 `stop_asr` 停止 ASR 主循环与 watchdog；`queues.clear_all()` 清空流水线背压队列；`splitter.reset()` 重置句子切分器；置 `tts_playing=False`；向客户端发 `end_frame` + `tts_real_end`，通知客户端音频已结束。

硬中断的特点是"一刀切"：它不区分当前处于 ASR、LLM 还是 TTS 阶段，统一把所有运行中的任务终止、所有队列清空、所有状态置回初始。`cancel_event` 作为共享信号让正在 `await` 的协程及时感知中断并退出，避免任务在被 cancel 前继续推进产生新的副作用。

### 与 StopPipeline 的区别

`StopPipeline` 是流水线内部的软停止信号，作用范围仅限于 `ConversationPipeline` 的 Worker 集合，触发后流水线停止产出新的句子与音频，但已经下发到 `WSChannel` 的帧仍会被客户端播放完毕。它通常用于"当前这句话说完就停"的场景。

`interrupt()` 则是会话级硬中断，作用范围覆盖 ASR、pipeline、队列、splitter 与 TTS 播放状态，并主动向客户端发送结束帧。它用于"立刻停下来"的场景，如用户重新唤醒、发生错误需要清理。下表对比二者。

| 维度 | `StopPipeline` | `interrupt()` |
| --- | --- | --- |
| 作用范围 | pipeline 内部 Worker | 整个 Session（ASR + pipeline + 队列 + splitter） |
| 已下发音频 | 继续播放完毕 | 主动发 `end_frame` + `tts_real_end` 终止 |
| 触发方 | pipeline 内部条件 | `Session` 外部调用 |
| 状态机影响 | 不直接改 FSM | 配合 `send_session_end` 回到 `IDLE` |
| 后续动作 | `_start_next_cycle` 检测到后不再启动下一轮 | 由调用方决定下一步 |

`_start_next_cycle` 在检测到 `StopPipeline` 时不再启动下一轮循环，而 `interrupt()` 之后的走向由调用方决定（通常是回到 `IDLE` 等待新的唤醒）。这种分层中断让会话引擎既能优雅收尾，也能强制清理。

## 设计要点

会话引擎的多个设计选择共同支撑了低延迟、高鲁棒的语音交互体验。本节归纳四个核心设计要点。

### 双层队列设计

`WSChannel` 的 `_hi`/`_lo` 双队列与流水线的 `BackpressureQueues` 共同构成双层队列结构。`WSChannel` 层负责下行帧的优先级调度，让控制帧优先于音频帧；`BackpressureQueues` 层负责 LLM、Splitter、TTS、Sender 四个 Worker 之间的解耦与背压。两层队列各自独立工作，又在 `interrupt` 时通过 `queues.clear_all()` 与 `channel.clear_queue()` 被统一清理，使中断操作能在任意时刻把整条数据通路清空。

### 首句加速策略

首句延迟是语音交互体验的核心指标。会话引擎从三个角度压缩首句延迟：ASR 首块使用 3200 字节小缓冲快速启动识别；`pre_connect_asr` 在用户开口前提前建立 ASR 连接，省去识别开始时的建连耗时；流水线内部的首句加速策略让第一句 TTS 音频在 LLM 还在生成后续内容时就尽早下发。三者叠加使首轮"听—想—说"的端到端延迟显著降低。

### 预连接机制

ASR 预连接通过 `pre_connect_asr` 与 `cancel_pre_asr` 管理。在 `initialize` 阶段和每轮 `start` 命令处理时都会触发预连接，把建连开销前置到用户开口之前。`SessionRuntime` 持有 `pre_asr_ws` 与 `_pre_asr_time`，`start_asr` 取走预连接时检查是否超过 25 秒过期阈值，过期则丢弃并重建。这种机制把 WebSocket 建连这一不可控的耗时项从关键路径上移除，使识别启动只需承担音频发送与结果接收的耗时。

### 中断机制

`interrupt()` 的硬中断与 `StopPipeline` 的软停止构成两级中断体系，分别覆盖"立刻停"与"说完停"两种语义。硬中断通过 `cancel_event` 共享取消信号、取消全部任务、清空全部队列、重置全部状态，保证会话能在任意阶段被强制拉回 `IDLE`。代际重启机制让 `WSChannel` 的发送循环在中断后能干净地重启，避免旧帧残留。两级中断配合使会话引擎在用户频繁打断、超时频发的真实场景下仍能保持状态一致。
