@echo off
title J.A.R.V.I.S. SMART MODE
echo.
echo  J.A.R.V.I.S. SMART MODE - local LLM without API key
echo  Arena/session keys are NOT used or requested.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\smart-mode.ps1" -InstallDir "%~dp0."
echo.
echo  Press any key to close this window...
pause >nul
