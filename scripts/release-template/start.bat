@echo off
REM ============================================================
REM  Activity Tracker - one-click launcher (release build)
REM  Double-click. UAC will be requested automatically.
REM
REM  No compiler / Node / cmake required: the native binary and
REM  the web UI are pre-built. Only Python 3.10+ is needed.
REM ============================================================

REM --- self-elevate -----------------------------------------------------------
fltmc >nul 2>&1
if %errorlevel% neq 0 goto :elevate

REM --- already admin ----------------------------------------------------------
cd /d "%~dp0"
chcp 65001 >nul

echo.
echo ============================================================
echo  Activity Tracker (release)
echo  Folder: %CD%
echo  Admin:  YES
echo ============================================================
echo.

REM Hoist parens-containing env vars OUT of any if-block.
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
REM  Step 2: install runtime dependencies if missing
REM ============================================================
%PYTHON% -c "import fastapi, psutil, pydantic_settings, prometheus_client" >nul 2>&1
if %errorlevel% equ 0 goto :deps_ok

echo [..] Installing runtime dependencies (one-time, ~30 MB)...
%PYTHON% -m pip install --upgrade pip
if errorlevel 1 goto :pip_failed
%PYTHON% -m pip install -r "%CD%\requirements.txt"
if errorlevel 1 goto :pip_failed

REM MCP server is optional — install if the folder is present so MCP-compatible
REM clients can pick up .mcp.json. Failure here is non-fatal.
if exist "%CD%\mcp\pyproject.toml" (
    echo [..] Installing MCP server ^(optional^)...
    %PYTHON% -m pip install -e "%CD%\mcp"
    if errorlevel 1 echo [WARN] MCP install failed; the backend will still run.
)
goto :deps_ok

:pip_failed
echo [ERROR] pip install failed. See message above.
echo         Make sure you have internet access for the first run.
goto :end_pause


:deps_ok
echo [OK] Runtime dependencies present.


REM ============================================================
REM  Step 3: verify pre-built artifacts
REM ============================================================
if not exist "%CD%\service\native\build\tracker_capture.exe" (
    echo [ERROR] tracker_capture.exe missing.
    echo         The release zip is incomplete. Re-extract it.
    goto :end_pause
)
echo [OK] Native ETW binary present.

if not exist "%CD%\ui\dist\index.html" (
    echo [ERROR] ui\dist\index.html missing.
    echo         The release zip is incomplete. Re-extract it.
    goto :end_pause
)
echo [OK] UI assets present.


REM ============================================================
REM  Step 4: ensure port 8000 is free
REM ============================================================
netstat -ano | findstr ":8000 .*LISTENING" >nul 2>&1
if %errorlevel% neq 0 goto :launch

echo.
echo [ERROR] Port 8000 is already in use.
echo         Run stop.bat to kill the previous backend, or set
echo            set TRACKER_PORT=8001
echo         before re-running start.bat.
goto :end_pause


REM ============================================================
REM  Step 5: launch
REM ============================================================
:launch
REM Wait until backend answers /api/health, then open the browser.
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
