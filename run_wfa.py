#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
前进式分析测试脚本
==================
运行参数网格搜索，寻找均值回归策略的最优参数

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

# 添加路径
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

def walk_forward_analysis(
    symbol='sh600000',
    data_path='./research/data',
    train_months=12,
    test_months=6,
    step_months=3
):
    """
    前进式分析
    
    Args:
        symbol: 股票代码
        train_months: 训练窗口（月）
        test_months: 测试窗口（月）
        step_months: 滚动步长（月）
    """
    print("=" * 60)
    print("📊 前进式分析 (Walk-Forward Analysis)")
    print("=" * 60)
    print(f"股票: {symbol}")
    print(f"训练窗口: {train_months}个月")
    print(f"测试窗口: {test_months}个月")
    print(f"滚动步长: {step_months}个月")
    print("=" * 60)
    
    # 参数网格
    param_grid = {
        'z_threshold': [-2.0, -1.5, -1.0],
        'window': [5, 10, 15],
        'trade_ratio': [0.3]
    }
    
    # 生成参数组合
    param_names = list(param_grid.keys())
    param_values = list(param_grid.values())
    combinations = list(product(*param_values))
    
    print(f"\n📋 参数网格: {len(combinations)} 种组合")
    print(f"   z_threshold: {param_grid['z_threshold']}")
    print(f"   window: {param_grid['window']}")
    print(f"   trade_ratio: {param_grid['trade_ratio']}")
    
    # 时间窗口设置
    start_year = 2022
    end_year = 2024
    
    # 转换为天数（近似）
    train_days = train_months * 21  # 每月约21个交易日
    test_days = test_months * 21
    step_days = step_months * 21
    
    # 加载数据获取日期范围
    data_file = os.path.join(data_path, f"{symbol}_daily.csv")
    df = pd.read_csv(data_file)
    df['date'] = pd.to_datetime(df['date'])
    trading_days = df['date'].tolist()
    
    # 生成窗口
    windows = []
    i = 0
    while i + train_days + test_days <= len(trading_days):
        train_start = trading_days[i].strftime('%Y-%m-%d')
        train_end = trading_days[i + train_days - 1].strftime('%Y-%m-%d')
        test_start = trading_days[i + train_days].strftime('%Y-%m-%d')
        test_end = trading_days[i + train_days + test_days - 1].strftime('%Y-%m-%d')
        
        windows.append({
            'train_start': train_start,
            'train_end': train_end,
            'test_start': test_start,
            'test_end': test_end
        })
        
        i += step_days
    
    print(f"\n📅 生成 {len(windows)} 个前进式窗口\n")
    
    # 存储结果
    all_results = []
    test_returns = []
    
    # 遍历每个窗口
    for w_idx, window in enumerate(windows):
        print(f"\n{'='*60}")
        print(f"📊 窗口 {w_idx+1}/{len(windows)}")
        print(f"   训练: {window['train_start']} ~ {window['train_end']}")
        print(f"   测试: {window['test_start']} ~ {window['test_end']}")
        print(f"{'='*60}")
        
        # 在训练集上寻找最优参数
        best_params = None
        best_sharpe = -999
        
        print(f"\n🔍 训练集参数优化...")
        
        for combo in combinations:
            params = dict(zip(param_names, combo))
            
            try:
                perf = run_single_backtest(
                    symbol,
                    window['train_start'],
                    window['train_end'],
                    params
                )
                
                sharpe = perf.get('sharpe_ratio') or 0
                
                if sharpe > best_sharpe:
                    best_sharpe = sharpe
                    best_params = params
                    
            except Exception as e:
                pass
        
        if best_params is None:
            best_params = dict(zip(param_names, combinations[0]))
        
        print(f"✅ 最优参数: {best_params}, 夏普={best_sharpe:.2f}")
        
        # 在测试集上验证
        print(f"\n📊 测试集验证...")
        
        try:
            test_perf = run_single_backtest(
                symbol,
                window['test_start'],
                window['test_end'],
                best_params
            )
            
            test_return = test_perf.get('total_return') or 0
            test_sharpe = test_perf.get('sharpe_ratio') or 0
            
            print(f"📈 测试收益: {test_return:.2f}%")
            print(f"⚡ 测试夏普: {test_sharpe:.2f}")
            
            test_returns.append(test_return)
            
            all_results.append({
                'window': window,
                'best_params': best_params,
                'train_sharpe': best_sharpe,
                'test_return': test_return,
                'test_sharpe': test_sharpe
            })
            
        except Exception as e:
            print(f"❌ 测试失败: {e}")
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("📊 前进式分析汇总")
    print("=" * 60)
    
    if test_returns:
        avg_return = np.mean(test_returns)
        std_return = np.std(test_returns)
        win_rate = sum(1 for r in test_returns if r > 0) / len(test_returns) * 100
        
        # 计算累计收益
        cumulative = 1
        for r in test_returns:
            cumulative *= (1 + r/100)
        cumulative = (cumulative - 1) * 100
        
        print(f"📅 总窗口数: {len(test_returns)}")
        print(f"📈 平均测试收益: {avg_return:.2f}%")
        print(f"📉 收益标准差: {std_return:.2f}%")
        print(f"🎯 测试胜率: {win_rate:.1f}%")
        print(f"💰 累计收益: {cumulative:.2f}%")
        
        # 计算 OOS 夏普
        if std_return > 0:
            oos_sharpe = avg_return / std_return * np.sqrt(2)
            print(f"⚡ 样本外夏普: {oos_sharpe:.2f}")
        
        # 过拟合概率 (PBO)
        train_sharpes = [r['train_sharpe'] for r in all_results]
        test_sharpes = [r['test_sharpe'] for r in all_results]
        
        pbo = sum(1 for tr, te in zip(train_sharpes, test_sharpes) if tr > te) / len(all_results)
        print(f"⚠️ 过拟合概率 (PBO): {pbo*100:.1f}%")
        
        if pbo > 0.7:
            print("   ⚠️ 警告: 过拟合概率很高！")
        elif pbo > 0.5:
            print("   ⚠️ 注意: 存在一定过拟合风险")
        else:
            print("   ✅ 策略泛化能力良好")
    
    # 保存结果
    output_path = os.path.join(data_path, "wfa_results.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump({
            'summary': {
                'total_windows': len(test_returns),
                'avg_return': avg_return if test_returns else 0,
                'win_rate': win_rate if test_returns else 0,
                'pbo': pbo if test_returns else 0
            },
            'windows': all_results
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 结果已保存: {output_path}")
    print("=" * 60)

if __name__ == "__main__":
    walk_forward_analysis(
        symbol='sh600000',
        data_path='./research/data',
        train_months=12,
        test_months=6,
        step_months=3
    )
