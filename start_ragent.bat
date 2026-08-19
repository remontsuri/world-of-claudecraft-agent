@echo off
REM start_ragent.bat — stable singleton launcher for the ONLINE autonomous agent.
REM Runs OUTSIDE any MSYS/bash shell (double-click, or `cmd /c start_ragent.bat`).
REM
REM Runtime graph (correct entrypoint):
REM   start_ragent.bat -> browser_bridge.cjs -> Chrome/live WoC
REM                      -> BrowserEnv -> play_autonomous.py -> Agent -> Policy/Memory/Reward
REM
REM SINGLETON: this launcher keeps exactly ONE bridge + ONE agent alive. Process
REM identity is tracked via .pid files (not WMIC/findstr, which proved flaky and
REM caused duplicate spawns that fought over port :8791). On each loop we check
REM the recorded PID is still alive; if not, we restart that one process only.

setlocal
REM REPO = directory this .bat lives in (no hard-coded path)
set "REPO=%~dp0"
set "PY=%REPO%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=D:\woc-llm\therock-test\Scripts\python.exe"
set "LOG=%REPO%ragent_launcher.log"
set "BRIDGE_PID=%REPO%bridge.pid"
set "AGENT_PID=%REPO%python\agent.pid"

echo [%date% %time%] launcher start >> "%LOG%"

REM Pull latest fixes so bridge/agent always run the committed fixed code.
cd /d "%REPO%"
git pull mine backup >> "%LOG%" 2>&1

REM Is a PID still alive? sets errorlevel 0 if alive, 1 if dead/missing.
:pid_alive
if not exist "%~1" exit /b 1
set "PID="
for /f "usebackq tokens=*" %%a in ("%~1") do set "PID=%%a"
if "%PID%"=="" exit /b 1
tasklist /FI "PID eq %PID%" 2>nul | find ":%PID%" >nul
if errorlevel 1 exit /b 1
exit /b 0

:loop
  REM --- bridge ---
  call :pid_alive "%BRIDGE_PID%"
  if errorlevel 1 (
    echo [%date% %time%] starting bridge >> "%LOG%"
    start "woc-bridge" /min cmd /c "cd /d "%REPO%" && node browser_bridge.cjs >> "%REPO%bridge_smoke.log" 2>&1 & echo %^PID% > "%BRIDGE_PID%""
    REM give it a moment to bind the port before we might spawn a duplicate
    timeout /t 4 /nobreak >nul
  )

  REM --- agent ---
  call :pid_alive "%AGENT_PID%"
  if errorlevel 1 (
    echo [%date% %time%] starting play_autonomous >> "%LOG%"
    start "woc-agent" /min cmd /c "cd /d "%REPO%python" && set PYTHONPATH= && "%PY%" play_autonomous.py >> "%REPO%python\agent_run.log" 2>&1 & echo %^PID% > "%AGENT_PID%""
  )

  REM check every 10s
  timeout /t 10 /nobreak >nul
goto loop
