"""
manual_recover.py — 人工投放恢复工具

当进程崩溃 / 浏览器 DOM 变化 / 自动流程卡死后，
手动将任务标记为"已完成"并写入分享链接。

使用场景:
  - bad-format 的任务其实解压成功/可以手动分享
  - adding 卡死的任务可以从迅雷网页手动处理
  - 任何 status 不对的任务，人工介入修正

用法:
  python manual_recover.py
"""

import sqlite3
import os
import sys
from pathlib import Path

DB_PATH = str(Path(__file__).parent / "tasks.db")
STATUS_MAP = {
    "0": "pending",
    "1": "adding",
    "2": "downloading",
    "3": "ready",
    "4": "decompressing",
    "5": "done",
    "6": "bad-format",
    "7": "failed",
}


def get_all_tasks():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.execute("SELECT * FROM tasks ORDER BY queue_order")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def print_tasks(tasks):
    print(f"\n{'ID':>4} {'序号':>4} {'状态':<14} {'文件夹名':<30} {'分享链接':<45}")
    print("-" * 110)
    for t in tasks:
        sid = t["share_url"][:42] if t["share_url"] else "-"
        fn = t["folder_name"][:28] if t["folder_name"] else "-"
        print(f"{t['id']:>4} {t['queue_order']:>4} {t['status']:<14} {fn:<30} {sid:<45}")
    print()


def update_task(task_id, new_status, share_url=""):
    conn = sqlite3.connect(DB_PATH)
    if new_status == "done" and share_url:
        conn.execute(
            "UPDATE tasks SET status=?, share_url=? WHERE id=?",
            (new_status, share_url, task_id),
        )
    else:
        conn.execute(
            "UPDATE tasks SET status=? WHERE id=?",
            (new_status, task_id),
        )
    conn.commit()
    conn.close()
    print(f"  ✅ 任务 #{task_id} 已更新 → status={new_status}")


def main():
    os.system("cls" if os.name == "nt" else "clear")

    print("=" * 60)
    print("  人工投放 - 恢复工具")
    print("=" * 60)

    tasks = get_all_tasks()
    if not tasks:
        print("\n  (数据库为空)")
        input("\n按回车退出...")
        return

    # 只显示非 done、非空
    active = [t for t in tasks if t["status"] != "done"]
    if not active:
        print("\n  ✅ 全部任务已完成，无需恢复")
        input("\n按回车退出...")
        return

    print_tasks(active)

    # 选任务
    valid_ids = {str(t["id"]) for t in active}
    while True:
        raw = input("输入要恢复的任务 ID（或 q 退出）: ").strip()
        if raw.lower() == "q":
            return
        if raw in valid_ids:
            break
        print(f"  ❌ 无效 ID，可选: {', '.join(sorted(valid_ids, key=int))}")

    task_id = int(raw)
    task = next(t for t in active if t["id"] == task_id)

    print(f"\n  当前状态: {task['status']}")
    print(f"  文件夹:   {task['folder_name']}")
    print(f"  直链:     {task['url'][:60]}...")
    if task["share_url"]:
        print(f"  旧分享:   {task['share_url']}")

    # 选操作
    print("\n  操作选项:")
    print("    1) 标记为 done（需输入分享链接）")
    print("    2) 标记为 bad-format（不可解压，放弃）")
    print("    3) 标记为 failed（彻底失败）")
    print("    4) 回退 pending（让流程自动重试，⚠️ 同名文件夹可能冲突）")
    print("    5) 取消")

    while True:
        op = input("\n选择操作 (1-5): ").strip()
        if op in ("1", "2", "3", "4", "5"):
            break
        print("  无效，输入 1-5")

    if op == "5":
        print("  已取消")
        return

    if op == "1":
        raw = input("粘贴分享链接（支持从迅雷消息直接粘贴）: ").strip()
        if not raw:
            print("  ❌ 链接不能为空")
            return
        # 从"链接：https://...?pwd=xxx# 复制这段内容..." 中提取 URL
        import re
        m = re.search(r'(https?://[^\s#?]+(?:\?[^\s#]*)?(?:#[^\s]*)?)', raw)
        share_url = m.group(1) if m else raw
        # 去掉 # 后的尾巴
        hash_idx = share_url.find('#')
        if hash_idx > 0:
            share_url = share_url[:hash_idx]
        if share_url != raw:
            print(f"  📎 自动提取链接: {share_url[:80]}")
        if not share_url.startswith("http"):
            print("  ⚠️  链接不像标准 URL，确认继续？(y/n)")
            if input().strip().lower() != "y":
                return
        confirm = input(f"\n  确认将 #{task_id} 标记为 done？(y/n): ").strip().lower()
        if confirm == "y":
            update_task(task_id, "done", share_url)
    elif op == "2":
        confirm = input(f"\n  确认将 #{task_id} 标记为 bad-format？(y/n): ").strip().lower()
        if confirm == "y":
            update_task(task_id, "bad-format")
    elif op == "3":
        confirm = input(f"\n  确认将 #{task_id} 标记为 failed？(y/n): ").strip().lower()
        if confirm == "y":
            update_task(task_id, "failed")
    elif op == "4":
        print(f"\n  ⚠️  回退 pending 后，同名文件夹 [{task['folder_name']}] 已存在，")
        print(f"      step1_new_folder 将尝试创建同名文件夹 → 可能失败。")
        print(f"      除非你先把迅雷网盘里的旧文件夹删掉，否则建议用选项 1/2/3。")
        confirm = input(f"\n  确认回退 pending？(y/n): ").strip().lower()
        if confirm == "y":
            update_task(task_id, "pending")

    print("\n  ✅ 操作完成")
    print("\n  当前队列状态:")
    print_tasks(get_all_tasks())
    input("按回车退出...")


if __name__ == "__main__":
    main()
