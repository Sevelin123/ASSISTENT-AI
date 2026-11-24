@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions
cd /d "%~dp0"
echo.
echo   J.A.R.V.I.S.  ^-^>  http://127.0.0.1:8080
echo.
echo   IMPORTANT: open 127.0.0.1, NOT localhost and NOT file://web/index.html.
echo   If the browser says "cannot connect to server", run FIX-SERVER.bat.
echo.
echo   TIP: for a full automatic Windows setup (Python, autostart, tray, shortcuts),
echo        run INSTALL_WINDOWS.bat instead of this file.
echo.
python jarvis.py %*
if errorlevel 1 (
  echo.
  echo   Python not found. Install Python 3.9+ from https://python.org
  echo   or just run INSTALL_WINDOWS.bat - it installs Python automatically.
  pause
)
