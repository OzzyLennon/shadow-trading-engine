# -*- coding: utf-8 -*-
"""
科技动量 + 市场中性对冲回测引擎
===============================

策略逻辑：
- 多头：动量追涨 (Z-Score > 1.5 买入)
- 空头：100%市值对冲（做空指数）
- 止盈：动量衰竭 (Z-Score < 0)
"""

import backtrader as bt
import pandas as pd
import numpy as np
import os

# ==================== 策略定义 ====================

class MomentumStrategy(bt.Strategy):
    """纯动量策略（无对冲）"""
    params = dict(
        window=10,
        z_entry=1.5,      # 动量突破阈值
        z_exit=0.0,       # 动量衰竭阈值
        trade_ratio=0.3,
        printlog=True
    )
    
    def __init__(self):
        self.dataclose = self.data.close
        self.returns = []
        self.z_score = 0
        
    def next(self):
        # 计算收益率序列
        if len(self.dataclose) < self.p.window + 1:
            return
            
        close_prices = list(self.dataclose.get(size=self.p.window + 1))
        returns = [(close_prices[i] - close_prices[i-1]) / close_prices[i-1] 
                   for i in range(1, len(close_prices))]
        
        # 计算 Z-Score
        mu = np.mean(returns)
        sigma = np.std(returns)
        if sigma > 0:
            self.z_score = (returns[-1] - mu) / sigma
        else:
            self.z_score = 0
        
        # 交易逻辑
        if not self.position:
            # 动量突破：追涨买入
            if self.z_score > self.p.z_entry:
                cash = self.broker.getcash()
                price = self.data.close[0]
                size = int(cash * self.p.trade_ratio / price / 100) * 100
                if size > 0:
                    self.buy(size=size)
                    if self.p.printlog:
                        print(f"[{self.data.datetime.date()}] 🚀 动量追涨 Z={self.z_score:.2f} > {self.p.z_entry}")
                        print(f"    买入 {size}股 @ {price:.2f}")
        else:
            # 动量衰竭：止盈
            if self.z_score < self.p.z_exit:
                self.close()
                if self.p.printlog:
                    print(f"[{self.data.datetime.date()}] 🏆 动量衰竭 Z={self.z_score:.2f} < {self.p.z_exit}")
                    print(f"    卖出 {self.position.size}股 @ {self.data.close[0]:.2f}")


class MomentumHedgeStrategy(bt.Strategy):
    """动量策略 + 市场中性对冲"""
    params = dict(
        window=10,
        z_entry=1.5,
        z_exit=0.0,
        trade_ratio=0.3,
        hedge_ratio=1.0,    # 100%市值对冲
        printlog=True
    )
    
    def __init__(self):
        # Data 0 = 目标股票, Data 1 = 对冲指数
        self.stock_close = self.data0.close
        self.hedge_close = self.data1.close
        
        self.returns = []
        self.z_score = 0
        
        # 记录对冲仓位状态
        self.hedge_open = False
        
    def next(self):
        if len(self.stock_close) < self.p.window + 1:
            return
            
        # 计算股票的动量 Z-Score
        close_prices = list(self.stock_close.get(size=self.p.window + 1))
        returns = [(close_prices[i] - close_prices[i-1]) / close_prices[i-1] 
                   for i in range(1, len(close_prices))]
        
        mu = np.mean(returns)
        sigma = np.std(returns)
        if sigma > 0:
            self.z_score = (returns[-1] - mu) / sigma
        else:
            self.z_score = 0
        
        stock_pos = self.getposition(self.data0)
        hedge_pos = self.getposition(self.data1)
        
        # 交易逻辑
        if stock_pos.size == 0:
            # 动量突破：买入股票 + 做空指数
            if self.z_score > self.p.z_entry:
                cash = self.broker.getcash()
                stock_price = self.data0.close[0]
                hedge_price = self.data1.close[0]
                
                # 计算股票仓位 (使用一半资金，留一半做对冲保证金)
                stock_size = int(cash * self.p.trade_ratio * 0.5 / stock_price / 100) * 100
                
                if stock_size > 0:
                    # 买入股票
                    self.buy(data=self.data0, size=stock_size)
                    
                    # 做空等市值的指数
                    hedge_value = stock_size * stock_price * self.p.hedge_ratio
                    hedge_size = int(hedge_value / hedge_price / 100) * 100
                    
                    if hedge_size > 0:
                        self.sell(data=self.data1, size=hedge_size)
                        self.hedge_open = True
                    
                    if self.p.printlog:
                        print(f"[{self.data0.datetime.date()}] 🚀 动量追涨 + 对冲 Z={self.z_score:.2f}")
                        print(f"    做多股票: {stock_size}股 @ {stock_price:.2f}")
                        print(f"    做空指数: {hedge_size}股 @ {hedge_price:.2f}")
        else:
            # 动量衰竭：平仓
            if self.z_score < self.p.z_exit:
                if self.p.printlog:
                    print(f"[{self.data0.datetime.date()}] 🏆 动量衰竭平仓 Z={self.z_score:.2f}")
                    print(f"    平股票: {stock_pos.size}股 @ {self.data0.close[0]:.2f}")
                    if hedge_pos.size != 0:
                        print(f"    平指数: {hedge_pos.size}股 @ {self.data1.close[0]:.2f}")
                
                self.close(data=self.data0)
                if hedge_pos.size != 0:
                    self.close(data=self.data1)
                self.hedge_open = False


# ==================== 回测引擎 ====================

class TechMomentumEngine:
    """科技动量对冲回测引擎"""
    
    def __init__(self, cash=1_000_000, commission=0.0003, stamp_duty=0.001, slippage=0.002):
        self.cash = cash
        self.commission = commission
        self.stamp_duty = stamp_duty
        self.slippage = slippage
        
    def load_data(self, stock_path, hedge_path):
        """加载股票和指数数据"""
        stock_df = pd.read_csv(stock_path, parse_dates=['date'], index_col='date')
        hedge_df = pd.read_csv(hedge_path, parse_dates=['date'], index_col='date')
        
        # 对齐日期
        common_dates = stock_df.index.intersection(hedge_df.index)
        stock_df = stock_df.loc[common_dates]
        hedge_df = hedge_df.loc[common_dates]
        
        return stock_df, hedge_df
    
    def run_backtest(self, stock_path, hedge_path, stock_name, printlog=True):
        """运行对比回测"""
        print(f"\n{'='*60}")
        print(f"📊 回测标的: {stock_name}")
        print(f"{'='*60}")
        
        # 加载数据
        stock_df, hedge_df = self.load_data(stock_path, hedge_path)
        print(f"📅 数据范围: {stock_df.index[0].date()} ~ {stock_df.index[-1].date()}")
        print(f"📊 数据条数: {len(stock_df)}")
        
        results = {}
        
        # ========== 纯动量策略（无对冲）==========
        cerebro1 = bt.Cerebro()
        cerebro1.addstrategy(MomentumStrategy, printlog=printlog)
        cerebro1.broker.setcash(self.cash)
        cerebro1.broker.setcommission(commission=self.commission)
        
        stock_data = bt.feeds.PandasData(dataname=stock_df)
        cerebro1.adddata(stock_data)
        
        # 添加分析器
        cerebro1.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
        cerebro1.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        cerebro1.addanalyzer(bt.analyzers.Returns, _name='returns')
        
        print(f"\n🚀 纯动量策略（无对冲）...")
        result1 = cerebro1.run()[0]
        
        results['momentum'] = {
            'return': result1.analyzers.returns.get_analysis()['rtot'] * 100,
            'sharpe': result1.analyzers.sharpe.get_analysis().get('sharperatio', 0),
            'max_dd': result1.analyzers.drawdown.get_analysis()['max']['drawdown']
        }
        
        print(f"   收益率: {results['momentum']['return']:.2f}%")
        print(f"   夏普: {results['momentum']['sharpe']:.2f}")
        print(f"   最大回撤: {results['momentum']['max_dd']:.2f}%")
        
        # ========== 动量 + 对冲策略 ==========
        cerebro2 = bt.Cerebro()
        cerebro2.addstrategy(MomentumHedgeStrategy, printlog=printlog)
        cerebro2.broker.setcash(self.cash)
        cerebro2.broker.setcommission(commission=self.commission)
        
        # 关键：允许做空，不检查空头保证金
        cerebro2.broker.set_coc(True)  # Cash-on-Close模式
        
        stock_data2 = bt.feeds.PandasData(dataname=stock_df)
        hedge_data = bt.feeds.PandasData(dataname=hedge_df)
        
        cerebro2.adddata(stock_data2)  # Data 0 = 股票
        cerebro2.adddata(hedge_data)   # Data 1 = 指数
        
        cerebro2.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
        cerebro2.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        cerebro2.addanalyzer(bt.analyzers.Returns, _name='returns')
        
        print(f"\n🛡️ 动量 + 市场中性对冲...")
        result2 = cerebro2.run()[0]
        
        results['hedged'] = {
            'return': result2.analyzers.returns.get_analysis()['rtot'] * 100,
            'sharpe': result2.analyzers.sharpe.get_analysis().get('sharperatio', 0),
            'max_dd': result2.analyzers.drawdown.get_analysis()['max']['drawdown']
        }
        
        print(f"   收益率: {results['hedged']['return']:.2f}%")
        print(f"   夏普: {results['hedged']['sharpe']:.2f}")
        print(f"   最大回撤: {results['hedged']['max_dd']:.2f}%")
        
        return results


# ==================== 主程序 ====================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="科技动量对冲回测")
    parser.add_argument("--quiet", action="store_true", help="静默模式")
    args = parser.parse_args()
    
    engine = TechMomentumEngine()
    
    # 科技股列表
    stocks = [
        ("sz300308", "中际旭创"),
        ("sh601138", "工业富联"),
        ("sz002371", "北方华创"),
        ("sh688256", "寒武纪"),
    ]
    
    hedge_index = "sh000852"  # 中证1000指数
    
    all_results = {}
    
    for code, name in stocks:
        stock_path = f"data/{code}_daily.csv"
        hedge_path = f"data/{hedge_index}_daily.csv"
        
        if not os.path.exists(stock_path):
            print(f"❌ 数据文件不存在: {stock_path}")
            continue
        
        results = engine.run_backtest(
            stock_path, hedge_path, name,
            printlog=not args.quiet
        )
        all_results[name] = results
    
    # 汇总报告
    print("\n" + "="*60)
    print("📊 汇总报告：动量策略 vs 动量对冲策略")
    print("="*60)
    print(f"{'股票':<10} {'纯动量收益':>10} {'对冲收益':>10} {'纯动量回撤':>10} {'对冲回撤':>10}")
    print("-"*60)
    
    for name, results in all_results.items():
        mom = results['momentum']
        hed = results['hedged']
        print(f"{name:<10} {mom['return']:>9.2f}% {hed['return']:>9.2f}% {mom['max_dd']:>9.2f}% {hed['max_dd']:>9.2f}%")
