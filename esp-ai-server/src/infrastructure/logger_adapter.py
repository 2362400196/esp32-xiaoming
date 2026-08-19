"""Logger Adapter - 实现 LoggerPort 接口"""
from __future__ import annotations

import logging

from src.use_cases.ports import LoggerPort


class LoggingLoggerAdapter(LoggerPort):
    """通过标准 logging 模块实现 LoggerPort"""

    def __init__(self, name: str = __name__):
        self._logger = logging.getLogger(name)

    def info(self, msg: str, *args, **kwargs) -> None:
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs) -> None:
        self._logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs) -> None:
        self._logger.error(msg, *args, **kwargs)

    def debug(self, msg: str, *args, **kwargs) -> None:
        self._logger.debug(msg, *args, **kwargs)
