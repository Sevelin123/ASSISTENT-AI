@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions
title J.A.R.V.I.S. - Uninstall
cd /d "%~dp0"

echo.
echo   ==========================================================
echo      J.A.R.V.I.S.  -  UNINSTALL
echo   ==========================================================
echo.
echo   This stops the services and removes shortcuts / autostart.
echo   Your notes, tasks and settings are KEPT unless you add -Purge.
echo.

set "SETUP=%~dp0windows\setup.ps1"
if not exist "%SETUP%" set "SETUP=%~dp0..\windows\setup.ps1"
if not exist "%SETUP%" set "SETUP=%~dp0setup.ps1"
if not exist "%SETUP%" set "SETUP=%LOCALAPPDATA%\JARVIS\app\windows\setup.ps1"

if not exist "%SETUP%" (
    echo   [X] setup.ps1 not found. Nothing to do.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SETUP%" -Uninstall %*
if errorlevel 1 (
    echo   [X] Uninstall finished with warnings.
    pause
    exit /b 1
)
exit /b 0
