import requests

headers = {
    'Authorization': 'alist-e322686d-8e5f-4d63-a4ed-7d7ac09ea29ejcm9mRiTpEx5sEB5WJPbvHLPr9al0lMW7MjgV8n19vRY7maKTf2Biw5C7FxetATN',
}

# 列出所有文件夹名（按修改时间倒序，看最新的）
body = {'path': '/online_prase_site', 'password': '', 'page': 1, 'per_page': 0, 'refresh': True}
r = requests.post('http://127.0.0.1:5240/api/fs/list', headers=headers, json=body, timeout=10)
data = r.json()
print('code:', data.get('code'))
content = data.get('data', {}).get('content', []) or []
print('总数:', len(content))
# 找包含 23 的文件夹
for item in content:
    name = item.get('name', '')
    if '23' in name:
        print(f'  {name}  modified={item.get("modified","")[:25]}')
