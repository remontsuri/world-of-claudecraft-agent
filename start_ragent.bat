@echo off
REM start_ragent.bat — singleton launcher for the ONLINE autonomous agent.
REM Runs OUTSIDE any MSYS/bash shell (double-click, or `cmd /c start_ragent.bat`).
REM
REM SINGLETON: keeps exactly ONE launcher + ONE bridge + ONE agent alive.
REM Each child writes its OWN live pid to a .pid file; the launcher tracks the
REM real long-lived process (not a transient wrapper). On each loop we check the
REM recorded PID is still alive; if not, we restart that one process only.
REM
REM NOTE: no `git pull` here. The agent must run the COMMITTED version of the
REM code; pulling mid-run would silently swap the revision under a long self-play
REM experiment and corrupt it. Update + restart deliberately.

setlocal enabledelayedexpansion
REM REPO = directory this .bat lives in (no hard-coded path), WITHOUT trailing
REM backslash so it can be passed inside a quoted Python argv safely (a trailing
REM '\' would escape the closing quote in cmd).
set "REPO=%~dp0"
set "REPO=%REPO:~0,-1%"
set "PY=%REPO%.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=D:\woc-llm\therock-test\Scripts\python.exe"

set "LOG=%REPO%ragent_launcher.log"
set "BRIDGE_PID=%REPO%bridge.pid"
set "BRIDGE_LOG=%REPO%bridge_smoke.log"
set "AGENT_PID=%REPO%python\play_autonomous.lock"
set "AGENT_LOG=%REPO%python\agent_run.log"
set "LAUNCHER_PID=%REPO%launcher.pid"

REM Max log size in bytes (10485760 = 10 MB) before rotation.
set "MAX_LOG_SIZE=10485760"

REM --- launcher self-lock: only ONE start_ragent.bat may run at a time ---
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
for /f "tokens=2" %%P in ('tasklist /FI "IMAGENAME eq cmd.exe" /NH 2^>nul ^| findstr /I "start_ragent"') do (
    REM best-effort: write our own pid; if unresolved, placeholder stays
)

call :rotate_log "%LOG%"
echo [%date% %time%] launcher start >> "%LOG%"

REM Skip the subroutines on first pass (they are only entered via `call`).
goto loop

REM Is a PID still alive? Sets errorlevel 0 if alive, 1 if dead/missing.
:pid_alive
if not exist "%~1" exit /b 1
set "PID="
for /f "usebackq tokens=*" %%a in ("%~1") do set "PID=%%a"
if "%PID%"=="" exit /b 1
REM regex word-boundary match; robust to tasklist column padding in any locale.
tasklist /FI "PID eq %PID%" 2>nul | findstr /R /C:"\<%PID%\>" >nul
if errorlevel 1 exit /b 1
exit /b 0

REM Is the bridge HTTP endpoint answering on :8791?
:bridge_health
set "BH="
for /f "tokens=*" %%R in ('powershell -NoProfile -Command "try{(Invoke-WebRequest -Uri http://127.0.0.1:8791/ -Method HEAD -TimeoutSec 2 -UseBasicParsing).StatusCode}catch{exit 1}" 2^>nul') do set "BH=%%R"
if "%BH%"=="200" exit /b 0
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

:loop
  call :rotate_log "%LOG%"

  REM --- bridge ---
  REM node -e writes the LIVE wrapper pid to bridge.pid, then spawns the real
  REM bridge with inherited stdio and exits only when the bridge exits. So
  REM bridge.pid tracks a process that is alive exactly as long as the bridge.
  call :pid_alive "%BRIDGE_PID%"
  if errorlevel 1 (
    echo [%date% %time%] starting bridge >> "%LOG%"
    call :rotate_log "%BRIDGE_LOG%"
    start "woc-bridge" /min cmd /c cd /d %REPO% ^&^& node -e "const fs=require('fs');fs.writeFileSync('bridge.pid',String(process.pid));const cp=require('child_process');const c=cp.spawn('node',['browser_bridge.cjs'],{stdio:'inherit'});c.on('exit',()=>process.exit(c.exitCode===null?1:c.exitCode));" >> "%BRIDGE_LOG%" 2^>^&1
    REM give it a moment to bind the port before we might spawn a duplicate
    timeout /t 4 /nobreak >nul
  )

  REM --- agent (only AFTER the bridge is actually serving) ---
  call :bridge_health
  if errorlevel 1 (
    echo [%date% %time%] bridge not ready yet - skipping agent start >> "%LOG%"
    goto wait
  )
  call :pid_alive "%AGENT_PID%"
  if errorlevel 1 (
    echo [%date% %time%] starting play_autonomous >> "%LOG%"
    call :rotate_log "%AGENT_LOG%"
    REM Run as a MODULE (-m play_autonomous) so __file__ and __name__ are real.
    REM The old `exec(open(...).read())` form left __file__ undefined -> NameError
    REM at import (line 36) -> agent died before main() with an empty log.
    REM PYTHONPATH points at the python/ dir so `import browser_env` etc. resolve.
    REM agent.pid is written by play_autonomous.main() itself.
    start "woc-agent" /min cmd /c cd /d %REPO%python ^&^& set "PYTHONPATH=%REPO%\python" ^&^& "%PY%" -m play_autonomous >> "%AGENT_LOG%" 2^>^&1
  )

  REM check every 10s
  :wait
  timeout /t 10 /nobreak >nul
goto loop
