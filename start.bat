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

REM --- check Python (try python, then py.exe launcher) ----------------------
set PYTHON=
where python >nul 2>&1 && set PYTHON=python
if not defined PYTHON (
    where py >nul 2>&1 && set PYTHON=py -3
)
if not defined PYTHON (
    echo [ERROR] Python 3.10+ not found.
    echo         Install from https://www.python.org/downloads/  (tick "Add to PATH")
    echo         or from the Microsoft Store.
    pause
    exit /b 1
)

REM --- ensure backend deps installed -----------------------------------------
%PYTHON% -c "import fastapi, psutil, etw" >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Installing backend dependencies (one-time)...
    %PYTHON% -m pip install --upgrade pip
    %PYTHON% -m pip install -e ".[dev]"
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

%PYTHON% -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

echo.
echo [INFO] Backend stopped.
pause
