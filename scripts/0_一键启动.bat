@echo off
cd /d "%~dp0..\backend"
echo ============================================
echo   宠物影像识别与荐购系统 一键启动（后端 + 网页）
echo ============================================
echo.
echo [0/3] 先让开 8000 端口（防 Docker 容器抢占）...
docker stop petvision-backend petvision-frontend >nul 2>&1
echo       完成（没开 Docker 的话这步自动跳过）
echo.
echo [1/3] 启动后端服务（端口 8000）...
start "宠物影像识别与荐购系统后端" .venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
timeout /t 5 /nobreak >nul

echo [2/3] 启动网页服务（端口 5199）...
start "宠物影像识别与荐购系统网页" .venv\Scripts\python.exe serve_gui.py
timeout /t 3 /nobreak >nul

echo [3/3] 打开浏览器 http://127.0.0.1:5199 ...
start "" http://127.0.0.1:5199
echo.
echo 两个服务已在各自的窗口里运行，关掉那些黑窗口即停止服务。
echo 本窗口可以关掉，不影响服务。
pause >nul
