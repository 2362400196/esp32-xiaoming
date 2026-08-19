"""
Logging 日志系统单元测试
- StructuredLogger
- ColoredFormatter
- JsonFormatter
- 上下文变量 (trace_id, session_id, device_id)
- 日志级别
"""
import io
import json
import logging
import pytest
from unittest.mock import patch, MagicMock
from src.infrastructure.logging import (
    StructuredLogger,
    ColoredFormatter,
    JsonFormatter,
    LogLevel,
    setup_logging,
    get_logger,
    set_trace_id,
    set_session_id,
    set_device_id,
    trace_id_var,
    session_id_var,
    device_id_var,
)


class TestLogLevel:
    """LogLevel 枚举测试"""

    def test_log_level_values(self):
        assert LogLevel.DEBUG.value == "DEBUG"
        assert LogLevel.INFO.value == "INFO"
        assert LogLevel.WARNING.value == "WARNING"
        assert LogLevel.ERROR.value == "ERROR"
        assert LogLevel.CRITICAL.value == "CRITICAL"

    def test_log_level_is_string_enum(self):
        assert isinstance(LogLevel.INFO, str)


class TestColoredFormatter:
    """彩色格式化器测试"""

    def test_format_adds_color_for_info(self):
        formatter = ColoredFormatter("%(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        assert "Test message" in formatted
        assert "\033[32m" in formatted  # Green for INFO

    def test_format_adds_color_for_warning(self):
        formatter = ColoredFormatter("%(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="Warning message",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        assert "Warning message" in formatted
        assert "\033[33m" in formatted  # Yellow for WARNING

    def test_format_adds_color_for_error(self):
        formatter = ColoredFormatter("%(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="Error message",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        assert "Error message" in formatted
        assert "\033[31m" in formatted  # Red for ERROR

    def test_format_adds_color_for_debug(self):
        formatter = ColoredFormatter("%(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.DEBUG,
            pathname="",
            lineno=0,
            msg="Debug message",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        assert "Debug message" in formatted
        assert "\033[36m" in formatted  # Cyan for DEBUG

    def test_format_adds_timestamp(self):
        formatter = ColoredFormatter("%(timestamp)s %(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        assert hasattr(record, "timestamp")
        assert "Test" in formatted


class TestJsonFormatter:
    """JSON 格式化器测试"""

    def test_format_returns_json(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        data = json.loads(formatted)
        assert data["msg"] == "Test message"
        assert data["level"] == "INFO"
        assert data["name"] == "test_logger"

    def test_format_includes_trace_id(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test",
            args=(),
            exc_info=None,
        )
        record.trace_id = "trace123"
        formatted = formatter.format(record)
        data = json.loads(formatted)
        assert data["trace_id"] == "trace123"

    def test_format_includes_session_id(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test",
            args=(),
            exc_info=None,
        )
        record.session_id = "sess123"
        formatted = formatter.format(record)
        data = json.loads(formatted)
        assert data["session_id"] == "sess123"

    def test_format_includes_exception(self):
        formatter = JsonFormatter()
        try:
            raise ValueError("Test error")
        except ValueError:
            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname="",
                lineno=0,
                msg="Error occurred",
                args=(),
                exc_info=logging.sys.exc_info(),
            )
        formatted = formatter.format(record)
        data = json.loads(formatted)
        assert "exception" in data
        assert "Test error" in data["exception"]


class TestContextVariables:
    """上下文变量测试"""

    @pytest.fixture(autouse=True)
    def _reset_contextvars(self):
        """每个测试前后保存/恢复 contextvar，防止泄漏污染其他测试模块"""
        tok_t = trace_id_var.set("")
        tok_s = session_id_var.set("")
        tok_d = device_id_var.set("")
        yield
        trace_id_var.reset(tok_t)
        session_id_var.reset(tok_s)
        device_id_var.reset(tok_d)

    def test_trace_id_default(self):
        assert trace_id_var.get() == ""

    def test_session_id_default(self):
        assert session_id_var.get() == ""

    def test_device_id_default(self):
        assert device_id_var.get() == ""

    def test_set_trace_id(self):
        set_trace_id("trace123")
        assert trace_id_var.get() == "trace123"

    def test_set_session_id(self):
        set_session_id("session456")
        assert session_id_var.get() == "session456"

    def test_set_device_id(self):
        set_device_id("device789")
        assert device_id_var.get() == "device789"


class TestStructuredLogger:
    """StructuredLogger 测试"""

    @pytest.fixture(autouse=True)
    def _reset_contextvars(self):
        """每个测试前后保存/恢复 contextvar，防止 set_context 泄漏"""
        tok_t = trace_id_var.set("")
        tok_s = session_id_var.set("")
        tok_d = device_id_var.set("")
        yield
        trace_id_var.reset(tok_t)
        session_id_var.reset(tok_s)
        device_id_var.reset(tok_d)

    def test_create_logger(self):
        logger = StructuredLogger(name="test")
        assert logger.name == "test"
        assert isinstance(logger.logger, logging.Logger)

    def test_logger_level(self):
        logger = StructuredLogger(name="test", level=LogLevel.DEBUG)
        assert logger.logger.level == logging.DEBUG

    def test_logger_has_handlers(self):
        logger = StructuredLogger(name="test", console_output=True)
        assert len(logger.logger.handlers) > 0

    def test_debug_method(self):
        logger = StructuredLogger(name="test_debug", level=LogLevel.DEBUG)
        with patch.object(logger.logger, "debug") as mock_debug:
            logger.debug("Debug message")
            mock_debug.assert_called_once_with("Debug message")

    def test_info_method(self):
        logger = StructuredLogger(name="test_info")
        with patch.object(logger.logger, "info") as mock_info:
            logger.info("Info message")
            mock_info.assert_called_once_with("Info message")

    def test_warning_method(self):
        logger = StructuredLogger(name="test_warning")
        with patch.object(logger.logger, "warning") as mock_warning:
            logger.warning("Warning message")
            mock_warning.assert_called_once_with("Warning message")

    def test_error_method(self):
        logger = StructuredLogger(name="test_error")
        with patch.object(logger.logger, "error") as mock_error:
            logger.error("Error message")
            mock_error.assert_called_once_with("Error message")

    def test_exception_method(self):
        logger = StructuredLogger(name="test_exception")
        with patch.object(logger.logger, "exception") as mock_exception:
            logger.exception("Exception message")
            mock_exception.assert_called_once_with("Exception message")

    def test_set_context(self):
        logger = StructuredLogger(name="test_context")
        # 捕获 token 以便测试后重置，避免 contextvar 泄漏污染其他测试
        tok_t = trace_id_var.set("")
        tok_s = session_id_var.set("")
        tok_d = device_id_var.set("")
        try:
            logger.set_context(trace_id="t1", session_id="s1", device_id="d1")
            assert trace_id_var.get() == "t1"
            assert session_id_var.get() == "s1"
            assert device_id_var.get() == "d1"
        finally:
            trace_id_var.reset(tok_t)
            session_id_var.reset(tok_s)
            device_id_var.reset(tok_d)

    def test_set_context_partial(self):
        logger = StructuredLogger(name="test_partial")
        tok_t = trace_id_var.set("original")
        try:
            logger.set_context(session_id="new_session")
            assert trace_id_var.get() == "original"
            assert session_id_var.get() == "new_session"
        finally:
            trace_id_var.reset(tok_t)


class TestSetupLogging:
    """setup_logging 函数测试"""

    def test_setup_logging_returns_structured_logger(self):
        logger = setup_logging(level=LogLevel.INFO)
        assert isinstance(logger, StructuredLogger)

    def test_setup_logging_with_debug(self):
        logger = setup_logging(debug=True)
        assert logger.logger.level == logging.DEBUG

    def test_setup_logging_json_format(self):
        logger = setup_logging(log_format="json")
        assert len(logger.logger.handlers) > 0


class TestGetLogger:
    """get_logger 函数测试"""

    def test_get_logger_returns_structured_logger(self):
        logger = get_logger("test_module")
        assert isinstance(logger, StructuredLogger)

    def test_get_logger_returns_same_instance(self):
        logger1 = get_logger("same_module")
        logger2 = get_logger("same_module")
        assert logger1 is logger2

    def test_get_logger_default_name(self):
        logger = get_logger()
        assert logger.name == "esp_ai"
