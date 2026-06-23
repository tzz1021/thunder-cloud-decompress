"""
Token 管理器 — 从浏览器 cookies/localStorage 提取迅雷 JWT 和 Captcha Token

用法:
  python token_manager.py            # 交互式粘贴
  python token_manager.py --check    # 检查当前 token 是否有效
  
注意: 这是临时方案, 后续可自动化 token 刷新
"""

import json
import os
import sys
from datetime import datetime

TOKEN_FILE = os.path.join(os.path.dirname(__file__), "tokens.json")


def save_tokens(bearer: str, captcha: str):
    """保存 token 到本地文件"""
    data = {
        "bearer_token": bearer,
        "captcha_token": captcha,
        "updated_at": datetime.now().isoformat(),
    }
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[✓] Tokens saved to {TOKEN_FILE}")


def load_tokens() -> dict:
    """从本地文件读取 token"""
    if not os.path.exists(TOKEN_FILE):
        print(f"[!] Token file not found: {TOKEN_FILE}")
        return {}
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def interactive_input():
    """交互式粘贴 token"""
    print("=" * 50)
    print("  迅雷 Token 注入工具")
    print("=" * 50)
    print()
    print("从浏览器 DevTools 获取:")
    print("  1. JWT: Network → 任意请求 → Authorization: Bearer <...>")
    print("  2. Captcha: 同一请求的 x-captcha-token header")
    print()

    bearer = input("Paste Bearer Token (JWT):\n> ").strip()
    if not bearer:
        print("[!] Bearer Token 不能为空")
        return False

    captcha = input("Paste x-captcha-token:\n> ").strip()
    if not captcha:
        print("[!] Captcha Token 不能为空")
        return False

    save_tokens(bearer, captcha)
    return True


def quick_test():
    """快速测试 token 是否有效"""
    tokens = load_tokens()
    if not tokens:
        print("[!] 请先运行 python token_manager.py 注入 token")
        return False

    from api import XunleiAPI

    client = XunleiAPI(
        bearer_token=tokens.get("bearer_token", ""),
        captcha_token=tokens.get("captcha_token", ""),
    )

    try:
        # 轻量测试: 获取空间限制
        result = client.get_space_limit()
        print(f"[✓] Token 有效!")
        print(f"    Response keys: {list(result.keys())}")
        return True
    except Exception as e:
        print(f"[✗] Token 失效: {e}")
        print("    请重新从浏览器 DevTools 复制新 token 并注入。")
        return False


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        quick_test()
    elif len(sys.argv) > 1 and sys.argv[1] == "--quick":
        # 从命令行参数直接传 (bearer, captcha)
        # 用法: python token_manager.py --quick "bearer..." "captcha..."
        save_tokens(sys.argv[2], sys.argv[3])
    else:
        interactive_input()
