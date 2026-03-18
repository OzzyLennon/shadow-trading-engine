#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
蓝筹组合前进式分析 (Walk-Forward Analysis)
============================================
对5只蓝筹股分别运行WFA，验证策略泛化能力

作者: AI 量化研究助手
日期: 2026-03-18
"""

import os
import sys
import pandas as pd
import numpy as np
from itertools import product
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from research.backtest_engine import BacktestEngine, ZScoreStrategy

def run_single_backtest(symbol, start_date, end_date, params):
    """运行单次回测"""
    engine = BacktestEngine(
        initial_cash=1000000,
        commission=0.00025,
        stamp_duty=0.001,
        slippage=0.002
    )
    
    engine.load_data(symbol, start_date=start_date, end_date=end_date)
    engine.add_strategy(ZScoreStrategy, **params, printlog=False)
    perf = engine.run()
    
    return perf

def run_wfa_for_stock(symbol, name, data_path='./research/data'):
    """对单只股票运行前进式分析"""
    print(f"\n{'='*60}")
    print(f"📊 {name} ({symbol}) - 前进式分析")
    print(f"{'='*60}")
    
    # 参数网格 (保持 z_threshold = -1.5 为核心)
    param_grid = {
        'z_threshold': [-2.0, -1.5, -1.0],
        'window': [5, 10, 15],
        'trade_ratio': [0.3]
    }
    
    # 生成参数组合
    param_names = list(param_grid.keys())
    param_values = list(param_grid.values())
    combinations = list(product(*param_values))
    
    # 加载数据获取交易日历
    data_file = os.path.join(data_path, f"{symbol}_daily.csv")
    df = pd.read_csv(data_file)
    df['date'] = pd.to_datetime(df['date'])
    trading_days = df['date'].tolist()
    
    # 时间窗口设置
    train_days = 12 * 21  # 12个月
    test_days = 6 * 21    # 6个月
    step_days = 3 * 21    # 3个月滚动
    
    # 生成窗口
    windows = []
    i = 0
    while i + train_days + test_days <= len(trading_days):
        windows.append({
            'train_start': trading_days[i].strftime('%Y-%m-%d'),
            'train_end': trading_days[i + train_days - 1].strftime('%Y-%m-%d'),
            'test_start': trading_days[i + train_days].strftime('%Y-%m-%d'),
            'test_end': trading_days[i + train_days + test_days - 1].strftime('%Y-%m-%d')
        })
        i += step_days
    
    print(f"📅 生成 {len(windows)} 个前进式窗口")
    
    # 存储结果
    all_results = []
    test_returns = []
    
    for w_idx, window in enumerate(windows):
        print(f"\n  窗口 {w_idx+1}/{len(windows)}: {window['test_start']} ~ {window['test_end']}")
        
        # 训练集参数优化
        best_params = None
        best_sharpe = -999
        
        for combo in combinations:
            params = dict(zip(param_names, combo))
            try:
                perf = run_single_backtest(symbol, window['train_start'], window['train_end'], params)
                sharpe = perf.get('sharpe_ratio') or 0
                if sharpe > best_sharpe:
                    best_sharpe = sharpe
                    best_params = params
            except:
                pass
        
        if best_params is None:
            best_params = dict(zip(param_names, combinations[0]))
        
        # 测试集验证
        try:
            test_perf = run_single_backtest(symbol, window['test_start'], window['test_end'], best_params)
            test_return = test_perf.get('total_return') or 0
            test_returns.append(test_return)
            
            all_results.append({
                'window': window,
                'best_params': best_params,
                'test_return': test_return
            })
            
            print(f"    最优: z={best_params['z_threshold']}, w={best_params['window']}")
            print(f"    测试收益: {test_return:.2f}%")
            
        except Exception as e:
            print(f"    ❌ 测试失败: {e}")
    
    # 汇总
    if test_returns:
        avg_return = np.mean(test_returns)
        win_rate = sum(1 for r in test_returns if r > 0) / len(test_returns) * 100
        
        # 累计收益
        cumulative = 1
        for r in test_returns:
            cumulative *= (1 + r/100)
        cumulative = (cumulative - 1) * 100
        
        print(f"\n  📊 {name} WFA汇总:")
        print(f"     平均测试收益: {avg_return:.2f}%")
        print(f"     测试胜率: {win_rate:.1f}%")
        print(f"     累计收益: {cumulative:.2f}%")
        
        return {
            'symbol': symbol,
            'name': name,
            'windows': len(test_returns),
            'avg_return': avg_return,
            'win_rate': win_rate,
            'cumulative': cumulative,
            'results': all_results
        }
    
    return None

if __name__ == "__main__":
    # 5只蓝筹股
    portfolio = [
        ('sh600000', '浦发银行'),
        ('sh601318', '中国平安'),
        ('sh600030', '中信证券'),
        ('sh600519', '贵州茅台'),
        ('sh601088', '中国神华')
    ]
    
    print("=" * 60)
    print("📊 蓝筹组合前进式分析 (Walk-Forward Analysis)")
    print("=" * 60)
    print("训练窗口: 12个月 | 测试窗口: 6个月 | 滚动步长: 3个月")
    print("=" * 60)
    
    # 对每只股票运行WFA
    all_stock_results = []
    
    for code, name in portfolio:
        result = run_wfa_for_stock(code, name, './research/data')
        if result:
            all_stock_results.append(result)
    
    # 组合汇总
    print("\n" + "=" * 60)
    print("📊 组合WFA汇总报告")
    print("=" * 60)
    
    if all_stock_results:
        avg_returns = [r['avg_return'] for r in all_stock_results]
        avg_win_rates = [r['win_rate'] for r in all_stock_results]
        cumulatives = [r['cumulative'] for r in all_stock_results]
        
        print(f"\n📈 组合平均测试收益: {np.mean(avg_returns):.2f}%")
        print(f"🎯 组合平均窗口胜率: {np.mean(avg_win_rates):.1f}%")
        print(f"💰 组合平均累计收益: {np.mean(cumulatives):.2f}%")
        
        # 盈利股票数
        profit_stocks = sum(1 for r in all_stock_results if r['avg_return'] > 0)
        print(f"✅ WFA盈利股票数: {profit_stocks}/5")
        
        # 详细表格
        print("\n📋 详细结果:")
        print(f"{'股票':<12} {'窗口数':>8} {'平均收益':>10} {'窗口胜率':>10} {'累计收益':>10}")
        print("-" * 60)
        for r in all_stock_results:
            print(f"{r['name']:<12} {r['windows']:>8} {r['avg_return']:>9.2f}% {r['win_rate']:>9.1f}% {r['cumulative']:>9.2f}%")
    
    # 保存结果
    output_path = './research/data/wfa_portfolio_results.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_stock_results, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n💾 结果已保存: {output_path}")
    print("=" * 60)
