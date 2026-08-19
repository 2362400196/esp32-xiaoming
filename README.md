# ESP-AI 智能语音助手（ESP32 全栈方案）

基于 **ESP32** 的开源智能语音助手全栈项目，覆盖 **固件 → 服务端 → Web 控制台 → 手机 App → 文档** 完整链路。支持语音唤醒、实时对话（ASR → LLM → TTS）、技能/插件扩展、设备管理、OTA 升级等能力。

## 项目组成

| 目录 | 名称 | 说明 |
|---|---|---|
| `esp-ai-idf-client` | 固件客户端 | 基于 ESP-IDF 的 ESP32 设备端固件，跑在硬件上：BLE 配网、语音唤醒、音频采集/播放、屏幕显示、WebSocket 与服务端通信、OTA 升级 |
| `esp-ai-server` | 后端服务 | 基于 FastAPI + asyncio 的语音交互后端：流式 ASR/LLM/TTS 全链路、多设备鉴权、技能/插件/MCP 工具、设备管理 REST API、AI 成长记忆系统 |
| `esp-ai-web` | Web 控制台 | Vite + Vue3 的浏览器管理端：设备管理、技能配置、插件商店、MCP 服务器、表情管理、开发者工具等 |
| `esp-ai-app` | 手机 App | uni-app 跨端 App（iOS/Android）：BLE 蓝牙配网、设备控制、语音对话、技能与插件商店、微信绑定、OTA 升级 |
| `vuepress-starter` | 文档站 | VuePress + Plume 主题搭建的项目文档网站 |

## 支持板型

固件通过 `menuconfig` 选择板型（`main/boards/defs/`）：

| 板型 | 芯片 | 屏幕 |
|---|---|---|
| `breadboard` | ESP32-S3 面包板 | 无屏幕 |
| `breadboard_1.54_lcd` | ESP32-S3 面包板 | 1.54" ST7789 LCD (240×240) |
| `breadboard_1.54_lcd_official` | ESP32-S3 面包板 | 1.54" ST7789 LCD（适配官方服务） |
| `esp32c3_supermini` | ESP32-C3 SuperMini | 无屏幕 |

**音频方案**（与板型独立，`menuconfig` 选择）：

- **I2S 直连**：INMP441 数字麦克风 + MAX98357 数字功放（S3 双 I2S 总线）
- **ES8311**：ES8311 编解码器 + NS4150B 功放（全双工 I2S，C3 必须使用此方案）

## 支持功能

- BLE 蓝牙配网 / AP 热点配网
- 语音唤醒（WakeNet 9，多唤醒词，`你好小智`/`小明同学` 等）
- 全链路流式对话：语音识别 → 大模型 → 语音合成，低延迟实时交互
- TFT/LCD 屏幕显示、表情动画（GIF）
- 多设备管理、设备鉴权、请求限流
- 技能系统（Skill）、插件商店、MCP 外部工具
- AI 主动聊天、长期记忆、设备画像
- 微信绑定聊天、远程唤醒
- OTA 远程固件升级
- WebSocket（ws/wss）安全通信，TLS + CA 证书验证

## 快速开始

```
1. esp-ai-idf-client  编译固件烧录到 ESP32（详见其 README）
2. esp-ai-server      uv sync && cp .env.example .env && python src/main.py（端口 8088）
3. esp-ai-web         npm install && npm run dev（浏览器控制台）
4. esp-ai-app         HBuilderX 导入后运行到手机（App 内 BLE 配网）
5. vuepress-starter   npm install && npm run docs:dev（本地文档站）
```

各子项目均有独立 README 与详细文档，按需进入对应目录查看。

## 目录结构

```
esp32-xiaoming/
├── esp-ai-idf-client/   # ESP-IDF 固件客户端
├── esp-ai-server/       # FastAPI 语音后端
├── esp-ai-web/          # Web 管理控制台
├── esp-ai-app/          # 手机 App（uni-app）
└── vuepress-starter/    # 文档站
```

## 许可证

各子项目均为 MIT License。