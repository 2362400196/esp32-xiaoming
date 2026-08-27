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

# 设备工具列表
s, r = get(f"{BASE}/api/v1/devices/D8%3A3B%3ADA%3A6D%3AD9%3A3C/tools")
print("tools status:", s)
if s == 200:
    data = r.get("data", [])
    print("total tools:", len(data))
    mcp_tools = [t for t in data if t.get("type") == "mcp"]
    print("mcp tools:", len(mcp_tools))
    for t in mcp_tools[:20]:
        print("  ", t.get("name"), "|", t.get("description", "")[:60])
else:
    print(json.dumps(r, ensure_ascii=False)[:500])
