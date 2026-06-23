@echo off
title xunlei-api launcher

echo [0/3] Killing old processes...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /c:":5000 "') do (
    taskkill /f /pid %%a >nul 2>&1
)
taskkill /f /im msedge.exe >nul 2>&1
timeout /t 2 /nobreak >nul

echo [1/3] Starting Edge with remote debugging port 9222...
start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9222 --user-data-dir=C:\selenium_user_data --no-first-run --no-default-browser-check

echo Waiting 5 seconds for Edge to be ready...
timeout /t 5 /nobreak >nul

echo [2/3] Starting Python manager...
cd /d C:\Users\tzz\.openclaw\workspace\xunlei-api-v5
start /min "" python restart_once_a_day.py

echo Done!
timeout /t 3 /nobreak >nul
