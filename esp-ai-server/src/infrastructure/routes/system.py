"""系统路由

健康检查、指标、统计信息等系统级路由。
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text

from src.infrastructure.logging import get_logger
from src.infrastructure.web import get_device_registry

logger = get_logger(__name__)

router = APIRouter(tags=["system"])


async def _check_db_health() -> bool:
    """检查数据库连通性（执行 SELECT 1）"""
    try:
        from src.infrastructure.db.engine import get_engine
        engine = get_engine()
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            return result.scalar() == 1
    except Exception as e:
        logger.warning(f"[Health] DB check failed: {e}")
        return False


@router.get("/health/live")
async def liveness():
    return {"code": 0, "message": "ok", "data": {"status": "alive"}}


@router.get("/health/ready")
async def readiness(request: Request):
    """就绪检查：验证关键组件（ASR/LLM/TTS 网关 + 数据库）与设备注册表是否初始化完成。"""
    asr_ok = getattr(request.app.state, "asr_gateway", None) is not None
    llm_ok = getattr(request.app.state, "llm_gateway", None) is not None
    tts_ok = getattr(request.app.state, "tts_gateway", None) is not None
    registry_ok = getattr(request.app.state, "device_registry", None) is not None
    db_ok = await _check_db_health()

    components = {
        "asr_gateway": "up" if asr_ok else "down",
        "llm_gateway": "up" if llm_ok else "down",
        "tts_gateway": "up" if tts_ok else "down",
        "database": "up" if db_ok else "down",
        "device_registry": "up" if registry_ok else "down",
    }

    critical_ready = asr_ok and llm_ok and tts_ok and db_ok
    status = "ready" if critical_ready else "not_ready"

    data = {
        "status": status,
        "components": components,
        "critical": ["asr_gateway", "llm_gateway", "tts_gateway", "database"],
    }

    if critical_ready:
        return {"code": 0, "message": "ok", "data": data}
    return JSONResponse(
        status_code=503,
        content={"code": 1, "message": "not ready", "data": data},
    )


@router.get("/metrics")
async def metrics_endpoint():
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    try:
        from src.infrastructure.monitoring import update_pool_metrics
        update_pool_metrics()
    except Exception:
        pass
    content = generate_latest()
    return Response(content=content, media_type=CONTENT_TYPE_LATEST)


@router.get("/stats")
async def get_stats(request: Request):
    stats = {
        "server": {"version": "3.0.0-clean-arch", "architecture": "Clean Architecture"},
        "sessions": {"active": 0},
        "devices": {"total": 0, "online": 0},
        "gateways": {"asr": False, "llm": False, "tts": False},
        "timestamp": time.time(),
    }

    if hasattr(request.app.state, 'device_registry') and request.app.state.device_registry:
        registry = request.app.state.device_registry
        total = registry.count()
        online = 0
        # 在线数：注册表中 channel 仍处于连接状态的设备（与 devices.py 列表口径一致）
        for did in registry.get_all_ids():
            d = registry.get(did)
            if not d:
                continue
            channel = d.get("channel")
            if channel is not None and getattr(channel, "connected", False):
                online += 1
        stats["devices"]["total"] = total
        stats["devices"]["online"] = online

    stats["gateways"]["asr"] = hasattr(request.app.state, 'asr_gateway') and request.app.state.asr_gateway is not None
    stats["gateways"]["llm"] = hasattr(request.app.state, 'llm_gateway') and request.app.state.llm_gateway is not None
    stats["gateways"]["tts"] = hasattr(request.app.state, 'tts_gateway') and request.app.state.tts_gateway is not None

    return {"code": 0, "message": "ok", "data": stats}


@router.get("/api/health")
async def api_health():
    return {"code": 0, "message": "ok", "data": {"status": "healthy"}}