# -*- coding: utf-8 -*-
"""
历史数据下载器 (Data Downloader)
=================================
从 Baostock 获取 A 股历史分钟级/日线数据

功能：
1. 下载日线数据（用于策略回测）
2. 下载分钟级数据（用于高频策略）
3. 数据清洗：去除停牌、复权处理
4. 本地存储为 CSV

作者: AI 量化研究助手
日期: 2026-03-18
"""

import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
from typing import Optional, List, Dict
import warnings
warnings.filterwarnings('ignore')

# 尝试导入数据源
try:
    import baostock as bs
    DATA_SOURCE = "baostock"
except ImportError:
    try:
        import yfinance as yf
        DATA_SOURCE = "yfinance"
    except ImportError:
        DATA_SOURCE = None
        print("⚠️ 请安装数据源: pip install baostock 或 pip install yfinance")

# ================= 配置区 =================
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("DataDownloader")

# ================= 数据下载函数 =================

def download_stock_daily(
    symbol: str,
    start_date: str = "20200101",
    end_date: str = None,
    adjust: str = "qfq"
) -> Optional[pd.DataFrame]:
    """
    下载股票日线数据
    
    Args:
        symbol: 股票代码 (如 "sh600000", "sz000001")
        start_date: 开始日期 (YYYYMMDD 或 YYYY-MM-DD)
        end_date: 结束日期 (YYYYMMDD 或 YYYY-MM-DD)，默认今天
        adjust: 复权类型 "qfq"(前复权) / "hfq"(后复权) / ""(不复权)
    
    Returns:
        DataFrame 或 None
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")
    
    # 标准化日期格式
    start_date = start_date.replace("-", "")
    end_date = end_date.replace("-", "")
    
    logger.info(f"📥 下载 {symbol} 日线数据: {start_date} ~ {end_date}")
    
    try:
        if DATA_SOURCE == "baostock":
            return _download_baostock(symbol, start_date, end_date, adjust)
        elif DATA_SOURCE == "yfinance":
            return _download_yfinance(symbol, start_date, end_date, adjust)
        else:
            logger.error("❌ 无可用数据源，请安装 baostock 或 yfinance")
            return None
        
    except Exception as e:
        logger.error(f"❌ {symbol} 下载失败: {e}")
        return None


def _download_baostock(symbol: str, start_date: str, end_date: str, adjust: str) -> Optional[pd.DataFrame]:
    """使用 Baostock 下载 A 股数据"""
    import baostock as bs
    
    lg = bs.login()
    
    # 转换股票代码格式
    if symbol.startswith("sh"):
        code = f"sh.{symbol[2:]}"
    elif symbol.startswith("sz"):
        code = f"sz.{symbol[2:]}"
    else:
        code = symbol
    
    # 复权类型
    adjust_flag = "2" if adjust == "qfq" else "1" if adjust == "hfq" else "3"
    
    # 日期格式转换: YYYYMMDD -> YYYY-MM-DD
    start_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
    end_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
    
    rs = bs.query_history_k_data_plus(
        code,
        "date,code,open,high,low,close,volume,amount,turn,pctChg",
        start_date=start_fmt,
        end_date=end_fmt,
        frequency="d",
        adjustflag=adjust_flag
    )
    
    data_list = []
    while (rs.error_code == '0') & rs.next():
        data_list.append(rs.get_row_data())
    
    bs.logout()
    
    if not data_list:
        return None
    
    df = pd.DataFrame(data_list, columns=rs.fields)
    
    for col in ['open', 'high', 'low', 'close', 'volume', 'amount', 'turn', 'pctChg']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    df = df.rename(columns={'pctChg': 'pct_change', 'turn': 'turnover'})
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    
    logger.info(f"✅ {symbol} 获取 {len(df)} 条日线数据 (Baostock)")
    return df


def _download_yfinance(symbol: str, start_date: str, end_date: str, adjust: str) -> Optional[pd.DataFrame]:
    """使用 yfinance 下载数据"""
    import yfinance as yf
    
    # 转换股票代码格式 (yfinance 格式: 600000.SS 或 000001.SZ)
    if symbol.startswith("sh"):
        ticker = f"{symbol[2:]}.SS"
    elif symbol.startswith("sz"):
        ticker = f"{symbol[2:]}.SZ"
    else:
        ticker = symbol
    
    # 转换日期格式
    start = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
    end = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
    
    df = yf.download(ticker, start=start, end=end, progress=False)
    
    if df.empty:
        return None
    
    df = df.reset_index()
    df = df.rename(columns={
        'Date': 'date',
        'Open': 'open',
        'High': 'high',
        'Low': 'low',
        'Close': 'close',
        'Volume': 'volume',
        'Adj Close': 'adj_close'
    })
    
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    
    # 计算涨跌幅
    df['pct_change'] = df['close'].pct_change() * 100
    
    logger.info(f"✅ {symbol} 获取 {len(df)} 条日线数据 (yfinance)")
    return df


def download_index_daily(
    symbol: str = "000300",  # 默认沪深300
    start_date: str = "20200101",
    end_date: str = None
) -> Optional[pd.DataFrame]:
    """
    下载指数日线数据
    
    Args:
        symbol: 指数代码 (如 "000300" 沪深300, "000001" 上证指数)
        start_date: 开始日期
        end_date: 结束日期
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")
    
    logger.info(f"📥 下载指数 {symbol} 日线: {start_date} ~ {end_date}")
    
    try:
        df = ak.stock_zh_index_daily(symbol=symbol)
        df = df[(df['date'] >= start_date) & (df['date'] <= end_date)]
        logger.info(f"✅ 指数 {symbol} 获取 {len(df)} 条数据")
        return df
    except Exception as e:
        logger.error(f"❌ 指数 {symbol} 下载失败: {e}")
        return None


def download_stock_minute(
    symbol: str,
    period: str = "1",
    start_date: str = None,
    end_date: str = None,
    adjust: str = ""
) -> Optional[pd.DataFrame]:
    """
    下载股票分钟级数据
    
    Args:
        symbol: 股票代码
        period: 周期 "1"/"5"/"15"/"30"/"60" 分钟
        start_date: 开始日期
        end_date: 结束日期
    
    Note:
        AkShare 的分钟级数据接口有限制，可能需要付费数据源
    """
    logger.info(f"📥 下载 {symbol} {period}分钟级数据")
    
    # 尝试使用分钟级接口
    try:
        # 转换为 AkShare 格式
        if symbol.startswith("sh"):
            code = symbol[2:]
        elif symbol.startswith("sz"):
            code = symbol[2:]
        else:
            code = symbol
        
        # 近期数据接口
        df = ak.stock_zh_a_hist_min_em(
            symbol=code,
            period=period,
            start_date=start_date,
            end_date=end_date,
            adjust=adjust
        )
        
        if df is not None and not df.empty:
            df = df.rename(columns={
                '时间': 'datetime',
                '开盘': 'open',
                '收盘': 'close',
                '最高': 'high',
                '最低': 'low',
                '成交量': 'volume',
                '成交额': 'amount',
                '振幅': 'amplitude',
                '涨跌幅': 'pct_change',
                '涨跌额': 'change',
                '换手率': 'turnover'
            })
            logger.info(f"✅ {symbol} 获取 {len(df)} 条分钟数据")
            return df
            
    except Exception as e:
        logger.warning(f"⚠️ 分钟级数据获取失败: {e}")
    
    return None


# ================= 数据清洗函数 =================

def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    数据清洗：
    1. 去除停牌日（成交量为0）
    2. 去除异常值
    3. 处理缺失值
    """
    if df is None or df.empty:
        return df
    
    original_len = len(df)
    
    # 去除停牌日（成交量为0或NaN）
    if 'volume' in df.columns:
        df = df[df['volume'] > 0]
    
    # 去除价格异常值
    if 'close' in df.columns:
        # 价格为0或负数
        df = df[df['close'] > 0]
        # 单日涨跌幅超过20%视为异常
        if 'pct_change' in df.columns:
            df = df[abs(df['pct_change']) < 0.20]
    
    # 去除缺失值
    df = df.dropna()
    
    cleaned_len = len(df)
    if original_len > cleaned_len:
        logger.info(f"🧹 清洗数据: {original_len} → {cleaned_len} 条 (去除 {original_len - cleaned_len} 条)")
    
    return df.reset_index(drop=True)


def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    添加技术指标（用于策略回测）
    """
    if df is None or df.empty:
        return df
    
    # 移动平均线
    for window in [5, 10, 20, 60]:
        df[f'ma{window}'] = df['close'].rolling(window=window).mean()
    
    # EMA
    for window in [12, 26]:
        df[f'ema{window}'] = df['close'].ewm(span=window, adjust=False).mean()
    
    # MACD
    df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
    df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = df['ema12'] - df['ema26']
    df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['signal']
    
    # 布林带
    df['bb_middle'] = df['close'].rolling(window=20).mean()
    df['bb_std'] = df['close'].rolling(window=20).std()
    df['bb_upper'] = df['bb_middle'] + 2 * df['bb_std']
    df['bb_lower'] = df['bb_middle'] - 2 * df['bb_std']
    
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # 成交量变化
    df['volume_change'] = df['volume'].pct_change()
    
    logger.info(f"📊 添加技术指标完成")
    return df


# ================= 存储函数 =================

def save_to_csv(
    df: pd.DataFrame,
    symbol: str,
    data_type: str = "daily",
    period: str = "1"
) -> str:
    """
    保存数据到 CSV 文件
    """
    if df is None or df.empty:
        return None
    
    # 生成文件名
    if data_type == "daily":
        filename = f"{symbol}_daily.csv"
    else:
        filename = f"{symbol}_minute_{period}.csv"
    
    filepath = os.path.join(DATA_DIR, filename)
    df.to_csv(filepath, index=False, encoding='utf-8')
    logger.info(f"💾 数据已保存: {filepath}")
    return filepath


def load_from_csv(symbol: str, data_type: str = "daily") -> Optional[pd.DataFrame]:
    """
    从 CSV 加载数据
    """
    if data_type == "daily":
        filename = f"{symbol}_daily.csv"
    else:
        return None
    
    filepath = os.path.join(DATA_DIR, filename)
    if os.path.exists(filepath):
        df = pd.read_csv(filepath)
        df['date'] = pd.to_datetime(df['date'])
        logger.info(f"📂 加载本地数据: {filepath} ({len(df)} 条)")
        return df
    return None


# ================= 批量下载 =================

def download_stock_pool(
    symbols: List[str],
    start_date: str = "20200101",
    end_date: str = None,
    adjust: str = "qfq"
) -> Dict[str, pd.DataFrame]:
    """
    批量下载多只股票数据
    """
    results = {}
    
    for symbol in symbols:
        logger.info(f"📥 进度: {symbols.index(symbol) + 1}/{len(symbols)} - {symbol}")
        
        # 先尝试从本地加载
        df = load_from_csv(symbol, "daily")
        if df is not None:
            results[symbol] = df
            continue
        
        # 下载
        df = download_stock_daily(symbol, start_date, end_date, adjust)
        if df is not None:
            df = clean_data(df)
            df = add_technical_indicators(df)
            save_to_csv(df, symbol, "daily")
            results[symbol] = df
        
        # 避免请求过快
        import time
        time.sleep(1)
    
    logger.info(f"✅ 批量下载完成: {len(results)}/{len(symbols)} 只股票")
    return results


# ================= 主程序 =================

if __name__ == "__main__":
    # 测试下载
    test_symbols = ["sh600000", "sz000001"]
    
    for symbol in test_symbols:
        df = download_stock_daily(symbol, "20240101")
        if df is not None:
            df = clean_data(df)
            df = add_technical_indicators(df)
            save_to_csv(df, symbol)
            print(df.tail())
