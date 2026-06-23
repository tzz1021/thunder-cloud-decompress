"""
step2_cloud_upload.py — 阶段2：云添加（"更改"目录方案）

流程（来自 code_to_word.json → flow_steps.2_cloud_upload）:
  1. 悬停"添加"按钮弹出 PlusMenu → 点击"添加链接"
  2. 在 textarea 中填写直链 URL
  3. 点击"更改"链接打开树形目录选择框
  4. 在树形目录中：
     a. 找到"在线解压站点食用"节点 → 点击展开箭头
     b. 在其子目录中找到时间戳文件夹 → 随机点图标/label/复选框选中
  5. 点击目录选择框的"确定"关闭目录选择
  6. 点击云添加弹窗的"确定"提交任务
  7. 回到在线解压站点食用目录

前置条件：已在文件夹内（由 step1 创建并进入）
调用者需传入：
  - engine: BrowserEngine 实例
  - url: 用户提交的直链 URL
  - folder_name: 时间戳文件夹名（用于在树形目录中定位）

防检测策略：
  - 每一步之间随机等待 0.5~2.5 秒
  - 选中文件夹时从图标/label/复选框随机选取
  - 不固定时间，模拟人类操作节奏
"""

import time
import random
import logging

logger = logging.getLogger("step2_cloud_upload")

PAN_BASE = "https://pan.xunlei.com"
TARGET_DIR = "https://pan.xunlei.com/?path=%2F%E5%9C%A8%E7%BA%BF%E8%A7%A3%E5%8E%8B%E7%AB%99%E7%82%B9%E9%A3%9F%E7%94%A8"

# 面包屑：降级回到在线解压站点食用目录用
BREADCRUMB_XPATH = "/html/body/div[1]/div/div/div/div[2]/div[2]/section/div[2]/div[1]/div/div/div/div[3]/div/span[1]/a"
TARGET_DIR_TITLE_XPATH = "//a[@title='在线解压站点食用']"


def _random_wait(min_s=0.5, max_s=2.5):
    """随机等待，模拟人类操作间隔"""
    t = random.uniform(min_s, max_s)
    time.sleep(t)


def _navigate_back_to_target(engine):
    """
    云添加完成后回到"在线解压站点食用"目录。
    尝试顺序：面包屑点击 → title 点击 → URL 跳转+点击
    """
    _random_wait(1.0, 2.0)

    # 尝试1: 面包屑 - 通过 JS XPath 查找点击
    try:
        js = """
        (() => {
            const el = document.evaluate(
                "/html/body/div[1]/div/div/div/div[2]/div[2]/section/div[2]/div[1]/div/div/div/div[3]/div/span[1]/a",
                document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
            ).singleNodeValue;
            if (el) { el.scrollIntoView({block:'center'}); el.click(); return true; }
            return false;
        })()
        """
        if engine._cdp.eval(js) == "true":
            _random_wait(2.0, 3.0)
            logger.info("面包屑回到目标目录")
            return
    except Exception:
        pass

    # 尝试2: title 定位点击
    try:
        js = """
        (() => {
            const el = document.querySelector('a[title="在线解压站点食用"]');
            if (el) { el.click(); return true; }
            return false;
        })()
        """
        if engine._cdp.eval(js) == "true":
            _random_wait(2.0, 3.0)
            logger.info("title 点击回到目标目录")
            return
    except Exception:
        pass

    # 尝试3: URL 跳转
    try:
        engine.navigate_to(TARGET_DIR)
        _random_wait(3.0, 4.0)
        logger.info("URL 跳转回到目标目录")
    except Exception:
        logger.warning("无法回到目标目录，继续")


def run(engine, url: str, folder_name: str = "") -> dict:
    """
    执行云添加流程（"更改"目录方案）。

    参数:
      engine: BrowserEngine 实例
      url: 直链 URL
      folder_name: 时间戳文件夹名（用于树形目录中定位）

    返回:
      {
        "url": str,
        "success": bool
      }
    """
    result = {"url": url, "success": False}

    # ── 步骤1: 悬停"添加"按钮弹出 PlusMenu → 点击"添加链接" ──
    logger.info("步骤1: 打开云添加弹窗")
    engine.hover_add_button()
    _random_wait()
    engine.click_add_link()
    _random_wait(3.0, 5.0)  # 等待云添加弹窗 CSS 动画渲染完成

    # ── 步骤2: 在 textarea 中填写直链 URL ──
    logger.info(f"步骤2: 填写 URL: {url[:80]}...")
    engine.fill_url_textarea(url)
    _random_wait()

    # ── 步骤3: 点击"更改"打开树形目录选择框 ──
    logger.info("步骤3: 点击更改目录")
    engine.click_change_folder()
    _random_wait(5.0, 8.0)  # 树形目录弹窗渲染较慢，确保完整展开

    # ── 步骤4: 在树形目录中选文件夹 ──
    logger.info("步骤4: 在树形目录中找到并选择目标文件夹")

    # 4a-d: 在树形目录中选文件夹（带重试：每轮重新搜根节点）
    logger.info("步骤4: 在树形目录中找到并选择目标文件夹")

    target_child = None
    for attempt in range(1, 4):
        # 每轮重新搜索根节点（应对弹窗变化/刷新）
        target_node = engine.find_tree_node_by_label("在线解压站点食用")
        if not target_node:
            logger.warning(f"第 {attempt} 轮：未找到'在线解压站点食用'，等待重试...")
            _random_wait(3.0, 5.0)
            continue

        # 点击展开箭头
        logger.info(f"第 {attempt} 轮：展开在线解压站点食用节点")
        engine.click_tree_node_expand(target_node)
        _random_wait(5.0, 8.0)

        # 遍历子目录找时间戳文件夹
        children = engine.get_tree_children(target_node)
        logger.info(f"第 {attempt} 轮：共 {len(children)} 个子目录")
        for child in children:
            label = engine.get_tree_node_label(child)
            if label == folder_name:
                target_child = child
                logger.info(f"  找到目标: [{label}]")
                break

        if target_child:
            break
        logger.info(f"  未找到 [{folder_name}]，{3-attempt} 次重试...")
        _random_wait(2.0, 3.0)

    if not target_child:
        logger.error(f"重试 3 次后仍未找到文件夹: {folder_name}")
        result["success"] = False
        return result

    # 4d: 随机点击选中目标文件夹
    logger.info(f"选中目标文件夹: {folder_name}")
    engine.click_tree_node_select(target_child)
    _random_wait()

    # ── 步骤5: 点击目录选择框的"确定" ──
    logger.info("步骤5: 确认目录选择")
    engine.click_tree_confirm()
    _random_wait()

    # ── 步骤6: 点击云添加弹窗的"确定"提交任务 ──
    logger.info("步骤6: 最终确认云添加")
    engine.click_cloud_upload_final_confirm()
    _random_wait(1.0, 2.0)

    # ── 步骤7: 回到在线解压站点食用目录 ──
    logger.info("步骤7: 回到在线解压站点食用目录")
    _navigate_back_to_target(engine)

    result["success"] = True
    logger.info("云添加流程完成")
    return result
