@echo off
REM start_ragent.bat — stable launcher for the ONLINE autonomous self-playing agent.
REM Runs OUTSIDE any MSYS/bash shell (double-click, or `cmd /c start start_ragent.bat`).
REM
REM Runtime graph (correct entrypoint):
REM   start_ragent.bat -> browser_bridge.cjs -> Chrome/live WoC
REM                      -> BrowserEnv -> play_autonomous.py -> Agent -> Policy/Memory/Reward
REM NOT agent.py (that one drives HierarchicalWoWEnv = headless Sim, wrong graph).
REM
REM Keeps the bridge + play_autonomous alive: if either dies, it is restarted.
REM Process identity is checked via WMIC command-line match (reliable), not tasklist|findstr.

setlocal
set REPO=D:\world-of-claudecraft
set PY=D:\woc-llm\therock-test\Scripts\python.exe
set LOG=%REPO%\ragent_launcher.log

echo [%date% %time%] launcher start >> %LOG%

:loop
  REM --- bridge: alive if any node.exe has browser_bridge.cjs in its command line ---
  wmic process where "name='node.exe'" get CommandLine /FORMAT:CSV 2>nul | findstr /I "browser_bridge.cjs" >nul
  if errorlevel 1 (
    echo [%date% %time%] starting bridge >> %LOG%
    start "woc-bridge" /min cmd /c "cd /d %REPO% && node browser_bridge.cjs >> %REPO%\bridge_smoke.log 2>&1"
    timeout /t 3 /nobreak >nul
  )

  REM --- agent: alive if any python.exe has play_autonomous.py in its command line ---
  wmic process where "name='python.exe'" get CommandLine /FORMAT:CSV 2>nul | findstr /I "play_autonomous.py" >nul
  if errorlevel 1 (
    echo [%date% %time%] starting play_autonomous >> %LOG%
    start "woc-agent" /min cmd /c "cd /d %REPO%\python && set PYTHONPATH= && %PY% play_autonomous.py >> %REPO%\python\agent_run.log 2>&1"
  )

  REM check every 15s
  timeout /t 15 /nobreak >nul
goto loop
