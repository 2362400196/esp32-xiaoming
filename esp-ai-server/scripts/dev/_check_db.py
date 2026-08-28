import sqlite3
import json

conn = sqlite3.connect('data/espai.db')
c = conn.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [t[0] for t in c.fetchall()]
print('Tables:', tables)

if 'devices' in tables:
    c.execute('SELECT device_key, plugin_configs FROM devices')
    rows = c.fetchall()
    print(f'Devices ({len(rows)}):')
    for r in rows:
        print(f'  device_key={r[0]}')
        print(f'  plugin_configs={r[1]}')
        if r[1]:
            try:
                parsed = json.loads(r[1])
                print(f'  parsed: {json.dumps(parsed, indent=4, ensure_ascii=False)}')
            except Exception as e:
                print(f'  parse error: {e}')

for t in tables:
    if 'plugin' in t.lower() and t != 'devices':
        c.execute(f'SELECT * FROM "{t}"')
        rows = c.fetchall()
        desc = [d[0] for d in c.description]
        print(f'  Table {t} ({desc}): {rows}')

conn.close()