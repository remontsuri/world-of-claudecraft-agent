@echo off
powershell -NoProfile -Command "Compress-Archive -Path D:\woc_archive\* -DestinationPath D:\woc_archive.zip -Force"
echo ZIP_DONE
powershell -NoProfile -Command "(Get-Item D:\woc_archive.zip).Length"
