@echo off
REM APEX 量化交易系统停止脚本
REM Windows版本

echo ========================================
echo   停止所有交易引擎...
echo ========================================
echo.

taskkill /f /fi "WINDOWTITLE eq Red Engine*" 2>nul
taskkill /f /fi "WINDOWTITLE eq Blue Engine*" 2>nul
taskkill /f /fi "WINDOWTITLE eq Alpha Factory*" 2>nul

REM 也尝试按进程名结束
taskkill /f /im python.exe /fi "WINDOWTITLE eq apex*" 2>nul

echo.
echo [完成] 所有引擎已停止
pause
