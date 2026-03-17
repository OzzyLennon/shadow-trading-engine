# 🚀 影子交易引擎（统计学升级版 v4.0）

AI + 统计学驱动的高频量化交易模拟系统。**实时守护进程模式**，3-5秒级轮询。

---

## 📐 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                    🧠 AI 大脑 (ai_brain.py)                   │
│  • 每天 8:30 运行（Cron 定时）                                 │
│  • 抓取 A 股早盘新闻 + 资金面 + 外围市场                       │
│  • 动态生成当日作战参数 + 选股池                               │
└────────────────────────┬──────────────────────────────────────┘
                         │ daily_config.json
                         ▼
┌──────────────────────────────────────────────────────────────┐
│           ⚡ APEX 守护进程 (apex_quant_simulator.py)           │
│  • 常驻内存，实时运行                                          │
│  • 每 5 秒扫描一次（可配置 3-5 秒）                            │
│  • 自动检测交易时段                                            │
│  • 优雅退出（支持 SIGINT/SIGTERM）                            │
│  • Z-Score + 布林带 + 凯利公式 + VaR                           │
└──────────────────────────────────────────────────────────────┘
```

---

## ⚡ v4.0 守护进程升级

### 为什么从 Cron 改为守护进程？

| 对比项 | Cron (v3) | 守护进程 (v4) |
|--------|-----------|---------------|
| 轮询间隔 | 2 分钟 | **3-5 秒** |
| 启动延迟 | 每次启动 Python | 常驻内存 |
| 游资点火响应 | 慢 2 分钟 | **毫秒级** |
| 买入时机 | 可能买在山顶 | **及时追入** |

### 关键改进

**投资顾问分析**：
> 对于"游资点火追涨"策略，2分钟延迟是致命的。
> 妖股从平盘拉到涨停只需 30秒~1分钟，
> 2分钟后追入可能已经涨了 6%，盈亏比极度恶化。

**解决方案**：
- 改为常驻内存的守护进程
- 3-5 秒轮询（新浪接口完全承受）
- 自动检测交易时段

---

## 🧪 统计学核心（LaTeX 精确公式）

### 1. Z-Score 波动率调整

```
Z = (r_t - μ) / σ
```

当 `Z > 2.0` 时，突破 95% 置信区间，触发买入。

### 2. 凯利公式仓位管理

```
f* = (bp - (1-p)) / b
```

- `b` = 赔率（盈亏比）
- `p` = 胜率
- 使用半凯利策略，更保守

### 3. VaR 风险预警

```
VaR_α = inf { L : P(Loss > L) ≤ 1-α }
```

99% 置信度下的最大可能损失。

---

## 🚀 快速开始

### 1. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入你的 API Key
```

### 2. 运行 AI 大脑（每天 8:30）

```bash
python ai_brain.py
```

### 3. 启动守护进程

```bash
# 前台运行（可看到日志输出）
python apex_quant_simulator.py

# 后台运行（推荐生产环境）
nohup python apex_quant_simulator.py > logs/daemon.log 2>&1 &

# 使用 systemd 管理（更专业）
# 见下方 systemd 配置
```

### 4. 停止守护进程

```bash
# 发送 SIGTERM 信号优雅退出
kill <PID>

# 或使用 Ctrl+C（如果在前台运行）
```

---

## ⚙️ Systemd 服务配置（推荐）

创建 `/etc/systemd/system/apex-trader.service`：

```ini
[Unit]
Description=APEX Shadow Trading Engine
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/path/to/shadow-trading-engine
ExecStart=/usr/bin/python3 /path/to/shadow-trading-engine/apex_quant_simulator.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# 启用并启动
systemctl enable apex-trader
systemctl start apex-trader

# 查看状态
systemctl status apex-trader

# 查看日志
journalctl -u apex-trader -f
```

---

## ⏰ 定时任务配置

只需配置 AI 大脑，守护进程会自动运行：

```bash
# 每天 8:30 运行 AI 大脑
30 8 * * 1-5 cd /path/to/shadow-trading-engine && /usr/bin/python3 ai_brain.py >> logs/brain.log 2>&1
```

---

## 📁 文件说明

| 文件 | 说明 |
|------|------|
| `ai_brain.py` | AI 大脑，每天 8:30 生成参数 |
| `apex_quant_simulator.py` | **守护进程引擎 v4.0** |
| `shadow_quant_trader.py` | 原版保守引擎（备用） |
| `daily_config.json` | 每日策略参数 |
| `apex_portfolio.json` | 虚拟持仓记录 |
| `trade_stats.json` | 交易统计（凯利公式用） |
| `logs/apex_daemon.log` | 守护进程日志 |

---

## 🎯 参数配置

在 `apex_quant_simulator.py` 头部修改：

```python
POLL_INTERVAL = 5      # 轮询间隔（秒），建议 3-5
TRADING_START = 9      # 交易开始时间
TRADING_END = 15       # 交易结束时间
MOMENTUM_WINDOW = 20   # 统计窗口大小
Z_SCORE_THRESHOLD = 2.0 # Z-Score 阈值
```

---

## ⚠️ 免责声明

本系统仅供学习和研究使用，所有交易均为模拟盘，不涉及真实资金。

**新联系方式警告**：
- 3-5 秒轮询对新浪接口完全安全
- 但比 2 分钟 Cron 频繁 24 倍
- 如需实盘，请接入券商 QMT/Ptrade

股市有风险，投资需谨慎。

---

## 📜 License

MIT

---

## 🙏 致谢

感谢投资顾问的专业分析，指出 2 分钟延迟对游资点火策略的致命影响。
