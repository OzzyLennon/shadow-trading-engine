# -*- coding: utf-8 -*-
"""
Alpha 市场中性对冲回测引擎
===========================
核心逻辑：做多目标个股 + 做空宽基指数 ETF = 纯 Alpha 收益

架构：
- Data 0: 目标股票 (如中国神华)
- Data 1: 对冲标的 (如上证50ETF sh510050)

作者: AI量化研究助手
版本: 1.0.0
日期: 2026-03-18
"""

import backtrader as bt
import pandas as pd
import numpy as np
import os
import logging
from typing import Dict, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AlphaHedgeStrategy(bt.Strategy):
    """
    市场中性对冲策略 (Alpha Hedging Strategy)
    
    核心逻辑：
    1. 当 Z-Score < -1.5（极度恐慌）时：
       - 做多目标股票
       - 同时做空对冲ETF（市值对等）
    2. 当 Z-Score > 0（情绪回归）时：
       - 平仓股票（卖出）
       - 平仓ETF（买券还券）
    
    这样获得的是纯粹的 Alpha 收益（股票跑赢大盘的部分）
    """
    
    params = dict(
        z_threshold=-1.5,      # 极度恐慌抄底阈值
        z_exit=0.0,            # 情绪回归止盈阈值
        momentum_window=10,    # Z-Score 计算窗口
        trade_ratio=0.3,       # 每次动用资金比例
        hedge_ratio=1.0,       # 对冲比例：1.0 = 100%市值中性
        printlog=True
    )
    
    def __init__(self):
        # Data 0: 目标股票 (如中国神华)
        self.stock = self.datas[0]
        # Data 1: 对冲标的 (如上证50ETF)
        self.benchmark = self.datas[1]
        
        # 只针对目标股票计算 Z-Score
        self.roc = bt.indicators.RateOfChange100(self.stock, period=1)
        self.roc_sma = bt.indicators.SimpleMovingAverage(
            self.roc, period=self.p.momentum_window
        )
        self.roc_std = bt.indicators.StandardDeviation(
            self.roc, period=self.p.momentum_window
        )
        
        # 记录订单状态
        self.order_stock = None
        self.order_bench = None
        
        # 交易统计
        self.trades = []
    
    def log(self, txt, dt=None):
        if self.p.printlog:
            dt = dt or self.datas[0].datetime.date(0)
            print(f'[{dt.isoformat()}] {txt}')
    
    def next(self):
        # 确保两份数据都准备好
        if len(self.stock) < self.p.momentum_window or len(self.benchmark) < self.p.momentum_window:
            return
        
        # 获取当前价格
        stock_price = self.stock.close[0]
        bench_price = self.benchmark.close[0]
        
        # 计算 Z-Score
        std = self.roc_std[0]
        current_z = (self.roc[0] - self.roc_sma[0]) / std if std and std > 0 else 0.0
        
        # === 核心交易逻辑 ===
        
        # 没有股票持仓时，寻找抄底机会
        if not self.getposition(self.stock):
            if current_z < self.p.z_threshold:
                # 1. 计算要做多的股票数量
                target_value = self.broker.getcash() * self.p.trade_ratio
                stock_size = int(target_value / stock_price / 100) * 100
                
                # 2. 计算要做空的指数 ETF 数量 (市值对等)
                hedge_value = target_value * self.p.hedge_ratio
                bench_size = int(hedge_value / bench_price / 100) * 100
                
                if stock_size > 0 and bench_size > 0:
                    self.log(f'🟢 [开启对冲] Z-Score: {current_z:.2f}')
                    self.log(f'   -> 做多: {self.stock._name} {stock_size}股 @ {stock_price:.2f}')
                    self.log(f'   -> 做空: {self.benchmark._name} {bench_size}股 @ {bench_price:.2f}')
                    
                    # 做多股票
                    self.order_stock = self.buy(data=self.stock, size=stock_size)
                    # 做空ETF
                    self.order_bench = self.sell(data=self.benchmark, size=bench_size)
        
        # 持仓时的平仓逻辑
        else:
            # 止盈条件：恐慌情绪消失
            if current_z > self.p.z_exit:
                self.log(f'🔴 [解除对冲] 情绪回归 (Z={current_z:.2f})，双边平仓')
                
                # 平仓股票（卖出）
                self.order_stock = self.close(data=self.stock)
                # 平仓ETF（买券还券）
                self.order_bench = self.close(data=self.benchmark)
    
    def notify_order(self, order):
        if order.status in [order.Completed]:
            action = "买入" if order.isbuy() else "卖出(做空)"
            self.log(f'✅ [订单成交] {order.data._name} | {action} 价格: {order.executed.price:.2f} | 费用: {order.executed.comm:.2f}')
    
    def notify_trade(self, trade):
        if trade.isclosed:
            self.trades.append({
                'pnl': trade.pnl,
                'pnlcomm': trade.pnlcomm
            })


class AlphaHedgeEngine:
    """
    Alpha 对冲回测引擎
    
    使用方法：
    >>> engine = AlphaHedgeEngine()
    >>> engine.load_stock_data('sh601088', '中国神华')
    >>> engine.load_hedge_data('sh510050', '上证50ETF')
    >>> results = engine.run()
    """
    
    def __init__(
        self,
        initial_cash: float = 1000000.0,
        commission: float = 0.0003,
        data_path: str = './research/data'
    ):
        self.cerebro = bt.Cerebro()
        self.initial_cash = initial_cash
        self.commission = commission
        self.data_path = data_path
        self.stock_name = ""
        self.hedge_name = ""
        
        # 设置初始资金
        self.cerebro.broker.setcash(initial_cash)
        
        # 设置手续费（做多和做空统一）
        self.cerebro.broker.setcommission(commission=commission)
        
        # 允许做空产生负头寸
        self.cerebro.broker.set_shortcash(True)
        
        # 添加分析器
        self.cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
        self.cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        self.cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
        self.cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    def load_stock_data(self, symbol: str, name: str = "Target_Stock"):
        """加载目标股票数据"""
        csv_path = os.path.join(self.data_path, f'{symbol}_daily.csv')
        
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"数据文件不存在: {csv_path}")
        
        df = pd.read_csv(csv_path, index_col='date', parse_dates=True)
        
        data = bt.feeds.PandasData(
            dataname=df,
            name=name
        )
        
        self.cerebro.adddata(data)
        self.stock_name = name
        logger.info(f"📂 加载股票数据: {name} ({len(df)} 条)")
    
    def load_hedge_data(self, symbol: str, name: str = "Hedge_Index"):
        """加载对冲ETF数据"""
        csv_path = os.path.join(self.data_path, f'{symbol}_daily.csv')
        
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"数据文件不存在: {csv_path}")
        
        df = pd.read_csv(csv_path, index_col='date', parse_dates=True)
        
        data = bt.feeds.PandasData(
            dataname=df,
            name=name
        )
        
        self.cerebro.adddata(data)
        self.hedge_name = name
        logger.info(f"📂 加载对冲数据: {name} ({len(df)} 条)")
    
    def add_strategy(self, **kwargs):
        """添加对冲策略"""
        self.cerebro.addstrategy(AlphaHedgeStrategy, **kwargs)
        logger.info(f"📈 添加策略: AlphaHedgeStrategy, 参数: {kwargs}")
    
    def run(self) -> Dict:
        """运行回测"""
        logger.info("=" * 50)
        logger.info("🛡️ 启动 Alpha 市场中性对冲回测引擎")
        logger.info("=" * 50)
        
        start_value = self.cerebro.broker.getvalue()
        
        results = self.cerebro.run()
        strategy = results[0]
        
        end_value = self.cerebro.broker.getvalue()
        total_return = (end_value - start_value) / start_value * 100
        
        # 提取分析结果
        sharpe = strategy.analyzers.sharpe.get_analysis().get('sharperatio', 0) or 0
        drawdown = strategy.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0) or 0
        trades = strategy.analyzers.trades.get_analysis()
        
        total_trades = trades.get('total', {}).get('total', 0)
        won = trades.get('won', {}).get('total', 0)
        win_rate = (won / total_trades * 100) if total_trades > 0 else 0
        
        print("\n" + "=" * 50)
        print("📊 对冲回测结果")
        print("=" * 50)
        print(f"💰 初始资金: {start_value:,.0f}")
        print(f"💰 最终资金: {end_value:,.0f}")
        print(f"📈 纯Alpha收益率: {total_return:.2f}%")
        print(f"⚡ 夏普比率: {sharpe:.2f}")
        print(f"📉 最大回撤: {drawdown:.2f}%")
        print(f"🎯 胜率: {win_rate:.1f}% ({won}/{total_trades})")
        print("=" * 50)
        
        return {
            'total_return': total_return,
            'sharpe_ratio': sharpe,
            'max_drawdown': drawdown,
            'win_rate': win_rate,
            'total_trades': total_trades,
            'initial_cash': start_value,
            'final_cash': end_value
        }


def run_hedge_backtest_comparison(stock_symbol: str, stock_name: str, hedge_symbol: str, hedge_name: str):
    """
    运行对比回测：纯多头 vs 对冲
    
    Args:
        stock_symbol: 股票代码 (如 sh601088)
        stock_name: 股票名称 (如 中国神华)
        hedge_symbol: 对冲ETF代码 (如 sh510050)
        hedge_name: 对冲ETF名称 (如 上证50ETF)
    """
    from .backtest_engine import BacktestEngine, ZScoreStrategy
    
    print("\n" + "=" * 60)
    print("🔬 对冲效果对比实验")
    print("=" * 60)
    
    # 1. 纯多头回测
    print("\n📊 [实验1] 纯多头策略 (不做对冲)")
    print("-" * 40)
    
    engine_long = BacktestEngine(initial_cash=1000000, commission=0.0003)
    engine_long.load_data(stock_symbol)
    engine_long.add_strategy(
        ZScoreStrategy,
        window=10,
        z_threshold=-1.5,
        trade_ratio=0.3,
        printlog=False
    )
    result_long = engine_long.run()
    
    # 2. 对冲回测
    print("\n📊 [实验2] 市场中性对冲策略 (做多股票+做空ETF)")
    print("-" * 40)
    
    engine_hedge = AlphaHedgeEngine(initial_cash=1000000, commission=0.0003)
    engine_hedge.load_stock_data(stock_symbol, stock_name)
    engine_hedge.load_hedge_data(hedge_symbol, hedge_name)
    engine_hedge.add_strategy(
        z_threshold=-1.5,
        z_exit=0.0,
        momentum_window=10,
        trade_ratio=0.3,
        hedge_ratio=1.0,
        printlog=False
    )
    result_hedge = engine_hedge.run()
    
    # 3. 对比结果
    print("\n" + "=" * 60)
    print("📊 策略对比汇总")
    print("=" * 60)
    
    print(f"\n{'指标':<20} {'纯多头':<15} {'市场中性对冲':<15}")
    print("-" * 50)
    print(f"{'收益率':<20} {result_long['total_return']:>12.2f}% {result_hedge['total_return']:>12.2f}%")
    print(f"{'夏普比率':<20} {result_long['sharpe_ratio']:>12.2f} {result_hedge['sharpe_ratio']:>12.2f}")
    print(f"{'最大回撤':<20} {result_long['max_drawdown']:>12.2f}% {result_hedge['max_drawdown']:>12.2f}%")
    print(f"{'胜率':<20} {result_long['win_rate']:>12.1f}% {result_hedge['win_rate']:>12.1f}%")
    
    # 计算Alpha提取效果
    beta_reduction = result_long['max_drawdown'] - result_hedge['max_drawdown']
    print(f"\n🛡️ Beta剥离效果: 最大回撤减少 {beta_reduction:.2f}%")
    
    return {
        'long_only': result_long,
        'hedged': result_hedge,
        'beta_reduction': beta_reduction
    }


if __name__ == '__main__':
    # 示例：运行对冲回测
    # 需要先下载上证50ETF数据
    pass
