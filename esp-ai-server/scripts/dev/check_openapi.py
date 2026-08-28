import json
import urllib.request

with urllib.request.urlopen("http://localhost:8088/openapi.json", timeout=10) as resp:
    schema = json.load(resp)

paths = schema.get("paths", {})
print("Total paths:", len(paths))
mcp_paths = [p for p in paths if "mcp" in p.lower()]
print("MCP paths:")
for p in mcp_paths:
    print(" ", p, list(paths[p].keys()))
