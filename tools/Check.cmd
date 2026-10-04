@echo off
setlocal
if not exist "%~dp0..\.venv\Scripts\python.exe" call "%~dp0..\Setup.cmd"
if errorlevel 1 exit /b 1
"%~dp0..\.venv\Scripts\python.exe" "%~dp0doctor.py"
