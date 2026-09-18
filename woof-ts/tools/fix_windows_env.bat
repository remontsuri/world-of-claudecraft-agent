@echo off
rem Обёртка для cmd: одна команда вместо ручных правок окружения линии woof-ts.
rem Лечение и причина описаны в knowledge/pitfalls.md (2026-09-18, "дерево игры
rem и резолвер расширений") и в шапке fix_windows_env.ps1.
rem
rem Использование (из каталога woof-ts):
rem   tools\fix_windows_env.bat
rem   tools\fix_windows_env.bat -GameDir D:\woc-game -CleanInPlace
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fix_windows_env.ps1" %*
exit /b %ERRORLEVEL%
