import json
import urllib.request


def get(url):
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {"detail": str(e)}


BASE = "http://localhost:8088"

# 设备列表（检查在线状态）
s, r = get(f"{BASE}/api/v1/devices")
print("devices status:", s)
if s == 200:
    devs = r.get("data", {}).get("devices", [])
    for d in devs:
        print(f"  {d.get('device_id')} | online={d.get('online')} | name={d.get('name')}")
