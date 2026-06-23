import sqlite3
conn = sqlite3.connect('tasks.db')

# Check current
print("=== 清理前 ===")
for s in ['downloading', 'adding']:
    cur = conn.execute(f"SELECT id, queue_order, folder_name FROM tasks WHERE status='{s}'")
    for r in cur.fetchall():
        print(f"  {s}: #{r[1]} [{r[2]}]")

# Mark all downloading and adding as failed
conn.execute("UPDATE tasks SET status='failed' WHERE status='downloading' OR status='adding'")
conn.commit()
print("\n✅ downloading + adding → failed")

# Verify
print("\n=== 清理后 ===")
for s in ['ready','pending','failed','done']:
    c = conn.execute('SELECT COUNT(*) FROM tasks WHERE status=?', (s,)).fetchone()[0]
    if c: print(f"{s}: {c}")

conn.close()
