@echo off
cd /d "%~dp0"
where node >nul 2>nul
if errorlevel 1 (
  echo 未找到 Node.js。请先安装 Node.js 20 或更新版本，然后重新双击本文件。
  pause
  exit /b 1
)
if not exist node_modules (
  echo 首次启动，正在安装依赖。这可能需要几分钟...
  call npm install --no-audit --no-fund
  if errorlevel 1 (
    echo 安装失败。请保留此窗口中的错误信息。
    pause
    exit /b 1
  )
)
echo 正在启动外贸开发信小助手...
start "外贸开发信小助手" cmd /k npm start
timeout /t 3 >nul
start "" "http://localhost:48173"
echo 服务运行在新打开的窗口中；关闭该窗口会停止服务。
