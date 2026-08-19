# TTS 模块扩展指南

本指南详细说明如何为 ESP-AI 服务器添加新的 TTS（语音合成）服务支持。

## 现有架构

当前 TTS 模块采用了抽象工厂模式，具有良好的扩展性：

- `base.py` - 定义抽象基类 `BaseTTSProcessor`
- `volcengine.py` - 火山引擎 TTS 实现
- `factory.py` - 工厂函数，根据配置创建处理器
- `__init__.py` - 模块导出
- `voice_generator.py` - 语音帧生成工具

## 添加新 TTS 服务步骤

### 步骤 1: 创建新的 TTS 处理器类

在 `app/tts/` 目录下创建新的处理器文件，例如 `baidu_tts.py`：

```python
import asyncio
from app.tts.base import BaseTTSProcessor
from app.config import BAIDU_TTS_CONFIG
from app.utils.logger import info, error, debug


class BaiduTTSP(BaseTTSProcessor):
    """百度语音合成 TTS 处理器"""
    
    def __init__(self):
        self.client = None
        if BAIDU_TTS_CONFIG.get("api_key") and BAIDU_TTS_CONFIG.get("secret_key"):
            # 初始化百度 TTS 客户端
            # 这里需要根据百度 API 文档实现
            pass

    async def synthesize_stream(self, text: str):
        """流式合成语音，yield 音频数据块"""
        info("[Baidu TTS] 开始合成语音")

        if not self.client:
            error("百度 TTS 未配置")
            return

        try:
            # 调用百度 TTS API
            # 这里需要根据百度 API 文档实现
            # 示例：模拟流式输出
            info("[Baidu TTS] 正在请求合成...")
            
            # 模拟音频数据
            # 实际实现中应该调用百度 TTS API 获取真实的音频数据
            for i in range(3):
                # 模拟音频数据块
                audio_chunk = b"\x00\x00\x00\x00" * 1024
                yield audio_chunk
                await asyncio.sleep(0.1)
            
            info("[Baidu TTS] 合成完成")
        except Exception as e:
            error(f"[Baidu TTS] 合成异常: {e}")
