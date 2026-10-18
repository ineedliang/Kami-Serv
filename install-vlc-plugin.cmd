@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-vlc-plugin.ps1"
if errorlevel 1 echo Installation did not finish. Read the message above.
pause
