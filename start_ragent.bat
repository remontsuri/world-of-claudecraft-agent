@echo off
REM start_ragent.bat — singleton launcher for the ONLINE autonomous agent.
REM Double-click, or `cmd /c start_ragent.bat`. Runs OUTSIDE any MSYS/bash shell.
REM
REM Keeps exactly ONE launcher + ONE bridge + ONE agent alive. Each child writes
REM its own live pid to a .pid file; the launcher tracks the real long-lived
REM process and restarts only the dead one.
REM
REM CRASH VISIBILITY: any agent/bridge crash is written in FULL to a log file
REM (agent_crash.log / bridge_crash.txt) AND summarized into ragent_launcher.log
REM with the exit code, so a silent death is never lost in the /min window.

setlocal enabledelayedexpansion
REM REPO = directory this .bat lives in (no hard-coded path), no trailing backslash.
set "REPO=%~dp0"
set "REPO=%REPO:~0,-1%"

set "PY=%REPO%.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=D:\woc-llm\therock-test\Scripts\python.exe"

set "LOG=%REPO%ragent_launcher.log"
set "BRIDGE_PID=%REPO%bridge.pid"
set "BRIDGE_LOG=%REPO%bridge_smoke.log"
set "AGENT_PID=%REPO%python\play_autonomous.lock"
set "AGENT_LOG=%REPO%python\agent_run.log"
set "AGENT_CRASH=%REPO%python\agent_crash.log"
set "LAUNCHER_PID=%REPO%launcher.pid"

REM Max log size in bytes (10 MB) before rotation.
set "MAX_LOG_SIZE=10485760"

REM --- launcher self-lock: only ONE start_ragent.bat at a time ---
if exist "%LAUNCHER_PID%" (
    set "LPID="
    for /f "usebackq tokens=*" %%a in ("%LAUNCHER_PID%") do set "LPID=%%a"
    if defined LPID (
        tasklist /FI "PID eq !LPID!" 2>nul | findstr /R /C:"\<!LPID!\>" >nul
        if not errorlevel 1 (
            echo [%date% %time%] launcher already running (pid !LPID!) - exiting >> "%LOG%"
            exit /b 0
        )
    )
)
echo %%~ exists > "%LAUNCHER_PID%"
for /f "tokens=2" %%P in ('tasklist /FI "IMAGENAME eq cmd.exe" /NH 2^>nul ^| findstr /I "start_ragent"') do (
    REM best-effort: leave our own pid recorded above
)

call :rotate_log "%LOG%"
echo [%date% %time%] launcher start >> "%LOG%"

goto loop

REM Is a PID still alive? errorlevel 0 = alive, 1 = dead/missing.
:pid_alive
if not exist "%~1" exit /b 1
set "PID="
for /f "usebackq tokens=*" %%a in ("%~1") do set "PID=%%a"
if "%PID%"=="" exit /b 1
tasklist /FI "PID eq %PID%" 2>nul | findstr /R /C:"\<%PID%\>" >nul
if errorlevel 1 exit /b 1
exit /b 0

REM Is the bridge HTTP endpoint answering on :8791 AND driving a live game?
REM Honest health: GET /health must return game:true (window.__game present).
:bridge_health
set "BH="
for /f "tokens=*" %%R in ('powershell -NoProfile -Command "try{(Invoke-WebRequest -Uri http://127.0.0.1:8791/health -TimeoutSec 2 -UseBasicParsing).Content}catch{exit 1}" 2^>nul') do set "BH=%%R"
echo %BH% | findstr /C "\"game\":true" >nul
if not errorlevel 1 exit /b 0
exit /b 1

REM Rotate a log if it exceeds MAX_LOG_SIZE (keep a single .bak).
:rotate_log
if not exist "%~1" exit /b 0
for %%A in ("%~1") do set "FSZ=%%~zA"
if !FSZ! GTR %MAX_LOG_SIZE% (
    if exist "%~1.bak" del /f /q "%~1.bak"
    rename "%~1" "%~nx1.bak"
)
exit /b 0

REM Append last N lines of a file to the launcher log (crash context).
:tail_to_log
set "SRC=%~1"
set "N=%~2"
if not exist "%SRC%" exit /b 0
echo --- last %N% lines of %SRC% --- >> "%LOG%"
powershell -NoProfile -Command "try{(Get-Content '%SRC%' -Tail %N%) -join \"`n\"}catch{}" >> "%LOG%"
exit /b 0

:loop
  call :rotate_log "%LOG%"

  REM --- bridge ---
  call :pid_alive "%BRIDGE_PID%"
  if errorlevel 1 (
    echo [%date% %time%] starting bridge >> "%LOG%"
    call :rotate_log "%BRIDGE_LOG%"
    start "woc-bridge" /min cmd /c cd /d %REPO% ^&^& node -e "const fs=require('fs');fs.writeFileSync('bridge.pid',String(process.pid));const cp=require('child_process');const c=cp.spawn('node',['browser_bridge.cjs'],{stdio:'inherit'});c.on('exit',(code)=>{try{require('fs').appendFileSync('bridge_crash.txt','\n=== BRIDGE EXIT code='+code+' '+new Date().toISOString()+'\n');}catch(e){}process.exit(code===null?1:code)});" >> "%BRIDGE_LOG%" 2^>^&1
    REM give it a moment to bind the port before we might spawn a duplicate
    timeout /t 4 /nobreak >nul
  )

  REM --- agent (only AFTER the bridge is actually serving a live game) ---
  call :bridge_health
  if errorlevel 1 (
    echo [%date% %time%] bridge not ready yet - skipping agent start >> "%LOG%"
    goto wait
  )
  call :pid_alive "%AGENT_PID%"
  if errorlevel 1 (
    echo [%date% %time%] starting play_autonomous >> "%LOG%"
    call :rotate_log "%AGENT_LOG%"
    REM Run as a MODULE (-m play_autonomous) so __file__/__name__ are real.
    REM PYTHONPATH points at python/ so `import browser_env` etc. resolve.
    REM -X faulthandler + PYTHONFAULTHANDLER=1 dump a traceback on hard hangs.
    REM agent.pid is written by play_autonomous.main() itself.
    set "PYTHONFAULTHANDLER=1"
    start "woc-agent" /min cmd /c cd /d %REPO%python ^&^& set "PYTHONPATH=%REPO%\python" ^&^& "%PY%" -X faulthandler -m play_autonomous >> "%AGENT_LOG%" 2^>^&1
  )

  REM check every 10s
  :wait
  timeout /t 10 /nobreak >nul
  REM detect agent death between loops and record the crash context
  call :pid_alive "%AGENT_PID%"
  if errorlevel 1 (
    if exist "%AGENT_CRASH%" (
      echo [%date% %time%] AGENT CRASHED - see %AGENT_CRASH% >> "%LOG%"
      call :tail_to_log "%AGENT_CRASH%" 40
    ) else (
      echo [%date% %time%] AGENT EXITED (no crash log) - see %AGENT_LOG% >> "%LOG%"
      call :tail_to_log "%AGENT_LOG%" 20
    )
  )
  call :pid_alive "%BRIDGE_PID%"
  if errorlevel 1 (
    echo [%date% %time%] BRIDGE CRASHED - see bridge_crash.txt >> "%LOG%"
    call :tail_to_log "bridge_crash.txt" 20
  )
goto loop
