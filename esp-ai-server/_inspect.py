import sqlite3, time

c = sqlite3.connect("data/espai.db")
row = c.execute("SELECT device_id, is_online, last_seen FROM devices").fetchone()
print("device:", row)
print("now:", time.time())
print("last_seen ago (s):", time.time() - row[2])
