@echo off
chcp 936 >nul
cd /d "%~dp0"
echo ============================================
echo   宠物影像识别与荐购系统（Docker 版）
echo ============================================
echo.
docker info >nul 2>&1
if errorlevel 1 (
  echo  [错误] Docker 没在运行。
  echo  请先打开 Docker Desktop，等它的图标变成绿色，再双击本文件。
  echo.
  pause
  exit /b 1
)
echo [1/2] 构建并启动后端 + 前端（改过代码时会重新打包，约需 1-2 分钟）...
echo.
docker compose up -d --build
echo.
echo [2/2] 等 10 秒后自动打开浏览器...
timeout /t 10 /nobreak >nul
start "" http://127.0.0.1:8080
echo.
echo ============================================
echo   网址: http://127.0.0.1:8080
echo   停止: 在本文件夹执行  docker compose down
echo ============================================
echo.
pause >nul
