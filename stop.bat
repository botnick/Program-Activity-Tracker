@echo off
REM ============================================================
REM  Activity Tracker - graceful stop
REM
REM  Kills:
REM   1. Whatever is LISTENING on port 8000 (the FastAPI backend)
REM   2. Any orphan tracker_capture.exe (the native ETW consumer)
REM   3. Any leftover ETW sessions named ActivityTracker-* (logman)
REM
REM  Safe to run when nothing is up — every step is best-effort.
REM ============================================================

REM --- self-elevate (needed to taskkill the elevated tracker_capture.exe
REM     and to logman-stop kernel sessions started elevated) -----------------
fltmc >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator elevation...
    powershell -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList '/k','\"%~f0\"' -Verb RunAs"
    exit /b 0
)

setlocal EnableDelayedExpansion
chcp 65001 >nul

set "PORT=%TRACKER_PORT%"
if not defined PORT set "PORT=8000"

echo.
echo ============================================================
echo  Activity Tracker - stopping
echo ============================================================
echo.

REM --- 1) port 8000 backend --------------------------------------------------
set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT% .*LISTENING"') do (
    set /a FOUND+=1
    echo [..] Killing PID %%a on port %PORT%
    taskkill /F /PID %%a >nul 2>&1
)
if !FOUND! equ 0 echo [OK] No listener on port %PORT%.

REM --- 2) native ETW consumer ------------------------------------------------
tasklist /FI "IMAGENAME eq tracker_capture.exe" 2>nul | findstr /I "tracker_capture.exe" >nul
if errorlevel 1 (
    echo [OK] No tracker_capture.exe running.
) else (
    echo [..] Killing tracker_capture.exe
    taskkill /F /IM tracker_capture.exe >nul 2>&1
)

REM --- 3) orphan ETW sessions ------------------------------------------------
REM Stop any sessions whose name starts with "ActivityTracker-" so a fresh
REM start doesn't collide. logman is part of every Windows install since 2003.
set ETW_FOUND=0
for /f "tokens=1" %%s in ('logman query -ets 2^>nul ^| findstr /I /B /C:"ActivityTracker-"') do (
    set /a ETW_FOUND+=1
    echo [..] Stopping ETW session %%s
    logman stop %%s -ets >nul 2>&1
)
if !ETW_FOUND! equ 0 echo [OK] No orphan ETW sessions.

echo.
echo Done.
echo.
pause
