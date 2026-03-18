# -*- coding: utf-8 -*-
"""
动态Beta对冲回测引擎
====================

核心功能：
1. 动态计算Beta：每次买入时用过去60天数据计算回归系数
2. 动态配平：根据Beta调整对冲比例
3. 基准错配纠正：自动选择最优对冲基准
"""

import pandas as pd
import numpy as np
import os


class DynamicBetaHedgeEngine:
    """动态Beta对冲回测引擎"""
    
    # 股票 → 对冲基准映射
    HEDGE_BENCHMARK = {
        'sz300308': 'sh000852',  # 中际旭创 → 中证1000 (中小盘科技)
        'sh601138': 'sh000300',  # 工业富联 → 沪深300 (大盘蓝筹)
        'sz002371': 'sh000852',  # 北方华创 → 中证1000 (中小盘科技)
        'sh688256': 'sh000852',  # 寒武纪 → 中证1000 (科创中小盘)
    }
    
    BENCHMARK_NAMES = {
        'sh000300': '沪深300',
        'sh000852': '中证1000',
    }
    
    def __init__(self, initial_capital=1_000_000, trade_ratio=0.3,
                 commission=0.0003, stamp_duty=0.001, slippage=0.002,
                 beta_window=60):
        self.initial_capital = initial_capital
        self.trade_ratio = trade_ratio
        self.commission = commission
        self.stamp_duty = stamp_duty
        self.slippage = slippage
        self.beta_window = beta_window
    
    def calculate_beta(self, stock_returns, benchmark_returns):
        """
        计算股票相对于基准的Beta值
        
        Beta = Cov(R_stock, R_benchmark) / Var(R_benchmark)
        """
        if len(stock_returns) < self.beta_window or len(benchmark_returns) < self.beta_window:
            return 1.0  # 默认Beta=1
        
        # 取最近N天的收益率
        stock_ret = np.array(stock_returns[-self.beta_window:])
        bench_ret = np.array(benchmark_returns[-self.beta_window:])
        
        # 计算协方差和方差
        covariance = np.cov(stock_ret, bench_ret)[0, 1]
        variance = np.var(bench_ret)
        
        if variance == 0:
            return 1.0
        
        beta = covariance / variance
        
        # 限制Beta范围 [0.3, 2.5]
        return max(0.3, min(2.5, beta))
    
    def calculate_z_score(self, prices, window=10):
        """计算Z-Score"""
        if len(prices) < window + 1:
            return 0
        
        recent_prices = prices[-(window+1):]
        returns = [(recent_prices[i] - recent_prices[i-1]) / recent_prices[i-1] 
                   for i in range(1, len(recent_prices))]
        
        if len(returns) < 2:
            return 0
        
        mu = np.mean(returns)
        sigma = np.std(returns)
        if sigma == 0:
            return 0
        
        return (returns[-1] - mu) / sigma
    
    def run_backtest(self, stock_path, z_entry=1.5, z_exit=0.0, printlog=False):
        """运行动态Beta对冲回测"""
        
        # 解析股票代码
        stock_code = os.path.basename(stock_path).replace('_daily.csv', '')
        
        # 确定对冲基准
        benchmark_code = self.HEDGE_BENCHMARK.get(stock_code, 'sh000852')
        benchmark_path = f"data/{benchmark_code}_daily.csv"
        
        if not os.path.exists(benchmark_path):
            print(f"❌ 基准数据不存在: {benchmark_path}")
            return None
        
        # 加载数据
        stock_df = pd.read_csv(stock_path, parse_dates=['date'])
        bench_df = pd.read_csv(benchmark_path, parse_dates=['date'])
        
        # 对齐日期
        merged = pd.merge(stock_df[['date', 'close']], 
                          bench_df[['date', 'close']], 
                          on='date', suffixes=('_stock', '_bench'))
        merged = merged.sort_values('date').reset_index(drop=True)
        
        # 计算收益率序列（用于Beta计算）
        merged['stock_return'] = merged['close_stock'].pct_change()
        merged['bench_return'] = merged['close_bench'].pct_change()
        merged = merged.dropna()
        
        if printlog:
            print(f"\n{'='*70}")
            print(f"📊 回测标的: {stock_code}")
            print(f"📅 数据范围: {merged['date'].iloc[0].date()} ~ {merged['date'].iloc[-1].date()}")
            print(f"🎯 对冲基准: {self.BENCHMARK_NAMES.get(benchmark_code, benchmark_code)}")
            print(f"{'='*70}")
        
        # ========== 纯动量策略（无对冲）==========
        results_momentum = self._run_single_strategy(
            merged, use_hedge=False, 
            z_entry=z_entry, z_exit=z_exit, 
            printlog=printlog
        )
        
        # ========== 动态Beta对冲策略 ==========
        results_hedged = self._run_single_strategy(
            merged, use_hedge=True,
            z_entry=z_entry, z_exit=z_exit,
            printlog=printlog,
            stock_code=stock_code,
            benchmark_code=benchmark_code
        )
        
        return {
            'stock': stock_code,
            'benchmark': benchmark_code,
            'momentum': results_momentum,
            'hedged': results_hedged
        }
    
    def _run_single_strategy(self, df, use_hedge, z_entry, z_exit, printlog, 
                              stock_code=None, benchmark_code=None):
        """运行单一策略回测"""
        
        capital = self.initial_capital
        cash = capital
        position = 0
        hedge_position = 0
        
        trades = []
        equity_curve = [capital]
        beta_history = []
        
        stock_prices = df['close_stock'].values
        bench_prices = df['close_bench'].values
        stock_returns = df['stock_return'].values
        bench_returns = df['bench_return'].values
        dates = df['date'].values
        
        entry_price_stock = 0
        entry_price_bench = 0
        current_beta = 1.0
        
        for i in range(max(10, self.beta_window), len(df)):
            current_stock_price = stock_prices[i]
            current_bench_price = bench_prices[i]
            current_date = dates[i]
            
            # 计算Z-Score
            z_score = self.calculate_z_score(stock_prices[:i+1])
            
            # 交易逻辑
            if position == 0:
                if z_score > z_entry:
                    # 计算动态Beta
                    if use_hedge:
                        current_beta = self.calculate_beta(
                            stock_returns[:i+1].tolist(),
                            bench_returns[:i+1].tolist()
                        )
                        beta_history.append({
                            'date': current_date,
                            'beta': current_beta
                        })
                    
                    # 买入金额
                    trade_amount = cash * self.trade_ratio
                    
                    # 买入股票
                    buy_price = current_stock_price * (1 + self.slippage)
                    shares = int(trade_amount / buy_price / 100) * 100
                    
                    if shares > 0:
                        cost = shares * buy_price * (1 + self.commission)
                        if cost <= cash:
                            position = shares
                            cash -= cost
                            entry_price_stock = buy_price
                            
                            if use_hedge:
                                # 动态对冲：做空 (股票市值 × Beta) 的指数
                                hedge_value = shares * buy_price * current_beta
                                # 指数点位转换为虚拟单位
                                virtual_etf_price = current_bench_price / 100
                                hedge_units = int(hedge_value / virtual_etf_price / 100) * 100
                                hedge_position = -hedge_units
                                entry_price_bench = current_bench_price
                            
                            if printlog:
                                action = f"动量追涨 + Beta对冲 (β={current_beta:.2f})" if use_hedge else "动量追涨"
                                print(f"[{pd.Timestamp(current_date).date()}] 🚀 {action} Z={z_score:.2f}")
                                print(f"    买入股票: {shares}股 @ {buy_price:.2f}")
                                if use_hedge and hedge_units > 0:
                                    print(f"    做空指数: {hedge_units}单位 @ {current_bench_price:.2f}")
                                    print(f"    对冲比例: {current_beta:.2f}x (市值{shares * buy_price:.0f} → 对冲{hedge_value:.0f})")
                            
                            trades.append({
                                'date': current_date,
                                'action': 'buy',
                                'shares': shares,
                                'price': buy_price,
                                'z_score': z_score,
                                'beta': current_beta if use_hedge else None
                            })
            else:
                if z_score < z_exit:
                    # 卖出股票
                    sell_price = current_stock_price * (1 - self.slippage)
                    proceeds = position * sell_price * (1 - self.commission - self.stamp_duty)
                    
                    stock_pnl = (sell_price - entry_price_stock) * position
                    
                    cash += proceeds
                    
                    hedge_pnl = 0
                    if use_hedge and hedge_position != 0:
                        hedge_exit_price = current_bench_price
                        hedge_pnl = (entry_price_bench - hedge_exit_price) / 100 * abs(hedge_position)
                        cash += hedge_pnl
                        
                        if printlog:
                            print(f"[{pd.Timestamp(current_date).date()}] 🏆 动量衰竭平仓 Z={z_score:.2f}")
                            print(f"    股票盈亏: {stock_pnl:+.2f}")
                            print(f"    对冲盈亏: {hedge_pnl:+.2f}")
                            print(f"    合计盈亏: {stock_pnl + hedge_pnl:+.2f}")
                    elif printlog:
                        print(f"[{pd.Timestamp(current_date).date()}] 🏆 动量衰竭平仓 Z={z_score:.2f}")
                        print(f"    股票盈亏: {stock_pnl:+.2f}")
                    
                    trades.append({
                        'date': current_date,
                        'action': 'sell',
                        'shares': position,
                        'price': sell_price,
                        'z_score': z_score,
                        'stock_pnl': stock_pnl,
                        'hedge_pnl': hedge_pnl if use_hedge else 0
                    })
                    
                    position = 0
                    hedge_position = 0
            
            # 计算当前权益
            stock_value = position * current_stock_price if position > 0 else 0
            if use_hedge and hedge_position != 0:
                hedge_value = abs(hedge_position) * (entry_price_bench - current_bench_price) / 100
            else:
                hedge_value = 0
            total_equity = cash + stock_value + hedge_value
            equity_curve.append(total_equity)
        
        # 计算绩效指标
        final_equity = equity_curve[-1]
        total_return = (final_equity - self.initial_capital) / self.initial_capital * 100
        
        # 计算最大回撤
        peak = self.initial_capital
        max_dd = 0
        for equity in equity_curve:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100
            if dd > max_dd:
                max_dd = dd
        
        # 计算夏普比率
        returns = []
        for i in range(1, len(equity_curve)):
            daily_return = (equity_curve[i] - equity_curve[i-1]) / equity_curve[i-1]
            returns.append(daily_return)
        
        if len(returns) > 1:
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0
        else:
            sharpe = 0
        
        # 计算平均Beta
        avg_beta = np.mean([b['beta'] for b in beta_history]) if beta_history else 1.0
        
        return {
            'final_equity': final_equity,
            'total_return': total_return,
            'max_drawdown': max_dd,
            'sharpe_ratio': sharpe,
            'trade_count': len([t for t in trades if t['action'] == 'sell']),
            'avg_beta': avg_beta,
            'trades': trades,
            'beta_history': beta_history
        }


# ==================== 主程序 ====================

if __name__ == "__main__":
    engine = DynamicBetaHedgeEngine()
    
    # 科技股列表
    stocks = [
        ("sz300308", "中际旭创"),
        ("sh601138", "工业富联"),
        ("sz002371", "北方华创"),
        ("sh688256", "寒武纪"),
    ]
    
    all_results = []
    
    print("=" * 70)
    print("🚀 动态Beta对冲回测")
    print("=" * 70)
    print(f"参数: Z买入={1.5}, Z卖出={0.0}, 仓位={30}%")
    print(f"特色: 动态Beta计算 (窗口=60天) + 基准自动选择")
    print("=" * 70)
    
    for code, name in stocks:
        stock_path = f"data/{code}_daily.csv"
        
        if not os.path.exists(stock_path):
            print(f"❌ 数据文件不存在: {stock_path}")
            continue
        
        result = engine.run_backtest(
            stock_path,
            z_entry=1.5, z_exit=0.0,
            printlog=True
        )
        if result:
            all_results.append(result)
    
    # 汇总报告
    print("\n" + "=" * 70)
    print("📊 汇总报告：纯动量 vs 动态Beta对冲")
    print("=" * 70)
    print(f"{'股票':<12} {'基准':<10} {'策略':<12} {'收益':>10} {'回撤':>10} {'夏普':>8} {'平均Beta':>10}")
    print("-" * 70)
    
    for result in all_results:
        name = result['stock']
        bench = result['benchmark']
        mom = result['momentum']
        hed = result['hedged']
        
        print(f"{name:<12} {bench:<10} {'纯动量':<12} {mom['total_return']:>9.2f}% {mom['max_drawdown']:>9.2f}% {mom['sharpe_ratio']:>8.2f} {'-':>10}")
        print(f"{name:<12} {bench:<10} {'Beta对冲':<12} {hed['total_return']:>9.2f}% {hed['max_drawdown']:>9.2f}% {hed['sharpe_ratio']:>8.2f} {hed['avg_beta']:>10.2f}")
        print("-" * 70)
    
    # 对比分析
    print("\n" + "=" * 70)
    print("📈 Beta对冲效果分析")
    print("=" * 70)
    print(f"{'股票':<12} {'基准选择':<10} {'收益变化':>12} {'回撤变化':>12} {'效果':>10}")
    print("-" * 70)
    
    for result in all_results:
        name = result['stock']
        bench = result['benchmark']
        mom = result['momentum']
        hed = result['hedged']
        
        return_change = hed['total_return'] - mom['total_return']
        dd_change = hed['max_drawdown'] - mom['max_drawdown']
        
        if dd_change < -1:
            effect = "✅ 有效"
        elif dd_change > 1:
            effect = "❌ 负面"
        else:
            effect = "➖ 中性"
        
        bench_name = engine.BENCHMARK_NAMES.get(bench, bench)
        print(f"{name:<12} {bench_name:<10} {return_change:>+11.2f}% {dd_change:>+11.2f}% {effect:>10}")
