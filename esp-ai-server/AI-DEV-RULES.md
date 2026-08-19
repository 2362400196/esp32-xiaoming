# AI 开发规则 — Clean Architecture

> 所有 AI 助手（包括 Claude、Copilot、Cursor 等）在修改此项目代码时必须遵守以下规则。

## 1. 分层依赖方向（不可逆）

```
┌────────────────────────────────────────────────────────────┐
│  Domain 层 (domain/)          ← 最内层，零外部依赖         │
│  ─────────────────                                         │
│  entities.py      — 业务实体（纯数据类，无副作用）          │
│  value_objects.py — 值对象（不可变，通过值识别）            │
│  repositories.py  — 仓储接口（表达领域操作，不是 IO）       │
│  services.py      — 领域服务接口（纯业务操作）              │
│  exceptions.py    — 领域异常                               │
├────────────────────────────────────────────────────────────┤
│  Use Case 层 (use_cases/)     ← 依赖 Domain 接口           │
│  ─────────────────                                         │
│  XXX.py           — 用例实现                               │
│  规则：可以 import domain 下的接口，不可 import infrastructure │
├────────────────────────────────────────────────────────────┤
│  Interface 层 (interfaces/)   ← 依赖 Domain + Use Case     │
│  ─────────────────                                         │
│  websocket_handler.py  — WebSocket 适配器                  │
│  gateways.py           — 外部服务适配器                    │
│  规则：不包含业务逻辑，只做数据格式转换                     │
├────────────────────────────────────────────────────────────┤
│  Infrastructure 层 (infrastructure/) ← 实现 Domain 接口    │
│  ─────────────────                                         │
│  memory_repository.py  — JSON 文件仓储实现                 │
│  config.py             — 配置管理                          │
│  logging.py            — 日志实现                          │
│  规则：不包含业务逻辑，只做技术实现                         │
├────────────────────────────────────────────────────────────┤
│  组合根 (interfaces/ or main.py) ← 创建所有依赖并注入       │
│  ─────────────────                                         │
│  唯一允许"new 具体类"的地方                                  │
│  创建 Service → 注入到 Controller/Pipeline                  │
└────────────────────────────────────────────────────────────┘
```

## 2. 铁律（不可违反）

### 规则 2.1：依赖方向
```
USE CASE 层 禁止 import infrastructure 层的任何内容
```
```python
# ❌ 违规
from src.infrastructure.memory_repository import JsonLongTermMemoryRepository

# ✅ 合规
from src.domain.repositories import LongTermMemoryRepository
```

### 规则 2.2：Repository 接口表达领域操作，不是 IO
```python
# ❌ 违规
class MemoryRepository(ABC):
    async def load_records(self, device_id: str) -> list[dict]: ...
    async def append_record(self, device_id: str, record: dict) -> None: ...
    async def save_index(self, device_id: str, index: dict) -> None: ...

# ✅ 合规
class MemoryRepository(ABC):
    async def save(self, item: MemoryItem) -> None: ...
    async def find_by_labels(self, ...) -> list[MemoryItem]: ...
    async def mark_deleted(self, memory_id: str, device_id: str) -> None: ...
```

### 规则 2.3：Use Case 通过构造注入获取依赖
```python
# ❌ 违规
class MyService:
    def __init__(self):
        self._repo = JsonLongTermMemoryRepository()  # 直接在 Use Case 里 new

# ✅ 合规
class MyService:
    def __init__(self, repository: LongTermMemoryRepository):
        self._repo = repository  # 依赖通过构造注入
```

### 规则 2.4：Domain 实体不能有 infrastructure 依赖
```python
# ❌ 违规 — entities.py 里 import json / import requests
from dataclasses import dataclass
import json  # domain 层只能引入 Python 标准库

# ✅ 合规
from dataclasses import dataclass
from typing import Optional
```

### 规则 2.5：组合根是唯一 new 具体类的地方
```
websocket_handler.py 或 main.py
│
├── repo = JsonLongTermMemoryRepository()        ← 唯一允许 new 实现类
├── service = LongTermMemoryServiceImpl(repo)     ← 注入接口
├── tool_mgr.ltm_service = service                ← 注入
└── Session(ltm_service=service)                  ← 传递
```

## 3. 新增功能的操作流程

```
┌─────────────────────────────────────────────────────────────┐
│  1. 定义 Domain 接口                                         │
│     domain/repositories.py  +  abstract method              │
│     domain/services.py      +  abstract method              │
│     domain/entities.py      +  data class                   │
├─────────────────────────────────────────────────────────────┤
│  2. 实现 Infrastructure                                     │
│     infrastructure/xxx.py  class XxxImpl(XxxRepository):     │
├─────────────────────────────────────────────────────────────┤
│  3. 实现 Use Case                                           │
│     use_cases/xxx.py  class XxxService(XxxServiceInterface): │
│     只 import domain 层的接口                                 │
├─────────────────────────────────────────────────────────────┤
│  4. 组合根注入                                              │
│     websocket_handler.py 或 main.py                          │
│     → 创建实现 → 注入 Use Case → 注入 Pipeline               │
└─────────────────────────────────────────────────────────────┘
```

## 4. 文件结构验证

```
src/
├── domain/
│   ├── entities.py          ← 纯数据类，零依赖
│   ├── value_objects.py     ← frozen dataclass
│   ├── repositories.py      ← ABC，只含 abstractmethod
│   ├── services.py          ← ABC，只含 abstractmethod
│   └── exceptions.py        ← 自定义异常
├── use_cases/               ← 不可 import infrastructure
│   ├── memory.py
│   ├── pipeline.py
│   └── ...
├── interfaces/              ← 适配器，无业务逻辑
│   ├── websocket_handler.py
│   └── gateways.py
└── infrastructure/          ← 技术实现
    ├── memory_repository.py
    ├── config.py
    └── ...
```

## 5. 代码审查 Checklist

AI 生成代码后请自查：

- [ ] Use Case 是否 import 了 infrastructure？ → **必须删除**
- [ ] Repository 接口方法名是否表达了 IO（load/save_index）？ → **改为领域操作**
- [ ] Use Case 是否在构造器里 new 了具体类？ → **改为注入**
- [ ] Domain 实体是否引入了外部库？ → **只允许 stdlib**
- [ ] 组合根是否在多个地方分散 new？ → **集中到一个地方**
- [ ] import 链是否符合依赖方向？ → **domain ← use_cases ← interfaces/infrastructure**
