@echo off
REM Обёртка для Windows: hermes зовёт .cmd, внутри тот же bash-хук (единый контракт).
REM Требуется bash (Git for Windows). Если его нет — хук не блокирует работу,
REM а честно сообщает, что предохранитель не активен (правила всё равно в AGENTS.md).
setlocal
set "HOOK_DIR=%~dp0.."
where bash >nul 2>nul
if errorlevel 1 (
  echo {"continue": true, "message": "bash не найден: предохранитель guard не активен. Поставь Git for Windows или запускай хук вручную: bash hermes/hooks/guard.sh"}
  exit /b 0
)
bash "%HOOK_DIR%\guard.sh"
exit /b %errorlevel%
