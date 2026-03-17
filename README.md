# 🚀 影子交易引擎（模拟盘）

AI 驱动的高频量化交易模拟系统，包含「大脑」与「小脑」双层架构。

## 📐 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    🧠 AI 大脑 (ai_brain.py)              │
│  • 每天 8:30 运行                                        │
│  • 抓取 A 股早盘新闻                                     │
│  • 调用 LLM 进行情绪分析                                 │
│  • 动态生成当日作战参数                                  │
└─────────────────────┬───────────────────────────────────┘
                      │ daily_config.json
                      ▼
┌─────────────────────────────────────────────────────────┐
│              ⚡ APEX 小脑 (apex_quant_simulator.py)       │
│  • 交易时段每 2 分钟运行                                 │
│  • 读取 AI 大脑下发的参数                                │
│  • 监控 20 只高弹性 A 股                                 │
│  • 执行追涨/止盈/止损策略                                │
└─────────────────────────────────────────────────────────┘
```

## 🔧 策略说明

### 游资点火追涨
- 5 分钟内涨速超过阈值 → 动态仓位追入
- 动态开火：每次动用剩余现金的 N%

### 追踪止盈
- 盈利超过 5% 后激活
- 从最高点回落 3% → 锁定利润

### 铁血止损
- 亏损达到止损线 → 立即清仓

### AI 动态参数
根据新闻情绪，AI 每日动态调整：
- `surge_threshold`: 追涨阈值（激进 1.5%，防守 3.5%）
- `stop_loss_pct`: 止损线（激进 -8%，防守 -3%）
- `trade_ratio`: 动态开火比例（激进 50%，防守 10%）

## 🚀 快速开始

### 1. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入你的 API Key
```

### 2. 安装依赖

```bash
pip install requests
```

### 3. 运行

```bash
# 先运行大脑（生成当日参数）
python ai_brain.py

# 再运行小脑（执行交易）
python apex_quant_simulator.py
```

### 4. 配置定时任务

```bash
# 每天 8:30 运行大脑
30 8 * * 1-5 cd /path/to/shadow-trading-engine && /usr/bin/python3 ai_brain.py >> logs/brain.log 2>&1

# 交易时段每 2 分钟运行小脑
*/2 9-15 * * 1-5 cd /path/to/shadow-trading-engine && /usr/bin/python3 apex_quant_simulator.py >> logs/apex.log 2>&1
```

## 📁 文件说明

| 文件 | 说明 |
|------|------|
| `ai_brain.py` | AI 大脑，负责新闻分析和参数生成 |
| `apex_quant_simulator.py` | APEX 小脑，高频执行引擎 |
| `shadow_quant_trader.py` | 原版交易引擎（保守策略） |
| `daily_config.json` | AI 下发的每日参数（运行时生成） |
| `apex_portfolio.json` | 虚拟持仓记录 |

## ⚠️ 免责声明

本系统仅供学习和研究使用，所有交易均为模拟盘，不涉及真实资金。股市有风险，投资需谨慎。

## 📜 License

MIT
