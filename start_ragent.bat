@echo off
REM start_ragent.bat — singleton launcher for the ONLINE autonomous agent.
REM Runs OUTSIDE any MSYS/bash shell (double-click, or `cmd /c start_ragent.bat`).
REM
REM Runtime graph (correct entrypoint):
REM   start_ragent.bat -> browser_bridge.cjs -> Chrome/live WoC
REM                      -> BrowserEnv -> play_autonomous.py -> Agent -> Policy/Memory/Reward
REM
REM SINGLETON: keeps exactly ONE bridge + ONE agent alive. PID is captured
REM reliably via PowerShell Start-Process -PassThru (NOT %^PID%, which is the
REM parent cmd's PID, not the child's). On each loop we check the recorded PID
REM is still alive; if not, we restart that one process only.

setlocal
REM REPO = directory this .bat lives in (no hard-coded path)
set "REPO=%~dp0"
set "PY=%REPO%.venv\Scripts\python.exe"
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
    REM PowerShell reliably returns the child PID; write it to the pid file.
    powershell -NoProfile -Command "Start-Process -FilePath 'node.exe' -ArgumentList 'browser_bridge.cjs' -WorkingDirectory '%REPO%' -RedirectStandardOutput '%REPO%bridge_smoke.log' -RedirectStandardError '%REPO%bridge_smoke.err' -WindowStyle Minimized -PassThru | Select-Object -ExpandProperty Id > '%BRIDGE_PID%'"
    REM give it a moment to bind the port before we might spawn a duplicate
    timeout /t 4 /nobreak >nul
  )

  REM --- agent ---
  call :pid_alive "%AGENT_PID%"
  if errorlevel 1 (
    echo [%date% %time%] starting play_autonomous >> "%LOG%"
    REM -I isolates from the Hermes venv (which ships an ABI-mismatched numpy
    REM under cp311). sys.path.insert(0,...) adds the project dir so local
    REM imports (browser_env, agent, ...) resolve. exec() runs the script.
    powershell -NoProfile -Command "Start-Process -FilePath '%PY%' -ArgumentList '-I','-c','import sys; sys.path.insert(0, r''%REPO%python''); exec(open(r''%REPO%python\play_autonomous.py'', encoding=''utf-8'').read())' -WorkingDirectory '%REPO%python' -RedirectStandardOutput '%REPO%python\agent_run.log' -RedirectStandardError '%REPO%python\agent_run.err' -WindowStyle Minimized -PassThru | Select-Object -ExpandProperty Id > '%AGENT_PID%'"
  )

  REM check every 10s
  timeout /t 10 /nobreak >nul
goto loop
