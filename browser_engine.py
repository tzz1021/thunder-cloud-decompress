"""
browser_engine.py — Selenium 浏览器引擎模块

提供浏览器初始化、Cookie 注入、通用交互方法。
所有使用的 DOM 选择器来自 code_to_word.json 映射表。

两种运行模式:
  1. 默认模式: Selenium 自启动 Edge（带反检测）
  2. Debug 模式 (attach=True): 连接到已启动的 Edge/Chrome（--remote-debugging-port=9222）
     → 完全绕过自动化检测，因为你手动启动的浏览器

依赖:
  - msedgedriver.exe（已从 v1 迁移）
  - xunlei_cookies.json（已从 v1 迁移）
"""

import os
import json
import time
import logging
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service

logger = logging.getLogger("browser_engine")

# ─── 自定义异常 ────────────────────────────────────────────

class DecompressFailedError(Exception):
    """解压彻底失败，文件不可解压（非重试能解决的）"""
    pass

BASE_DIR = Path(__file__).parent
DRIVER_PATH = str(BASE_DIR / "msedgedriver.exe")
COOKIES_FILE = str(BASE_DIR / "xunlei_cookies.json")

# ─── 映射表引用（以下全部来自 code_to_word.json） ────────────────────

# urls
PAN_BASE = "https://pan.xunlei.com"
TARGET_DIR = "https://pan.xunlei.com/?path=%2F%E5%9C%A8%E7%BA%BF%E8%A7%A3%E5%8E%8B%E7%AB%99%E7%82%B9%E9%A3%9F%E7%94%A8"
CHILD_DIR_TEMPLATE = "https://pan.xunlei.com/?path=%2F%E5%9C%A8%E7%BA%BF%E8%A7%A3%E5%8E%8B%E7%AB%99%E7%82%B9%E9%A3%9F%E7%94%A8%2F{foldername}"

# selectors
ADD_BUTTON_XPATH = "/html/body/div[1]/div/div/div/div[2]/div[2]/section[1]/div[1]/div[1]/a[1]/span"
# add_button: 悬停后弹出 PlusMenu 的"添加"按钮，需要先 hover 让 PlusMenu 出现

NEW_FOLDER_MENU_CLASS = "pan-dropdown-menu-item pan-dropdown-divider"
# new_folder_in_menu: PlusMenu 中的"新建文件夹"菜单项，<a class='...'><span>新建文件夹</span></a>

RENAME_INPUT_PREFIX = "current-"
# rename_input: 新建文件夹/重命名时弹出的文本输入框，外层容器 class='current-1'，里面 <input type='text'>

RENAME_CONFIRM_CLASS = "xlpfont xlp-action-yes"
# rename_confirm_yes: 输入框旁边的确认对钩按钮，<i class='xlpfont xlp-action-yes'>

FILE_LINK_BY_TITLE_TPL = "//a[@title='{title}']"
# file_link_by_title: 通过 title 属性定位文件或文件夹的 <a> 标签

FOLDER_LIST_ITEM_TPL = "/html/body/div[1]/div/div/div/div[2]/div[2]/section[2]/ul/li[{index}]"
# folder_list_item: 文件列表中的单个条目，<li data-file-id='xxx' class='SourceListItem__item--XxpOC normal-item'>

FOLDER_NAME_SPAN_XPATH = "./div/div[2]/div[1]/div[2]/a/span"
# folder_name_span: 文件夹列表项中显示名字的 <span>，相对 li 的路径

FOLDER_DATE_DIV_XPATH = "./div/div[2]/div[2]/div[3]"
# folder_date_span: 文件夹列表项中显示修改时间的 <div>，文本格式如 '2026-06-07 17:06'

RIGHT_CLICK_MENU_ITEM_TPL = "//div[contains(@class,'contextMenu_ops')]/a[@class='pan-dropdown-menu-item' and text()='{text}']"
# right_click_menu_item: 右键菜单中的具体操作项，文本匹配："重命名"、"删除"等

CHECKBOX_INPUT_XPATH = "./div/div[1]/div/label/input"
# checkbox_input: 文件/文件夹前面的复选框，相对 li 的路径

SHARE_BUTTON_CLASS = "xlpfont xlp-share"
# share_button: 选中文件后顶部的分享按钮

CREATE_SHARE_BUTTON_CLASS = "dialog-web-create-share__button-box"
# create_share_button: 分享弹窗中的"创建链接"按钮，<div class='dialog-web-create-share__button-box'><button>

COPY_LINK_BUTTON_CLASS = "td-button dialog-web-create-share__button-copy-link"
# copy_share_link: 复制链接按钮（点击后链接写入剪贴板）

DECOMPRESS_BTN_XPATH = "//div[contains(@class,'decompress-file-tree-btn')]/a[text()='解压全部文件']"
# decompress_btn: 压缩包弹窗中的"解压全部文件"按钮

CLIPBOARD_HIJACK_JS = """
// clipboard_hijack_js: 拦截所有写剪贴板操作，捕获分享链接到 window.__copiedLink

// 方式1: 劫持 navigator.clipboard.writeText
Object.defineProperty(navigator, 'clipboard', {
  get: () => ({
    writeText: (text) => {
      window.__copiedLink = text;
      console.log('[clipboard-hijack] writeText captured:', text);
      return Promise.resolve();
    },
    readText: () => Promise.resolve(window.__copiedLink || '')
  })
});

// 方式2: 劫持 document.execCommand('copy')
// 迅雷可能用 execCommand 写入剪贴板
const origCopy = document.execCommand;
document.execCommand = function(command, ...args) {
  if (command === 'copy') {
    // 尝试从选中文本或隐藏输入框读取分享链接
    try {
      const selected = window.getSelection().toString();
      if (selected && selected.startsWith('http')) {
        window.__copiedLink = selected;
        console.log('[clipboard-hijack] execCommand copy captured:', selected);
      }
    } catch(e) {}
  }
  return origCopy.apply(this, [command, ...args]);
};

// 方式3: 劫持 ClipboardEvent（部分网盘用 copy 事件写入）
document.addEventListener('copy', function(e) {
  try {
    const text = e.clipboardData.getData('text/plain');
    if (text) {
      window.__copiedLink = text;
      console.log('[clipboard-hijack] copy event captured:', text);
    }
  } catch(e) {}
}, true);
"""


class BrowserEngine:
    """浏览器引擎，管理 Selenium 浏览器实例，提供通用交互方法

    参数:
      headless: 否启用无头模式（仅默认模式有效）
      attach (bool): 是否附加到已有浏览器（debug 模式）
      debug_port (int): 远程调试端口，默认 9222
      browser_type (str): "edge" 或 "chrome"，默认 "edge"

    使用方式（debug 模式）:
      1. 先手动启动 Edge:
         msedge.exe --remote-debugging-port=9222 --user-data-dir="C:\\selenium_user_data"
      2. 手动登录迅雷网页版
      3. 脚本中 BrowserEngine(attach=True) 直接接管
      → 无需 Cookie 注入，无需反检测，浏览器就是"正常浏览器"
    """

    def __init__(self, headless: bool = False, attach: bool = False,
                 debug_port: int = 9222, browser_type: str = "edge",
                 driver_path: str | None = None):
        self.is_logged_in = False
        self.attach_mode = attach
        self.custom_driver_path = driver_path

        if attach:
            self._attach_to_browser(browser_type, debug_port)
        else:
            self._launch_browser(headless)

    def _attach_to_browser(self, browser_type: str, debug_port: int):
        """
        附加到已启动的浏览器（debug 模式）。
        你提前手动启动 Edge/Chrome + 手动登录迅雷。
        """
        logger.info(f"附加到已有 {browser_type} (端口 {debug_port})...")

        if browser_type == "chrome":
            options = webdriver.ChromeOptions()
            options.add_experimental_option("debuggerAddress", f"127.0.0.1:{debug_port}")
            driver_class = webdriver.Chrome
            self.driver = driver_class(options=options)
        else:
            options = EdgeOptions()
            options.add_experimental_option("debuggerAddress", f"127.0.0.1:{debug_port}")
            # ⭐ 显式传 driver_path，不走 Selenium Manager（否则 win32/arm64 会报错）
            exec_path = self.custom_driver_path or DRIVER_PATH
            service = Service(executable_path=exec_path)
            self.driver = webdriver.Edge(service=service, options=options)

        self.is_logged_in = True  # 你手动登录的，信任
        logger.info(f"已附加到浏览器，当前标签页: {self.driver.title}")

    def _launch_browser(self, headless: bool):
        """
        Selenium 自启动浏览器（默认模式）。
        带反检测注入 + 剪贴板权限。
        """
        options = EdgeOptions()
        if headless:
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
        else:
            options.add_argument("--window-size=1400,900")

        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--enable-features=Clipboard")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        # 剪贴板读写权限
        prefs = {
            "profile.content_settings.exceptions.clipboard": {
                "https://pan.xunlei.com,https://api-pan.xunlei.com": {
                    "setting": 1  # 允许
                }
            }
        }
        options.add_experimental_option("prefs", prefs)

        exec_path = self.custom_driver_path or DRIVER_PATH
        service = Service(executable_path=exec_path)
        self.driver = webdriver.Edge(service=service, options=options)

        # 反检测
        self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh']});
            """
        })

    def inject_clipboard_hijack(self):
        """
        注入剪贴板劫持 JS。
        来自 code_to_word.json → clipboard_hijack_js。
        拦截 navigator.clipboard.writeText，将内容存到 window.__copiedLink。
        """
        self.driver.execute_script(CLIPBOARD_HIJACK_JS)
        logger.info("剪贴板劫持 JS 已注入")

    def get_copied_link(self) -> str:
        """读取被劫持的分享链接（来自 window.__copiedLink）"""
        return self.driver.execute_script("return window.__copiedLink || '';")

    def get_clipboard_via_cdp(self) -> str:
        """
        通过 CDP 读取系统剪贴板内容。
        绕过 JS 劫持限制，直接走浏览器协议读取。
        需要浏览器支持 Browser.getClipboard（Edge 148 支持）。
        """
        try:
            result = self.driver.execute_cdp_cmd("Browser.getClipboard", {})
            text = result.get("clipboard", {}).get("text", "")
            if text:
                logger.info(f"CDP 读取剪贴板成功: {text[:80]}...")
            return text
        except Exception as e:
            logger.warning(f"CDP 读取剪贴板失败: {e}")
            return ""

    def login_and_inject_cookies(self):
        """
        登录 + Cookie 处理。

        两种模式:
          - attach=True (debug 模式): 你已手动登录，直接导航到迅雷首页确认
          - attach=False (默认模式): 导航到首页 → 注入 Cookie → 刷新使其生效

        迅雷是 SPA，不能直接 URL 跳转子目录，必须先到根目录再点击。
        """
        if self.attach_mode:
            # debug 模式：你已手动登录，导航到首页确认登录状态
            logger.info("Debug 模式：跳过 Cookie 注入，直接导航到首页")
            self.driver.get(PAN_BASE)
            time.sleep(3)
            self.is_logged_in = True
            logger.info(f"当前页面标题: {self.driver.title}")
            return

        # 默认模式：自动启动 + Cookie 注入
        self.driver.get(PAN_BASE)
        time.sleep(3)

        if os.path.exists(COOKIES_FILE):
            with open(COOKIES_FILE, encoding="utf-8") as f:
                cookies = json.load(f)
            for name, value in cookies.items():
                try:
                    self.driver.add_cookie({
                        "name": name, "value": value,
                        "domain": ".xunlei.com", "path": "/",
                    })
                except Exception:
                    pass
            logger.info(f"已注入 {len(cookies)} 个 Cookie")
            self.is_logged_in = True

        # 刷新使 Cookie 生效，进入根目录
        self.driver.get(PAN_BASE)
        time.sleep(3)

    def navigate_to_target_dir(self):
        """
        点击进入"在线解压站点食用"目录。
        因为迅雷 SPA 不认 ?path= 参数直跳，必须通过点击进入。
        
        容错：原生 click 失败则降级 JS click 绕过遮罩。
        """
        dir_el = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.XPATH,
                f"//a[@title='在线解压站点食用']"))
        )
        self.driver.execute_script("arguments[0].scrollIntoView(true);", dir_el)
        time.sleep(0.5)
        try:
            dir_el.click()
        except Exception as e:
            logger.warning(f"原生 click 在线解压站点食用 失败 ({e})，降级 JS click")
            self.driver.execute_script("arguments[0].click();", dir_el)
        time.sleep(3)
        logger.info("已点击进入: 在线解压站点食用")

    def navigate_to(self, url: str):
        """导航到指定 URL"""
        self.driver.get(url)
        time.sleep(3)

    def hover_add_button(self):
        """
        悬停"添加"按钮，弹出 PlusMenu。
        选择器：add_button — XPath: /html/body/.../a[1]/span
        操作：JS 触发 mouseenter + mouseover 事件（绕过 Selenium ActionChains 被检测的风险）
        """
        add_btn = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.XPATH, ADD_BUTTON_XPATH))
        )
        self.driver.execute_script("arguments[0].scrollIntoView(true);", add_btn)
        time.sleep(0.5)

        # 用 JS 派发鼠标事件，比 Selenium ActionChains 更接近真实浏览器
        self.driver.execute_script("""
            var el = arguments[0];
            var rect = el.getBoundingClientRect();
            ['mouseenter', 'mouseover', 'mousemove'].forEach(function(type) {
                var evt = new MouseEvent(type, {
                    bubbles: true, cancelable: true,
                    clientX: rect.left + rect.width/2,
                    clientY: rect.top + rect.height/2
                });
                el.dispatchEvent(evt);
            });
        """, add_btn)
        time.sleep(2)
        logger.info("已悬停添加按钮（JS mouseenter）")

    def click_new_folder(self):
        """
        在 PlusMenu 中点击"新建文件夹"。
        选择器：new_folder_in_menu — class="pan-dropdown-menu-item pan-dropdown-divider"，子文本"新建文件夹"
        
        源码结构: <a class="pan-dropdown-menu-item pan-dropdown-divider"><span>新建文件夹</span></a>
        
        由于反自动化机制拦截 Selenium 原生 click，直接使用 JS click 确保事件派发。
        """
        span_el = WebDriverWait(self.driver, 5).until(
            EC.presence_of_element_located((By.XPATH,
                "//a[contains(@class, 'pan-dropdown-divider')]//span[text()='新建文件夹']"))
        )
        # JS click 绕过 Selenium 自动化检测
        self.driver.execute_script("arguments[0].click();", span_el)
        time.sleep(1.5)
        logger.info("已点击新建文件夹（JS click）")


    def click_add_link(self):
        """
        在 PlusMenu 中点击"添加链接"。
        容错：先等可点击 -> 原生 click；降级 -> JS click
        """
        try:
            add_link = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//span[text()='添加链接']/.."))
            )
            add_link.click()
            logger.info("已点击添加链接（原生 click）")
        except Exception:
            add_link = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.XPATH, "//span[text()='添加链接']/.."))
            )
            self.driver.execute_script("arguments[0].click();", add_link)
            logger.info("已点击添加链接（JS click 降级）")
        time.sleep(1.5)


    def fill_url_textarea(self, url: str):
        """
        在云添加弹窗的 textarea 中填写 URL。
        选择器：<textarea placeholder='支持HTTP...'>
        
        容错：原生 send_keys 被遮罩挡住时报 element not interactable，
        自动降级为 JS 直接设置 value 并派发 input 事件。
        """
        textarea = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.XPATH,
                "//textarea[contains(@placeholder,'HTTP')]"))
        )
        try:
            textarea.clear()
            textarea.send_keys(url)
        except Exception as e:
            logger.warning(f"原生填写 URL 失败，降级 JS 注入: {e}")
            self.driver.execute_script(
                "arguments[0].value = arguments[1];"
                "arguments[0].dispatchEvent(new Event('input', {bubbles: true}));"
                "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
                textarea, url
            )
        time.sleep(0.5)
        logger.info(f"已填写 URL: {url[:60]}...")

    def click_upload_confirm(self):
        """
        点击云添加弹窗的"确定"按钮。
        选择器：/html/body/div[3]/div/div[3]/div/div/div[1]（由你提供）
        """
        confirm = WebDriverWait(self.driver, 5).until(
            EC.element_to_be_clickable((By.XPATH,
                "/html/body/div[3]/div/div[3]/div/div/div[1]"))
        )
        confirm.click()
        time.sleep(2)
        logger.info("已确认云添加")

    # ─────────────────────────────────────────────────────────
    # 新增：云添加"更改"目录方案相关方法
    # 对应 code_to_word.json → selectors.change_folder_link / tree_*
    # ─────────────────────────────────────────────────────────

    def click_change_folder(self):
        """
        在云添加弹窗中点击"更改"链接。
        选择器：change_folder_link — class="fileurl-folder__container" 内的 <a>更改</a>
        点击后弹出树形目录选择保存位置。
        """
        change_btn = WebDriverWait(self.driver, 8).until(
            EC.element_to_be_clickable((By.XPATH,
                "//div[contains(@class,'fileurl-folder__container')]/a[text()='更改']"))
        )
        change_btn.click()
        time.sleep(1.5)
        logger.info("已点击更改目录")

    def find_tree_node_by_label(self, label: str):
        """
        在树形目录弹窗中通过 label 文本找到对应的 td-tree-node div。
        
        策略：遍历弹窗内所有 td-tree-node div，逐个读取 div[1]/span[3] 的文本，
        匹配文件夹名。基于 DOM 结构位置而非 class 名，更抗前端变化。
        
        DOM 结构（各级目录层级相同）：
          <div class="td-tree-node is-expanded">               ← 返回这个
            <div class="td-tree-node__content">                ← div[1]
              <span class="td-tree-node__expand-icon"></span>   span[1]
              <label class="td-checkbox"></label>               label
              <span class="td-tree-node__image-icon"></span>    span[2]
              <span class="td-tree-node__label">{label}</span>  span[3] ← 读这个匹配
            </div>
            <div class="td-tree-node__children">...</div>       ← div[2]
          </div>
        
        返回: td-tree-node div（匹配到的外层容器）
        返回 None: 未找到
        """
        try:
            # 找到弹窗内所有 td-tree-node div
            all_nodes = self.driver.find_elements(By.XPATH,
                "//div[contains(@class,'dialog-folder')]"
                "//div[contains(@class,'td-tree-node')]"
            )
            for node in all_nodes:
                try:
                    # 取该节点的 div[1]（即 td-tree-node__content）下的 span[3] 文本
                    name = node.find_element(By.XPATH,
                        "./div[1]/span[3]"
                    ).text.strip()
                    if name == label:
                        logger.info(f"树形目录匹配到: {name}")
                        return node
                except Exception:
                    continue
            # 没找到，打印所有节点名方便调试
            logger.warning(f"树形目录未找到 [{label}]，所有节点名:")
            for node in all_nodes:
                try:
                    name = node.find_element(By.XPATH, "./div[1]/span[3]").text.strip()
                    logger.warning(f"  - {name}")
                except Exception:
                    logger.warning(f"  - (无法读取名称)")
            return None
        except Exception:
            return None

    def get_tree_node_label(self, node):
        """
        获取树形目录节点的文件夹名。
        选择器：tree_node_label — content 内的 span[3]（即 td-tree-node__label）
        
        根据 DOM：
          <div class="td-tree-node__content">
            <span class="td-tree-node__expand-icon"></span>    span[1]
            <label class="td-checkbox">...</label>             label
            <span class="td-tree-node__image-icon"></span>     span[2]
            <span class="td-tree-node__label">{name}</span>   span[3]
          </div>
        
        span[1]=箭头, span[2]=图标, span[3]=文件夹名
        """
        try:
            return node.find_element(By.XPATH,
                ".//span[contains(@class,'td-tree-node__label')]"
            ).text.strip()
        except Exception:
            return ""


    def click_tree_node_expand(self, node):
        """
        点击树形目录节点展开箭头，展开该节点下的子目录。
        容错：原生 click 失败 -> JS click 降级
        """
        arrow = node.find_element(By.XPATH,
            ".//span[contains(@class,'td-tree-node__expand-icon')]")
        try:
            arrow.click()
            logger.info("已展开树形目录节点（原生 click）")
        except Exception:
            self.driver.execute_script("arguments[0].click();", arrow)
            logger.info("已展开树形目录节点（JS click 降级）")
        time.sleep(2.0)


    def click_tree_node_select(self, node):
        """
        在树形目录节点上选中文件夹。
        容错：固定顺序（图标->label->复选框），逐个原生 click；
        全部失败 -> JS click 降级
        """
        content_el = node.find_element(By.XPATH,
            "./div[contains(@class,'td-tree-node__content')]")

        for sel, name in [("./span[2]", "图标"), ("./span[3]", "label"), ("./label", "复选框")]:
            try:
                el = content_el.find_element(By.XPATH, sel)
                el.click()
                logger.info(f"选中文件夹（{name} click）")
                time.sleep(0.8)
                return
            except Exception:
                continue

        try:
            label = content_el.find_element(By.XPATH, ".//span[contains(@class,'td-tree-node__label')]")
            self.driver.execute_script("arguments[0].click();", label)
            logger.info("选中文件夹（JS click 降级）")
        except Exception as e:
            logger.warning(f"选中文件夹完全失败: {e}")
        time.sleep(0.8)


    def click_tree_confirm(self):
        """
        点击树形目录选择框的"确定"按钮。
        选择器：tree_confirm_button — class="file-tree-btn__normal" 内的第一个 a
        """
        confirm = WebDriverWait(self.driver, 5).until(
            EC.element_to_be_clickable((By.XPATH,
                "//div[contains(@class,'file-tree-btn__normal')]/a[1]"))
        )
        confirm.click()
        time.sleep(1.5)
        logger.info("已确认目录选择")

    def get_tree_children(self, node):
        """
        获取树形目录节点下的直接子节点列表（只查一层）。
        子节点的 DOM 结构与父节点完全一致。
        
        DOM:
          <div class="td-tree-node is-expanded">
            <div class="td-tree-node__children">
              <div class="td-tree-node is-expanded"> ← 子节点1
              <div class="td-tree-node is-expanded"> ← 子节点2
        
        返回: list[WebElement] — 子节点列表
        """
        try:
            children_container = node.find_element(By.XPATH,
                "./div[contains(@class,'td-tree-node__children')]")
            child_nodes = children_container.find_elements(By.XPATH,
                "./div[contains(@class,'td-tree-node')]")
            return child_nodes
        except Exception:
            return []

    def click_cloud_upload_final_confirm(self):
        """
        在目录选择完成后，点击云添加弹窗底部的"确定"按钮。
        选择器：cloud_upload_final_confirm
          <div class="pan-dialog-btn__container">
            <div class="pan-dialog-btn__default pan-dialog-btn__primary">确定</div>
            <div class="pan-dialog-btn__default">取消</div>
          </div>
        注意 class 是双下划线：pan-dialog-btn__primary
        """
        import random as _random_wait
        time.sleep(_random_wait.uniform(0.5, 2.5))
        confirm = WebDriverWait(self.driver, 5).until(
            EC.element_to_be_clickable((By.XPATH,
                "//div[contains(@class,'pan-dialog-btn__primary')]"))
        )
        confirm.click()
        time.sleep(1)
        logger.info("已最终确认云添加")

    def find_rename_input(self):
        """
        定位重命名/新建文件夹的文本输入框。
        返回 _InputWrapper 包装对象，原生操作被遮罩挡住时自动降级 JS。
        """
        el = None
        for xpath in [
            "//div[starts-with(@class, 'current-')]/input[@type='text']",
            "//div[contains(@class, 'SourceListItem__input')]//input",
            "//input[@type='text' and not(ancestor::div[contains(@style,'display:none')])]"
        ]:
            try:
                el = WebDriverWait(self.driver, 3).until(
                    EC.presence_of_element_located((By.XPATH, xpath))
                )
                break
            except Exception:
                continue

        if not el:
            el = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.XPATH,
                    "//div[starts-with(@class, 'current-')]/input[@type='text']"))
            )

        return _InputWrapper(self.driver, el)

    def click_rename_confirm(self):
        """
        点击输入框旁边的确认对钩。
        选择器：rename_confirm_yes — class="xlpfont xlp-action-yes"
        """
        confirm = WebDriverWait(self.driver, 5).until(
            EC.element_to_be_clickable((By.CLASS_NAME, RENAME_CONFIRM_CLASS.split()[-1]))
        )
        # 注意：xlpfont xlp-action-yes 是两个 class，用最后一个唯一标识
        confirm.click()
        time.sleep(1)
        logger.info("已确认命名")

    def right_click_by_title(self, title: str):
        """
        右键通过 title 定位的元素。
        选择器：file_link_by_title — XPath: //a[@title='{title}']
        """
        el = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.XPATH,
                FILE_LINK_BY_TITLE_TPL.format(title=title)))
        )
        self.driver.execute_script("arguments[0].scrollIntoView(true);", el)
        time.sleep(0.5)
        actions = ActionChains(self.driver)
        actions.context_click(el).perform()
        time.sleep(1.5)
        logger.info(f"已右键: {title}")

    def right_click_first_file_in_pan(self):
        """
        在时间戳文件夹内右键第一个文件。
        使用 ul.pan-list > li[1] 定位，再在图标 <img> 上随机偏移右键。
        
        返回: (first_file_title: str) — 第一个文件的 title，用于后续重命名
              返回 None 表示定位失败
        """
        import random as _r

        # 找到 ul.pan-list
        pan_list = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "ul.pan-list"))
        )
        # 取第1个 li
        first_li = pan_list.find_element(By.XPATH, "./li[1]")
        # 滚动到视口
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", first_li)

        # 从 li > div > div[2] > div[1] 拿文件信息区
        # div[2] = SourceListItem_content, div[1] = SourceListItem_title
        # 向下找 <a title="xxx"> 获取文件原名
        file_title = ""
        try:
            a_tag = first_li.find_element(By.XPATH,
                ".//div[2]/div[1]//a[@title]")
            file_title = a_tag.get_attribute("title") or ""
        except Exception:
            logger.warning("无法获取文件 title，尝试备用方式")
            try:
                a_tag = first_li.find_element(By.XPATH, ".//a[@title]")
                file_title = a_tag.get_attribute("title") or ""
            except Exception:
                logger.warning("完全无法获取文件名")

        # 从 li 中找到图标 <img>（呈现大小 28×28）
        img = first_li.find_element(By.XPATH, ".//img")
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", img)
        time.sleep(0.3)

        # 右键时在图标 28×28 范围内随机偏移
        offset_x = _r.randint(-10, 10)
        offset_y = _r.randint(-10, 10)
        actions = ActionChains(self.driver)
        actions.move_to_element_with_offset(img, offset_x, offset_y) \
               .context_click().perform()
        time.sleep(1.5)
        logger.info(f"已右键文件（图标随机偏移 {offset_x},{offset_y}）: {file_title or 'unknown'}")

        return file_title if file_title else None

    def click_context_menu_item(self, text: str):
        """
        在右键菜单中点击指定文本的菜单项。
        策略：取页面上所有 class="pan-dropdown-menu-item" 的 <a> 标签（约15个），
        逐个检查文本 strip 后是否等于目标文本。
        文本选项：下载、在线解压、分享、复制到、移动到、删除、重命名
        """
        all_items = self.driver.find_elements(By.CSS_SELECTOR,
            "a.pan-dropdown-menu-item")
        target = None
        for item in all_items:
            raw = item.text
            if raw.strip() == text:
                target = item
                logger.debug(f"匹配到右键菜单项: [{raw.strip()}]")
                break

        if not target:
            logger.error(f"未找到右键菜单项: {text}，可用项: {[i.text.strip() for i in all_items]}")
            raise Exception(f"右键菜单中未找到 [{text}]")

        target.click()
        time.sleep(1)
        logger.info(f"已点击右键菜单: {text}")

    def click_file_by_title(self, title: str):
        """
        左键单击通过 title 定位的文件/文件夹（进入文件夹或选中压缩包）。
        选择器：file_link_by_title — XPath: //a[@title='{title}']
        
        容错：如果 Selenium 原生 click 报 not interactable，
        自动降级为 JS click 绕过遮罩层。
        """
        el = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.XPATH,
                FILE_LINK_BY_TITLE_TPL.format(title=title)))
        )
        self.driver.execute_script("arguments[0].scrollIntoView(true);", el)
        time.sleep(0.5)
        try:
            el.click()
        except Exception as e:
            logger.warning(f"原生 click {title} 失败 ({e})，降级 JS click")
            self.driver.execute_script("arguments[0].click();", el)
        time.sleep(2)
        logger.info(f"已单击: {title}")

    def click_decompress(self):
        """
        在压缩包弹窗中点击"解压全部文件"。

        容错逻辑（v2）：
          1. 先正常找"解压全部文件"按钮 → 找到直接点
          2. 找不到 → 尽可能找"重试"按钮：
             a. 找到 → 点重试 → 等 20-30 秒（反检测） → 再次找解压按钮
             b. 找不到 → 打印弹窗快照 → 等 5 秒 → 再次找解压按钮
          3. 重复最多 6 次，6 次都不行才抛异常

        选择器：
          decompress_btn: //div[contains(@class,'decompress-file-tree-btn')]/a[text()='解压全部文件']
          retry_btn: class="dialog-decompress-status__footer" 内的 button 文本"重试"
        """
        import random as _rnd
        max_attempts = 6

        for attempt in range(1, max_attempts + 1):
            # 先找"解压全部文件"
            try:
                btn = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, DECOMPRESS_BTN_XPATH))
                )
                btn.click()
                time.sleep(3)
                logger.info(f"已点击: 解压全部文件（第 {attempt} 次尝试）")
                return
            except Exception:
                logger.info(f"未找到解压全部文件按钮（第 {attempt} 次），尝试找重试按钮")

            if attempt >= max_attempts:
                break

            # ── 直接找重试按钮 ──
            found_retry = False
            try:
                # DOM: <button class="td-button primary"><!---->"重试"<!----></button>
                # text()='重试' 会因为 <!-- --> 注释节点匹配失败，
                # 改用 contains(text(), '重试') 且 target 仅一个 primary button
                retry_btn = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH,
                        "//button[contains(@class,'primary') and contains(text(),'重试')]"))
                )
                retry_btn.click()
                logger.info("已点击: 重试按钮")
                found_retry = True
            except Exception:
                pass

            if found_retry:
                # 点了重试 → 等 20-30 秒
                wait_time = _rnd.uniform(20, 30)
                logger.info(f"等待 {wait_time:.1f}s 让解压重新处理...")
                time.sleep(wait_time)
            else:
                # 没找到重试 → 打印弹窗快照帮 debug
                self._log_dialog_snapshot()
                wait_time = _rnd.uniform(3, 5)
                logger.info(f"未找到重试按钮，等待 {wait_time:.1f}s 后重试")
                time.sleep(wait_time)

        # 6 次都失败
        raise RuntimeError(f"尝试 {max_attempts} 次后仍未找到解压全部文件按钮")

    def _log_dialog_snapshot(self):
        """打印当前弹窗/页面的快照到日志，帮助 debug 弹窗结构"""
        try:
            # 打印可能相关的弹窗 HTML
            dialogs = self.driver.find_elements(By.XPATH,
                "//div[contains(@class,'dialog') or contains(@class,'modal')"
                " or contains(@class,'overlay')]")
            if dialogs:
                for i, d in enumerate(dialogs[:5]):
                    if d.is_displayed():
                        html = d.get_attribute("outerHTML") or ""
                        logger.warning(f"  弹窗[{i}] (可见): {html[:500]}")
                    else:
                        html = d.get_attribute("outerHTML") or ""
                        logger.warning(f"  弹窗[{i}] (隐藏): {html[:200]}")
            else:
                logger.warning("  页面无弹窗元素")
        except Exception as e:
            logger.warning(f"  打印弹窗快照失败: {e}")

    def _detect_decompress_dialog(self) -> str:
        """
        探测压缩包弹窗的当前状态。
        返回状态字符串:
          - "retry_visible": 有重试按钮可点
          - "failed_text": 弹窗显示"解压失败"且无重试
          - "dialog_gone": 弹窗已关闭（无可探测元素）
          - "unsupported_format": 显示"不支持"或"格式错误"等
          - "unknown": 以上都不是
        """
        # 1) 检查重试按钮
        try:
            retry_btn = self.driver.find_element(By.XPATH,
                "//div[contains(@class,'dialog-decompress-status__footer')]"
                "//button[text()='重试']")
            if retry_btn and retry_btn.is_displayed():
                return "retry_visible"
        except Exception:
            pass

        # 2) 检查弹窗内容文本
        try:
            body_el = self.driver.find_element(By.XPATH,
                "//div[contains(@class,'dialog-decompress-status') or contains(@class,'pan-dialog')]")
            body_text = body_el.text.strip()
        except Exception:
            body_text = ""

        # 3) 检查页面主体（弹窗可能已关）
        try:
            page_body = self.driver.find_element(By.TAG_NAME, "body").text
        except Exception:
            page_body = ""

        combined = body_text + " " + page_body

        # 各种失败标记
        fail_keywords = ["解压失败", "解压出错", "无法解压"]
        unsupported_keywords = ["不支持", "格式错误", "无法识别", "不支持的解压方式"]

        if any(kw in combined for kw in unsupported_keywords):
            return "unsupported_format"
        if any(kw in combined for kw in fail_keywords):
            return "failed_text"

        # 4) 弹窗是否还在？
        if not body_text and "解压" not in combined:
            return "dialog_gone"

        logger.debug(f"弹窗内容: {body_text[:200]}")
        return "unknown"


    # ─── 分享相关方法 ─────────────────────────────────────

    def click_checkbox_for_li(self, li_element):
        """
        在指定 <li> 元素内勾选复选框。
        选择器：checkbox_input — ./div/div[1]/div/label/input（相对 li 路径）
        """
        checkbox = li_element.find_element(By.XPATH, CHECKBOX_INPUT_XPATH)
        self.driver.execute_script("arguments[0].click();", checkbox)
        time.sleep(0.5)
        logger.info("已勾选复选框")

    def click_share_button(self):
        """
        点击顶部工具栏的"分享"按钮（勾选文件后出现）。
        策略：找所有文本含"分享"的元素 → 过滤出父级是 <a> 标签的那个 → 点击。
        另一个"我的分享"的父级是 <p>，排除。
        
        目标结构：
          <a class="FileMenu__item--7MGwA primary">
            <i class="xlpfont xlp-share"></i>
            <span>分享</span>
          </a>
        """
        import random as _r
        # 找所有文本为"分享"的元素
        share_spans = self.driver.find_elements(By.XPATH,
            "//*[text()='分享']")
        target = None
        for el in share_spans:
            try:
                parent = el.find_element(By.XPATH, "..")
                if parent.tag_name == "a":
                    target = parent
                    logger.debug("找到分享按钮，父级是 <a>")
                    break
            except Exception:
                continue

        if not target:
            logger.error("未找到顶部分享按钮（父级为 <a> 的）")
            # 打印所有"分享"元素的父标签供调试
            for el in share_spans:
                try:
                    parent_tag = el.find_element(By.XPATH, "..").tag_name
                    logger.warning(f"  '分享'的父级: <{parent_tag}>")
                except Exception:
                    pass
            raise Exception("未找到顶部分享按钮")

        self.driver.execute_script("arguments[0].scrollIntoView(true);", target)
        time.sleep(_r.uniform(0.3, 0.6))
        target.click()
        time.sleep(2)
        logger.info("已点击分享按钮")

    def click_create_share(self):
        """
        在分享弹窗中点击"创建链接"按钮。
        
        目标 DOM：
          <div class="dialog-web-create-share__button-box">
            <button class="td-button">创建链接</button>
            <button class="td-button td-button--other">取消</button>
          </div>
        
        定位方式：div.dialog-web-create-share__button-box 内的第一个 button
        """
        btn = WebDriverWait(self.driver, 5).until(
            EC.element_to_be_clickable((By.XPATH,
                "//div[contains(@class,'dialog-web-create-share__button-box')]/button[1]"))
        )
        btn.click()
        time.sleep(2)
        logger.info("已点击创建链接")

    def click_copy_link(self):
        """
        点击"复制链接"按钮。
        选择器：copy_share_link — class="td-button dialog-web-create-share__button-copy-link"
        """
        btn = WebDriverWait(self.driver, 5).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "dialog-web-create-share__button-copy-link"))
        )
        btn.click()
        time.sleep(1)
        logger.info("已点击复制链接")

    def get_folder_info_list(self):
        """
        扫描在线解压站点食用目录下所有文件夹的列表信息。
        返回 list[dict]: [{"name": "文件夹名", "date": "修改时间", "file_id": "xxx", "index": 1}]

        选择器参考（来自你提供的 li 源码）:
          <li data-file-id="xxx" class="SourceListItem__item--XxpOC normal-item">
            <div class="SourceListItem_main--c9HnH">  <!-- 唯一外层 div -->
              <div class="SourceListItem_checkbox--wP+8J">...</div>
              <div class="SourceListItem_content--b]bFo">
                <div class="SourceListItem_title--fq2DG">
                  <div class="SourceListItem_img--IMuw">...</div>
                  <div class="SourceListItem_name--y6dVw">
                    <a title="大一第二学期.7z"><span>...</span></a>
                  </div>
                </div>
                <div class="SourceListItem_desc--MDJR2">
                  <div class="SourceListItem_size--bFXwQ">1G</div>
                  <div class="SourceListItem_date--jVz00">2026-06-07 17:06</div>
                </div>
              </div>
            </div>
          </li>
        
        使用 data-file-id 和 title 属性获取信息。
        """
        results = []
        for i in range(1, 200):
            try:
                li = self.driver.find_element(By.XPATH,
                    FOLDER_LIST_ITEM_TPL.format(index=i))
                file_id = li.get_attribute("data-file-id") or ""

                # 从 <a title="xxx"> 获取名字
                a_tag = li.find_element(By.XPATH, ".//a[@title]")
                name = a_tag.get_attribute("title") or ""

                # 从 date div 获取修改时间
                date_el = li.find_element(By.XPATH,
                    ".//div[contains(@class, 'SourceListItem__date') or contains(@class, 'SourceListItem_date')]")
                date = date_el.text.strip()

                if name:
                    results.append({"name": name, "date": date,
                                    "file_id": file_id, "index": i})
            except Exception:
                break
        return results

    def get_li_by_file_id(self, file_id: str):
        """通过 data-file-id 找到对应的 <li> 元素"""
        return self.driver.find_element(By.XPATH,
            f"//li[@data-file-id='{file_id}']")

    def close(self):
        try:
            self.driver.quit()
        except Exception:
            pass


class _InputWrapper:
    """输入框包装：优先原生操作，遮罩挡住时自动降级 JS 注入"""
    def __init__(self, driver, el):
        self.driver = driver
        self.el = el

    def clear(self):
        try:
            self.el.clear()
        except Exception:
            self.driver.execute_script("arguments[0].value = '';", self.el)

    def send_keys(self, text):
        try:
            self.el.send_keys(text)
        except Exception as e:
            logger.warning(f"send_keys 被遮罩挡住，降级 JS 注入: {e}")
            self.driver.execute_script(
                "arguments[0].value = arguments[1];"
                "arguments[0].dispatchEvent(new Event('input', {bubbles: true}));"
                "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
                self.el, text
            )
