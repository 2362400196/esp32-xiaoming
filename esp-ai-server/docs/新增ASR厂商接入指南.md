# 新增 ASR 厂商接入指南

本文档详细说明如何为 ESP-AI 服务端新增一个 ASR（语音识别）厂商。以阿里云 ASR 为例，完整演示从代码实现到配置切换的全流程。

---

## 一、整体架构回顾

```
app/iat/
├── base.py              # 抽象基类（统一接口）
├── factory.py           # 工厂函数（根据配置创建客户端）
├── tencent/             # 腾讯云（已完成）
│   ├── __init__.py
│   └── tencent_asr.py
├── aliyun/              # 阿里云（示例）
│   ├── __init__.py
│   └── aliyun_asr.py
└── ...                  # 其他厂商
```

**核心设计**：
- `BaseASRClient` 定义所有厂商必须实现的接口
- `factory.py` 根据 `ASR_PROVIDER` 配置创建对应客户端
- `handler.py` 通过工厂获取客户端，无需关心底层厂商

---

## 二、接入步骤总览

新增一个 ASR 厂商需要完成以下 5 个步骤：

1. 创建厂商目录和 `__init__.py`
2. 实现 `BaseASRClient` 的子类
3. 在工厂中注册新厂商
4. 在配置文件中添加厂商配置
5. 切换配置并测试

---

## 三、详细步骤（以阿里云为例）

### 步骤 1：创建厂商目录

在 `app/iat/` 下创建新厂商的目录：

```bash
mkdir app/iat/aliyun
```

创建 `__init__.py` 文件，导出客户端类：

```python
# app/iat/aliyun/__init__.py
from .aliyun_asr import AliyunASRClient

__all__ = ["AliyunASRClient"]
```

---

### 步骤 2：实现 ASR 客户端类

创建 `app/iat/aliyun/aliyun_asr.py`，继承 `BaseASRClient` 并实现所有抽象方法。

#### 2.1 文件模板

```python
import json
import asyncio
import websockets
from typing import Optional, Callable
from app.iat.base import BaseASRClient


class AliyunASRClient(BaseASRClient):
    """阿里云 ASR 客户端"""

    def __init__(
        self,
        app_key: str,
        access_key_id: str,
        access_key_secret: str,
        region: str = "cn-shanghai",
        **kwargs
    ):
        """
        初始化阿里云 ASR 客户端

        :param app_key: 阿里云应用 Key
        :param access_key_id: Access Key ID
        :param access_key_secret: Access Key Secret
        :param region: 服务区域，默认 cn-shanghai
        """
        super().__init__(
            app_key=app_key,
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            region=region,
            **kwargs
        )
        self.app_key = app_key
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.region = region
        self.ws_url = f"wss://nls-gateway.{region}.aliyuncs.com/ws/v1"

    def _build_url(self) -> str:
        """
        构建 WebSocket 连接 URL

        阿里云需要先用 AK/SK 获取 Token，再用 Token 构建 WebSocket URL
        """
        # 1. 获取 Token（HTTP 请求）
        token = self._get_token()

        # 2. 构建 WebSocket URL
        params = {
            "token": token,
            "appkey": self.app_key,
        }
        param_string = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.ws_url}?{param_string}"

    def _get_token(self) -> str:
        """
        获取阿里云访问 Token

        实际实现需要调用阿里云 Pop 网关获取 Token
        这里仅作示例
        """
        import requests
        import time
        import hashlib
        import hmac
        import base64

        # 构造签名
        timestamp = int(time.time() * 1000)
        string_to_sign = f"GET&%2F&AccessKeyId%3D{self.access_key_id}"
        # ... 实际签名逻辑请参考阿里云官方文档

        # 发送请求获取 Token
        url = "https://nls-meta.cn-shanghai.aliyuncs.com"
        # response = requests.get(url, params={...})
        # return response.json()["Token"]["Id"]

        # 占位实现
        return "your_token_here"

    async def recognize(
        self,
        audio_data: bytes,
        callback: Optional[Callable[[str], None]] = None
    ) -> str:
        """
        单次语音识别

        :param audio_data: 完整的音频数据（PCM 格式）
        :param callback: 识别结果回调函数
        :return: 识别完整文本
        """
        full_text = ""
        url = self._build_url()

        try:
            async with websockets.connect(url) as ws:
                # 1. 发送开始识别指令
                start_cmd = {
                    "header": {
                        "message_id": "your_message_id",
                        "task_id": "your_task_id",
                        "namespace": "SpeechRecognizer",
                        "name": "StartRecognition",
                        "appkey": self.app_key
                    },
                    "payload": {
                        "format": "pcm",
                        "sample_rate": 16000,
                        "enable_intermediate_result": True,
                        "enable_punctuation_prediction": True
                    }
                }
                await ws.send(json.dumps(start_cmd))

                # 2. 发送音频数据
                await ws.send(audio_data)

                # 3. 发送结束标记
                end_cmd = {
                    "header": {
                        "message_id": "your_message_id",
                        "task_id": "your_task_id",
                        "namespace": "SpeechRecognizer",
                        "name": "StopRecognition"
                    }
                }
                await ws.send(json.dumps(end_cmd))

                # 4. 接收识别结果
                while True:
                    response = await asyncio.wait_for(ws.recv(), timeout=30.0)
                    result = json.loads(response)

                    # 解析结果
                    header = result.get("header", {})
                    name = header.get("name", "")

                    if name == "RecognitionResultChanged":
                        # 中间结果
                        payload = result.get("payload", {})
                        text = payload.get("result", "")
                        if callback:
                            callback(text)
                        full_text = text  # 阿里云中间结果是增量还是全量视具体版本

                    elif name == "RecognitionCompleted":
                        # 识别完成
                        payload = result.get("payload", {})
                        full_text = payload.get("result", "")
                        break

                    elif name == "TaskFailed":
                        # 识别失败
                        print(f"ASR failed: {result}")
                        break

        except Exception as e:
            print(f"Aliyun ASR error: {e}")
            import traceback
            traceback.print_exc()

        return full_text

    async def recognize_streaming(
        self,
        audio_chunks: list[bytes],
        callback: Optional[Callable[[str], None]] = None
    ) -> str:
        """
        流式语音识别

        :param audio_chunks: 音频数据块列表
        :param callback: 识别结果回调函数
        :return: 识别完整文本
        """
        full_text = ""
        url = self._build_url()

        try:
            async with websockets.connect(url) as ws:
                # 1. 发送开始识别指令
                start_cmd = {
                    "header": {
                        "message_id": "your_message_id",
                        "task_id": "your_task_id",
                        "namespace": "SpeechRecognizer",
                        "name": "StartRecognition",
                        "appkey": self.app_key
                    },
                    "payload": {
                        "format": "pcm",
                        "sample_rate": 16000,
                        "enable_intermediate_result": True,
                        "enable_punctuation_prediction": True
                    }
                }
                await ws.send(json.dumps(start_cmd))

                # 2. 流式发送音频数据
                for chunk in audio_chunks:
                    await ws.send(chunk)
                    await asyncio.sleep(0.01)  # 控制发送速率

                # 3. 发送结束标记
                end_cmd = {
                    "header": {
                        "message_id": "your_message_id",
                        "task_id": "your_task_id",
                        "namespace": "SpeechRecognizer",
                        "name": "StopRecognition"
                    }
                }
                await ws.send(json.dumps(end_cmd))

                # 4. 接收识别结果
                while True:
                    response = await asyncio.wait_for(ws.recv(), timeout=30.0)
                    result = json.loads(response)

                    header = result.get("header", {})
                    name = header.get("name", "")

                    if name == "RecognitionResultChanged":
                        payload = result.get("payload", {})
                        text = payload.get("result", "")
                        if callback:
                            callback(text)
                        full_text = text

                    elif name == "RecognitionCompleted":
                        payload = result.get("payload", {})
                        full_text = payload.get("result", "")
                        break

                    elif name == "TaskFailed":
                        print(f"ASR failed: {result}")
                        break

        except Exception as e:
            print(f"Aliyun ASR streaming error: {e}")
            import traceback
            traceback.print_exc()

        return full_text
```

#### 2.2 关键实现要点

| 方法 | 说明 | 注意事项 |
|------|------|---------|
| `__init__` | 初始化配置 | 调用 `super().__init__(**kwargs)` 保存配置 |
| `_build_url` | 构建 WebSocket URL | 不同厂商鉴权方式不同，可能需要先获取 Token |
| `recognize` | 单次识别 | 发送完整音频，等待完整结果 |
| `recognize_streaming` | 流式识别 | 边发送音频边接收结果，需要处理数据流控制 |

---

### 步骤 3：在工厂中注册

修改 `app/iat/factory.py`，在 `create_asr_client()` 函数中添加新厂商分支：

```python
# app/iat/factory.py
from app.config import ASR_PROVIDER, ASR_CONFIG


def create_asr_client():
    """
    ASR 客户端工厂函数
    根据配置文件中的 ASR_PROVIDER 创建对应的 ASR 客户端
    """
    provider = ASR_PROVIDER.lower()

    if provider == "tencent":
        from app.iat.tencent import TencentASRClient
        config = ASR_CONFIG.get("tencent", {})
        return TencentASRClient(**config)

    elif provider == "aliyun":
        from app.iat.aliyun import AliyunASRClient
        config = ASR_CONFIG.get("aliyun", {})
        return AliyunASRClient(**config)

    elif provider == "bytedance":
        from app.iat.bytedance import BytedanceASRClient
        config = ASR_CONFIG.get("bytedance", {})
        return BytedanceASRClient(**config)

    elif provider == "xunfei":
        from app.iat.xunfei import XunfeiASRClient
        config = ASR_CONFIG.get("xunfei", {})
        return XunfeiASRClient(**config)

    else:
        raise ValueError(f"Unsupported ASR provider: {ASR_PROVIDER}")
```

**注意**：
- 使用 `elif` 添加新分支
- 配置参数通过 `**config` 解包传入，保持灵活性
- 如果厂商不存在，抛出 `ValueError`

---

### 步骤 4：添加配置文件

修改 `app/config.py`，在 `ASR_CONFIG` 字典中添加阿里云配置：

```python
# app/config.py

# ASR 厂商选择: tencent | aliyun | bytedance | xunfei
ASR_PROVIDER = os.getenv("ASR_PROVIDER", "tencent")

# ASR 配置
ASR_CONFIG = {
    "tencent": {
        "app_id": "1252924679",
        "secret_id": "your_secret_id",
        "secret_key": "your_secret_key",
        "engine_model_type": "16k_zh",
        "voice_format": 1,
        "needvad": 1,
    },
    "aliyun": {
        # 阿里云 ASR 配置
        "app_key": "your_app_key",
        "access_key_id": "your_access_key_id",
        "access_key_secret": "your_access_key_secret",
        "region": "cn-shanghai",
    },
    "bytedance": {
        # 字节跳动 ASR 配置
        "app_id": "",
        "access_token": "",
        "cluster": "volcengine",
    },
    "xunfei": {
        # 讯飞 ASR 配置
        "app_id": "",
        "api_key": "",
        "api_secret": "",
    },
}
```

**配置说明**：
- `ASR_PROVIDER`：当前使用的厂商，修改此值切换厂商
- `ASR_CONFIG`：各厂商的独立配置，键名与 `__init__` 参数名对应

---

### 步骤 5：切换配置并测试

#### 5.1 修改配置

将 `ASR_PROVIDER` 改为 `"aliyun"`：

```python
ASR_PROVIDER = "aliyun"  # 从 tencent 切换到 aliyun
```

或通过环境变量切换（无需修改代码）：

```bash
# Linux/Mac
export ASR_PROVIDER=aliyun

# Windows PowerShell
$env:ASR_PROVIDER="aliyun"
```

#### 5.2 运行测试

```bash
python main.py
```

观察日志输出：
```
ASR client initialized: AliyunASRClient
```

表示已成功切换到阿里云 ASR。

---

## 四、各厂商接口差异对比

| 特性 | 腾讯云 | 阿里云 | 讯飞 | 字节跳动 |
|------|--------|--------|------|---------|
| **协议** | WebSocket | WebSocket | WebSocket | WebSocket |
| **鉴权方式** | HMAC-SHA1 签名 | Token | HMAC-SHA256 签名 | Bearer Token |
| **音频格式** | PCM | PCM | PCM | PCM |
| **采样率** | 16kHz | 16kHz | 16kHz | 16kHz |
| **结果类型** | slice_type (0/1/2) | 中间结果/最终结果 | 中间结果/最终结果 | 中间结果/最终结果 |
| **VAD 支持** | 内置 (needvad=1) | 内置 | 内置 | 内置 |

---

## 五、常见问题

### Q1：如何调试新接入的厂商？

**A**：在 `handler.py` 中 `asr_streaming_task` 会打印 ASR 响应：
```python
print(f"ASR response: {response}")
```

观察日志中的原始响应，确认：
1. 连接是否成功
2. 鉴权是否通过
3. 结果格式是否符合预期

### Q2：厂商的回调数据格式不同怎么办？

**A**：在各自的 `*_asr.py` 中统一转换为标准格式。例如腾讯云返回 `slice_type`，阿里云返回 `RecognitionResultChanged`，都在各自客户端内部处理，对外统一调用 `result_callback(text)`。

### Q3：需要支持厂商特有的高级功能怎么办？

**A**：在 `BaseASRClient` 中添加可选方法（非抽象），子类选择实现：

```python
# base.py
class BaseASRClient(ABC):
    # ... 抽象方法 ...

    async def set_custom_params(self, params: dict):
        """设置厂商特有参数（可选实现）"""
        pass  # 默认空实现

# tencent_asr.py
class TencentASRClient(BaseASRClient):
    async def set_custom_params(self, params: dict):
        self.vad_silence_time = params.get("vad_silence_time", 2000)
```

### Q4：如何同时支持多个厂商（负载均衡）？

**A**：修改工厂函数，支持按权重或策略选择：

```python
def create_asr_client(provider: str = None):
    if provider is None:
        provider = random.choice(["tencent", "aliyun"])  # 随机选择
    # ...
```

---

## 六、完整文件清单

新增阿里云 ASR 后，新增/修改的文件：

```
app/
├── iat/
│   ├── aliyun/                    # 新增目录
│   │   ├── __init__.py            # 新增
│   │   └── aliyun_asr.py          # 新增
│   └── factory.py                 # 修改（添加 aliyun 分支）
├── config.py                      # 修改（添加 aliyun 配置）
└── websocket/
    └── handler.py                 # 无需修改（通过工厂自动适配）
```

---

## 七、参考资源

- [阿里云语音识别官方文档](https://help.aliyun.com/document_detail/84426.html)
- [腾讯云语音识别官方文档](https://cloud.tencent.com/document/product/1093)
- [讯飞开放平台文档](https://www.xfyun.cn/doc/asr/rtasr/API.html)
- [字节跳动火山引擎文档](https://www.volcengine.com/docs/6561)

---

**文档版本**：v1.0
**最后更新**：2026-04-24
