@echo off
REM start_v5_windows.bat — Windows 版一键启动脚本
REM 用法：双击运行，或在 CMD 中执行 start_v5_windows.bat

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
REM 杀掉旧 Chrome（带 remote-debugging-port=9222 的）
taskkill /F /IM chrome.exe /FI "COMMANDLINE eq *remote-debugging-port=9222*" >nul 2>&1
REM 杀掉旧 Python 进程
taskkill /F /FI "IMAGENAME eq python.exe" /FI "COMMANDLINE eq *restart_once_a_day.py*" >nul 2>&1
taskkill /F /FI "IMAGENAME eq pythonw.exe" /FI "COMMANDLINE eq *restart_once_a_day.py*" >nul 2>&1
timeout /t 2 /nobreak >nul

echo [1/3] 启动 Chrome（CDP 端口 %CDP_PORT%）...
if not exist "%CHROME_DATA%" mkdir "%CHROME_DATA%"

REM 检查浏览器是否存在
if not exist "%BROWSER_BIN%" (
    echo   [ERROR] 找不到浏览器: %BROWSER_BIN%
    echo   请修改 BROWSER_BIN 路径为实际安装位置
    pause
    exit /b 1
)

start "" "%BROWSER_BIN%" ^
    --remote-debugging-port=%CDP_PORT% ^
    --remote-allow-origins=* ^
    --no-sandbox ^
    --disable-dev-shm-usage ^
    --user-data-dir="%CHROME_DATA%" ^
    --window-size=1920,1080 ^
    about:blank

echo   浏览器已启动，等待就绪...

REM 等待 CDP 端口可用（最多 30 秒）
set /a "WAIT_COUNT=0"
:WAIT_CDP
timeout /t 1 /nobreak >nul
set /a "WAIT_COUNT+=1"
curl -s http://127.0.0.1:%CDP_PORT%/json/version >nul 2>&1
if "%ERRORLEVEL%"=="0" (
    echo   [OK] CDP 端口 %CDP_PORT% 正常响应
    goto CDP_READY
)
if %WAIT_COUNT% GEQ 30 (
    echo   [ERROR] CDP 端口 %CDP_PORT% 无响应，请检查浏览器启动日志
    echo   浏览器路径: %BROWSER_BIN%
    pause
    exit /b 1
)
goto WAIT_CDP

:CDP_READY

echo [2/3] 启动 Python 管理器...
cd /d "%SCRIPT_DIR%"

REM 后台启动 Python 脚本（用 pythonw 避免弹出窗口，若无 pythonw 则改用 python）
where pythonw >nul 2>&1
if "%ERRORLEVEL%"=="0" (
    start "" /B pythonw restart_once_a_day.py >"%PY_LOG%" 2>&1
) else (
    start "" /B python restart_once_a_day.py >"%PY_LOG%" 2>&1
)
echo   restart_once_a_day.py 已启动

echo.
echo ========================================
echo   [OK] 启动完成！
echo   [INFO] Chromium CDP: ws://127.0.0.1:%CDP_PORT%
echo   [INFO] 工作目录: %SCRIPT_DIR%
echo ========================================
echo.
echo 按任意键退出启动器（服务继续后台运行）...
pause >nul
