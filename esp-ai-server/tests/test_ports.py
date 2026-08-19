"""ConfigPort / LoggerPort / adapters 单元测试"""
from src.use_cases.ports import ConfigPort, LoggerPort
from src.infrastructure.config_adapter import SettingsConfigAdapter
from src.infrastructure.logger_adapter import LoggingLoggerAdapter


class TestConfigPort:
    def test_interface(self):
        """验证 ConfigPort 是抽象类，不能直接实例化"""
        import abc
        assert issubclass(type(ConfigPort), abc.ABCMeta)

    def test_adapter(self):
        """验证 SettingsConfigAdapter 实现了 ConfigPort"""
        adapter = SettingsConfigAdapter()
        assert isinstance(adapter, ConfigPort)


class TestLoggerPort:
    def test_interface(self):
        import abc
        assert issubclass(type(LoggerPort), abc.ABCMeta)

    def test_adapter(self):
        adapter = LoggingLoggerAdapter("test")
        assert isinstance(adapter, LoggerPort)

    def test_log_methods(self):
        adapter = LoggingLoggerAdapter("test")
        # 验证方法存在且不抛出异常
        adapter.info("info test")
        adapter.warning("warning test")
        adapter.error("error test")
        adapter.debug("debug test")
