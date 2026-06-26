# thunder-cloud-decompress
xunlei云解压全栈项目，flask+selenium
简要说明一下源码结构

main_loop.py是主循环，调用各个step

code_to_word.json是自然语言与class xpath选择器的映射表，browser_engine.py是各种模拟点击指令，step里面直接调用这些指令

api.py还有一堆test是测试openlist对接的（从alist迁移，测试发现alist延迟过大）

intro.txt算一个简陋的食用方法

# how to use

python环境，依赖selenium，flask，pywin32（不全自己补充，linux用户把pywin32换成一个能读取剪切板的即可）

先克隆项目，启动前端step6_web（5000本地端口）启动测试版后端step5_quene_worker.py首次启动可以附加-h参数获取帮助，也可直接跑一遍测试。

    git clone https://github.com/tzz1021/thunder-cloud-decompress.git

    cd thunder-cloud-decompress

    python step6_web.py

    python step5_quene_worker.py -h

**下面是输出**

用法: python step5_queue_worker.py <文件夹名> <直链URL> [选项]

选项:

  --headless         无头模式（默认模式，需要 Cookie 注入）
  
  --debug            附加到已有浏览器（需先手动启动 Edge/Chrome）
  
  --port <数字>      调试端口（默认 9222）
  
  --browser <edge|chrome>  浏览器类型（默认 edge）
  

Debug 模式使用步骤:
1. 关闭所有 Edge 窗口
2. 命令行启动: msedge.exe --remote-debugging-port=9222 --user-data-dir="C:\selenium_user_data"
3. 手动登录 pan.xunlei.com
4. 运行: python step5_queue_worker.py <文件夹名> <URL> --debug
  
示例: python step5_queue_worker.py "2026-06-08 13：45：00" https://example.com/file.zip --debug

**长期运维**

restart_once_a_day.py每天定时24:00重启一次服务，清理数据库

批处理文件：
停止浏览器，停止前端，启动浏览器，启动restart_once_a_day.py（显示python manager）
无头模式bug频出，有服务器的开有头即可


更多测试数据以及站点体验位置，更新日志这里不再列出，仅作存档不打算公开
当大家都能看到的时候说明项目已经黄了
    https://gcnk5l8dhg5s.feishu.cn/docx/HSg5dSYMzog8FnxwZV6cLTMJnWe?from=from_copylink

# ackonwledged
[openlist](https://github.com/OpenListTeam/OpenList)
