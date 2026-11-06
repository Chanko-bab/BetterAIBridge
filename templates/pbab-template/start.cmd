@echo off
setlocal
cd /d "%~dp0"
if not exist "logs" mkdir "logs"
set "PORT=%BAB_MODULE_PORT%"
if not defined PORT set "PORT=__PORT__"
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  echo [%DATE% %TIME%] python not found >> "logs\server.log"
  exit /b 1
)
echo [%DATE% %TIME%] starting with %PY% on port %PORT% >> "logs\server.log"
%PY% server.py --port %PORT% >> "logs\server.log" 2>&1
