@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\publish-to-github.ps1"
if errorlevel 1 echo Upload did not finish. Read the message above before retrying.
pause
