@echo off
setlocal
if exist "%~dp0LMU-StintLab.exe" (
  start "" /wait "%~dp0LMU-StintLab.exe" --doctor --doctor-output "%TEMP%\LMU-StintLab-doctor.json"
  if errorlevel 1 exit /b 1
  type "%TEMP%\LMU-StintLab-doctor.json"
  pause
  exit /b 0
)
if not exist "%~dp0.venv\Scripts\python.exe" call "%~dp0Setup.cmd"
if errorlevel 1 exit /b 1
"%~dp0.venv\Scripts\python.exe" "%~dp0src\inputscope.py" --doctor
