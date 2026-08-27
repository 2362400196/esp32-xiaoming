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


def get_disabled():
    s, r = post(EXEC, {"method": "get_disabled", "args": {"mac": MAC}})
    return r.get("data", {})


print("before:", json.dumps(get_disabled(), ensure_ascii=False))

# 启用 amap-maps（disabled=false）
s, r = post(EXEC, {"method": "toggle_server", "args": {"mac": MAC, "server_name": "amap-maps", "disabled": False}})
print("toggle enable:", s, json.dumps(r, ensure_ascii=False))
print("after enable:", json.dumps(get_disabled(), ensure_ascii=False))

# 再禁用回来（disabled=true）
s, r = post(EXEC, {"method": "toggle_server", "args": {"mac": MAC, "server_name": "amap-maps", "disabled": True}})
print("toggle disable:", s, json.dumps(r, ensure_ascii=False))
print("after disable:", json.dumps(get_disabled(), ensure_ascii=False))
