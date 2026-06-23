import requests

headers = {
    'Authorization': 'alist-e322686d-8e5f-4d63-a4ed-7d7ac09ea29ejcm9mRiTpEx5sEB5WJPbvHLPr9al0lMW7MjgV8n19vRY7maKTf2Biw5C7FxetATN',
}

# 完全模拟 check_folder_has_files 的拼接方式
folder_name = '2026-06-11 23\uFF1A23\uFF1A02'  # 全角冒号
ALIST_TARGET_PATH = '/online_prase_site'
path = f'{ALIST_TARGET_PATH}/{folder_name}'
print('拼接路径:', repr(path))
print('路径hex:', path.encode('utf-8').hex())

body = {'path': path, 'password': '', 'page': 1, 'per_page': 0, 'refresh': True}
r = requests.post('http://127.0.0.1:5240/api/fs/list', headers=headers, json=body, timeout=10)
d = r.json()
print('code:', d.get('code'))
print('message:', d.get('message'))
