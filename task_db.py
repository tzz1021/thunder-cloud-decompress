"""
task_db.py — SQLite 任务队列

管理所有任务的增删查改，替代 dict2 / processed_set / 排队逻辑。

表结构:
  tasks:
    id              INTEGER PRIMARY KEY AUTOINCREMENT
    queue_order     INTEGER NOT NULL        -- 排队序号（按填写时间排序）
    folder_name     TEXT NOT NULL           -- 时间戳文件夹名（如 "2026-06-10 23：19：30"）
    url             TEXT NOT NULL           -- 原始直链 URL
    status          TEXT DEFAULT 'pending'  -- pending | downloading | ready | processing | done | failed
    share_url       TEXT DEFAULT ''         -- 分享链接（处理完成后写入）
    st_mtime        REAL DEFAULT 0          -- OS 检测到的修改时间
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP

状态流转:
  pending     → 用户提交 URL，等待云添加
  adding      → 正在新建文件夹 + 云添加（浏览器操作中）
  downloading → 已云添加，等待下载完成
  ready       → 下载完成，等待解压分享
  decompressing → 正在解压 + 分享（浏览器操作中）
  done        → 已完成，share_url 已生成
  failed      → 处理失败
"""

import sqlite3
import os
import logging
from pathlib import Path

logger = logging.getLogger("task_db")

DB_DIR = Path(__file__).parent
DB_PATH = str(DB_DIR / "tasks.db")

# ─── 初始化 ──────────────────────────────────────────────────

def init_db(db_path: str = DB_PATH):
    """创建数据库和表（如果不存在）"""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            queue_order INTEGER NOT NULL,
            folder_name TEXT NOT NULL,
            url TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            share_url TEXT DEFAULT '',
            st_mtime REAL DEFAULT 0,
            fp TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 兼容旧表：加 fp 列（如果已存在就忽略）
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN fp TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()
    logger.info(f"数据库初始化完成: {db_path}")

# ─── 增 ──────────────────────────────────────────────────────

def add_task(folder_name: str, url: str, fp: str = "", db_path: str = DB_PATH) -> int:
    """
    添加新任务。
    自动生成 queue_order（当前最大序号 + 1），created_at 使用北京时间。
    fp: 提交者的浏览器指纹，用于前端隔离。
    返回新任务的 queue_order。
    """
    conn = sqlite3.connect(db_path)
    cur = conn.execute("SELECT COALESCE(MAX(queue_order), 0) FROM tasks")
    max_order = cur.fetchone()[0]
    new_order = max_order + 1

    # 北京时间 CURRENT_TIMESTAMP 的修正
    import datetime
    bj_now = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        "INSERT INTO tasks (queue_order, folder_name, url, fp, created_at) VALUES (?, ?, ?, ?, ?)",
        (new_order, folder_name, url, fp, bj_now)
    )
    conn.commit()
    conn.close()

    logger.info(f"添加任务 #{new_order}: [{folder_name}] {url[:60]}...")
    return new_order

# ─── 查 ──────────────────────────────────────────────────────

def get_first_by_status(status: str, db_path: str = DB_PATH) -> dict:
    """
    获取指定状态的第一个任务（按 queue_order 升序）。
    返回 dict 或 None。
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "SELECT * FROM tasks WHERE status=? ORDER BY queue_order LIMIT 1",
        (status,)
    )
    row = cur.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def get_by_folder_name(folder_name: str, db_path: str = DB_PATH) -> dict:
    """通过文件夹名查找任务"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "SELECT * FROM tasks WHERE folder_name=? LIMIT 1",
        (folder_name,)
    )
    row = cur.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def count_by_status(status: str, db_path: str = DB_PATH) -> int:
    """统计指定状态的任务数"""
    conn = sqlite3.connect(db_path)
    cur = conn.execute("SELECT COUNT(*) FROM tasks WHERE status=?", (status,))
    count = cur.fetchone()[0]
    conn.close()
    return count

def get_queue_summary(db_path: str = DB_PATH) -> dict:
    """
    返回排队概览（供前端轮询用）
    {
      "pending": N,       # 等待云添加
      "downloading": N,   # 正在下载
      "ready": N,         # 等待解压
      "processing": N,    # 正在处理
      "done": N,          # 已完成
      "bad-format": N,    # 不可解压
      "failed": N         # 失败
    }
    """
    conn = sqlite3.connect(db_path)
    cur = conn.execute("""
        SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status
    """)
    rows = cur.fetchall()
    conn.close()
    summary = {"pending": 0, "adding": 0, "downloading": 0, "ready": 0,
               "decompressing": 0, "done": 0, "bad-format": 0, "failed": 0}
    for status, cnt in rows:
        if status in summary:
            summary[status] = cnt
    return summary

# ─── 改 ──────────────────────────────────────────────────────

def update_status(task_id: int, status: str, db_path: str = DB_PATH):
    """更新任务状态"""
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))
    conn.commit()
    conn.close()
    logger.info(f"任务 {task_id} 状态更新: {status}")

def update_share_url(task_id: int, share_url: str, db_path: str = DB_PATH):
    """更新分享链接，同时标记为 done"""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE tasks SET share_url=?, status='done' WHERE id=?",
        (share_url, task_id)
    )
    conn.commit()
    conn.close()
    logger.info(f"任务 {task_id} 分享链接已写入")

def update_st_mtime(task_id: int, st_mtime: float, db_path: str = DB_PATH):
    """更新本地文件夹修改时间（OS scandir 用 float）"""
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE tasks SET st_mtime=? WHERE id=?", (st_mtime, task_id))
    conn.commit()
    conn.close()

def update_st_mtime_string(task_id: int, modified_str: str, db_path: str = DB_PATH):
    """更新文件夹修改时间（Alist API 用字符串）"""
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE tasks SET st_mtime=? WHERE id=?", (modified_str, task_id))
    conn.commit()
    conn.close()

# ─── 删（调试用） ────────────────────────────────────────────

def clear_all(db_path: str = DB_PATH):
    """清空所有任务（调试用）"""
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM tasks")
    conn.commit()
    conn.close()
    logger.warning("所有任务已清空")

def get_all(db_path: str = DB_PATH, fp: str = "") -> list:
    """获取所有任务。如果指定 fp，只返回该 fp 提交的任务。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    if fp:
        cur = conn.execute("SELECT * FROM tasks WHERE fp=? ORDER BY queue_order", (fp,))
    else:
        cur = conn.execute("SELECT * FROM tasks ORDER BY queue_order")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows
