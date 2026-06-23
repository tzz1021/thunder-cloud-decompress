"""
browser_engine.py — CDP 浏览器引擎模块 (替代 Selenium 版)

通过 Chrome DevTools Protocol (CDP) 直接控制 Chromium 浏览器。
无需 chromedriver，支持 ARM64 Linux。

两种运行模式:
  1. 默认模式: 连接已启动的 Chromium（--remote-debugging-port=9222）
  2. Debug 模式: 同默认模式，但信任登录状态

用法:
  先启动 Chromium:
    chromium --remote-debugging-port=9222 --remote-allow-origins=* --no-sandbox
  然后在代码中:
    engine = BrowserEngine(attach=True)
"""

import os
import json
import time
import logging
import random
import urllib.request
from pathlib import Path
import websocket

logger = logging.getLogger("browser_engine")

# ─── 自定义异常 ────────────────────────────────────────────

class DecompressFailedError(Exception):
    """解压彻底失败，文件不可解压（非重试能解决的）"""
    pass


BASE_DIR = Path(__file__).parent
COOKIES_FILE = str(BASE_DIR / "xunlei_cookies.json")

# ─── URLs ──────────────────────────────────────────────────

PAN_BASE = "https://pan.xunlei.com"
TARGET_DIR = "https://pan.xunlei.com/?path=%2F%E5%9C%A8%E7%BA%BF%E8%A7%A3%E5%8E%8B%E7%AB%99%E7%82%B9%E9%A3%9F%E7%94%A8"
CHILD_DIR_TEMPLATE = "https://pan.xunlei.com/?path=%2F%E5%9C%A8%E7%BA%BF%E8%A7%A3%E5%8E%8B%E7%AB%99%E7%82%B9%E9%A3%9F%E7%94%A8%2F{foldername}"

# ─── Selectors ─────────────────────────────────────────────

ADD_BUTTON_XPATH = "/html/body/div[1]/div/div/div/div[2]/div[2]/section[1]/div[1]/div[1]/a[1]/span"
RENAME_CONFIRM_CLASS = "xlpfont xlp-action-yes"
FILE_LINK_BY_TITLE_TPL = "//a[@title='{title}']"
FOLDER_LIST_ITEM_TPL = "/html/body/div[1]/div/div/div/div[2]/div[2]/section[2]/ul/li[{index}]"
DECOMPRESS_BTN_XPATH = "//div[contains(@class,'decompress-file-tree-btn')]/a[text()='解压全部文件']"
CHECKBOX_INPUT_XPATH = "./div/div[1]/div/label/input"

CLIPBOARD_HIJACK_JS = """
// clipboard_hijack_js: 拦截所有写剪贴板操作，捕获分享链接到 window.__copiedLink
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
const origCopy = document.execCommand;
document.execCommand = function(command, ...args) {
  if (command === 'copy') {
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


class CDPConnection:
    """CDP 连接管理：处理 WebSocket 通信和消息收发"""
    
    def __init__(self, host="127.0.0.1", port=9222):
        self.host = host
        self.port = port
        self._msg_id = 0
        self.target_id = None
        self.ws = None
        self._connected = False
    
    def _http_get(self, url):
        with urllib.request.urlopen(url) as f:
            return f.read().decode()
    
    def list_pages(self):
        """获取所有页面"""
        data = json.loads(self._http_get(f"http://{self.host}:{self.port}/json"))
        return [t for t in data if t.get("type") == "page"]
    
    def connect(self, target_id=None):
        """连接到指定页面"""
        if target_id is None:
            pages = self.list_pages()
            if pages:
                target_id = pages[0]["id"]
                logger.info(f"使用现有页面: {target_id}")
            else:
                data = json.loads(self._http_get(
                    f"http://{self.host}:{self.port}/json/new?about:blank"
                ))
                target_id = data["id"]
                logger.info(f"新建页面: {target_id}")
        
        self.target_id = target_id
        ws_url = f"ws://{self.host}:{self.port}/devtools/page/{target_id}"
        self.ws = websocket.create_connection(ws_url)
        
        # 启用关键域
        self._enable_domains()
        self._connected = True
        return target_id
    
    def _enable_domains(self):
        """启用需要的 CDP 域"""
        for domain in ["Page", "DOM", "Runtime", "Input"]:
            try:
                self._send(f"{domain}.enable")
            except:
                pass
    
    def _send(self, method, params=None):
        self._msg_id += 1
        msg = {"id": self._msg_id, "method": method}
        if params:
            msg["params"] = params
        if not self.ws:
            raise Exception("CDP 未连接")
        self.ws.send(json.dumps(msg))
        return self._recv()
    
    def _recv(self, timeout=30):
        """接收响应，忽略事件消息"""
        start = time.time()
        while time.time() - start < timeout:
            try:
                self.ws.settimeout(timeout)
                resp = self.ws.recv()
                data = json.loads(resp)
                if "id" in data:
                    if "error" in data:
                        raise Exception(f"CDP 错误 [{data['error']['code']}]: {data['error']['message']}")
                    return data.get("result", {})
            except websocket.WebSocketTimeoutException:
                raise Exception("CDP 响应超时")
    
    def send(self, method, params=None):
        """发送 CDP 命令并返回结果"""
        return self._send(method, params)
    
    def eval(self, js, await_promise=True):
        """执行 JS 并返回值"""
        result = self._send("Runtime.evaluate", {
            "expression": js,
            "returnByValue": True,
            "awaitPromise": await_promise
        })
        return result.get("result", {}).get("value", "")
    
    def eval_no_return(self, js):
        """执行 JS，不关心返回值"""
        self._send("Runtime.evaluate", {
            "expression": js,
            "returnByValue": False,
            "awaitPromise": True
        })
    
    def navigate(self, url, wait_complete=True):
        """导航到 URL，等待加载完成"""
        self._send("Page.navigate", {"url": url})
        if wait_complete:
            self._wait_page_loaded()
    
    def _wait_page_loaded(self, timeout=20):
        """等待页面加载完成"""
        start = time.time()
        while time.time() - start < timeout:
            try:
                state = self.eval("document.readyState")
                if state in ("complete", "interactive"):
                    time.sleep(1)
                    return
            except:
                pass
            time.sleep(0.3)
        logger.warning("页面加载等待超时")
    
    def screenshot(self, filename="screenshot.png"):
        """截屏"""
        result = self._send("Page.captureScreenshot", {"format": "png"})
        import base64
        img_data = base64.b64decode(result["data"])
        with open(filename, "wb") as f:
            f.write(img_data)
        logger.info(f"截屏已保存: {filename} ({len(img_data)} bytes)")
        return filename
    
    def close(self):
        if self.ws:
            self.ws.close()
            self._connected = False


def _js_find_element_by_xpath(xpath, index=0):
    """生成通过 XPath 查找元素的 JS 代码"""
    safe_xpath = xpath.replace("'", "\\'")
    return f"""
    (() => {{
        const result = document.evaluate(
            '{safe_xpath}',
            document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null
        );
        const el = result.snapshotItem({index});
        if (!el) return null;
        return el;
    }})()
    """


def _js_get_text(el_var):
    """获取元素文本"""
    return f"({el_var} ? {el_var}.textContent.trim() : '')"


def _js_get_attribute(el_var, attr):
    """获取元素属性"""
    return f"({el_var} ? {el_var}.getAttribute('{attr}') : '')"


def _js_click(el_var):
    """点击元素"""
    return f"""
    (() => {{
        const el = {el_var};
        if (!el) return false;
        el.scrollIntoView({{block: 'center', behavior: 'instant'}});
        el.click();
        return true;
    }})()
    """


def _js_set_value(el_var, value):
    """设置 input 的值"""
    safe = value.replace("'", "\\'").replace("\\", "\\\\").replace("\n", "\\n")
    return f"""
    (() => {{
        const el = {el_var};
        if (!el) return false;
        el.focus();
        el.value = '{safe}';
        el.dispatchEvent(new Event('input', {{bubbles: true}}));
        el.dispatchEvent(new Event('change', {{bubbles: true}}));
        return true;
    }})()
    """


def _js_hover(el_var):
    """悬停元素"""
    return f"""
    (() => {{
        const el = {el_var};
        if (!el) return false;
        el.scrollIntoView({{block: 'center', behavior: 'instant'}});
        const rect = el.getBoundingClientRect();
        ['mouseenter', 'mouseover', 'mousemove'].forEach(type => {{
            el.dispatchEvent(new MouseEvent(type, {{
                bubbles: true, cancelable: true,
                clientX: rect.left + rect.width/2,
                clientY: rect.top + rect.height/2
            }}));
        }});
        return true;
    }})()
    """


def _js_right_click(el_var):
    """右键元素"""
    return f"""
    (() => {{
        const el = {el_var};
        if (!el) return false;
        el.scrollIntoView({{block: 'center', behavior: 'instant'}});
        el.dispatchEvent(new MouseEvent('contextmenu', {{
            bubbles: true, cancelable: true, button: 2
        }}));
        return true;
    }})()
    """


# ═══════════════════════════════════════════════════════════════
#  BrowserEngine 类 — 完整替代 Selenium 版本
# ═══════════════════════════════════════════════════════════════

class BrowserEngine:
    """浏览器引擎，通过 CDP 控制 Chromium 浏览器实例
    
    参数:
      headless: 无效（CDP 不需要此参数，保留兼容）
      attach (bool): 是否附加到已有浏览器（debug 模式）
      debug_port (int): CDP 调试端口，默认 9222
      browser_type (str): 保留兼容
    """
    
    def __init__(self, headless: bool = False, attach: bool = False,
                 debug_port: int = 9222, browser_type: str = "chrome"):
        self.is_logged_in = False
        self.attach_mode = attach
        self._cdp = CDPConnection(port=debug_port)
        self._cdp.connect()
        self.driver = _DriverProxy(self._cdp)  # 兼容原有 driver 引用
        
        # 去掉 navigator.webdriver 属性，防检测
        self._cdp.eval("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)
        
        logger.info(f"CDP BrowserEngine 已初始化 (attach={attach}, port={debug_port})")
    
    # ─── 初始化 / 登录 ──────────────────────────────────
    
    def login_and_inject_cookies(self):
        """登录逻辑"""
        if self.attach_mode:
            logger.info("Debug 模式：直接导航到首页")
            self._cdp.navigate(PAN_BASE)
            time.sleep(3)
            self.is_logged_in = True
            logger.info(f"当前页面标题: {self._cdp.eval('document.title')}")
            return
        
        self._cdp.navigate(PAN_BASE)
        time.sleep(3)
        
        if os.path.exists(COOKIES_FILE):
            with open(COOKIES_FILE, encoding="utf-8") as f:
                cookies = json.load(f)
            # CDP 注入 Cookie
            for name, value in cookies.items():
                try:
                    self._cdp.send("Network.setCookie", {
                        "name": name, "value": str(value),
                        "domain": ".xunlei.com", "path": "/",
                        "secure": True
                    })
                except Exception as e:
                    logger.warning(f"注入 Cookie [{name}] 失败: {e}")
            logger.info(f"已注入 {len(cookies)} 个 Cookie")
            self.is_logged_in = True
        
        self._cdp.navigate(PAN_BASE)
        time.sleep(3)
    
    def inject_clipboard_hijack(self):
        """注入剪贴板劫持 JS"""
        self._cdp.eval(CLIPBOARD_HIJACK_JS)
        logger.info("剪贴板劫持 JS 已注入")
    
    def get_copied_link(self) -> str:
        """读取被劫持的分享链接"""
        return self._cdp.eval("return window.__copiedLink || '';")
    
    def get_clipboard_via_cdp(self) -> str:
        """通过 CDP 读取系统剪贴板"""
        try:
            result = self._cdp.send("Browser.getClipboard", {})
            text = result.get("clipboard", {}).get("text", "")
            if text:
                logger.info(f"CDP 读取剪贴板成功: {text[:80]}...")
            return text
        except Exception as e:
            logger.warning(f"CDP 读取剪贴板失败: {e}")
            return ""
    
    # ─── 导航 ───────────────────────────────────────────
    
    def navigate_to_target_dir(self):
        """点击进入在线解压站点食用目录"""
        logger.info("导航到目标目录...")
        # 先直接导航到目标 URL
        self._cdp.navigate(TARGET_DIR)
        time.sleep(3)
    
    def navigate_to(self, url: str):
        """导航到指定 URL"""
        self._cdp.navigate(url)
        time.sleep(3)
    
    # ─── 添加按钮 / 新建文件夹 ──────────────────────────
    
    def hover_add_button(self):
        """悬停添加按钮"""
        logger.info("悬停添加按钮...")
        # 通过 JS 触发悬停
        js = """
        (() => {
            const addBtn = document.evaluate(
                "/html/body/div[1]/div/div/div/div[2]/div[2]/section[1]/div[1]/div[1]/a[1]/span",
                document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
            ).singleNodeValue;
            if (!addBtn) return false;
            addBtn.scrollIntoView({block: 'center'});
            const rect = addBtn.getBoundingClientRect();
            ['mouseenter', 'mouseover', 'mousemove'].forEach(type => {
                addBtn.dispatchEvent(new MouseEvent(type, {
                    bubbles: true, cancelable: true,
                    clientX: rect.left + rect.width/2,
                    clientY: rect.top + rect.height/2
                }));
            });
            return true;
        })()
        """
        self._cdp.eval(js)
        time.sleep(2)
        logger.info("已悬停添加按钮")
    
    def click_new_folder(self):
        """点击新建文件夹"""
        js = """
        (() => {
            const items = document.querySelectorAll('a.pan-dropdown-menu-item');
            for (const item of items) {
                if (item.textContent.trim() === '新建文件夹') {
                    item.click();
                    return true;
                }
            }
            // 备用: 通过 XPath
            const el = document.evaluate(
                "//a[contains(@class, 'pan-dropdown-divider')]//span[text()='新建文件夹']",
                document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
            ).singleNodeValue;
            if (el) { el.click(); return true; }
            return false;
        })()
        """
        if not self._cdp.eval(js):
            logger.warning("未找到新建文件夹按钮")
        else:
            logger.info("已点击新建文件夹")
        time.sleep(1.5)
    
    def click_add_link(self):
        """点击添加链接"""
        js = """
        (() => {
            const items = document.querySelectorAll('a.pan-dropdown-menu-item');
            for (const item of items) {
                if (item.textContent.trim() === '添加链接') {
                    item.click();
                    return 'native';
                }
            }
            // 备用: 通过 span 文本
            const spans = document.querySelectorAll('span');
            for (const span of spans) {
                if (span.textContent.trim() === '添加链接') {
                    span.click();
                    return 'span';
                }
            }
            return 'not_found';
        })()
        """
        result = self._cdp.eval(js)
        logger.info(f"已点击添加链接 ({result})")
        time.sleep(1.5)
    
    # ─── URL 填写 ───────────────────────────────────────
    
    def fill_url_textarea(self, url: str):
        """填写 URL 到 textarea"""
        safe_url = url.replace("'", "\\'").replace("\\", "\\\\")
        js = f"""
        (() => {{
            const textarea = document.querySelector('textarea[placeholder*="HTTP"]');
            if (!textarea) return false;
            textarea.value = '{safe_url}';
            textarea.dispatchEvent(new Event('input', {{bubbles: true}}));
            textarea.dispatchEvent(new Event('change', {{bubbles: true}}));
            return true;
        }})()
        """
        if self._cdp.eval(js):
            logger.info(f"已填写 URL: {url[:60]}...")
        else:
            logger.warning("未找到 textarea")
        time.sleep(0.5)
    
    def click_upload_confirm(self):
        """点击云添加确定按钮"""
        js = """
        (() => {
            const els = document.evaluate(
                "/html/body/div[3]/div/div[3]/div/div/div[1]",
                document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
            ).singleNodeValue;
            if (els) { els.click(); return true; }
            // 备用
            const btns = document.querySelectorAll('.pan-dialog-btn__primary');
            if (btns.length) { btns[0].click(); return true; }
            return false;
        })()
        """
        if self._cdp.eval(js):
            logger.info("已确认云添加")
        else:
            logger.warning("未找到确定按钮")
        time.sleep(2)
    
    # ─── 更改目录 ───────────────────────────────────────
    
    def click_change_folder(self):
        """点击更改目录链接"""
        js = """
        (() => {
            const links = document.querySelectorAll('a');
            for (const link of links) {
                if (link.textContent.trim() === '更改') {
                    link.click();
                    return true;
                }
            }
            return false;
        })()
        """
        if self._cdp.eval(js):
            logger.info("已点击更改目录")
        else:
            logger.warning("未找到更改链接")
        time.sleep(1.5)
    
    def find_tree_node_by_label(self, label: str):
        """
        在树形目录中查找对应 label 的节点。
        返回节点信息 dict 或 None
        """
        safe_label = label.replace("'", "\\'")
        js = f"""
        (() => {{
            const allNodes = document.querySelectorAll('.td-tree-node');
            for (const node of allNodes) {{
                const labels = node.querySelectorAll('.td-tree-node__label');
                for (const lbl of labels) {{
                    if (lbl.textContent.trim() === '{safe_label}') {{
                        return '{safe_label}';
                    }}
                }}
            }}
            return null;
        }})()
        """
        result = self._cdp.eval(js)
        if result:
            logger.info(f"树形目录匹配到: {result}")
            return {"label": result}
        logger.warning(f"树形目录未找到 [{label}]")
        return None
    
    def get_tree_node_label(self, node) -> str:
        """获取树形目录节点名称"""
        if isinstance(node, dict):
            return node.get("label", "")
        return str(node)
    
    def click_tree_node_expand(self, node):
        """展开树形目录节点"""
        label = self.get_tree_node_label(node)
        safe_label = label.replace("'", "\\'")
        js = f"""
        (() => {{
            const allNodes = document.querySelectorAll('.td-tree-node');
            for (const node of allNodes) {{
                const labels = node.querySelectorAll('.td-tree-node__label');
                for (const lbl of labels) {{
                    if (lbl.textContent.trim() === '{safe_label}') {{
                        const arrow = node.querySelector('.td-tree-node__expand-icon');
                        if (arrow) {{ arrow.click(); return true; }}
                        node.click(); return true;
                    }}
                }}
            }}
            return false;
        }})()
        """
        self._cdp.eval(js)
        logger.info(f"已展开树形目录节点: {label}")
        time.sleep(2.0)
    
    def click_tree_node_select(self, node):
        """选中树形目录节点"""
        label = self.get_tree_node_label(node)
        safe_label = label.replace("'", "\\'")
        js = f"""
        (() => {{
            const allNodes = document.querySelectorAll('.td-tree-node');
            for (const node of allNodes) {{
                const labels = node.querySelectorAll('.td-tree-node__label');
                for (const lbl of labels) {{
                    if (lbl.textContent.trim() === '{safe_label}') {{
                        const content = node.querySelector('.td-tree-node__content');
                        if (content) {{ content.click(); return true; }}
                        node.click(); return true;
                    }}
                }}
            }}
            return false;
        }})()
        """
        self._cdp.eval(js)
        logger.info(f"选中文件夹: {label}")
        time.sleep(0.8)
    
    def click_tree_confirm(self):
        """点击树形目录确定按钮"""
        js = """
        (() => {
            const btns = document.querySelectorAll('.file-tree-btn__normal a, .file-tree-btn__normal button');
            if (btns.length) { btns[0].click(); return true; }
            return false;
        })()
        """
        if self._cdp.eval(js):
            logger.info("已确认目录选择")
        else:
            logger.warning("未找到目录确认按钮")
        time.sleep(1.5)
    
    def get_tree_children(self, node):
        """获取子节点列表"""
        label = self.get_tree_node_label(node)
        safe_label = label.replace("'", "\\'")
        js = f"""
        (() => {{
            const result = [];
            const allNodes = document.querySelectorAll('.td-tree-node');
            for (const node of allNodes) {{
                const labels = node.querySelectorAll('.td-tree-node__label');
                for (const lbl of labels) {{
                    if (lbl.textContent.trim() === '{safe_label}') {{
                        const children = node.querySelector('.td-tree-node__children');
                        if (children) {{
                            const childNodes = children.querySelectorAll(':scope > .td-tree-node');
                            childNodes.forEach(cn => {{
                                const cl = cn.querySelector('.td-tree-node__label');
                                if (cl) result.push({{label: cl.textContent.trim()}});
                            }});
                        }}
                        return JSON.stringify(result);
                    }}
                }}
            }}
            return JSON.stringify(result);
        }})()
        """
        try:
            result = json.loads(self._cdp.eval(js))
            return result
        except:
            return []
    
    def click_cloud_upload_final_confirm(self):
        """最终确认云添加"""
        time.sleep(random.uniform(0.5, 2.5))
        js = """
        (() => {
            const btns = document.querySelectorAll('.pan-dialog-btn__primary');
            if (btns.length) { btns[0].click(); return true; }
            // 备用: 找"确定"文本的 div
            const allDivs = document.querySelectorAll('div');
            for (const div of allDivs) {
                if (div.textContent.trim() === '确定') {
                    div.click(); return true;
                }
            }
            return false;
        })()
        """
        if self._cdp.eval(js):
            logger.info("已最终确认云添加")
        else:
            logger.warning("未找到最终确认按钮")
        time.sleep(1)
    
    # ─── 重命名 ─────────────────────────────────────────
    
    def find_rename_input(self):
        """找到重命名输入框，返回 _InputWrapper"""
        js = """
        (() => {
            // 多种查找策略
            const selectors = [
                "div[class*='current-'] input[type='text']",
                "div[class*='SourceListItem__input'] input",
                "input[type='text']"
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el) return true;
            }
            return false;
        })()
        """
        found = self._cdp.eval(js)
        return _InputWrapper(self._cdp) if found else _InputWrapper(self._cdp)
    
    def click_rename_confirm(self):
        """点击重命名确认对钩"""
        js = """
        (() => {
            const el = document.querySelector('.xlp-action-yes');
            if (el) { el.click(); return true; }
            return false;
        })()
        """
        if self._cdp.eval(js):
            logger.info("已确认命名")
        else:
            logger.warning("未找到确认对钩")
        time.sleep(1)
    
    # ─── 右键菜单 ───────────────────────────────────────
    
    def right_click_by_title(self, title: str):
        """右键通过 title 定位的元素"""
        safe_title = title.replace("'", "\\'")
        js = f"""
        (() => {{
            const el = document.querySelector('a[title="{safe_title}"]');
            if (!el) return false;
            el.scrollIntoView({{block: 'center'}});
            el.dispatchEvent(new MouseEvent('contextmenu', {{
                bubbles: true, cancelable: true, button: 2,
                clientX: 100, clientY: 100
            }}));
            return true;
        }})()
        """
        if self._cdp.eval(js):
            logger.info(f"已右键: {title}")
        else:
            logger.warning(f"未找到元素: {title}")
        time.sleep(1.5)
    
    def right_click_first_file_in_pan(self):
        """右键第一个文件"""
        js = """
        (() => {
            const panList = document.querySelector('ul.pan-list');
            if (!panList) return null;
            const firstLi = panList.querySelector('li');
            if (!firstLi) return null;
            firstLi.scrollIntoView({block: 'center'});
            // 获取文件名
            let fileTitle = '';
            const aTag = firstLi.querySelector('a[title]');
            if (aTag) fileTitle = aTag.getAttribute('title') || '';
            // 右键
            const img = firstLi.querySelector('img');
            if (img) {
                img.scrollIntoView({block: 'center'});
                img.dispatchEvent(new MouseEvent('contextmenu', {
                    bubbles: true, cancelable: true, button: 2
                }));
            } else {
                firstLi.dispatchEvent(new MouseEvent('contextmenu', {
                    bubbles: true, cancelable: true, button: 2
                }));
            }
            return fileTitle;
        })()
        """
        result = self._cdp.eval(js)
        if result:
            logger.info(f"已右键文件: {result}")
        else:
            logger.warning("右键文件失败")
        time.sleep(1.5)
        return result if result else None
    
    def click_context_menu_item(self, text: str):
        """点击右键菜单项"""
        safe_text = text.replace("'", "\\'")
        js = f"""
        (() => {{
            const items = document.querySelectorAll('a.pan-dropdown-menu-item');
            for (const item of items) {{
                if (item.textContent.trim() === '{safe_text}') {{
                    item.click();
                    return true;
                }}
            }}
            return false;
        }})()
        """
        if self._cdp.eval(js):
            logger.info(f"已点击右键菜单: {text}")
        else:
            logger.warning(f"未找到右键菜单项: {text}")
        time.sleep(1)
    
    # ─── 文件操作 ───────────────────────────────────────
    
    def click_file_by_title(self, title: str):
        """左键单击文件/文件夹"""
        safe_title = title.replace("'", "\\'")
        js = f"""
        (() => {{
            const el = document.querySelector('a[title="{safe_title}"]');
            if (!el) return false;
            el.scrollIntoView({{block: 'center'}});
            el.click();
            return true;
        }})()
        """
        if self._cdp.eval(js):
            logger.info(f"已单击: {title}")
        else:
            logger.warning(f"未找到文件: {title}")
        time.sleep(2)
    
    # ─── 解压 ───────────────────────────────────────────
    
    def click_decompress(self):
        """点击解压全部文件"""
        max_attempts = 6
        
        for attempt in range(1, max_attempts + 1):
            js = """
            (() => {
                const btn = document.evaluate(
                    "//div[contains(@class,'decompress-file-tree-btn')]/a[text()='解压全部文件']",
                    document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
                ).singleNodeValue;
                if (btn) { btn.click(); return 'clicked'; }
                return 'not_found';
            })()
            """
            result = self._cdp.eval(js)
            if result == 'clicked':
                time.sleep(3)
                logger.info(f"已点击: 解压全部文件（第 {attempt} 次尝试）")
                return
            
            logger.info(f"未找到解压全部文件按钮（第 {attempt} 次）")
            
            if attempt >= max_attempts:
                break
            
            # 找重试按钮
            retry_js = """
            (() => {
                const btns = document.querySelectorAll('button');
                for (const btn of btns) {
                    if (btn.textContent.includes('重试')) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            })()
            """
            if self._cdp.eval(retry_js):
                logger.info("已点击: 重试按钮")
                wait_time = random.uniform(20, 30)
                logger.info(f"等待 {wait_time:.1f}s...")
                time.sleep(wait_time)
            else:
                self._log_dialog_snapshot()
                wait_time = random.uniform(3, 5)
                logger.info(f"等待 {wait_time:.1f}s 后重试")
                time.sleep(wait_time)
        
        raise RuntimeError(f"尝试 {max_attempts} 次后仍未找到解压全部文件按钮")
    
    def _detect_decompress_dialog(self) -> str:
        """检测解压弹窗状态"""
        # 检查重试按钮
        js_retry = """
        (() => {
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.textContent.includes('重试') && btn.offsetParent !== null) return true;
            }
            return false;
        })()
        """
        if self._cdp.eval(js_retry) == "true":
            return "retry_visible"
        
        # 检查弹窗文本
        body_text = self._cdp.eval("document.body ? document.body.innerText : ''")
        
        if any(kw in body_text for kw in ["不支持", "格式错误", "无法识别", "不支持的解压方式"]):
            return "unsupported_format"
        if any(kw in body_text for kw in ["解压失败", "解压出错", "无法解压"]):
            return "failed_text"
        if "解压" not in body_text:
            return "dialog_gone"
        
        return "unknown"
    
    def _log_dialog_snapshot(self):
        """打印弹窗快照"""
        try:
            dialogs_js = """
            (() => {
                const dialogs = document.querySelectorAll('div[class*="dialog"], div[class*="modal"]');
                const result = [];
                for (const d of dialogs) {
                    if (d.offsetParent !== null) {
                        result.push(d.outerHTML.substring(0, 300));
                    }
                }
                return JSON.stringify(result);
            })()
            """
            dialogs = json.loads(self._cdp.eval(dialogs_js))
            for i, html in enumerate(dialogs[:5]):
                logger.warning(f"  弹窗[{i}] (可见): {html[:200]}")
            if not dialogs:
                logger.warning("  页面无可见弹窗")
        except Exception as e:
            logger.warning(f"  打印弹窗快照失败: {e}")
    
    # ─── 分享 ───────────────────────────────────────────
    
    def click_checkbox_for_li(self, li_element):
        """勾选复选框"""
        try:
            if isinstance(li_element, dict):
                file_id = li_element.get("data-file-id", "")
                if file_id:
                    js = f"""
                    (() => {{
                        const li = document.querySelector('li[data-file-id="{file_id}"]');
                        if (!li) return false;
                        const checkbox = li.querySelector('input[type="checkbox"]');
                        if (checkbox) {{ checkbox.click(); return true; }}
                        const label = li.querySelector('label');
                        if (label) {{ label.click(); return true; }}
                        return false;
                    }})()
                    """
                    self._cdp.eval(js)
                    logger.info("已勾选复选框")
                    time.sleep(0.5)
                    return
        except:
            pass
        
        # 通用方式
        self._cdp.eval("""
        (() => {
            const checkbox = document.querySelector('input[type="checkbox"]');
            if (checkbox) { checkbox.click(); return; }
            const label = document.querySelector('label');
            if (label) { label.click(); }
        })()
        """)
        logger.info("已勾选复选框（通用）")
        time.sleep(0.5)
    
    def click_share_button(self):
        """点击分享按钮"""
        js = """
        (() => {
            const spans = document.querySelectorAll('span');
            for (const span of spans) {
                if (span.textContent.trim() === '分享') {
                    const parent = span.parentElement;
                    if (parent && parent.tagName === 'A') {
                        parent.click();
                        return 'parent_a';
                    }
                    span.click();
                    return 'span';
                }
            }
            return 'not_found';
        })()
        """
        result = self._cdp.eval(js)
        if result != 'not_found':
            logger.info(f"已点击分享按钮 ({result})")
        else:
            logger.warning("未找到分享按钮")
        time.sleep(2)
    
    def click_create_share(self):
        """点击创建链接"""
        js = """
        (() => {
            const btn = document.querySelector('.dialog-web-create-share__button-box button, button.td-button');
            if (btn && (btn.textContent.includes('创建链接') || btn.textContent.includes('创建'))) {
                btn.click(); return true;
            }
            // 找第一个 button
            const allBtns = document.querySelectorAll('.dialog-web-create-share__button-box button');
            if (allBtns.length) { allBtns[0].click(); return true; }
            return false;
        })()
        """
        if self._cdp.eval(js):
            logger.info("已点击创建链接")
        else:
            logger.warning("未找到创建链接按钮")
        time.sleep(2)
    
    def click_copy_link(self):
        """点击复制链接"""
        js = """
        (() => {
            const btn = document.querySelector('.dialog-web-create-share__button-copy-link');
            if (btn) { btn.click(); return true; }
            // 备用: 找"复制链接"文本
            const allEls = document.querySelectorAll('button, a, div');
            for (const el of allEls) {
                if (el.textContent.trim() === '复制链接') {
                    el.click(); return true;
                }
            }
            return false;
        })()
        """
        if self._cdp.eval(js):
            logger.info("已点击复制链接")
        else:
            logger.warning("未找到复制链接按钮")
        time.sleep(1)
    
    # ─── 文件夹信息 ─────────────────────────────────────
    
    def get_folder_info_list(self):
        """扫描目录下所有文件夹信息"""
        js = """
        (() => {
            const results = [];
            const items = document.querySelectorAll('ul.pan-list > li');
            items.forEach((li, index) => {
                const fileId = li.getAttribute('data-file-id') || '';
                const aTag = li.querySelector('a[title]');
                const name = aTag ? (aTag.getAttribute('title') || '') : '';
                let date = '';
                const dateEl = li.querySelector('[class*="date"]');
                if (dateEl) date = dateEl.textContent.trim();
                if (name) {
                    results.push({name, date, file_id: fileId, index: index + 1});
                }
            });
            return JSON.stringify(results);
        })()
        """
        try:
            result = json.loads(self._cdp.eval(js))
            return result
        except:
            return []
    
    def get_li_by_file_id(self, file_id: str):
        """通过 file_id 获取 li 信息"""
        return {"data-file-id": file_id}
    
    # ─── 清理 ───────────────────────────────────────────
    
    def close(self):
        """关闭连接"""
        try:
            self._cdp.close()
        except Exception:
            pass
        logger.info("浏览器引擎已关闭")


class _InputWrapper:
    """输入框包装：通过 CDP eval 操作"""
    def __init__(self, cdp):
        self._cdp = cdp
        self._value = ""
    
    def clear(self):
        """清空输入框"""
        js = """
        (() => {
            const selectors = [
                "div[class*='current-'] input[type='text']",
                "div[class*='SourceListItem__input'] input",
                "input[type='text']"
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el) { el.value = ''; return true; }
            }
            return false;
        })()
        """
        self._cdp.eval(js)
        self._value = ""
    
    def send_keys(self, text):
        """输入文本"""
        safe = text.replace("'", "\\'").replace("\\", "\\\\")
        js = f"""
        (() => {{
            const selectors = [
                "div[class*='current-'] input[type='text']",
                "div[class*='SourceListItem__input'] input",
                "input[type='text']"
            ];
            for (const sel of selectors) {{
                const el = document.querySelector(sel);
                if (el) {{
                    el.value = '{safe}';
                    el.dispatchEvent(new Event('input', {{bubbles: true}}));
                    el.dispatchEvent(new Event('change', {{bubbles: true}}));
                    return true;
                }}
            }}
            return false;
        }})()
        """
        if self._cdp.eval(js):
            logger.info(f"已输入文本: {text[:50]}...")
        else:
            logger.warning("未找到输入框")
        self._value = text


class _DriverProxy:
    """
    兼容性代理：让 step 文件中可能的 driver 直接调用不报错
    暴露 title 属性和 execute_script 等方法
    """
    def __init__(self, cdp):
        self._cdp = cdp
    
    @property
    def title(self):
        return self._cdp.eval("document.title")
    
    def execute_script(self, script, *args):
        """执行 JS 脚本，兼容 Selenium 的 execute_script"""
        if args:
            # 替换 arguments[0], arguments[1] 等
            for i, arg in enumerate(args):
                if isinstance(arg, str):
                    safe_arg = arg.replace("'", "\\'")
                    script = script.replace(f"arguments[{i}]", f"'{safe_arg}'")
                elif isinstance(arg, bool):
                    script = script.replace(f"arguments[{i}]", "true" if arg else "false")
                elif arg is None:
                    script = script.replace(f"arguments[{i}]", "null")
                else:
                    script = script.replace(f"arguments[{i}]", str(arg))
        return self._cdp.eval(script)
    
    def execute_cdp_cmd(self, cmd, cmd_args=None):
        """执行 CDP 命令"""
        return self._cdp.send(cmd, cmd_args or {})
    
    def get(self, url):
        """导航到 URL"""
        self._cdp.navigate(url)
    
    def find_element(self, by, value):
        """查找元素 - 简化兼容"""
        return None  # 不真正支持，让 JS 路径走
    
    def find_elements(self, by, value):
        """查找多个元素"""
        return []
    
    def quit(self):
        pass
