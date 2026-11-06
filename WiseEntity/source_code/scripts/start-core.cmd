@echo off
chcp 65001 >nul
cd /d "%~dp0..\..\entity"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
set PYTHONPATH=%~dp0..\..\entity
set BAB_PORT=40740
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m uvicorn core.app:app --host 127.0.0.1 --port %BAB_PORT% >> "%~dp0..\..\runtime\logs\core.log" 2>&1
) else (
  echo [BAB] core venv missing, run setup.cmd first
  exit /b 1
)
