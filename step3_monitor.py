"""
step3_monitor.py — 阶段3：监听修改时间 + 重命名 + 解压

流程:
  [快速方式] 进入刚刚创建的时间戳文件夹 → Selenium 保持不动
    → 启动 OS 秒传监听（聚焦当前文件夹，3次额外机会，间隔3秒）
    → 发现修改时间变化 → 立即执行右键→重命名→解压（Selenium 已在文件夹内）
    → 3次机会耗尽无变化 → 回到常规 OS 监听（扫描所有文件夹）

  [常规 OS 监听] 每 3 秒 os.scandir 本地挂载目录，
    对比所有文件夹的修改时间，发现变化 → 导航进入该文件夹 → 执行后续操作

调用者需传入：
  - engine: BrowserEngine 实例
  - dict2: 文件夹名 → 修改时间 映射（本次扫描用）
  - processed_set: 已处理的文件夹名集合
  - new_folder_name: str，刚创建的时间戳文件夹名（用于秒传监听）
  - max_wait_seconds: 单次最大等待时间（默认 1000 秒）
  - mount_path: str，clouddrive2 挂载的本地目录路径（默认 W:\\WebDAV\\online_prase_site）
"""

import os
import time
import logging
import urllib.parse
from pathlib import Path

from browser_engine import DecompressFailedError

logger = logging.getLogger("step3_monitor")

TARGET_DIR = "https://pan.xunlei.com/?path=%2F%E5%9C%A8%E7%BA%BF%E8%A7%A3%E5%8E%8B%E7%AB%99%E7%82%B9%E9%A3%9F%E7%94%A8"
PAN_BASE = "https://pan.xunlei.com"
CHILD_DIR_TEMPLATE = "https://pan.xunlei.com/?path=%2F%E5%9C%A8%E7%BA%BF%E8%A7%A3%E5%8E%8B%E7%AB%99%E7%82%B9%E9%A3%9F%E7%94%A8%2F{foldername}"

DEFAULT_MOUNT_PATH = r"W:\WebDAV\online_prase_site"

# 秒传监听：额外扫描次数
EXTRA_SCAN_COUNT = 3


def scan_local_times(mount_path: str) -> dict:
    """
    OS 级别扫描本地挂载目录下所有文件夹的修改时间。
    只扫 mount_path 这一层子目录，不递归。

    返回 dict: {文件夹名: st_mtime(float)}
    """
    result = {}
    try:
        with os.scandir(mount_path) as it:
            for entry in it:
                if entry.is_dir():
                    mtime = entry.stat().st_mtime
                    result[entry.name] = mtime
    except FileNotFoundError:
        logger.error(f"挂载目录不存在: {mount_path}")
    except PermissionError:
        logger.error(f"无权限读取: {mount_path}")
    except Exception as e:
        logger.error(f"扫描本地目录失败: {e}")
    return result


def _rename_and_decompress(engine, folder_name: str) -> dict:
    """
    在子文件夹内执行重命名+解压流程。
    注意：调用前 engine 必须在文件所在文件夹内，无需导航。
    """
    result = {"folder_name": folder_name, "success": False, "message": ""}

    try:
        original_title = engine.right_click_first_file_in_pan()
        if not original_title:
            original_title = "file.zip"
            logger.warning("未获取到文件名，使用默认 file.zip")
    except Exception as e:
        original_title = "file.zip"
        logger.warning(f"右键文件失败: {e}")

    new_name = f"{folder_name}.zip"

    engine.click_context_menu_item("重命名")
    time.sleep(1)

    input_el = engine.find_rename_input()
    input_el.clear()
    input_el.send_keys(new_name)
    time.sleep(0.5)

    engine.click_rename_confirm()
    logger.info(f"已重命名: {original_title} → {new_name}")

    engine.click_file_by_title(new_name)

    try:
        engine.click_decompress()
    except DecompressFailedError as e:
        result["success"] = False
        result["message"] = f"文件不可解压: {e}"
        logger.warning(f"文件夹 {folder_name} 标记为不可解压: {e}")
        # 回到根目录，不抛异常
        engine.navigate_to(PAN_BASE)
        time.sleep(1)
        engine.navigate_to_target_dir()
        return result

    engine.navigate_to(PAN_BASE)
    time.sleep(1)
    engine.navigate_to_target_dir()

    result["success"] = True  # 解压已启动即视为成功，后续解压进度由其他模块上报
    result["message"] = f"已启动解压: {new_name}"
    logger.info(f"文件夹 {folder_name} 处理完毕")
    return result


def run(engine, dict2: dict, processed_set: set,
        new_folder_name: str = "",
        max_wait_seconds: int = 1000,
        mount_path: str = DEFAULT_MOUNT_PATH) -> dict:
    """
    监听文件夹修改时间变化，完成下载后重命名+解压。

    new_folder_name 传值时的行为：
      1. Selenium 进入该文件夹保持不动
      2. 下次常规扫描+3次额外扫描聚焦此文件夹
      3. 发现变化立即处理（Selenium 已在文件夹内）
      4. 3次用完无变化 → 回到常规扫描所有文件夹

    返回:
      {"folder_name": str, "success": bool, "message": str}
    """
    elapsed = 0
    result = {"folder_name": "", "success": False, "message": ""}

    extra_mode = False       # 是否处于秒传监听模式
    extra_remaining = 0      # 剩余额外扫描次数
    extra_folder = ""        # 秒传监听的文件夹名

    # ── 导航 ──
    if new_folder_name:
        import random as _r
        logger.info(f"快速方式: 进入文件夹 {new_folder_name}，等待秒传")

        engine.navigate_to(PAN_BASE)
        time.sleep(_r.uniform(1.0, 2.0))
        engine.navigate_to_target_dir()
        time.sleep(_r.uniform(2.0, 3.0))

        # 进入时间戳文件夹，Selenium 保持在此页面不动
        engine.click_file_by_title(new_folder_name)
        time.sleep(_r.uniform(1.0, 3.0))

        # 启动秒传监听模式
        extra_mode = True
        extra_remaining = EXTRA_SCAN_COUNT
        extra_folder = new_folder_name
        logger.info(f"秒传监听激活: 聚焦 [{extra_folder}]，剩余 {extra_remaining} 次额外扫描")
    else:
        engine.navigate_to(PAN_BASE)
        time.sleep(2)
        engine.navigate_to_target_dir()

    # ── OS 监听主循环 ──
    logger.info(f"开始 OS 监听: {mount_path}")

    while elapsed < max_wait_seconds:
        current_times = scan_local_times(mount_path)

        # ── 秒传监听模式：只扫额外文件夹 ──
        if extra_mode and extra_remaining > 0 and extra_folder:
            mtime = current_times.get(extra_folder)
            prev_mtime = dict2.get(extra_folder)

            if mtime is not None:
                if prev_mtime is not None and abs(mtime - prev_mtime) > 1.0:
                    logger.info(f"秒传命中! [{extra_folder}] {prev_mtime:.1f} → {mtime:.1f}")
                    # Selenium 已在文件夹内，直接执行
                    process_result = _rename_and_decompress(engine, extra_folder)
                    processed_set.add(extra_folder)
                    dict2[extra_folder] = mtime
                    process_result["folder_name"] = extra_folder
                    return process_result
                elif prev_mtime is None:
                    # 首次记录
                    dict2[extra_folder] = mtime
                    logger.debug(f"秒传监听: 记录 [{extra_folder}] mtime={mtime:.1f}")

            extra_remaining -= 1
            if extra_remaining > 0:
                logger.info(f"秒传监听: [{extra_folder}] 剩余 {extra_remaining} 次额外扫描")
            else:
                logger.info(f"秒传监听: [{extra_folder}] 额外扫描耗尽，切换回常规扫描")
                extra_mode = False
                # 回到 target_dir 等待常规扫描
                engine.navigate_to(PAN_BASE)
                time.sleep(1)
                engine.navigate_to_target_dir()
        else:
            # ── 常规模式：扫描所有文件夹 ──
            for folder_name, current_mtime in current_times.items():
                if folder_name in processed_set:
                    continue

                if folder_name in dict2:
                    prev_mtime = dict2[folder_name]
                    if abs(current_mtime - prev_mtime) > 1.0:
                        logger.info(f"检测到修改时间变化: {folder_name}  {prev_mtime:.1f} → {current_mtime:.1f}")
                        child_url = CHILD_DIR_TEMPLATE.format(
                            foldername=urllib.parse.quote(folder_name, safe=''))
                        engine.navigate_to(child_url)
                        time.sleep(2)

                        process_result = _rename_and_decompress(engine, folder_name)
                        processed_set.add(folder_name)
                        dict2[folder_name] = current_mtime
                        process_result["folder_name"] = folder_name
                        return process_result
                else:
                    dict2[folder_name] = current_mtime
                    logger.debug(f"记录初始时间: {folder_name} = {current_mtime:.1f}")

            # 更新 dict2
            for folder_name, current_mtime in current_times.items():
                if folder_name in dict2:
                    dict2[folder_name] = current_mtime

        time.sleep(3)
        elapsed += 3

        if elapsed % 30 == 0:
            mode_tag = f"秒传监听[{extra_folder}]" if extra_mode else "常规监听"
            logger.info(f"{mode_tag} 中... 已等待 {elapsed}s, 跟踪 {len(dict2)} 个文件夹")

    result["message"] = f"超时: {max_wait_seconds} 秒内未检测到修改时间变化"
    logger.warning(result["message"])
    return result
