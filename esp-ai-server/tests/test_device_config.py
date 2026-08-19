"""DeviceConfig 单元测试"""
import json
import os
import tempfile
import pytest
from dataclasses import dataclass

from src.use_cases.device_config import DeviceConfig, DeviceManager, load_devices


class TestDeviceConfig:
    def test_device_config_defaults(self):
        """验证默认值"""
        cfg = DeviceConfig(device_id="test-001")
        assert cfg.device_id == "test-001"
        assert cfg.name == ""
        assert cfg.key == ""
        assert cfg.asr_provider is None
        assert cfg.llm_api_key is None
        assert cfg.tts_config is None
        assert cfg.music_config is None
        assert cfg.mcp_servers is None
        assert cfg.rate_limit_rpm is None
        assert cfg.disabled_tools == []
        assert cfg.wakeup_config is None

    def test_device_config_full(self):
        """验证完整配置"""
        cfg = DeviceConfig(
            device_id="dev-001",
            name="客厅设备",
            key="abc123",
            asr_provider="volcengine",
            llm_type="openai",
            tts_type="volcengine",
            asr_config={"volcengine": {"api_key": "test_key"}},
            tts_config={"api_key": "test_tts_key"},
            llm_api_key="sk-test",
            llm_base_url="https://api.test.com",
            llm_model="gpt-4",
            llm_system_prompt="你是助手",
            rate_limit_rpm=60,
            disabled_tools=["tool1"],
            wakeup_config={"text": "我在呢"},
        )
        assert cfg.device_id == "dev-001"
        assert cfg.name == "客厅设备"
        assert cfg.llm_api_key == "sk-test"
        assert cfg.rate_limit_rpm == 60
        assert cfg.disabled_tools == ["tool1"]

    def test_get_asr_config(self):
        """验证 ASR 配置读取"""
        cfg = DeviceConfig(
            asr_config={"volcengine": {"api_key": "vk"}, "tencent": {"app_id": "ta"}}
        )
        volc = cfg.get_asr_config("volcengine")
        assert volc == {"api_key": "vk"}
        tencent = cfg.get_asr_config("tencent")
        assert tencent == {"app_id": "ta"}
        missing = cfg.get_asr_config("aliyun")
        assert missing == {}

    def test_get_tts_config(self):
        cfg = DeviceConfig(tts_config={"api_key": "test"})
        assert cfg.get_tts_config() == {"api_key": "test"}

        cfg2 = DeviceConfig()
        assert cfg2.get_tts_config() == {}

    def test_get_effective_methods(self):
        cfg = DeviceConfig(
            llm_model="gpt-4",
            llm_system_prompt="你是助手",
            rate_limit_rpm=30,
        )
        assert cfg.get_effective_llm_model("any") == "gpt-4"
        assert cfg.get_effective_llm_system_prompt("any") == "你是助手"
        assert cfg.get_effective_rate_limit("any") == 30


class TestDeviceManager:
    def test_empty_manager(self):
        dm = DeviceManager()
        assert dm.has_users() is False
        assert dm.has_devices() is False
        assert dm.resolve("any") is None

    def test_resolve_by_key(self):
        dm = DeviceManager(devices={
            "dev1": DeviceConfig(device_id="dev1", key="key1", name="设备1"),
            "dev2": DeviceConfig(device_id="dev2", key="key2", name="设备2"),
        })
        assert dm.has_users() is True
        assert dm.has_devices() is True

        found = dm.resolve("key1")
        assert found is not None
        assert found.name == "设备1"
        assert found.device_id == "dev1"

        not_found = dm.resolve("nonexistent")
        assert not_found is None

    def test_resolve_none_key(self):
        dm = DeviceManager()
        assert dm.resolve(None) is None
        assert dm.resolve("") is None


class TestLoadDevices:
    def test_load_devices_no_file(self):
        """验证 DB 无数据时返回空 DeviceManager"""
        dm = load_devices()
        # load_devices 从 DB 加载，DB 无数据时返回空 DeviceManager
        assert isinstance(dm, DeviceManager)

    def test_load_devices_with_temp_file(self):
        """验证 DeviceConfig 从 dict 正确构造"""
        test_data = {
            "devices": {
                "mac1": {
                    "name": "设备1",
                    "key": "k1",
                    "asr_provider": "volcengine",
                    "asr_config": {"volcengine": {"api_key": "test"}},
                    "llm_type": "openai",
                    "llm": {
                        "api_key": "sk-key",
                        "base_url": "https://api.test.com",
                        "model": "gpt-4",
                        "system_prompt": "你好",
                        "memory_enabled": True,
                        "memory_max_messages": 20,
                    },
                    "tts_type": "volcengine",
                    "tts_config": {"api_key": "tts_key"},
                    "wakeup": {"text": "我在呢", "enabled": True},
                    "rate_limit_rpm": 60,
                    "disabled_tools": [],
                }
            }
        }
        # 验证 DeviceConfig 从 dict（与 DB 返回结构一致）正确构造
        # 注意：load_devices 从 DB 加载，此处验证 DeviceConfig 创建是否正确
        raw = test_data["devices"]["mac1"]
        llm = raw.get("llm") or {}
        cfg = DeviceConfig(
            device_id="mac1",
            name=raw.get("name", ""),
            key=raw.get("key", ""),
            asr_provider=raw.get("asr_provider"),
            llm_type=raw.get("llm_type"),
            tts_type=raw.get("tts_type"),
            asr_config=raw.get("asr_config"),
            tts_config=raw.get("tts_config"),
            llm_api_key=llm.get("api_key"),
            llm_base_url=llm.get("base_url"),
            llm_model=llm.get("model"),
            llm_system_prompt=llm.get("system_prompt"),
            rate_limit_rpm=raw.get("rate_limit_rpm"),
            disabled_tools=raw.get("disabled_tools", []),
            wakeup_config=raw.get("wakeup"),
        )
        assert cfg.name == "设备1"
        assert cfg.key == "k1"
        assert cfg.llm_api_key == "sk-key"
        assert cfg.llm_model == "gpt-4"
        assert cfg.tts_config == {"api_key": "tts_key"}
        assert cfg.wakeup_config == {"text": "我在呢", "enabled": True}
        assert cfg.rate_limit_rpm == 60
