@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo   J.A.R.V.I.S.  ^-^>  http://localhost:8080
echo.
python jarvis.py %*
if errorlevel 1 (
  echo.
  echo Python не найден. Установите Python 3.9+ с https://python.org
  pause
)
