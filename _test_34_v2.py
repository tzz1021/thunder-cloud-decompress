import requests

headers = {
    'Authorization': 'alist-e322686d-8e5f-4d63-a4ed-7d7ac09ea29ejcm9mRiTpEx5sEB5WJPbvHLPr9al0lMW7MjgV8n19vRY7maKTf2Biw5C7FxetATN',
}

# 先列出所有，精确拿到名字（直接从 API 返回取）
body = {'path': '/online_prase_site', 'password': '', 'page': 1, 'per_page': 0, 'refresh': True}
r = requests.post('http://127.0.0.1:5240/api/fs/list', headers=headers, json=body, timeout=10)
data = r.json()
name = ''
for item in data.get('data',{}).get('content',[]):
    if '23：23：02' in item.get('name',''):
        name = item['name']
        print('从列表取到的精确名字:', repr(name))
        print('  字节:', name.encode('utf-8').hex())
        break

# 用精确名字去查
path = '/online_prase_site/' + name
body2 = {'path': path, 'password': '', 'page': 1, 'per_page': 0, 'refresh': True}
r2 = requests.post('http://127.0.0.1:5240/api/fs/list', headers=headers, json=body2, timeout=10)
d2 = r2.json()
print('查结果 -> code:', d2.get('code'))
content2 = d2.get('data',{}).get('content',[]) or []
for item in content2:
    print('  文件:', item.get('name'), 'size:', item.get('size'))
