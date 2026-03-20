#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WFA 自动验证器 - Alpha Factory 第二阶段
======================================
自动对接因子分析结果 + 批量WFA验证 + 策略晋级

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
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import warnings
warnings.filterwarnings('ignore')

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

# ================= WFA 配置 =================
TRAIN_WINDOW = 120           # 训练窗口: 120天 (~6个月)
TEST_WINDOW = 20             # 测试窗口: 20天 (~1个月)
ROLLING_STEPS = 10           # 滚动次数


# ================= 因子到策略的映射 =================
def get_factor_strategy(factor_name: str) -> Dict:
    """
    将因子名转换为策略参数
    """
    strategies = {
        # 低波动策略
        "volatility_60d": {
            "name": "低波动策略_60日",
            "signal": "low_vol",
            "period": 60,
            "description": "做多低波动股票，做空高波动股票"
        },
        "volatility_20d": {
            "name": "低波动策略_20日",
            "signal": "low_vol",
            "period": 20,
            "description": "做多低波动股票，做空高波动股票"
        },
        "volatility_10d": {
            "name": "低波动策略_10日",
            "signal": "low_vol",
            "period": 10,
            "description": "做多低波动股票，做空高波动股票"
        },
        "volatility_5d": {
            "name": "低波动策略_5日",
            "signal": "low_vol",
            "period": 5,
            "description": "做多低波动股票，做空高波动股票"
        },
        "ATR_14d": {
            "name": "ATR低波动策略_14日",
            "signal": "low_atr",
            "period": 14,
            "description": "做多ATR低的股票"
        },
        "ATR_20d": {
            "name": "ATR低波动策略_20日",
            "signal": "low_atr",
            "period": 20,
            "description": "做多ATR低的股票"
        },
        # 成交量均线策略
        "volume_ma_10d": {
            "name": "成交量均线策略_10日",
            "signal": "high_volume_ma",
            "period": 10,
            "description": "做多成交量均线高的股票"
        },
        "volume_ma_5d": {
            "name": "成交量均线策略_5日",
            "signal": "high_volume_ma",
            "period": 5,
            "description": "做多成交量均线高的股票"
        },
        "volume_ma_20d": {
            "name": "成交量均线策略_20日",
            "signal": "high_volume_ma",
            "period": 20,
            "description": "做多成交量均线高的股票"
        },
        "volume_ma_60d": {
            "name": "成交量均线策略_60日",
            "signal": "high_volume_ma",
            "period": 60,
            "description": "做多成交量均线高的股票"
        },
    }
    
    return strategies.get(factor_name, None)


# ================= 数据加载 =================
def load_panel_data() -> pd.DataFrame:
    """加载面板数据"""
    import glob
    
    all_files = glob.glob(os.path.join(DATA_DIR, "*.csv"))
    if not all_files:
        print(f"❌ 未找到数据文件")
        return None
    
    print(f"📂 加载 {len(all_files)} 只股票数据...")
    
    df_list = []
    for file in all_files:
        symbol = os.path.basename(file).split('.')[0]
        df = pd.read_csv(file, parse_dates=['date'])
        df['symbol'] = symbol
        df_list.append(df)
    
    panel_df = pd.concat(df_list, ignore_index=True)
    panel_df = panel_df.sort_values(by=['date', 'symbol'])
    
    print(f"✅ 加载完成: {len(panel_df['symbol'].unique())} 只股票")
    return panel_df


# ================= WFA 验证引擎 =================
class WFAValidator:
    """前进式验证器"""
    
    def __init__(self, panel_df: pd.DataFrame):
        self.panel_df = panel_df
        self.dates = sorted(panel_df['date'].unique())
    
    def calculate_factor(self, df: pd.DataFrame, factor_name: str) -> pd.Series:
        """计算因子值"""
        close = df['close']
        volume = df['volume']
        
        # 提取数字 (如 volatility_60d -> 60)
        import re
        period_match = re.search(r'(\d+)', factor_name)
        period = int(period_match.group(1)) if period_match else 20
        
        if 'volatility' in factor_name:
            vol = close.pct_change().rolling(period).std()
            return vol
        elif 'ATR' in factor_name:
            high = df['high']
            low = df['low']
            tr1 = high - low
            tr2 = abs(high - close.shift(1))
            tr3 = abs(low - close.shift(1))
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(period).mean()
            return atr
        elif 'volume_ma' in factor_name:
            return volume.rolling(period).mean()
        else:
            return None
    
    def run_wfa(
        self, 
        factor_name: str, 
        signal_type: str,
        period: int
    ) -> Dict:
        """
        运行WFA验证
        
        Returns:
            {'win_rate': float, 'sharpe_ratio': float, 'total_return': float, ...}
        """
        print(f"\n🔬 WFA验证: {factor_name}")
        
        # 获取有足够数据的日期
        start_idx = TRAIN_WINDOW + TEST_WINDOW
        if start_idx >= len(self.dates):
            print(f"  ⚠️ 数据不足，跳过")
            return None
        
        results = []
        
        for step in range(ROLLING_STEPS):
            # 计算训练/测试窗口位置
            train_end_idx = start_idx + step * TEST_WINDOW
            test_start_idx = train_end_idx
            test_end_idx = min(test_start_idx + TEST_WINDOW, len(self.dates))
            
            if test_start_idx >= len(self.dates):
                break
            
            train_start_idx = train_end_idx - TRAIN_WINDOW
            
            # 获取训练/测试日期
            train_dates = self.dates[train_start_idx:train_end_idx]
            test_dates = self.dates[test_start_idx:test_end_idx]
            
            if len(test_dates) < 5:
                continue
            
            # 训练集: 计算因子分位数
            train_panel = self.panel_df[self.panel_df['date'].isin(train_dates)]
            
            # 计算训练集因子值
            factor_ranks = {}
            for symbol in train_panel['symbol'].unique():
                stock_df = train_panel[train_panel['symbol'] == symbol].copy()
                stock_df = stock_df.sort_values('date')
                
                factor_vals = self.calculate_factor(stock_df, factor_name)
                if factor_vals is None or factor_vals.empty:
                    continue
                
                # 取训练集最后一天的因子值
                last_factor = factor_vals.iloc[-1]
                if pd.notna(last_factor):
                    factor_ranks[symbol] = last_factor
            
            if len(factor_ranks) < 10:
                continue
            
            # 分组: 高/低
            sorted_stocks = sorted(factor_ranks.items(), key=lambda x: x[1])
            n = len(sorted_stocks)
            
            if signal_type == "low_vol":
                # 低因子组 = 低波动 = 做多
                long_stocks = [s[0] for s in sorted_stocks[:n//3]]
                short_stocks = [s[0] for s in sorted_stocks[-n//3:]]
            else:
                # 高因子组 = 高成交量 = 做多
                long_stocks = [s[0] for s in sorted_stocks[-n//3:]]
                short_stocks = [s[0] for s in sorted_stocks[:n//3]]
            
            # 测试集: 计算收益
            test_panel = self.panel_df[self.panel_df['date'].isin(test_dates)]
            
            # 计算组合收益
            long_returns = []
            short_returns = []
            
            for i in range(len(test_dates) - 1):
                date = test_dates[i]
                next_date = test_dates[i + 1]
                
                day_panel = test_panel[test_panel['date'] == date]
                next_day_panel = test_panel[test_panel['date'] == next_date]
                
                for symbol in long_stocks:
                    try:
                        price_today = day_panel[day_panel['symbol'] == symbol]['close'].values[0]
                        price_next = next_day_panel[next_day_panel['symbol'] == symbol]['close'].values[0]
                        ret = (price_next - price_today) / price_today
                        long_returns.append(ret)
                    except:
                        continue
                
                for symbol in short_stocks:
                    try:
                        price_today = day_panel[day_panel['symbol'] == symbol]['close'].values[0]
                        price_next = next_day_panel[next_day_panel['symbol'] == symbol]['close'].values[0]
                        ret = (price_today - price_next) / price_today  # 做空收益
                        short_returns.append(ret)
                    except:
                        continue
            
            if not long_returns or not short_returns:
                continue
            
            # 计算策略收益
            avg_long = np.mean(long_returns)
            avg_short = np.mean(short_returns)
            strategy_return = (avg_long + avg_short) / 2  # 多空组合
            
            results.append({
                'return': strategy_return,
                'long_return': avg_long,
                'short_return': avg_short
            })
        
        if not results:
            return None
        
        # 汇总结果
        returns = [r['return'] for r in results]
        total_return = np.sum(returns)
        avg_return = np.mean(returns)
        std_return = np.std(returns)
        
        # 胜率
        wins = sum(1 for r in returns if r > 0)
        win_rate = wins / len(returns) if returns else 0
        
        # 夏普比率 (假设无风险利率=0)
        sharpe = avg_return / std_return * np.sqrt(252) if std_return > 0 else 0
        
        # Haircut折扣
        sharpe_haircut = sharpe * HAIRCUT_FACTOR
        
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
            'losses': len(results) - wins
        }


# ================= 主程序 =================
def main():
    print("=" * 60)
    print("🚀 Alpha Factory - WFA 自动验证器启动")
    print("=" * 60)
    
    # 1. 加载候选因子
    print(f"\n📋 加载候选因子...")
    if not os.path.exists(CANDIDATES_FILE):
        print(f"❌ 候选因子文件不存在: {CANDIDATES_FILE}")
        print("   请先运行 factor_generator.py")
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
    print("-" * 60)
    
    wfa_results = []
    promoted = []
    
    for candidate in candidates:
        factor_name = candidate['factor_name']
        
        # 获取策略配置
        strategy = get_factor_strategy(factor_name)
        if strategy is None:
            print(f"  ⚠️ {factor_name}: 无对应策略，跳过")
            continue
        
        # 运行WFA
        result = validator.run_wfa(
            factor_name, 
            strategy['signal'],
            strategy['period']
        )
        
        if result:
            wfa_results.append(result)
            
            # 检查是否通过准入门槛
            passed = (
                result['win_rate'] >= WIN_RATE_THRESHOLD and
                result['sharpe_ratio_haircut'] >= SHARPE_THRESHOLD * HAIRCUT_FACTOR
            )
            
            status = "✅" if passed else "❌"
            print(f"  {status} {factor_name}: 胜率={result['win_rate']:.1%}, 夏普={result['sharpe_ratio']:.2f} ( haircut={result['sharpe_ratio_haircut']:.2f})")
            
            if passed:
                promoted.append({
                    **result,
                    'strategy_name': strategy['name'],
                    'description': strategy['description'],
                    'promoted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
        else:
            print(f"  ❌ {factor_name}: WFA验证失败")
    
    # 5. 输出结果
    print("\n" + "=" * 60)
    print("🎯 WFA 验证结果")
    print("=" * 60)
    
    print(f"\n通过验证晋级的策略: {len(promoted)}/{len(wfa_results)}")
    
    for i, p in enumerate(promoted, 1):
        print(f"\n  {i}. {p['strategy_name']}")
        print(f"     因子: {p['factor_name']}")
        print(f"     胜率: {p['win_rate']:.1%} ({p['wins']}胜/{p['losses']}负)")
        print(f"     夏普: {p['sharpe_ratio']:.2f} ( haircut后: {p['sharpe_ratio_haircut']:.2f})")
        print(f"     累计收益: {p['total_return']:.2%}")
    
    # 6. 保存晋级策略
    output_data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_tested": len(wfa_results),
        "promoted_count": len(promoted),
        "thresholds": {
            "win_rate": WIN_RATE_THRESHOLD,
            "sharpe": SHARPE_THRESHOLD,
            "haircut": HAIRCUT_FACTOR
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