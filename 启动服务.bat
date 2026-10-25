@echo off
cd /d "C:\Users\15536\Doubao\chats\2026-10-03\new-chat-1\EVE_Ship_Builder"
echo 正在启动 EVE_Ship_Builder 服务... (Ctrl+C 停止)
python server.py
if errorlevel 1 pause
