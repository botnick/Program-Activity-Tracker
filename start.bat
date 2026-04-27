@echo off

REM ============================================================
REM  Activity Tracker - One-click launcher (Windows)
REM  Double-click to start. Requests UAC elevation automatically.
REM ============================================================

REM --- self-elevate to admin if not already ----------------------------------
REM We launch the elevated copy via `cmd /k <script>` so that the window
REM stays open even if the script exits early (failed dep install, port
REM already bound, etc). Without /k the window would close instantly,
REM hiding the error message.
fltmc >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Requesting Administrator elevation...
    powershell -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList '/k','\"%~f0\"' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
chcp 65001 >nul

REM Show diagnostics so any failure is visible before pause.
echo [DEBUG] cwd=%CD%
echo [DEBUG] LOCALAPPDATA=%LOCALAPPDATA%
echo [DEBUG] SystemRoot=%SystemRoot%

echo.
echo ============================================================
echo  Activity Tracker
echo  Repo:  %CD%
echo  Admin: YES  (ETW capture enabled)
echo ============================================================
echo.

REM --- locate Python ---------------------------------------------------------
REM UAC-elevated shells often lose user PATH, so we search known install
REM locations after PATH lookup fails. Prefer the system-wide py launcher.

set PYTHON=
where python >nul 2>&1 && set PYTHON=python
if not defined PYTHON if exist "%SystemRoot%\py.exe" set PYTHON=py -3
if not defined PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if not defined PYTHON if exist "%ProgramFiles%\Python313\python.exe" set "PYTHON=%ProgramFiles%\Python313\python.exe"
if not defined PYTHON if exist "%ProgramFiles%\Python312\python.exe" set "PYTHON=%ProgramFiles%\Python312\python.exe"
if not defined PYTHON if exist "%ProgramFiles%\Python311\python.exe" set "PYTHON=%ProgramFiles%\Python311\python.exe"
if not defined PYTHON if exist "%ProgramFiles%\Python310\python.exe" set "PYTHON=%ProgramFiles%\Python310\python.exe"

if not defined PYTHON (
    echo [ERROR] Python 3.10+ not found.
    echo.
    echo         Searched: PATH, %%SystemRoot%%\py.exe, and Python310-313 in:
    echo           %LOCALAPPDATA%\Programs\Python\
    echo           %ProgramFiles%\
    echo.
    echo         Install Python 3.10+ from https://www.python.org/downloads/
    echo         and tick "Add Python to PATH" during install.
    pause
    exit /b 1
)

echo [INFO] Using Python: %PYTHON%

REM Wrap in quotes if the resolved path has spaces (e.g. Program Files).
echo %PYTHON% | findstr /c:" " >nul
if %errorlevel% equ 0 (
    echo %PYTHON% | findstr /b /c:^" >nul
    if errorlevel 1 set PYTHON="%PYTHON%"
)

REM --- ensure backend deps installed -----------------------------------------
echo [INFO] Checking backend dependencies...
%PYTHON% -c "import fastapi, psutil, pydantic_settings" >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Installing backend dependencies ^(one-time^)...
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
    echo [INFO] Native ETW binary missing; building via Visual Studio...
    set VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe
    set VSDEVCMD=
    if exist "%VSWHERE%" (
        for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -property installationPath`) do set VSDEVCMD=%%i\Common7\Tools\VsDevCmd.bat
    )
    if not defined VSDEVCMD (
        echo [WARN] Visual Studio not detected. Native ETW capture will not work.
        echo        Install Visual Studio 2022+ with C++ workload, then re-run this script.
    ) else (
        echo [INFO] Found VsDevCmd at: %VSDEVCMD%
        cmd /c ""%VSDEVCMD%" -arch=amd64 && cmake -S service\native -B service\native\build -G Ninja -DCMAKE_BUILD_TYPE=Release && cmake --build service\native\build --config Release"
        if not exist "%BIN1%" if not exist "%BIN2%" (
            echo [WARN] Native build did not produce an exe. ETW capture will not work.
            echo        Run scripts\setup-defender-exclusion.ps1 if Defender is blocking.
        )
    )
) else (
    echo [INFO] Native ETW binary OK.
)

REM --- build the UI if dist is missing ---------------------------------------
if not exist "ui\dist\index.html" (
    where npm >nul 2>&1
    if %errorlevel% neq 0 (
        echo [WARN] npm not on PATH; UI will not be served. Install Node.js 20+.
    ) else (
        echo [INFO] Building UI ^(one-time^)...
        pushd ui
        if not exist node_modules (
            call npm install
        )
        call npm run build
        popd
    )
) else (
    echo [INFO] UI dist OK.
)

REM --- check port 8000 is free -----------------------------------------------
netstat -ano | findstr ":8000 .*LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo.
    echo [ERROR] Port 8000 is already in use. Run stop.bat first, or set
    echo         a different port:  set TRACKER_PORT=8001 ^&^& start.bat
    echo.
    pause
    exit /b 1
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
