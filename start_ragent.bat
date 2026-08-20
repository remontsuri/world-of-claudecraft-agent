@echo off
REM start_ragent.bat — singleton launcher for the ONLINE autonomous agent.
REM Double-click to run. Keeps ONE bridge + ONE agent alive, restarts the dead one.
REM Crash visibility: agent writes full traceback to python/agent_crash.log
REM (see play_autonomous.py sys.excepthook); bridge appends exit to bridge_crash.txt.
REM Both also log stderr to bridge_smoke.log / agent_run.log.

setlocal enabledelayedexpansion
set "REPO=%~dp0"
set "REPO=%REPO:~0,-1%"

set "PY=%REPO%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=D:\woc-llm\therock-test\Scripts\python.exe"

set "LOG=%REPO%\ragent_launcher.log"
set "BRIDGE_PID=%REPO%\bridge.pid"
set "BRIDGE_LOG=%REPO%\bridge_smoke.log"
set "AGENT_PID=%REPO%\python\play_autonomous.lock"
set "AGENT_LOG=%REPO%\python\agent_run.log"
set "LAUNCHER_PID=%REPO%\launcher.pid"
set "MAX_LOG_SIZE=10485760"

echo launcher > "%LAUNCHER_PID%"

call :rotate_log "%LOG%"
echo [%date% %time%] launcher start >> "%LOG%"

goto loop

:pid_alive
if not exist "%~1" exit /b 1
set "PID="
for /f "usebackq tokens=*" %%a in ("%~1") do set "PID=%%a"
if "%PID%"=="" exit /b 1
tasklist /FI "PID eq %PID%" 2>nul | findstr /C:%PID% >nul
if errorlevel 1 exit /b 1
exit /b 0

:bridge_health
set "BH="
for /f "tokens=*" %%R in ('powershell -NoProfile -Command "try{(Invoke-WebRequest -Uri http://127.0.0.1:8791/health -TimeoutSec 2 -UseBasicParsing).Content}catch{exit 1}" 2^>nul') do set "BH=%%R"
echo %BH% | findstr game >nul
if not errorlevel 1 exit /b 0
exit /b 1

:rotate_log
if not exist "%~1" exit /b 0
for %%A in ("%~1") do set "FSZ=%%~zA"
if !FSZ! GTR %MAX_LOG_SIZE% (
    if exist "%~1.bak" del /f /q "%~1.bak"
    rename "%~1" "%~nx1.bak"
)
exit /b 0

:loop
  call :rotate_log "%LOG%"

  call :pid_alive "%BRIDGE_PID%"
  if errorlevel 1 (
    echo [%date% %time%] starting bridge >> "%LOG%"
    call :rotate_log "%BRIDGE_LOG%"
    start "woc-bridge" /min cmd /c "%REPO%\bridge_launch.bat" >> "%BRIDGE_LOG%" 2^>^&1
    ping -n 5 127.0.0.1 >nul
  )

  call :bridge_health
  if errorlevel 1 (
    echo [%date% %time%] bridge not ready yet - skipping agent start >> "%LOG%"
    goto wait
  )
  call :pid_alive "%AGENT_PID%"
  if errorlevel 1 (
    echo [%date% %time%] starting play_autonomous >> "%LOG%"
    call :rotate_log "%AGENT_LOG%"
    start "woc-agent" /min cmd /c cd /d %REPO%\python ^&^& set "PYTHONPATH=%REPO%\python" ^&^& "%PY%" -X faulthandler -m play_autonomous >> "%AGENT_LOG%" 2^>^&1
  )

  :wait
  ping -n 11 127.0.0.1 >nul
goto loop
