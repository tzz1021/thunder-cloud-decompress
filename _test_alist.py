import requests, json

url = 'http://127.0.0.1:5240/api/fs/list'
headers = {
    'Authorization': 'alist-e322686d-8e5f-4d63-a4ed-7d7ac09ea29ejcm9mRiTpEx5sEB5WJPbvHLPr9al0lMW7MjgV8n19vRY7maKTf2Biw5C7FxetATN',
    'Content-Type': 'application/json'
}
body = {'path': '/online_prase_site', 'password': '', 'page': 1, 'per_page': 0, 'refresh': True}

print('=== 1. 列出 /online_prase_site 目录 ===')
try:
    r = requests.post(url, headers=headers, json=body, timeout=10, proxies={})
    print(f'status: {r.status_code}')
    data = r.json()
    print(f'code: {data.get("code")}')
    content = data.get('data', {}).get('content', [])
    print(f'子文件夹/文件数: {len(content)}')
    for item in content[:10]:
        print(f'  [{item.get("name")}] is_dir={item.get("is_dir")} modified={item.get("modified","")[:25]}')
except Exception as e:
    print(f'失败: {e}')

print()
print('=== 2. 查具体文件夹（模拟 downloading 检查） ===')
test_folder = input('输入要检查的文件夹名（直接回车跳过）: ').strip()
if test_folder:
    import urllib.parse
    path = f'/online_prase_site/{urllib.parse.quote(test_folder, safe="")}'
    body2 = {'path': path, 'password': '', 'page': 1, 'per_page': 0, 'refresh': True}
    try:
        r2 = requests.post(url, headers=headers, json=body2, timeout=10, proxies={})
        data2 = r2.json()
        content2 = data2.get('data', {}).get('content', [])
        print(f'code: {data2.get("code")}')
        print(f'内部文件数: {len(content2)}')
        for item in content2[:10]:
            print(f'  [{item.get("name")}] is_dir={item.get("is_dir")} size={item.get("size","?")}')
    except Exception as e:
        print(f'失败: {e}')
