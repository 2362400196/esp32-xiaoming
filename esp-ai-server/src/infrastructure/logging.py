"""
Logging - 日志系统

提供结构化日志记录功能，支持彩色控制台输出和JSON格式
"""
from __future__ import annotations

import contextvars
import json
import logging
import sys
from contextlib import suppress
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

try:
    import colorama
    colorama.init()
except ImportError:
    pass


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")
session_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("session_id", default="")
device_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("device_id", default="")


class _TraceFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = trace_id_var.get() or "-"
        record.session_id = session_id_var.get() or "-"
        record.device_id = device_id_var.get() or "-"
        return True


class ColoredFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        record.timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        if isinstance(record.msg, str):
            with suppress(Exception):
                record.msg = record.msg.encode("utf-8", errors="replace").decode("utf-8")
        log_message = super().format(record)
        levelname = record.levelname
        if levelname in self.COLORS:
            log_message = f"{self.COLORS[levelname]}{log_message}{self.RESET}"
        return log_message


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "msg": record.getMessage(),
            "name": record.name,
            "trace_id": getattr(record, "trace_id", "-"),
            "session_id": getattr(record, "session_id", "-"),
            "device_id": getattr(record, "device_id", "-"),
        }
        if record.exc_info and record.exc_info[1]:
            log_obj["exception"] = str(record.exc_info[1])
        return json.dumps(log_obj, ensure_ascii=False)


class StructuredLogger:
    def __init__(
        self,
        name: str = "esp_ai",
        level: LogLevel = LogLevel.INFO,
        log_format: str = "console",
        file_path: Optional[str] = None,
        console_output: bool = True,
    ):
        self.name = name
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, level.value))
        self.logger.propagate = False

        self.logger.handlers.clear()

        if console_output:
            if hasattr(sys.stdout, "reconfigure"):
                with suppress(Exception):
                    sys.stdout.reconfigure(encoding="utf-8")

            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(getattr(logging, level.value))
            console_handler.addFilter(_TraceFilter())

            if log_format == "json":
                formatter = JsonFormatter()
            else:
                formatter = ColoredFormatter(
                    "[%(timestamp)s] [%(levelname)s] [%(trace_id)s|%(session_id)s|%(device_id)s] %(message)s"
                )

            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)

        if file_path:
            self._setup_file_handler(file_path, level)

    def _setup_file_handler(
        self,
        file_path: str,
        level: LogLevel,
        max_size: int = 10 * 1024 * 1024,
        backup_count: int = 5,
    ) -> None:
        from logging.handlers import RotatingFileHandler

        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            filename=str(path),
            maxBytes=max_size,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(getattr(logging, level.value))
        file_handler.addFilter(_TraceFilter())

        formatter = JsonFormatter()
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

    def debug(self, msg: str, *args, **kwargs) -> None:
        self.logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs) -> None:
        self.logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs) -> None:
        self.logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs) -> None:
        self.logger.error(msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs) -> None:
        self.logger.critical(msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs) -> None:
        self.logger.exception(msg, *args, **kwargs)

    def set_context(
        self,
        trace_id: str = "",
        session_id: str = "",
        device_id: str = "",
    ) -> None:
        if trace_id:
            trace_id_var.set(trace_id)
        if session_id:
            session_id_var.set(session_id)
        if device_id:
            device_id_var.set(device_id)


_loggers: dict[str, StructuredLogger] = {}


def setup_logging(
    level: LogLevel = LogLevel.INFO,
    log_format: str = "console",
    file_path: Optional[str] = None,
    debug: bool = False,
) -> StructuredLogger:
    if debug:
        level = LogLevel.DEBUG

    logger = StructuredLogger(
        name="esp_ai",
        level=level,
        log_format=log_format,
        file_path=file_path,
    )
    _loggers["esp_ai"] = logger

    _root = logging.getLogger()
    if _root.handlers:
        _root.handlers.clear()
        _root.addHandler(logging.NullHandler())

    return logger


def get_logger(name: str = "esp_ai") -> StructuredLogger:
    if name not in _loggers:
        _loggers[name] = StructuredLogger(name=name)
    return _loggers[name]


def set_trace_id(trace_id: str) -> None:
    trace_id_var.set(trace_id)


def set_session_id(session_id: str) -> None:
    session_id_var.set(session_id)


def set_device_id(device_id: str) -> None:
    device_id_var.set(device_id)


def debug(msg: str) -> None:
    get_logger().debug(msg)

def info(msg: str) -> None:
    get_logger().info(msg)

def warning(msg: str) -> None:
    get_logger().warning(msg)

def error(msg: str) -> None:
    get_logger().error(msg)


__all__ = [
    "StructuredLogger",
    "setup_logging",
    "get_logger",
    "set_trace_id",
    "set_session_id",
    "set_device_id",
    "LogLevel",
    "ColoredFormatter",
    "JsonFormatter",
    "debug",
    "info",
    "warning",
    "error",
    "trace_id_var",
    "session_id_var",
    "device_id_var",
]
