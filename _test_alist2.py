import requests, json, urllib.parse

headers = {
    'Authorization': 'alist-e322686d-8e5f-4d63-a4ed-7d7ac09ea29ejcm9mRiTpEx5sEB5WJPbvHLPr9al0lMW7MjgV8n19vRY7maKTf2Biw5C7FxetATN',
    'Content-Type': 'application/json'
}

# 测试文件名编码
folder_name = '2026-06-11 17：28：13'
encoded = urllib.parse.quote(folder_name, safe='')
print(f'原始: [{folder_name}]')
print(f'编码:  [{encoded}]')

path = f'/online_prase_site/{encoded}'
body = {'path': path, 'password': '', 'page': 1, 'per_page': 0, 'refresh': True}
r = requests.post('http://127.0.0.1:5240/api/fs/list', headers=headers, json=body, timeout=10, proxies={})
data = r.json()
print(f'code: {data.get("code")}')
content = data.get('data', {}).get('content', [])
print(f'该文件夹内文件数: {len(content)}')
for item in content:
    print(f'  [{item.get("name")}] is_dir={item.get("is_dir")} size={item.get("size","?")}')
