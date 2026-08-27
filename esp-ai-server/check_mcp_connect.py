import json
import urllib.request


def post(url, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {"detail": str(e)}
    except Exception as e:
        return 0, {"detail": str(e)}


BASE = "http://localhost:8088"
MAC = "D8:3B:DA:6D:D9:3C"
EXEC = f"{BASE}/api/v1/plugins/mcp_manager/exec"

# 获取 amap-maps 的工具列表
s, r = post(EXEC, {"method": "get_tools", "args": {"mac": MAC, "server_name": "amap-maps"}})
print("get_tools status:", s)
if s == 200:
    data = r.get("data", [])
    print("tools count:", len(data))
    for t in data[:15]:
        print("  ", t.get("name"), "|", t.get("description", "")[:70])
else:
    print(json.dumps(r, ensure_ascii=False)[:500])
