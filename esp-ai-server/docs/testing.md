# ESP-AI Server 开发者文档

## 测试框架

### 快速开始

```bash
uv run pytest tests/ -v
```

预期输出：25 个测试全部通过，0 warnings。

---

### 测试文件结构

```
tests/
├── __init__.py
├── conftest.py                    # 公共 fixtures：Mock WSChannel / MockFSM
├── test_sentence_splitter.py      # 句子分割器单元测试（9 个）
├── test_fsm.py                    # 会话状态机单元测试（8 个）
├── test_voice_generator.py        # 音频帧生成器单元测试（3 个）
└── test_integration.py            # 集成测试：HTTP 健康检查、SessionContext、TTS 打断（5 个）
```

### 测试分类

| 文件 | 类型 | 测试内容 |
|------|------|----------|
| `test_sentence_splitter.py` | 单元测试 | 中文/英文分句、流式 token 组装、缓冲区刷新、reset |
| `test_fsm.py` | 单元测试 | 合法状态转换、非法状态拦截、完整生命周期 |
| `test_voice_generator.py` | 单元测试 | TTS 帧格式（会话ID + 状态码 + 音频数据）、结束帧 |
| `test_integration.py` | 集成测试 | HTTP `/api/health`、SessionContext 生命周期、打断后 end_frame 发送 |

---

### 编写新测试

#### 1. 纯逻辑单元测试

不依赖任何外部服务，直接 import 被测类：

```python
# tests/test_my_module.py
from app.pipeline.sentence_splitter import SentenceSplitter

class TestMyFeature:
    def test_empty_input(self):
        s = SentenceSplitter()
        assert s.feed("") == []

    def test_normal_case(self):
        s = SentenceSplitter()
        result = s.feed("你好世界。")
        assert result == ["你好世界。"]
```

#### 2. 异步测试

使用 `@pytest.mark.asyncio` 装饰（或依赖 `pytest.ini` 中 `asyncio_mode = auto` 自动识别）：

```python
import pytest

@pytest.mark.asyncio
async def test_async_behavior():
    from app.websocket.channel import SessionFSM, SessionState
    fsm = SessionFSM()
    await fsm.set(SessionState.ASR)
    assert fsm.get() == SessionState.ASR
```

#### 3. Mock 测试（不依赖真实设备）

项目中内置了 Mock 辅助工具，`conftest.py` 提供：

```python
# 用法：在测试函数中声明参数即可自动注入
async def test_something(mock_channel):
    await mock_channel.send_json({"type": "test"})
    assert mock_channel.sent_json[0] == {"type": "test"}
```

**Mock WSChannel**（`conftest.py` → `mock_channel` fixture）：

| 方法 | 说明 |
|------|------|
| `sent_json` | 所有已发送 JSON 消息的列表 |
| `sent_bytes` | 所有已发送二进制消息的列表 |
| `clear_queue()` | 清空发送队列，返回清空数量 |

**MockFSM**（`conftest.py` → `mock_fsm` fixture）：

| 属性 | 说明 |
|------|------|
| `state` | 当前状态 |
| `transitions` | 所有状态转换记录 `[(from, to), ...]` |

#### 4. HTTP 端点测试

```python
from app.main import app
from fastapi.testclient import TestClient

def test_health():
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_liveness():
    client = TestClient(app)
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
```

---

### 测试命令参考

```bash
# 运行全部测试
uv run pytest tests/ -v

# 仅运行单元测试（跳过集成测试）
uv run pytest tests/test_fsm.py tests/test_sentence_splitter.py tests/test_voice_generator.py -v

# 仅运行集成测试
uv run pytest tests/test_integration.py -v

# 运行并显示最简输出
uv run pytest tests/ -q

# 运行并停在第一个失败
uv run pytest tests/ -x

# 按名称过滤（匹配函数名）
uv run pytest tests/ -v -k "splitter"

# 按名称过滤（匹配类名）
uv run pytest tests/ -v -k "TestSessionFSM"

# 显示慢测试（>0.1s）
uv run pytest tests/ -v --durations=5

# 生成覆盖率报告（需安装 pytest-cov）
uv run pytest tests/ --cov=app --cov-report=html
```

---

### 依赖

测试相关依赖已声明在 `pyproject.toml` 的 `[project.optional-dependencies] dev` 组中：

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",
]
```

安装方式：

```bash
uv pip install pytest pytest-asyncio httpx
```

---

### 配置文件

`pytest.ini` 位于项目根目录：

```ini
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

`asyncio_mode = "auto"` 表示：任何 `async def` 测试函数自动运行在 asyncio 事件循环中，无需手动加 `@pytest.mark.asyncio`。

---

### 最佳实践

1. **测试函数名以 `test_` 开头**，遵循 `test_<what>_<condition>_<expected>` 命名风格
2. **每个测试只验证一件事**，"一个测试 = 一个 assert" 是理想目标
3. **不依赖外部服务**（不连真实 ASR/LLM/TTS），使用 mock 替代
4. **先写测试再写代码**（TDD）有助于发现接口设计问题
5. **每次提交前运行 `pytest tests/ -v`**，确保全部通过
