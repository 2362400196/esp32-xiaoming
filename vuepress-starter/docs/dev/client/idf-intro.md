## 功能特性

- **语音交互** — I2S 双路音频（INMP441 麦克风 + MAX98357A 喇叭），Helix MP3 软件解码，PCM 采样定点音量控制
- **WiFi 联网** — WebSocket 长连接，心跳保活，断线自动重连
- **屏幕显示** — 1.54 寸 TFT (ST7789 240x240)，LVGL 9.2 + EEUI GIF 表情引擎，支持 15 种表情/状态动画
- **指令系统** — 模块化指令注册，`commands/` 目录自由扩展，核心代码零侵入
- **硬件 IO** — 完整移植 pinMode / digitalWrite / analogWrite / ledcWrite 硬件控制
- **网络音乐** — HTTP 流式 MP3 播放，复用现有解码管道，支持歌词同步显示
- **配网方式** — menuconfig 可选 BLE 蓝牙配网（NimBLE 协议栈，App 端一键配网）或 AP 热点配网
- **OTA 升级** — 空中固件升级，远程更新无需接线
- **板级包架构** — 统一的板型接口，切换硬件只需修改配置文件

## 架构图

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
  --green: #10b981;
  --green-light: #d1fae5;
  --blue: #3b82f6;
  --blue-light: #dbeafe;
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-mono: "SF Mono", Monaco, Consolas, monospace;
}
</style>

<svg viewBox="0 0 720 520" width="100%" height="auto" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="arr" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto">
      <path d="M1,1 L7,4 L1,7 Z" fill="var(--text-muted)"/>
    </marker>
    <marker id="arr-brand" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto">
      <path d="M1,1 L7,4 L1,7 Z" fill="var(--brand)"/>
    </marker>
    <marker id="arr-green" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto">
      <path d="M1,1 L7,4 L1,7 Z" fill="var(--green)"/>
    </marker>
  </defs>

  <!-- 图例 -->
  <rect x="20" y="12" width="14" height="14" rx="3" fill="var(--brand-light)" stroke="var(--brand)" stroke-width="1.2"/>
  <text x="40" y="23" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11">核心框架</text>

  <rect x="160" y="12" width="14" height="14" rx="3" fill="var(--accent-light)" stroke="var(--accent)" stroke-width="1.2"/>
  <text x="180" y="23" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11">硬件层</text>

  <rect x="290" y="12" width="14" height="14" rx="3" fill="var(--green-light)" stroke="var(--green)" stroke-width="1.2"/>
  <text x="310" y="23" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11">指令扩展（自由添加）</text>

  <rect x="490" y="12" width="14" height="14" rx="3" fill="var(--blue-light)" stroke="var(--blue)" stroke-width="1.2"/>
  <text x="510" y="23" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11">显示/音频</text>

  <line x1="20" y1="38" x2="700" y2="38" stroke="var(--border)" stroke-width="1"/>

  <!-- 第一行：入口 + 通信 -->
  <rect x="40" y="55" width="200" height="40" rx="8" fill="var(--brand-light)" stroke="var(--brand)" stroke-width="1.5"/>
  <text x="140" y="75" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="13" font-weight="600" text-anchor="middle" dominant-baseline="middle">main.c（app_main 入口）</text>

  <path d="M240,75 H280" fill="none" stroke="var(--text-muted)" stroke-width="1.5" marker-end="url(#arr)"/>

  <rect x="280" y="55" width="200" height="40" rx="8" fill="var(--brand-light)" stroke="var(--brand)" stroke-width="1.5"/>
  <text x="380" y="75" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="13" font-weight="600" text-anchor="middle" dominant-baseline="middle">wifi.c / websocket.c</text>
  <text x="380" y="90" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="10" text-anchor="middle">WiFi 联网 + WebSocket 通信</text>

  <path d="M480,75 H520" fill="none" stroke="var(--text-muted)" stroke-width="1.5" marker-end="url(#arr)"/>

  <rect x="520" y="55" width="160" height="40" rx="8" fill="var(--brand-light)" stroke="var(--brand)" stroke-width="1.5"/>
  <text x="600" y="75" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="13" font-weight="600" text-anchor="middle" dominant-baseline="middle">provisioning.c</text>
  <text x="600" y="90" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="10" text-anchor="middle">BLE / AP 配网</text>

  <!-- 分叉箭头 -->
  <path d="M380,95 V115" fill="none" stroke="var(--text-muted)" stroke-width="1.5" marker-end="url(#arr)"/>

  <!-- 第二行：三层分发 -->
  <rect x="200" y="115" width="360" height="40" rx="8" fill="var(--brand-light)" stroke="var(--brand)" stroke-width="1.5" stroke-dasharray="4 2"/>
  <text x="380" y="130" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="13" font-weight="500" text-anchor="middle" dominant-baseline="middle">三层消息分发（op_code → type → command_id）</text>
  <text x="380" y="148" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="10" text-anchor="middle">文本/二进制 → instruct/hardware-fns/emotion/play_audio → 指令注册表</text>

  <!-- 三层分发向下分支 -->
  <path d="M240,155 V185" fill="none" stroke="var(--green)" stroke-width="2" marker-end="url(#arr-green)"/>
  <path d="M380,155 V185" fill="none" stroke="var(--accent)" stroke-width="2" marker-end="url(#arr-brand)"/>
  <path d="M520,155 V185" fill="none" stroke="var(--blue)" stroke-width="2" marker-end="url(#arr-brand)"/>

  <!-- 第三行：左侧 - 指令系统 -->
  <rect x="60" y="185" width="320" height="160" rx="8" fill="var(--green-light)" stroke="var(--green)" stroke-width="1.5"/>
  <text x="220" y="205" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="13" font-weight="600" text-anchor="middle">指令系统 commands/</text>

  <rect x="75" y="215" width="135" height="36" rx="6" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="142" y="232" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11" font-weight="500" text-anchor="middle" dominant-baseline="middle">volume_commands.c</text>
  <text x="142" y="246" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="9" text-anchor="middle">set_volume / add_volume</text>

  <rect x="230" y="215" width="135" height="36" rx="6" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="297" y="232" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11" font-weight="500" text-anchor="middle" dominant-baseline="middle">audio_commands.c</text>
  <text x="297" y="246" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="9" text-anchor="middle">play_music</text>

  <rect x="75" y="258" width="135" height="36" rx="6" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="142" y="275" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11" font-weight="500" text-anchor="middle" dominant-baseline="middle">callback_commands.c</text>
  <text x="142" y="289" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="9" text-anchor="middle">on_iat_cb / on_llm_cb</text>

  <rect x="230" y="258" width="135" height="36" rx="6" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="297" y="275" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11" font-weight="500" text-anchor="middle" dominant-baseline="middle">lyric_commands.c</text>
  <text x="297" y="289" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="9" text-anchor="middle">music_meta / lyric_line</text>

  <rect x="75" y="300" width="290" height="34" rx="6" fill="var(--surface)" stroke="var(--green)" stroke-width="1.2" stroke-dasharray="4 2"/>
  <text x="220" y="320" fill="var(--green)" font-family="var(--font-sans)" font-size="11" font-weight="500" text-anchor="middle" dominant-baseline="middle">✦ 新增：your_command.c</text>

  <!-- 第三行：中间 - 音频 -->
  <rect x="400" y="185" width="280" height="160" rx="8" fill="var(--blue-light)" stroke="var(--blue)" stroke-width="1.5"/>
  <text x="540" y="205" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="13" font-weight="600" text-anchor="middle">音频 & 显示</text>

  <rect x="412" y="215" width="256" height="36" rx="6" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="540" y="232" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11" font-weight="500" text-anchor="middle" dominant-baseline="middle">audio.c — I2S + MP3 解码 + 音量</text>
  <text x="540" y="246" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="9" text-anchor="middle">Helix MP3 软件解码</text>

  <rect x="412" y="258" width="256" height="36" rx="6" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="540" y="275" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11" font-weight="500" text-anchor="middle" dominant-baseline="middle">network_audio.c — HTTP 流式音乐</text>
  <text x="540" y="289" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="9" text-anchor="middle">歌词同步 + 进度条</text>

  <rect x="412" y="300" width="256" height="36" rx="6" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="540" y="317" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11" font-weight="500" text-anchor="middle" dominant-baseline="middle">eeui_port.cpp — LVGL + GIF 表情引擎</text>
  <text x="540" y="330" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="9" text-anchor="middle">15 种表情/状态动画 / 电量 / 音量 / 信号</text>

  <!-- 第四行：硬件层 -->
  <path d="M160,185 V370" fill="none" stroke="var(--accent)" stroke-width="2" marker-end="url(#arr-brand)"/>
  <path d="M600,185 V370" fill="none" stroke="var(--accent)" stroke-width="2" marker-end="url(#arr-brand)"/>

  <rect x="120" y="370" width="180" height="44" rx="8" fill="var(--accent-light)" stroke="var(--accent)" stroke-width="1.5"/>
  <text x="210" y="388" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="12" font-weight="500" text-anchor="middle" dominant-baseline="middle">hardware_io.c / wakeup.c</text>
  <text x="210" y="404" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="10" text-anchor="middle">GPIO / LED / 语音唤醒</text>

  <rect x="460" y="370" width="200" height="44" rx="8" fill="var(--accent-light)" stroke="var(--accent)" stroke-width="1.5"/>
  <text x="560" y="388" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="12" font-weight="500" text-anchor="middle" dominant-baseline="middle">boards/（板级包）</text>
  <text x="560" y="404" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="10" text-anchor="middle">board_interface.h / defs/ + gen_boards.py</text>

  <!-- OTA -->
  <rect x="40" y="440" width="200" height="40" rx="8" fill="var(--brand-light)" stroke="var(--brand)" stroke-width="1.5"/>
  <text x="140" y="460" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="13" font-weight="600" text-anchor="middle" dominant-baseline="middle">ota_update.c</text>
  <text x="140" y="475" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="10" text-anchor="middle">空中固件升级</text>

  <rect x="480" y="440" width="200" height="40" rx="8" fill="var(--brand-light)" stroke="var(--brand)" stroke-width="1.5"/>
  <text x="580" y="460" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="13" font-weight="600" text-anchor="middle" dominant-baseline="middle">displays/</text>
  <text x="580" y="475" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="10" text-anchor="middle">display.c / display_uart.c</text>
</svg>

## 项目目录结构

```
main/
├── main.c                       # 入口：app_main() 初始化编排
├── config.h                     # 全局接口声明
│
├── 通信层
│   ├── wifi.c                   # WiFi 连接管理（自动重连）
│   ├── websocket.c              # WebSocket 客户端 + 消息分发
│   └── provisioning.c           # 配网（menuconfig 可选 BLE / AP）
│
├── 音频
│   ├── audio.c                  # I2S 双路 + 扬声器播放管道 + MP3 解码 + 音量控制
│   ├── network_audio.c          # HTTP 流式网络音乐播放
│   ├── helix_mp3/               # Helix MP3 软件解码库
│   └── wakeup.c                 # 语音唤醒
│
├── 显示
│   ├── displays/
│   │   ├── display.c            # 显示模块 C 包装层
│   │   ├── display_lcd.cpp      # LCD 显示驱动
│   │   └── display_uart.c       # UART 串口屏驱动
│   ├── eeui_port.cpp            # EEUI 表情显示核心（LVGL + GIF）
│   ├── eeui_port.h              # EEUI C 接口声明
│   ├── gif_downloader.cpp       # 表情 GIF 下载器
│   ├── emos/                    # 表情 GIF C 数组
│   └── fonts/                   # 中文字体（font_puhui_16_4）
│
├── 指令系统 ★
│   └── commands/
│       ├── command_registry.h/c     # 注册系统核心（勿改）
│       ├── volume_commands.c        # 音量指令
│       ├── audio_commands.c         # 音乐播放
│       ├── display_commands.c       # 屏幕亮度
│       ├── callback_commands.c      # 服务端回调
│       ├── lyric_commands.c         # 歌词同步
│       ├── config_commands.c        # 远程配置更新
│       ├── bind_commands.c          # 设备绑定 / 微信
│       ├── lua_commands.c           # Lua 脚本执行
│       └── README.md                # 扩展指南详见指令扩展
│
├── 硬件抽象
│   ├── hardware_io.c           # GPIO/LED/PWM 控制
│   ├── boards/
│   │   ├── board_interface.h   # 板型接口定义
│   │   ├── board.c             # 板型核心逻辑
│   │   ├── board_select.h      # 编译时板型选择（自动生成）
│   │   ├── Kconfig.gen         # menuconfig 板型菜单（自动生成）
│   │   ├── tools/gen_boards.py # 板型自动生成脚本
│   │   └── defs/               # ★ 板型定义（一个文件一个板型）
│   │       ├── board_templates.h
│   │       ├── esp32s3_breadboard.h
│   │       └── esp32s3_breadboard_1.54_lcd.h
│
├── 工具模块
│   ├── ota_update.c            # OTA 空中升级
│
├── sdkconfig.defaults          # 默认编译配置（项目根）
│
└── CMakeLists.txt              # 项目构建配置
```

## 消息处理流程

IDF 客户端采用三层分发机制处理服务端消息：

```
WebSocket 消息
    │
    ├─ 第一层：op_code 分发
    │   ├─ 0x01 文本 → cJSON 解析
    │   └─ 0x02 二进制 → 音频解码（TTS）
    │
    ├─ 第二层：type 分发
    │   ├─ instruct       → 指令注册表（commands/）
    │   ├─ hardware-fns   → 硬件 IO 控制
    │   ├─ emotion        → 表情切换
    │   ├─ play_audio     → TTS 音频播放
    │   └─ session_*      → 会话状态管理
    │
    └─ 第三层：command_id 分发
        └─ commands_dispatch(type, cmd_id, json)
             → 匹配注册的 handler 执行
```

## 指令扩展

IDF 客户端的核心优势是**模块化指令系统**。你只需在 `commands/` 目录下创建 `.c` 文件，实现注册函数并显式注册指令处理函数，无需修改任何核心代码。

详细指南请参阅 [指令扩展指南](./idf-commands.md)。
