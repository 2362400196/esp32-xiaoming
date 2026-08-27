import os

root = r"c:\Users\23624\Desktop\esp\esp32-xiaoming\esp-ai-server\src"
for dirpath, dirnames, filenames in os.walk(root):
    if "__pycache__" in dirpath:
        continue
    for fn in filenames:
        if not fn.endswith(".py"):
            continue
        path = os.path.join(dirpath, fn)
        try:
            with open(path, "r", encoding="utf-8") as f:
                for i, line in enumerate(f, 1):
                    low = line.lower()
                    if "mcp" in low and ("router." in low or "app." in low or "add_api_route" in low or "include_router" in low):
                        print(f"{path}:{i}: {line.rstrip()}")
        except Exception:
            pass
