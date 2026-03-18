# -*- coding: utf-8 -*-
"""
回测引擎 (Backtesting Engine) - 调试优化版
=============================================
基于文档建议的调试策略模板

核心改进：
1. 使用 ROC (收益率) 计算 Z-Score
2. 参数化设计，方便网格搜索
3. use_ema_filter 调试开关
4. 详细日志输出

作者: AI 量化研究助手
日期: 2026-03-18
"""

import os
import sys
import pandas as pd
import numpy as np
import backtrader as bt
import matplotlib.pyplot as plt
import logging
from datetime import datetime
from typing import Optional, Dict
import warnings
warnings.filterwarnings('ignore')

# ================= 配置区 =================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("BacktestEngine")


# ================= 调试版策略 =================

class ZScoreStrategy(bt.Strategy):
    """
    自适应 Z-Score 测试策略（调试版）
    
    核心改进：
    1. 使用 ROC (收益率) 计算 Z-Score，避免价格绝对值问题
    2. use_ema_filter 开关控制 EMA 过滤（调试时关闭）
    3. 详细日志输出
    """
    
    params = dict(
        window=10,            # 统计窗口 (日线级别建议 5-20)
        z_threshold=-1.5,    # 【均值回归】Z-Score 阈值（负数表示超跌）
        ema_period=20,       # EMA 周期
        use_ema_filter=False,# 【调试开关】是否开启 EMA 过滤
        stop_loss=0.10,      # 止损比例
        trade_ratio=0.3,     # 每次交易动用资金比例
        printlog=True,       # 是否打印日志
    )

    def __init__(self):
        # 记录收盘价
        self.dataclose = self.datas[0].close
        
        # 计算 EMA
        self.ema = bt.indicators.ExponentialMovingAverage(
            self.datas[0], period=self.p.ema_period
        )
        
        # 计算日收益率 (Rate of Change)
        self.roc = bt.indicators.RateOfChange100(self.datas[0], period=1)
        
        # 使用 Backtrader 内置的移动平均和标准差计算 Z-Score
        self.roc_sma = bt.indicators.SimpleMovingAverage(self.roc, period=self.p.window)
        self.roc_std = bt.indicators.StandardDeviation(self.roc, period=self.p.window)
        
        # 订单引用
        self.order = None
        self.buy_price = None
        
        # 统计
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        
    def log(self, txt, dt=None):
        if self.p.printlog:
            dt = dt or self.datas[0].datetime.date(0)
            print(f'[{dt.isoformat()}] {txt}')

    def next(self):
        # 如果有挂起的订单，不执行新操作
        if self.order:
            return

        # 获取当前值
        price = self.dataclose[0]
        ema_val = self.ema[0]
        
        # 计算当前的 Z-score (基于 ROC)
        std = self.roc_std[0]
        if std and std > 0:
            current_z = (self.roc[0] - self.roc_sma[0]) / std
        else:
            current_z = 0.0

        # === 均值回归核心逻辑判断 ===
        
        # 1. 抄底条件：发生极端暴跌 (Z < threshold, 如 -1.5)
        # threshold 为负数，所以 current_z < self.p.z_threshold 意味着超跌
        buy_signal = current_z < self.p.z_threshold
        
        # EMA 过滤逻辑 (如果开启：要求价格在均线之下，确认是超跌)
        if self.p.use_ema_filter:
            buy_signal = buy_signal and (price < ema_val)

        # 2. 卖出条件：情绪回归正常 (Z > 0) 或 股价反弹到 EMA 以上
        sell_signal = (current_z > 0) or (price > ema_val)

        # === 执行交易 ===
        pos = self.getposition().size
        
        if pos == 0:  # 空仓状态
            if buy_signal:
                # 按照资金比例买入
                target_value = self.broker.getcash() * self.p.trade_ratio
                size = int(target_value / price / 100) * 100  # A股凑整100股
                
                if size > 0:
                    self.log(f'🟢 [恐慌抄底] Z={current_z:.2f}<{self.p.z_threshold} | 买入 {size}股 @ {price:.2f}')
                    self.order = self.buy(size=size)
                    self.buy_price = price
        
        else:  # 持仓状态 - 止盈/止损
            # 止损
            if price < self.buy_price * (1 - self.p.stop_loss):
                self.log(f'🔴 [止损] 跌幅 {(price/self.buy_price-1)*100:.1f}% | 卖出 {pos}股 @ {price:.2f}')
                self.order = self.close()
                self.loss_count += 1
            
            # 止盈：均值回归
            elif sell_signal:
                profit_pct = (price / self.buy_price - 1) * 100
                self.log(f'🔴 [均值回归止盈] Z={current_z:.2f}>0 | 卖出 {pos}股 @ {price:.2f} (盈利{profit_pct:.1f}%)')
                self.order = self.close()
                if price > self.buy_price:
                    self.win_count += 1
                else:
                    self.loss_count += 1

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'✅ [买单成交] 价格: {order.executed.price:.2f}, 成本: {order.executed.value:.2f}, 手续费: {order.executed.comm:.2f}')
            else:
                self.log(f'✅ [卖单成交] 价格: {order.executed.price:.2f}, 成本: {order.executed.value:.2f}, 手续费: {order.executed.comm:.2f}')
                self.trade_count += 1

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('❌ [订单失败] 资金不足或被拒绝')

        self.order = None

    def stop(self):
        total = self.win_count + self.loss_count
        win_rate = self.win_count / total * 100 if total > 0 else 0
        self.log(f'========== 策略结束 ==========')
        self.log(f'总交易次数: {self.trade_count}')
        self.log(f'盈利次数: {self.win_count}, 亏损次数: {self.loss_count}')
        self.log(f'胜率: {win_rate:.1f}%')


class BollingerBandsStrategy(bt.Strategy):
    """
    布林带突破策略（简化版）
    """
    
    params = dict(
        bb_period=20,
        bb_dev=2.0,
        trade_ratio=0.3,
        printlog=True,
    )
    
    def __init__(self):
        self.dataclose = self.datas[0].close
        self.bb = bt.indicators.BollingerBands(
            self.datas[0].close, 
            period=self.p.bb_period,
            devfactor=self.p.bb_dev
        )
        self.order = None
        self.buy_price = None
        
    def log(self, txt, dt=None):
        if self.p.printlog:
            dt = dt or self.datas[0].datetime.date(0)
            print(f'[{dt.isoformat()}] {txt}')
    
    def next(self):
        pos = self.getposition().size
        
        # 价格触及下轨买入
        if pos == 0 and self.dataclose[0] < self.bb.lines.bot[0]:
            size = int(self.broker.getcash() * self.p.trade_ratio / self.dataclose[0] / 100) * 100
            if size > 0:
                self.log(f'🟢 [布林下轨买入] {self.dataclose[0]:.2f}')
                self.order = self.buy(size=size)
                self.buy_price = self.dataclose[0]
        
        # 价格触及上轨或止损卖出
        elif pos > 0:
            if self.dataclose[0] > self.bb.lines.top[0]:
                self.log(f'🔴 [布林上轨卖出] {self.dataclose[0]:.2f}')
                self.order = self.close()
            elif self.dataclose[0] < self.buy_price * 0.9:
                self.log(f'🔴 [止损卖出] {self.dataclose[0]:.2f}')
                self.order = self.close()
    
    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'✅ 买入成交: {order.executed.price:.2f}')
            else:
                self.log(f'✅ 卖出成交: {order.executed.price:.2f}')
        self.order = None


# ================= 回测引擎 =================

class BacktestEngine:
    """
    回测引擎主类
    """
    
    def __init__(
        self,
        data_path: str = None,
        initial_cash: float = 1000000,
        commission: float = 0.00025,
        stamp_duty: float = 0.001,
        slippage: float = 0.002
    ):
        self.cerebro = bt.Cerebro()
        self.cerebro.broker.setcash(initial_cash)
        
        # 设置佣金（双向）
        self.cerebro.broker.setcommission(commission=commission)
        
        self.data_path = data_path
        self.results = None
        self.performance = {}
        
        logger.info(f"💰 初始资金: {initial_cash:,.0f}")
        logger.info(f"📊 佣金: {commission*100:.3f}%, 印花税: {stamp_duty*100:.2f}%, 滑点: {slippage*100:.2f}%")
    
    def load_data(self, symbol: str, start_date: str = None, end_date: str = None):
        """加载历史数据"""
        if self.data_path:
            filepath = os.path.join(self.data_path, f"{symbol}_daily.csv")
        else:
            data_dir = os.path.join(os.path.dirname(__file__), 'data')
            filepath = os.path.join(data_dir, f"{symbol}_daily.csv")
        
        if not os.path.exists(filepath):
            logger.error(f"❌ 数据文件不存在: {filepath}")
            return False
        
        df = pd.read_csv(filepath)
        df['date'] = pd.to_datetime(df['date'])
        
        # 日期过滤
        if start_date:
            start = pd.to_datetime(start_date)
            df = df[df['date'] >= start]
        if end_date:
            end = pd.to_datetime(end_date)
            df = df[df['date'] <= end]
        
        # 创建 Backtrader 数据源
        data = bt.feeds.PandasData(
            dataname=df,
            datetime='date',
            open='open',
            high='high',
            low='low',
            close='close',
            volume='volume',
            openinterest=-1
        )
        
        self.cerebro.adddata(data, name=symbol)
        logger.info(f"📂 加载数据: {symbol} ({len(df)} 条)")
        return True
    
    def add_strategy(self, strategy_class, **kwargs):
        """添加策略"""
        self.cerebro.addstrategy(strategy_class, **kwargs)
        logger.info(f"📈 添加策略: {strategy_class.__name__}, 参数: {kwargs}")
    
    def add_analyzers(self):
        """添加分析器"""
        self.cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
        self.cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        self.cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
        self.cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    def run(self):
        """运行回测"""
        logger.info("=" * 50)
        logger.info("🚀 开始回测...")
        logger.info("=" * 50)
        
        self.add_analyzers()
        self.results = self.cerebro.run()
        
        # 提取绩效
        strat = self.results[0]
        
        # Sharpe
        sharpe = strat.analyzers.sharpe.get_analysis()
        self.performance['sharpe_ratio'] = sharpe.get('sharperatio', None)
        
        # Drawdown
        dd = strat.analyzers.drawdown.get_analysis()
        self.performance['max_drawdown'] = dd.get('max', {}).get('drawdown', None)
        
        # Returns
        ret = strat.analyzers.returns.get_analysis()
        self.performance['total_return'] = ret.get('rtot', None) * 100 if ret.get('rtot') else None
        
        # Trades
        trades = strat.analyzers.trades.get_analysis()
        total = trades.get('total', {}).get('total', 0)
        won = trades.get('won', {}).get('total', 0)
        lost = trades.get('lost', {}).get('total', 0)
        self.performance['total_trades'] = total
        self.performance['win_rate'] = (won / total * 100) if total > 0 else None
        
        # 最终资金
        final_value = self.cerebro.broker.getvalue()
        self.performance['final_value'] = final_value
        
        return self.performance
    
    def print_results(self):
        """打印回测结果"""
        print("\n" + "=" * 60)
        print("📊 回测绩效报告")
        print("=" * 60)
        print(f"💰 最终资金: {self.performance.get('final_value', 0):,.0f}")
        print(f"📈 总收益率: {self.performance.get('total_return') or 0:.2f}%")
        print(f"📉 最大回撤: {self.performance.get('max_drawdown') or 0:.2f}%")
        print(f"⚡ 夏普比率: {self.performance.get('sharpe_ratio') or 0:.2f}")
        print(f"🎯 胜率: {self.performance.get('win_rate') or 0:.1f}%")
        print(f"📊 总交易次数: {self.performance.get('total_trades') or 0}")
        print("=" * 60 + "\n")


# ================= 主程序 =================

if __name__ == "__main__":
    import sys
    
    # 获取数据路径
    if len(sys.argv) > 1:
        data_path = sys.argv[1]
    else:
        data_path = os.path.join(os.path.dirname(__file__), 'data')
    
    # 创建回测引擎
    engine = BacktestEngine(
        initial_cash=1000000,
        commission=0.00025,
        stamp_duty=0.001,
        slippage=0.002
    )
    
    # 加载数据
    engine.load_data("sh600000", "2022-01-01", "2024-12-31")
    
    # 添加调试版策略
    engine.add_strategy(
        ZScoreStrategy,
        window=10,
        z_threshold=0.8,       # 降低门槛
        use_ema_filter=False,  # 关闭 EMA 悖论
        trade_ratio=0.3,
        printlog=True
    )
    
    # 运行回测
    engine.run()
    engine.print_results()
