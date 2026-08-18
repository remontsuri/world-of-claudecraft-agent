@echo off
set SRC=D:\world-of-claudecraft
set DST=D:\woc_archive
if not exist %DST%\python mkdir %DST%\python
if not exist %DST%\bridge mkdir %DST%\bridge
copy /Y %SRC%\browser_bridge.cjs %DST%\bridge\
copy /Y %SRC%\readiness_zond.cjs %DST%\bridge\
copy /Y %SRC%\run_bridge.bat %DST%\bridge\
copy /Y %SRC%\run_agent.bat %DST%\bridge\
for %%f in (%SRC%\python\*.py) do copy /Y "%%f" %DST%\python\
echo ARCHIVE_READY
dir /b %DST%\python
echo ---
dir /b %DST%\bridge
