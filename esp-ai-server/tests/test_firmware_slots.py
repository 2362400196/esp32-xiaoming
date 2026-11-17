"""固件槽位（板卡 + 配网类型）单测"""
import sys
from types import SimpleNamespace

sys.path.insert(0, r"c:\Users\23624\Desktop\esp32-xiaoming\esp-ai-server")

from src.infrastructure import device_api as api


def test_slot_key_with_board():
    entry = {"fw_type": "wifi", "fw_sig": {"board": "ai_vox3"}}
    assert api.firmware_slot_key(entry, "x.bin") == "ai_vox3|wifi"


def test_slot_key_legacy_without_board():
    # 老固件无 board 签名 → 退化为按配网类型分槽
    assert api.firmware_slot_key({"fw_type": "ble"}, "x.bin") == "ble"


def _patch(monkeypatch, meta):
    monkeypatch.setattr(api, "load_firmware_meta", lambda: meta)
    monkeypatch.setattr(
        api, "get_firmware_info",
        lambda name: SimpleNamespace(download_url=f"http://h/{name}", size=100) if name in meta else None,
    )


def test_active_prefers_same_board(monkeypatch):
    meta = {
        "vox3.bin": {"active": True, "fw_type": "wifi", "fw_sig": {"board": "ai_vox3"},
                     "bin_id": "a", "version": "1"},
        "other.bin": {"active": True, "fw_type": "wifi", "fw_sig": {"board": "other_board"},
                      "bin_id": "b", "version": "2"},
    }
    _patch(monkeypatch, meta)
    fw = api.get_active_firmware("wifi", "ai_vox3")
    assert fw["filename"] == "vox3.bin", fw
    assert fw["board"] == "ai_vox3"


def test_active_fallback_to_legacy(monkeypatch):
    # 目标板卡没有专属固件 → 回退到无板卡标识的老固件，而不是别的板卡固件
    meta = {
        "legacy.bin": {"active": True, "fw_type": "wifi", "bin_id": "c", "version": "1"},
        "other.bin": {"active": True, "fw_type": "wifi", "fw_sig": {"board": "other_board"},
                      "bin_id": "b", "version": "2"},
    }
    _patch(monkeypatch, meta)
    fw = api.get_active_firmware("wifi", "brand_new_board")
    assert fw["filename"] == "legacy.bin", fw


def test_active_type_filter(monkeypatch):
    meta = {
        "ble.bin": {"active": True, "fw_type": "ble", "fw_sig": {"board": "ai_vox3"}, "bin_id": "x"},
        "wifi.bin": {"active": True, "fw_type": "wifi", "fw_sig": {"board": "ai_vox3"}, "bin_id": "y"},
    }
    _patch(monkeypatch, meta)
    assert api.get_active_firmware("ble", "ai_vox3")["filename"] == "ble.bin"
    assert api.get_active_firmware("wifi", "ai_vox3")["filename"] == "wifi.bin"


def test_pick_slot_for_bin(monkeypatch):
    meta = {"vox3.bin": {"bin_id": "abc", "fw_type": "wifi", "fw_sig": {"board": "ai_vox3"}}}
    _patch(monkeypatch, meta)
    assert api.pick_slot_for_bin("abc") == {"fw_type": "wifi", "board": "ai_vox3"}
    assert api.pick_slot_for_bin("nope") == {}


def test_prune_keeps_newest_and_active(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "FIRMWARE_DIR", tmp_path)
    meta = {}
    for i in range(4):
        name = f"v{i}.bin"
        (tmp_path / name).write_bytes(b"x")
        meta[name] = {"active": i == 3, "fw_type": "wifi",
                      "fw_sig": {"board": "b"}, "uploaded_at": i + 1}
    removed = api.prune_firmware_versions(meta, keep=2)
    # 每个槽位只保留最新 2 个版本，更旧的连同文件一起删除
    assert set(meta) == {"v2.bin", "v3.bin"}, meta
    assert set(removed) == {"v0.bin", "v1.bin"}, removed
    assert not (tmp_path / "v0.bin").exists()


def test_prune_never_deletes_active(monkeypatch, tmp_path):
    # 启用中的旧固件即使超出保留数也不能删
    monkeypatch.setattr(api, "FIRMWARE_DIR", tmp_path)
    meta = {}
    for i in range(3):
        name = f"old{i}.bin"
        (tmp_path / name).write_bytes(b"x")
        meta[name] = {"active": i == 0, "fw_type": "wifi",
                      "fw_sig": {"board": "b"}, "uploaded_at": i + 1}
    removed = api.prune_firmware_versions(meta, keep=1)
    assert "old0.bin" in meta, meta
    assert set(removed) == {"old1.bin"}


def test_meta_atomic_roundtrip(monkeypatch, tmp_path):
    meta_file = tmp_path / "firmware_meta.json"
    monkeypatch.setattr(api, "FIRMWARE_META_FILE", meta_file)
    monkeypatch.setattr(api, "_META_CACHE", {})
    monkeypatch.setattr(api, "_META_CACHE_MTIME", -1.0)
    api.save_firmware_meta({"a.bin": {"active": True, "bin_id": "x"}})
    assert not (tmp_path / "firmware_meta.json.tmp").exists()
    assert api.load_firmware_meta()["a.bin"]["bin_id"] == "x"
    # 返回副本：调用方修改不会污染缓存
    snapshot = api.load_firmware_meta()
    snapshot["a.bin"]["bin_id"] = "changed"
    assert api.load_firmware_meta()["a.bin"]["bin_id"] == "x"
