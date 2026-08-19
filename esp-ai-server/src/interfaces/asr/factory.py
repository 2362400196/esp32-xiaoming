from __future__ import annotations

from src.infrastructure.config import get_settings
from src.interfaces.asr.aliyun import AliYunASRGateway
from src.interfaces.asr.base import BaseASRGateway
from src.interfaces.asr.tencent import TencentASRGateway
from src.interfaces.asr.volcengine import VolcEngineASRGateway
from src.interfaces.asr.xunfei import XunfeiASRGateway


def create_asr_gateway(provider: str = None, config: dict = None) -> BaseASRGateway:
    settings = get_settings()
    provider = (provider or settings.asr.provider).lower()
    config = config or {}

    if provider == "tencent":
        tencent_config = {
            "app_id": config.get("app_id") or settings.asr.tencent_app_id,
            "secret_id": config.get("secret_id") or settings.asr.tencent_secret_id,
            "secret_key": config.get("secret_key") or settings.asr.tencent_secret_key,
            "engine_model_type": config.get("engine_model_type") or settings.asr.tencent_engine,
        }
        return TencentASRGateway(tencent_config)

    elif provider in ("bytedance", "volcengine"):
        volcengine_config = {
            "api_key": config.get("api_key") or settings.asr.volcengine_api_key,
            "resource_id": config.get("resource_id") or settings.asr.volcengine_resource_id,
            "model_name": config.get("model_name") or settings.asr.volcengine_model,
        }
        return VolcEngineASRGateway(volcengine_config)

    elif provider == "aliyun":
        aliyun_config = {
            "access_key_id": config.get("access_key_id") or settings.asr.aliyun_access_key_id,
            "access_key_secret": config.get("access_key_secret") or settings.asr.aliyun_access_key_secret,
            "app_key": config.get("app_key") or settings.asr.aliyun_app_key,
        }
        return AliYunASRGateway(aliyun_config)

    elif provider == "xunfei":
        xunfei_config = {
            "app_id": config.get("app_id") or settings.asr.xunfei_app_id,
            "api_key": config.get("api_key") or settings.asr.xunfei_api_key,
            "api_secret": config.get("api_secret") or settings.asr.xunfei_api_secret,
        }
        return XunfeiASRGateway(xunfei_config)

    else:
        raise ValueError(f"Unsupported ASR provider: {provider}")
