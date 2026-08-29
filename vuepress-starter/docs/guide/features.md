# 全功能总览

本文档介绍「小明同学」AI 语音解决方案当前支持的全部功能，按 服务端 / 客户端固件 / App / 硬件 四个维度整理。整体架构与指令系统设计可参考 [指令扩展指南](/dev/client/idf-commands) 的「架构设计」章节。

## 架构设计

系统采用 **分层 + 模块化** 架构：云端服务 → 服务端核心 → 设备固件 → 用户交互，各层职责明确、通过标准接口解耦；服务端能力以模块化扩展（新增工具/技能/厂商无需改核心）。

<style>
:root {
  --surface: #ffffff;
  --surface-muted: #f5f5f7;
  --border: #e5e5ea;
  --text-primary: #1d1d1f;
  --text-muted: #86868b;
  --brand: #7c3aed;
  --brand-light: #ede9fe;
  --accent: #f59e0b;
  --accent-light: #fef3c7;
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-mono: "SF Mono", Monaco, Consolas, monospace;
}
</style>

<svg viewBox="0 0 720 620" width="100%" height="auto" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="arr" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto">
      <path d="M1,1 L7,4 L1,7 Z" fill="var(--text-muted)"/>
    </marker>
    <marker id="arr-brand" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto">
      <path d="M1,1 L7,4 L1,7 Z" fill="var(--brand)"/>
    </marker>
  </defs>

  <!-- 背景 -->
  <rect width="720" height="620" fill="var(--surface)" rx="12"/>

  <!-- 区域：云端服务层 -->
  <text x="20" y="28" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="var(--text-muted)">云端服务层</text>
  <line x1="20" y1="34" x2="340" y2="34" stroke="var(--border)" stroke-width="1"/>

  <rect x="50" y="46" width="190" height="52" rx="6" fill="var(--accent-light)" stroke="var(--accent)" stroke-width="1"/>
  <text x="145" y="70" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="#92400e" text-anchor="middle">火山引擎</text>
  <text x="145" y="88" font-family="var(--font-sans)" font-size="10" fill="#92400e" text-anchor="middle">ASR · TTS 流式合成</text>

  <rect x="265" y="46" width="190" height="52" rx="6" fill="var(--accent-light)" stroke="var(--accent)" stroke-width="1"/>
  <text x="360" y="70" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="#92400e" text-anchor="middle">DeepSeek / GPT</text>
  <text x="360" y="88" font-family="var(--font-sans)" font-size="10" fill="#92400e" text-anchor="middle">LLM 对话 · 工具调用</text>

  <rect x="480" y="46" width="190" height="52" rx="6" fill="var(--accent-light)" stroke="var(--accent)" stroke-width="1"/>
  <text x="575" y="70" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="#92400e" text-anchor="middle">音乐服务</text>
  <text x="575" y="88" font-family="var(--font-sans)" font-size="10" fill="#92400e" text-anchor="middle">曲库搜索 · 歌词</text>

  <!-- 箭头：云端 -> 服务端 -->
  <line x1="145" y1="98" x2="145" y2="150" stroke="var(--text-muted)" stroke-width="1.5" marker-end="url(#arr)"/>
  <line x1="360" y1="98" x2="360" y2="150" stroke="var(--text-muted)" stroke-width="1.5" marker-end="url(#arr)"/>
  <line x1="575" y1="98" x2="575" y2="150" stroke="var(--text-muted)" stroke-width="1.5" marker-end="url(#arr)"/>

  <!-- 区域：服务端核心层 -->
  <text x="20" y="136" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="var(--text-muted)">服务端核心层</text>
  <line x1="20" y1="142" x2="340" y2="142" stroke="var(--border)" stroke-width="1"/>

  <rect x="40" y="152" width="640" height="216" rx="8" fill="var(--brand-light)" stroke="var(--brand)" stroke-width="1.5"/>
  <text x="360" y="178" font-family="var(--font-sans)" font-size="14" font-weight="600" fill="var(--brand)" text-anchor="middle">esp-ai-server · FastAPI + asyncio</text>

  <!-- 接入层 -->
  <rect x="56" y="192" width="292" height="72" rx="6" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="202" y="214" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="var(--brand)" text-anchor="middle">接入层</text>
  <text x="202" y="232" font-family="var(--font-sans)" font-size="11" fill="var(--text-muted)" text-anchor="middle">WebSocket 接入 · 鉴权 · 心跳 · 多设备</text>
  <text x="202" y="248" font-family="var(--font-sans)" font-size="11" fill="var(--text-muted)" text-anchor="middle">ws / wss · 绑定校验</text>

  <!-- 引擎层 -->
  <rect x="372" y="192" width="292" height="72" rx="6" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="518" y="214" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="var(--brand)" text-anchor="middle">引擎层</text>
  <text x="518" y="232" font-family="var(--font-sans)" font-size="11" fill="var(--text-muted)" text-anchor="middle">会话状态机 · Pipeline 流水线</text>
  <text x="518" y="248" font-family="var(--font-sans)" font-size="11" fill="var(--text-muted)" text-anchor="middle">流控 · 硬打断</text>

  <!-- AI 能力 -->
  <rect x="56" y="280" width="292" height="76" rx="6" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="202" y="302" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="var(--brand)" text-anchor="middle">AI 能力</text>
  <text x="202" y="320" font-family="var(--font-sans)" font-size="11" fill="var(--text-muted)" text-anchor="middle">ASR / LLM / TTS 网关 · 记忆系统</text>
  <text x="202" y="336" font-family="var(--font-sans)" font-size="11" fill="var(--text-muted)" text-anchor="middle">技能系统 · 工具 / MCP</text>

  <!-- 生态与运维 -->
  <rect x="372" y="280" width="292" height="76" rx="6" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="518" y="302" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="var(--brand)" text-anchor="middle">生态与运维</text>
  <text x="518" y="320" font-family="var(--font-sans)" font-size="11" fill="var(--text-muted)" text-anchor="middle">微信 · 音乐 · 闹钟 · AI 推送</text>
  <text x="518" y="336" font-family="var(--font-sans)" font-size="11" fill="var(--text-muted)" text-anchor="middle">OTA · 监控 · SQLite 存储</text>

  <!-- 区域：硬件设备层 / 用户交互层 -->
  <text x="20" y="404" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="var(--text-muted)">硬件设备层</text>
  <line x1="20" y1="410" x2="340" y2="410" stroke="var(--border)" stroke-width="1"/>

  <text x="380" y="404" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="var(--text-muted)">用户交互层</text>
  <line x1="380" y1="410" x2="700" y2="410" stroke="var(--border)" stroke-width="1"/>

  <rect x="40" y="420" width="300" height="66" rx="8" fill="var(--brand-light)" stroke="var(--brand)" stroke-width="1.5"/>
  <text x="190" y="446" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="var(--brand)" text-anchor="middle">ESP32-S3 · esp-ai-idf-client</text>
  <text x="190" y="466" font-family="var(--font-sans)" font-size="11" fill="var(--text-muted)" text-anchor="middle">麦克风 · 喇叭 · 彩屏 · 语音唤醒 · Lua · OTA</text>

  <rect x="380" y="420" width="155" height="66" rx="6" fill="var(--accent-light)" stroke="var(--accent)" stroke-width="1"/>
  <text x="458" y="446" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="#92400e" text-anchor="middle">手机 App</text>
  <text x="458" y="466" font-family="var(--font-sans)" font-size="10" fill="#92400e" text-anchor="middle">配网 · 管理 · 音色</text>

  <rect x="545" y="420" width="155" height="66" rx="6" fill="var(--accent-light)" stroke="var(--accent)" stroke-width="1"/>
  <text x="622" y="446" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="#92400e" text-anchor="middle">微信</text>
  <text x="622" y="466" font-family="var(--font-sans)" font-size="10" fill="#92400e" text-anchor="middle">扫码绑定 · 聊天控制</text>

  <!-- 箭头：设备/交互 -> 服务端 -->
  <line x1="190" y1="420" x2="190" y2="370" stroke="var(--brand)" stroke-width="1.5" marker-end="url(#arr-brand)"/>
  <text x="190" y="404" font-family="var(--font-mono)" font-size="10" fill="var(--text-muted)" text-anchor="middle">WebSocket</text>

  <line x1="458" y1="420" x2="458" y2="370" stroke="var(--text-muted)" stroke-width="1.5" marker-end="url(#arr)"/>
  <line x1="622" y1="420" x2="622" y2="370" stroke="var(--text-muted)" stroke-width="1.5" marker-end="url(#arr)"/>

  <text x="360" y="522" font-family="var(--font-sans)" font-size="12" fill="var(--text-muted)" text-anchor="middle">固件实现 WebSocket 协议与指令注册即可接入 · 服务端能力以模块化扩展 · App/微信仅消费服务端 API</text>
</svg>

### 语音交互全链路

唤醒 → 采集 → 上传 → 识别 → 理解 → 合成 → 播放，全流程流式处理，支持随时打断与连续对话。

<svg viewBox="0 0 720 200" width="100%" height="auto" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="arr2" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto">
      <path d="M1,1 L7,4 L1,7 Z" fill="var(--text-muted)"/>
    </marker>
  </defs>

  <rect width="720" height="200" fill="var(--surface)" rx="12"/>

  <text x="20" y="28" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="var(--text-muted)">语音交互全链路</text>
  <line x1="20" y1="34" x2="700" y2="34" stroke="var(--border)" stroke-width="1"/>

  <!-- 节点1：唤醒 -->
  <rect x="30" y="60" width="96" height="60" rx="8" fill="var(--brand-light)" stroke="var(--brand)" stroke-width="1.5"/>
  <text x="78" y="88" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="var(--brand)" text-anchor="middle">语音唤醒</text>
  <text x="78" y="106" font-family="var(--font-sans)" font-size="10" fill="var(--text-muted)" text-anchor="middle">WakeNet9</text>

  <line x1="126" y1="90" x2="146" y2="90" stroke="var(--text-muted)" stroke-width="1.5" marker-end="url(#arr2)"/>

  <!-- 节点2：上传 -->
  <rect x="148" y="60" width="96" height="60" rx="8" fill="var(--brand-light)" stroke="var(--brand)" stroke-width="1.5"/>
  <text x="196" y="88" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="var(--brand)" text-anchor="middle">音频上传</text>
  <text x="196" y="106" font-family="var(--font-sans)" font-size="10" fill="var(--text-muted)" text-anchor="middle">WebSocket</text>

  <line x1="244" y1="90" x2="264" y2="90" stroke="var(--text-muted)" stroke-width="1.5" marker-end="url(#arr2)"/>

  <!-- 节点3：ASR -->
  <rect x="266" y="60" width="96" height="60" rx="8" fill="var(--accent-light)" stroke="var(--accent)" stroke-width="1"/>
  <text x="314" y="88" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="#92400e" text-anchor="middle">ASR 识别</text>
  <text x="314" y="106" font-family="var(--font-sans)" font-size="10" fill="#92400e" text-anchor="middle">火山 / 腾讯等</text>

  <line x1="362" y1="90" x2="382" y2="90" stroke="var(--text-muted)" stroke-width="1.5" marker-end="url(#arr2)"/>

  <!-- 节点4：LLM -->
  <rect x="384" y="60" width="96" height="60" rx="8" fill="var(--accent-light)" stroke="var(--accent)" stroke-width="1"/>
  <text x="432" y="88" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="#92400e" text-anchor="middle">LLM 理解</text>
  <text x="432" y="106" font-family="var(--font-sans)" font-size="10" fill="#92400e" text-anchor="middle">DeepSeek</text>

  <line x1="480" y1="90" x2="500" y2="90" stroke="var(--text-muted)" stroke-width="1.5" marker-end="url(#arr2)"/>

  <!-- 节点5：TTS -->
  <rect x="502" y="60" width="96" height="60" rx="8" fill="var(--accent-light)" stroke="var(--accent)" stroke-width="1"/>
  <text x="550" y="88" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="#92400e" text-anchor="middle">TTS 合成</text>
  <text x="550" y="106" font-family="var(--font-sans)" font-size="10" fill="#92400e" text-anchor="middle">火山流式</text>

  <line x1="598" y1="90" x2="618" y2="90" stroke="var(--text-muted)" stroke-width="1.5" marker-end="url(#arr2)"/>

  <!-- 节点6：播放 -->
  <rect x="620" y="60" width="80" height="60" rx="8" fill="var(--brand-light)" stroke="var(--brand)" stroke-width="1.5"/>
  <text x="660" y="88" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="var(--brand)" text-anchor="middle">播放</text>
  <text x="660" y="106" font-family="var(--font-sans)" font-size="10" fill="var(--text-muted)" text-anchor="middle">I2S 喇叭</text>

  <text x="360" y="160" font-family="var(--font-sans)" font-size="12" fill="var(--text-muted)" text-anchor="middle">全程流式 · 随时打断 · 连续对话</text>
</svg>

> 各层职责明确、通过标准接口解耦：固件只需实现 WebSocket 协议与指令注册；服务端能力以模块化扩展（新增工具/技能/厂商无需改核心）；App 与微信仅消费服务端 API。

## 服务端功能（esp-ai-server）

服务端采用 **工厂模式 + 注册表** 设计：ASR/LLM/TTS 网关由工厂按配置创建；工具、技能、指令均通过注册机制扩展，无需修改核心流程。

### 语音交互链路

| 模块 | 功能 | 说明 |
|------|------|------|
| ASR 识别 | 流式语音识别 | 火山引擎 / 腾讯云 / 阿里云 / 讯飞，工厂模式切换 |
| LLM 大模型 | 对话理解 + 工具调用 | OpenAI 兼容网关，可配 DeepSeek/GPT 任意 base_url+model |
| TTS 合成 | 流式语音合成 | 火山引擎，逐句下发，多音色/语速/音量/音调调节 |
| 唤醒提示音 | 「我在呢」预合成 | TTS 合成 + 缓存，连接时预热，首唤醒零延迟；异常自动重试 |
| 连续对话 | 多轮自动聆听 | 对话结束自动进入下一轮 ASR，无需反复唤醒 |
| 随时打断 | 硬中断 | cancel_event 全链路取消，TTS 播放期间唤醒即打断 |

### 会话引擎与流水线

| 模块 | 功能 | 说明 |
|------|------|------|
| 会话状态机 | IDLE→ASR→LLM→TTS | 严格状态流转，防止指令乱序 |
| Pipeline | 4-Worker 流水线 | LLM → Splitter → TTS → Sender 并行，三级背压队列 |
| 流控机制 | 反压控制 | 客户端可用缓冲上报 + TCP 反压，防止音频帧丢失 |
| 并发控制 | 全局会话限制 | 默认 500，CPU 线程池 8 worker |

### 智能能力

| 模块 | 功能 | 说明 |
|------|------|------|
| 记忆系统 | 会话 + 长期记忆 | 会话级对话记忆 + 跨会话长期记忆（摘要标签检索，DB 持久化） |
| 技能系统 | SKILL.md 声明 | 每设备启用/停用技能，REST CRUD，示例：猜数字、成语故事 |
| 工具系统 | @tool 装饰器 | 内置 11+ 工具（时间/日期/音量/音乐/待机/灯…），支持自定义工具 |
| MCP 集成 | 外部工具协议 | 每设备独立 MCP Server 配置，接入外部工具生态 |
| Function Calling | LLM 自动调用 | 工具描述注入 LLM，自动决策并执行 |

### 设备接入与通信

| 模块 | 功能 | 说明 |
|------|------|------|
| WebSocket 接入 | `/connect_espai_node` | 二进制音频流 + JSON 指令，支持 ws/wss |
| 设备鉴权 | key + 绑定校验 | URL key 鉴权，设备绑定双重校验 |
| 心跳保活 | 应用层 keepalive | 断线快速感知与恢复 |
| 多设备管理 | MAC+key 索引 | 每设备独立 LLM Key、音色、系统提示词、工具/MCP 配置 |
| 远程唤醒/播报 | API 触发 | 服务端主动唤醒设备并语音播报 |

### 生态集成

| 模块 | 功能 | 说明 |
|------|------|------|
| 微信接入 | iLink Bot | 扫码登录、消息轮询、收发文本/图片 |
| 微信绑定 | 设备-微信绑定 | 扫码自动绑定；多设备用配对码。微信内直接聊天（设备控制类指令在微信通道禁用） |
| 音乐服务 | 外部音乐 API | 曲库搜索、流式音频、歌词元数据、随机播放/续播 |
| 闹钟/提醒 | DB 持久化 | once/daily/weekly/monthly 重复，到点播报语音或音乐 |
| AI 主动推送 | LLM 自主决定 | 8-23 点随机间隔（30-120 分钟），每日上限 |
| 表情包 | GIF 表情管理 | 13 个标准槽位，多包切换，App 上传 |

### 数据与运维

| 模块 | 功能 | 说明 |
|------|------|------|
| 数据库 | SQLite | device/emo/growth/memory/skill/user/wechat_binding 模型 |
| 安全 | JWT + Fernet | 字段加密 + 鉴权，DEPLOY_MODE=single/multi 双模式 |
| OTA | 固件生命周期 | 上传/下发/默认固件/批量推送/状态查询 |
| 监控 | Prometheus | `/metrics` 指标，业务请求追踪 |
| 健康检查 | /health/* | live/ready/stats 接口 |
| 成长系统 | 持续进化 | 日记、用户画像、情绪分析、自学习 |

## 客户端固件功能（esp-ai-idf-client）

固件指令系统采用 **注册表 + 自动发现** 架构（详见[指令扩展指南](/dev/client/idf-commands)）：`websocket.c` 收到指令后经 `commands_dispatch()` 分发给注册表，按 type + command_id 匹配 handler；`commands/*.c` 由 CMake GLOB 自动收集。

### 音频与语音

| 模块 | 功能 | 说明 |
|------|------|------|
| 音频采集 | I2S 麦克风 | INMP441，16kHz |
| 音频播放 | I2S 喇叭 + MP3 软解 | MAX98357，24kHz，helix 解码器 |
| 语音唤醒 | WakeNet9 | 「小明同学」唤醒词 + 按钮唤醒兜底 |
| 音乐播放 | 网络音频流 | 点歌搜索、随机播放、自动续播 |
| 音乐闪避 | Ducking | TTS 播放时音乐降至 15%，说完恢复 |
| 音量控制 | 0~100 级 | App / 语音 / 指令调节 |

### 配网与连接

| 模块 | 功能 | 说明 |
|------|------|------|
| BLE 配网 | NimBLE | Service=0xBAAD，Char=0xF00D，JSON 分块传输 |
| AP 配网 | 热点页面 | 密码 `esp-ai-setup`，网页配置，备选方案 |
| WiFi | 自动重连 | 多级自愈：重建 WiFi → 强制重连 → 整机重启 |
| WebSocket | ws/wss | 心跳保活，音频流 + 指令分发 |

### 屏幕与显示

| 模块 | 功能 | 说明 |
|------|------|------|
| 表情引擎 | LVGL 9 | 13 种 GIF 表情（快乐/聆听/说话/休息…），在线下载 |
| 多屏支持 | 驱动注册制 | SPI TFT / I2C OLED / UART 串口屏 |
| 字幕显示 | TTS 节拍同步 | 实时显示识别文本与回答，滚动播放 |
| 歌词显示 | lyric_line | 播放音乐时逐行歌词 |
| 屏幕控制 | 指令驱动 | 亮度、旋转（MADCTL 硬件级）、状态/表情 |

### 设备能力

| 模块 | 功能 | 说明 |
|------|------|------|
| Lua 脚本 | Lua 5.4 | `lvgl/gpio/led/json` 模块，远程下发执行 |
| OTA | 远程升级 | 服务端触发，自动检查更新 |
| 设备绑定 | 6 位绑定码 | 扫码绑定，微信连接 |
| 指令框架 | 29 条指令 | 8 个指令文件，详见[已有指令参考](/dev/client/idf-commands#已有指令参考) |

## App 功能（esp-ai-app）

uni-app 跨平台移动端，四个 Tab：首页 / 技能管理 / 配网 / 我的。

| 功能 | 说明 |
|------|------|
| BLE 配网 | 雷达扫描设备，自定义 WiFi/服务器/引脚配置 |
| 设备管理 | 设备列表、6 位绑定码绑定/解绑 |
| 音色管理 | TTS 模型 + 音色下拉搜索切换 |
| 表情包管理 | 多包切换、上传、新建、删除 |
| 技能管理 | 技能 CRUD、启停、MCP 服务/工具管理 |
| 微信绑定 | 扫码登录自动绑定（单设备）/ 配对码绑定，仅支持私聊 |
| OTA 升级 | 一键触发固件升级 |
| ASR 配置 | ASR 引擎与 API Key 配置 |

## 硬件支持

| 板型 | 说明 | 屏幕 |
|------|------|------|
| `breadboard` | 基础面包板 | 无屏 |
| `breadboard_1.54_lcd` | 面包板 + 1.54 寸彩屏 | ST7789 240×240（SPI） |

> 主控 **ESP32-S3**（ESP-IDF v6.0），8MB PSRAM + 16MB Flash。板型由 Kconfig 选择，适配新板参考[适配自己的开发板](/dev/client/idf-board-adaptation)。

## 技术栈

| 端 | 技术栈 |
|----|--------|
| 服务端 | Python 3.10+ · FastAPI · asyncio · SQLite · WebSocket |
| 固件 | C/C++ · ESP-IDF v6.0 · LVGL 9 · WakeNet9 · Lua 5.4 |
| App | uni-app · Vue 3 · 跨平台（Android / iOS / 小程序） |
| 文档 | VuePress + theme-plume |

## 目录结构

```
esp-ai/
├── esp-ai-server/            # 服务端（FastAPI + asyncio）
│   └── src/
│       ├── interfaces/       # 接入层：websocket_handler / ws_session_handler / 网关
│       ├── use_cases/        # 业务层：session / pipeline / memory / skill / tools
│       ├── infrastructure/   # 基础设施：db / config / web / security
│       └── skills/           # 技能定义（SKILL.md）
├── esp-ai-idf-client/        # 客户端固件（ESP-IDF）
│   └── main/
│       ├── commands/         # 指令注册表 + 各指令模块（8 文件 / 29 指令）
│       ├── boards/           # 板级支持包（breadboard / breadboard_1.54_lcd）
│       ├── displays/         # 显示驱动（LCD / OLED / UART）
│       ├── lua/              # Lua 5.4 运行时 + 绑定
│       └── websocket.c       # 消息接收 + 分发（勿改）
├── esp-ai-app/               # 手机 App（uni-app）
│   └── pages/                # ble（配网）/ asr（引擎配置）/ index（主界面）
└── vuepress-starter/         # 本文档站
```

## 开源协议

MIT License —— Python / C++ / Vue 全栈开源，本地化部署，数据自主可控。
