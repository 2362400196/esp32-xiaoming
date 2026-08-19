"""System Management Routes"""
from __future__ import annotations

import time

from fastapi import Header, APIRouter, Request

from src.infrastructure.device_api import (
    DeviceControlResponse, DeviceListResponse,
    verify_api_key, get_device_registry,
)
from src.infrastructure.config import get_settings
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["system-management"])

@router.get("/system/info", response_model=DeviceListResponse)
async def get_system_info(request: Request) -> DeviceListResponse:
    """获取系统信息"""
    await verify_api_key(request)

    settings = get_settings()
    registry = get_device_registry()

    info = {
        "version": "3.0.0-clean-arch",
        "architecture": "Clean Architecture",
        "uptime": time.time(),
        "server": {
            "host": settings.server.host,
            "port": settings.server.port,
            "workers": settings.server.workers,
        },
        "devices": {
            "online": registry.count() if registry else 0,
        },
        "features": {
            "auth_enabled": settings.auth.enabled,
            "remote_config_enabled": getattr(settings, "remote_config_enabled", False),
            "mcp_enabled": bool(settings.mcp.servers_json),
        }
    }

    return DeviceListResponse(code=0, message="ok", data=info)


@router.get("/system/config", response_model=DeviceListResponse)
async def get_system_config(request: Request) -> DeviceListResponse:
    """获取系统配置（脱敏）"""
    await verify_api_key(request)

    settings = get_settings()

    config = {
        "server": {
            "host": settings.server.host,
            "port": settings.server.port,
        },
        "asr": {
            "provider": settings.asr.provider,
            "no_speech_timeout": settings.asr.no_speech_timeout,
            "silence_timeout": settings.asr.silence_timeout,
            "enable_pool": settings.asr.enable_pool,
        },
        "llm": {
            "provider": settings.llm.provider,
            "model": settings.llm.model,
            "base_url": settings.llm.base_url,
            "temperature": settings.llm.temperature,
            "memory_enabled": settings.llm.memory_enabled,
        },
        "tts": {
            "provider": settings.tts.provider,
            "voice_type": settings.tts.voice_type,
            "speed_ratio": settings.tts.speed_ratio,
            "enable_pool": settings.tts.enable_pool,
        },
        "wakeup": {
            "enable_audio": settings.wakeup.enable_audio,
            "text": settings.wakeup.text[:20] + "..." if len(settings.wakeup.text) > 20 else settings.wakeup.text,
        },
    }

    return DeviceListResponse(code=0, message="ok", data=config)


@router.get("/system/gateways", response_model=DeviceListResponse)
async def get_gateways_status(request: Request) -> DeviceListResponse:
    """获取网关状态"""
    await verify_api_key(request)

    from src.infrastructure.web import get_app
    app = get_app()
    if app is None:
        return DeviceListResponse(code=1, message="App not initialized", data=None)

    status = {
        "asr": {
            "enabled": hasattr(app.state, 'asr_gateway') and app.state.asr_gateway is not None,
            "provider": getattr(app.state, 'asr_gateway', None).__class__.__name__ if hasattr(app.state, 'asr_gateway') else None,
        },
        "llm": {
            "enabled": hasattr(app.state, 'llm_gateway') and app.state.llm_gateway is not None,
            "provider": getattr(app.state, 'llm_gateway', None).__class__.__name__ if hasattr(app.state, 'llm_gateway') else None,
        },
        "tts": {
            "enabled": hasattr(app.state, 'tts_gateway') and app.state.tts_gateway is not None,
            "provider": getattr(app.state, 'tts_gateway', None).__class__.__name__ if hasattr(app.state, 'tts_gateway') else None,
        },
    }

    return DeviceListResponse(code=0, message="ok", data=status)


@router.post("/system/reload", response_model=DeviceControlResponse)
async def reload_config(request: Request) -> DeviceControlResponse:
    """重新加载配置"""
    await verify_api_key(request)

    try:
        from src.infrastructure.config import reset_settings
        reset_settings()

        auth_service = None
        try:
            from src.infrastructure.web import get_app
            _app = get_app()
            auth_service = getattr(_app.state, 'auth_service', None) if _app else None
        except Exception as e:
            logger.debug(f"[DeviceAPI] 获取 auth_service 失败: {e}")

        if auth_service and hasattr(auth_service, 'reload_users_config'):
            auth_service.reload_users_config()

        logger.info("[DeviceAPI] Config reloaded")
        return DeviceControlResponse(code=0, message="Config reloaded", data={"timestamp": time.time()})
    except Exception as e:
        return DeviceControlResponse(code=1, message=f"Reload failed: {str(e)}", data=None)


@router.get("/system/metrics", response_model=DeviceListResponse)
async def get_performance_metrics(request: Request) -> DeviceListResponse:
    """
    获取性能指标（支持500+并发监控）
    
    返回：
    - 设备统计
    - 连接池统计
    - 并发控制状态
    - 内存使用情况
    """
    await verify_api_key(request)

    from src.infrastructure.web import get_app
    app = get_app()
    if app is None:
        return DeviceListResponse(code=1, message="App not initialized", data=None)
    from src.infrastructure.concurrency import get_stats as get_concurrency_stats
    from src.infrastructure.connection_pool import PoolManager

    device_registry = getattr(app.state, 'device_registry', None)
    device_stats = device_registry.get_stats() if device_registry else {}

    pool_stats = PoolManager.get_all_stats()
    concurrency_stats = get_concurrency_stats()

    import psutil
    import os
    process = psutil.Process(os.getpid())
    memory_info = process.memory_info()

    metrics = {
        "devices": device_stats,
        "pools": pool_stats,
        "concurrency": concurrency_stats,
        "system": {
            "cpu_percent": process.cpu_percent(interval=0.1),
            "memory_mb": memory_info.rss / 1024 / 1024,
            "memory_percent": process.memory_percent(),
            "num_threads": process.num_threads(),
        },
        "uptime": time.time(),
    }

    return DeviceListResponse(code=0, message="ok", data=metrics)
