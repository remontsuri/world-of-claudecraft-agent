@echo off
REM start_ragent.bat — stable launcher for the autonomous self-playing agent.
REM Runs OUTSIDE any MSYS/bash shell (double-click, or `cmd /c start start_ragent.bat`).
REM Keeps the bridge + agent alive: if either dies, it is restarted. The agent
REM itself also waits for bridge recovery on ENV_ERROR, so this is belt-and-braces.

setlocal
set REPO=D:\world-of-claudecraft
set PY=D:\woc-llm\therock-test\Scripts\python.exe
set LOG=%REPO%\ragent_launcher.log

echo [%date% %time%] launcher start >> %LOG%

:loop
  REM --- bridge ---
  tasklist /FI "IMAGENAME eq node.exe" /FO CSV | findstr /I "browser_bridge.cjs" >nul
  if errorlevel 1 (
    echo [%date% %time%] starting bridge >> %LOG%
    start "woc-bridge" /min cmd /c "cd /d %REPO% && node browser_bridge.cjs >> %REPO%\bridge_smoke.log 2>&1"
    timeout /t 3 /nobreak >nul
  )

  REM --- agent ---
  tasklist /FI "IMAGENAME eq python.exe" /FO CSV | findstr /I "agent.py" >nul
  if errorlevel 1 (
    echo [%date% %time%] starting agent >> %LOG%
    start "woc-agent" /min cmd /c "cd /d %REPO%\python && set PYTHONPATH= && %PY% agent.py >> %REPO%\python\agent_run.log 2>&1"
  )

  REM check every 15s
  timeout /t 15 /nobreak >nul
goto loop
