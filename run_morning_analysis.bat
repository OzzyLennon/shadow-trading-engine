@echo off
REM AI 晨间研判启动脚本
REM 运行 AI Sentinel (风控) 和 AI Brain (策略部署)

echo ========================================
echo   AI 晨间研判系统
echo ========================================
echo.

cd /d "%~dp0"

echo [1] 运行 AI Sentinel (风控研判)...
python ai_sentinel.py
echo.

echo [2] 运行 AI Brain (策略部署)...
python ai_brain.py
echo.

echo ========================================
echo   晨间研判完成！
echo ========================================
echo.

pause
