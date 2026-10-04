@echo off
setlocal
call "%~dp0Setup.cmd" -BuildTools
if errorlevel 1 exit /b 1
"%~dp0.venv\Scripts\python.exe" "%~dp0build.py"
if errorlevel 1 (
  pause
  exit /b 1
)
echo Release ZIP created in dist.
