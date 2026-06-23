import requests, sqlite3

headers = {
    'Authorization': 'alist-e322686d-8e5f-4d63-a4ed-7d7ac09ea29ejcm9mRiTpEx5sEB5WJPbvHLPr9al0lMW7MjgV8n19vRY7maKTf2Biw5C7FxetATN',
}

from pathlib import Path
conn = sqlite3.connect(str(Path(__file__).parent / 'tasks.db'))
cur = conn.execute("SELECT id, folder_name, status FROM tasks WHERE status='downloading' OR status='processing'")
tasks = cur.fetchall()
conn.close()

print(f'检查 {len(tasks)} 个 downloading/processing 任务:')
for tid, fn, st in tasks:
    path = f'/online_prase_site/{fn}'
    body = {'path': path, 'password': '', 'page': 1, 'per_page': 0, 'refresh': True}
    r = requests.post('http://127.0.0.1:5240/api/fs/list', headers=headers, json=body, timeout=10)
    d = r.json()
    content = d.get('data',{}).get('content',[]) or []
    has_files = any(not item.get('is_dir') for item in content)
    print(f'  #{tid} [{fn}] code={d.get("code")} 文件数={len(content)} 有文件={has_files}')
