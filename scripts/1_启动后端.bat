@echo off
cd /d "%~dp0..\backend"
echo ============================================
echo   宠物影像识别与荐购系统 后端启动中，请不要关闭本窗口
echo ============================================
echo.
.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
echo.
echo 后端已停止。按任意键关闭。
pause >nul
