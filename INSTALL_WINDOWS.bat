@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions
title J.A.R.V.I.S. - Windows Setup
cd /d "%~dp0"

echo.
echo   ==========================================================
echo      J.A.R.V.I.S.  -  AUTOMATIC WINDOWS INSTALLER
echo   ==========================================================
echo.

rem --- Find the PowerShell installer next to this file --------------------
set "SETUP=%~dp0windows\setup.ps1"
if not exist "%SETUP%" set "SETUP=%~dp0..\windows\setup.ps1"
if not exist "%SETUP%" set "SETUP=%~dp0setup.ps1"
if not exist "%SETUP%" set "SETUP=%LOCALAPPDATA%\JARVIS\app\windows\setup.ps1"
if exist "%SETUP%" goto RUN

rem --- Standalone mode: this .bat was downloaded alone -------------------
echo   setup.ps1 not found locally. Downloading J.A.R.V.I.S. from GitHub...
echo   (Please wait, this can take a minute.)
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $z=Join-Path $env:TEMP 'jarvis-src.zip'; $d=Join-Path $env:TEMP 'jarvis-src'; $b='arena/57b8f59e-assistent-ai'; $u='https://codeload.github.com/Sevelin123/ASSISTENT-AI/zip/refs/heads/'+$b; try { $bs=Invoke-RestMethod -Uri 'https://api.github.com/repos/Sevelin123/ASSISTENT-AI/branches?per_page=100' -Headers @{'User-Agent'='JARVIS-Setup'} -TimeoutSec 20; $a=$bs | Where-Object { $_.name -eq $b } | Select-Object -First 1; if($a -and $a.commit.sha){$u='https://codeload.github.com/Sevelin123/ASSISTENT-AI/zip/'+$a.commit.sha} } catch {}; Write-Host ('  Branch: '+$b); Invoke-WebRequest -UseBasicParsing $u -OutFile $z -TimeoutSec 180; if(Test-Path $d){Remove-Item $d -Recurse -Force}; Expand-Archive $z $d -Force; $s=Get-ChildItem $d -Recurse -Filter setup.ps1 | Select-Object -First 1 -ExpandProperty FullName; if(-not $s){throw 'setup.ps1 not found in downloaded archive'}; & $s %*"
if errorlevel 1 goto FAIL
goto END

:RUN
powershell -NoProfile -ExecutionPolicy Bypass -File "%SETUP%" %*
if errorlevel 1 goto FAIL
goto END

:FAIL
echo.
echo   [X] Installation failed. See %LOCALAPPDATA%\JARVIS\install.log
echo       If the HUD says "cannot connect to server": run FIX-SERVER.bat from the archive.
echo       Open EXACTLY http://127.0.0.1:8080 (not localhost, not *.e2b.app).
echo       Offline archive: codeload.github.com/Sevelin123/ASSISTENT-AI/zip/refs/heads/arena/57b8f59e-assistent-ai
echo.
pause
exit /b 1

:END
exit /b 0
