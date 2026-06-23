@echo off
REM start_v5_windows-CDP.bat — Windows 一键启动脚本 (CDP 版)
REM 双击运行即可，无需手动启动浏览器或 Python
REM =====================================================================

setlocal EnableDelayedExpansion

REM ========== 配置区 ==========
REM 脚本所在目录（自动获取）
set "SCRIPT_DIR=%~dp0"
REM Chrome / Edge 可执行文件路径（根据实际安装位置修改）
set "BROWSER_BIN=C:\Program Files\Google\Chrome\Application\chrome.exe"
REM 用户数据目录
set "CHROME_DATA=%SCRIPT_DIR%chromium_user_data"
REM CDP 端口
set "CDP_PORT=9222"
REM 日志路径
set "CHROME_LOG=%SCRIPT_DIR%chrome_v5.log"
set "PY_LOG=%SCRIPT_DIR%restart_once_a_day.log"
REM ==============================

echo [0/3] 清理旧进程...

REM 杀掉所有旧 Chrome/Edge（避免端口冲突）
taskkill /F /IM msedge.exe >nul 2>&1
taskkill /F /IM chrome.exe >nul 2>&1
REM 杀掉旧 Python 进程
taskkill /F /IM pythonw.exe >nul 2>&1
taskkill /F /IM python.exe >nul 2>&1
timeout /t 2 /nobreak >nul

echo [1/3] 启动浏览器（CDP 端口 %CDP_PORT%）...
if not exist "%CHROME_DATA%" mkdir "%CHROME_DATA%"

REM 自动检测浏览器（Edge -> Chrome）
if not exist "%BROWSER_BIN%" (
    if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" (
        set "BROWSER_BIN=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    ) else if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
        set "BROWSER_BIN=C:\Program Files\Google\Chrome\Application\chrome.exe"
    ) else (
        echo   [ERROR] 找不到 Chrome 或 Edge
        echo   请确保已安装 Chrome 或 Edge 浏览器
        pause
        exit /b 1
    )
)

start "" /B "%BROWSER_BIN%" ^
    --remote-debugging-port=%CDP_PORT% ^
    --remote-allow-origins=* ^
    --no-sandbox ^
    --disable-dev-shm-usage ^
    --user-data-dir="%CHROME_DATA%" ^
    --window-size=1920,1080 ^
    about:blank ^
    >"%CHROME_LOG%" 2>&1

echo   浏览器已启动，等待就绪...

REM 等待 CDP 端口可用（最多 30 秒）
set /a "WAIT_COUNT=0"
:WAIT_CDP
timeout /t 1 /nobreak >nul
set /a "WAIT_COUNT+=1"

REM 用 PowerShell 检查端口是否已监听（兼容无 curl 的系统）
powershell -NoProfile -Command "try { $r = netstat -an | Select-String '127.0.0.1:!CDP_PORT!'; if ($r) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1

if "!ERRORLEVEL!"=="0" (
    echo   [OK] CDP 端口 %CDP_PORT% 已就绪
    goto CDP_READY
)
if %WAIT_COUNT% GEQ 30 (
    echo   [ERROR] CDP 端口 %CDP_PORT% 无响应，请检查浏览器启动日志
    echo   浏览器路径: "%BROWSER_BIN%"
    echo   日志文件:   "%CHROME_LOG%"
    pause
    exit /b 1
)
goto WAIT_CDP

:CDP_READY

echo [2/3] 启动 Python 管理器...
cd /d "%SCRIPT_DIR%"

REM 后台启动 Python 脚本（用 pythonw 避免弹出窗口，兜底 python）
REM restart_once_a_day.py自身会写日志文件（run_YYYY-MM-DD.log）
REM 所以不需要 bat 层重定向
where pythonw >nul 2>&1
if "!ERRORLEVEL!"=="0" (
    start "" /B pythonw restart_once_a_day.py
) else (
    start "" /B python restart_once_a_day.py
)

echo   restart_once_a_day.py 已启动 (PID 见任务管理器)

echo.
echo ========================================
echo   [OK] 一键启动完成！
echo   [INFO] CDP: ws://127.0.0.1:%CDP_PORT%
echo   [INFO] 工作目录: %SCRIPT_DIR%
echo   [INFO] 日志: run_YYYY-MM-DD.log
echo ========================================
echo.
echo 按任意键关闭此窗口（服务继续后台运行）...
pause >nul
