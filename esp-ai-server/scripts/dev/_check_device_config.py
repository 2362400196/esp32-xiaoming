"""临时诊断脚本：查看设备 LLM/TTS/ASR 配置。"""
import sqlite3
import json

conn = sqlite3.connect("data/espai.db")
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("Tables:", tables)

# 找设备表
for t in tables:
    if any(k in t.lower() for k in ("device", "config", "user")):
        cur.execute(f"PRAGMA table_info({t})")
        cols = [r[1] for r in cur.fetchall()]
        print(f"\n=== {t} cols: {cols} ===")
        cur.execute(f"SELECT * FROM {t} LIMIT 5")
        rows = cur.fetchall()
        for row in rows:
            print(row)
conn.close()
