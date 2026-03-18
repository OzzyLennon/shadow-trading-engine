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
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())

load_env()

# ================= 核心系统配置 =================
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")
INITIAL_CAPITAL = 1000000.0
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_FILE = os.path.join(SCRIPT_DIR, "apex_portfolio.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "logs", "apex_daemon.log")
CONFIG_FILE = os.path.join(SCRIPT_DIR, "daily_config.json")

POLL_INTERVAL = 5  # 轮询间隔（秒）

# 严格交易时段
MORNING_START = (9, 30)
MORNING_END = (11, 30)
AFTERNOON_START = (13, 0)
AFTERNOON_END = (14, 57)

# 交易冷却期 (防连续开火)
COOLDOWN_MINUTES = 10      # 抄底后的冷却期建议长一点
ACCOUNT_COOLDOWN_MINUTES = 3

# 脏数据过滤
MIN_VALID_PRICE = 1.0
PRICE_CHANGE_LIMIT = 0.20

# ================= 🌟 终极圣杯股票池 (煤电一体化组合) =================
SYMBOLS = {
    "sh600886": "国投电力",
    "sh601088": "中国神华",
    "sh601991": "大唐发电"
}

# ================= 🌟 均值回归核心参数 (与 WFA 严丝合缝) =================
Z_SCORE_THRESHOLD = -1.5   # 买入阈值：极度恐慌的超跌
Z_SCORE_EXIT = 0.0         # 卖出阈值：情绪回归均值
MOMENTUM_WINDOW = 10       # Z-Score 观测窗口 (与回测对齐)
TRADE_RATIO = 0.3          # 每次动用资金的 30%

EMA_ALPHA = 0.3            # 微观结构滤波
EMA_PERIOD = 20            # 用于止盈的大周期均线计算

# 交易成本
SLIPPAGE = 0.002
STAMP_DUTY = 0.001
COMMISSION = 0.00025

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
    now = datetime.datetime.now()
    if now.weekday() >= 5: return False
    current_time = (now.hour, now.minute)
    if MORNING_START <= current_time < MORNING_END: return True
    if AFTERNOON_START <= current_time < AFTERNOON_END: return True
    return False

def is_in_cooldown(symbol):
    if symbol not in last_trade_times: return False
    return datetime.datetime.now() - last_trade_times[symbol] < datetime.timedelta(minutes=COOLDOWN_MINUTES)

def is_account_in_cooldown():
    global last_account_trade
    if last_account_trade is None: return False
    return datetime.datetime.now() - last_account_trade < datetime.timedelta(minutes=ACCOUNT_COOLDOWN_MINUTES)

def update_trade_time(symbol):
    global last_account_trade
    last_trade_times[symbol] = datetime.datetime.now()
    last_account_trade = datetime.datetime.now()

def calculate_ema(symbol, price):
    global ema_prices
    if symbol not in ema_prices:
        ema_prices[symbol] = price
        return price
    ema = EMA_ALPHA * price + (1 - EMA_ALPHA) * ema_prices[symbol]
    ema_prices[symbol] = ema
    return ema

def is_valid_price(symbol, price, name):
    global prev_prices
    if price <= 0 or price < MIN_VALID_PRICE: return False
    if symbol in prev_prices and prev_prices[symbol] > 0:
        change_pct = abs(price - prev_prices[symbol]) / prev_prices[symbol]
        if change_pct > PRICE_CHANGE_LIMIT: return False
    prev_prices[symbol] = price
    return True

def calculate_z_score(prices):
    """标准的 Z-Score 计算"""
    if len(prices) < 2: return 0.0
    returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
    if len(returns) < 2: return 0.0

    n = len(returns)
    mu = sum(returns) / n
    variance = sum((r - mu) ** 2 for r in returns) / (n - 1)
    sigma = math.sqrt(variance) if variance > 0 else 0.0001

    r_t = returns[-1]
    return (r_t - mu) / sigma if sigma > 0 else 0.0

def check_allow_trading():
    """检查 AI 大脑是否允许 Red Engine 交易（风控开关）"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                # 优先读取 red_engine_allow 字段（V3.0双控模式）
                if "red_engine_allow" in config:
                    return config.get("red_engine_allow", True)
                # 兼容旧字段
                return config.get("allow_trading", True)
    except: pass
    return True  # 默认允许

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

def save_portfolio(portfolio):
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, indent=4)

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

        if len(queue) < 5 or len(long_queue) < 5: continue

        current_z = calculate_z_score(queue)
        long_term_ema = sum(long_queue) / len(long_queue)

        # ==========================================
        # 🌟 纯正的均值回归：卖出逻辑 (完全剥离硬止损)
        # ==========================================
        if sym in p["positions"]:
            pos = p["positions"][sym]

            sell_reason = None
            # 止盈 1：Z-Score 恢复到 0 以上 (恐慌彻底消除)
            if current_z > Z_SCORE_EXIT:
                sell_reason = f"🏆 情绪回归常态 (Z={current_z:.2f})"
            # 止盈 2：价格强势反弹，站上长期均线
            elif smoothed_price > long_term_ema:
                sell_reason = f"🏆 价格回归均线"

            if sell_reason and pos["available_shares"] > 0:
                sell_shares = pos["available_shares"]
                actual_sell_price = smoothed_price * (1 - SLIPPAGE)
                sell_amount = sell_shares * actual_sell_price
                actual_revenue = sell_amount - (sell_amount * STAMP_DUTY) - (sell_amount * COMMISSION)
                profit_val = actual_revenue - (sell_shares * pos["cost"])

                p["cash"] += actual_revenue
                pos["total_shares"] -= sell_shares
                pos["available_shares"] = 0

                alerts.append(f"🔴 **{sell_reason}**\n卖出：{name} @ `{actual_sell_price:.3f}` | 盈亏：`{profit_val:.2f}元`")
                if pos["total_shares"] == 0: del p["positions"][sym]
                continue

        # ==========================================
        # 🌟 纯正的均值回归：买入逻辑 (极端恐慌抄底)
        # ==========================================
        if is_in_cooldown(sym) or is_account_in_cooldown(): continue

        # 核心触发器：Z-Score 小于设定的负阈值
        if current_z < Z_SCORE_THRESHOLD and p["cash"] >= 10000 and sym not in p["positions"]:
            # 记录日志
            log(f"🔍 检测到抄底信号: {name} Z={current_z:.2f} < {Z_SCORE_THRESHOLD}")

            trade_amount = p["cash"] * TRADE_RATIO
            actual_buy_price = smoothed_price * (1 + SLIPPAGE)
            shares = int(trade_amount / actual_buy_price / 100) * 100

            if shares > 0:
                buy_amount = shares * actual_buy_price
                p["cash"] -= (buy_amount + buy_amount * COMMISSION)

                p["positions"][sym] = {
                    "total_shares": shares, "available_shares": 0,
                    "cost": actual_buy_price, "peak_price": actual_buy_price
                }
                update_trade_time(sym)

                # 记录交易日志
                log(f"🟢 恐慌抄底触发! 买入 {name} {shares}股 @ {actual_buy_price:.3f}元")

                alerts.append(f"🟢 **恐慌抄底触发** (Z={current_z:.2f} < {Z_SCORE_THRESHOLD})\n买入：{name} @ `{actual_buy_price:.3f}` | `{shares}股`\n说明：煤电红利股大跌，左侧建仓。")

    if alerts: send_alert(alerts, total_assets, p["cash"])
    save_portfolio(p)

def main():
    global running
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    log("="*50)
    log("🚀 APEX 煤电红利抄底引擎 V5.0 (WFA 严选版)")
    log(f"🎯 核心策略: 均值回归 | Z-Score 阈值: {Z_SCORE_THRESHOLD}")
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
