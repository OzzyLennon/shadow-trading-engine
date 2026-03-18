import backtrader as bt
import pandas as pd
import numpy as np

class BlueHedgeOptStrategy(bt.Strategy):
    """
    专用于网格搜索的 Blue Engine (科技动量 + 低波过滤)
    """
    params = dict(
        vol_window=20,       # 待优化参数 1
        vol_threshold=0.03,  # 待优化参数 2
        z_threshold=1.5,
        momentum_window=20,
    )

    def __init__(self):
        self.stock = self.datas[0]
        
        # 计算动量 Z-Score
        self.roc = bt.indicators.RateOfChange100(self.stock, period=1)
        self.roc_sma = bt.indicators.SimpleMovingAverage(self.roc, period=self.p.momentum_window)
        self.roc_std = bt.indicators.StandardDeviation(self.roc, period=self.p.momentum_window)
        
        # 核心：计算波动率 (利用 ROC 的标准差，年化前)
        self.volatility = bt.indicators.StandardDeviation(self.roc, period=self.p.vol_window)

    def next(self):
        if len(self.stock) < max(self.p.momentum_window, self.p.vol_window):
            return

        std = self.roc_std[0]
        current_z = (self.roc[0] - self.roc_sma[0]) / std if std and std > 0 else 0.0
        
        # 将 ROC 的百分比标准差转为小数形式的波动率
        current_vol = self.volatility[0] / 100.0 if self.volatility[0] else 0.0

        if not self.position:
            # 💡 多因子共振买入条件：动量突破 + 波动率达标
            if current_z > self.p.z_threshold and current_vol < self.p.vol_threshold:
                # 简化测试：全仓做多 (只测因子有效性，对冲另算)
                self.order_target_percent(target=0.95)
        else:
            # 动量衰竭卖出
            if current_z < 0:
                self.close()

# ==========================================
# 启动网格搜索引擎
# ==========================================
def run_grid_search(data_path):
    print("="*60)
    print("🧬 启动 Blue Engine 参数网格搜索 (Grid Search)")
    print(f"📁 测试标的: {data_path}")
    print("="*60)
    
    cerebro = bt.Cerebro(optreturn=False)

    # 加载数据
    data = bt.feeds.PandasData(
        dataname=pd.read_csv(data_path, index_col='date', parse_dates=True)
    )
    cerebro.adddata(data)

    # 💡 核心：注入待优化的参数列表
    cerebro.optstrategy(
        BlueHedgeOptStrategy,
        vol_window=[10, 20, 40, 60],
        vol_threshold=[0.02, 0.03, 0.04, 0.05]
    )

    # 设置初始资金和手续费
    cerebro.broker.setcash(1000000.0)
    cerebro.broker.setcommission(commission=0.0003)

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')

    # 运行优化 (会返回一个包含所有策略运行结果的列表的列表)
    print("⏳ 正在并行运算所有参数组合，请稍候...")
    opt_runs = cerebro.run()

    # 解析并打印结果
    print("\n🏆 网格搜索结果排行榜 (按总收益率排序)：")
    print(f"{'窗口(天)':<10} | {'波动阈值':<10} | {'总收益率':<10} | {'最大回撤':<10} | {'交易次数':<10}")
    print("-" * 60)
    
    results_list = []
    for run in opt_runs:
        strat = run[0]
        params = strat.params
        
        # 提取指标
        ret = strat.analyzers.returns.get_analysis()
        dd = strat.analyzers.drawdown.get_analysis()
        trades = strat.analyzers.trades.get_analysis()
        
        total_return = ret.get('rtot', 0) * 100 # 换算为百分比
        max_dd = dd.get('max', {}).get('drawdown', 0)
        total_trades = trades.get('total', {}).get('closed', 0)
        
        results_list.append({
            'window': params.vol_window,
            'threshold': params.vol_threshold,
            'return': total_return,
            'drawdown': max_dd,
            'trades': total_trades
        })
        
    # 按收益率降序排序
    results_list.sort(key=lambda x: x['return'], reverse=True)
    
    for r in results_list:
        print(f"{r['window']:<10} | {r['threshold']*100:>4.1f}%{'':<5} | {r['return']:>6.2f}%{'':<3} | {r['drawdown']:>6.2f}%{'':<3} | {r['trades']:<10}")

if __name__ == '__main__':
    # 替换为你实际的寒武纪或中际旭创数据路径
    # run_grid_search('data/sh688256_daily.csv')
    pass
