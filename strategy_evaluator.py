#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略性能评估器 - 末位淘汰制
===========================
每周运行，评估策略表现，淘汰表现差的策略

淘汰条件:
- 胜率 < 40%
- 累计收益 < -5%
- 连续亏损 > 5笔

作者: AI 量化研究助手
日期: 2026-03-20
"""

import os
import json
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROMOTED_FILE = os.path.join(SCRIPT_DIR, "promoted_strategies.json")
PERFORMANCE_FILE = os.path.join(SCRIPT_DIR, "strategy_performance.json")
DEMOTE_FILE = os.path.join(SCRIPT_DIR, "demoted_strategies.json")

# 淘汰阈值
MIN_WIN_RATE = 0.40
MIN_TOTAL_RETURN = -0.05
MAX_CONSECUTIVE_LOSSES = 5

def load_performance():
    """加载性能数据"""
    if not os.path.exists(PERFORMANCE_FILE):
        return {}
    with open(PERFORMANCE_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_promoted():
    """加载晋级策略"""
    if not os.path.exists(PROMOTED_FILE):
        return {}
    with open(PROMOTED_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_promoted(data):
    """保存晋级策略"""
    with open(PROMOTED_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_demoted(demoted_list):
    """保存淘汰记录"""
    data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "demoted": demoted_list
    }
    with open(PERFORMANCE_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def evaluate():
    """评估策略"""
    print("=" * 60)
    print("📊 策略性能评估 - 末位淘汰")
    print("=" * 60)
    
    performance = load_performance()
    promoted = load_promoted()
    
    if not promoted.get('strategies'):
        print("⚠️ 无策略需要评估")
        return
    
    strategies = promoted['strategies']
    perf_data = performance.get('strategies', {})
    
    demoted = []
    kept = []
    
    print(f"\n📋 评估 {len(strategies)} 个策略:")
    print("-" * 60)
    
    for s in strategies:
        factor_name = s['factor_name']
        strat_perf = perf_data.get(factor_name, {})
        
        trades = strat_perf.get('trades', 0)
        wins = strat_perf.get('wins', 0)
        losses = strat_perf.get('losses', 0)
        total_return = strat_perf.get('total_return', 0)
        
        win_rate = wins / trades if trades > 0 else 0
        
        # 淘汰判断
        reasons = []
        
        if trades > 0 and win_rate < MIN_WIN_RATE:
            reasons.append(f"胜率过低({win_rate:.1%}<{MIN_WIN_RATE:.0%})")
        
        if total_return < MIN_TOTAL_RETURN:
            reasons.append(f"累计亏损({total_return:.2%}<{MIN_TOTAL_RETURN:.0%})")
        
        if losses >= MAX_CONSECUTIVE_LOSSES and wins == 0:
            reasons.append(f"连续亏损({losses}笔)")
        
        if reasons:
            status = "❌ 淘汰"
            demoted.append({
                'factor_name': factor_name,
                'strategy_name': s.get('strategy_name', ''),
                'win_rate': win_rate,
                'total_return': total_return,
                'reasons': reasons
            })
        else:
            status = "✅ 保留"
            kept.append(s)
        
        print(f"{status} {factor_name}")
        print(f"   胜率: {win_rate:.1%} ({wins}胜/{losses}负/{trades}笔)")
        print(f"   累计收益: {total_return:.2%}")
        if reasons:
            print(f"   淘汰原因: {', '.join(reasons)}")
    
    # 更新晋级列表
    promoted['strategies'] = kept
    promoted['last_evaluation'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    promoted['demoted_count'] = len(demoted)
    
    save_promoted(promoted)
    
    if demoted:
        save_demoted(demoted)
    
    print("\n" + "=" * 60)
    print(f"📊 评估完成: 保留{len(kept)}个, 淘汰{len(demoted)}个")
    print("=" * 60)

if __name__ == "__main__":
    evaluate()
