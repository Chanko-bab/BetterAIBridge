@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist logs mkdir logs
set "PORT=%BAB_MODULE_PORT%"
if not defined PORT set "PORT=40739"
python server.py --port %PORT% >> logs\server.log 2>&1
