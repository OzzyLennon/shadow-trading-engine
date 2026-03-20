#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
因子计算库 - 单一数据源 (DRY原则)
==================================
所有因子计算逻辑统一存放于此
研究脚本和实盘引擎统一import此库

作者: AI 量化研究助手
日期: 2026-03-20
"""

import pandas as pd
import numpy as np
from typing import Optional


# ================= 因子计算函数 =================

def calc_return(close: pd.Series, period: int) -> pd.Series:
    """收益率因子"""
    return close.pct_change(periods=period)


def calc_log_return(close: pd.Series, period: int) -> pd.Series:
    """对数收益率因子"""
    return np.log(close / close.shift(period))


def calc_volume_ma(volume: pd.Series, period: int) -> pd.Series:
    """成交量均线因子"""
    return volume.rolling(period).mean()


def calc_volume_ratio(volume: pd.Series, period: int) -> pd.Series:
    """成交量比因子"""
    return volume / volume.rolling(period).mean()


def calc_volatility(close: pd.Series, period: int) -> pd.Series:
    """波动率因子"""
    return close.pct_change().rolling(period).std()


def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    """
    真实波动幅度 (ATR)
    
    TR = max(H-L, |H-C_prev|, |L-C_prev|)
    ATR = MA(TR, period)
    """
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    
    return atr


def calc_turnover(volume: pd.Series, period: int) -> pd.Series:
    """换手率因子 (简化版，用成交量变化率近似)"""
    return volume.pct_change(period)


def calc_bias(close: pd.Series, period: int) -> pd.Series:
    """乖离率因子"""
    ma = close.rolling(period).mean()
    return (close - ma) / ma


def calc_momentum(close: pd.Series, period: int) -> pd.Series:
    """动量因子"""
    return close / close.shift(period) - 1


def calc_rsi(close: pd.Series, period: int) -> pd.Series:
    """
    相对强弱因子 (RSI)
    
    RSI = 100 - 100/(1+RS)
    RS = AvgGain / AvgLoss
    """
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi


def calc_price_ma_ratio(close: pd.Series, period: int) -> pd.Series:
    """价格与均线比因子"""
    return close / close.rolling(period).mean()


# ================= 因子分发器 =================

FACTOR_REGISTRY = {
    'return': calc_return,
    'log_return': calc_log_return,
    'volume_ma': calc_volume_ma,
    'volume_ratio': calc_volume_ratio,
    'volatility': calc_volatility,
    'ATR': calc_atr,
    'turnover': calc_turnover,
    'bias': calc_bias,
    'momentum': calc_momentum,
    'RSI': calc_rsi,
    'price_ma_ratio': calc_price_ma_ratio,
}


def calculate_factor(
    df: pd.DataFrame, 
    factor_name: str,
    period: Optional[int] = None
) -> Optional[pd.Series]:
    """
    统一因子计算入口
    
    Args:
        df: 包含 OHLCV 的 DataFrame
        factor_name: 因子名，如 'volatility_60d', 'volume_ma_10d'
        period: 可选，手动指定周期
    
    Returns:
        因子值序列，计算失败返回 None
    """
    import re
    
    # 提取因子类型和周期
    period_match = re.search(r'(\d+)', factor_name)
    if period is None and period_match:
        period = int(period_match.group(1))
    elif period is None:
        period = 20  # 默认周期
    
    # 识别因子类型
    factor_type = None
    for key in FACTOR_REGISTRY:
        if key.lower() in factor_name.lower():
            factor_type = key
            break
    
    if factor_type is None:
        return None
    
    # 获取计算函数
    calc_func = FACTOR_REGISTRY.get(factor_type)
    if calc_func is None:
        return None
    
    # 准备数据
    close = df['close']
    volume = df.get('volume')
    high = df.get('high')
    low = df.get('low')
    
    try:
        # 根据因子类型调用不同参数
        if factor_type == 'ATR':
            if high is None or low is None:
                return None
            return calc_atr(high, low, close, period)
        elif factor_type in ['volume_ma', 'volume_ratio', 'turnover']:
            if volume is None:
                return None
            return calc_func(volume, period)
        elif factor_type == 'RSI':
            return calc_rsi(close, period)
        else:
            return calc_func(close, period)
    except Exception as e:
        return None


# ================= 批量实时价格获取 =================

def get_realtime_prices_batch(symbols: list, batch_size: int = 50) -> dict:
    """
    批量获取实时价格 (新浪接口)
    
    Args:
        symbols: 股票代码列表，如 ['sh600000', 'sz000001']
        batch_size: 每批请求数量，默认50
    
    Returns:
        {symbol: price} 字典
    """
    import requests
    import time
    
    prices = {}
    
    # 分批请求
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        
        # 构建批量请求URL
        codes = []
        for s in batch:
            if s.startswith('sh'):
                codes.append(f"sh{s[2:]}")
            elif s.startswith('sz'):
                codes.append(f"sz{s[2:]}")
            else:
                codes.append(s)
        
        url = f"http://hq.sinajs.cn/list={','.join(codes)}"
        headers = {'Referer': 'http://finance.sina.com.cn'}
        
        try:
            res = requests.get(url, headers=headers, timeout=10)
            res.encoding = 'gbk'
            
            # 解析返回数据
            lines = res.text.split('\n')
            for line in lines:
                if 'hq_str_' not in line or '=' not in line:
                    continue
                
                # 提取代码和数据
                code_part = line.split('=')[0].split('_')[-1]
                data_part = line.split('"')[1] if '"' in line else ''
                
                if not data_part:
                    continue
                
                fields = data_part.split(',')
                if len(fields) < 31:
                    continue
                
                # 获取当前价 (第4字段)
                try:
                    price = float(fields[3])
                    if price <= 0:
                        price = float(fields[2])  # 用昨收
                    
                    # 恢复原始代码格式
                    if code_part.startswith('sh'):
                        symbol = f"sh{code_part[2:]}"
                    elif code_part.startswith('sz'):
                        symbol = f"sz{code_part[2:]}"
                    else:
                        symbol = code_part
                    
                    prices[symbol] = price
                except:
                    continue
            
            # 批次间间隔，避免封禁
            if i + batch_size < len(symbols):
                time.sleep(0.5)
                
        except Exception as e:
            continue
    
    return prices
