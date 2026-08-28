import json
import urllib.request


def post(url, body, token=None):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {"detail": str(e)}


def get(url, token=None):
    req = urllib.request.Request(url, method="GET")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {"detail": str(e)}


BASE = "http://localhost:8088"

# 1. 登录
status, login = post(f"{BASE}/api/v1/auth/login", {"email": "2362400196", "password": "admin123"})
print("login:", status, json.dumps(login, ensure_ascii=False)[:200])
token = None
if status == 200 and login.get("data", {}).get("access_token"):
    token = login["data"]["access_token"]

# 2. 前端页面列表
status, pages = get(f"{BASE}/api/v1/plugins/frontend-pages", token)
print("\nfrontend-pages:", status)
if status == 200:
    for p in pages.get("data", []):
        print("  ", p.get("name"), "|", p.get("nav_label"), "|", p.get("entry"))

# 3. exec 桥梁 get_servers
status, res = post(f"{BASE}/api/v1/plugins/mcp_manager/exec",
                   {"method": "get_servers", "args": {"mac": "D8:3B:DA:6D:D9:3C"}}, token)
print("\nexec get_servers:", status, json.dumps(res, ensure_ascii=False)[:300])

# 4. exec 桥梁 get_disabled
status, res = post(f"{BASE}/api/v1/plugins/mcp_manager/exec",
                   {"method": "get_disabled", "args": {"mac": "D8:3B:DA:6D:D9:3C"}}, token)
print("exec get_disabled:", status, json.dumps(res, ensure_ascii=False)[:300])
