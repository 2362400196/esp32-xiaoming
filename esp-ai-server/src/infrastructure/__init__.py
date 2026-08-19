"""
Infrastructure - Core infrastructure components

This module contains:
- Config: Application configuration management
- Logging: Structured logging with context
- Monitoring: Prometheus metrics collection
- Auth: Authentication and authorization
- RemoteConfig: Remote configuration provider
- Web: FastAPI application and routes
- Connection Pool: Generic connection pooling
"""

__all__ = [
    "get_settings",
    "Settings",
    "get_logger",
    "StructuredLogger",
    "MetricsCollector",
    "RemoteConfigProvider",
    "get_remote_config_provider",
    "create_app",
    "lifespan",
    "ConnectionPoolBase",
    "ConnectionWrapper",
]


def __getattr__(name):
    if name == "get_settings":
        from src.infrastructure.config import get_settings
        return get_settings
    elif name == "Settings":
        from src.infrastructure.config import Settings
        return Settings
    elif name == "get_logger":
        from src.infrastructure.logging import get_logger
        return get_logger
    elif name == "StructuredLogger":
        from src.infrastructure.logging import StructuredLogger
        return StructuredLogger
    elif name == "MetricsCollector":
        from src.infrastructure.monitoring import MetricsCollector
        return MetricsCollector
    elif name == "RemoteConfigProvider":
        from src.infrastructure.remote_config import RemoteConfigProvider
        return RemoteConfigProvider
    elif name == "get_remote_config_provider":
        from src.infrastructure.remote_config import get_remote_config_provider
        return get_remote_config_provider
    elif name == "create_app":
        from src.infrastructure.web import create_app
        return create_app
    elif name == "lifespan":
        from src.infrastructure.web import lifespan
        return lifespan
    elif name == "ConnectionPoolBase":
        from src.infrastructure.connection_pool import ConnectionPoolBase
        return ConnectionPoolBase
    elif name == "ConnectionWrapper":
        from src.infrastructure.connection_pool import ConnectionWrapper
        return ConnectionWrapper
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
