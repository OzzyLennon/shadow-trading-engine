@echo off
REM 收盘汇报启动脚本

echo ========================================
echo   发送收盘汇报...
echo ========================================
echo.

cd /d "%~dp0"
python daily_report.py

echo.
echo [完成] 收盘汇报已发送
pause
