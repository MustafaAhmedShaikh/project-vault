@echo off
rem Installs the ProjectVault daemon as a per-user Scheduled Task. No administrator rights needed.
title Install ProjectVault Auto-Start
echo Installing ProjectVault auto-start (current user, runs at logon)...
echo.
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0install_service_windows.ps1"
echo.
pause
