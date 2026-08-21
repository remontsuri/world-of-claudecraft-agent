@echo off
REM start_agent_visible.bat - launch the ONE long-lived agent in a VISIBLE window.
REM Must clear PYTHONPATH: Hermes terminal injects its own venv path which breaks
REM numpy (cp311 .pyd loaded into cp312). Clearing it lets system Python 3.12 use
REM its own site-packages. -u = unbuffered stdout so the window shows live steps.
setlocal
set "PYTHONPATH="
cd /d "D:\world-of-claudecraft\python"
start "woc-agent" "C:\Users\vladc\AppData\Local\Programs\Python\Python312\python.exe" -u -X faulthandler -m play_autonomous >> "D:\world-of-claudecraft\agent_console.log" 2>&1
endlocal
