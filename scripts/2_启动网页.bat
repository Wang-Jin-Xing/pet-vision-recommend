@echo off
cd /d "%~dp0..\backend"
echo ============================================
echo   宠物影像识别与荐购系统 网页启动中，请不要关闭本窗口
echo   启动后浏览器打开: http://127.0.0.1:5199
echo ============================================
echo.
.venv\Scripts\python.exe serve_gui.py
echo.
echo 网页服务已停止。按任意键关闭。
pause >nul
