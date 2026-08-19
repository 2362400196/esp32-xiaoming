# LLM 模块扩展指南

本指南详细说明如何为 ESP-AI 服务器添加新的大模型支持。

## 现有架构

当前 LLM 模块采用了抽象工厂模式，具有良好的扩展性：

- `base.py` - 定义抽象基类 `BaseLLMProcessor`
- `openai_llm.py` - OpenAI 兼容接口实现
- `factory.py` - 工厂函数，根据配置创建处理器
- `__init__.py` - 模块导出

## 添加新大模型步骤

### 步骤 1: 创建新的处理器类

在 `app/llm/` 目录下创建新的处理器文件，例如 `baidu_ernie.py`：

```python
import asyncio
from app.llm.base import BaseLLMProcessor
from app.config import BAIDU_API_KEY, BAIDU_SECRET_KEY, LLM_SYSTEM_PROMPT
from app.utils.logger import info, error, debug

SEP = "=" * 50
THIN_SEP = "-" * 50


class BaiduErnieLLM(BaseLLMProcessor):
    """百度文心一言 LLM 处理器"""
    
    def __init__(self):
        self.client = None
        if BAIDU_API_KEY and BAIDU_SECRET_KEY:
            # 初始化百度文心一言客户端
            # 这里需要根据百度 API 文档实现
            pass

    async def process_text(self, text: str) -> str:
        """处理文本并生成 LLM 回复（非流式）"""
        debug(f"{THIN_SEP}")
        debug(f"[ASR 识别] {text}")
        debug(f"{THIN_SEP}")

        if not self.client:
            return "百度文心一言未配置 - 这是模拟响应"

        try:
            info(f"{SEP}")
            info("[Baidu Ernie LLM] 正在请求大模型...")
            # 调用百度文心一言 API
            # 这里需要根据百度 API 文档实现
            llm_response = "这是百度文心一言的模拟回复"
            info(f"[Baidu Ernie LLM 回复]")
            info(llm_response)
            info(f"{SEP}")
            return llm_response
        except Exception as e:
            error(f"[Baidu Ernie LLM] 请求异常: {e}")
            return f"LLM 请求失败: {str(e)}"

    async def generate_response_stream(self, text: str):
        """流式生成 LLM 回复，yield 每个文本片段"""
        debug(f"{THIN_SEP}")
        debug(f"[ASR 识别] {text}")
        debug(f"{THIN_SEP}")

        if not self.client:
            yield "百度文心一言未配置 - 这是模拟响应"
            return

        try:
            info(f"{SEP}")
            info("[Baidu Ernie LLM] 正在流式请求大模型...")
            # 调用百度文心一言流式 API
            # 这里需要根据百度 API 文档实现
            
            # 模拟流式输出
            response_parts = ["这是", "百度文心一言", "的流式", "回复"]
            full_text = ""
            for part in response_parts:
                full_text += part
                yield part
                await asyncio.sleep(0.1)

            info(f"[Baidu Ernie LLM 回复]")
            info(full_text)
            info(f"{SEP}")
        except Exception as e:
            error(f"[Baidu Ernie LLM] 流式请求异常: {e}")
            yield f"LLM 请求失败: {str(e)}"
```

### 步骤 2: 更新工厂函数

修改 `app/llm/factory.py` 文件，添加对新大模型的支持：

```python
from app.config import LLM_TYPE
from app.llm.openai_llm import OpenAILLM
from app.llm.baidu_ernie import BaiduErnieLLM


def create_llm_processor():
    """创建 LLM 处理器实例"""
    if LLM_TYPE == "openai":
        return OpenAILLM()
    elif LLM_TYPE == "baidu":
        return BaiduErnieLLM()
    else:
        # 默认使用 OpenAI 兼容接口
        return OpenAILLM()
```

### 步骤 3: 添加配置项

修改 `app/config.py` 文件，添加新大模型的配置：

```python
# LLM 配置
LLM_TYPE = "openai"  # LLM 类型: openai | baidu

# OpenAI 兼容接口配置
LLM_API_KEY = "sk-your-api-key"
LLM_BASE_URL = "https://api.deepseek.com/v1"
LLM_MODEL = "deepseek-v4-flash"

# 百度文心一言配置
BAIDU_API_KEY = "your_baidu_api_key"
BAIDU_SECRET_KEY = "your_baidu_secret_key"

# LLM 系统提示词
LLM_SYSTEM_PROMPT = "你是一个智能语音助手，请用最短的中文回答用户的问题"
```

### 步骤 4: 更新模块导出

修改 `app/llm/__init__.py` 文件，添加新的处理器类：

```python
from app.llm.base import BaseLLMProcessor
from app.llm.openai_llm import OpenAILLM
from app.llm.baidu_ernie import BaiduErnieLLM
from app.llm.factory import create_llm_processor

__all__ = ['BaseLLMProcessor', 'OpenAILLM', 'BaiduErnieLLM', 'create_llm_processor']
```

### 步骤 5: 安装必要的依赖

如果新的大模型需要特定的 SDK 或依赖，需要在 `pyproject.toml` 或 `requirements.txt` 中添加：

```bash
# 例如，百度文心一言可能需要的依赖
pip install baidu-aip
```

### 步骤 6: 测试新大模型

1. 修改 `config.py` 中的 `LLM_TYPE` 为新的大模型类型，例如：
   ```python
   LLM_TYPE = "baidu"
   ```

2. 启动服务器并测试：
   ```bash
   python main.py
   ```

3. 检查终端输出，确保新的大模型被正确初始化和使用。

## 示例：添加百度文心一言

### 1. 安装百度 SDK

```bash
pip install baidu-aip
```

### 2. 实现百度文心一言处理器

```python
# app/llm/baidu_ernie.py
import asyncio
from aip import AipNlp
from app.llm.base import BaseLLMProcessor
from app.config import BAIDU_API_KEY, BAIDU_SECRET_KEY, LLM_SYSTEM_PROMPT
from app.utils.logger import info, error, debug

SEP = "=" * 50
THIN_SEP = "-" * 50


class BaiduErnieLLM(BaseLLMProcessor):
    """百度文心一言 LLM 处理器"""
    
    def __init__(self):
        self.client = None
        if BAIDU_API_KEY and BAIDU_SECRET_KEY:
            # 初始化百度文心一言客户端
            # 注意：这里使用的是百度 NLP API，实际文心一言需要使用对应的 API
            self.client = AipNlp(BAIDU_API_KEY, BAIDU_SECRET_KEY, "your_app_id")

    async def process_text(self, text: str) -> str:
        """处理文本并生成 LLM 回复（非流式）"""
        debug(f"{THIN_SEP}")
        debug(f"[ASR 识别] {text}")
        debug(f"{THIN_SEP}")

        if not self.client:
            return "百度文心一言未配置 - 这是模拟响应"

        try:
            info(f"{SEP}")
            info("[Baidu Ernie LLM] 正在请求大模型...")
            # 调用百度文心一言 API
            # 这里需要根据百度 API 文档实现
            # 示例：使用百度 NLP 情感分析 API 作为模拟
            result = self.client.sentimentClassify(text)
            llm_response = f"情感分析结果: {result}"
            info(f"[Baidu Ernie LLM 回复]")
            info(llm_response)
            info(f"{SEP}")
            return llm_response
        except Exception as e:
            error(f"[Baidu Ernie LLM] 请求异常: {e}")
            return f"LLM 请求失败: {str(e)}"

    async def generate_response_stream(self, text: str):
        """流式生成 LLM 回复，yield 每个文本片段"""
        debug(f"{THIN_SEP}")
        debug(f"[ASR 识别] {text}")
        debug(f"{THIN_SEP}")

        if not self.client:
            yield "百度文心一言未配置 - 这是模拟响应"
            return

        try:
            info(f"{SEP}")
            info("[Baidu Ernie LLM] 正在流式请求大模型...")
            # 调用百度文心一言流式 API
            # 这里需要根据百度 API 文档实现
            
            # 模拟流式输出
            response_parts = ["你好", "我是", "百度文心一言", "很高兴为你服务"]
            full_text = ""
            for part in response_parts:
                full_text += part
                yield part
                await asyncio.sleep(0.1)

            info(f"[Baidu Ernie LLM 回复]")
            info(full_text)
            info(f"{SEP}")
        except Exception as e:
            error(f"[Baidu Ernie LLM] 流式请求异常: {e}")
            yield f"LLM 请求失败: {str(e)}"
```

### 3. 更新配置

```python
# app/config.py
# LLM 配置
LLM_TYPE = "baidu"  # LLM 类型: openai | baidu

# 百度文心一言配置
BAIDU_API_KEY = "your_baidu_api_key"
BAIDU_SECRET_KEY = "your_baidu_secret_key"
```

## 注意事项

1. **API 文档**：不同大模型的 API 接口可能不同，需要根据官方文档实现。
2. **认证方式**：不同大模型的认证方式可能不同，需要正确配置。
3. **流式输出**：如果大模型支持流式输出，需要实现对应的流式处理逻辑。
4. **错误处理**：需要添加适当的错误处理，确保服务稳定性。
5. **性能优化**：对于大模型调用，需要考虑超时设置和重试机制。

## 支持的大模型类型

- **openai**：OpenAI 兼容接口（如 DeepSeek、GPT 等）
- **baidu**：百度文心一言（需要实现）
- **ali**：阿里云通义千问（需要实现）
- **tencent**：腾讯云混元大模型（需要实现）
- **anthropic**：Anthropic Claude（需要实现）

通过这种架构，可以轻松扩展支持更多的大模型，只需按照上述步骤实现对应的处理器类即可。
