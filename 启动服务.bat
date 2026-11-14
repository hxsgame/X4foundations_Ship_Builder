@echo off
cd /d "%~dp0"
echo 正在启动 EVE_Ship_Builder 服务... (Ctrl+C 停止)
python server.py
if errorlevel 1 pause
