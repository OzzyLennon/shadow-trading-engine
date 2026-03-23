# APEX 量化交易系统 - Windows 运行指南

## 快速开始

### 1. 环境准备

```powershell
# 安装依赖
pip install -r requirements.txt

# 复制环境变量配置
copy .env.example .env

# 编辑 .env 文件，配置你的 API 密钥
notepad .env
```

### 2. 配置文件说明

编辑 `.env` 文件：
```
FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/你的webhook-id
DEEPSEEK_API_KEY=sk-your-api-key
```

### 3. 启动方式

#### 手动启动（推荐新手）
```powershell
# 启动所有交易引擎
start_engines.bat

# 启动 Dashboard 监控面板
start_dashboard.bat

# 停止所有引擎
stop_engines.bat
```

#### 晨间研判（建议 9:00 运行）
```powershell
# 运行风控研判和策略部署
run_morning_analysis.bat
```

#### 收盘汇报（建议 15:00 运行）
```powershell
# 发送当日收益汇总
run_daily_report.bat
```

---

## Windows 任务计划程序配置

### 方法一：使用任务计划程序 GUI

1. 打开 **任务计划程序**（搜索 "Task Scheduler"）
2. 点击右侧 **创建任务**
3. 配置如下：

#### 任务1: AI晨间研判
- **名称**: APEX_AI_Morning
- **触发器**: 每周一至周五 9:00
- **操作**: 启动程序
  - 程序: `python.exe`
  - 参数: `D:\git\shadow-trading-engine\ai_sentinel.py`
  - 起始位置: `D:\git\shadow-trading-engine`

#### 任务2: 启动Red Engine
- **名称**: APEX_RedEngine
- **触发器**: 每周一至周五 9:25
- **操作**: 启动程序
  - 程序: `python.exe`
  - 参数: `apex_quant_simulator.py`
  - 起始位置: `D:\git\shadow-trading-engine`

#### 任务3: 启动Blue Engine
- **名称**: APEX_BlueEngine
- **触发器**: 每周一至周五 9:26
- **操作**: 启动程序
  - 程序: `python.exe`
  - 参数: `apex_tech_hedge.py`
  - 起始位置: `D:\git\shadow-trading-engine`

#### 任务4: 启动Alpha Factory
- **名称**: APEX_AlphaFactory
- **触发器**: 每周一至周五 9:27
- **操作**: 启动程序
  - 程序: `python.exe`
  - 参数: `alpha_factory_daemon.py`
  - 起始位置: `D:\git\shadow-trading-engine`

#### 任务5: 收盘汇报
- **名称**: APEX_DailyReport
- **触发器**: 每周一至周五 15:00
- **操作**: 启动程序
  - 程序: `python.exe`
  - 参数: `daily_report.py`
  - 起始位置: `D:\git\shadow-trading-engine`

#### 任务6: 停止所有引擎
- **名称**: APEX_StopEngines
- **触发器**: 每周一至周五 15:05
- **操作**: 启动程序
  - 程序: `stop_engines.bat`
  - 起始位置: `D:\git\shadow-trading-engine`

---

### 方法二：使用 PowerShell 命令创建任务

```powershell
# 以管理员身份运行 PowerShell

# 定义路径
$scriptPath = "D:\git\shadow-trading-engine"

# 创建晨间研判任务 (9:00)
$action = New-ScheduledTaskAction -Execute "python" -Argument "ai_sentinel.py" -WorkingDirectory $scriptPath
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 9:00AM
Register-ScheduledTask -TaskName "APEX_AI_Sentinel" -Action $action -Trigger $trigger -RunLevel Highest

# 创建Red Engine任务 (9:25)
$action = New-ScheduledTaskAction -Execute "python" -Argument "apex_quant_simulator.py" -WorkingDirectory $scriptPath
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 9:25AM
Register-ScheduledTask -TaskName "APEX_Red_Engine" -Action $action -Trigger $trigger -RunLevel Highest

# 创建Blue Engine任务 (9:26)
$action = New-ScheduledTaskAction -Execute "python" -Argument "apex_tech_hedge.py" -WorkingDirectory $scriptPath
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 9:26AM
Register-ScheduledTask -TaskName "APEX_Blue_Engine" -Action $action -Trigger $trigger -RunLevel Highest

# 创建收盘汇报任务 (15:00)
$action = New-ScheduledTaskAction -Execute "python" -Argument "daily_report.py" -WorkingDirectory $scriptPath
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 3:00PM
Register-ScheduledTask -TaskName "APEX_Daily_Report" -Action $action -Trigger $trigger -RunLevel Highest

# 创建停止引擎任务 (15:05)
$action = New-ScheduledTaskAction -Execute "stop_engines.bat" -WorkingDirectory $scriptPath
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 3:05PM
Register-ScheduledTask -TaskName "APEX_Stop_Engines" -Action $action -Trigger $trigger -RunLevel Highest
```

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Windows 任务计划程序                       │
├─────────────────────────────────────────────────────────────┤
│  9:00   AI Sentinel (风控研判)                               │
│  9:00   AI Brain (策略部署)                                  │
│  9:25   Red Engine 启动                                      │
│  9:26   Blue Engine 启动                                     │
│  9:27   Alpha Factory 启动                                   │
│  15:00  收盘汇报                                             │
│  15:05  停止所有引擎                                          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     核心模块 (core/)                          │
│  ├── config.py     统一配置管理                               │
│  ├── functions.py  核心计算函数                               │
│  ├── errors.py     错误处理                                   │
│  └── logging_config.py  日志系统                              │
└─────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
   │ Red Engine  │     │ Blue Engine │     │Alpha Factory│
   │ 均值回归     │     │ 科技对冲     │     │ 策略工厂     │
   │ 煤电红利     │     │ 动量+对冲    │     │ 灰度测试     │
   └─────────────┘     └─────────────┘     └─────────────┘
```

---

## 日志文件

所有日志保存在 `logs/` 目录：
- `apex_daemon.log` - Red Engine 日志
- `apex_tech_hedge.log` - Blue Engine 日志
- `alpha_factory.log` - Alpha Factory 日志
- `ai_sentinel.log` - AI Sentinel 日志
- `ai_brain.log` - AI Brain 日志

---

## 常见问题

### Q: 如何查看运行状态？
```powershell
# 查看 Dashboard
start_dashboard.bat
# 浏览器打开 http://localhost:8501
```

### Q: 如何手动运行单次扫描？
```powershell
# 测试配置加载
python -c "from core.config import load_config; c=load_config(); print(c)"

# 测试某个引擎
python apex_quant_simulator.py
```

### Q: 引擎没有触发交易？
1. 检查 `daily_config.json` 中的 `red_engine_allow` 和 `blue_engine_allow` 是否为 `true`
2. 检查是否在交易时段（9:30-11:30, 13:00-14:57）
3. 检查日志文件是否有错误信息

---

## 配置文件说明

### daily_config.json (可选)
系统运行时会在当前目录创建/更新此文件，包含：
- `red_engine_allow`: Red Engine 交易开关
- `blue_engine_allow`: Blue Engine 交易开关
- `global_market_status`: 全局市场状态
- `symbols`: 监控股票池
