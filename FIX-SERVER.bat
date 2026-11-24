@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions
title J.A.R.V.I.S. - FIX SERVER CONNECTION
cd /d "%~dp0"

echo.
echo   ==========================================================
echo      J.A.R.V.I.S.  -  FIX "CANNOT CONNECT TO SERVER"
echo   ==========================================================
echo.

rem --- Find the diagnostic PowerShell script ------------------------------
set "PS1=%~dp0windows\fix-server.ps1"
if not exist "%PS1%" set "PS1=%~dp0app\windows\fix-server.ps1"
if not exist "%PS1%" set "PS1=%LOCALAPPDATA%\JARVIS\windows\fix-server.ps1"
if not exist "%PS1%" set "PS1=%LOCALAPPDATA%\JARVIS\app\windows\fix-server.ps1"

if not exist "%PS1%" (
  echo   [X] windows\fix-server.ps1 not found.
  echo       Download the full archive again:
  echo       https://codeload.github.com/Sevelin123/ASSISTENT-AI/zip/refs/heads/arena/57b8f59e-assistent-ai
  echo.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" -InstallDir "%~dp0." %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo   [OK] Server is reachable. Browser should open http://127.0.0.1:8080
) else (
  echo   [X] Still no connection. Read the messages above and the logs folder.
  echo       Visible mode:  START-JARVIS.bat   (leave the console window OPEN)
  echo       Quick check:   open EXACTLY http://127.0.0.1:8080
  echo       Another port:  START-JARVIS.bat -Port 9000 / FIX-SERVER.bat -Port 9000
  echo       Proxy:         disable proxy for 127.0.0.1;localhost or chrome.exe --no-proxy-server
  echo       Reinstall:     INSTALL_WINDOWS.bat
)
echo.
pause
exit /b %RC%
