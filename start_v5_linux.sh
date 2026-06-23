#!/bin/bash
# start_v5_linux.sh — Linux 版启动脚本（替代 start_v5-先启动openlist再点我.bat）
# 用法: bash start_v5_linux.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CHROME_BIN="/root/.cache/ms-playwright/chromium-1223/chrome-linux/chrome"
CHROME_DATA="/root/chromium_user_data"
DISPLAY_NUM=":99"

echo "[0/3] 清理旧进程..."
# 杀掉旧 Chromium
pkill -f "chrome.*remote-debugging-port=9222" 2>/dev/null || true
# 杀掉旧 Python 进程（根据实际需要调整）
pkill -f "restart_once_a_day.py" 2>/dev/null || true
sleep 2

echo "[1/3] 启动 Xvfb 虚拟显示..."
if ! pgrep -f "Xvfb ${DISPLAY_NUM}" > /dev/null; then
    Xvfb ${DISPLAY_NUM} -screen 0 1920x1080x24 -ac &>/dev/null &
    sleep 2
    echo "  Xvfb 已启动 (PID: $!)"
else
    echo "  Xvfb 已在运行"
fi
export DISPLAY=${DISPLAY_NUM}

echo "[1/3] 启动 Chromium（CDP 端口 9222）..."
mkdir -p "${CHROME_DATA}"
"${CHROME_BIN}" \
    --remote-debugging-port=9222 \
    --remote-allow-origins=* \
    --no-sandbox \
    --disable-dev-shm-usage \
    --user-data-dir="${CHROME_DATA}" \
    --window-size=1920,1080 \
    about:blank &>/tmp/chrome_v5.log &
CHROME_PID=$!
echo "  Chromium 已启动 (PID: ${CHROME_PID})"

echo "等待 5 秒让 Chromium 就绪..."
sleep 5

# 验证 CDP 是否可用
if curl -s http://127.0.0.1:9222/json/version > /dev/null 2>&1; then
    echo "  ✅ CDP 端口 9222 正常响应"
else
    echo "  ❌ CDP 端口无响应，请检查 Chromium 启动日志: /tmp/chrome_v5.log"
    exit 1
fi

echo "[2/3] 启动 Python 管理器..."
cd "${SCRIPT_DIR}"
nohup python3 restart_once_a_day.py &>/tmp/restart_once_a_day.log &
echo "  restart_once_a_day.py 已启动 (PID: $!)"

echo ""
echo "========================================"
echo "  ✅ 启动完成！"
echo "  📌 Chromium CDP: ws://127.0.0.1:9222"
echo "  📌 工作目录: ${SCRIPT_DIR}"
echo "========================================"
