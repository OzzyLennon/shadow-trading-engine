import requests
import json
import datetime
import os
import math
import time
import signal
import sys

# ================= 加载环境变量 =================
def load_env():
    """从 .env 文件加载环境变量"""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())

load_env()
# ===============================================

# ================= 极限火力配置区域 =================
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")

INITIAL_CAPITAL = 1000000.0
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_FILE = os.path.join(SCRIPT_DIR, "apex_portfolio.json")
CONFIG_FILE = os.path.join(SCRIPT_DIR, "daily_config.json")
STATS_FILE = os.path.join(SCRIPT_DIR, "trade_stats.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "logs", "apex_daemon.log")

# ================= 守护进程参数 =================
POLL_INTERVAL = 5  # 轮询间隔（秒）

# ================= 严格交易时段 =================
MORNING_START = (9, 30)   # 上午开盘 09:30
MORNING_END = (11, 30)    # 上午收盘 11:30
AFTERNOON_START = (13, 0) # 下午开盘 13:00
AFTERNOON_END = (14, 57)  # 下午收盘前（避开尾盘集合竞价）

# ================= 交易冷却期 =================
COOLDOWN_MINUTES = 5      # 买入后冷却期（分钟）
ACCOUNT_COOLDOWN_MINUTES = 2  # 账户级冷却期

# ================= 脏数据过滤 =================
MIN_VALID_PRICE = 1.0     # 有效价格下限
PRICE_CHANGE_LIMIT = 0.20 # 单次价格变化上限（20%），超过视为异常

# 默认股票池
DEFAULT_SYMBOLS = {
    "sh601138": "工业富联", "sz000938": "紫光股份", "sz002371": "北方华创", "sh603019": "中科曙光",
    "sh601127": "赛力斯", "sz002594": "比亚迪", "sz002456": "欧菲光", "sz002241": "歌尔股份",
    "sh600030": "中信证券", "sh601519": "大智慧", "sh600999": "招商证券", "sh600036": "招商银行",
    "sh600276": "恒瑞医药", "sh603259": "药明康德", "sz000538": "云南白药", "sz002714": "牧原股份",
    "sz159819": "人工智能ETF", "sh512880": "证券ETF", "sh513180": "恒生科技ETF", "sh512010": "医药ETF"
}

SYMBOLS = DEFAULT_SYMBOLS.copy()

# ================= 统计学策略参数 =================
MOMENTUM_WINDOW = 20
Z_SCORE_THRESHOLD = 2.0
SURGE_THRESHOLD = 0.015
STOP_LOSS_PCT = -0.08
PROFIT_ACTIVATE = 0.05
TRAILING_DROP = 0.03
TRADE_RATIO = 0.3

# ================= EMA 滤波参数 =================
EMA_ALPHA = 0.3  # EMA 平滑系数 (0-1, 越小越平滑)

# ================= 交易成本参数 =================
SLIPPAGE = 0.002
STAMP_DUTY = 0.001
COMMISSION = 0.00025

# ================= 凯利公式参数 =================
KELLY_FRACTION = 0.5

# ================= 全局状态 =================
running = True
last_trade_times = {}  # 每只股票的最后交易时间
last_account_trade = None  # 账户级最后交易时间
ema_prices = {}  # EMA 平滑价格缓存
prev_prices = {}  # 上一次有效价格（用于脏数据检测）

def signal_handler(signum, frame):
    """优雅退出信号处理"""
    global running
    print("\n🛑 收到停止信号，正在优雅退出...")
    running = False

def log(message):
    """日志输出"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {message}"
    print(log_line)
    
    try:
        log_dir = os.path.dirname(LOG_FILE)
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_line + "\n")
    except:
        pass

def is_trading_time():
    """
    严格检查交易时段（排雷）
    
    交易时段：
    - 上午: 09:30 - 11:30
    - 下午: 13:00 - 14:57（避开尾盘集合竞价）
    
    周末不交易
    """
    now = datetime.datetime.now()
    
    # 周末检查
    if now.weekday() >= 5:
        return False
    
    current_time = (now.hour, now.minute)
    
    # 上午时段: 09:30 - 11:30
    if MORNING_START <= current_time < MORNING_END:
        return True
    
    # 下午时段: 13:00 - 14:57
    if AFTERNOON_START <= current_time < AFTERNOON_END:
        return True
    
    return False

def is_in_cooldown(symbol):
    """检查股票是否在冷却期"""
    if symbol not in last_trade_times:
        return False
    
    last_time = last_trade_times[symbol]
    cooldown_delta = datetime.timedelta(minutes=COOLDOWN_MINUTES)
    
    return datetime.datetime.now() - last_time < cooldown_delta

def is_account_in_cooldown():
    """检查账户是否在冷却期"""
    global last_account_trade
    
    if last_account_trade is None:
        return False
    
    cooldown_delta = datetime.timedelta(minutes=ACCOUNT_COOLDOWN_MINUTES)
    return datetime.datetime.now() - last_account_trade < cooldown_delta

def update_trade_time(symbol):
    """更新交易时间记录"""
    global last_account_trade
    last_trade_times[symbol] = datetime.datetime.now()
    last_account_trade = datetime.datetime.now()

# ===============================================
# EMA 滤波器（过滤微观噪音）
# ===============================================

def calculate_ema(symbol, price):
    """
    EMA (指数移动平均) 滤波器
    
    EMA_t = α * price_t + (1-α) * EMA_{t-1}
    
    参数：
    - α = EMA_ALPHA (0.3)
    - α 越小，平滑效果越强
    
    作用：过滤 3 秒级 Tick 数据的随机噪音
    """
    global ema_prices
    
    if symbol not in ema_prices:
        ema_prices[symbol] = price
        return price
    
    # EMA 计算
    ema = EMA_ALPHA * price + (1 - EMA_ALPHA) * ema_prices[symbol]
    ema_prices[symbol] = ema
    
    return ema

# ===============================================
# 脏数据检测（排雷）
# ===============================================

def is_valid_price(symbol, price, name):
    """
    脏数据检测
    
    拦截条件：
    1. price <= 0 (除零保护)
    2. 价格过低 (< 1元，异常)
    3. 单次变化超过 20% (停牌/网络抖动)
    """
    global prev_prices
    
    # 检查 1: 价格必须为正
    if price <= 0:
        log(f"⚠️ 脏数据拦截: {name} price={price} (<=0)")
        return False
    
    # 检查 2: 价格下限
    if price < MIN_VALID_PRICE:
        log(f"⚠️ 脏数据拦截: {name} price={price} (低于下限)")
        return False
    
    # 检查 3: 单次变化上限
    if symbol in prev_prices:
        prev = prev_prices[symbol]
        if prev > 0:
            change_pct = abs(price - prev) / prev
            if change_pct > PRICE_CHANGE_LIMIT:
                log(f"⚠️ 异常波动拦截: {name} 变化{change_pct*100:.1f}% ({prev} → {price})")
                return False
    
    # 更新上一次有效价格
    prev_prices[symbol] = price
    
    return True

# ===============================================
# 统计学核心
# ===============================================

def calculate_statistics(prices):
    """Z-Score 计算"""
    if len(prices) < 2:
        return None, None, None
    
    returns = []
    for i in range(1, len(prices)):
        r = (prices[i] - prices[i-1]) / prices[i-1]
        returns.append(r)
    
    if len(returns) < 2:
        return None, None, None
    
    n = len(returns)
    mu = sum(returns) / n
    variance = sum((r - mu) ** 2 for r in returns) / (n - 1)
    sigma = math.sqrt(variance) if variance > 0 else 0.0001
    
    r_t = returns[-1]
    z_score = (r_t - mu) / sigma if sigma > 0 else 0
    
    return mu, sigma, z_score

def calculate_bollinger_bands(prices, k=2.0):
    """布林带"""
    if len(prices) < 5:
        return None, None, None
    
    mid = sum(prices) / len(prices)
    variance = sum((p - mid) ** 2 for p in prices) / len(prices)
    std = math.sqrt(variance)
    
    upper = mid + k * std
    lower = mid - k * std
    
    return mid, upper, lower

def calculate_kelly_fraction(win_rate, win_loss_ratio):
    """凯利公式"""
    if win_rate <= 0 or win_loss_ratio <= 0:
        return 0.1
    
    p = win_rate
    b = win_loss_ratio
    q = 1 - p
    
    numerator = b * p - q
    kelly = numerator / b
    
    kelly = max(0, min(kelly, 0.5))
    return kelly * KELLY_FRACTION

def load_trade_stats():
    """加载历史交易统计"""
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    
    return {
        "total_trades": 0,
        "win_trades": 0,
        "total_profit": 0,
        "total_loss": 0,
        "symbols": {}
    }

def save_trade_stats(stats):
    """保存交易统计"""
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=4, ensure_ascii=False)

def update_trade_stats(stats, symbol, profit):
    """更新交易统计"""
    stats["total_trades"] += 1
    
    if symbol not in stats["symbols"]:
        stats["symbols"][symbol] = {
            "trades": 0, "wins": 0, "total_profit": 0, "total_loss": 0
        }
    
    sym_stats = stats["symbols"][symbol]
    sym_stats["trades"] += 1
    
    if profit > 0:
        stats["win_trades"] += 1
        stats["total_profit"] += profit
        sym_stats["wins"] += 1
        sym_stats["total_profit"] += profit
    else:
        stats["total_loss"] += abs(profit)
        sym_stats["total_loss"] += abs(profit)
    
    save_trade_stats(stats)

def get_symbol_kelly_ratio(stats, symbol):
    """计算凯利比例"""
    if symbol not in stats["symbols"]:
        return TRADE_RATIO
    
    sym = stats["symbols"][symbol]
    trades = sym["trades"]
    
    if trades < 3:
        return TRADE_RATIO
    
    win_rate = sym["wins"] / trades
    avg_win = sym["total_profit"] / sym["wins"] if sym["wins"] > 0 else 0
    avg_loss = sym["total_loss"] / (trades - sym["wins"]) if (trades - sym["wins"]) > 0 else 1
    
    if avg_loss == 0:
        avg_loss = 1
    
    win_loss_ratio = avg_win / avg_loss
    kelly = calculate_kelly_fraction(win_rate, win_loss_ratio)
    
    return max(kelly, 0.05)

def calculate_var(portfolio_value, returns_history, confidence=0.99):
    """计算 VaR"""
    if len(returns_history) < 10:
        return 0, 0
    
    sorted_returns = sorted(returns_history)
    var_index = int(len(sorted_returns) * (1 - confidence))
    var_index = max(0, min(var_index, len(sorted_returns) - 1))
    
    var_return = sorted_returns[var_index]
    var = portfolio_value * abs(var_return) if var_return < 0 else 0
    var_pct = (var / portfolio_value) * 100 if portfolio_value > 0 else 0
    
    return var, var_pct

def load_ai_config():
    """读取 AI 配置"""
    global SURGE_THRESHOLD, STOP_LOSS_PCT, TRADE_RATIO, SYMBOLS, SLIPPAGE, STAMP_DUTY, COMMISSION, Z_SCORE_THRESHOLD
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                if config.get("date") == str(datetime.date.today()):
                    SURGE_THRESHOLD = config.get("surge_threshold", SURGE_THRESHOLD)
                    STOP_LOSS_PCT = config.get("stop_loss_pct", STOP_LOSS_PCT)
                    TRADE_RATIO = config.get("trade_ratio", TRADE_RATIO)
                    SLIPPAGE = config.get("slippage", SLIPPAGE)
                    STAMP_DUTY = config.get("stamp_duty", STAMP_DUTY)
                    COMMISSION = config.get("commission", COMMISSION)
                    Z_SCORE_THRESHOLD = config.get("z_score_threshold", Z_SCORE_THRESHOLD)
                    
                    if "symbols" in config and config["symbols"]:
                        SYMBOLS = config["symbols"]
                    
                    return True
        return False
    except Exception as e:
        log(f"⚠️ AI配置读取失败: {e}")
        return False

def load_portfolio():
    """加载账本"""
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
                return p
        except Exception: pass
            
    return {
        "date": today_str,
        "cash": INITIAL_CAPITAL,
        "positions": {},
        "price_queue": {},
        "history": [] 
    }

def save_portfolio(portfolio):
    """保存账本"""
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, indent=4)

def get_market_data(symbols):
    """获取市场数据"""
    url = f"http://hq.sinajs.cn/list={','.join(symbols)}"
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
                    market_data[sym] = {
                        "name": SYMBOLS.get(sym, data[0]),
                        "current": float(data[3])
                    }
        return market_data
    except Exception: return {}

def send_alert(alerts, total_assets, total_market_value, cash, win_rate, total_trades, win_trades):
    """发送飞书警报"""
    return_pct = (total_assets - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    report = f"**🔥 APEX 统计学引擎 v4.1 (排雷版)**\n\n"
    for alert in alerts:
        report += f"{alert}\n\n"
    
    report += f"---\n**💼 账户总览**\n"
    report += f"动态总资产: **{total_assets:.2f} 元** (收益: {return_pct:.2f}%)\n"
    report += f"持仓总市值: {total_market_value:.2f} 元\n"
    report += f"可用现金流: {cash:.2f} 元\n"
    report += f"历史胜率: {win_rate:.1f}% ({win_trades}/{total_trades})\n"

    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "⚡ APEX 实时引擎警报"},
                "template": "purple"
            },
            "elements": [{"tag": "markdown", "content": report}]
        }
    }
    try:
        requests.post(FEISHU_WEBHOOK, json=payload)
    except Exception as e:
        log(f"飞书推送失败: {e}")

def scan_market():
    """市场扫描"""
    p = load_portfolio()
    data = get_market_data(list(SYMBOLS.keys()))
    if not data:
        return
    
    trade_stats = load_trade_stats()
    alerts = []
    
    total_market_value = sum(pos["total_shares"] * data[s]["current"] for s, pos in p["positions"].items() if s in data)
    total_assets = p["cash"] + total_market_value
    
    # VaR 预警
    all_returns = []
    for sym in p["price_queue"]:
        prices = p["price_queue"][sym]
        for i in range(1, len(prices)):
            r = (prices[i] - prices[i-1]) / prices[i-1]
            all_returns.append(r)
    
    if len(all_returns) >= 10:
        var, var_pct = calculate_var(total_assets, all_returns)
        if var_pct > 3:
            alerts.append(f"⚠️ **VaR 风险警报**: {var:.2f}元 ({var_pct:.2f}%)")
    
    for sym, info in data.items():
        price = info["current"]
        name = info["name"]
        
        # ===== 脏数据检测 =====
        if not is_valid_price(sym, price, name):
            continue
        
        # ===== EMA 滤波 =====
        smoothed_price = calculate_ema(sym, price)
        
        # 更新价格队列（使用平滑后的价格）
        if sym not in p["price_queue"]:
            p["price_queue"][sym] = []
        p["price_queue"][sym].append(smoothed_price)
        
        if len(p["price_queue"][sym]) > MOMENTUM_WINDOW:
            p["price_queue"][sym].pop(0)

        # ===== 卖出逻辑 =====
        if sym in p["positions"]:
            pos = p["positions"][sym]
            
            if smoothed_price > pos["peak_price"]:
                pos["peak_price"] = smoothed_price

            profit_pct = (smoothed_price - pos["cost"]) / pos["cost"]
            drop_from_peak = (pos["peak_price"] - smoothed_price) / pos["peak_price"]
            
            sell_reason = None
            
            if profit_pct >= PROFIT_ACTIVATE and drop_from_peak >= TRAILING_DROP:
                sell_reason = f"🏆 追踪止盈 (回落{drop_from_peak*100:.1f}%)"
            elif profit_pct <= STOP_LOSS_PCT:
                sell_reason = f"🩸 铁血止损 (亏损{profit_pct*100:.1f}%)"

            if sell_reason and pos["available_shares"] > 0:
                sell_shares = pos["available_shares"]
                
                actual_sell_price = smoothed_price * (1 - SLIPPAGE)
                sell_amount = sell_shares * actual_sell_price
                stamp_duty_cost = sell_amount * STAMP_DUTY
                commission_cost = sell_amount * COMMISSION
                total_cost = stamp_duty_cost + commission_cost
                
                actual_revenue = sell_amount - total_cost
                profit_val = actual_revenue - (sell_shares * pos["cost"])
                
                update_trade_stats(trade_stats, sym, profit_val)
                
                p["cash"] += actual_revenue
                pos["total_shares"] -= sell_shares
                pos["available_shares"] = 0
                
                alerts.append(f"🔴 **{sell_reason}**\n卖出：{name} @ `{actual_sell_price:.3f}` | 盈亏：`{profit_val:.2f}元`")
                
                if pos["total_shares"] == 0:
                    del p["positions"][sym]
                continue

        # ===== 买入逻辑（含冷却期检查）=====
        
        # 冷却期检查 1: 股票级别
        if is_in_cooldown(sym):
            continue
        
        # 冷却期检查 2: 账户级别
        if is_account_in_cooldown():
            continue
        
        queue = p["price_queue"][sym]
        
        if len(queue) >= 5:
            mean, std, z_score = calculate_statistics(queue)
            mid, upper, lower = calculate_bollinger_bands(queue)
            
            buy_signal = False
            signal_reason = ""
            
            if z_score is not None and z_score >= Z_SCORE_THRESHOLD:
                buy_signal = True
                signal_reason = f"Z={z_score:.2f}"
            
            if upper is not None and smoothed_price > upper:
                buy_signal = True
                signal_reason = f"突破布林"
            
            velocity = (smoothed_price - queue[0]) / queue[0] if queue[0] > 0 else 0
            if velocity >= SURGE_THRESHOLD:
                buy_signal = True
                signal_reason = f"涨速{velocity*100:.1f}%"
            
            if buy_signal and p["cash"] >= 10000 and sym not in p["positions"]:
                kelly_ratio = get_symbol_kelly_ratio(trade_stats, sym)
                actual_ratio = min(TRADE_RATIO, kelly_ratio)
                
                trade_amount = p["cash"] * actual_ratio
                actual_buy_price = smoothed_price * (1 + SLIPPAGE)
                
                shares = int(trade_amount / actual_buy_price / 100) * 100
                if shares > 0:
                    buy_amount = shares * actual_buy_price
                    commission_cost = buy_amount * COMMISSION
                    total_cost = buy_amount + commission_cost
                    
                    p["cash"] -= total_cost
                    
                    p["positions"][sym] = {
                        "total_shares": shares,
                        "available_shares": 0, 
                        "cost": actual_buy_price,
                        "peak_price": actual_buy_price
                    }
                    
                    # 更新冷却期
                    update_trade_time(sym)
                    
                    alerts.append(f"🚀 **信号触发** ({signal_reason})\n买入：{name} @ `{actual_buy_price:.3f}` | `{shares}股`\n冷却期：{COOLDOWN_MINUTES}分钟")

    if alerts:
        win_rate = (trade_stats["win_trades"] / trade_stats["total_trades"] * 100) if trade_stats["total_trades"] > 0 else 0
        send_alert(alerts, total_assets, total_market_value, p["cash"], win_rate, trade_stats["total_trades"], trade_stats["win_trades"])

    save_portfolio(p)

def main():
    """守护进程主循环"""
    global running
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    log("="*50)
    log("🚀 APEX 统计学量化引擎 v4.1 (排雷版)")
    log(f"📊 轮询间隔: {POLL_INTERVAL}秒 | EMA滤波: α={EMA_ALPHA}")
    log(f"🔒 交易时段: {MORNING_START[0]:02d}:{MORNING_START[1]:02d}-{AFTERNOON_END[0]:02d}:{AFTERNOON_END[1]:02d}")
    log(f"❄️ 冷却期: 股票{COOLDOWN_MINUTES}分钟 | 账户{ACCOUNT_COOLDOWN_MINUTES}分钟")
    log("="*50)
    
    if load_ai_config():
        log(f"🧠 已加载AI参数 | 监控 {len(SYMBOLS)} 只标的")
    else:
        log("⚠️ 使用默认参数")
    
    last_config_check = datetime.datetime.now()
    config_check_interval = 300
    
    while running:
        try:
            now = datetime.datetime.now()
            
            if (now - last_config_check).total_seconds() > config_check_interval:
                if load_ai_config():
                    log("🔄 配置已更新")
                last_config_check = now
            
            # 严格交易时段检查
            if is_trading_time():
                scan_market()
            else:
                # 非交易时段，降低频率
                time.sleep(60)
                continue
            
            time.sleep(POLL_INTERVAL)
            
        except Exception as e:
            log(f"❌ 异常: {e}")
            time.sleep(10)
    
    log("👋 守护进程已停止")

if __name__ == "__main__":
    main()
