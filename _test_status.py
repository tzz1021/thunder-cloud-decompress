import sqlite3
from pathlib import Path
conn = sqlite3.connect(str(Path(__file__).parent / 'tasks.db'))
conn.row_factory = sqlite3.Row
cur = conn.execute('SELECT id, folder_name, status FROM tasks ORDER BY id')
for r in cur.fetchall():
    d = dict(r)
    print(f'#{d["id"]:2d} {d["status"]:12s} {d["folder_name"]}')
conn.close()
