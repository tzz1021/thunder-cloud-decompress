"""
main_loop.py — 生产主循环

F5刷新回到target_dir → 查队列 → 执行下一步

无限循环（每轮约 3-10 秒）:
  1. F5 刷新（回到 target_dir）
  2. 查 tasks 表:
     a. 有 status='ready' 的任务 → 解压分享
     b. 没有 ready → scan_local_times 检查 downloading 有无完成
     c. 没有完成的 downloading → 有 pending → 云添加
     d. 啥都没有 → sleep 3 秒

运行方式:
  python main_loop.py --debug        # 附加到 9222 的 Edge
  python main_loop.py                # Selenium 自启动
"""

import sys
import os
import time
import random
import json
import logging
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

# 日志：按天命名，追加写入。同一天多次启动共用同一个文件。
_log_dir = Path(__file__).parent
_today = time.strftime("%Y-%m-%d")
_log_file = _log_dir / f"main_loop_{_today}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(_log_file, encoding="utf-8", mode="a"),
        logging.StreamHandler(sys.stdout)
    ],
    force=True
)
logger = logging.getLogger("main_loop")

from browser_engine import BrowserEngine
from task_db import init_db, get_first_by_status, get_by_folder_name
from task_db import add_task, update_status, update_share_url, update_st_mtime, update_st_mtime_string
from task_db import count_by_status, get_queue_summary
import step1_new_folder
import step2_cloud_upload
import step3_monitor
import step4_share

# ─── 配置 ────────────────────────────────────────────────────

TARGET_DIR = "https://pan.xunlei.com/?path=%2F%E5%9C%A8%E7%BA%BF%E8%A7%A3%E5%8E%8B%E7%AB%99%E7%82%B9%E9%A3%9F%E7%94%A8"
PAN_BASE = "https://pan.xunlei.com"
CHILD_DIR_TPL = "https://pan.xunlei.com/?path=%2F%E5%9C%A8%E7%BA%BF%E8%A7%A3%E5%8E%8B%E7%AB%99%E7%82%B9%E9%A3%9F%E7%94%A8%2F{foldername}"
LOOP_INTERVAL = 3       # 主循环间隔（秒）

# ─── Alist API 配置 ──────────────────────────────────────────
ALIST_BASE = "http://127.0.0.1:5244"
ALIST_TOKEN = "openlist-14989307-4a0f-4fe1-82db-1c38c6614af3YvPhW1slUHWoBBtIwRCyr5OPUrBErdbK0Nq40QYv69UkmbIq4gGGGXNeXZhdvxAJ"
ALIST_TARGET_PATH = "/online_prase_site"  # Alist 中的目录路径


def _alist_list(path: str) -> list:
    """通用 Alist API 调用：列出 path 下的内容。返回 content 列表或空列表。"""
    import requests as _req
    try:
        # OpenList API: GET 方式 + token 在 Authorization header
        resp = _req.get(
            f"{ALIST_BASE}/api/fs/list",
            headers={"Authorization": ALIST_TOKEN},
            params={"path": path},
            timeout=10
        )
        data = resp.json()
        if data.get("code") != 200:
            return []
        content = data.get("data", {})
        if content is None:
            return []
        content = content.get("content")
        return content if content else []
    except Exception as e:
        logger.warning(f"Alist API 请求失败 ({path}): {e}")
        return []


def check_folder_has_files(folder_name: str) -> bool:
    """
    直接查 Alist 中该文件夹下是否有文件（不比较 mtime）。
    路径: /online_prase_site/文件夹名
    
    返回 True: 文件夹内有内容（下载完成）
    返回 False: 文件夹不存在或为空
    """
    # Alist API 处理路径时直接支持中文/全角字符，不需要 URL 编码
    # urllib.parse.quote 会把全角冒号 ： 编码为 %EF%BC%9A 导致路径 mismatch（返回 500）
    # 直接拼接原始文件夹名即可
    path = f"{ALIST_TARGET_PATH}/{folder_name}"
    content = _alist_list(path)
    # 有非目录文件 = 下载完成
    for item in content:
        if not item.get("is_dir"):
            return True
    return False


def check_downloading_completion() -> bool:
    """
    检查 downloading 任务是否下载完成。
    直接查每个任务对应文件夹内是否有文件（取代 mtime 比较）。
    
    返回 True 表示有任务切换到了 ready。
    """
    conn = __import__("sqlite3").connect(str(Path(__file__).parent / "tasks.db"))
    conn.row_factory = __import__("sqlite3").Row
    cur = conn.execute(
        "SELECT * FROM tasks WHERE status='downloading' ORDER BY queue_order"
    )
    downloading_tasks = [dict(r) for r in cur.fetchall()]
    conn.close()

    found = False
    for task in downloading_tasks:
        fn = task["folder_name"]
        if check_folder_has_files(fn):
            logger.info(f"Alist 检测到文件夹已有文件: [{fn}] → 标记 ready")
            update_status(task["id"], "ready")
            found = True
        else:
            logger.debug(f"downloading 检查: [{fn}] 文件夹仍为空")

    return found


def refresh_and_goto_target(engine):
    """F5 刷新页面，然后导航到 target_dir"""
    try:
        # 直接 URL 导航代替 F5（SPA 下 refresh() 经常挂）
        engine.driver.get(PAN_BASE)
        time.sleep(3)
        engine.navigate_to_target_dir()
        time.sleep(2)
        logger.info("刷新 → 已回到 target_dir")
    except Exception as e:
        logger.warning(f"刷新失败（重试 navigate_to）: {e}")
        try:
            engine.navigate_to(PAN_BASE)
            time.sleep(2)
            engine.navigate_to_target_dir()
        except Exception as e2:
            logger.error(f"导航回 target_dir 也失败: {e2}")
            raise


def log_cycle_summary():
    """日志输出当前队列状态"""
    s = get_queue_summary()
    total = sum(s.values())
    logger.info(
        f"队列: 待添加={s['pending']} 添加中={s['adding']} "
        f"下载中={s['downloading']} 待解压={s['ready']} "
        f"解压中={s['decompressing']} 已完成={s['done']} "
        f"不可解压={s['bad-format']} 失败={s['failed']} 总计={total}"
    )


# ─── 主循环 ──────────────────────────────────────────────────

_LAST_ALIST_CHECK = 0       # 上次检查 downloading 的时间戳
_ALIST_CHECK_INTERVAL = 45  # 最短间隔（秒），防 OpenList 盲扫被封

def run(engine):
    """
    生产主循环。无限运行，Ctrl+C 退出。
    engine: 已经登录好且处于 target_dir 的 BrowserEngine 实例
    """
    logger.info("=" * 50)
    logger.info("生产主循环启动")
    logger.info("=" * 50)

    global _LAST_ALIST_CHECK

    loop_count = 0

    while True:
        loop_count += 1

        # 先查数据库，看有没有活要干
        ready_task = get_first_by_status("ready")
        pending_task = get_first_by_status("pending")
        downloading_count = count_by_status("downloading")

        # ── adding 超时检测（常规 90-100s，超 300s 视为 stuck） ──
        import sqlite3 as _sqlite3
        import datetime as _datetime
        _stuck_threshold = 300
        _conn = _sqlite3.connect(str(Path(__file__).parent / "tasks.db"))
        _conn.row_factory = _sqlite3.Row
        for _row in _conn.execute("SELECT * FROM tasks WHERE status='adding'"):
            _task = dict(_row)
            _elapsed = time.time() - _datetime.datetime.strptime(
                _task["created_at"], "%Y-%m-%d %H:%M:%S"
            ).timestamp()
            if _elapsed > _stuck_threshold:
                update_status(_task["id"], "failed")
                logger.warning(
                    f"⏰ #{_task['queue_order']} adding 超时 ({_elapsed:.0f}s)，"
                    f"标记为 failed"
                )
        _conn.close()

        # ── downloading 检查（限频调用 Alist API） ──
        if downloading_count > 0:
            now = time.time()
            if now - _LAST_ALIST_CHECK >= _ALIST_CHECK_INTERVAL:
                try:
                    changed = check_downloading_completion()
                    _LAST_ALIST_CHECK = now
                    if changed:
                        log_cycle_summary()
                        continue  # 有任务 ready 了，下一轮刷新去处理
                except Exception as e:
                    logger.warning(f"downloading 检查异常: {e}")
            else:
                logger.debug(f"Alist API 冷却中，剩余 {_ALIST_CHECK_INTERVAL - (now - _LAST_ALIST_CHECK):.0f}s")
        else:
            # 没有 downloading 任务时强制重置计时器，下次有了立即可查
            _LAST_ALIST_CHECK = 0

        # 需要操作浏览器的任务：ready（解压分享）或 pending（云添加）
        needs_refresh = ready_task is not None or pending_task is not None

        if not needs_refresh:
            log_cycle_summary()
            logger.debug(f"空循环 #{loop_count}，等待 {LOOP_INTERVAL}s...")
            time.sleep(LOOP_INTERVAL)
            continue

        # 有浏览器任务 → 刷新页面
        try:
            refresh_and_goto_target(engine)
        except Exception as e:
            logger.error(f"刷新失败，等待重试: {e}")
            time.sleep(10)
            continue

        # ── 检查 ready 任务（优先处理） ──
        ready_task = get_first_by_status("ready")
        if ready_task:
            folder_name = ready_task["folder_name"]
            task_id = ready_task["id"]
            logger.info(f"处理 ready 任务 #{ready_task['queue_order']}: [{folder_name}]")

            update_status(task_id, "decompressing")

            try:
                # 先等 3 秒让页面稳定
                time.sleep(3)

                # 用已经写好的导航链进入时间戳文件夹：PAN_BASE → target_dir → click 进入
                engine.navigate_to(PAN_BASE)
                time.sleep(2)
                engine.navigate_to_target_dir()
                time.sleep(2)
                engine.click_file_by_title(folder_name)
                time.sleep(2)

                # 执行解压分享（复用 step3_monitor 的 _rename_and_decompress）
                from step3_monitor import _rename_and_decompress
                process_result = _rename_and_decompress(engine, folder_name)

                # 解压启动失败（如文件不可解压）→ 直接标 bad-format，不继续分享
                if not process_result.get("success", False):
                    update_status(task_id, "bad-format")
                    logger.error(f"❌ #{ready_task['queue_order']} 解压失败: {process_result.get('message', '')}")
                    log_cycle_summary()
                    continue

                # 执行分享
                from step4_share import run as share_run
                # 需要 file_id（原 step4 需要）
                # 从文件夹列表中找到 file_id
                # 等页面加载完（100+ 个文件夹可能较慢），最多重试 10 次，每次等 5 秒
                import time as _time_retry
                file_id = ""
                folder_list = []
                for _retry in range(10):
                    _time_retry.sleep(5)
                    folder_list = engine.get_folder_info_list()
                    for f in folder_list:
                        if f["name"] == folder_name:
                            file_id = f["file_id"]
                            break
                    if file_id:
                        logger.info(f"第 {_retry+1} 次重试找到 file_id: {file_id}")
                        break
                    logger.info(f"等待 target_dir 列表加载... 已扫到 {len(folder_list)} 个条目，第 {_retry+1}/10 次重试")

                if not file_id:
                    logger.warning(f"重试 10 次后仍未找到 [{folder_name}]，最后扫描到 {len(folder_list)} 个条目")
                    # 打印前 10 个让 debug 看
                    for _f in folder_list[:10]:
                        logger.warning(f"  现有条目: {_f['name']} (file_id={_f['file_id']})")

                if file_id:
                    share_result = share_run(engine, file_id)
                    if share_result["success"]:
                        update_share_url(task_id, share_result["share_url"])
                        logger.info(f"✅ #{ready_task['queue_order']} 完成: {share_result['share_url']}")
                    else:
                        update_status(task_id, "bad-format")
                        logger.error(f"❌ #{ready_task['queue_order']} 分享失败: {share_result}")
                else:
                    update_status(task_id, "bad-format")
                    logger.error(f"❌ #{ready_task['queue_order']} 未找到 file_id")
            except Exception as e:
                update_status(task_id, "bad-format")
                logger.error(f"❌ #{ready_task['queue_order']} 处理异常: {e}")

            log_cycle_summary()
            continue  # 处理完 ready 立即下一轮（可能还有新的 ready）

        # ── 检查 downloading 完成情况 ──
        downloading_count = count_by_status("downloading")
        if downloading_count > 0:
            changed = check_downloading_completion()
            if changed:
                log_cycle_summary()
                continue  # 有变化，下一轮处理 ready

        # ── 检查 pending 任务（云添加） ──
        pending_task = get_first_by_status("pending")
        if pending_task:
            folder_name = pending_task["folder_name"]
            url = pending_task["url"]
            task_id = pending_task["id"]
            logger.info(f"处理 pending 任务 #{pending_task['queue_order']}: [{folder_name}]")

            update_status(task_id, "adding")

            try:
                # step1: 新建文件夹
                step1_result = step1_new_folder.run(engine, folder_name)
                if not step1_result["success"]:
                    update_status(task_id, "failed")
                    logger.error(f"❌ #{pending_task['queue_order']} 新建文件夹失败")
                    log_cycle_summary()
                    continue

                file_id = step1_result.get("file_id", "")

                # 等页面稳定 3-5 秒
                wait_time = random.randint(3, 5)
                logger.info(f"等待 {wait_time}s 让文件夹页面稳定...")
                time.sleep(wait_time)

                # step2: 云添加
                step2_result = step2_cloud_upload.run(engine, url, folder_name=folder_name)
                if not step2_result["success"]:
                    update_status(task_id, "failed")
                    logger.error(f"❌ #{pending_task['queue_order']} 云添加失败")
                    log_cycle_summary()
                    continue

                # 状态改为 downloading（后续靠 check_downloading_completion 查文件夹内文件）
                update_status(task_id, "downloading")

                logger.info(f"✅ #{pending_task['queue_order']} 云添加提交成功，等待下载")

            except Exception as e:
                update_status(task_id, "failed")
                logger.error(f"❌ #{pending_task['queue_order']} 新建/云添加异常: {e}")

            log_cycle_summary()
            continue  # 去下一轮

        # ── 啥都没有 ──
        log_cycle_summary()
        logger.debug(f"空循环 #{loop_count}，等待 {LOOP_INTERVAL}s...")
        time.sleep(LOOP_INTERVAL)


# ─── 入口 ────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="解析站 - 生产主循环")
    parser.add_argument("--debug", action="store_true", help="附加到已有浏览器（9222 端口）")
    parser.add_argument("--port", type=int, default=9222, help="调试端口（默认 9222）")
    parser.add_argument("--headless", action="store_true", help="无头模式")
    parser.add_argument("--browser", default="edge", choices=["edge", "chrome"], help="浏览器类型")

    args = parser.parse_args()

    # 初始化数据库
    init_db()

    # 初始化浏览器
    engine = BrowserEngine(
        headless=args.headless,
        attach=args.debug,
        debug_port=args.port,
        browser_type=args.browser
    )

    try:
        engine.login_and_inject_cookies()
        engine.inject_clipboard_hijack()

        # 先导航到 target_dir
        engine.navigate_to(PAN_BASE)
        time.sleep(2)
        engine.navigate_to_target_dir()

        # 进入主循环
        run(engine)

    except KeyboardInterrupt:
        logger.info("用户中断，退出主循环")
    except Exception as e:
        logger.error(f"主循环异常退出: {e}")
        raise
    finally:
        engine.close()
