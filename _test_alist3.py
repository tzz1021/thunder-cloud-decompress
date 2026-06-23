import requests, json, urllib.parse

headers = {
    'Authorization': 'alist-e322686d-8e5f-4d63-a4ed-7d7ac09ea29ejcm9mRiTpEx5sEB5WJPbvHLPr9al0lMW7MjgV8n19vRY7maKTf2Biw5C7FxetATN',
    'Content-Type': 'application/json'
}

folder_name = '2026-06-11 17：28：13'
safe_chars = "：；（）（）【】《》！？，。、"
encoded_name = urllib.parse.quote(folder_name, safe=safe_chars)
print(f'编码后: [{encoded_name}]')

path = f'/online_prase_site/{encoded_name}'
body = {'path': path, 'password': '', 'page': 1, 'per_page': 0, 'refresh': True}
r = requests.post('http://127.0.0.1:5240/api/fs/list', headers=headers, json=body, timeout=10, proxies={})
data = r.json()
print(f'code: {data.get("code")}')
content = data.get('data', {}).get('content', []) or []
print(f'内容数: {len(content)}')
for item in content:
    print(f'  [{item.get("name")}] is_dir={item.get("is_dir")} size={item.get("size","?")}')

# also test: 直接用未编码的
print()
print('=== 不编码直接传 ===')
body2 = {'path': f'/online_prase_site/{folder_name}', 'password': '', 'page': 1, 'per_page': 0, 'refresh': True}
r2 = requests.post('http://127.0.0.1:5240/api/fs/list', headers=headers, json=body2, timeout=10, proxies={})
data2 = r2.json()
print(f'code: {data2.get("code")}')
content2 = data2.get('data', {}).get('content', []) or []
print(f'内容数: {len(content2)}')
