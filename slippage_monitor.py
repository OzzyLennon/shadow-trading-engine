#!/usr/bin/env python3
"""
滑点监控脚本
对比新浪财经价格 vs 东方财富真实盘口价格
记录理论滑点 vs 实际滑点差距
"""

import requests
import json
import datetime
import os
import time
import sys
from typing import Dict, List, Any, Optional

from core.config import load_env, load_config_with_fallback
from core.errors import create_error_handler, log_error
from core.logging_config import get_logger

# 加载环境变量和配置
load_env()
config = load_config_with_fallback()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_FILE = os.path.join(SCRIPT_DIR, "apex_portfolio.json")
SLIPPAGE_LOG = os.path.join(SCRIPT_DIR, "logs", "slippage_monitor.json")

# 理论滑点设置
THEORETICAL_SLIPPAGE = config.costs.slippage

# 日志和错误处理
logger = get_logger("slippage_monitor")
error_handler = create_error_handler(logger)

def get_sina_price(symbol: str) -> Optional[Dict[str, Any]]:
    """获取新浪财经价格"""
    url = f"http://hq.sinajs.cn/list={symbol}"
    headers = {'Referer': 'http://finance.sina.com.cn'}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        res.encoding = 'gbk'
        if '="' in res.text:
            data = res.text.split('="')[1].split(';')[0].split(',')
            if len(data) > 3:
                return {
                    "name": data[0],
                    "current": float(data[3]) if data[3] else 0,
                    "prev_close": float(data[2]) if data[2] else 0,  # 昨收价
                    "buy1": float(data[6]) if len(data) > 6 and data[6] else 0,
                    "sell1": float(data[7]) if len(data) > 7 and data[7] else 0,
                }
    except Exception as e:
        logger.error(f"新浪获取失败: {e}")
    return None

def get_eastmoney_price(symbol: str) -> Optional[Dict[str, Any]]:
    """获取东方财富盘口价格"""
    # 转换代码格式
    if symbol.startswith('sh'):
        secid = f"1.{symbol[2:]}"
    elif symbol.startswith('sz'):
        secid = f"0.{symbol[2:]}"
    else:
        secid = symbol

    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f43,f44,f45,f46,f47,f48,f49,f50,f51,f52,f57,f58"
    headers = {'User-Agent': 'Mozilla/5.0'}

    try:
        res = requests.get(url, headers=headers, timeout=5)
        data = res.json()
        if data.get('data'):
            d = data['data']
            # f43=最新价, f46=买一价, f45=卖一价
            return {
                "current": d.get('f43', 0) / 100 if d.get('f43') else 0,
                "buy1": d.get('f46', 0) / 100 if d.get('f46') else 0,
                "sell1": d.get('f45', 0) / 100 if d.get('f45') else 0,
            }
    except Exception as e:
        logger.error(f"东方财富获取失败: {e}")
    return None

@error_handler
def calculate_slippage_gap(symbol: str, name: str) -> Optional[Dict[str, Any]]:
    """
    计算滑点差距
    返回：新浪价格、东财价格、差距百分比
    """
    sina = get_sina_price(symbol)
    eastmoney = get_eastmoney_price(symbol)
    
    if not sina or not eastmoney:
        return None
    
    # 对比卖一价（买入时需要付出的价格）
    sina_sell1 = sina.get('sell1', 0) or sina.get('current', 0)
    em_sell1 = eastmoney.get('sell1', 0) or eastmoney.get('current', 0)
    
    if sina_sell1 <= 0 or em_sell1 <= 0:
        return None
    
    # 计算差距
    gap = abs(sina_sell1 - em_sell1)
    gap_pct = (gap / em_sell1) * 100
    
    return {
        "symbol": symbol,
        "name": name,
        "timestamp": datetime.datetime.now().isoformat(),
        "sina_price": sina_sell1,
        "eastmoney_price": em_sell1,
        "gap": gap,
        "gap_pct": gap_pct,
        "theoretical_slippage": THEORETICAL_SLIPPAGE * 100,
        "actual_vs_theoretical": gap_pct - (THEORETICAL_SLIPPAGE * 100)
    }

MAX_SLIPPAGE_RECORDS = 1000  # 最大记录数

def log_slippage(result: Dict[str, Any]) -> None:
    """记录滑点数据"""
    log_dir = os.path.dirname(SLIPPAGE_LOG)
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 读取现有记录
    records = []
    if os.path.exists(SLIPPAGE_LOG):
        try:
            with open(SLIPPAGE_LOG, 'r', encoding='utf-8') as f:
                records = json.load(f)
        except:
            records = []

    records.append(result)

    # 限制记录数量，保留最新的记录
    if len(records) > MAX_SLIPPAGE_RECORDS:
        records = records[-MAX_SLIPPAGE_RECORDS:]

    # 保存
    with open(SLIPPAGE_LOG, 'w', encoding='utf-8') as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    logger.info(f"滑点记录已保存: {result['symbol']} {result['name']}")

@error_handler
def monitor_slippage(symbols: Dict[str, str]) -> List[Dict[str, Any]]:
    """
    监控多个股票的滑点
    """
    logger.info(f"滑点监控报告 - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\n{'='*50}")
    print(f"📊 滑点监控报告 - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    results = []
    for symbol, name in symbols.items():
        result = calculate_slippage_gap(symbol, name)
        if result:
            results.append(result)

            # 打印结果
            print(f"\n📌 {name} ({symbol})")
            print(f"   新浪卖一价: {result['sina_price']:.3f}")
            print(f"   东财卖一价: {result['eastmoney_price']:.3f}")
            print(f"   价差: {result['gap']:.3f} ({result['gap_pct']:.3f}%)")
            print(f"   理论滑点: {result['theoretical_slippage']:.2f}%")

            if result['actual_vs_theoretical'] > 0:
                print(f"   ⚠️ 实际滑点超出理论: +{result['actual_vs_theoretical']:.3f}%")
            else:
                print(f"   ✅ 实际滑点在理论范围内")

            # 记录到文件
            log_slippage(result)

    # 统计汇总
    if results:
        avg_gap = sum(r['gap_pct'] for r in results) / len(results)
        max_gap = max(r['gap_pct'] for r in results)
        exceed_count = sum(1 for r in results if r['actual_vs_theoretical'] > 0)

        print(f"\n{'='*50}")
        print(f"📈 汇总统计")
        print(f"   平均价差: {avg_gap:.3f}%")
        print(f"   最大价差: {max_gap:.3f}%")
        print(f"   超出理论滑点次数: {exceed_count}/{len(results)}")

    return results

@error_handler
def generate_daily_report() -> None:
    """
    生成每日滑点报告
    """
    if not os.path.exists(SLIPPAGE_LOG):
        logger.info("暂无滑点记录")
        print("暂无滑点记录")
        return

    with open(SLIPPAGE_LOG, 'r', encoding='utf-8') as f:
        records = json.load(f)

    # 按日期分组
    by_date = {}
    for r in records:
        date = r['timestamp'][:10]
        if date not in by_date:
            by_date[date] = []
        by_date[date].append(r)

    print(f"\n{'='*50}")
    print(f"📊 每日滑点报告")
    print(f"{'='*50}")

    for date, recs in sorted(by_date.items(), reverse=True)[:7]:
        avg_gap = sum(r['gap_pct'] for r in recs) / len(recs)
        exceed = sum(1 for r in recs if r['actual_vs_theoretical'] > 0)

        print(f"\n📅 {date}")
        print(f"   记录次数: {len(recs)}")
        print(f"   平均价差: {avg_gap:.3f}%")
        print(f"   超出理论: {exceed}/{len(recs)}")

if __name__ == "__main__":
    # 默认股票池
    DEFAULT_SYMBOLS = {
        "sh601138": "工业富联", "sz000938": "紫光股份",
        "sh600030": "中信证券", "sz002594": "比亚迪",
        "sz159819": "人工智能ETF", "sh512880": "证券ETF"
    }

    # 优先使用配置文件中的股票池
    if config.symbols:
        symbols = config.symbols
    else:
        # 尝试读取每日配置
        config_file = os.path.join(SCRIPT_DIR, "daily_config.json")
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    daily_config = json.load(f)
                symbols = daily_config.get('symbols', DEFAULT_SYMBOLS)
            except:
                symbols = DEFAULT_SYMBOLS
        else:
            symbols = DEFAULT_SYMBOLS

    if len(sys.argv) > 1 and sys.argv[1] == 'report':
        # 生成报告
        generate_daily_report()
    else:
        # 实时监控
        monitor_slippage(symbols)


# ================= 涨跌停检测函数 =================
def check_limit_up(symbol: str, limit_pct: float = 0.1) -> bool:
    """
    检查股票是否涨停

    Args:
        symbol: 股票代码
        limit_pct: 涨停幅度 (默认10%)

    Returns:
        True 如果涨停
    """
    data = get_eastmoney_price(symbol)
    if not data:
        return False

    current = data.get('current', 0)
    buy1 = data.get('buy1', 0)

    # 涨停特征：买一价等于当前价，且有大量买单
    # 简化判断：买一价存在且与当前价一致
    if buy1 > 0 and abs(buy1 - current) / current < 0.001:
        return True

    # 获取昨收价判断涨幅
    sina = get_sina_price(symbol)
    if sina and 'prev_close' in sina:
        prev_close = sina['prev_close']
        if prev_close > 0:
            change_pct = (current - prev_close) / prev_close
            if change_pct >= limit_pct - 0.001:
                return True

    return False


def check_limit_down(symbol: str, limit_pct: float = 0.1) -> bool:
    """
    检查股票是否跌停

    Args:
        symbol: 股票代码
        limit_pct: 跌停幅度 (默认10%)

    Returns:
        True 如果跌停
    """
    data = get_eastmoney_price(symbol)
    if not data:
        return False

    current = data.get('current', 0)
    sell1 = data.get('sell1', 0)

    # 跌停特征：卖一价等于当前价，且有大量卖单
    # 简化判断：卖一价存在且与当前价一致
    if sell1 > 0 and abs(sell1 - current) / current < 0.001:
        return True

    # 获取昨收价判断跌幅
    sina = get_sina_price(symbol)
    if sina and 'prev_close' in sina:
        prev_close = sina['prev_close']
        if prev_close > 0:
            change_pct = (current - prev_close) / prev_close
            if change_pct <= -limit_pct + 0.001:
                return True

    return False


def check_limit_status(symbol: str, limit_pct: float = 0.1) -> tuple:
    """
    检查股票涨跌停状态

    Args:
        symbol: 股票代码
        limit_pct: 涨跌停幅度 (默认10%)

    Returns:
        (is_limit_up, is_limit_down)
    """
    return check_limit_up(symbol, limit_pct), check_limit_down(symbol, limit_pct)
