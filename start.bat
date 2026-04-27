@echo off
REM ============================================================
REM  Activity Tracker - one-click launcher
REM  Double-click. UAC will be requested automatically.
REM ============================================================

REM --- self-elevate -----------------------------------------------------------
fltmc >nul 2>&1
if %errorlevel% neq 0 goto :elevate

REM --- already admin ----------------------------------------------------------
cd /d "%~dp0"
chcp 65001 >nul

echo.
echo ============================================================
echo  Activity Tracker
echo  Repo:  %CD%
echo  Admin: YES
echo ============================================================
echo.

REM Hoist parens-containing env vars OUT of any if-block (CMD parser
REM trips on (x86) inside multi-line if).
set "PF86=%ProgramFiles(x86)%"
set "PF=%ProgramFiles%"

goto :find_python


REM ============================================================
:elevate
echo Requesting Administrator elevation...
powershell -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList '/k','\"%~f0\"' -Verb RunAs"
exit /b 0


REM ============================================================
REM  Step 1: locate Python
REM  UAC-elevated shells often lose user PATH, so we try several
REM  known install locations after a regular PATH lookup.
REM ============================================================
:find_python
set "PYTHON="

where python >nul 2>&1 && set "PYTHON=python"
if defined PYTHON goto :have_python

if exist "%SystemRoot%\py.exe" set "PYTHON=py -3"
if defined PYTHON goto :have_python

if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if defined PYTHON goto :have_python
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined PYTHON goto :have_python
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if defined PYTHON goto :have_python
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if defined PYTHON goto :have_python
if exist "%PF%\Python313\python.exe" set "PYTHON=%PF%\Python313\python.exe"
if defined PYTHON goto :have_python
if exist "%PF%\Python312\python.exe" set "PYTHON=%PF%\Python312\python.exe"
if defined PYTHON goto :have_python
if exist "%PF%\Python311\python.exe" set "PYTHON=%PF%\Python311\python.exe"
if defined PYTHON goto :have_python
if exist "%PF%\Python310\python.exe" set "PYTHON=%PF%\Python310\python.exe"
if defined PYTHON goto :have_python

echo [ERROR] Python 3.10+ not found.
echo         Install from https://www.python.org/downloads/ and tick
echo         "Add Python to PATH" during install. Then re-run start.bat.
goto :end_pause


:have_python
echo [OK] Python: %PYTHON%


REM ============================================================
REM  Step 2: install backend dependencies if missing
REM ============================================================
%PYTHON% -c "import fastapi, psutil, pydantic_settings, prometheus_client" >nul 2>&1
if %errorlevel% equ 0 goto :deps_ok

echo [..] Installing backend dependencies...
%PYTHON% -m pip install --upgrade pip
if errorlevel 1 goto :pip_failed
%PYTHON% -m pip install -e ".[dev]"
if errorlevel 1 goto :pip_failed
goto :deps_ok

:pip_failed
echo [ERROR] pip install failed. See message above.
goto :end_pause


:deps_ok
echo [OK] Backend dependencies present.


REM ============================================================
REM  Step 3: build native ETW binary if missing
REM ============================================================
set "BIN1=%CD%\service\native\build\tracker_capture.exe"
set "BIN2=%CD%\service\native\build\Release\tracker_capture.exe"
if exist "%BIN1%" goto :native_ok
if exist "%BIN2%" goto :native_ok

echo [..] Native ETW binary missing. Locating Visual Studio...
set "VSWHERE=%PF86%\Microsoft Visual Studio\Installer\vswhere.exe"
set "VSDEVCMD="
if not exist "%VSWHERE%" goto :no_vs

for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -property installationPath`) do set "VSDEVCMD=%%i\Common7\Tools\VsDevCmd.bat"
if not defined VSDEVCMD goto :no_vs
if not exist "%VSDEVCMD%" goto :no_vs

echo [..] Building tracker_capture.exe with %VSDEVCMD%
cmd /c ""%VSDEVCMD%" -arch=amd64 && cmake -S service\native -B service\native\build -G Ninja -DCMAKE_BUILD_TYPE=Release && cmake --build service\native\build --config Release"

if exist "%BIN1%" goto :native_ok
if exist "%BIN2%" goto :native_ok

echo [WARN] Native build did not produce an exe.
echo        ETW capture will not work until the binary is built.
echo        Run scripts\setup-defender-exclusion.ps1 first if Defender is blocking.
goto :ui_check


:no_vs
echo [WARN] Visual Studio with C++ workload not detected.
echo        ETW capture (live event streaming) will not work.
echo        Install VS 2022+ with the "Desktop development with C++" workload,
echo        then re-run start.bat to build the native binary.
goto :ui_check


:native_ok
echo [OK] Native ETW binary present.


REM ============================================================
REM  Step 4: build UI if dist is missing
REM ============================================================
:ui_check
if exist "%CD%\ui\dist\index.html" goto :ui_ok

where npm >nul 2>&1
if errorlevel 1 goto :no_npm

echo [..] Building UI...
pushd ui
if not exist node_modules (
    call npm install
)
call npm run build
popd
if exist "%CD%\ui\dist\index.html" goto :ui_ok

echo [WARN] UI build failed; backend will still run but the / route returns 404.
goto :port_check


:no_npm
echo [WARN] Node.js / npm not on PATH.
echo        Install Node.js 20+ from https://nodejs.org/ to enable the web UI.
goto :port_check


:ui_ok
echo [OK] UI dist present.


REM ============================================================
REM  Step 5: ensure port 8000 is free
REM ============================================================
:port_check
netstat -ano | findstr ":8000 .*LISTENING" >nul 2>&1
if %errorlevel% neq 0 goto :launch

echo.
echo [ERROR] Port 8000 is already in use.
echo         Run stop.bat to kill the previous backend, or set
echo            set TRACKER_PORT=8001
echo         before re-running start.bat.
goto :end_pause


REM ============================================================
REM  Step 6: launch
REM ============================================================
:launch
REM Wait until the backend answers /api/health then open the browser
REM (PowerShell because cmd's `for /l` is awkward to nest through `cmd /c`).
start "" /b powershell -NoProfile -Command "1..30 | ForEach-Object { try { Invoke-WebRequest -Uri http://127.0.0.1:8000/api/health -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop | Out-Null; Start-Process 'http://127.0.0.1:8000'; exit 0 } catch { Start-Sleep -Seconds 1 } }"

echo.
echo ============================================================
echo  Backend starting on http://127.0.0.1:8000
echo  Press Ctrl+C in this window to stop.
echo ============================================================
echo.

%PYTHON% -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --ws-ping-interval 60 --ws-ping-timeout 60

echo.
echo Backend stopped.

:end_pause
echo.
pause
