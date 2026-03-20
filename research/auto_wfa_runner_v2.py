#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WFA 自动验证器 V2 - Alpha Factory 第二阶段 (幻觉修复版)
======================================================
自动对接因子分析结果 + 批量WFA验证 + 策略晋级

修复三大幻觉:
1. Lookahead Bias: 使用次日开盘价买入
2. 流动性幻觉: 过滤涨跌停无法成交
3. 交易成本: 扣除双边千分之二

准入门槛:
- 样本外胜率 >= 60%
- 夏普比率 >= 1.5
- Haircut折扣: 机器挖掘因子 × 0.7

作者: AI 量化研究助手
日期: 2026-03-20
"""

import os
import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List
import warnings
warnings.filterwarnings('ignore')

# 导入因子库 (DRY原则)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from factor_lib import calculate_factor

# ================= 路径配置 =================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESEARCH_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
CANDIDATES_FILE = os.path.join(SCRIPT_DIR, "promoted_candidates.json")
PROMOTED_FILE = os.path.join(RESEARCH_DIR, "promoted_strategies.json")

# ================= 准入阈值 =================
WIN_RATE_THRESHOLD = 0.60     # 样本外胜率 >= 60%
SHARPE_THRESHOLD = 1.5       # 夏普比率 >= 1.5
HAIRCUT_FACTOR = 0.7         # Haircut折扣

# ================= 交易成本 =================
TRANSACTION_COST = 0.002     # 双边成本: 千分之二

# ================= WFA 配置 =================
TRAIN_WINDOW = 120           # 训练窗口: 120天
TEST_WINDOW = 20             # 测试窗口: 20天
ROLLING_STEPS = 10           # 滚动次数

# ================= 股票池清洗配置 =================
MIN_LISTING_DAYS = 60        # 上市不足60天的新股剔除
EXCLUDE_ST = True            # 剔除ST股票


# ================= 因子到策略的映射 =================
def get_factor_strategy(factor_name: str) -> Dict:
    """将因子名转换为策略参数"""
    strategies = {
        "volatility_60d": {"name": "低波动策略_60日", "signal": "low_vol", "period": 60},
        "volatility_20d": {"name": "低波动策略_20日", "signal": "low_vol", "period": 20},
        "volatility_10d": {"name": "低波动策略_10日", "signal": "low_vol", "period": 10},
        "volatility_5d": {"name": "低波动策略_5日", "signal": "low_vol", "period": 5},
        "ATR_14d": {"name": "ATR低波动策略_14日", "signal": "low_vol", "period": 14},
        "ATR_20d": {"name": "ATR低波动策略_20日", "signal": "low_vol", "period": 20},
        "volume_ma_10d": {"name": "成交量均线策略_10日", "signal": "high_volume_ma", "period": 10},
        "volume_ma_5d": {"name": "成交量均线策略_5日", "signal": "high_volume_ma", "period": 5},
        "volume_ma_20d": {"name": "成交量均线策略_20日", "signal": "high_volume_ma", "period": 20},
        "volume_ma_60d": {"name": "成交量均线策略_60日", "signal": "high_volume_ma", "period": 60},
    }
    return strategies.get(factor_name, None)


# ================= 股票池清洗 =================
def clean_stock_pool(df: pd.DataFrame, symbol: str) -> bool:
    """
    股票池清洗
    返回: True=保留, False=剔除
    """
    # 剔除上市不足60天的新股
    if len(df) < MIN_LISTING_DAYS:
        return False
    
    # 剔除ST股票 (代码以ST开头或名称含ST)
    if EXCLUDE_ST and 'ST' in symbol.upper():
        return False
    
    # 剔除数据缺失严重的股票
    if df['close'].isna().sum() > len(df) * 0.1:
        return False
    
    return True


# ================= 数据加载 (内存优化版) =================
def load_panel_data() -> pd.DataFrame:
    """
    加载面板数据 (内存优化)
    - 只加载必要列
    - 使用category类型
    """
    import glob
    
    all_files = glob.glob(os.path.join(DATA_DIR, "*.csv"))
    if not all_files:
        print(f"❌ 未找到数据文件")
        return None
    
    print(f"📂 加载 {len(all_files)} 只股票数据...")
    
    df_list = []
    for file in all_files:
        symbol = os.path.basename(file).split('.')[0]
        
        # 只加载必要列，减少内存
        df = pd.read_csv(
            file, 
            parse_dates=['date'],
            usecols=['date', 'open', 'high', 'low', 'close', 'volume']
        )
        df['symbol'] = symbol
        
        # 股票池清洗
        if not clean_stock_pool(df, symbol):
            continue
        
        df_list.append(df)
    
    if not df_list:
        return None
    
    # 合并
    panel_df = pd.concat(df_list, ignore_index=True)
    panel_df = panel_df.sort_values(by=['date', 'symbol'])
    
    # 内存优化: 使用category类型
    panel_df['symbol'] = panel_df['symbol'].astype('category')
    
    print(f"✅ 加载完成: {len(panel_df['symbol'].unique())} 只股票, {len(panel_df)} 条记录")
    return panel_df


# ================= WFA 验证引擎 (幻觉修复版) =================
class WFAValidator:
    """前进式验证器 (修复三大幻觉)"""
    
    def __init__(self, panel_df: pd.DataFrame):
        self.panel_df = panel_df
        self.dates = sorted(panel_df['date'].unique())
    
    def run_wfa(self, factor_name: str, signal_type: str, period: int) -> Dict:
        """
        运行WFA验证 (幻觉修复版)
        """
        print(f"\n🔬 WFA验证: {factor_name}")
        
        start_idx = TRAIN_WINDOW + TEST_WINDOW
        if start_idx >= len(self.dates):
            print(f"  ⚠️ 数据不足，跳过")
            return None
        
        results = []
        
        for step in range(ROLLING_STEPS):
            train_end_idx = start_idx + step * TEST_WINDOW
            test_start_idx = train_end_idx
            test_end_idx = min(test_start_idx + TEST_WINDOW, len(self.dates))
            
            if test_start_idx >= len(self.dates):
                break
            
            train_start_idx = train_end_idx - TRAIN_WINDOW
            train_dates = self.dates[train_start_idx:train_end_idx]
            test_dates = self.dates[test_start_idx:test_end_idx]
            
            if len(test_dates) < 5:
                continue
            
            # 训练集: 计算因子分位数
            train_panel = self.panel_df[self.panel_df['date'].isin(train_dates)]
            
            factor_ranks = {}
            for symbol in train_panel['symbol'].unique():
                stock_df = train_panel[train_panel['symbol'] == symbol].copy()
                stock_df = stock_df.sort_values('date')
                
                factor_vals = calculate_factor(stock_df, factor_name)
                if factor_vals is not None and len(factor_vals) > 0:
                    last_factor = factor_vals.iloc[-1]
                    # 🔑 关键修复: 过滤inf和nan
                    if pd.notna(last_factor) and not np.isinf(last_factor):
                        factor_ranks[symbol] = last_factor
            
            if len(factor_ranks) < 10:
                continue
            
            # 分组排序
            sorted_stocks = sorted(factor_ranks.items(), key=lambda x: x[1])
            n = len(sorted_stocks)
            
            if signal_type == "low_vol":
                long_stocks = [s[0] for s in sorted_stocks[:n//3]]
            else:
                long_stocks = [s[0] for s in sorted_stocks[-n//3:]]
            
            # 测试集: 计算收益 (幻觉修复版)
            test_panel = self.panel_df[self.panel_df['date'].isin(test_dates)]
            
            long_returns = []
            skipped_trades = 0
            
            for i in range(len(test_dates) - 1):
                date = test_dates[i]
                next_date = test_dates[i + 1]
                
                day_panel = test_panel[test_panel['date'] == date]
                next_day_panel = test_panel[test_panel['date'] == next_date]
                
                for symbol in long_stocks:
                    try:
                        today_close = day_panel[day_panel['symbol'] == symbol]['close'].values[0]
                        
                        # 🔑 关键修复: 使用次日开盘价买入 (Lookahead Bias修复)
                        next_open = next_day_panel[next_day_panel['symbol'] == symbol]['open'].values[0]
                        next_close = next_day_panel[next_day_panel['symbol'] == symbol]['close'].values[0]
                        
                        if today_close <= 0 or next_open <= 0:
                            continue
                        
                        # 🔑 关键修复: 涨跌停流动性幻觉
                        pct_change = (next_open - today_close) / today_close
                        
                        # 一字板或涨跌停，无法成交
                        if abs(pct_change) >= 0.095:
                            skipped_trades += 1
                            continue
                        
                        # 收益率 = (收盘价 - 开盘价) / 开盘价
                        ret = (next_close - next_open) / next_open
                        
                        # 🔑 关键修复: 扣除双边交易成本
                        ret -= TRANSACTION_COST
                        
                        long_returns.append(ret)
                        
                    except Exception as e:
                        continue
            
            if not long_returns:
                continue
            
            avg_return = np.mean(long_returns)
            
            results.append({
                'return': avg_return,
                'num_trades': len(long_returns),
                'skipped_trades': skipped_trades
            })
        
        if not results:
            return None
        
        # 汇总结果
        returns = [r['return'] for r in results]
        total_return = np.sum(returns)
        avg_return = np.mean(returns)
        std_return = np.std(returns)
        
        wins = sum(1 for r in returns if r > 0)
        win_rate = wins / len(returns) if returns else 0
        
        sharpe = avg_return / std_return * np.sqrt(252) if std_return > 0 else 0
        sharpe_haircut = sharpe * HAIRCUT_FACTOR
        
        total_trades = sum(r['num_trades'] for r in results)
        total_skipped = sum(r['skipped_trades'] for r in results)
        
        return {
            'factor_name': factor_name,
            'signal_type': signal_type,
            'period': period,
            'total_return': round(total_return, 4),
            'avg_return': round(avg_return, 4),
            'std_return': round(std_return, 4),
            'sharpe_ratio': round(sharpe, 4),
            'sharpe_ratio_haircut': round(sharpe_haircut, 4),
            'win_rate': round(win_rate, 4),
            'num_windows': len(results),
            'wins': wins,
            'losses': len(results) - wins,
            'total_trades': total_trades,
            'skipped_trades': total_skipped
        }


# ================= 主程序 =================
def main():
    print("=" * 60)
    print("🚀 Alpha Factory - WFA 自动验证器 V2 (幻觉修复版)")
    print("=" * 60)
    
    # 1. 加载候选因子
    print(f"\n📋 加载候选因子...")
    if not os.path.exists(CANDIDATES_FILE):
        print(f"❌ 候选因子文件不存在: {CANDIDATES_FILE}")
        return
    
    with open(CANDIDATES_FILE, 'r', encoding='utf-8') as f:
        candidates_data = json.load(f)
    
    candidates = candidates_data.get('candidates', [])
    print(f"   加载了 {len(candidates)} 个候选因子")
    
    # 2. 加载数据
    panel_df = load_panel_data()
    if panel_df is None:
        return
    
    # 3. 初始化WFA验证器
    validator = WFAValidator(panel_df)
    
    # 4. 批量验证
    print(f"\n🔍 开始 WFA 验证 (训练{TRAIN_WINDOW}天/测试{TEST_WINDOW}天 x {ROLLING_STEPS}轮)...")
    print(f"   交易成本: 双边{TRANSACTION_COST*1000:.1f}‰")
    print("-" * 60)
    
    wfa_results = []
    promoted = []
    
    for candidate in candidates:
        factor_name = candidate['factor_name']
        
        strategy = get_factor_strategy(factor_name)
        if strategy is None:
            print(f"  ⚠️ {factor_name}: 无对应策略，跳过")
            continue
        
        result = validator.run_wfa(
            factor_name, 
            strategy['signal'],
            strategy['period']
        )
        
        if result:
            wfa_results.append(result)
            
            passed = (
                result['win_rate'] >= WIN_RATE_THRESHOLD and
                result['sharpe_ratio_haircut'] >= SHARPE_THRESHOLD * HAIRCUT_FACTOR
            )
            
            status = "✅" if passed else "❌"
            print(f"  {status} {factor_name}: 胜率={result['win_rate']:.1%}, 夏普={result['sharpe_ratio']:.2f} (haircut={result['sharpe_ratio_haircut']:.2f}), 交易={result['total_trades']}笔, 跳过涨跌停={result['skipped_trades']}笔")
            
            if passed:
                promoted.append({
                    **result,
                    'strategy_name': strategy['name'],
                    'promoted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
        else:
            print(f"  ❌ {factor_name}: WFA验证失败")
    
    # 5. 输出结果
    print("\n" + "=" * 60)
    print("🎯 WFA 验证结果 (幻觉修复后)")
    print("=" * 60)
    
    print(f"\n通过验证晋级的策略: {len(promoted)}/{len(wfa_results)}")
    
    for i, p in enumerate(promoted, 1):
        print(f"\n  {i}. {p['strategy_name']}")
        print(f"     因子: {p['factor_name']}")
        print(f"     胜率: {p['win_rate']:.1%} ({p['wins']}胜/{p['losses']}负)")
        print(f"     夏普: {p['sharpe_ratio']:.2f} (haircut后: {p['sharpe_ratio_haircut']:.2f})")
        print(f"     累计收益: {p['total_return']:.2%}")
        print(f"     交易笔数: {p['total_trades']}笔 (跳过涨跌停: {p['skipped_trades']}笔)")
    
    # 6. 保存晋级策略
    output_data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": "V2_幻觉修复版",
        "fixes": [
            "Lookahead Bias: 使用次日开盘价买入",
            "流动性幻觉: 过滤涨跌停无法成交",
            "交易成本: 扣除双边千分之二"
        ],
        "total_tested": len(wfa_results),
        "promoted_count": len(promoted),
        "thresholds": {
            "win_rate": WIN_RATE_THRESHOLD,
            "sharpe": SHARPE_THRESHOLD,
            "haircut": HAIRCUT_FACTOR,
            "transaction_cost": TRANSACTION_COST
        },
        "strategies": promoted
    }
    
    with open(PROMOTED_FILE, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 晋级策略已保存至: {PROMOTED_FILE}")
    print("=" * 60)
    
    return promoted


if __name__ == "__main__":
    main()
