"""
restart_once_a_day.py — 每日 00:00 自动轮换管理器

职责:
  1. 启动/管理 main_loop.py 和 step6_web.py 两个子进程
  2. 每天 00:00 自动:
     a. 终止两个子进程
     b. 清空 tasks.db（删表重建）
     c. 重启子进程（自动写新日期的日志文件）
  3. 日志重定向到 run_{日期}.log（管理自身的日志）

运行方式（后台无窗口）:
  python restart_once_a_day.py

停止方式:
  python -c "import os, signal; os.kill(<PID>, signal.SIGTERM)"
  或 任务管理器杀 python 进程
"""

import sys
import os
import time
import signal
import subprocess
import logging
import atexit
import hashlib
from pathlib import Path
from datetime import datetime, timedelta

# ─── 路径 ──────────────────────────────────────────────────

WORK_DIR = Path(__file__).parent
MAIN_LOOP = str(WORK_DIR / "main_loop.py")
STEP6_WEB = str(WORK_DIR / "step6_web.py")
TASKS_DB = str(WORK_DIR / "tasks.db")
DEBUG_PORT = "9222"

# ─── 管理日志 ──────────────────────────────────────────────

_log_today = time.strftime("%Y-%m-%d")
_log_file = WORK_DIR / f"run_{_log_today}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [manager] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(_log_file, encoding="utf-8", mode="a"),
        logging.StreamHandler(sys.stdout)
    ],
    force=True
)
logger = logging.getLogger("manager")

# ─── 进程管理 ──────────────────────────────────────────────

_procs: list[subprocess.Popen] = []

def kill_old_instances(script_name):
    """杀掉同名脚本的老进程，防止叠加（排除自身和已知子进程）"""
    import subprocess as _sp
    try:
        result = _sp.run(
            ['wmic', 'Process', 'Where', f'CommandLine like "%{script_name}%"', 'Get', 'ProcessId'],
            capture_output=True, text=True, timeout=5
        )
        this_pid = os.getpid()
        child_pids = {p.pid for p in _procs if p.pid}
        for line in result.stdout.splitlines():
            line = line.strip()
            if line and line.isdigit():
                pid = int(line)
                if pid != this_pid and pid != 0 and pid not in child_pids:
                    try:
                        os.kill(pid, signal.SIGTERM)
                        logger.info(f"已杀掉旧进程 {script_name}: PID={pid}")
                    except (OSError, PermissionError):
                        pass
    except Exception as e:
        logger.warning(f"清理旧进程 {script_name} 时异常: {e}")

def wait_for_port(port, timeout=30):
    """等待端口可用（轮询直到浏览器绑定端口）"""
    import socket
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(1)
    return False

def start_main_loop():
    """启动 main_loop.py（附加到 9222 Edge）"""
    # 等待端口就绪（开机时 Edge 可能还没绑定端口）
    if not wait_for_port(int(DEBUG_PORT), timeout=60):
        logger.error(f"端口 {DEBUG_PORT} 等待超时，浏览器可能未启动，退出")
        sys.exit(1)
    # 子进程自身的日志已经由 main_loop.py 写入文件，stdout 重定向到日志文件做兜底
    logfile = open(str(WORK_DIR / f"main_loop_stderr.log"), "a", encoding="utf-8")
    p = subprocess.Popen(
        [sys.executable, "-u", MAIN_LOOP, "--debug", "--port", DEBUG_PORT],
        cwd=str(WORK_DIR),
        stdout=logfile,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW  # 不弹黑窗
    )
    # 先 append 到 _procs（这样 kill_old 知道它是"自己人"），再杀旧的
    _procs.append(p)
    kill_old_instances("main_loop.py")
    logger.info(f"main_loop 已启动 (PID={p.pid})")
    return p

def start_step6_web():
    """启动 step6_web.py"""
    p = subprocess.Popen(
        [sys.executable, "-u", STEP6_WEB],
        cwd=str(WORK_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    # 先 append 到 _procs（这样 kill_old 知道它是"自己人"），再杀旧的
    _procs.append(p)
    kill_old_instances("step6_web.py")
    logger.info(f"step6_web 已启动 (PID={p.pid})")
    return p

def stop_all():
    """优雅终止所有子进程"""
    for p in _procs:
        if p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=5)
                logger.info(f"进程 PID={p.pid} 已终止")
            except Exception as e:
                logger.warning(f"进程 PID={p.pid} 终止异常: {e}")
                try:
                    p.kill()
                except:
                    pass
    _procs.clear()
    _rotated_today = False  # 标记当天是否已轮换

def clear_tasks_db():
    """清空 tasks 表（保留表结构），同时清理所有任务记录"""
    import sqlite3
    try:
        conn = sqlite3.connect(TASKS_DB)
        conn.execute("DELETE FROM tasks")
        conn.commit()
        conn.close()
        logger.info("tasks.db 已清空")
    except Exception as e:
        logger.error(f"清空 tasks.db 失败: {e}")

# ─── 每日轮换 ──────────────────────────────────────────────

def daily_rotate():
    """00:00 轮换操作：停止 → 清库 → 重启"""
    logger.info("=" * 40)
    logger.info("[轮换] 每日 00:00 轮换开始")
    logger.info("=" * 40)

    stop_all()
    time.sleep(2)
    clear_tasks_db()
    time.sleep(1)

    start_main_loop()
    start_step6_web()

    logger.info("✅ 每日轮换完成")

# ─── 主循环 ────────────────────────────────────────────────

def main():
    logger.info("=" * 50)
    logger.info("[启动] 解析站管理器启动")
    logger.info(f"工作目录: {WORK_DIR}")
    logger.info(f"Manager 日志: run_{_log_today}.log")
    logger.info(f"主循环日志: main_loop_{_log_today}.log")
    logger.info(f"Web 日志: step6_web_{_log_today}.log")
    logger.info("=" * 50)

    # 启动子进程
    start_main_loop()
    start_step6_web()

    # 计算到下一个 00:00 的秒数
    now = datetime.now()
    next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    seconds_to_midnight = (next_midnight - now).total_seconds()

    logger.info(f"距下次轮换: {seconds_to_midnight:.0f} 秒 ({next_midnight})")

    # 注册退出清理
    atexit.register(stop_all)

    _rotated_today = False

    # ── 文件监控：检测 .py 文件修改后自动重启 ──
    _watch_files = [MAIN_LOOP, STEP6_WEB, str(WORK_DIR / "browser_engine.py")]
    _watch_hashes = {}
    for _f in _watch_files:
        try:
            with open(_f, "rb") as _fh:
                _watch_hashes[_f] = hashlib.md5(_fh.read()).hexdigest()
        except FileNotFoundError:
            _watch_hashes[_f] = ""

    def _check_file_changes():
        nonlocal _watch_hashes
        for _f in _watch_files:
            try:
                with open(_f, "rb") as _fh:
                    _new_hash = hashlib.md5(_fh.read()).hexdigest()
                if _new_hash != _watch_hashes.get(_f, ""):
                    logger.info(f"📁 {Path(_f).name} 已修改，触发重启子进程...")
                    stop_all()
                    time.sleep(2)
                    start_main_loop()
                    start_step6_web()
                    # 更新 hash 表
                    for _ff in _watch_files:
                        try:
                            with open(_ff, "rb") as _ffh:
                                _watch_hashes[_ff] = hashlib.md5(_ffh.read()).hexdigest()
                        except FileNotFoundError:
                            _watch_hashes[_ff] = ""
                    return True
            except FileNotFoundError:
                pass
        return False

    # 每分钟检查一次子进程状态 + 文件变更 + 是否到点（检查窗口放宽到 2 分钟防漏）
    while True:
        time.sleep(60)  # 每分钟唤醒一次

        now = datetime.now()

        # 检查文件变更（优先于进程存活检查，改了直接重启）
        _check_file_changes()

        # 检查子进程是否还活着
        for i, p in enumerate(_procs):
            if p.poll() is not None:
                logger.warning(f"子进程 PID={p.pid} 已退出 (code={p.returncode})，重启中...")
                if i == 0:
                    start_main_loop()
                else:
                    start_step6_web()

        # 检查是否到 00:00 ~ 00:02 之间（2 分钟窗口防漏）
        if not _rotated_today and now.hour == 0 and now.minute < 3:
            daily_rotate()
            _rotated_today = True
            # 重新计算下次轮换
            next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


if __name__ == "__main__":
    main()
