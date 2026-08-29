# 架构细节：产品模型、对话旅程与时序

## 这个产品是什么

"小明同学"是一台 ESP32 桌面语音 AI 伙伴：用户对设备说话，设备经 WebSocket 把音频流发给本服务端，服务端完成 **ASR 识别 → LLM 对话（可调工具控制设备）→ TTS 合成**，再把 MP3 音频流推回设备播放。屏幕上有表情/字幕/卡片，配合手机 App（配网/绑定/配置）与微信（把设备当聊天对象）。服务端同时是插件宿主（市场安装的第三方代码跑在沙箱里）和设备管理后台。

理解三个核心抽象，一切代码都围绕它们：

- **设备（device）**：一台硬件，用三种标识（`device_id`=MAC、`device_key`=`bound_xxx` 随机密钥兼 WS 凭据、`mac_address`）——历史演进产物，查库用 device_key，设备间通信用 MAC，见 conventions 的键体系说明
- **会话（session）**：设备的一次 WS 连接 = 一个 Session（含 ASR 客户端、pipeline、记忆、状态机）。设备断电重连 = 新 session；用户解绑换绑 = 新 device_key = 干净的历史
- **对话轮（round）**：唤醒 → 聆听 → 判停 → pipeline → 播放 → 自动回到聆听，循环往复。打断（再唤醒/stop）发生在任何一点，服务端靠取消事件+轮次号保持两边状态一致

## 一通对话的完整旅程（改代码前先在脑中走一遍）

```
待机   设备跑唤醒词检测（WakeNet），服务端只有 keepalive 心跳
   │ 用户说"小明同学"
唤醒   设备发 {type:"start"} ──→ 服务端：取消旧 pipeline（若在播）
   │                          播唤醒提示音（缓存的 MP3，等设备回 client_out_audio_over）
   │                          下发 iat_start ──→ 设备开麦，音频帧开始上行
聆听   音频帧 → 有界队列 → 火山流式 ASR（结果实时回设备屏幕）
   │    判停（设备 iat_end / 服务端看门狗）→ drain_asr 优雅收尾
   │    on_vad_end：限流检查 → 后台启动 pipeline
Pipeline ASR 完成文本进 LLM（system prompt = 静态人设+工具规则+技能+记忆+画像）
   │    LLM 流式输出 → 分句 → TTS 合成（字幕/时长随音频下发）→ 1x 节流发送
   │    LLM 可调工具：查天气/播音乐/设闹钟/execute_lua 控制硬件……
播放   设备边收边播，播完回 client_out_audio_over → 自动进入下一轮聆听
   └──（任何时刻用户再次唤醒 → 打断，回到"唤醒"）
```

并行支线：微信消息（独立轮询，回复经 LLM 但工具受限）、闹钟到点播报、主动推送（LLM 自主决定何时找用户聊天）、成长系统（对话后异步提炼日记/画像/技能——这些产物会回注到下一轮 prompt）。

## 状态与数据归属（谁把什么存在哪）

| 状态 | 位置 | 生命周期 |
|------|------|---------|
| 设备配置（ASR/LLM/TTS key、插件白名单） | DB devices 表 | 持久；热重载推送到在线会话 |
| 用户账号/绑定关系 | DB users / devices.user_id | 持久 |
| 短期对话历史 | DB（按 device_key 键） | 持久，跨连接 |
| 长期记忆/画像/日记/自学习技能 | DB + 磁盘（data/） | 持久，**会回注 prompt** |
| 闹钟 | DB + 内存 dict（启动时从 DB 加载） | 持久，内存为运行时权威 |
| 插件 KV | data/plugins/kv/{mac}/（JSON 文件） | 持久，解绑时清除 |
| 微信 bot token | data/wechat_bot_data.json（加密） | 持久，扫码刷新 |
| 在线会话/音频队列/pipeline | 纯内存（registry） | 断连即逝 |
| 唤醒音缓存 | 进程内存（签名键控） | 运行时 |
| 安装的插件/沙箱数据 | data/plugins/installed/ 等 | 持久，卸载清理 |

## 4-Worker Pipeline（use_cases/pipeline.py）

```
LLM Worker ──text_queue──> Splitter Worker ──audio_queue──> TTS Worker ──send_queue──> Sender Worker
```

- `run(iat_text, system_prompt)`：先组装 prompt（静态前缀→动态块并行 gather），再并行启动 TTS 建连与 LLM
- **prompt 组装顺序是性能关键**：静态内容（回复风格/工具规则/Device ID）必须在前，动态（LTM/画像/技能/相关记忆）在后——影响 LLM 供应商前缀缓存命中
- prompt 素材缓存：模块级 `_prompt_caches`（按 device_id，TTL 60s）；设备唤醒时 `prewarm_prompt_caches()` 预热
- 分句：硬切分（。！？）与软切分（，；、：…——）；首句立即送 TTS 保证首响
- 发送节流：Sender Worker 按 1x 音频速率 + 300ms 超前量（`TARGET_AUDIO_LEAD_MS`）
- 会话 ID：pipeline 音频用 `SID_TTS="0010"`，连接提示音 `"0001"`，唤醒缓存 `"1000"/"1001"`；**interrupt 的 end_frame 必须同 SID_TTS**
- 错误流信号：`__STOP_PIPELINE__` 哨兵（常量 `STOP_PIPELINE_SENTINEL`）与 `LLM error` 前缀——pipeline.py 与 llm_gateways.py 字面量必须一致
- 双分支 LLM：直连（OpenAILLMGateway.stream_with_tools，含工具循环）与插件 LLM（PluginLLMGateway.stream_chat，无工具循环）——微信侧按 `hasattr(device_llm, "api_key")` 分流

## 会话与 WS 主循环（interfaces/ws_session_handler.py）

- `run()` 是设备 WS 消息主循环：start（唤醒）、iat_end（VAD 判停）、client_out_audio_over（播放完成）、音频帧转发
- **轮次/防串扰三件套**（改任何唤醒/打断逻辑前必须理解）：
  1. `_wake_audio_round` / `_wake_audio_expected_round`：唤醒音完成上报带轮次号，防上一轮迟到 over 串扰
  2. `_pending_out_audio_over`：pipeline 下发音频时置位，收到对应 over 复位；无进行中播放的 over 上报直接忽略（防误取消新 pipeline）
  3. `unregister(device_key, session=...)` 属主校验：设备重连后旧 handler 迟到的 cleanup 不杀新会话
- 唤醒流程 `_do_wake_start`：播唤醒音（等待上报，10s 兜底）→ iat_start → ASR。麦克风只在 iat_start 后上行（固件约定，无需担心唤醒期丢音频）
- ASR 判停三路：设备 iat_end 消息、看门狗（no_speech/silence 超时）、ASR 内部 VAD 回调
- `drain_asr`：投 None 哨兵后限时等待消费任务自然收尾（**不要**清空队列——会丢句尾音频）
- 上行音频队列有界（`AUDIO_QUEUE_MAX_SIZE=200`），满时丢最旧，绝不阻塞 WS 循环

## 微信链路（plugins/wechat_bot/handler.py + use_cases/wechat_bot.py）

- Bot 单例：`wechat_bot.get_or_create_bot()`；回调 `on_wechat_message` / `on_wechat_image` 在插件 handler
- 绑定：扫码自动绑（仅单设备）；多设备/手动 → Web 生成配对码（`routes/wechat.py`，10 分钟一次性）→ 微信发「绑定 XXXXXX」；「解绑」解除。**任何自动绑定到 registry[0] 的写法都是回归漏洞**
- 微信 LLM 用受限 PerUserToolManager：`disabled_tools=["execute_lua","send_device_command","send_device_command_ack","stop_lua"]`
- getupdates 是服务端长轮询（空轮询 ~18s 才返回）——微信回复慢是协议特性不是 bug
- 群聊已移除：带 group_id 的消息直接忽略

## 播放完成与关机

- `client_out_audio_over`：设备回的播放完成；`_on_tts_complete` 等待 `tts_playback_done`（动态超时 = base + 音频时长×乘数）
- 关机三阶段（web.py lifespan shutdown）：停微信 Bot → `task_manager.cancel_all()` → `registry.close_all()`（Session.close 里 aclose LLM/TTS 网关释放 SSL）→ 关网关池 → 关线程池。**顺序错会复现"离线通知打在已关闭 httpx 上"的报错刷屏**
