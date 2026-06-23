import sqlite3
from pathlib import Path
conn = sqlite3.connect(str(Path(__file__).parent / 'tasks.db'))
cur = conn.execute("SELECT id, status FROM tasks WHERE status='processing'")
rows = cur.fetchall()
print(f'旧 processing 任务数: {len(rows)}')
for tid, st in rows:
    print(f'  #{tid} was processing')
# 全都改成 ready（1个正在处理的数据，让它重新走解压流程）
conn.execute("UPDATE tasks SET status='ready' WHERE status='processing'")
conn.commit()
print('已统一迁移 processing → ready（让主循环重新走解压流程）')
conn.close()
