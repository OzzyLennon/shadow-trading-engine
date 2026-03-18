# 量化研究框架 (Research Framework)

IMA 知识库审核报告要求补全的投研环境。

## 📁 目录结构

```
research/
├── __init__.py           # 模块入口
├── data_downloader.py    # 历史数据下载器
├── backtest_engine.py    # Backtrader 回测引擎
├── walk_forward.py       # 前进式分析 (WFA)
├── README.md             # 本文档
└── data/                 # 数据存储目录 (自动创建)
    ├── sh600000_daily.csv
    ├── sz000001_daily.csv
    └── walk_forward_results.json
```

## 🚀 快速开始

### 1. 下载历史数据

```python
from research.data_downloader import download_stock_daily, clean_data, add_technical_indicators

# 下载单只股票
df = download_stock_daily("sh600000", "20200101", "20241231")

# 数据清洗
df = clean_data(df)

# 添加技术指标
df = add_technical_indicators(df)

# 批量下载
from research.data_downloader import download_stock_pool
symbols = ["sh600000", "sz000001", "sh601318"]
download_stock_pool(symbols, "20200101")
```

### 2. 运行回测

```python
from research.backtest_engine import BacktestEngine, ZScoreStrategy

# 创建回测引擎
engine = BacktestEngine(
    initial_cash=1000000,
    commission=0.00025,    # 佣金 0.025%
    stamp_duty=0.001,      # 印花税 0.1%
    slippage=0.002         # 滑点 0.2%
)

# 加载数据
engine.load_data("sh600000", start_date="20230101")

# 添加策略
engine.add_strategy(
    ZScoreStrategy,
    zscore_threshold=2.0,
    stop_loss=0.08,
    trade_ratio=0.3
)

# 运行回测
performance = engine.run()
engine.print_results()
```

### 3. 前进式分析 (Walk-Forward Analysis)

```python
from research.walk_forward import WalkForwardEngine

# 创建 WFA 引擎
wf_engine = WalkForwardEngine(
    data_path="./data",
    symbol="sh600000",
    train_window=252,  # 1年训练
    test_window=126,   # 半年测试
    step_size=63       # 3个月滚动
)

# 参数网格
param_grid = {
    'zscore_threshold': [1.5, 2.0, 2.5],
    'stop_loss': [0.05, 0.08, 0.10],
    'trade_ratio': [0.2, 0.3, 0.4]
}

# 运行 WFA
summary = wf_engine.run(param_grid)

# 保存结果
wf_engine.save_results("./data/walk_forward_results.json")
```

## 📊 核心指标

### 回测绩效指标

| 指标 | 说明 |
|------|------|
| **夏普比率 (Sharpe Ratio)** | 风险调整后收益，>1 为良好，>2 为优秀 |
| **最大回撤 (Max Drawdown)** | 历史最大亏损幅度，应控制在 20% 以内 |
| **胜率 (Win Rate)** | 盈利交易占比 |
| **盈亏比 (Profit/Loss Ratio)** | 平均盈利/平均亏损 |

### 前进式分析指标

| 指标 | 说明 |
|------|------|
| **样本外夏普比率 (OOS Sharpe)** | 测试集收益/标准差，反映策略泛化能力 |
| **过拟合概率 (PBO)** | 训练集优于测试集的比例，应 < 50% |
| **累计收益** | 所有测试窗口的复合收益 |

## ⚠️ 防过拟合检查清单

根据 IMA 报告，请确保：

- [ ] 使用前进式分析而非简单回测
- [ ] 严格区分训练集/测试集
- [ ] PBO < 50%（过拟合概率）
- [ ] 样本外夏普比率 > 0.5
- [ ] 参数数量少（奥卡姆剃刀原则）
- [ ] 考虑交易成本（佣金/印花税/滑点）

## 📦 依赖安装

```bash
pip install backtrader akshare pandas numpy matplotlib
```

## 📚 参考资料

- [Backtrader 官方文档](https://www.backtrader.com/)
- [AkShare 数据接口](https://akshare.akfamily.xyz/)
- [前进式分析论文](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2606462)

---

**作者**: AI 量化研究助手  
**日期**: 2026-03-18  
**版本**: v1.0
