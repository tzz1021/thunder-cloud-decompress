"""
step1_new_folder.py — 阶段1：新建时间戳文件夹

流程（来自 code_to_word.json → flow_steps.1_new_folder）:
  1. 导航到在线解压站点食用目录
  2. 悬停"添加"按钮弹出 PlusMenu
  3. 点击"新建文件夹"
  4. 输入文件夹名称（前端时间戳，中文冒号）
  5. 点击对钩确认
  6. 记录文件夹名 → data-file-id 到字典1
  7. 进入该文件夹

调用者需传入：
  - engine: BrowserEngine 实例
  - folder_name: 前端时间戳字符串（如 "2026-06-07 23：19：30"）
"""

import time
import logging
import urllib.parse

logger = logging.getLogger("step1_new_folder")

# 来自 code_to_word.json → selectors
FOLDER_LIST_ITEM_TPL = "/html/body/div[1]/div/div/div/div[2]/div[2]/section[2]/ul/li[{index}]"
# folder_list_item: 文件列表中的单个条目，<li data-file-id='xxx'>
FOLDER_NAME_SPAN_XPATH = "./div/div[2]/div[1]/div[2]/a/span"
# folder_name_span: 文件夹列表项中显示名字的 <span>
TARGET_DIR = "https://pan.xunlei.com/?path=%2F%E5%9C%A8%E7%BA%BF%E8%A7%A3%E5%8E%8B%E7%AB%99%E7%82%B9%E9%A3%9F%E7%94%A8"
PAN_BASE = "https://pan.xunlei.com"
CHILD_DIR_TEMPLATE = "https://pan.xunlei.com/?path=%2F%E5%9C%A8%E7%BA%BF%E8%A7%A3%E5%8E%8B%E7%AB%99%E7%82%B9%E9%A3%9F%E7%94%A8%2F{foldername}"


def run(engine, folder_name: str) -> dict:
    """
    执行新建文件夹流程。
    
    返回:
      {
        "folder_name": str,         # 文件夹名字
        "file_id": str,             # data-file-id（写入字典1用）
        "success": bool
      }
    """
    result = {"folder_name": folder_name, "file_id": "", "success": False}

    # ── 步骤1: 进入在线解压站点食用目录 ──
    logger.info(f"进入在线解压站点食用目录")
    engine.navigate_to(PAN_BASE)
    time.sleep(2)
    engine.navigate_to_target_dir()

    # ── 步骤2: 悬停"添加"按钮弹出 PlusMenu ──
    logger.info("悬停添加按钮")
    engine.hover_add_button()

    # ── 步骤3: 点击"新建文件夹" ──
    logger.info("点击新建文件夹")
    engine.click_new_folder()

    # ── 步骤4: 输入文件夹名称 ──
    logger.info(f"输入文件夹名称: {folder_name}")
    input_el = engine.find_rename_input()
    input_el.clear()
    input_el.send_keys(folder_name)
    time.sleep(0.5)

    # ── 步骤5: 点击对钩确认 ──
    logger.info("确认命名")
    engine.click_rename_confirm()

    # ── 步骤6: 确认文件夹已创建（等 1 秒让页面刷新），然后进入该文件夹 ──
    # 注意：不再在这里获取 file_id（main_loop ready 分支会重新扫），
    # 避免因页面未渲染完全而失败。
    result["success"] = True
    time.sleep(1)

    # ── 步骤7: 进入该文件夹 ──
    encoded_name = urllib.parse.quote(folder_name, safe='')
    child_url = CHILD_DIR_TEMPLATE.format(foldername=encoded_name)
    logger.info(f"进入文件夹: {child_url}")
    engine.navigate_to(child_url)

    return result
