@echo off
REM APEX 量化交易系统启动脚本
REM Windows版本

echo ========================================
echo   APEX 量化交易系统启动器
echo ========================================
echo.

REM 检查.env文件
if not exist "%~dp0.env" (
    echo [警告] 未找到 .env 文件，正在从示例创建...
    copy "%~dp0.env.example" "%~dp0.env"
    echo [提示] 请编辑 .env 文件配置你的飞书Webhook和API密钥
    echo.
)

REM 创建日志目录
if not exist "%~dp0logs" mkdir "%~dp0logs"

echo [1] 启动 Red Engine (煤电红利均值回归)...
start "Red Engine" /min python "%~dp0apex_quant_simulator.py"

timeout /t 2 /nobreak >nul

echo [2] 启动 Blue Engine (科技对冲)...
start "Blue Engine" /min python "%~dp0apex_tech_hedge.py"

timeout /t 2 /nobreak >nul

echo [3] 启动 Alpha Factory (策略工厂)...
start "Alpha Factory" /min python "%~dp0alpha_factory_daemon.py"

echo.
echo ========================================
echo   所有引擎已启动！
echo ========================================
echo.
echo 日志目录: %~dp0logs
echo.
echo 按任意键关闭此窗口 (引擎将继续运行)
pause >nul
