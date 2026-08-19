"""ASR 网关模块

按 provider 拆分：
- base.py: BaseASRGateway 基类及共享 logger
- tencent.py: 腾讯云 ASR
- volcengine.py: 火山引擎 ASR（含 VolcEngineASRConnectionPool）
- aliyun.py: 阿里云 ASR
- xunfei.py: 讯飞 ASR
- factory.py: create_asr_gateway 工厂函数
"""
from src.interfaces.asr.aliyun import AliYunASRGateway
from src.interfaces.asr.base import BaseASRGateway
from src.interfaces.asr.factory import create_asr_gateway
from src.interfaces.asr.tencent import TencentASRGateway
from src.interfaces.asr.volcengine import VolcEngineASRConnectionPool, VolcEngineASRGateway
from src.interfaces.asr.xunfei import XunfeiASRGateway

__all__ = [
    "BaseASRGateway",
    "TencentASRGateway",
    "VolcEngineASRGateway",
    "AliYunASRGateway",
    "XunfeiASRGateway",
    "VolcEngineASRConnectionPool",
    "create_asr_gateway",
]
