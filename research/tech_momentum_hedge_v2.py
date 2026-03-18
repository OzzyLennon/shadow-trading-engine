# -*- coding: utf-8 -*-
"""
科技动量 + 市场中性对冲回测引擎 V2
===================================

直接计算对冲后的收益，避免Backtrader做空限制
"""

import pandas as pd
import numpy as np
import os


class MomentumHedgeEngine:
    """动量对冲回测引擎"""
    
    def __init__(self, initial_capital=1_000_000, trade_ratio=0.3, hedge_ratio=1.0,
                 commission=0.0003, stamp_duty=0.001, slippage=0.002):
        self.initial_capital = initial_capital
        self.trade_ratio = trade_ratio
        self.hedge_ratio = hedge_ratio
        self.commission = commission
        self.stamp_duty = stamp_duty
        self.slippage = slippage
    
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
    
    def run_backtest(self, stock_path, hedge_path, z_entry=1.5, z_exit=0.0, printlog=False):
        """运行对比回测"""
        
        # 加载数据
        stock_df = pd.read_csv(stock_path, parse_dates=['date'])
        hedge_df = pd.read_csv(hedge_path, parse_dates=['date'])
        
        # 对齐日期
        merged = pd.merge(stock_df[['date', 'close']], 
                          hedge_df[['date', 'close']], 
                          on='date', suffixes=('_stock', '_hedge'))
        merged = merged.sort_values('date').reset_index(drop=True)
        
        stock_name = os.path.basename(stock_path).replace('_daily.csv', '')
        
        if printlog:
            print(f"\n{'='*60}")
            print(f"📊 回测标的: {stock_name}")
            print(f"📅 数据范围: {merged['date'].iloc[0].date()} ~ {merged['date'].iloc[-1].date()}")
            print(f"{'='*60}")
        
        # ========== 纯动量策略 ==========
        results_momentum = self._run_single_strategy(
            merged, use_hedge=False, z_entry=z_entry, z_exit=z_exit, printlog=printlog
        )
        
        # ========== 动量 + 对冲策略 ==========
        results_hedged = self._run_single_strategy(
            merged, use_hedge=True, z_entry=z_entry, z_exit=z_exit, printlog=printlog
        )
        
        return {
            'stock': stock_name,
            'momentum': results_momentum,
            'hedged': results_hedged
        }
    
    def _run_single_strategy(self, df, use_hedge, z_entry, z_exit, printlog):
        """运行单一策略回测"""
        
        capital = self.initial_capital
        cash = capital
        position = 0  # 股票持仓数量
        hedge_position = 0  # 对冲持仓数量
        
        trades = []
        equity_curve = [capital]
        
        stock_prices = df['close_stock'].values
        hedge_prices = df['close_hedge'].values
        dates = df['date'].values
        
        entry_price_stock = 0
        entry_price_hedge = 0
        
        for i in range(10, len(df)):
            current_stock_price = stock_prices[i]
            current_hedge_price = hedge_prices[i]
            current_date = dates[i]
            
            # 计算Z-Score
            z_score = self.calculate_z_score(stock_prices[:i+1])
            
            # 交易逻辑
            if position == 0:
                # 空仓状态，检查买入信号
                if z_score > z_entry:
                    # 计算买入金额
                    trade_amount = cash * self.trade_ratio
                    
                    # 买入股票（考虑滑点和手续费）
                    buy_price = current_stock_price * (1 + self.slippage)
                    shares = int(trade_amount / buy_price / 100) * 100
                    
                    if shares > 0:
                        cost = shares * buy_price * (1 + self.commission)
                        if cost <= cash:
                            position = shares
                            cash -= cost
                            entry_price_stock = buy_price
                            
                            if use_hedge:
                                # 做空等市值的指数
                                # 使用"虚拟单位"而非实际股数，模拟期货对冲效果
                                hedge_value = shares * buy_price * self.hedge_ratio
                                # 指数点位转换为虚拟单位（模拟ETF价格 = 指数/100）
                                virtual_etf_price = current_hedge_price / 100
                                hedge_units = int(hedge_value / virtual_etf_price / 100) * 100
                                hedge_position = -hedge_units  # 负数表示做空
                                entry_price_hedge = current_hedge_price
                            
                            if printlog:
                                action = "动量追涨 + 对冲" if use_hedge else "动量追涨"
                                print(f"[{pd.Timestamp(current_date).date()}] 🚀 {action} Z={z_score:.2f}")
                                print(f"    买入股票: {shares}股 @ {buy_price:.2f}")
                                if use_hedge and hedge_units > 0:
                                    print(f"    做空指数: {hedge_units}单位 @ {current_hedge_price:.2f} (虚拟)")
                            
                            trades.append({
                                'date': current_date,
                                'action': 'buy',
                                'shares': shares,
                                'price': buy_price,
                                'z_score': z_score
                            })
            else:
                # 持仓状态，检查卖出信号
                if z_score < z_exit:
                    # 卖出股票
                    sell_price = current_stock_price * (1 - self.slippage)
                    proceeds = position * sell_price * (1 - self.commission - self.stamp_duty)
                    
                    stock_pnl = (sell_price - entry_price_stock) * position
                    
                    cash += proceeds
                    
                    hedge_pnl = 0
                    if use_hedge and hedge_position != 0:
                        # 平仓对冲（做空的买入）
                        hedge_exit_price = current_hedge_price
                        # 做空盈利 = (入场价 - 出场价) / 100 * 虚拟单位数
                        # 每1点变动 = 1单位价值变化
                        hedge_pnl = (entry_price_hedge - hedge_exit_price) / 100 * abs(hedge_position)
                        cash += hedge_pnl
                        
                        if printlog:
                            print(f"[{pd.Timestamp(current_date).date()}] 🏆 动量衰竭平仓 Z={z_score:.2f}")
                            print(f"    股票盈亏: {stock_pnl:.2f}")
                            print(f"    对冲盈亏: {hedge_pnl:.2f}")
                    elif printlog:
                        print(f"[{pd.Timestamp(current_date).date()}] 🏆 动量衰竭平仓 Z={z_score:.2f}")
                        print(f"    股票盈亏: {stock_pnl:.2f}")
                    
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
            # 对冲价值 = 做空单位 * (入场价 - 当前价) / 100，负数表示做空
            if use_hedge and hedge_position != 0:
                # 做空盈利 = (入场价 - 当前价) / 100 * 单位数
                hedge_value = abs(hedge_position) * (entry_price_hedge - current_hedge_price) / 100
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
        
        # 计算夏普比率（简化版）
        returns = []
        for i in range(1, len(equity_curve)):
            daily_return = (equity_curve[i] - equity_curve[i-1]) / equity_curve[i-1]
            returns.append(daily_return)
        
        if len(returns) > 1:
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0
        else:
            sharpe = 0
        
        return {
            'final_equity': final_equity,
            'total_return': total_return,
            'max_drawdown': max_dd,
            'sharpe_ratio': sharpe,
            'trade_count': len([t for t in trades if t['action'] == 'sell']),
            'trades': trades
        }


# ==================== 主程序 ====================

if __name__ == "__main__":
    engine = MomentumHedgeEngine()
    
    # 科技股列表
    stocks = [
        ("sz300308", "中际旭创"),
        ("sh601138", "工业富联"),
        ("sz002371", "北方华创"),
        ("sh688256", "寒武纪"),
    ]
    
    hedge_index = "sh000852"  # 中证1000指数
    
    all_results = []
    
    print("=" * 70)
    print("🚀 科技动量 + 市场中性对冲回测")
    print("=" * 70)
    print(f"参数: Z买入={1.5}, Z卖出={0.0}, 仓位={30}%, 对冲比例={100}%")
    print("=" * 70)
    
    for code, name in stocks:
        stock_path = f"data/{code}_daily.csv"
        hedge_path = f"data/{hedge_index}_daily.csv"
        
        if not os.path.exists(stock_path):
            print(f"❌ 数据文件不存在: {stock_path}")
            continue
        
        result = engine.run_backtest(
            stock_path, hedge_path,
            z_entry=1.5, z_exit=0.0,
            printlog=True
        )
        all_results.append(result)
    
    # 汇总报告
    print("\n" + "=" * 70)
    print("📊 汇总报告：动量策略 vs 动量对冲策略")
    print("=" * 70)
    print(f"{'股票':<12} {'策略':<12} {'收益率':>10} {'最大回撤':>10} {'夏普':>8} {'交易次数':>8}")
    print("-" * 70)
    
    for result in all_results:
        name = result['stock']
        mom = result['momentum']
        hed = result['hedged']
        
        print(f"{name:<12} {'纯动量':<12} {mom['total_return']:>9.2f}% {mom['max_drawdown']:>9.2f}% {mom['sharpe_ratio']:>8.2f} {mom['trade_count']:>8}")
        print(f"{name:<12} {'动量对冲':<12} {hed['total_return']:>9.2f}% {hed['max_drawdown']:>9.2f}% {hed['sharpe_ratio']:>8.2f} {hed['trade_count']:>8}")
        print("-" * 70)
    
    # 统计改进
    print("\n" + "=" * 70)
    print("📈 对冲效果分析")
    print("=" * 70)
    print(f"{'股票':<12} {'收益变化':>12} {'回撤变化':>12} {'效果':>10}")
    print("-" * 70)
    
    for result in all_results:
        name = result['stock']
        mom = result['momentum']
        hed = result['hedged']
        
        return_change = hed['total_return'] - mom['total_return']
        dd_change = hed['max_drawdown'] - mom['max_drawdown']
        
        if dd_change < -1:  # 回撤减少超过1%
            effect = "✅ 有效"
        elif dd_change > 1:  # 回撤增加超过1%
            effect = "❌ 负面"
        else:
            effect = "➖ 中性"
        
        print(f"{name:<12} {return_change:>+11.2f}% {dd_change:>+11.2f}% {effect:>10}")
