"""固件内嵌签名（esp-ai-fw:）解析单测"""
import sys
sys.path.insert(0, r"c:\Users\23624\Desktop\esp32-xiaoming\esp-ai-server")
from src.infrastructure.device_api import extract_fw_signature, firmware_type_from_signature_or_filename


def test_basic_wifi():
    bin_data = b"\xe9" + b"\x00" * 100 + b"esp-ai-fw:prov=wifi;board=esp32s3_breadboard_1.54_lcd;display=st7789_240;ver=062438e-dirty" + b"\x00" * 50
    sig = extract_fw_signature(bin_data)
    assert sig["prov"] == "wifi", sig
    assert sig["board"] == "esp32s3_breadboard_1.54_lcd", sig
    assert sig["display"] == "st7789_240", sig
    assert sig["ver"] == "062438e-dirty", sig
    assert firmware_type_from_signature_or_filename(sig, "esp-ai-idf-client.bin") == "wifi"
    print("PASS basic_wifi")


def test_ble_no_wifi_name():
    # idf.py 原生产物名（无 -wifi-），签名 ble
    bin_data = b"xxx" + b"esp-ai-fw:prov=ble;board=esp32c3_supermini;display=none;ver=062438e"
    sig = extract_fw_signature(bin_data)
    assert firmware_type_from_signature_or_filename(sig, "esp-ai-idf-client.bin") == "ble"
    print("PASS ble_idfpy_name")


def test_wifi_name_but_ble_sig():
    # 文件名带 wifi 但签名说 ble → 签名优先
    sig = {"prov": "ble"}
    assert firmware_type_from_signature_or_filename(sig, "esp32s3-xiaoming-wifi-abc.bin") == "ble"
    print("PASS sig_overrides_filename")


def test_no_sig_fallback_filename():
    # 老固件无签名 → 回退文件名
    assert extract_fw_signature(b"\xe9" + b"\x00" * 200) == {}
    assert firmware_type_from_signature_or_filename({}, "esp32s3-xiaoming-wifi-abc.bin") == "wifi"
    assert firmware_type_from_signature_or_filename({}, "esp32s3-xiaoming-abc.bin") == "ble"
    print("PASS fallback_filename")


def test_future_keys_preserved():
    # 未来扩展键原样保留（如 audio/flash），未知键不破坏解析
    bin_data = b"esp-ai-fw:prov=wifi;board=x;display=ssd1306_128x64;ver=v1.2;audio=es8311;flash=4MB"
    sig = extract_fw_signature(bin_data)
    assert sig["audio"] == "es8311" and sig["flash"] == "4MB", sig
    print("PASS future_keys")


def test_garbage_and_bounds():
    # 非法内容不崩溃、签名被截断时安全
    assert extract_fw_signature(b"") == {}
    assert extract_fw_signature(b"esp-ai-fw:") == {}
    assert extract_fw_signature(b"esp-ai-fw:prov=") == {} or extract_fw_signature(b"esp-ai-fw:prov=") == {"prov": ""}
    print("PASS garbage")


if __name__ == "__main__":
    test_basic_wifi()
    test_ble_no_wifi_name()
    test_wifi_name_but_ble_sig()
    test_no_sig_fallback_filename()
    test_future_keys_preserved()
    test_garbage_and_bounds()
    print("\n全部 6 项通过 ✓")
