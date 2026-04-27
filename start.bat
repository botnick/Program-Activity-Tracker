@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul

REM ============================================================
REM Activity Tracker — One-click launcher (Windows)
REM ดับเบิลคลิกเพื่อเริ่มใช้งาน. หากไม่ได้รัน Administrator จะขอ UAC อัตโนมัติ
REM ============================================================

REM --- self-elevate to admin if not already ----------------------------------
fltmc >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Requesting Administrator elevation...
    powershell -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

echo.
echo ============================================================
echo  Activity Tracker
echo  Repo:  %CD%
echo  Admin: YES  (ETW capture enabled)
echo ============================================================
echo.

REM --- check Python ----------------------------------------------------------
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not on PATH. Install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

REM --- ensure backend deps installed -----------------------------------------
python -c "import fastapi, psutil, etw" >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Installing backend dependencies (one-time)...
    python -m pip install --upgrade pip
    python -m pip install -e ".[dev]"
    if %errorlevel% neq 0 (
        echo [ERROR] pip install failed.
        pause
        exit /b 1
    )
)

REM --- build the UI if dist is missing ---------------------------------------
if not exist "ui\dist\index.html" (
    where npm >nul 2>&1
    if %errorlevel% neq 0 (
        echo [WARN] npm not on PATH; UI will not be served. Install Node.js 20+ to enable the web UI.
    ) else (
        echo [INFO] Building UI (one-time)...
        pushd ui
        if not exist node_modules (
            call npm install
        )
        call npm run build
        popd
    )
)

REM --- open the browser tab in 3 seconds (after backend has time to bind) ----
start "" /b cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:8000"

echo.
echo [INFO] Starting backend on http://127.0.0.1:8000
echo [INFO] Press Ctrl+C to stop.
echo.

python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

echo.
echo [INFO] Backend stopped.
pause
