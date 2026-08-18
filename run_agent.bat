@echo off
cd /d D:\world-of-claudecraft\python
set AUTONOMOUS_STEPS=300
set SAVE_EVERY=100
set AUTONOMOUS_WINDOW=100
..\.venv\Scripts\python.exe play_autonomous.py > ..\autorun.log 2>&1
