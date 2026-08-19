@echo off
REM start_ragent.bat — singleton launcher for the ONLINE autonomous agent.
REM Runs OUTSIDE any MSYS/bash shell (double-click, or `cmd /c start_ragent.bat`).
REM
REM Runtime graph (correct entrypoint):
REM   start_ragent.bat -> browser_bridge.cjs -> Chrome/live WoC
REM                      -> BrowserEnv -> play_autonomous.py -> Agent -> Policy/Memory/Reward
REM
REM SINGLETON: keeps exactly ONE bridge + ONE agent alive. Each child writes
REM its OWN pid to a .pid file at startup (node -e / python -c), so the launcher
REM tracks the real child, not the parent cmd. On each loop we check the recorded
REM PID is still alive; if not, we restart that one process only.
REM
REM NOTE: no `git pull` here. The agent must run the COMMITTED version of the
REM code; pulling mid-run would silently swap the revision under a long self-play
REM experiment and corrupt it. Update + restart deliberately.

setlocal
REM REPO = directory this .bat lives in (no hard-coded path)
set "REPO=%~dp0"
set "PY=%REPO%.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=D:\woc-llm\therock-test\Scripts\python.exe"
set "LOG=%REPO%ragent_launcher.log"
set "BRIDGE_PID=%REPO%bridge.pid"
set "AGENT_PID=%REPO%python\agent.pid"

echo [%date% %time%] launcher start >> "%LOG%"

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
  REM --- bridge (writes its own pid) ---
  call :pid_alive "%BRIDGE_PID%"
  if errorlevel 1 (
    echo [%date% %time%] starting bridge >> "%LOG%"
    start "woc-bridge" /min cmd /c "cd /d "%REPO%" && node -e "require('fs').writeFileSync('bridge.pid', String(process.pid))" && node browser_bridge.cjs >> "%REPO%bridge_smoke.log" 2>&1"
    REM give it a moment to bind the port before we might spawn a duplicate
    timeout /t 4 /nobreak >nul
  )

  REM --- agent (writes its own pid; -I isolates from Hermes venv; project dir
  REM     added to sys.path so local imports resolve) ---
  call :pid_alive "%AGENT_PID%"
  if errorlevel 1 (
    echo [%date% %time%] starting play_autonomous >> "%LOG%"
    start "woc-agent" /min cmd /c "cd /d "%REPO%python" && "%PY%" -I -c "import os; os.chdir(r'%REPO%python'); open('agent.pid','w').write(str(os.getpid())); import runpy; runpy.run_path(r'%REPO%python\play_autonomous.py', run_name='__main__')" >> "%REPO%python\agent_run.log" 2>&1"
  )

  REM check every 10s
  timeout /t 10 /nobreak >nul
goto loop
