"""
step5_queue_worker.py — 阶段5：队列工作者（不带循环的单次执行入口）

接收一个任务（文件夹名 + URL），按顺序执行 step1 → step2 → step3 → step4。

流程:
  1. 初始化浏览器引擎
  2. step1: 新建时间戳文件夹
  3. step2: 云添加（在文件夹内提交 URL）
  4. step3: 监听修改时间变化 → 重命名 → 解压
  5. step4: 创建分享链接
  6. 关闭浏览器

注意：本文件是单次执行版本，不带循环。
需要排队循环逻辑的版本将在后续迭代中添加。
"""

import sys
import os
import time
import json
import random
import logging
from pathlib import Path

# 添加当前目录到 Python 路径
sys.path.insert(0, os.path.dirname(__file__))

from browser_engine import BrowserEngine
import step1_new_folder
import step2_cloud_upload
import step3_monitor
import step4_share

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("queue_worker")


def process_single_task(folder_name: str, url: str,
                        headless: bool = False,
                        debug: bool = False,
                        debug_port: int = 9222,
                        browser_type: str = "edge") -> dict:
    """
    执行单个任务的全流程。
    
    参数:
      folder_name: 时间戳字符串（如 "2026-06-07 23：19：30"）
      url: 用户提交的直链 URL
      headless: 是否无头模式
    
    返回:
      {
        "share_url": str,      # 分享链接
        "folder_name": str,
        "file_id": str,
        "success": bool,
        "steps": [               # 各步骤结果
          {"step": "new_folder", ...},
          {"step": "cloud_upload", ...},
          {"step": "monitor", ...},
          {"step": "share", ...}
        ]
      }
    """
    result = {
        "share_url": "",
        "folder_name": folder_name,
        "file_id": "",
        "success": False,
        "steps": []
    }

    # ── 初始化浏览器引擎 ──
    engine = BrowserEngine(headless=headless, attach=debug,
                           debug_port=debug_port, browser_type=browser_type)
    start_time = time.time()

    try:
        # 登录 + 注入 Cookie
        logger.info("=== 初始化浏览器 ===")
        engine.login_and_inject_cookies()

        # 注入剪贴板劫持 JS（用于后续 step4 获取分享链接）
        # clipboard_hijack_js: 拦截 navigator.clipboard.writeText
        engine.inject_clipboard_hijack()

        # ═══════════════════════════════════════════════════════
        # 阶段1: 新建时间戳文件夹
        # ═══════════════════════════════════════════════════════
        # dict1: 文件夹名 → data-file-id 映射
        logger.info(f"{'='*50}")
        logger.info(f"阶段1: 新建文件夹 {folder_name}")
        logger.info(f"{'='*50}")

        step1_result = step1_new_folder.run(engine, folder_name)
        result["steps"].append({"step": "new_folder", **step1_result})
        if not step1_result["success"]:
            raise RuntimeError(f"步骤1失败: 无法创建文件夹 {folder_name}")

        file_id = step1_result.get("file_id", "")
        result["file_id"] = file_id

        # 等待 3-5 秒让文件夹内页面渲染稳定
        import random
        wait_time = random.randint(3, 5)
        logger.info(f"等待 {wait_time}s 让文件夹页面稳定...")
        time.sleep(wait_time)

        # ═══════════════════════════════════════════════════════
        # 阶段2: 云添加
        # ═══════════════════════════════════════════════════════
        # 已在文件夹内（step1 导航进入），直接执行云添加
        logger.info(f"{'='*50}")
        logger.info(f"阶段2: 云添加 {url[:60]}...")
        logger.info(f"{'='*50}")

        step2_result = step2_cloud_upload.run(engine, url, folder_name=folder_name)
        result["steps"].append({"step": "cloud_upload", **step2_result})
        if not step2_result["success"]:
            raise RuntimeError(f"步骤2失败: 云添加失败")

        # ═══════════════════════════════════════════════════════
        # 阶段3: 监听 + 重命名 + 解压
        # ═══════════════════════════════════════════════════════
        # dict2: 文件夹名 → 修改时间
        # processed_set: 已处理的文件夹名集合
        logger.info(f"{'='*50}")
        logger.info(f"阶段3: 监听修改时间变化")
        logger.info(f"{'='*50}")

        dict2 = {}  # 监听用：文件夹名 → 修改时间
        processed_set = set()  # 已处理集合

        step3_result = step3_monitor.run(engine, dict2, processed_set,
                                         new_folder_name=folder_name,
                                         max_wait_seconds=300)
        result["steps"].append({"step": "monitor", **step3_result})
        if not step3_result["success"]:
            raise RuntimeError(f"步骤3失败: {step3_result.get('message', '未知错误')}")

        # ═══════════════════════════════════════════════════════
        # 阶段4: 创建分享链接
        # ═══════════════════════════════════════════════════════
        logger.info(f"{'='*50}")
        logger.info(f"阶段4: 创建分享链接")
        logger.info(f"{'='*50}")

        step4_result = step4_share.run(engine, file_id)
        result["steps"].append({"step": "share", **step4_result})
        if step4_result["success"]:
            result["share_url"] = step4_result["share_url"]
            result["success"] = True
            elapsed = time.time() - start_time
            logger.info(f"{'='*50}")
            logger.info(f"✅ 完成! 耗时: {elapsed:.0f}s")
            logger.info(f"   分享链接: {step4_result['share_url']}")
            logger.info(f"{'='*50}")
        else:
            raise RuntimeError("步骤4失败: 无法创建分享链接")

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"❌ 任务失败 ({elapsed:.0f}s): {e}")
        result["success"] = False
        result["error"] = str(e)

    finally:
        engine.close()

    return result


# ─── 入口（单次测试用） ───────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("用法: python step5_queue_worker.py <文件夹名> <直链URL> [选项]")
        print("选项:")
        print("  --headless         无头模式（默认模式，需要 Cookie 注入）")
        print("  --debug            附加到已有浏览器（需先手动启动 Edge/Chrome）")
        print("  --port <数字>      调试端口（默认 9222）")
        print("  --browser <edge|chrome>  浏览器类型（默认 edge）")
        print("")
        print("Debug 模式使用步骤:")
        print("  1. 关闭所有 Edge 窗口")
        print("  2. 命令行启动: msedge.exe --remote-debugging-port=9222 --user-data-dir=\"C:\\selenium_user_data\"")
        print("  3. 手动登录 pan.xunlei.com")
        print("  4. 运行: python step5_queue_worker.py <文件夹名> <URL> --debug")
        print("")
        print("示例: python step5_queue_worker.py \"2026-06-08 13：45：00\" https://example.com/file.zip --debug")
        sys.exit(1)

    folder_name = sys.argv[1]
    url = sys.argv[2]
    headless = "--headless" in sys.argv
    debug = "--debug" in sys.argv
    debug_port = 9222
    browser_type = "edge"

    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            debug_port = int(sys.argv[idx + 1])
    if "--browser" in sys.argv:
        idx = sys.argv.index("--browser")
        if idx + 1 < len(sys.argv):
            browser_type = sys.argv[idx + 1]

    logger.info(f"开始任务: {folder_name} | {url[:60]}...")
    logger.info(f"模式: {'Debug 附加' if debug else '默认自启动'} | 端口: {debug_port} | 浏览器: {browser_type}")
    result = process_single_task(folder_name, url, headless=headless,
                                 debug=debug, debug_port=debug_port,
                                 browser_type=browser_type)

    print("\n结果:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
