"""
XunleiAPI — 迅雷解析站后端核心封装

API 清单 (2026-06-07 逆向所得):
  1. GET  /drive/v1/share?share_id=&pass_code=...   # 查看分享内容
  2. POST /drive/v1/share/restore                    # 转存分享到网盘
  3. POST /drive/v1/share                            # 创建分享链接
  4. POST /drive/v1/files                            # 云添加(离线下载)
  5. GET  /drive/v1/tasks?type=offline               # 查看离线任务列表
  6. GET  /drive/v1/privilege/SPACE_SIZE_LIMIT       # 检查空间限制
  7. POST /decompress/v1/decompress                  # 创建云解压任务
  8. GET  /decompress/v1/progress?task_id=           # 查询解压进度
"""

import time
import json
from typing import Optional
import requests


# ─── 常量 ───────────────────────────────────────────────────────────────
PAN_BASE_URL = "https://api-pan.xunlei.com"
SHOULEI_BASE_URL = "https://api-shoulei-ssl.xunlei.com"

# 以下从浏览器 DevTools 抓取，根据实际情况修改
PARENT_ID = "VOuSL0mD5btC8rL42-TgLVHnA1"  # "在线解压站点食用" 目录 ID
X_CLIENT_ID = "Xqp0kJBXWhwaTpB6"
X_DEVICE_ID = "d6b229140b571bd46ae3742bc0753182"


# ─── 异常 ───────────────────────────────────────────────────────────────
class XunleiAPIError(Exception):
    """迅雷 API 调用异常"""
    def __init__(self, message: str, status_code: int = 0, response: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


# ─── 客户端 ─────────────────────────────────────────────────────────────
class XunleiAPI:
    """
    迅雷网盘 API 封装。

    使用前需注入:
      - bearer_token: JWT Token (从浏览器 DevTools 复制, 或自动刷新)
      - captcha_token: Captcha Token (从浏览器 DevTools 复制, 会过期)
    """

    def __init__(
        self,
        bearer_token: str = "",
        captcha_token: str = "",
        parent_id: str = PARENT_ID,
        x_client_id: str = X_CLIENT_ID,
        x_device_id: str = X_DEVICE_ID,
    ):
        self.bearer_token = bearer_token
        self.captcha_token = captcha_token
        self.parent_id = parent_id
        self.x_client_id = x_client_id
        self.x_device_id = x_device_id

        self._session = requests.Session()
        self._session.headers.update(self._base_headers())

    # ── 内部方法 ──────────────────────────────────────────────────────

    def _base_headers(self) -> dict:
        # 兼容处理: 如果存了 "Bearer xxx" 去掉多余前缀
        bearer = self.bearer_token
        if bearer.startswith("Bearer "):
            bearer = bearer[7:]

        return {
            "accept": "*/*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "authorization": f"Bearer {bearer}",
            "content-type": "application/json",
            "dnt": "1",
            "origin": "https://pan.xunlei.com",
            "referer": "https://pan.xunlei.com/",
            "sec-ch-ua": '"Chromium";v="148", "Microsoft Edge";v="148", "Not/A)Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "sec-gpc": "1",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"
            ),
            "x-captcha-token": self.captcha_token,
            "x-client-id": self.x_client_id,
            "x-device-id": self.x_device_id,
        }

    def _pan_get(self, path: str, params: dict = None) -> dict:
        url = PAN_BASE_URL + path
        resp = self._session.get(url, params=params)
        if not resp.ok:
            raise XunleiAPIError(
                f"PAN GET {path} 失败", resp.status_code, resp.text
            )
        return resp.json()

    def _pan_post(self, path: str, data: dict = None) -> dict:
        url = PAN_BASE_URL + path
        resp = self._session.post(url, json=data or {})
        if not resp.ok:
            raise XunleiAPIError(
                f"PAN POST {path} 失败", resp.status_code, resp.text
            )
        return resp.json()

    def _shoulei_post(self, path: str, data: dict = None) -> dict:
        url = SHOULEI_BASE_URL + path
        resp = self._session.post(url, json=data or {})
        if not resp.ok:
            raise XunleiAPIError(
                f"SHOULEI POST {path} 失败", resp.status_code, resp.text
            )
        return resp.json()

    def _shoulei_get(self, path: str, params: dict = None) -> dict:
        url = SHOULEI_BASE_URL + path
        resp = self._session.get(url, params=params)
        if not resp.ok:
            raise XunleiAPIError(
                f"SHOULEI GET {path} 失败", resp.status_code, resp.text
            )
        return resp.json()

    # ── Token / Captcha 管理 ──────────────────────────────────────────

    def set_tokens(self, bearer_token: str, captcha_token: str):
        """手动注入新的 Token 和 Captcha"""
        self.bearer_token = bearer_token
        self.captcha_token = captcha_token
        self._session.headers.update({
            "authorization": f"Bearer {bearer_token}",
            "x-captcha-token": captcha_token,
        })

    # ── 核心 API 业务方法 ──────────────────────────────────────────────

    # 1. 查看分享内容 ─────────────────────────────────────────────────
    def get_share_files(
        self, share_id: str, pass_code: str,
        pass_code_token: str = "",
        limit: int = 100,
    ) -> dict:
        """获取分享链接内的文件列表"""
        params = {
            "share_id": share_id,
            "pass_code": pass_code,
            "limit": limit,
            "keyword": "",
            "pass_code_token": pass_code_token,
            "page_token": "",
            "scene": "NORMAL",
            "order": "DEFAULT_ORDER",
            "thumbnail_size": "SIZE_SMALL",
        }
        return self._pan_get("/drive/v1/share", params)

    # 2. 转存分享到网盘 ───────────────────────────────────────────────
    def restore_share(
        self, share_id: str, file_ids: list,
        pass_code_token: str = "",
        parent_id: str = None,
    ) -> dict:
        """将分享中的文件转存到自己的网盘"""
        pid = parent_id or self.parent_id
        data = {
            "parent_id": pid,
            "share_id": share_id,
            "pass_code_token": pass_code_token,
            "ancestor_ids": [],
            "file_ids": file_ids,
            "specify_parent_id": True,
        }
        return self._pan_post("/drive/v1/share/restore", data)

    # 3. 创建分享链接 ─────────────────────────────────────────────────
    def create_share(
        self,
        file_ids: list,
        share_to: str = "copy",
        title: str = "",
        restore_limit: str = "-1",
        expiration_days: str = "-1",
        with_pass_code: bool = True,
    ) -> dict:
        """为文件或文件夹创建分享链接"""
        data = {
            "file_ids": file_ids,
            "share_to": share_to,
            "params": {
                "subscribe_push": "false",
                "WithPassCodeInLink": str(with_pass_code).lower(),
                "share_file_order": "MODIFY_TIME_DESC",
            },
            "title": title,
            "restore_limit": restore_limit,
            "expiration_days": expiration_days,
        }
        return self._pan_post("/drive/v1/share", data)

    # 4. 云添加(离线下载) ──────────────────────────────────────────────
    def cloud_upload_url(
        self, url: str, name: str = "",
        parent_id: str = None,
    ) -> dict:
        """提交直链/磁链进行离线下载"""
        pid = parent_id or self.parent_id
        data = {
            "upload_type": "UPLOAD_TYPE_URL",
            "kind": "drive#file",
            "parent_id": pid,
            "name": name or url,
            "hash": "",
            "size": 0,
            "url": {
                "url": url,
                "files": [],
            },
            "unionId": "",
            "params": {
                "require_links": "false",
            },
        }
        return self._pan_post("/drive/v1/files", data)

    # 5. 查看离线任务列表 ─────────────────────────────────────────────
    def list_offline_tasks(
        self, limit: int = 100, page_token: str = ""
    ) -> dict:
        """查看当前离线下载任务列表"""
        params = {
            "limit": limit,
            "phaseCheck": "false",
            "page_token": page_token,
            "type": "offline",
        }
        return self._pan_get("/drive/v1/tasks", params)

    # 6. 检查空间限制 ─────────────────────────────────────────────────
    def get_space_limit(self) -> dict:
        """检查账号可用空间"""
        return self._pan_get("/drive/v1/privilege/SPACE_SIZE_LIMIT")

    # 7. 创建云解压任务 ───────────────────────────────────────────────
    def decompress(
        self,
        file_id: str,
        gcid: str,
        parent_id: str = None,
        password: str = "",
    ) -> dict:
        """对压缩文件发起云解压"""
        pid = parent_id or self.parent_id
        data = {
            "gcid": gcid,
            "file_id": file_id,
            "password": password,
            "default_parent": False,
            "parent_id": pid,
            "files": [],
            "parent_full_path": [],
            "file_space": "",
            "parent_space": "",
        }
        return self._shoulei_post("/decompress/v1/decompress", data)

    # 8. 查询解压进度 ─────────────────────────────────────────────────
    def get_decompress_progress(self, task_id: str) -> dict:
        """查询云解压任务的当前进度"""
        params = {"task_id": task_id}
        return self._shoulei_get("/decompress/v1/progress", params)

    # 9. 获取文件列表(通用) ──────────────────────────────────────────
    def list_files(
        self, parent_id: str = None,
        limit: int = 50,
        filters: Optional[dict] = None,
    ) -> dict:
        """获取目录下的文件列表（辅助用）"""
        pid = parent_id or self.parent_id
        params = {
            "parent_id": pid,
            "usage": "DISPLAY",
            "filters": json.dumps(filters or {
                "phase": {"eq": "PHASE_TYPE_COMPLETE"},
                "trashed": {"eq": False},
            }),
            "with_audit": "true",
            "thumbnail_size": "SIZE_SMALL",
            "limit": limit,
        }
        return self._pan_get("/drive/v1/files", params)


# ─── 便捷函数 ───────────────────────────────────────────────────────────
def check_file_size(files: list, min_bytes: int = 1_000_000_000) -> tuple:
    """
    检查文件列表中是否有 ≥ min_bytes 的文件。
    返回 (is_large: bool, large_files: list)
    """
    large = [f for f in files if int(f.get("size", 0)) >= min_bytes]
    return len(large) > 0, large


# ─── Demo ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("XunleiAPI 已加载。使用样例：")
    print()
    print("  from api import XunleiAPI")
    print("  client = XunleiAPI(bearer_token='...', captcha_token='...')")
    print()
    print("  # 云添加一个直链")
    print("  r = client.cloud_upload_url('https://example.com/file.zip')")
    print()
    print("  # 转存分享")
    print("  r = client.restore_share('share_id', ['file_id1'], 'pass_code_token')")
    print()
    print("  # 云解压")
    print("  r = client.decompress('file_id', 'gcid')")
    print()
    print("  # 查解压进度")
    print("  r = client.get_decompress_progress('task_id')")
    print()
    print("  # 创建分享")
    print("  r = client.create_share(['file_id1'])")
