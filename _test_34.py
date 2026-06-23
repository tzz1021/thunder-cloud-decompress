import requests, json

headers = {
    'Authorization': 'alist-e322686d-8e5f-4d63-a4ed-7d7ac09ea29ejcm9mRiTpEx5sEB5WJPbvHLPr9al0lMW7MjgV8n19vRY7maKTf2Biw5C7FxetATN',
    'Content-Type': 'application/json'
}

folder = '2026-06-11 23：23：02'
path = '/online_prase_site/' + folder
body = {'path': path, 'password': '', 'page': 1, 'per_page': 0, 'refresh': True}
r = requests.post('http://127.0.0.1:5240/api/fs/list', headers=headers, json=body, timeout=10)
data = r.json()
print('code:', data.get('code'))
content = data.get('data', {}).get('content', []) or []
print('文件数:', len(content))
for item in content:
    print(' ', item.get('name'), 'is_dir:', item.get('is_dir'), 'size:', item.get('size','?'))
