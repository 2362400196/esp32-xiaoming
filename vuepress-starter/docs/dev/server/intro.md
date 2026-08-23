# 简介

## 技术栈

| 层级 | 技术 |
|------|------|
| 框架 | FastAPI + Uvicorn |
| 语言 | Python ≥ 3.10 |
| 异步 | asyncio + WebSocket |
| 配置 | pydantic-settings + .env |
| AI 网关 | OpenAI SDK（LLM）、火山引擎/腾讯云/阿里云/讯飞 SDK |
| 工具扩展 | MCP 协议（Model Context Protocol）|
| 监控 | Prometheus 指标 + 结构化日志 |
| 构建 | UV 包管理器 |

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
  --red: #ef4444;
  --red-light: #fee2e2;
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-mono: "SF Mono", Monaco, Consolas, monospace;
}
</style>

<svg viewBox="0 0 760 620" width="100%" height="auto" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="arr-down" viewBox="0 0 8 8" refX="4" refY="7" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto">
      <path d="M1,1 L4,7 L7,1" fill="none" stroke="var(--text-muted)" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
    </marker>
    <marker id="arr-right" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto">
      <path d="M1,1 L7,4 L1,7" fill="none" stroke="var(--text-muted)" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
    </marker>
  </defs>

  <!-- 图例 -->
  <rect x="20" y="10" width="14" height="14" rx="3" fill="var(--brand-light)" stroke="var(--brand)" stroke-width="1.2"/>
  <text x="40" y="21" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11">入口 / 适配器</text>

  <rect x="190" y="10" width="14" height="14" rx="3" fill="var(--green-light)" stroke="var(--green)" stroke-width="1.2"/>
  <text x="210" y="21" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11">核心业务</text>

  <rect x="360" y="10" width="14" height="14" rx="3" fill="var(--accent-light)" stroke="var(--accent)" stroke-width="1.2"/>
  <text x="380" y="21" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11">框架 / 基础设施</text>

  <rect x="570" y="10" width="14" height="14" rx="3" fill="var(--blue-light)" stroke="var(--blue)" stroke-width="1.2"/>
  <text x="590" y="21" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11">外部服务</text>

  <line x1="20" y1="34" x2="740" y2="34" stroke="var(--border)" stroke-width="1"/>

  <!-- ═══ 第一层：设备 ═══ -->
  <rect x="40" y="50" width="680" height="48" rx="10" fill="var(--surface-muted)" stroke="var(--border)" stroke-width="1.5" stroke-dasharray="4 2"/>
  <text x="380" y="72" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="14" font-weight="600" text-anchor="middle">ESP32 设备（多台并发，每设备独立 Session）</text>
  <text x="380" y="90" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="11" text-anchor="middle">WebSocket 二进制音频帧 + JSON 信令   |   通过 MAC 地址标识设备</text>

  <path d="M380,98 V120" fill="none" stroke="var(--text-muted)" stroke-width="2" marker-end="url(#arr-down)"/>

  <!-- ═══ 第二层：FastAPI + WebSocket ═══ -->
  <rect x="40" y="122" width="680" height="44" rx="10" fill="var(--brand-light)" stroke="var(--brand)" stroke-width="1.5"/>
  <text x="380" y="142" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="14" font-weight="600" text-anchor="middle">infrastructure / web.py — FastAPI 应用 + WebSocket 连接管理</text>
  <text x="380" y="158" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="11" text-anchor="middle">路由注册 · JWT 用户认证 + 设备绑定码 · REST 管理 API</text>

  <!-- 从 FastAPI 分支到左边的接口层和右边的核心业务 -->
  <path d="M200,166 V200" fill="none" stroke="var(--blue)" stroke-width="2" marker-end="url(#arr-down)"/>
  <path d="M560,166 V200" fill="none" stroke="var(--green)" stroke-width="2" marker-end="url(#arr-down)"/>

  <!-- ═══ 第三行左：interfaces 外部服务适配 ═══ -->
  <rect x="20" y="202" width="340" height="170" rx="10" fill="var(--blue-light)" stroke="var(--blue)" stroke-width="1.5"/>
  <text x="190" y="222" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="14" font-weight="600" text-anchor="middle">interfaces / — 外部服务适配器</text>

  <rect x="35" y="235" width="150" height="38" rx="6" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="110" y="252" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="12" font-weight="500" text-anchor="middle">asr/ — 语音识别网关</text>
  <text x="110" y="267" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="10" text-anchor="middle">火山 / 腾讯 / 阿里 / 讯飞</text>

  <rect x="195" y="235" width="150" height="38" rx="6" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="270" y="252" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="12" font-weight="500" text-anchor="middle">llm_gateways.py</text>
  <text x="270" y="267" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="10" text-anchor="middle">OpenAI 兼容协议</text>

  <rect x="35" y="282" width="150" height="38" rx="6" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="110" y="299" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="12" font-weight="500" text-anchor="middle">tts_gateways.py</text>
  <text x="110" y="314" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="10" text-anchor="middle">火山引擎语音合成</text>

  <rect x="195" y="282" width="150" height="38" rx="6" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="270" y="299" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="12" font-weight="500" text-anchor="middle">websocket_handler.py</text>
  <text x="270" y="314" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="10" text-anchor="middle">WS 入口 + 鉴权 / 绑定</text>

  <rect x="35" y="325" width="310" height="36" rx="6" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="190" y="342" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="12" font-weight="500" text-anchor="middle">gateways.py — 旧版网关</text>
  <text x="190" y="356" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="10" text-anchor="middle">旧版 LLM/TTS 网关 + 向后兼容重导出</text>

  <!-- ═══ 第三行右：use_cases 核心业务 ═══ -->
  <rect x="380" y="202" width="360" height="280" rx="10" fill="var(--green-light)" stroke="var(--green)" stroke-width="1.5"/>
  <text x="560" y="222" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="14" font-weight="600" text-anchor="middle">use_cases / — 核心业务逻辑</text>

  <!-- Session 卡片 -->
  <rect x="395" y="235" width="165" height="48" rx="6" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="477" y="252" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="12" font-weight="500" text-anchor="middle">session.py — 会话核心</text>
  <text x="477" y="268" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="10" text-anchor="middle">Watchdog · 中断 · 生命周期</text>

  <rect x="570" y="235" width="155" height="48" rx="6" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="647" y="252" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="12" font-weight="500" text-anchor="middle">session_fsm.py</text>
  <text x="647" y="268" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="10" text-anchor="middle">IDLE→ASR→LLM→TTS 状态机</text>

  <!-- Pipeline -->
  <rect x="395" y="292" width="330" height="100" rx="6" fill="var(--surface)" stroke="var(--brand)" stroke-width="1.2" stroke-dasharray="4 2"/>
  <text x="560" y="310" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="13" font-weight="600" text-anchor="middle">pipeline.py — 4-Worker 流水线</text>

  <!-- 4 Workers 箭头流程 -->
  <rect x="405" y="322" width="68" height="28" rx="5" fill="var(--brand-light)" stroke="var(--brand)" stroke-width="1"/>
  <text x="439" y="340" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="10" font-weight="600" text-anchor="middle">LLM</text>
  <text x="439" y="348" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="8" text-anchor="middle">流式生成</text>

  <line x1="473" y1="336" x2="498" y2="336" fill="none" stroke="var(--text-muted)" stroke-width="1.5" marker-end="url(#arr-right)"/>

  <rect x="500" y="322" width="68" height="28" rx="5" fill="var(--accent-light)" stroke="var(--accent)" stroke-width="1"/>
  <text x="534" y="340" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="10" font-weight="600" text-anchor="middle">分句</text>
  <text x="534" y="348" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="8" text-anchor="middle">按标点断句</text>

  <line x1="568" y1="336" x2="593" y2="336" fill="none" stroke="var(--text-muted)" stroke-width="1.5" marker-end="url(#arr-right)"/>

  <rect x="595" y="322" width="60" height="28" rx="5" fill="var(--green-light)" stroke="var(--green)" stroke-width="1"/>
  <text x="625" y="340" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="10" font-weight="600" text-anchor="middle">TTS</text>
  <text x="625" y="348" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="8" text-anchor="middle">语音合成</text>

  <line x1="655" y1="336" x2="680" y2="336" fill="none" stroke="var(--text-muted)" stroke-width="1.5" marker-end="url(#arr-right)"/>

  <rect x="682" y="322" width="24" height="28" rx="5" fill="var(--brand-light)" stroke="var(--brand)" stroke-width="1"/>
  <text x="694" y="340" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="14" font-weight="600" text-anchor="middle">▶</text>

  <!-- 其他 use_cases -->
  <rect x="395" y="400" width="100" height="36" rx="5" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="445" y="417" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11" font-weight="500" text-anchor="middle">queues.py</text>
  <text x="445" y="430" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="9" text-anchor="middle">3 级有损降级</text>

  <rect x="505" y="400" width="100" height="36" rx="5" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="555" y="417" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11" font-weight="500" text-anchor="middle">memory.py</text>
  <text x="555" y="430" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="9" text-anchor="middle">短时 + 长期记忆</text>

  <rect x="615" y="400" width="110" height="36" rx="5" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="670" y="417" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11" font-weight="500" text-anchor="middle">tools_system.py</text>
  <text x="670" y="430" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="9" text-anchor="middle">工具框架 + MCP</text>

  <rect x="395" y="442" width="100" height="30" rx="5" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="445" y="460" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11" font-weight="500" text-anchor="middle">emotion.py</text>

  <rect x="505" y="442" width="100" height="30" rx="5" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="555" y="460" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11" font-weight="500" text-anchor="middle">skill_system.py</text>

  <rect x="615" y="442" width="110" height="30" rx="5" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="670" y="460" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11" font-weight="500" text-anchor="middle">growth/ 成长系统</text>

  <!-- 箭头：interfaces → use_cases（gateways 把 ASR/LLM/TTS 实例传给 session） -->
  <path d="M360,240 L380,240" fill="none" stroke="var(--text-muted)" stroke-width="1.5" marker-end="url(#arr-right)"/>
  <text x="370" y="232" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="9" text-anchor="middle">注入</text>

  <!-- ═══ 第三行中间下箭头：走到基础设施 ═══ -->
  <path d="M560,482 V510" fill="none" stroke="var(--accent)" stroke-width="2" marker-end="url(#arr-down)"/>
  <path d="M200,372 V510" fill="none" stroke="var(--accent)" stroke-width="2" marker-end="url(#arr-down)"/>

  <!-- ═══ 第四行：基础设施 ═══ -->
  <rect x="20" y="510" width="720" height="100" rx="10" fill="var(--accent-light)" stroke="var(--accent)" stroke-width="1.5"/>
  <text x="380" y="530" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="14" font-weight="600" text-anchor="middle">infrastructure / — 框架集成</text>

  <rect x="35" y="542" width="110" height="28" rx="5" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="90" y="560" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11" font-weight="500" text-anchor="middle">config.py</text>

  <rect x="155" y="542" width="110" height="28" rx="5" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="210" y="560" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11" font-weight="500" text-anchor="middle">logging.py</text>

  <rect x="275" y="542" width="110" height="28" rx="5" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="330" y="560" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11" font-weight="500" text-anchor="middle">monitoring.py</text>

  <rect x="395" y="542" width="110" height="28" rx="5" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="450" y="560" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11" font-weight="500" text-anchor="middle">security.py</text>

  <rect x="515" y="542" width="110" height="28" rx="5" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="570" y="560" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11" font-weight="500" text-anchor="middle">db/ 数据库层</text>

  <rect x="635" y="542" width="90" height="28" rx="5" fill="var(--surface)" stroke="var(--border)" stroke-width="1"/>
  <text x="680" y="560" fill="var(--text-primary)" font-family="var(--font-sans)" font-size="11" font-weight="500" text-anchor="middle">routes/</text>

  <text x="380" y="598" fill="var(--text-muted)" font-family="var(--font-sans)" font-size="11" text-anchor="middle">SQLite + SQLAlchemy · Prometheus 指标 · 结构化日志 · pydantic-settings 配置</text>
</svg>

## 项目架构

### 整体架构

```
ESP32 设备
  │ WebSocket (binary + JSON)
  ▼
WebSocket 处理器（收消息 + 分发）
  │
  ▼
Session 控制器（会话生命周期）
  │
  ▼
Session / 设备（per-device 硬隔离）
  ├── SessionFSM（状态机：IDLE → ASR → LLM → TTS）
  ├── 背压队列（3 级有损降级）
  ├── 4 Workers（协程解耦并行）
  │     LLM → 分句 → TTS → 发送
  ├── 对话记忆（消息 + Token 双限）
  └── 中断机制（cancel_event → 清空队列 → 重置）
```

### Clean Architecture 分层

```
┌─────────────────────────────────────┐
│           interfaces/                │  ← 外层：适配器
│   (ASR/LLM/TTS 网关、WebSocket 控制器)│
├─────────────────────────────────────┤
│         infrastructure/              │  ← 框架层
│   (FastAPI、配置、日志、监控)         │
├─────────────────────────────────────┤
│           use_cases/                 │  ← 核心业务
│   (Session、Pipeline、工具系统、队列) │
├─────────────────────────────────────┤
│            domain/                   │  ← 领域层（最内层）
│   (实体、值对象、异常、接口)          │
└─────────────────────────────────────┘
```

### 目录结构

```
src/
├── domain/               # 领域层（零外部依赖）
│   ├── entities.py       #   实体：Session, Device, Conversation
│   ├── exceptions.py     #   异常层级
│   ├── repositories.py   #   仓储接口
│   ├── services.py       #   领域服务
│   └── value_objects.py
│
├── use_cases/            # 核心业务逻辑
│   ├── session.py        #   会话核心 + Watchdog
│   ├── pipeline.py       #   4-Worker 流水线
│   ├── session_fsm.py    #   状态机
│   ├── tools_system.py   #   工具框架 + MCP + 断路器
│   ├── stop_pipeline.py  #   Pipeline 停止信号
│   ├── tool_cache.py     #   工具结果缓存
│   ├── builtin_tools.py  #   内置工具
│   ├── sdk/              #   插件 SDK 子模块
│   │   ├── utils.py      #     工具函数
│   │   ├── device.py     #     设备指令下发
│   │   ├── http.py       #     HTTP 请求
│   │   ├── music.py      #     音乐播放
│   │   ├── io.py         #     GPIO/PWM/ADC/舵机
│   │   ├── storage.py    #     文件存储
│   │   └── services.py   #     服务查询
│   ├── _plugin_helpers.py #   SDK 统一导出层（兼容旧导入）
│   ├── custom/           #   自定义工具（@tool 自动注册）
│   ├── skill_system.py   #   技能系统
│   ├── skill_tools.py    #   技能工具
│   ├── memory.py         #   短时/长期记忆
│   ├── queues.py         #   背压队列
│   ├── speaker.py        #   设备语音控制
│   ├── device_registry.py #  设备注册表
│   ├── device_config.py  #   设备配置加载
│   ├── auth_service.py   #   鉴权服务
│   ├── emotion.py        #   情感检测
│   ├── image_sender.py   #   图片发送
│   ├── growth/           #   AI 成长系统
│   │   ├── growth_system.py
│   │   ├── diary_service.py
│   │   ├── emotion_analyzer.py
│   │   ├── self_learning.py
│   │   └── user_profile.py
│   └── ...
│
├── interfaces/           # 外部服务适配
│   ├── asr/              #   ASR 网关
│   │   ├── base.py       #     抽象基类
│   │   ├── factory.py    #     工厂函数
│   │   ├── volcengine.py #     火山引擎（支持连接池）
│   │   ├── tencent.py    #     腾讯云
│   │   ├── aliyun.py     #     阿里云
│   │   └── xunfei.py     #     讯飞
│   ├── llm_gateways.py   #   LLM 网关（OpenAI 兼容）
│   ├── tts_gateways.py   #   TTS 网关（火山引擎）
│   ├── ws_session_handler.py  # WebSocket 会话处理器
│   ├── websocket_handler.py   # WebSocket 连接管理
│   └── gateways.py       #   网关工厂
│
├── infrastructure/       # 框架集成
│   ├── web.py            #   FastAPI 应用 + 路由注册
│   ├── config.py         #   配置管理（pydantic-settings）
│   ├── config_adapter.py #   配置适配器
│   ├── security.py       #   鉴权（WS/REST 严格分离）
│   ├── logging.py        #   结构化日志
│   ├── monitoring.py     #   Prometheus 监控指标
│   ├── concurrency.py    #   并发控制
│   ├── connection_pool.py #  连接池基类
│   ├── emo_pack.py       #   表情包管理
│   ├── device_api.py     #   设备配置 CRUD
│   ├── remote_config.py  #   远程配置
│   ├── db/               #   数据库层（SQLite + SQLAlchemy）
│   │   ├── engine.py     #     引擎创建
│   │   ├── session.py    #     会话工厂
│   │   ├── base.py       #     基类
│   │   ├── models/       #     ORM 模型
│   │   │   ├── user.py          #       users 表（用户）
│   │   │   ├── device.py #       devices 表
│   │   │   ├── memory.py #       记忆表
│   │   │   ├── emo.py    #       表情包表
│   │   │   ├── skill.py  #       技能表
│   │   │   ├── growth.py #       成长记录表
│   │   │   └── wechat_binding.py #  微信绑定表
│   │   ├── repositories/ #     仓储实现
│   │   │   ├── device_repository.py
│   │   │   ├── ltm_repository.py       # 长期记忆
│   │   │   ├── short_term_memory_repo.py
│   │   │   ├── emo_repository.py
│   │   │   ├── skill_repository.py
│   │   │   └── growth_repositories.py
│   │   ├── migrations/   #     数据迁移
│   │   └── compat/       #     同步会话兼容
│   └── routes/           #   REST 路由模块
│       ├── devices.py    #     设备管理 + 控制
│       ├── system.py     #     系统管理
│       ├── skills.py     #     技能管理
│       ├── mcp.py        #     MCP 配置
│       ├── emos.py       #     表情包管理
│       ├── growth.py     #     成长系统
│       ├── auth.py       #     用户认证
│       ├── wechat.py     #     微信集成
│       ├── plugins.py    #     插件管理
│       ├── plugin_frontend.py # 插件前端页面
│       ├── marketplace.py #    云市场
│       └── admin.py      #     管理员后台
│
├── skills/               # 技能定义（SKILL.md）
│   ├── guess_number/
│   ├── gushi/
│   └── ...
│
├── emos/                 # 表情包资源
│   └── packs/            #   表情包目录
│
├── firmware/             # OTA 固件文件
│
└── main.py               # 应用入口
```

## 核心概念

### Session（会话）

每个设备连接对应一个 `Session`，负责管理会话生命周期：

- **设备隔离**：每设备独立 Session，互不干扰
- **状态管理**：通过 `SessionFSM` 管理会话状态转换
- **背压控制**：3 级有损降级队列，防止内存溢出
- **中断机制**：`cancel_event` 信号 → 清空队列 → 重置状态

### SessionFSM（状态机）

会话状态机管理对话流程的状态转换：

```
IDLE → ASR → LLM → TTS → ASR（连续对话）
                                    ↓
                                  IDLE（会话结束）
```

| 状态 | 说明 |
|------|------|
| `IDLE` | 空闲，等待用户唤醒 |
| `ASR` | 语音识别中，接收设备音频流 |
| `LLM` | 大模型生成中，流式输出文本 |
| `TTS` | 语音合成中，流式输出音频 |

合法状态转换：`IDLE→ASR`、`IDLE→TTS`、`ASR→LLM`、`ASR→IDLE`、`LLM→TTS`、`TTS→ASR`、`TTS→IDLE`

### Pipeline（4-Worker 流水线）

对话处理采用 4-Worker 协程流水线，各阶段解耦并行：

```
LLM Worker  →  分句 Worker  →  TTS Worker  →  发送 Worker
(流式生成)     (按标点断句)     (语音合成)       (推送音频帧)
```

| Worker | 职责 | 队列 |
|--------|------|------|
| LLM | 流式调用 LLM API，输出文本块 | `llm_queue` |
| 分句 | 按标点/长度断句，输出完整句子 | `sentence_queue` |
| TTS | 调用 TTS API 合成音频 | `tts_queue` |
| 发送 | 通过 WebSocket 推送音频帧到设备 | — |

流水线优势：LLM 还在生成时，已完成的句子已经开始 TTS 合成和播放，实现端到端低延迟。

### 背压队列（3 级降级）

当设备处理速度跟不上服务端时，三类队列按各自策略背压（三级背压队列）：

1. **TextQueue（text）**：容量 10，`drop_oldest` —— 队列满时丢弃最旧文本帧
2. **AudioQueue（audio）**：容量 20，`block` —— 队列满时阻塞等待
3. **SendQueue（send）**：容量 256，`block` —— 队列满时阻塞等待

### 设备注册表（DeviceRegistry）

管理所有在线设备的 WebSocket 连接、会话对象、状态机等。设备连接时注册，断开时注销。通过设备 key（WebSocket `?key=` 参数）或 MAC 地址查找。

### 鉴权模型

采用 **JWT 用户认证 + 绑定码设备认证** 的双轨模型，用户侧与设备侧严格分离：

| 侧 | 认证方式 | 传输方式 |
|----|---------|---------|
| 用户 / 管理 REST API | JWT 用户认证 | Header `Authorization: Bearer <JWT>`（登录 `/api/v1/auth/login` 获取）|
| 设备 WebSocket 连接 | 绑定码设备认证 | URL 参数 `?key=xxx`（与数据库 `device_key` 比对）；未绑定设备自动进入绑定模式 |

用户通过邮箱/密码注册登录获取 JWT，JWT 仅用于管理 REST API；设备首次连接时不携带有效 key，服务端生成 6 位绑定码下发设备屏幕显示，用户在 App/Web 输入绑定码完成绑定，绑定后设备获得 `bound_xxx` 形式的 `device_key` 用于后续连接鉴权。设备密钥无法访问管理 API，JWT 不用于设备连接。多用户模式下每设备在数据库中拥有独立的 `device_key`。

## 数据流

### 完整对话流程

```
用户说话 → ASR 识别 → LLM 生成 → 分句 → TTS 合成 → 设备播放
          ↓           ↓          ↓        ↓           ↓
        流式文本    流式文本    完整句子   音频帧     扬声器
```

### 详细数据流

```
设备                      服务端
  │                         │
  │── start ──────────────▶│  唤醒
  │                         │── 播放唤醒音频
  │◀── session_start ──────│
  │                         │
  │── 二进制音频 ─────────▶│  ASR 阶段
  │── 二进制音频 ─────────▶│  （流式识别）
  │── iat_end ────────────▶│  VAD 静默检测
  │◀── on_iat_cb ──────────│  返回识别文本
  │                         │
  │                         │  LLM 阶段（Pipeline 启动）
  │                         │── LLM Worker: 流式生成
  │◀── on_llm_cb ──────────│  （逐块推送文本）
  │                         │── 分句 Worker: 按标点断句
  │                         │── TTS Worker: 语音合成
  │◀── play_audio ─────────│  TTS 阶段
  │◀── 二进制音频帧 ───────│  （流式推送 PCM）
  │◀── tts_real_end ───────│  TTS 完成
  │                         │
  │── client_out_audio_over▶│  设备播放完成
  │                         │── 启动下一轮 ASR
```

### 多设备并发

每个设备拥有独立的 Session 和 Pipeline，通过 asyncio 协程并行处理。全局并发控制（`PERF_GLOBAL_MAX_CONCURRENT_SESSIONS`）限制总并发数，防止单机过载。
