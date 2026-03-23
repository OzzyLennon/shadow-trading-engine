@echo off
REM APEX Dashboard 启动脚本
REM 在浏览器中打开 http://localhost:8501

echo ========================================
echo   启动 APEX Dashboard...
echo ========================================
echo.

cd /d "%~dp0"
streamlit run dashboard.py --server.port 8501

pause
