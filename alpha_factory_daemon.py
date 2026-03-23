#!/usr/bin/env python3
"""
Alpha Factory 策略执行引擎 - 第三阶段
动态读取 promoted_strategies.json，热更新策略
"""

import json
import datetime
import os
import math
import time
import signal
import sys
import glob
import pandas as pd

from factor_lib import calculate_factor, get_realtime_prices_batch
from core.config import load_env, load_config_with_fallback
from core.errors import create_error_handler, log_error
from core import functions
from core.logging_config import get_logger

# 加载环境变量和配置
load_env()
config = load_config_with_fallback()

# ================= 核心配置 =================
FEISHU_WEBHOOK = config.api.feishu_webhook or ""
INITIAL_CAPITAL = config.initial_capital
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_FILE = os.path.join(SCRIPT_DIR, "alpha_factory_portfolio.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "logs", "alpha_factory.log")
PROMOTED_FILE = os.path.join(SCRIPT_DIR, "promoted_strategies.json")
DATA_DIR = os.path.join(SCRIPT_DIR, "research", "data")
PERFORMANCE_FILE = os.path.join(SCRIPT_DIR, "strategy_performance.json")

POLL_INTERVAL = config.poll_interval  # 轮询间隔（秒）

# 交易时段
MORNING_START = config.market_hours.morning_start
MORNING_END = config.market_hours.morning_end
AFTERNOON_START = config.market_hours.afternoon_start
AFTERNOON_END = config.market_hours.afternoon_end

# 灰度配置
GRAY_WEIGHT = config.alpha_factory.gray_weight        # 新策略只给10%仓位
MIN_CAPITAL_PER_TRADE = config.alpha_factory.min_capital_per_trade  # 单笔最小金额
MAX_POSITIONS = config.alpha_factory.max_positions        # 单策略最多持有10只股票 (硬性截断)
MAX_HOLDING_DAYS = config.alpha_factory.max_holding_days      # 最大持仓天数 (调仓周期)

# 交易成本
COMMISSION_RATE = config.alpha_factory.commission_rate
STAMP_DUTY_RATE = config.alpha_factory.stamp_duty_rate

# ================= 日志和错误处理 =================
logger = get_logger("alpha_factory")
error_handler = create_error_handler(logger)

# ================= 全局状态 =================
running = True
strategies = {}
stock_pool = []
daily_signals = {}
portfolio = None
last_strategy_load = None

def log(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {message}"
    print(log_line)
    try:
        log_dir = os.path.dirname(LOG_FILE)
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_line + "\n")
    except: pass

def signal_handler(signum, frame):
    global running
    log("🛑 收到停止信号，正在优雅退出...")
    running = False


# ================= 策略加载 =================
@error_handler
def load_promoted_strategies():
    """加载晋级策略"""
    global strategies, last_strategy_load
    
    if not os.path.exists(PROMOTED_FILE):
        log(f"⚠️ 策略文件不存在: {PROMOTED_FILE}")
        return False
    
    with open(PROMOTED_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    new_strategies = {}
    for s in data.get('strategies', []):
        factor_name = s['factor_name']
        new_strategies[factor_name] = {
            'signal_type': s['signal_type'],
            'period': s['period'],
            'sharpe': s['sharpe_ratio_haircut'],
            'win_rate': s['win_rate'],
            'name': s['strategy_name'],
            'weight': GRAY_WEIGHT  # 灰度权重
        }
    
    if new_strategies != strategies:
        log(f"📥 策略更新: 加载了 {len(new_strategies)} 个策略")
        strategies = new_strategies
        last_strategy_load = datetime.datetime.now()
        return True
    
    return False

@error_handler
def load_stock_pool():
    """加载股票池"""
    global stock_pool
    
    if not os.path.exists(DATA_DIR):
        log(f"⚠️ 数据目录不存在: {DATA_DIR}")
        return
    
    files = glob.glob(os.path.join(DATA_DIR, "*.csv"))
    stock_pool = [os.path.basename(f).split('.')[0] for f in files]
    log(f"📊 股票池: {len(stock_pool)} 只")

@error_handler
def generate_signals():
    """生成交易信号 (使用绝对数量截断)"""
    global daily_signals
    
    if not strategies or not stock_pool:
        return
    
    log("🔮 正在生成交易信号...")
    daily_signals = {}
    
    for factor_name, config in strategies.items():
        signal_type = config['signal_type']
        period = config['period']
        
        # 计算所有股票的因子值
        factor_values = {}
        
        for symbol in stock_pool:
            file_path = os.path.join(DATA_DIR, f"{symbol}.csv")
            if not os.path.exists(file_path):
                continue
            
            try:
                stock_df = pd.read_csv(file_path, parse_dates=['date'])
                stock_df = stock_df.sort_values('date')
                
                # 使用factor_lib统一计算
                factor_series = calculate_factor(stock_df, factor_name)
                if factor_series is not None and len(factor_series) > 0:
                    last_val = factor_series.iloc[-1]
                    if pd.notna(last_val):
                        factor_values[symbol] = last_val
            except Exception as e:
                continue
        
        if len(factor_values) < MAX_POSITIONS:
            continue
        
        # 排序后取绝对数量 (硬性截断，避免过度分散)
        sorted_stocks = sorted(factor_values.items(), key=lambda x: x[1])
        
        if signal_type == "high_volume_ma":
            # 高因子组 = 做多，取前MAX_POSITIONS只
            top_stocks = sorted_stocks[-MAX_POSITIONS:]
            daily_signals[factor_name] = {
                'long': [s[0] for s in top_stocks],
                'factor_values': {s[0]: s[1] for s in top_stocks}
            }
        elif signal_type in ["low_vol", "low_atr"]:
            # 低因子组 = 做多，取前MAX_POSITIONS只
            bottom_stocks = sorted_stocks[:MAX_POSITIONS]
            daily_signals[factor_name] = {
                'long': [s[0] for s in bottom_stocks],
                'factor_values': {s[0]: s[1] for s in bottom_stocks}
            }
    
    # 汇总信号
    log(f"📡 信号生成完成: {len(daily_signals)} 个策略有信号")
    for factor_name, sig in daily_signals.items():
        log(f"   {factor_name}: {len(sig['long'])} 只股票看多")

# ================= 组合管理 =================
@error_handler
def load_portfolio():
    """加载组合"""
    global portfolio
    
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE, 'r', encoding='utf-8') as f:
            portfolio = json.load(f)
        log(f"📂 加载组合: 现金 {portfolio.get('cash', 0):.2f}")
    else:
        portfolio = {
            'date': datetime.datetime.now().strftime('%Y-%m-%d'),
            'cash': INITIAL_CAPITAL,
            'positions': {},
            'trades': []
        }
        log(f"🆕 创建新组合: 初始资金 {INITIAL_CAPITAL}")

def save_portfolio():
    """保存组合"""
    portfolio['date'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(PORTFOLIO_FILE, 'w', encoding='utf-8') as f:
        json.dump(portfolio, f, ensure_ascii=False, indent=2)

# ================= 交易执行 =================
@error_handler
def execute_trade():
    """执行交易 (调仓逻辑: 先卖后买)"""
    if not daily_signals or not portfolio:
        return
    
    cash = portfolio['cash']
    positions = portfolio['positions']
    
    # 汇总所有策略的看多股票
    all_long = {}
    for factor_name, sig in daily_signals.items():
        weight = strategies.get(factor_name, {}).get('weight', GRAY_WEIGHT)
        for symbol in sig['long']:
            if symbol not in all_long:
                all_long[symbol] = 0
            all_long[symbol] += weight
    
    # ================= 阶段1: 调仓卖出 =================
    # 找出需要卖出的股票
    symbols_to_sell = []
    for symbol in list(positions.keys()):
        pos = positions[symbol]
        
        # 卖出条件1: 不在任何策略的看多名单中
        if symbol not in all_long:
            symbols_to_sell.append((symbol, "信号消失"))
            continue
        
        # 卖出条件2: 持仓超过最大天数
        buy_time = datetime.datetime.strptime(pos['buy_time'], '%Y-%m-%d %H:%M:%S')
        holding_days = (datetime.datetime.now() - buy_time).days
        if holding_days >= MAX_HOLDING_DAYS:
            symbols_to_sell.append((symbol, f"持仓{holding_days}天到期"))
            continue
    
    # 执行卖出
    if symbols_to_sell:
        sell_symbols = [s[0] for s in symbols_to_sell]
        sell_prices = get_realtime_prices_batch(sell_symbols, batch_size=50)
        
        for symbol, reason in symbols_to_sell:
            price = sell_prices.get(symbol)
            if price is None or price < 0.01:
                log(f"⚠️ {symbol} 无法获取价格，暂缓卖出")
                continue
            
            pos = positions[symbol]
            shares = pos['shares']
            
            # 计算卖出收入 (扣除印花税+佣金)
            sell_amount = shares * price
            total_cost, net_revenue = functions.calculate_trade_costs(
                sell_amount, is_buy=False,
                commission=COMMISSION_RATE,
                stamp_duty=STAMP_DUTY_RATE,
                slippage=0  # 滑点已在价格中考虑
            )
            profit = net_revenue - pos['total_cost']
            
            # 记录交易
            portfolio['trades'].append({
                'type': 'sell',
                'symbol': symbol,
                'price': price,
                'shares': shares,
                'revenue': net_revenue,
                'profit': profit,
                'reason': reason,
                'time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'strategies': pos.get('strategies', [])
            })
            
            # 更新资金
            cash += net_revenue
            del positions[symbol]
            
            status = "🔴" if profit < 0 else "🟢"
            log(f"{status} 卖出 {symbol}: {shares}股 @ {price:.3f}元, 收益{profit:+.2f} ({reason})")
    
    # 更新组合现金
    portfolio['cash'] = cash
    
    # ================= 阶段2: 调仓买入 =================
    to_buy = {s: w for s, w in all_long.items() if s not in positions}
    
    if not to_buy:
        save_portfolio()
        return
    
    # 批量获取价格
    symbols_to_buy = list(to_buy.keys())
    prices = get_realtime_prices_batch(symbols_to_buy, batch_size=50)
    
    log(f"📡 批量获取 {len(symbols_to_buy)} 只股票价格, 成功 {len(prices)} 只")
    
    # 执行买入
    for symbol, total_weight in sorted(to_buy.items(), key=lambda x: -x[1]):
        price = prices.get(symbol)
        if price is None or price < 1:
            continue
        
        # 计算仓位
        trade_amount = cash * total_weight
        if trade_amount < MIN_CAPITAL_PER_TRADE:
            continue
        
        shares = int(trade_amount / price / 100) * 100  # 整手
        if shares < 100:
            continue
        
        # 计算买入成本
        buy_amount = shares * price
        total_cost, net_cost = functions.calculate_trade_costs(
            buy_amount, is_buy=True,
            commission=COMMISSION_RATE,
            stamp_duty=STAMP_DUTY_RATE,
            slippage=0  # 滑点已在价格中考虑
        )

        if net_cost > cash:
            continue

        # 执行买入
        positions[symbol] = {
            'shares': shares,
            'cost_price': price,
            'total_cost': net_cost,
            'buy_time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'strategies': [k for k, v in daily_signals.items() if symbol in v['long']]
        }
        cash -= net_cost
        portfolio['trades'].append({
            'type': 'buy',
            'symbol': symbol,
            'price': price,
            'shares': shares,
            'cost': net_cost,
            'time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        
        log(f"🟢 买入 {symbol}: {shares}股 @ {price:.3f}元, 成本{net_cost:.2f}")
    
    portfolio['cash'] = cash
    save_portfolio()

# ================= 性能追踪 (末位淘汰) =================
@error_handler
def update_performance():
    """更新策略性能"""
    if not os.path.exists(PERFORMANCE_FILE):
        performance = {'strategies': {}}
    else:
        with open(PERFORMANCE_FILE, 'r', encoding='utf-8') as f:
            performance = json.load(f)
    
    # 计算每个策略的收益
    for factor_name, config in strategies.items():
        if factor_name not in performance['strategies']:
            performance['strategies'][factor_name] = {
                'total_return': 0,
                'trades': 0,
                'wins': 0,
                'losses': 0
            }
    
    # 从交易记录更新
    for trade in portfolio.get('trades', []):
        if trade['type'] == 'sell':
            for strat in trade.get('strategies', []):
                if strat in performance['strategies']:
                    performance['strategies'][strat]['trades'] += 1
                    if trade.get('profit', 0) > 0:
                        performance['strategies'][strat]['wins'] += 1
                    else:
                        performance['strategies'][strat]['losses'] += 1
                    performance['strategies'][strat]['total_return'] += trade.get('profit', 0)
    
    with open(PERFORMANCE_FILE, 'w', encoding='utf-8') as f:
        json.dump(performance, f, ensure_ascii=False, indent=2)

# ================= 主循环 =================
def main():
    global running
    
    print("=" * 60)
    print("🚀 Alpha Factory 策略执行引擎 V1.0")
    print("=" * 60)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 初始化
    load_promoted_strategies()
    load_stock_pool()
    load_portfolio()
    
    last_signal_time = None
    
    log("🎯 引擎启动，等待交易时段...")
    
    while running:
        now = datetime.datetime.now()
        
        # 每日早盘加载策略
        if now.hour == 9 and now.minute < 30:
            if last_strategy_load is None or last_strategy_load.date() != now.date():
                load_promoted_strategies()
                generate_signals()
                last_signal_time = now
        
        # 交易时段
        if functions.is_trading_time(
            morning_start=MORNING_START,
            morning_end=MORNING_END,
            afternoon_start=AFTERNOON_START,
            afternoon_end=AFTERNOON_END
        ):
            execute_trade()
        
        # 收盘后更新性能
        if now.hour == 15 and now.minute < 10:
            update_performance()
        
        time.sleep(POLL_INTERVAL)
    
    save_portfolio()
    log("👋 引擎已停止")

if __name__ == "__main__":
    main()
