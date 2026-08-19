---
home: true
config:
  - type: hero
    full: true
    hero:
      name: 小明同学
      text: 服务端 · 客户端 · App · 硬件
      tagline: 一站式 AI 语音解决方案
      actions:
        - theme: brand
          text: 快速开始
          link: /guide/server/get-started
          icon: material-symbols:rocket-launch
        - theme: alt
          text: 全功能总览
          link: /guide/features
          suffixIcon: material-symbols:grid-view
        - theme: alt
          text: 项目简介
          link: /guide/intro
          suffixIcon: material-symbols:info-outline
    effect: liquid-ether

  - type: features
    title: 四大组件
    description: 覆盖语音交互全链路
    features:
      - title: 服务端
        icon: 🖥️
        details: FastAPI + asyncio 语音后端，ASR → LLM → TTS 全链路流式处理
        link: /guide/server/get-started
        linkText: 了解详情 →
      - title: 客户端
        icon: 📟
        details: ESP32-S3/C3 ESP-IDF 固件，I2S 音频、TFT 彩屏、EEUI 动效引擎
        link: /guide/client/flash
        linkText: 了解详情 →
      - title: App
        icon: 📱
        details: uni-app 跨平台移动控制端，BLE 配网、设备管理、语音控制
      - title: 硬件
        icon: 🔧
        details: ESP32-S3 多板型支持，面包板/V2/V3/V4/圆形屏
        link: /guide/client/wiring
        linkText: 了解详情 →

  - type: features
    title: 核心特性
    description: 为什么选择 小明同学
    features:
      - title: 全链路流式
        icon: ⚡
        details: ASR → LLM → TTS 流式处理，端到端低延迟
      - title: 多厂商支持
        icon: 🏭
        details: 火山引擎/腾讯云 ASR，火山引擎 TTS，DeepSeek/GPT 等 LLM
      - title: 工具生态
        icon: 🔌
        details: 内置工具 + MCP 协议 + Lua 脚本，Function Calling 集成
      - title: 多设备管理
        icon: 👥
        details: 每设备独立 LLM Key、音色、系统提示词
      - title: 一键配网
        icon: 📶
        details: BLE + AP 双模式配网，App 端一键配置
      - title: 开源免费
        icon: 🎯
        details: MIT 协议，Python/C++ 全栈开源
---
