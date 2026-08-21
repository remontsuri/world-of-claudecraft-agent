@echo off
REM start_ragent.bat — singleton launcher for the ONLINE autonomous agent.
REM Model: ONE launcher -> ONE bridge + ONE agent. The agent is a LONG-LIVED
REM process (death/respawn/heal happen IN-PROCESS). The launcher only restarts
REM the agent if it is TRULY dead (lock file gone AND /health missing for it).
REM It does NOT spawn a new agent every N seconds — that is what created 5
REM concurrent agents driving one character.

setlocal enabledelayedexpansion
set "REPO=%~dp0"
set "REPO=%REPO:~0,-1%"

set "LOG=%REPO%\ragent_launcher.log"
set "PY=C:\Users\vladc\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=D:\woc-llm\woc-llm\venv-dml\Scripts\python.exe"
if not exist "%PY%" (
  echo [%date% %time%] FATAL: no usable Python interpreter >> "%LOG%"
  exit /b 2
)
REM Clear PYTHONPATH: Hermes injects a Py3.11 venv whose numpy crashes Py3.12.
set "PYTHONPATH=%REPO%\python"

set "BRIDGE_PID=%REPO%\bridge.pid"
set "BRIDGE_LOG=%REPO%\bridge_smoke.log"
set "AGENT_LOCK=%REPO%\python\play_autonomous.lock"
set "AGENT_LOG=%REPO%\python\agent_run.log"
set "LAUNCHER_PID=%REPO%\launcher.pid"
set "MAX_LOG_SIZE=10485760"

echo launcher > "%LAUNCHER_PID%"

:loop
  call :rotate_log "%LOG%"

  REM --- bridge: start if not already running ---
  call :pid_alive "%BRIDGE_PID%"
  if errorlevel 1 (
    echo [%date% %time%] starting bridge >> "%LOG%"
    call :rotate_log "%BRIDGE_LOG%"
    start "woc-bridge" cmd /d /c ""node" "%REPO%\browser_bridge.cjs" >> "%BRIDGE_LOG%" 2^>^&1"
    ping -n 5 127.0.0.1 >nul
  )

  REM --- bridge health gate: don't launch agent until the game tab is live ---
  call :bridge_health
  if errorlevel 1 (
    echo [%date% %time%] bridge not ready (game=false) - skipping agent start >> "%LOG%"
    goto wait
  )

  REM --- agent: start ONLY if the singleton lock is absent (atomic mutex in
  REM play_autonomous guarantees no second instance even under a race). We do NOT
  REM start a new agent on a timer; only when the previous one is dead. ---
  if not exist "%AGENT_LOCK%" (
    echo [%date% %time%] starting play_autonomous >> "%LOG%"
    call :rotate_log "%AGENT_LOG%"
    start "woc-agent" /D "%REPO%\python" cmd /d /c ""%PY%" -X faulthandler -m play_autonomous >> "%AGENT_LOG%" 2>&1"
  ) else (
    REM lock exists: either a live agent holds it, or a stale one. The agent
    REM itself releases the lock on exit via atexit, so a live agent keeps it;
    REM a dead one leaves it. To avoid spawning duplicates we only act if the
    REM holder PID is verified dead AND the lock is stale. psutil check is in
    REM the agent; here we trust the lock file presence and let the agent's own
    REM mutex refuse duplicates. If the lock is stale (holder dead but file
    REM remains), the next agent start would refuse too — so we clear ONLY when
    REM we can prove the holder is gone.
    call :lock_holder_dead "%AGENT_LOCK%"
    if errorlevel 0 (
      echo [%date% %time%] stale agent lock (holder dead) - clearing >> "%LOG%"
      del /f /q "%AGENT_LOCK%" >nul 2>&1
    )
  )

:wait
  ping -n 15 127.0.0.1 >nul
goto loop

REM ---------- helpers ----------

:pid_alive
if not exist "%~1" exit /b 1
set "PID="
for /f "usebackq tokens=*" %%a in ("%~1") do set "PID=%%a"
if "%PID%"=="" exit /b 1
tasklist /FI "PID eq %PID%" 2>nul | findstr /C:%PID% >nul
if errorlevel 1 exit /b 1
exit /b 0

:bridge_health
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; try { $j=Invoke-RestMethod -Uri 'http://127.0.0.1:8791/health' -TimeoutSec 2; if($j.ok -and $j.bridge -and $j.page -and $j.game){exit 0}else{exit 1} } catch { exit 1 }" >nul 2>&1
exit /b %errorlevel%

:lock_holder_dead
if not exist "%~1" exit /b 1
set "LPID="
for /f "usebackq tokens=*" %%a in ("%~1") do set "LPID=%%a"
if "%LPID%"=="" exit /b 1
REM Conservative stale-lock check: only clear when the holder PID is absent or
REM clearly not our play_autonomous Python process. Ambiguity means KEEP lock to
REM prevent duplicate agents.
powershell -NoProfile -Command "$p=Get-CimInstance Win32_Process -Filter 'ProcessId=%LPID%' -ErrorAction SilentlyContinue; if($null -eq $p){exit 0}; if($p.Name -match '^python(\.exe)?$' -and $p.CommandLine -match 'play_autonomous'){exit 1}; exit 0" >nul 2>&1
exit /b %errorlevel%

:rotate_log
if not exist "%~1" exit /b 0
for %%A in ("%~1") do set "FSZ=%%~zA"
if !FSZ! GTR %MAX_LOG_SIZE% (
    if exist "%~1.bak" del /f /q "%~1.bak"
    rename "%~1" "%~nx1.bak"
)
exit /b 0
