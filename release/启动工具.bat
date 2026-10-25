@echo off
setlocal
cd /d "%~dp0"
title X4foundations Ship Builder
set PORT=8765

rem ===== 已在运行则直接打开浏览器 =====
powershell -NoProfile -Command "try{$c=New-Object Net.Sockets.TcpClient;$c.Connect('127.0.0.1',%PORT%);$c.Close();exit 0}catch{exit 1}"
if %errorlevel%==0 (
  start "" http://127.0.0.1:%PORT%/
  exit /b
)

rem ===== 查找 Python：优先 py 启动器 =====
set PY=
py -3 --version >nul 2>nul && set PY=py -3
if not defined PY (
  python --version >nul 2>nul && set PY=python
)
if not defined PY (
  echo.
  echo [错误] 未检测到 Python。
  echo 请先安装 Python 3.9 或更高版本： https://www.python.org/downloads/
  echo 安装时务必勾选 "Add Python to PATH"。
  echo.
  pause
  exit /b 1
)

echo 正在启动本地服务（端口 %PORT%）…
start "" /b %PY% server.py

rem ===== 等待端口真正开始监听（最多 60 秒）=====
powershell -NoProfile -Command "$n=120; while($n -gt 0){ try{$c=New-Object Net.Sockets.TcpClient;$c.Connect('127.0.0.1',%PORT%);$c.Close();exit 0}catch{Start-Sleep -Milliseconds 500;$n--} }; exit 1"
if errorlevel 1 (
  echo.
  echo [错误] 服务启动超时。可能原因：端口 %PORT% 被占用，或 Python 依赖缺失。
  echo 若端口被占用，请关闭占用程序后重试。
  echo.
  pause
  exit /b 1
)

start "" http://127.0.0.1:%PORT%/
echo.
echo 工具已启动： http://127.0.0.1:%PORT%/
echo 关闭本窗口即停止服务。
echo.
pause >nul
