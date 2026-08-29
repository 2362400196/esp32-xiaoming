"""SDK KV 存储单元测试（storage.py）

重点覆盖安全修复：
- 设备级 KV 文件不存在时不再回退到全局文件或扫描其他设备目录复制数据
  （跨设备复制会把前用户的插件数据 token/账号配置泄露给新设备）
"""
import json

import pytest

from src.use_cases.sdk import storage


@pytest.fixture
def kv_root(tmp_path, monkeypatch):
    """把项目根目录重定向到临时目录，并重置全局 KV 警告限频"""
    monkeypatch.setattr(storage, "_get_project_root", lambda: str(tmp_path))
    monkeypatch.setattr(storage, "_global_kv_warn_at", 0.0)
    return tmp_path


class TestGetKvStorePath:
    def test_device_level_path(self, kv_root):
        path = storage._get_kv_store_path("mac-01")
        assert "kv" in path and "mac-01" in path and path.endswith(".json")

    def test_global_path_without_device(self, kv_root):
        path = storage._get_kv_store_path("")
        # 全局路径直接位于 kv 根目录（不含设备子目录）
        assert str(kv_root / "data" / "plugins" / "kv") in path


class TestLoadKvStoreNoCrossDeviceLeak:
    """KV 不再跨设备复制（安全修复回归测试）"""

    def _write_device_store(self, kv_root, device_id: str, data: dict):
        device_dir = kv_root / "data" / "plugins" / "kv" / device_id
        device_dir.mkdir(parents=True, exist_ok=True)
        (device_dir / "unknown.json").write_text(json.dumps(data), encoding="utf-8")

    def test_loads_own_device_file(self, kv_root):
        self._write_device_store(kv_root, "deviceA", {"token": "aaa"})
        assert storage._load_kv_store("deviceA") == {"token": "aaa"}

    def test_missing_device_file_does_not_copy_from_other_devices(self, kv_root):
        """设备 B 文件不存在时不得扫描设备 A 目录复制数据（跨设备泄露修复）"""
        self._write_device_store(kv_root, "deviceA", {"token": "secret-of-user-a"})
        assert storage._load_kv_store("deviceB") == {}
        # 且未把 A 的数据写入 B 的文件（目录可能因 makedirs 创建，但不应有内容文件）
        assert not (kv_root / "data" / "plugins" / "kv" / "deviceB" / "unknown.json").exists()

    def test_missing_device_file_does_not_fallback_to_global(self, kv_root):
        """设备级文件缺失时也不得回退读取/复制全局文件"""
        global_dir = kv_root / "data" / "plugins" / "kv"
        global_dir.mkdir(parents=True, exist_ok=True)
        (global_dir / "unknown.json").write_text(json.dumps({"token": "global-secret"}), encoding="utf-8")
        assert storage._load_kv_store("deviceB") == {}
        assert not (global_dir / "deviceB" / "unknown.json").exists()

    def test_global_branch_still_works_without_device_id(self, kv_root):
        """device_id 为空时仍读全局文件（兼容旧单设备用法）"""
        global_dir = kv_root / "data" / "plugins" / "kv"
        global_dir.mkdir(parents=True, exist_ok=True)
        (global_dir / "unknown.json").write_text(json.dumps({"k": "v"}), encoding="utf-8")
        assert storage._load_kv_store("") == {"k": "v"}

    def test_corrupted_device_file_returns_empty(self, kv_root):
        device_dir = kv_root / "data" / "plugins" / "kv" / "deviceA"
        device_dir.mkdir(parents=True, exist_ok=True)
        (device_dir / "unknown.json").write_text("{broken", encoding="utf-8")
        assert storage._load_kv_store("deviceA") == {}
