import json
import urllib.request


def post(url, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {"detail": str(e)}


BASE = "http://localhost:8088"
MAC = "D8:3B:DA:6D:D9:3C"
EXEC = f"{BASE}/api/v1/plugins/mcp_manager/exec"

# 恢复为测试前状态：amap-maps 禁用
s, r = post(EXEC, {"method": "toggle_server", "args": {"mac": MAC, "server_name": "amap-maps", "disabled": True}})
print("restore:", s, json.dumps(r, ensure_ascii=False))

s, r = post(EXEC, {"method": "get_disabled", "args": {"mac": MAC}})
print("final state:", json.dumps(r.get("data", {}), ensure_ascii=False))
