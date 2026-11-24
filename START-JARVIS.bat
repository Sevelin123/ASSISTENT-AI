@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions
title J.A.R.V.I.S. - LOCAL SERVER - DO NOT CLOSE
cd /d "%~dp0"

echo.
echo   ==========================================================
echo      J.A.R.V.I.S.  -  VISIBLE LOCAL SERVER
echo   ==========================================================
echo.

rem --- Optional: START-JARVIS.bat -Port 9000 ------------------------------
set "PORT=8080"
if /i "%~1"=="-Port" if not "%~2"=="" set "PORT=%~2"

rem --- Find jarvis.py: extracted archive OR installed app folder -------------
set "APPDIR=%~dp0"
if not exist "%APPDIR%jarvis.py" if exist "%APPDIR%app\jarvis.py" set "APPDIR=%APPDIR%app"
if not exist "%APPDIR%jarvis.py" (
  echo   [X] jarvis.py not found next to this BAT.
  echo       Download the full archive again:
  echo       https://codeload.github.com/Sevelin123/ASSISTENT-AI/zip/refs/heads/arena/57b8f59e-assistent-ai
  echo.
  pause
  exit /b 1
)

rem --- Find Python: py -3, then python, then python3 ------------------------
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY where python3 >nul 2>&1 && set "PY=python3"
if not defined PY (
  echo   [X] Python 3.9+ not found.
  echo       Running INSTALL_WINDOWS.bat — it installs Python automatically...
  echo.
  if exist "%~dp0INSTALL_WINDOWS.bat" (
    call "%~dp0INSTALL_WINDOWS.bat"
  ) else (
    echo       INSTALL_WINDOWS.bat not found. Download the full archive:
    echo       https://codeload.github.com/Sevelin123/ASSISTENT-AI/zip/refs/heads/arena/57b8f59e-assistent-ai
  )
  echo.
  pause
  exit /b 1
)

cd /d "%APPDIR%"

echo   Python:  %PY%
echo   Folder:  %CD%
echo   Address: http://127.0.0.1:%PORT%
echo   Default: http://127.0.0.1:8080
echo.
echo   IMPORTANT: leave THIS WINDOW OPEN while using J.A.R.V.I.S.
echo   Closing it stops the server and Chrome will show ERR_CONNECTION_REFUSED again.
echo.
echo   Browser will open in 5 seconds. If it opens too early, press F5.
echo   ------------------------------------------------------------------
echo.

start "" /min cmd /c "timeout /t 5 /nobreak >nul & start http://127.0.0.1:%PORT%"

%PY% jarvis.py --host 127.0.0.1 --port %PORT%
set "RC=%ERRORLEVEL%"

echo.
echo   ------------------------------------------------------------------
echo   Server stopped. Exit code: %RC%
echo.
if not "%RC%"=="0" (
  echo   Read the error above. Quick fixes:
  echo     - Python missing?  Run INSTALL_WINDOWS.bat
  echo     - Port busy?       START-JARVIS.bat -Port 9000  then open 127.0.0.1:9000
  echo     - Logs:            logs\server.err.log and logs\server.out.log
) else (
  echo   You closed the server on purpose. Run this BAT again to start it.
)
echo.
pause
exit /b %RC%
