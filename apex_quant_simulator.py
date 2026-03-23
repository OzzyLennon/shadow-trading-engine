import requests
import json
import datetime
import os
import math
import time
import signal
import sys
from core import functions
from core.config import load_env, load_config_with_fallback
from core.errors import create_error_handler, log_error, TradingSystemError
from core.logging_config import get_logger

# 加载环境变量和配置
load_env()
config = load_config_with_fallback()

# 初始化日志系统
logger = get_logger("apex_quant_simulator")
error_handler = create_error_handler(logger)

# ================= 核心系统配置 =================
FEISHU_WEBHOOK = config.api.feishu_webhook or ""
INITIAL_CAPITAL = config.initial_capital
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_FILE = os.path.join(SCRIPT_DIR, "apex_portfolio.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "logs", "apex_daemon.log")
CONFIG_FILE = os.path.join(SCRIPT_DIR, "daily_config.json")

POLL_INTERVAL = config.poll_interval  # 轮询间隔（秒）

# 严格交易时段
MORNING_START = config.market_hours.morning_start
MORNING_END = config.market_hours.morning_end
AFTERNOON_START = config.market_hours.afternoon_start
AFTERNOON_END = config.market_hours.afternoon_end

# 交易冷却期 (防连续开火)
COOLDOWN_MINUTES = config.risk.cooldown_minutes      # 抄底后的冷却期建议长一点
ACCOUNT_COOLDOWN_MINUTES = config.risk.account_cooldown_minutes

# 脏数据过滤
MIN_VALID_PRICE = config.risk.min_valid_price
PRICE_CHANGE_LIMIT = config.risk.price_change_limit

# ================= 🌟 终极圣杯股票池 (煤电一体化组合) =================
SYMBOLS = config.symbols if config.symbols else {
    "sh600886": "国投电力",
    "sh601088": "中国神华",
    "sh601991": "大唐发电"
}

# ================= 🌟 均值回归核心参数 (优化版) =================
Z_SCORE_THRESHOLD = config.strategy.z_score_threshold   # 买入阈值：极度恐慌的超跌
Z_SCORE_EXIT = config.strategy.z_score_exit         # 卖出阈值：情绪回归均值
MOMENTUM_WINDOW = config.strategy.momentum_window       # Z-Score 观测窗口 (优化: 20)
TRADE_RATIO = config.strategy.trade_ratio          # 每次动用资金的 30%

EMA_ALPHA = config.strategy.ema_alpha            # 微观结构滤波 (优化: 0.15)
EMA_PERIOD = config.strategy.ema_period            # 用于止盈的大周期均线计算

# 止损参数 (新增)
STOP_LOSS = config.strategy.stop_loss             # 固定止损: 8%
TRAILING_STOP = config.strategy.trailing_stop     # 移动止损: 5%
USE_ADAPTIVE_THRESHOLD = config.strategy.use_adaptive_threshold  # 自适应阈值
MIN_CONFIRMATIONS = config.strategy.min_signal_confirmations     # 信号确认数

# 交易成本
SLIPPAGE = config.costs.slippage
STAMP_DUTY = config.costs.stamp_duty
COMMISSION = config.costs.commission

# ================= 全局状态 =================
running = True
last_trade_times = {}
last_account_trade = None
ema_prices = {}
portfolio_loaded = False  # 标记是否已加载过持仓
prev_prices = {}

def signal_handler(signum, frame):
    global running
    print("\n🛑 收到停止信号，正在优雅退出...")
    running = False

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

def is_trading_time():
    """检查是否为A股交易时间"""
    return functions.is_trading_time(
        morning_start=MORNING_START,
        morning_end=MORNING_END,
        afternoon_start=AFTERNOON_START,
        afternoon_end=AFTERNOON_END
    )

def is_in_cooldown(symbol):
    """检查股票是否在冷却期内"""
    return functions.is_in_cooldown(symbol, last_trade_times, COOLDOWN_MINUTES)

def is_account_in_cooldown():
    """检查账户是否在冷却期内"""
    global last_account_trade
    return functions.is_account_in_cooldown(last_account_trade, ACCOUNT_COOLDOWN_MINUTES)

def update_trade_time(symbol):
    global last_account_trade
    last_trade_times[symbol] = datetime.datetime.now()
    last_account_trade = datetime.datetime.now()

def calculate_ema(symbol, price):
    """计算指数移动平均（EMA）"""
    global ema_prices
    previous_ema = ema_prices.get(symbol)
    ema = functions.calculate_ema(price, previous_ema, EMA_ALPHA)
    ema_prices[symbol] = ema
    return ema

def is_valid_price(symbol, price, name):
    """检查价格有效性"""
    global prev_prices
    previous_price = prev_prices.get(symbol)
    valid, error_msg = functions.is_valid_price(
        price, previous_price, MIN_VALID_PRICE, PRICE_CHANGE_LIMIT
    )
    if valid:
        prev_prices[symbol] = price
    return valid

def calculate_z_score(prices):
    """标准的 Z-Score 计算 (使用改进版本)"""
    # 优先使用改进的价格偏离度Z-Score
    if len(prices) >= MOMENTUM_WINDOW:
        return functions.calculate_z_score_improved(prices, window=MOMENTUM_WINDOW)
    return functions.calculate_z_score(prices)

def check_allow_trading():
    """检查 AI 大脑是否允许 Red Engine 交易（风控开关）"""
    return config.red_engine_allow

@error_handler
def load_portfolio():
    global portfolio_loaded
    today_str = str(datetime.date.today())
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                p = json.load(f)
                if p.get("date") != today_str:
                    log("🌅 新的一天！解锁昨日冻结筹码...")
                    for sym, pos in p["positions"].items():
                        pos["available_shares"] = pos["total_shares"]
                    p["date"] = today_str
                    p["price_queue"] = {}   
                    p["long_ema_queue"] = {}
                elif not portfolio_loaded:
                    log("🔄 引擎重启，清空队列数据...")
                    p["price_queue"] = {}
                    p["long_ema_queue"] = {}
                    portfolio_loaded = True
                return p
        except Exception: pass
            
    return {"date": today_str, "cash": INITIAL_CAPITAL, "positions": {}, "price_queue": {}, "long_ema_queue": {}}

@error_handler
def save_portfolio(portfolio):
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, indent=4)

@error_handler
def get_market_data():
    url = f"http://hq.sinajs.cn/list={','.join(SYMBOLS.keys())}"
    headers = {'Referer': 'http://finance.sina.com.cn'}
    market_data = {}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.encoding = 'gbk'
        for line in response.text.strip().split('\n'):
            if '="' in line:
                sym = line.split('=')[0].split('_')[-1]
                data = line.split('="')[1].split(';')[0].split(',')
                if len(data) > 3:
                    market_data[sym] = {"name": SYMBOLS[sym], "current": float(data[3])}
        return market_data
    except Exception: return {}

def send_alert(alerts, total_assets, cash):
    return_pct = (total_assets - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    report = f"**🏆 煤电一体化引擎 V5.0 (均值回归)**\n\n"
    for alert in alerts: report += f"{alert}\n\n"
    report += f"---\n**💼 账户总览**\n动态总资产: **{total_assets:.2f} 元** (收益: {return_pct:.2f}%)\n可用现金流: {cash:.2f} 元\n"

    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": "⚡ APEX 抄底引擎警报"}, "template": "blue"},
            "elements": [{"tag": "markdown", "content": report}]
        }
    }
    try: requests.post(FEISHU_WEBHOOK, json=payload)
    except Exception: pass

@error_handler
def scan_market():
    p = load_portfolio()
    data = get_market_data()
    if not data: return

    # 检查风控开关
    if not check_allow_trading():
        log("🚫 AI风控哨兵：交易通道已关闭")
        return

    alerts = []
    total_market_value = sum(pos["total_shares"] * data[s]["current"] for s, pos in p["positions"].items() if s in data)
    total_assets = p["cash"] + total_market_value

    # 确保存储长周期队列的字典存在
    if "long_ema_queue" not in p: p["long_ema_queue"] = {}

    for sym, info in data.items():
        price = info["current"]
        name = info["name"]
        if not is_valid_price(sym, price, name): continue

        # 微观平滑
        smoothed_price = calculate_ema(sym, price)

        # 短期动量队列 (用于算 Z-Score)
        if sym not in p["price_queue"]: p["price_queue"][sym] = []
        p["price_queue"][sym].append(smoothed_price)
        if len(p["price_queue"][sym]) > MOMENTUM_WINDOW: p["price_queue"][sym].pop(0)

        # 长期均线队列 (用于均值回归止盈)
        if sym not in p["long_ema_queue"]: p["long_ema_queue"][sym] = []
        p["long_ema_queue"][sym].append(smoothed_price)
        if len(p["long_ema_queue"][sym]) > EMA_PERIOD: p["long_ema_queue"][sym].pop(0)

        queue = p["price_queue"][sym]
        long_queue = p["long_ema_queue"][sym]

        # 增加最小数据要求 (优化: 5 -> 10)
        if len(queue) < 10 or len(long_queue) < 5: continue

        current_z = calculate_z_score(queue)
        long_term_ema = sum(long_queue) / len(long_queue)

        # 自适应阈值调整 (新增)
        effective_threshold = Z_SCORE_THRESHOLD
        if USE_ADAPTIVE_THRESHOLD and len(queue) >= 20:
            effective_threshold = functions.adaptive_z_threshold(
                queue, base_threshold=Z_SCORE_THRESHOLD, lookback=20
            )

        # ==========================================
        # 🌟 改进的均值回归：卖出逻辑 (含止损)
        # ==========================================
        if sym in p["positions"]:
            pos = p["positions"][sym]

            sell_reason = None

            # 止损检查 (新增)
            stop_triggered, stop_reason = functions.check_stop_loss(
                pos, smoothed_price,
                max_loss=STOP_LOSS, trailing_stop=TRAILING_STOP
            )
            if stop_triggered and pos["available_shares"] > 0:
                sell_reason = f"🛡️ {stop_reason}"

            # 止盈 1：Z-Score 恢复到 0 以上 (恐慌彻底消除)
            elif current_z > Z_SCORE_EXIT:
                sell_reason = f"🏆 情绪回归常态 (Z={current_z:.2f})"
            # 止盈 2：价格强势反弹，站上长期均线
            elif smoothed_price > long_term_ema:
                sell_reason = f"🏆 价格回归均线"

            if sell_reason and pos["available_shares"] > 0:
                sell_shares = pos["available_shares"]
                actual_sell_price = smoothed_price * (1 - SLIPPAGE)
                sell_amount = sell_shares * actual_sell_price
                total_cost, actual_revenue = functions.calculate_trade_costs(
                    sell_amount, is_buy=False,
                    commission=COMMISSION,
                    stamp_duty=STAMP_DUTY,
                    slippage=0  # 滑点已包含在actual_sell_price中
                )
                profit_val = actual_revenue - (sell_shares * pos["cost"])

                p["cash"] += actual_revenue
                pos["total_shares"] -= sell_shares
                pos["available_shares"] = 0

                alerts.append(f"🔴 **{sell_reason}**\n卖出：{name} @ `{actual_sell_price:.3f}` | 盈亏：`{profit_val:.2f}元`")
                if pos["total_shares"] == 0: del p["positions"][sym]
                continue

        # ==========================================
        # 🌟 改进的均值回归：买入逻辑 (多因子确认)
        # ==========================================
        if is_in_cooldown(sym) or is_account_in_cooldown(): continue

        # 核心触发器：Z-Score 小于自适应阈值
        if current_z < effective_threshold and p["cash"] >= 10000 and sym not in p["positions"]:
            # 记录日志
            log(f"🔍 检测到抄底信号: {name} Z={current_z:.2f} < {effective_threshold:.2f}")

            # 多因子信号确认 (新增)
            price_vs_ema = (smoothed_price - long_term_ema) / long_term_ema
            rsi = functions.calculate_rsi(queue) if len(queue) >= 14 else None

            confirmed, confirmations = functions.confirm_buy_signal(
                z_score=current_z,
                volume_ratio=1.0,  # 暂无成交量数据，使用默认值
                price_vs_ema=price_vs_ema,
                rsi=rsi,
                min_confirmations=MIN_CONFIRMATIONS
            )

            if not confirmed:
                # 记录未确认的信号
                log(f"⚠️ 信号未确认: {confirmations}")
                continue

            trade_amount = functions.calculate_trade_amount(p["cash"], TRADE_RATIO, min_trade_amount=10000.0)
            actual_buy_price = smoothed_price * (1 + SLIPPAGE)
            shares = functions.calculate_shares(trade_amount, actual_buy_price, lot_size=100)

            if shares > 0:
                buy_amount = shares * actual_buy_price
                total_cost, net_amount = functions.calculate_trade_costs(
                    buy_amount, is_buy=True,
                    commission=COMMISSION,
                    stamp_duty=STAMP_DUTY,
                    slippage=0  # 滑点已包含在actual_buy_price中
                )
                p["cash"] -= net_amount

                p["positions"][sym] = {
                    "total_shares": shares, "available_shares": 0,
                    "cost": actual_buy_price, "peak_price": actual_buy_price
                }
                update_trade_time(sym)

                # 记录交易日志
                log(f"🟢 恐慌抄底触发! 买入 {name} {shares}股 @ {actual_buy_price:.3f}元")

                # 构建确认因子描述
                confirm_desc = [k for k, v in confirmations.items() if v]
                alerts.append(f"🟢 **恐慌抄底触发** (Z={current_z:.2f} < {effective_threshold:.2f})\n"
                              f"买入：{name} @ `{actual_buy_price:.3f}` | `{shares}股`\n"
                              f"确认因子: {', '.join(confirm_desc)}\n"
                              f"说明：煤电红利股大跌，左侧建仓。")

    if alerts: send_alert(alerts, total_assets, p["cash"])
    save_portfolio(p)

def main():
    global running
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    log("="*50)
    log("🚀 APEX 煤电红利抄底引擎 V5.1 (优化版)")
    log(f"🎯 核心策略: 均值回归 | Z-Score 阈值: {Z_SCORE_THRESHOLD}")
    log(f"📊 窗口参数: MOMENTUM={MOMENTUM_WINDOW}, EMA_ALPHA={EMA_ALPHA}")
    log(f"🛡️ 止损设置: 固定{STOP_LOSS*100:.0f}% | 移动{TRAILING_STOP*100:.0f}%")
    log(f"✅ 自适应阈值: {'启用' if USE_ADAPTIVE_THRESHOLD else '禁用'}")
    log(f"🔒 监控标的: {', '.join(SYMBOLS.values())}")
    log("="*50)

    while running:
        try:
            if is_trading_time(): scan_market()
            else: time.sleep(60); continue
            time.sleep(POLL_INTERVAL)
        except Exception as e:
            log(f"❌ 异常: {e}")
            time.sleep(10)
    log("👋 引擎已停止")

if __name__ == "__main__":
    main()
