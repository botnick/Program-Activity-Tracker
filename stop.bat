@echo off
chcp 65001 >nul
REM Stop any uvicorn / Activity Tracker backend listening on port 8000.

echo [INFO] Looking for processes on port 8000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 .*LISTENING"') do (
    echo [INFO] Killing PID %%a
    taskkill /F /PID %%a >nul 2>&1
)

REM Also stop any lingering tracker_capture.exe (native ETW engine).
taskkill /F /IM tracker_capture.exe >nul 2>&1

echo [INFO] Done.
pause
