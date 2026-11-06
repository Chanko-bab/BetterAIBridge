@echo off
setlocal
chcp 65001 >nul
set HERE=%~dp0
if not exist "%HERE%logs" mkdir "%HERE%logs"
if "%BAB_ASR_PORT%"=="" set BAB_ASR_PORT=40715
if "%BAB_ASR_MODEL%"=="" set BAB_ASR_MODEL=small
if exist "%HERE%.venv\Scripts\python.exe" (
  set "PY=%HERE%.venv\Scripts\python.exe"
) else (
  set "PY=python"
)
"%PY%" "%HERE%server.py" --port %BAB_ASR_PORT% >> "%HERE%logs\asr-boot.log" 2>&1
endlocal
