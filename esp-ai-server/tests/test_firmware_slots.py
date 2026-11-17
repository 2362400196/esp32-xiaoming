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
