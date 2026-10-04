@echo off
setlocal
if exist "%~dp0LMU-StintLab.exe" (
  start "" "%~dp0LMU-StintLab.exe" %*
  exit /b 0
)
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
  call "%~dp0Setup.cmd"
  if errorlevel 1 exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0src\inputscope.py" %*
