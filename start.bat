@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions
cd /d "%~dp0"
echo.
echo   J.A.R.V.I.S.  ^-^>  http://localhost:8080
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
