# ESP-AI-Server 架构图

本文档包含 ESP-AI-Server 项目的完整架构图，使用 Mermaid 语法绘制。

---

## 一、整体分层架构

```mermaid
graph TB
    subgraph "Interfaces Layer (接口适配器层)"
        I1["gateways.py (ASR/TTS 网关基类)"]
        I2["asr_gateways.py (ASR 工厂)"]
        I3["llm_gateways.py (LLM 网关)"]
        I4["tts_gateways.py (TTS 网关)"]
        I5["controllers.py (REST 控制器)"]
        I6["presenters.py (输出呈现器)"]
    end

    subgraph "Infrastructure Layer (基础设施层)"
        IF1["web.py (FastAPI 应用)"]
        IF2["config.py (配置管理)"]
        IF3["logging.py (彩色日志)"]
        IF4["connection_pool.py (连接池基类)"]
        IF5["auth.py (认证)"]
        IF6["di_container.py (DI 容器)"]
        IF7["monitoring.py (监控指标)"]
    end

    subgraph "Use Cases Layer (用例层 - 核心业务)"
        U1["session.py (会话核心)"]
        U2["pipeline.py (4-Worker 流水线)"]
        U3["session_fsm.py (状态机+WS通道)"]
        U4["session_management.py (会话管理器)"]
        U5["tools_system.py (工具框架)"]
        U6["builtin_tools.py (内置工具)"]
        U7["custom/ (自定义工具目录)"]
        U8["queues.py (三级背压队列)"]
        U9["voice_generator.py (音频帧生成)"]
        U10["auxiliary_services.py (辅助服务)"]
    end

    subgraph "Domain Layer (领域层 - 最内层)"
        D1["entities.py (实体)"]
        D2["exceptions.py (领域异常)"]
        D3["repositories.py (仓储接口)"]
        D4["services.py (领域服务接口)"]
        D5["value_objects.py (值对象)"]
    end

    %% 依赖关系（外层依赖内层）
    U1 --> D1
    U1 --> D2
    U1 --> D3
    U1 --> D4
    U1 --> D5
    
    U2 --> D1
    U2 --> D2
    
    U3 --> D1
    U3 --> IF3
    
    U5 --> D1
    U5 --> D2
    U5 --> IF3
    U5 --> IF2
    
    U6 --> U5
    U7 --> U5
    
    U10 --> D1
    U10 --> D2
    U10 --> IF2
    U10 --> IF3
    
    I1 --> D1
    I1 --> D2
    I1 --> D3
    I1 --> IF4
    I1 --> IF3
    
    I2 --> I1
    I3 --> D1
    I3 --> D2
    I3 --> D3
    I4 --> I1
    
    I5 --> U1
    I5 --> U2
    I5 --> U5
    
    IF1 --> I1
    IF1 --> I2
    IF1 --> I3
    IF1 --> I4
    IF1 --> U1
    IF1 --> U2
    IF1 --> U3
    IF1 --> U5
    IF1 --> U10
    IF1 --> IF2
    IF1 --> IF3
```

---

## 二、核心数据流向图

```mermaid
sequenceDiagram
    autonumber
    participant Dev as ESP32 设备
    participant WS as WebSocket 通道 (WSChannel)
    participant FSM as 会话状态机 (SessionFSM)
    participant ASR as ASR 网关
    participant Mem as 对话记忆
    participant LLM as LLM 网关
    participant Tool as 工具系统
    participant TTS as TTS 网关
    participant VG as 语音生成器

    Dev->>WS: 唤醒词 (或直接连接)
    activate WS
    FSM->>FSM: IDLE → ASR
    WS->>Dev: iat_start 状态
    Dev->>WS: 二进制音频帧
    loop 音频流持续
        WS->>ASR: 音频入队
    end
    ASR->>WS: 识别完成文本
    FSM->>FSM: ASR → LLM
    WS->>Mem: 保存用户消息
    Mem-->>WS: 返回历史上下文
    WS->>LLM: 发送对话请求
    activate LLM
    loop 流式输出 token
        LLM-->>WS: 增量 token
    end
    alt LLM 决定调用工具
        LLM-->>WS: 工具调用请求
        WS->>Tool: 执行工具
        Tool-->>WS: 工具结果
        WS->>LLM: 回传工具结果
        loop 工具循环 (最多5轮)
            LLM-->>WS: 可能继续调用工具
        end
    end
    LLM-->>WS: 最终回复文本
    deactivate LLM
    FSM->>FSM: LLM → TTS
    WS->>TTS: 合成语音
    activate TTS
    loop 流式音频块
        TTS-->>WS: PCM 音频块
        WS->>VG: 帧封装
        VG->>WS: TTS 二进制帧
        WS->>Dev: 发送音频帧
    end
    TTS-->>WS: 合成完成
    deactivate TTS
    WS->>VG: 结束帧
    VG->>WS: 结束帧 (SID=0010, status=03)
    WS->>Dev: 发送结束帧
    WS->>Dev: tts_real_end 状态
    FSM->>FSM: TTS → ASR
    WS->>Dev: iat_start 状态 (开始下一轮)
    deactivate WS
```

---

## 三、会话状态机

```mermaid
stateDiagram-v2
    [*] --> IDLE: 设备连接/会话结束
    
    IDLE --> ASR: 开始语音识别<br/>(唤醒/上一轮TTS完成)
    IDLE --> IDLE: 空闲
    
    ASR --> LLM: 识别到文本
    ASR --> IDLE: 无语音超时<br/>(Watchdog 触发)
    ASR --> IDLE: 停止会话
    
    LLM --> TTS: 生成回复
    
    TTS --> ASR: TTS 播放完成<br/>(下一轮自动开始)
    TTS --> IDLE: 会话结束<br/>(工具触发/超时)
    
    state "语音识别中" as ASR
    state "大模型思考中" as LLM
    state "语音合成/播放中" as TTS
    state "待机" as IDLE
```

---

## 四、4-Worker 并发流水线

```mermaid
graph TB
    subgraph "输入"
        A["ASR 识别文本"]
    end

    subgraph "LLM Worker"
        B["从 LLM 获取流式 token"]
        C["组装 buffer"]
    end

    subgraph "Sentence Splitter"
        D["句子分割 (。！？.!?)"]
        E["flush 剩余文本"]
    end

    subgraph "TTS Worker"
        F["调用 TTS 合成"]
        G["获取 PCM 音频块"]
    end

    subgraph "Sender Worker"
        H["封装 TTS 帧"]
        I["发送到设备"]
        J["发送结束帧"]
    end

    subgraph "背压队列"
        Q1["text_queue<br/>(drop_oldest)"]
        Q2["audio_queue<br/>(block)"]
        Q3["send_queue<br/>(block)"]
    end

    A --> B
    B --> C
    C -->|token 到达| D
    C -->|LLM 完成| E
    D --> Q1
    E --> Q1
    Q1 --> F
    F --> G
    G --> Q2
    Q2 --> H
    H --> I
    I -->|继续| H
    I -->|所有音频发送完毕| J

    classDef worker fill:#e1f5ff,stroke:#0066cc,stroke-width:2px
    classDef queue fill:#fff4e1,stroke:#cc6600,stroke-width:2px
    class B,C,D,E,F,G,H,I,J worker
    class Q1,Q2,Q3 queue
```

---

## 五、完整会话生命周期

```mermaid
graph TB
    Start["设备连接 WebSocket<br/>(/ws 端点)"] --> Auth["设备认证<br/>(API Key 或 users.json)"]
    
    Auth -->|成功| Create["创建 Session + FSM + WSChannel"]
    Auth -->|失败| Reject["401 Unauthorized"]
    
    Create --> Reg["注册到 DeviceRegistry"]
    Reg --> Greet["发送问候语<br/>(TTS 合成欢迎语)"]
    
    Greet --> LoopStart["进入自动对话循环"]
    
    subgraph "循环：ASR → LLM → TTS"
        LoopStart --> ASRStart["启动 ASR 识别<br/>(FSM: IDLE → ASR)"]
        ASRStart --> RecvAudio["接收设备音频<br/>(queue_audio())"]
        RecvAudio --> ASRProcess["ASR 流式处理"]
        
        ASRProcess -->|有识别结果| LLMStart["启动 Pipeline<br/>(FSM: ASR → LLM)"]
        ASRProcess -->|Watchdog 超时| EndSession["发送 session_end<br/>(FSM: ASR → IDLE)"]
        
        LLMStart --> PipelineRun["4-Worker 流水线运行"]
        PipelineRun -->|工具调用| ToolExec["执行工具 (可选)"]
        ToolExec --> PipelineRun
        PipelineRun -->|TTS 播放完成| NextASR["回到 ASRStart<br/>(FSM: TTS → ASR)"]
        PipelineRun -->|需要结束| EndSession
    end
    
    EndSession --> Disconnect["WebSocket 断开"]
    Disconnect --> Cleanup["清理资源<br/>(从 DeviceRegistry 移除)"]
    Reject --> Cleanup
    Cleanup --> Done["会话结束"]
```

---

## 六、工具系统架构

```mermaid
graph TB
    subgraph "工具注册与发现"
        Discover["auto_discover()"] --> ScanBuiltin["扫描 builtin_tools.py"]
        Discover --> ScanCustom["扫描 custom/ 目录"]
        ScanBuiltin --> RegTool["@tool() 装饰器<br/>(_registry 字典)"]
        ScanCustom --> RegTool
    end

    subgraph "工具调用"
        LLMCall["LLM 决定调用工具"] --> GetTool["get_tool(tool_name)"]
        GetTool --> Coerce["参数类型转换<br/>(_coerce_args)"]
        Coerce --> Inject["自动注入特殊参数<br/>(tool_manager/channel/fsm)"]
        Inject --> Exec["执行工具函数"]
        Exec -->|StopPipeline| Stop["终止 Pipeline"]
        Exec -->|正常返回| Return["返回结果给 LLM"]
    end

    subgraph "工具类型"
        Builtin["内置工具<br/>(builtin_tools.py)"]
        Custom["自定义工具<br/>(custom/*.py)"]
        MCP["MCP 外部工具<br/>(工具服务器)"]
    end

    RegTool --> Builtin
    RegTool --> Custom
    RegTool --> MCP

    Builtin --> GetTool
    Custom --> GetTool
    MCP --> GetTool
```

---

## 七、目录结构树

```
src/
├── main.py                          # 入口点
├── domain/
│   ├── __init__.py
│   ├── entities.py                  # 实体定义
│   │   ├── SessionState
│   │   ├── Session
│   │   ├── Device
│   │   ├── Conversation
│   │   ├── Message
│   │   └── ToolCall
│   ├── exceptions.py                # 领域异常层级
│   ├── repositories.py              # 仓储接口
│   ├── services.py                  # 领域服务接口
│   └── value_objects.py             # 值对象
├── use_cases/
│   ├── __init__.py
│   ├── session.py                   # 会话核心
│   │   ├── SessionRuntime
│   │   ├── Session
│   │   └── Watchdog
│   ├── pipeline.py                  # 4-Worker 流水线
│   │   ├── SentenceSplitter
│   │   ├── PipelineConfig
│   │   └── ConversationPipeline
│   ├── session_fsm.py               # 状态机 + WS通道
│   │   ├── SessionFSM
│   │   └── WSChannel
│   ├── session_management.py        # 会话管理器
│   ├── tools_system.py              # 工具框架
│   │   ├── @tool() 装饰器
│   │   ├── PerUserToolManager
│   │   └── auto_discover()
│   ├── builtin_tools.py             # 内置工具
│   ├── custom/                      # 自定义工具目录
│   │   ├── __init__.py
│   │   └── example.py
│   ├── queues.py                    # 三级背压队列
│   ├── voice_generator.py           # 音频帧生成器
│   ├── auxiliary_services.py        # 辅助服务
│   │   ├── DeviceRegistry
│   │   ├── WakeAudioManager
│   │   ├── EmotionDetector
│   │   ├── EmotionRenderer
│   │   ├── ImageSender
│   │   ├── ConversationMemory
│   │   └── Speaker
│   ├── dtos.py
│   └── ports.py
├── infrastructure/
│   ├── __init__.py
│   ├── web.py                       # FastAPI 应用
│   ├── config.py                    # 配置管理
│   ├── logging.py                   # 彩色日志系统
│   ├── connection_pool.py           # 连接池基类
│   ├── auth.py                      # 认证
│   ├── di_container.py              # DI 容器
│   └── monitoring.py                # 监控指标
└── interfaces/
    ├── __init__.py
    ├── gateways.py                  # ASR 网关基类
    ├── asr_gateways.py              # ASR 工厂
    ├── llm_gateways.py              # LLM 网关
    ├── tts_gateways.py              # TTS 网关
    ├── controllers.py               # REST 控制器
    └── presenters.py                # 输出呈现器
```

---

## 八、WebSocket 消息交换时序

```mermaid
sequenceDiagram
    autonumber
    participant D as ESP32 设备
    participant S as 服务端 (FastAPI)

    Note over D,S: 连接阶段
    D->>S: WebSocket Upgrade (带 device_key)
    S->>S: 认证验证
    alt 认证成功
        S->>D: 200 OK (连接建立)
        S->>D: session_start (session_id=0001)
        S->>D: iat_start 状态
    else 认证失败
        S->>D: 401 Unauthorized
        S->>D: 关闭连接
    end

    Note over D,S: 唤醒阶段
    D->>S: 唤醒词 (或用户直接说话)
    S->>S: 检测到唤醒
    S->>D: play_audio (tts_task_id=0010)
    S->>D: tts_chunk_start
    loop 发送唤醒音
        S->>D: 二进制 TTS 帧 (SID=0010, status=00)
    end
    S->>D: 结束帧 (SID=0010, status=03)
    S->>D: tts_real_end

    Note over D,S: ASR 识别阶段
    S->>D: iat_start
    loop 用户说话
        D->>S: 二进制音频帧 (PCM 16kHz 16bit mono)
    end
    S->>S: ASR 识别完成
    S->>D: iat_end
    D->>S: 停止发送音频

    Note over D,S: Pipeline 阶段
    S->>D: 中间指示 (可选)
    S->>D: play_audio (tts_task_id=0010)
    S->>D: tts_chunk_start
    loop 发送 TTS 音频
        S->>D: 二进制 TTS 帧 (SID=0010, status=00)
    end
    S->>D: 结束帧 (SID=0010, status=03)
    S->>D: tts_real_end

    Note over D,S: 设备播放完成
    D->>S: client_out_audio_over

    Note over D,S: 下一轮开始
    S->>D: iat_start (开始下一轮)

    Note over D,S: 心跳保活
    loop 每 30 秒
        S->>D: keepalive
        D->>S: keepalive (或忽略)
    end
```

---

## 九、工具循环调用图

```mermaid
graph TB
    A["LLM 接收到用户请求"] --> B{"LLM 是否需要调用工具？"}
    
    B -->|否| Z["生成最终回复"]
    B -->|是| C["解析 tool calls"]
    
    C --> D["工具调用数量 N"]
    D --> LoopStart["循环 N 次"]
    
    LoopStart --> E["获取工具 (get_tool())"]
    E --> F{"工具存在？"}
    F -->|否| G["返回工具不存在错误"]
    F -->|是| H["参数类型转换 (_coerce_args)"]
    
    H --> I["自动注入特殊参数"]
    I --> J["执行工具函数"]
    J --> K{"抛出 StopPipeline？"}
    K -->|是| L["终止 Pipeline"]
    K -->|否| M["工具返回结果"]
    
    M --> N["保存工具结果到上下文"]
    N --> O{"还有工具？"}
    O -->|是| LoopStart
    O -->|否| P["将所有工具结果回传给 LLM"]
    
    P --> Q["LLM 处理工具结果"]
    Q --> R{"LLM 是否需要更多工具？"}
    R -->|否| Z
    R -->|是, <5轮| B
    R -->|是, >=5轮| S["已达最大工具调用轮数，返回"]
    S --> Z
```

---

## 十、ASR 连接池与预热

```mermaid
graph TB
    subgraph "启动阶段"
        A["服务启动"] --> B["初始化 ASR 网关"]
        B --> C["创建连接池 (VolcEngineASRConnectionPool)"]
        C --> D["预热: 建立 min_size 个裸 WebSocket"]
        D --> E["连接加入空闲队列，config 暂不发送"]
    end

    subgraph "使用阶段"
        F["会话需要 ASR"] --> G["从池中获取连接 (take_pre_ws())"]
        G --> H{"连接过期？(<25秒)"}
        H -->|否| I["发送 config + 等待 ACK"]
        H -->|是| J["建立新连接"]
        J --> I
        I --> K["开始发送音频"]
    end

    subgraph "归还阶段"
        L["ASR 完成"] --> M["检查连接健康"]
        M -->|健康| N["归还到空闲队列"]
        M -->|不健康| O["关闭连接"]
    end

    E --> G
    K --> L
    N --> G
```

---

## 十一、音频帧格式

```mermaid
graph TB
    subgraph "TTS 数据帧"
        A1["字节 0-3"] -->|UTF-8| A2["会话ID<br/>(\"0010\" = TTS)"]
        A3["字节 4-5"] -->|UTF-8| A4["状态码<br/>(\"00\" = 正常数据)"]
        A5["字节 6+"] --> A6["PCM 音频数据<br/>(16kHz, 16bit, mono)"]
    end

    subgraph "TTS 结束帧"
        B1["字节 0-3"] -->|UTF-8| B2["会话ID<br/>(\"0010\" = TTS)"]
        B3["字节 4-5"] -->|UTF-8| B4["状态码<br/>(\"03\" = 结束)"]
    end

    subgraph "连接/问候帧"
        C1["字节 0-3"] -->|UTF-8| C2["会话ID<br/>(\"0001\" = CONNECTED)"]
        C3["字节 4-5"] -->|UTF-8| C4["状态码<br/>(\"00\" = 正常数据)"]
    end

    style A6 fill:#e1f5ff,stroke:#0066cc,stroke-width:2px
    style B4 fill:#c8e6c9,stroke:#2e7d32,stroke-width:2px
    style C2 fill:#fff4e1,stroke:#cc6600,stroke-width:2px
```

---

## 十二、Watchdog 超时检测

```mermaid
flowchart TB
    A["Watchdog 启动"] --> B["定时器开始"]
    B --> C["定时检查 (每 1 秒)"]
    
    C --> D{"asr_start_time 存在？"}
    D -->|否| C
    D -->|是| E{"asr_last_result_time 存在？"}
    
    E -->|否| F{"asr_start_time 超时？"}
    F -->|是| G["触发无语音超时"]
    F -->|否| C
    
    E -->|是| H{"asr_last_result_time 超时？"}
    H -->|是| G
    H -->|否| C
    
    G --> I["发送 iat_end + session_end"]
    I --> J["FSM 设为 IDLE"]
    J --> K["等待下一轮"]
```

---

## 十三、文件依赖关系简图

```mermaid
graph LR
    Main["main.py"] --> Web["web.py"]
    
    Web --> Config["config.py"]
    Web --> Log["logging.py"]
    Web --> Sess["session.py"]
    Web --> Pipe["pipeline.py"]
    Web --> FSM["session_fsm.py"]
    Web --> Tools["tools_system.py"]
    Web --> Aux["auxiliary_services.py"]
    Web --> ASR["asr_gateways.py"]
    Web --> LLM["llm_gateways.py"]
    Web --> TTS["tts_gateways.py"]
    
    Sess --> Ent["entities.py"]
    Sess --> Ex["exceptions.py"]
    Sess --> Log
    Sess --> FSM
    Sess --> Que["queues.py"]
    Sess --> VG["voice_generator.py"]
    Sess --> Aux
    
    Pipe --> Ex
    Pipe --> Log
    Pipe --> Que
    Pipe --> VG
    
    Tools --> Ent
    Tools --> Ex
    Tools --> Config
    Tools --> Log
    
    Builtin["builtin_tools.py"] --> Tools
    Custom["custom/*.py"] --> Tools
    
    ASR --> GW["gateways.py"]
    GW --> Ent
    GW --> Ex
    GW --> Repo["repositories.py"]
    GW --> CP["connection_pool.py"]
    GW --> Log
    
    LLM --> Ent
    LLM --> Ex
    LLM --> Repo
    LLM --> Log
    
    TTS --> GW
    TTS --> VG
    
    Aux --> Config
    Aux --> Log
    Aux --> TTS
    Aux --> VG
```
