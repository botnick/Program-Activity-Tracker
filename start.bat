@echo off

REM ============================================================
REM  Activity Tracker - One-click launcher (Windows)
REM  Double-click to start. Requests UAC elevation automatically.
REM ============================================================

REM --- self-elevate to admin if not already ----------------------------------
fltmc >nul 2>&1
if %errorlevel% neq 0 goto :request_elevation

cd /d "%~dp0"
chcp 65001 >nul

echo.
echo ============================================================
echo  Activity Tracker
echo  Repo:  %CD%
echo  Admin: YES  ETW capture enabled
echo ============================================================
echo.
echo [DEBUG] cwd=%CD%
echo [DEBUG] LOCALAPPDATA=%LOCALAPPDATA%
echo [DEBUG] SystemRoot=%SystemRoot%
echo.

REM Hoist all %ProgramFiles(x86)%-style references OUTSIDE of any if-block
REM so the parens in (x86) don't confuse the CMD parser.
set "PF86=%ProgramFiles(x86)%"
set "PF=%ProgramFiles%"

goto :find_python


:request_elevation
echo [INFO] Requesting Administrator elevation...
powershell -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList '/k','\"%~f0\"' -Verb RunAs"
exit /b


REM ============================================================
REM  Locate Python
REM ============================================================
:find_python
set PYTHON=
where python >nul 2>&1 && set PYTHON=python
if defined PYTHON goto :python_found

if exist "%SystemRoot%\py.exe" set "PYTHON=py -3"
if defined PYTHON goto :python_found

if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if defined PYTHON goto :python_found
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined PYTHON goto :python_found
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if defined PYTHON goto :python_found
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if defined PYTHON goto :python_found

if exist "%PF%\Python313\python.exe" set "PYTHON=%PF%\Python313\python.exe"
if defined PYTHON goto :python_found
if exist "%PF%\Python312\python.exe" set "PYTHON=%PF%\Python312\python.exe"
if defined PYTHON goto :python_found
if exist "%PF%\Python311\python.exe" set "PYTHON=%PF%\Python311\python.exe"
if defined PYTHON goto :python_found
if exist "%PF%\Python310\python.exe" set "PYTHON=%PF%\Python310\python.exe"
if defined PYTHON goto :python_found

echo [ERROR] Python 3.10+ not found in PATH or known install locations.
echo         Install Python 3.10+ from https://www.python.org/downloads/
echo         and tick "Add Python to PATH" during install.
pause
exit /b 1


:python_found
echo [INFO] Using Python: %PYTHON%

REM ============================================================
REM  Backend deps
REM ============================================================
echo [INFO] Checking backend dependencies...
%PYTHON% -c "import fastapi, psutil, pydantic_settings" >nul 2>&1
if %errorlevel% equ 0 goto :deps_ok

echo [INFO] Installing backend dependencies, one-time setup...
%PYTHON% -m pip install --upgrade pip
if errorlevel 1 goto :pip_failed
%PYTHON% -m pip install -e ".[dev]"
if errorlevel 1 goto :pip_failed
goto :deps_ok

:pip_failed
echo [ERROR] pip install failed.
pause
exit /b 1


:deps_ok
REM ============================================================
REM  Native ETW binary
REM ============================================================
set BIN1=service\native\build\tracker_capture.exe
set BIN2=service\native\build\Release\tracker_capture.exe
if exist "%BIN1%" goto :native_ok
if exist "%BIN2%" goto :native_ok

echo [INFO] Native ETW binary missing; locating Visual Studio...
set "VSWHERE=%PF86%\Microsoft Visual Studio\Installer\vswhere.exe"
set "VSDEVCMD="
if not exist "%VSWHERE%" goto :no_vs
for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -property installationPath`) do set "VSDEVCMD=%%i\Common7\Tools\VsDevCmd.bat"
if not defined VSDEVCMD goto :no_vs

echo [INFO] Found VsDevCmd: %VSDEVCMD%
echo [INFO] Building native binary, this takes ~10-20 seconds...
cmd /c ""%VSDEVCMD%" -arch=amd64 && cmake -S service\native -B service\native\build -G Ninja -DCMAKE_BUILD_TYPE=Release && cmake --build service\native\build --config Release"
if exist "%BIN1%" goto :native_ok
if exist "%BIN2%" goto :native_ok
echo [WARN] Native build did not produce an exe. ETW capture will not work.
echo        Run scripts\setup-defender-exclusion.ps1 if Defender is blocking.
goto :ui_check

:no_vs
echo [WARN] Visual Studio not detected. Native ETW capture will not work.
echo        Install Visual Studio 2022+ with the C++ workload, then re-run.
goto :ui_check


:native_ok
echo [INFO] Native ETW binary OK.


:ui_check
REM ============================================================
REM  UI build
REM ============================================================
if exist "ui\dist\index.html" goto :ui_ok
where npm >nul 2>&1
if errorlevel 1 goto :no_npm
echo [INFO] Building UI, one-time setup...
pushd ui
if not exist node_modules call npm install
call npm run build
popd
goto :ui_ok

:no_npm
echo [WARN] npm not on PATH; UI will not be served. Install Node.js 20+.


:ui_ok
REM ============================================================
REM  Port check
REM ============================================================
netstat -ano | findstr ":8000 .*LISTENING" >nul 2>&1
if %errorlevel% neq 0 goto :start_backend
echo.
echo [ERROR] Port 8000 is already in use. Run stop.bat first.
pause
exit /b 1


:start_backend
start "" /b cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:8000"

echo.
echo [INFO] Starting backend on http://127.0.0.1:8000
echo [INFO] Press Ctrl+C to stop.
echo.

%PYTHON% -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --ws-ping-interval 60 --ws-ping-timeout 60

echo.
echo [INFO] Backend stopped.
pause
