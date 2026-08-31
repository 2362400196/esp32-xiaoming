import sqlite3

con = sqlite3.connect('data/espai.db')
cur = con.cursor()
tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print('tables:', tables)
for t in tables:
    if 'device' in t.lower():
        cols = [c[1] for c in cur.execute(f'PRAGMA table_info({t})').fetchall()]
        print(t, 'cols:', cols)
        rows = cur.execute(f'SELECT * FROM {t}').fetchall()
        print('rows:', len(rows))
        for r in rows[:5]:
            print(r)
con.close()
