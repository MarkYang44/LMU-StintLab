@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup.ps1" %*
if errorlevel 1 (
  echo Setup failed. Read the error above and try again.
  pause
  exit /b 1
)
exit /b 0
