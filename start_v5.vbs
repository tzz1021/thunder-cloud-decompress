Dim ws, shell, edgeCmd, managerCmd

Set ws = WScript.CreateObject("Wscript.Shell")

' Edge：开远程调试端口，用 Chrome-devtools 用户数据目录
edgeCmd = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe --remote-debugging-port=9222 --user-data-dir=C:\selenium_user_data"

' Python 管理器（后台无窗口）
managerCmd = "cmd /c cd /d C:\Users\tzz\.openclaw\workspace\xunlei-api-v5 && python restart_once_a_day.py"

ws.run edgeCmd, 0, False
WScript.Sleep 3000  ' 等 Edge 启动完再跑 Python
ws.run managerCmd, 0, False

WScript.quit
