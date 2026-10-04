@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0publish.ps1" %*
if errorlevel 1 (
  echo Publication stopped. Review the message above; local data is untouched.
  pause
  exit /b 1
)
pause
