import sqlite3

for db in ["data/espai.db", "data/esp-ai.db"]:
    print(f"===== {db} =====")
    try:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        print("tables:", tables)
        if "skills" in tables:
            cols = [r[1] for r in cur.execute("PRAGMA table_info(skills)").fetchall()]
            rows = cur.execute("SELECT * FROM skills").fetchall()
            total = 0
            for r in rows:
                d = dict(r)
                body = d.get("body") or ""
                total += len(body)
                print(f"  {d.get('skill_id')}: body={len(body)}字 device={d.get('device_id')}")
            print(f"总 body: {total}")
        conn.close()
    except Exception as e:
        print("error:", e)
