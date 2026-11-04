@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Run: powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1
  pause
  exit /b 1
)
start "ZAOWU" ".venv\Scripts\pythonw.exe" "launch.py"
