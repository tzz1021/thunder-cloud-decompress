import requests

headers = {'Authorization': 'alist-e322686d-8e5f-4d63-a4ed-7d7ac09ea29ejcm9mRiTpEx5sEB5WJPbvHLPr9al0lMW7MjgV8n19vRY7maKTf2Biw5C7FxetATN'}

# 列出所有文件夹拿到精确名字
body = {'path': '//online_prase_site', 'password': '', 'page': 1, 'per_page': 0, 'refresh': True}
r = requests.post('http://127.0.0.1:5240/api/fs/list', headers=headers, json=body, timeout=10)
data = r.json()
name = ''
for item in data.get('data',{}).get('content',[]):
    if '23：23：02' in item.get('name',''):
        name = item['name']
        break
print('精确文件夹名:', repr(name))

# 查文件
body2 = {'path': '//online_prase_site/'+name, 'password': '', 'page': 1, 'per_page': 0, 'refresh': True}
r2 = requests.post('http://127.0.0.1:5240/api/fs/list', headers=headers, json=body2, timeout=10)
d2 = r2.json()
print('code:', d2.get('code'))
items = d2.get('data',{}).get('content',[]) or []
print('文件数:', len(items))
for item in items:
    print('  name:', item.get('name'), 'is_dir:', item.get('is_dir'), 'size:', item.get('size','?'), 'modified:', str(item.get('modified',''))[:25])
