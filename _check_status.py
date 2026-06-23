import sqlite3
conn = sqlite3.connect('tasks.db')
cur = conn.execute("SELECT id, queue_order, folder_name, status, created_at FROM tasks WHERE status='downloading'")
rows = cur.fetchall()
print('=== downloading (' + str(len(rows)) + ') ===')
for r in rows:
    print(f'  #{r[1]} [{r[2]}] {r[3]} {r[4]}')

for s in ['ready','pending','adding','failed','done']:
    c = conn.execute('SELECT COUNT(*) FROM tasks WHERE status=?', (s,)).fetchone()[0]
    if c: print(f'{s}: {c}')
conn.close()
