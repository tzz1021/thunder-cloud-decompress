"""
step4_share.py — 阶段4：创建分享链接

流程:
  1. 回到在线解压站点食用目录
  2. 通过 data-file-id 找到对应的 <li>，勾选复选框
  3. 点击"分享"按钮（弹出分享弹窗）
  4. 点击"创建链接"（此时迅雷写入系统剪贴板）
  5. 用 win32clipboard 读取系统剪贴板获取分享链接
  6. 返回

调用者需传入：
  - engine: BrowserEngine 实例
  - file_id: 文件夹的 data-file-id（来自字典1）
"""

import time
import re
import logging

logger = logging.getLogger("step4_share")

TARGET_DIR = "https://pan.xunlei.com/?path=%2F%E5%9C%A8%E7%BA%BF%E8%A7%A3%E5%8E%8B%E7%AB%99%E7%82%B9%E9%A3%9F%E7%94%A8"
PAN_BASE = "https://pan.xunlei.com"

try:
    import win32clipboard
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False
    logger.warning("win32clipboard 不可用，尝试 pip install pywin32")


def _extract_share_url(raw: str) -> str:
    """
    从剪贴板原始文本中提取分享链接。
    迅雷剪贴板格式："链接：https://pan.xunlei.com/s/XXX?pwd=xxx# 复制这段内容..."
    取 http 开头到 # 之间的部分（不含 # 后的 tail）。
    """
    m = re.search(r'(https?://[^\s#]+#[^\s]*)', raw)
    if m:
        url = m.group(1)
        # 如果 # 后有空格或中文，截断到 # 为止
        hash_idx = url.find('#')
        if hash_idx > 0:
            url = url[:hash_idx]
        if url:
            return url.strip()
    return raw


def _get_clipboard_text() -> str:
    """
    通过 win32clipboard 读取 Windows 系统剪贴板文本。
    完全绕过浏览器层，什么 JS/CDP 限制都不管用。
    """
    if not HAS_WIN32:
        return ""

    try:
        win32clipboard.OpenClipboard()
        try:
            data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            if data:
                text = data.strip()
                logger.debug(f"win32clipboard 读取成功: {text[:80]}...")
                return text
        except TypeError:
            # 剪贴板不是文本格式
            pass
        finally:
            win32clipboard.CloseClipboard()
    except Exception as e:
        logger.warning(f"win32clipboard 读取失败: {e}")

    return ""


def _retry_get_share_url(max_attempts: int = 4, interval: float = 5.0) -> str:
    """
    持续监听系统剪贴板，直到拿到合法的迅雷分享链接。
    
    校验规则：
      - 正则提取 http 链接
      - 提取到的链接必须以 https://pan.xunlei.com 开头
    任一条件不满足就继续轮询（因为剪贴板可能还没被迅雷写入，或者被其他程序污染）。
    
    参数:
      max_attempts: 最大轮询次数（默认 20 次 ≈ 20 秒）
      interval: 每次轮询间隔秒数（默认 1 秒）
    
    返回:
      str: 合法的迅雷分享链接（空字符串表示超时未获取到）
    """
    for attempt in range(1, max_attempts + 1):
        raw_text = _get_clipboard_text()
        if raw_text:
            candidate = _extract_share_url(raw_text)
            if candidate and candidate.startswith("https://pan.xunlei.com"):
                logger.info(f"✅ 第 {attempt} 次轮询获取到合法分享链接: {candidate[:80]}...")
                return candidate
            else:
                logger.debug(f"第 {attempt} 次轮询: 剪贴板内容非合法分享链接 ({candidate[:60] if candidate else '空'}...)，继续等待")
        else:
            logger.debug(f"第 {attempt} 次轮询: 剪贴板为空，继续等待")
        time.sleep(interval)
    
    logger.warning(f"⚠️ 轮询 {max_attempts} 次后仍未获取到合法迅雷分享链接")
    return ""


def run(engine, file_id: str) -> dict:
    """
    执行创建分享流程。
    
    返回:
      {
        "share_url": str,          # 分享链接
        "file_id": str,
        "success": bool
      }
    """
    result = {"share_url": "", "file_id": file_id, "success": False}

    # ── 步骤1: 回到在线解压站点食用目录 ──
    engine.navigate_to(PAN_BASE)
    time.sleep(2)
    engine.navigate_to_target_dir()

    # ── 步骤2: 勾选文件夹 ──
    logger.info(f"勾选文件夹: file_id={file_id}")
    li_element = engine.get_li_by_file_id(file_id)
    engine.click_checkbox_for_li(li_element)

    # ── 步骤3: 点击"分享"按钮弹出分享弹窗 ──
    logger.info("点击分享按钮")
    engine.click_share_button()
    time.sleep(1)

    # ── 步骤4: 点击"创建链接"（此时迅雷写入系统剪贴板） ──
    logger.info("点击创建链接按钮")
    try:
        engine.click_create_share()
    except Exception as e:
        logger.warning(f"创建链接按钮点击失败: {e}")

    # 等系统剪贴板写入
    time.sleep(2)

    # ── 步骤5: 轮询系统剪贴板，直到拿到合法迅雷分享链接 ──
    logger.info("轮询系统剪贴板，等待迅雷写入分享链接...")
    share_url = _retry_get_share_url(max_attempts=4, interval=5.0)
    if share_url:
        result["share_url"] = share_url
        result["success"] = True
        return result

    # ── 步骤6: 兜底 — 点"复制链接"后再轮询一次 ──
    logger.info("点击复制链接按钮（兜底）")
    try:
        engine.click_copy_link()
    except Exception as e:
        logger.warning(f"复制链接按钮点击失败: {e}")

    share_url = _retry_get_share_url(max_attempts=4, interval=5.0)
    if share_url:
        result["share_url"] = share_url
        result["success"] = True
        return result

    logger.error("❌ 未能获取到分享链接")
    return result
