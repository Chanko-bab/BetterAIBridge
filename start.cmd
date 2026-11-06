@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo [BAB] dependencies missing - double-click setup.cmd first
  pause
  exit /b 1
)
wscript "%~dp0launch.vbs"
