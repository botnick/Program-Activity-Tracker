@echo off
setlocal EnableDelayedExpansion

REM ============================================================
REM  Activity Tracker - One-click launcher (Windows)
REM  Double-click to start. Requests UAC elevation automatically.
REM ============================================================

REM --- self-elevate to admin if not already ----------------------------------
fltmc >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Requesting Administrator elevation...
    powershell -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
chcp 65001 >nul

echo.
echo ============================================================
echo  Activity Tracker
echo  Repo:  %CD%
echo  Admin: YES  (ETW capture enabled)
echo ============================================================
echo.

REM --- locate Python ---------------------------------------------------------
REM UAC-elevated shells often lose user PATH, so search known install
REM locations after PATH lookup fails.
set PYTHON=
where python >nul 2>&1 && set PYTHON=python
if not defined PYTHON (
    where py >nul 2>&1 && set "PYTHON=py -3"
)
if not defined PYTHON (
    REM Search per-user installs (Python.org default for "Install for me")
    for %%V in (313 312 311 310) do (
        if not defined PYTHON (
            if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
                set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
            )
        )
    )
)
if not defined PYTHON (
    REM Search system-wide installs
    for %%V in (313 312 311 310) do (
        if not defined PYTHON (
            if exist "%ProgramFiles%\Python%%V\python.exe" set "PYTHON=%ProgramFiles%\Python%%V\python.exe"
            if exist "%ProgramFiles(x86)%\Python%%V\python.exe" set "PYTHON=%ProgramFiles(x86)%\Python%%V\python.exe"
        )
    )
)
if not defined PYTHON (
    REM Try py launcher at the standard Windows install path
    if exist "%SystemRoot%\py.exe" set "PYTHON=%SystemRoot%\py.exe -3"
)
if not defined PYTHON (
    echo [ERROR] Python 3.10+ not found in PATH or known install locations.
    echo.
    echo         Searched:
    echo           - PATH ^(where python / where py^)
    echo           - %LOCALAPPDATA%\Programs\Python\Python310-313
    echo           - %ProgramFiles%\Python310-313
    echo           - %SystemRoot%\py.exe
    echo.
    echo         Install Python 3.10+ from https://www.python.org/downloads/
    echo         and tick "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)

echo [INFO] Using Python: %PYTHON%

REM Quote the path if it contains spaces and isn't already quoted.
echo %PYTHON% | findstr /c:"\"" >nul
if %errorlevel% neq 0 (
    echo %PYTHON% | findstr /c:" " >nul
    if %errorlevel% equ 0 set "PYTHON=\"%PYTHON%\""
)

REM --- ensure backend deps installed -----------------------------------------
%PYTHON% -c "import fastapi, psutil, pydantic_settings" >nul 2>&1
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

REM --- build native ETW binary if missing ------------------------------------
set BIN1=service\native\build\tracker_capture.exe
set BIN2=service\native\build\Release\tracker_capture.exe
if not exist "%BIN1%" if not exist "%BIN2%" (
    echo [INFO] Native ETW binary missing; building via Visual Studio Developer env...
    set VSDEVCMD=
    set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
    if exist "!VSWHERE!" (
        for /f "usebackq tokens=*" %%i in (`"!VSWHERE!" -latest -property installationPath`) do set "VSDEVCMD=%%i\Common7\Tools\VsDevCmd.bat"
    )
    if not defined VSDEVCMD (
        echo [WARN] Visual Studio not detected. Native ETW capture will not work.
        echo        Install Visual Studio 2022+ with C++ workload, then re-run this script.
    ) else (
        cmd /c ""!VSDEVCMD!" -arch=amd64 ^&^& cmake -S service\native -B service\native\build -G Ninja -DCMAKE_BUILD_TYPE=Release ^&^& cmake --build service\native\build --config Release"
        if not exist "%BIN1%" if not exist "%BIN2%" (
            echo [ERROR] Native build failed. ETW capture will not work.
            echo         Run scripts\setup-defender-exclusion.ps1 first if Defender is blocking output.
        )
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
