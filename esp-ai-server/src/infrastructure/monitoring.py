"""
Monitoring - 监控指标系统

基于Prometheus实现指标收集和导出
"""
from __future__ import annotations

import time
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

try:
    from prometheus_client import (
        Counter,
        Gauge,
        Histogram,
        Summary,
        CollectorRegistry,
        generate_latest,
        CONTENT_TYPE_LATEST,
        REGISTRY,
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    # 提供空实现以支持无prometheus_client环境运行
    class Counter:
        def __init__(self, *args, **kwargs): pass
        def labels(self, **kw): return self
        def inc(self, amount=1): pass
        def _children(self): return {}
    class Gauge:
        def __init__(self, *args, **kwargs): pass
        def labels(self, **kw): return self
        def inc(self, amount=1): pass
        def dec(self, amount=1): pass
        def set(self, value): pass
        def _children(self): return {}
    class Histogram:
        def __init__(self, *args, **kwargs): pass
        def labels(self, **kw): return self
        def observe(self, amount): pass
        def _children(self): return {}
    class Summary:
        def __init__(self, *args, **kwargs): pass
        def labels(self, **kw): return self
        def observe(self, amount): pass
        def _children(self): return {}
    CollectorRegistry = object
    REGISTRY = None
    def generate_latest(*args, **kwargs): return b""
    CONTENT_TYPE_LATEST = ""


F = TypeVar('F', bound=Callable[..., Any])

# ── 自定义 Histogram buckets（针对语音场景优化） ──
# ASR 延迟：0.1s 到 30s
ASR_BUCKETS = (0.1, 0.25, 0.5, 1, 2, 3, 5, 8, 10, 15, 20, 30)

# LLM 延迟（首 token）：0.05s 到 60s
LLM_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 8, 10, 15, 20, 30, 60)

# TTS 延迟：0.05s 到 10s
TTS_BUCKETS = (0.05, 0.1, 0.2, 0.5, 1, 2, 3, 5, 8, 10)

# Pipeline 延迟：0.5s 到 120s
PIPELINE_BUCKETS = (0.5, 1, 2, 5, 10, 15, 20, 30, 45, 60, 90, 120)

# 会话时长：1s 到 600s
SESSION_BUCKETS = (1, 5, 10, 30, 60, 120, 180, 300, 600)


class MetricsCollector:
    """
    指标收集器

    收集以下类型的指标：
    - Counter: 计数器（只增不减）
    - Gauge: 仪表盘（可增可减）
    - Histogram: 直方图（观察值分布）
    - Summary: 摘要（类似直方图但客户端计算分位数）
    """

    def __init__(self, namespace: str = "espai"):
        self.namespace = namespace
        # 统一使用 prometheus 默认 registry（prometheus_client.REGISTRY）。
        # 这样 /metrics 端点（generate_latest() 默认读取该 registry）能够同时暴露
        # HTTP 指标（来自 instrumentator）和业务指标（来自 track_* 方法）。
        self.registry = REGISTRY if PROMETHEUS_AVAILABLE else None

        def _make(metric_cls, name, documentation, labelnames=None, buckets=None):
            """在默认 registry 上创建指标；若同名指标已注册则复用，避免重复注册报错。

            多次实例化 MetricsCollector（如模块级单例 + 测试用例）时，
            默认 registry 上同名指标已存在会抛 ValueError，此处复用已有实例。

            Args:
                metric_cls: 指标类型（Counter / Gauge / Histogram / Summary）
                name: 指标名称
                documentation: 帮助文档
                labelnames: 标签名称列表
                buckets: Histogram 自定义 bucket 边界（仅对 Histogram 有效）
            """
            # 收集需要透传的关键字参数
            extra_kwargs = {}
            if buckets is not None:
                extra_kwargs["buckets"] = buckets

            if not PROMETHEUS_AVAILABLE:
                # prometheus 不可用：构造未注册实例（显式 registry=None 避免误注册）
                if labelnames is not None:
                    return metric_cls(name, documentation, labelnames, registry=None, **extra_kwargs)
                return metric_cls(name, documentation, registry=None, **extra_kwargs)
            try:
                if labelnames is not None:
                    return metric_cls(name, documentation, labelnames, **extra_kwargs)
                return metric_cls(name, documentation, **extra_kwargs)
            except ValueError:
                # 同名指标已在默认 registry 注册（如全局单例），复用之
                try:
                    return REGISTRY._names_to_collectors[name]
                except Exception:
                    return None

        # ── 会话相关指标 ──
        self.session_active = _make(Gauge, f"{namespace}_session_active", "Current active sessions")
        self.session_total = _make(Counter, f"{namespace}_session_total", "Total sessions created/closed", ["reason"])
        self.session_duration = _make(Histogram, f"{namespace}_session_duration_seconds", "Session duration in seconds", buckets=SESSION_BUCKETS)

        # ── WebSocket相关指标 ──
        self.websocket_connections = _make(Gauge, f"{namespace}_websocket_connections_current", "Current WebSocket connections")
        self.websocket_disconnect_total = _make(Counter, f"{namespace}_websocket_disconnect_total", "Total WebSocket disconnections", ["reason"])
        self.websocket_messages_total = _make(Counter, f"{namespace}_websocket_messages_total", "Total WebSocket messages received", ["type"])

        # ── ASR相关指标 ──
        self.asr_requests_total = _make(Counter, f"{namespace}_asr_requests_total", "Total ASR requests", ["provider", "status"])
        self.asr_duration = _make(Histogram, f"{namespace}_asr_duration_seconds", "ASR processing duration", ["provider"], buckets=ASR_BUCKETS)
        self.asr_audio_queue_size = _make(Gauge, f"{namespace}_asr_audio_queue_size", "ASR audio queue size")

        # ── LLM相关指标 ──
        self.llm_requests_total = _make(Counter, f"{namespace}_llm_requests_total", "Total LLM requests", ["provider", "status"])
        self.llm_tokens_total = _make(Counter, f"{namespace}_llm_tokens_total", "Total tokens processed", ["type"])  # prompt, completion
        self.llm_duration = _make(Histogram, f"{namespace}_llm_duration_seconds", "LLM generation duration", ["provider"], buckets=LLM_BUCKETS)

        # ── TTS相关指标 ──
        self.tts_requests_total = _make(Counter, f"{namespace}_tts_requests_total", "Total TTS requests", ["provider", "status"])
        self.tts_characters_total = _make(Counter, f"{namespace}_tts_characters_total", "Total characters synthesized")
        self.tts_audio_frames_total = _make(Counter, f"{namespace}_tts_audio_frames_total", "Total audio frames generated")
        self.tts_duration = _make(Histogram, f"{namespace}_tts_duration_seconds", "TTS synthesis duration", ["provider"], buckets=TTS_BUCKETS)

        # ── Pipeline相关指标 ──
        self.pipeline_runs_total = _make(Counter, f"{namespace}_pipeline_runs_total", "Total pipeline runs", ["status"])  # completed, interrupted, error
        self.pipeline_interrupt_total = _make(Counter, f"{namespace}_pipeline_interrupt_total", "Total pipeline interrupts")
        self.pipeline_sentences_total = _make(Counter, f"{namespace}_pipeline_sentences_total", "Total sentences processed by pipeline")
        self.pipeline_duration = _make(Histogram, f"{namespace}_pipeline_duration_seconds", "Pipeline total duration", buckets=PIPELINE_BUCKETS)

        # ── VAD（语音活动检测）相关指标 ──
        self.vad_trigger_total = _make(Counter, f"{namespace}_vad_trigger_total", "Total VAD triggers", ["type"])  # silence, final, timeout

        # ── HTTP请求相关指标 ──
        self.http_requests_total = _make(Counter, f"{namespace}_http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"])
        self.http_request_duration = _make(Histogram, f"{namespace}_http_request_duration_seconds", "HTTP request duration", ["method", "endpoint"])
        self.http_request_size = _make(Summary, f"{namespace}_http_request_size_bytes", "HTTP request size in bytes", ["method", "endpoint"])
        self.http_response_size = _make(Summary, f"{namespace}_http_response_size_bytes", "HTTP response size in bytes", ["method", "endpoint", "status"])

        # ── 连接池相关指标 ──
        self.connection_pool_active = _make(Gauge, f"{namespace}_connection_pool_active", "Active connections in pool", ["pool_name"])
        self.connection_pool_idle = _make(Gauge, f"{namespace}_connection_pool_idle", "Idle connections in pool", ["pool_name"])
        self.connection_pool_max = _make(Gauge, f"{namespace}_connection_pool_max", "Max connections in pool", ["pool_name"])

        # ── 错误率指标 ──
        self.error_rate = _make(Gauge, f"{namespace}_error_rate", "Error rate (errors/total) in the last minute", ["component"])

    # ── 会话指标方法 ──

    def track_session_created(self) -> None:
        """跟踪会话创建"""
        self.session_active.inc()
        self.session_total.labels(reason="created").inc()

    def track_session_closed(self, duration: float) -> None:
        """跟踪会话关闭"""
        self.session_active.dec()
        self.session_total.labels(reason="closed").inc()
        self.session_duration.observe(duration)

    # ── WebSocket指标方法 ──

    def track_ws_connection_opened(self) -> None:
        """跟踪WebSocket连接打开"""
        self.websocket_connections.inc()

    def track_ws_connection_closed(self, reason: str = "normal") -> None:
        """跟踪WebSocket连接关闭"""
        self.websocket_connections.dec()
        self.websocket_disconnect_total.labels(reason=reason).inc()

    def track_ws_message_received(self, msg_type: str) -> None:
        """跟踪收到WebSocket消息"""
        self.websocket_messages_total.labels(type=msg_type).inc()

    # ── ASR指标方法 ──

    def track_asr_request(
        self,
        provider: str,
        status: str = "success",
        duration: float = 0.0,
    ) -> None:
        """跟踪ASR请求"""
        self.asr_requests_total.labels(provider=provider, status=status).inc()
        if duration > 0:
            self.asr_duration.labels(provider=provider).observe(duration)

    def set_asr_queue_size(self, size: int) -> None:
        """设置ASR队列大小"""
        self.asr_audio_queue_size.set(size)

    # ── LLM指标方法 ──

    def track_llm_request(
        self,
        provider: str,
        status: str = "success",
        duration: float = 0.0,
    ) -> None:
        """跟踪LLM请求"""
        self.llm_requests_total.labels(provider=provider, status=status).inc()
        if duration > 0:
            self.llm_duration.labels(provider=provider).observe(duration)

    def track_llm_tokens(self, token_type: str, count: int) -> None:
        """跟踪Token使用量"""
        self.llm_tokens_total.labels(type=token_type).inc(count)

    # ── TTS指标方法 ──

    def track_tts_request(
        self,
        provider: str,
        status: str = "success",
        duration: float = 0.0,
    ) -> None:
        """跟踪TTS请求"""
        self.tts_requests_total.labels(provider=provider, status=status).inc()
        if duration > 0:
            self.tts_duration.labels(provider=provider).observe(duration)

    def track_tts_characters(self, count: int) -> None:
        """跟踪合成字符数"""
        self.tts_characters_total.inc(count)

    def track_tts_frame(self) -> None:
        """跟踪音频帧生成"""
        self.tts_audio_frames_total.inc()

    # ── Pipeline指标方法 ──

    def track_pipeline_run(self, status: str, duration: float = 0.0) -> None:
        """跟踪Pipeline执行"""
        self.pipeline_runs_total.labels(status=status).inc()
        if duration > 0:
            self.pipeline_duration.observe(duration)

    def track_pipeline_interrupt(self) -> None:
        """跟踪Pipeline中断"""
        self.pipeline_interrupt_total.inc()

    def track_pipeline_sentence(self) -> None:
        """跟踪句子处理"""
        self.pipeline_sentences_total.inc()

    # ── VAD指标方法 ──

    def track_vad_trigger(self, trigger_type: str) -> None:
        """跟踪VAD触发"""
        self.vad_trigger_total.labels(type=trigger_type).inc()

    # ── HTTP指标方法 ──

    def track_http_request(
        self,
        method: str,
        endpoint: str,
        status_code: int,
        duration: float = 0.0,
    ) -> None:
        """跟踪HTTP请求"""
        self.http_requests_total.labels(
            method=method,
            endpoint=endpoint,
            status=str(status_code),
        ).inc()
        if duration > 0:
            self.http_request_duration.labels(
                method=method,
                endpoint=endpoint,
            ).observe(duration)

    def get_metrics(self) -> bytes:
        """获取Prometheus格式的指标"""
        if PROMETHEUS_AVAILABLE and self.registry:
            return generate_latest(self.registry)
        return b""

    # ── 连接池指标方法 ──

    def update_connection_pool(
        self,
        pool_name: str,
        active: int,
        idle: int,
        max_size: int,
    ) -> None:
        """更新连接池使用率指标

        Args:
            pool_name: 连接池名称（如 ``"http"``、``"db"``）
            active: 当前活跃连接数
            idle: 当前空闲连接数
            max_size: 连接池最大容量
        """
        self.connection_pool_active.labels(pool_name=pool_name).set(active)
        self.connection_pool_idle.labels(pool_name=pool_name).set(idle)
        self.connection_pool_max.labels(pool_name=pool_name).set(max_size)

    # ── 错误率指标方法 ──

    def set_error_rate(self, component: str, rate: float) -> None:
        """设置指定组件的最近一分钟错误率

        Args:
            component: 组件名（如 ``"asr"``、``"llm"``、``"tts"``、``"pipeline"``）
            rate: 错误率（0.0 ~ 1.0），errors / total
        """
        self.error_rate.labels(component=component).set(rate)


class PrometheusMetrics:
    """
    Prometheus指标集成

    用于FastAPI的Prometheus中间件集成
    """

    def __init__(self, metrics: MetricsCollector = None):
        self.metrics = metrics or MetricsCollector()

    def instrumentator(self, app: Any) -> Any:
        """
        创建FastAPI Instrumentator

        Args:
            app: FastAPI应用实例

        Returns:
            配置好的Instrumentator实例
        """
        if not PROMETHEUS_AVAILABLE:
            return None

        try:
            from prometheus_fastapi_instrumentator import Instrumentator

            instrumentator = Instrumentator(
                should_group_status_codes=True,
                should_ignore_untemplated=True,
                should_instrument_requests_inprogress=True,
                excluded_handlers=["/metrics"],
            )

            instrumentator.instrument(app).expose(
                app,
                endpoint="/metrics",
                include_in_schema=True,
            )

            return instrumentator
        except ImportError:
            return None


def track_time(metric_name: str = "", labels: dict = None):
    """
    装饰器：跟踪函数执行时间并记录到 Histogram

    通过 ``_get_metric(metric_name)`` 在全局 MetricsCollector 上查找同名属性，
    找到后调用 ``observe(duration)`` 记录耗时。支持 ``labels`` 透传。

    Args:
        metric_name: MetricsCollector 上的属性名（如 ``"asr_duration"``）
        labels: 可选的标签键值对，如 ``{"provider": "volcengine"}``

    Returns:
        装饰后的函数

    Example::

        @track_time("asr_duration", labels={"provider": "volcengine"})
        async def recognize(audio: bytes) -> str:
            ...
    """
    def decorator(func: F) -> F:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.monotonic()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = time.monotonic() - start
                metric = _get_metric(metric_name) if metric_name else None
                if metric and hasattr(metric, "observe"):
                    try:
                        if labels:
                            metric.labels(**labels).observe(duration)
                        else:
                            metric.observe(duration)
                    except Exception:
                        pass

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.monotonic()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.monotonic() - start
                metric = _get_metric(metric_name) if metric_name else None
                if metric and hasattr(metric, "observe"):
                    try:
                        if labels:
                            metric.labels(**labels).observe(duration)
                        else:
                            metric.observe(duration)
                    except Exception:
                        pass

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        else:
            return sync_wrapper  # type: ignore

    return decorator


# 全局单例
_global_metrics: Optional[MetricsCollector] = None


def get_metrics() -> MetricsCollector:
    """
    获取全局指标收集器

    Returns:
        MetricsCollector实例
    """
    global _global_metrics
    if _global_metrics is None:
        _global_metrics = MetricsCollector()
    return _global_metrics


# 便捷的模块级访问器（向后兼容）
def _get_metric(name: str):
    """获取指定指标的便捷方法"""
    metrics = get_metrics()
    return getattr(metrics, name, None)


# 常用指标的快捷引用（方便直接导入使用）
ACTIVE_SESSIONS = get_metrics().session_active
SESSION_DURATION = get_metrics().session_duration
SESSION_TOTAL = get_metrics().session_total

LLM_COMPLETION_DURATION = get_metrics().llm_duration
LLM_COMPLETION_TOTAL = get_metrics().llm_requests_total
if PROMETHEUS_AVAILABLE:
    try:
        LLM_FIRST_TOKEN_LATENCY = Histogram(
            "espai_llm_first_token_latency_seconds",
            "LLM first token latency",
            buckets=LLM_BUCKETS,
        )
    except ValueError:
        LLM_FIRST_TOKEN_LATENCY = REGISTRY._names_to_collectors.get(  # type: ignore[union-attr]
            "espai_llm_first_token_latency_seconds"
        )
else:
    LLM_FIRST_TOKEN_LATENCY = Histogram(
        "espai_llm_first_token_latency_seconds",
        "LLM first token latency",
        buckets=LLM_BUCKETS,
    )
LLM_TOKEN_USAGE = get_metrics().llm_tokens_total

TTS_SYNTHESIZE_DURATION = get_metrics().tts_duration
TTS_SYNTHESIZE_TOTAL = get_metrics().tts_requests_total
if PROMETHEUS_AVAILABLE:
    try:
        TTS_AUDIO_LENGTH = Histogram(
            "espai_tts_audio_length_seconds",
            "TTS audio length in seconds",
            buckets=TTS_BUCKETS,
        )
    except ValueError:
        TTS_AUDIO_LENGTH = REGISTRY._names_to_collectors.get(  # type: ignore[union-attr]
            "espai_tts_audio_length_seconds"
        )
else:
    TTS_AUDIO_LENGTH = Histogram(
        "espai_tts_audio_length_seconds",
        "TTS audio length in seconds",
        buckets=TTS_BUCKETS,
    )

PIPELINE_DURATION = get_metrics().pipeline_duration
PIPELINE_TOTAL = get_metrics().pipeline_runs_total

# 连接池指标快捷引用
CONNECTION_POOL_ACTIVE = get_metrics().connection_pool_active
CONNECTION_POOL_IDLE = get_metrics().connection_pool_idle
CONNECTION_POOL_MAX = get_metrics().connection_pool_max

# 错误率指标快捷引用
ERROR_RATE = get_metrics().error_rate


def update_pool_metrics() -> None:
    """采集并更新所有连接池的使用率指标。

    在 ``/metrics`` 端点被访问时调用，遍历已注册的连接池实例，
    将 active / idle / max 信息写入对应的 Gauge。
    """
    metrics = get_metrics()
    try:
        from src.infrastructure.connection_pool import get_pool_manager

        manager = get_pool_manager()
        if not manager:
            return

        stats = manager.get_stats()
        # stats 是 {pool_name: {active_count, idle_count, max_size, ...}}
        if isinstance(stats, dict):
            iterable = stats.items()
        else:
            iterable = ((s.get("pool_name", s.get("name", "unknown")), s) for s in stats)

        for pool_name, info in iterable:
            if isinstance(info, dict):
                metrics.update_connection_pool(
                    pool_name=str(pool_name),
                    active=int(info.get("active_count", info.get("active", 0))),
                    idle=int(info.get("idle_count", info.get("idle", 0))),
                    max_size=int(info.get("max_size", info.get("max", 0))),
                )
    except Exception:
        # 连接池模块不可用或未初始化时静默跳过，不影响 /metrics 输出
        pass


__all__ = [
    "MetricsCollector",
    "PrometheusMetrics",
    "track_time",
    "get_metrics",
    "update_pool_metrics",
    # 自定义 buckets
    "ASR_BUCKETS",
    "LLM_BUCKETS",
    "TTS_BUCKETS",
    "PIPELINE_BUCKETS",
    "SESSION_BUCKETS",
    # 便捷常量
    "ACTIVE_SESSIONS",
    "SESSION_DURATION",
    "SESSION_TOTAL",
    "LLM_COMPLETION_DURATION",
    "LLM_COMPLETION_TOTAL",
    "LLM_FIRST_TOKEN_LATENCY",
    "LLM_TOKEN_USAGE",
    "TTS_SYNTHESIZE_DURATION",
    "TTS_SYNTHESIZE_TOTAL",
    "TTS_AUDIO_LENGTH",
    "PIPELINE_DURATION",
    "PIPELINE_TOTAL",
    "CONNECTION_POOL_ACTIVE",
    "CONNECTION_POOL_IDLE",
    "CONNECTION_POOL_MAX",
    "ERROR_RATE",
]
