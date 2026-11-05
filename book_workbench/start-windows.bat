@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
 echo Please run scripts\setup-windows.ps1 first.
 pause
 exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0launch.py"
