@echo off
rem Removes the ProjectVault per-user Scheduled Task. No administrator rights needed.
title Uninstall ProjectVault Auto-Start
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0uninstall_service_windows.ps1"
echo.
pause
