import requests
import json
import datetime
import os
import math
import time
import signal

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

# ================= 核心配置区域 =================
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")
INITIAL_CAPITAL = 1000000.0  
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_FILE = os.path.join(SCRIPT_DIR, "apex_tech_portfolio.json") # 独立的对冲账本
LOG_FILE = os.path.join(SCRIPT_DIR, "logs", "apex_tech_hedge.log")

# ================= 科技对冲专属标的池 =================
# 多头目标：高波科技先锋
TECH_SYMBOLS = {
    "sz300308": "中际旭创",
    "sh601138": "工业富联",
    "sz002371": "北方华创",
    "sh688256": "寒武纪"
}

# 空头基准：ETF替代期指
BENCHMARKS = {
    "sh512100": "中证1000ETF", # 对应中小盘科技
    "sh510300": "沪深300ETF"   # 对应大盘蓝筹
}

# 动态基准映射 (解决工业富联的基准错配问题)
HEDGE_MAPPING = {
    "sz300308": "sh512100", # 中际旭创 -> 中证1000
    "sh601138": "sh510300", # 工业富联 -> 沪深300
    "sz002371": "sh512100", # 北方华创 -> 中证1000
    "sh688256": "sh512100"  # 寒武纪 -> 中证1000
}

# ================= 策略参数 (低波蓄势 + 动量突破 + 动态对冲) =================
POLL_INTERVAL = 5
MOMENTUM_WINDOW = 20      # Z-Score 计算窗口 (取最后20个点)
VOLATILITY_WINDOW = 60    # 波动率计算窗口 (收集60个5秒数据点，约5分钟)
VOLATILITY_THRESHOLD = 0.03  # 低波动过滤阈值 3% (参数高原优化结果)
Z_BUY_THRESHOLD = 1.5     # 动量爆发买入 (Z > 1.5)
Z_SELL_THRESHOLD = 0.0    # 动量衰竭卖出 (Z < 0)
TRADE_RATIO = 0.3         # 每次动用总资金的 30%

# 摩擦成本
SLIPPAGE = 0.002
COMMISSION = 0.00025
STAMP_DUTY = 0.001        # 印花税（仅卖出）
SHORT_INTEREST = 0.0005   # 模拟做空的额外融券/期指升水成本

# 静默期配置 (防止刷屏)
ALERT_COOLDOWN = 300      # 同一股票同一状态，5分钟内不重复报警

running = True
prev_prices = {}
last_alert_time = {}       # 上次报警时间

# ================= 预热期配置 =================
# 每天首次启动需要5分钟预热 (60个点 * 5秒 = 300秒)
WARMUP_POINTS = VOLATILITY_WINDOW  # 60个点
WARMUP_LOGGED = False  # 预热完成标志

def signal_handler(signum, frame):
    global running
    print("\n🛑 收到停止信号，科技对冲引擎优雅退出...")
    running = False

def log(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f: f.write(line + "\n")
    except: pass

def is_trading_time():
    now = datetime.datetime.now()
    if now.weekday() >= 5: return False
    current_time = (now.hour, now.minute)
    if (9, 30) <= current_time < (11, 30): return True
    if (13, 0) <= current_time < (14, 57): return True
    return False

# ================= 统计与动态 Beta 计算 =================
def calc_returns(prices):
    return [(prices[i] - prices[i-1])/prices[i-1] for i in range(1, len(prices))]

def calculate_z_score(prices):
    if len(prices) < 2: return 0.0
    returns = calc_returns(prices)
    mu = sum(returns) / len(returns)
    variance = sum((r - mu)**2 for r in returns) / (len(returns)-1) if len(returns)>1 else 0
    sigma = math.sqrt(variance) if variance > 0 else 0.0001
    return (returns[-1] - mu) / sigma

def calculate_dynamic_beta(stock_prices, bench_prices):
    """实时计算股票与基准的动态 Beta"""
    min_len = min(len(stock_prices), len(bench_prices))
    if min_len < 5: return 1.0 # 数据不足，默认 1:1

    s_ret = calc_returns(stock_prices[-min_len:])
    b_ret = calc_returns(bench_prices[-min_len:])

    mean_s = sum(s_ret) / len(s_ret)
    mean_b = sum(b_ret) / len(b_ret)

    # 协方差 Cov(S, B)
    cov = sum((s - mean_s) * (b - mean_b) for s, b in zip(s_ret, b_ret)) / (len(s_ret)-1)
    # 基准方差 Var(B)
    var_b = sum((b - mean_b)**2 for b in b_ret) / (len(b_ret)-1)

    beta = cov / var_b if var_b > 0 else 1.0
    # 限制 Beta 范围，防止极端微观数据导致爆仓
    return max(0.5, min(beta, 2.5))

def calculate_volatility(prices, window=VOLATILITY_WINDOW):
    """
    计算近期波动率 (日收益率标准差)
    返回: 年化前的日收益率标准差
    """
    if len(prices) < window + 1:
        return float('inf')  # 数据不足，返回极大值，阻止交易
    
    returns = calc_returns(prices)
    recent_returns = returns[-window:]
    
    mean_ret = sum(recent_returns) / len(recent_returns)
    variance = sum((r - mean_ret) ** 2 for r in recent_returns) / (len(recent_returns) - 1)
    volatility = math.sqrt(variance) if variance > 0 else 0
    
    return volatility

def is_low_volatility(prices, threshold=VOLATILITY_THRESHOLD):
    """
    判断是否为低波动状态 (低波蓄势)
    排除近期已上蹿下跳、高度炒作的股票
    """
    vol = calculate_volatility(prices)
    return vol < threshold, vol

# ================= 账本与市场数据 =================
def load_portfolio():
    today = str(datetime.date.today())
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE, "r") as f:
                p = json.load(f)
                if p.get("date") != today:
                    for sym, pos in p["positions"].items():
                        pos["stock_available"] = pos["stock_shares"]
                    p["date"] = today
                    p["queues"] = {}
                return p
        except: pass
    return {"date": today, "cash": INITIAL_CAPITAL, "positions": {}, "queues": {}}

def save_portfolio(p):
    with open(PORTFOLIO_FILE, "w") as f: json.dump(p, f, indent=4)

def get_market_data():
    all_syms = list(TECH_SYMBOLS.keys()) + list(BENCHMARKS.keys())
    url = f"http://hq.sinajs.cn/list={','.join(all_syms)}"
    headers = {'Referer': 'http://finance.sina.com.cn'}
    data = {}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        res.encoding = 'gbk'
        for line in res.text.strip().split('\n'):
            if '="' in line:
                sym = line.split('=')[0].split('_')[-1]
                parts = line.split('="')[1].split(';')[0].split(',')
                if len(parts) > 3:
                    name = TECH_SYMBOLS.get(sym, BENCHMARKS.get(sym, parts[0]))
                    data[sym] = {"name": name, "price": float(parts[3])}
        return data
    except: return {}

def send_alert(alerts, p, data):
    # 计算动态净值 (现金 + 股票多头市值 - 做空需偿还市值)
    market_val = 0
    short_debt = 0
    for sym, pos in p["positions"].items():
        if sym in data and pos["bench_sym"] in data:
            market_val += pos["stock_shares"] * data[sym]["price"]
            short_debt += pos["bench_shares"] * data[pos["bench_sym"]]["price"]

    total_assets = p["cash"] + market_val - short_debt
    ret_pct = (total_assets - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    report = "**🛡️ APEX 科技动量对冲引擎 (Blue Engine)**\n\n"
    for a in alerts: report += f"{a}\n\n"
    report += f"---\n**💼 中性账户总览**\n动态总资产: **{total_assets:.2f} 元** (纯Alpha: {ret_pct:.2f}%)\n"
    report += f"多头总市值: {market_val:.2f} 元 | 空头总负债: {short_debt:.2f} 元\n"

    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": "⚔️ 科技中性对冲警报"}, "template": "blue"},
            "elements": [{"tag": "markdown", "content": report}]
        }
    }
    try: requests.post(FEISHU_WEBHOOK, json=payload)
    except: pass

# ================= 新增：读取 AI 风控权限 =================
def check_ai_permission():
    """检查 Blue Engine 的交易权限"""
    config_path = os.path.join(SCRIPT_DIR, "daily_config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                # 专门读取 Blue Engine 的权限字段
                if config.get("blue_engine_allow") is False:
                    return False, config.get("blue_reasoning", "AI 判定科技板块存在宏观风险")
        except:
            pass
    # 默认允许交易（防止配置文件读取失败导致停机）
    return True, "OK"

# ================= 核心扫描引擎 =================
def scan_market():
    # 1. 每次扫描前，先问问 AI 总司令给没给权限
    allow_trading, reason = check_ai_permission()

    if not allow_trading:
        # 如果被 AI 拔了网线，记录一条心跳日志并直接 return，不执行后续的买卖逻辑
        log(f"🔒 [风控熔断] Blue Engine 已被 AI 大脑锁定。原因: {reason}")
        return

    # 2. 以下为原有的数据拉取和交易扫描逻辑...
    p = load_portfolio()
    data = get_market_data()
    if not data: return
    alerts = []

    # 1. 更新所有监控标的的价格队列 (收集60个5秒数据点，约5分钟)
    global WARMUP_LOGGED
    warmup_ready = True
    min_queue_len = float('inf')
    
    for sym, info in data.items():
        if sym not in p["queues"]: p["queues"][sym] = []
        p["queues"][sym].append(info["price"])
        if len(p["queues"][sym]) > VOLATILITY_WINDOW: p["queues"][sym].pop(0)
        min_queue_len = min(min_queue_len, len(p["queues"][sym]))
    
    # 预热期检查
    if min_queue_len < WARMUP_POINTS:
        warmup_ready = False
        if not WARMUP_LOGGED:
            log(f"⏳ 引擎预热中... 已收集 {min_queue_len}/{WARMUP_POINTS} 个数据点 (约{min_queue_len * POLL_INTERVAL}秒)，剩余约{(WARMUP_POINTS - min_queue_len) * POLL_INTERVAL}秒可交易")
    elif not WARMUP_LOGGED:
        log(f"🔥 引擎预热完成！已收集 {min_queue_len} 个数据点，开始交易")
        WARMUP_LOGGED = True

    # 2. 遍历科技股，执行对冲策略
    for sym, name in TECH_SYMBOLS.items():
        if sym not in data: continue
        bench_sym = HEDGE_MAPPING[sym]
        if bench_sym not in data: continue

        stock_q_full = p["queues"][sym]
        bench_q_full = p["queues"][bench_sym]
        
        # 至少需要VOLATILITY_WINDOW个点才能计算波动率
        if len(stock_q_full) < VOLATILITY_WINDOW or len(bench_q_full) < VOLATILITY_WINDOW:
            continue
        
        # 动量Z-score用最后MOMENTUM_WINDOW个点（最近100秒）
        stock_q = stock_q_full[-MOMENTUM_WINDOW:] if len(stock_q_full) > MOMENTUM_WINDOW else stock_q_full
        bench_q = bench_q_full[-MOMENTUM_WINDOW:] if len(bench_q_full) > MOMENTUM_WINDOW else bench_q_full

        stock_price = data[sym]["price"]
        bench_price = data[bench_sym]["price"]
        bench_name = BENCHMARKS[bench_sym]

        current_z = calculate_z_score(stock_q)
        
        # 波动率用全部60个点计算
        is_low_vol, recent_vol = is_low_volatility(stock_q_full)

        # ====== 卖出逻辑 (平仓对冲) ======
        if sym in p["positions"]:
            pos = p["positions"][sym]

            # 动量衰竭 (Z < 0) 触发双边平仓
            if current_z < Z_SELL_THRESHOLD and pos["stock_available"] > 0:
                s_shares = pos["stock_available"]
                b_shares = pos["bench_shares"]

                # 结算多头
                s_revenue = s_shares * stock_price * (1 - SLIPPAGE - COMMISSION - STAMP_DUTY)
                s_profit = s_revenue - (s_shares * pos["stock_cost"])

                # 结算空头 (买回 ETF 还券)
                b_cost = b_shares * bench_price * (1 + SLIPPAGE + COMMISSION + SHORT_INTEREST)
                b_profit = (b_shares * pos["bench_short_price"]) - b_cost

                net_profit = s_profit + b_profit

                # 更新账本
                p["cash"] += (s_revenue - b_cost)
                del p["positions"][sym]

                alerts.append(f"🔴 **动量衰竭，双边平仓** (Z={current_z:.2f})\n"
                              f"卖出多头: {name} | 平仓空头: {bench_name}\n"
                              f"多头盈亏: `{s_profit:.2f}` | 空头盈亏: `{b_profit:.2f}`\n"
                              f"**纯 Alpha 净赚: `{net_profit:.2f} 元`**")

        # ====== 买入逻辑 (低波蓄势 + 动量突破 + 动态 Beta 做空) ======
        else:
            # 多因子共振条件检查
            momentum_trigger = current_z > Z_BUY_THRESHOLD
            
            # 双因子共振：动量突破 + 低波动蓄势
            if momentum_trigger and is_low_vol and p["cash"] > 20000:
                dyn_beta = calculate_dynamic_beta(stock_q, bench_q)

                # 计算多头金额
                long_amount = p["cash"] * TRADE_RATIO
                stock_shares = int(long_amount / stock_price / 100) * 100

                # 计算空头金额 (Beta 中性配平)
                short_amount = long_amount * dyn_beta
                bench_shares = int(short_amount / bench_price / 100) * 100

                if stock_shares > 0 and bench_shares > 0:
                    # 扣除多头成本
                    actual_long_cost = stock_shares * stock_price * (1 + SLIPPAGE + COMMISSION)
                    p["cash"] -= actual_long_cost
                    
                    # 做空ETF获得现金收入（这是关键！）
                    short_proceeds = bench_shares * bench_price * (1 - SLIPPAGE - COMMISSION)
                    p["cash"] += short_proceeds

                    p["positions"][sym] = {
                        "stock_shares": stock_shares,
                        "stock_available": 0, # T+1
                        "stock_cost": stock_price,
                        "bench_sym": bench_sym,
                        "bench_shares": bench_shares,
                        "bench_short_price": bench_price,
                        "beta_applied": dyn_beta
                    }

                    alerts.append(f"🚀 **低波蓄势 + 动量突破共振** (Z={current_z:.2f} > 1.5)\n"
                                  f"📊 近{VOLATILITY_WINDOW}个5秒波动率: `{recent_vol*100:.2f}%` (< 3% 低波门槛)\n"
                                  f"🟢 做多: {name} `{stock_shares}股`\n"
                                  f"🔴 做空: {bench_name} `{bench_shares}股`\n"
                                  f"📐 动态 Beta 配平: `β = {dyn_beta:.2f}`")
            
            # 调试信息：动量触发但波动率过高 (加静默期防刷屏)
            elif momentum_trigger and not is_low_vol and p["cash"] > 20000:
                # 检查静默期
                alert_key = f"{sym}_blocked"
                now = time.time()
                if alert_key in last_alert_time and now - last_alert_time[alert_key] < ALERT_COOLDOWN:
                    pass  # 静默期内，不报警
                else:
                    last_alert_time[alert_key] = now
                    alerts.append(f"⚠️ **动量突破被低波过滤拦截** (Z={current_z:.2f} > 1.5)\n"
                                  f"🚫 近{VOLATILITY_WINDOW}个5秒波动率: `{recent_vol*100:.2f}%` > 3%\n"
                                  f"📝 {name} 近期已炒作，等待回调蓄势")

    if alerts: send_alert(alerts, p, data)
    save_portfolio(p)

def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    log("="*50)
    log("⚔️ APEX 科技动量对冲引擎 (Blue Engine) 启动")
    log(f"🎯 策略: 低波蓄势({VOLATILITY_WINDOW}点<3%) + 动量突破 Z>{Z_BUY_THRESHOLD} | 动态 Beta 风险中性")
    log(f"🛡️ 空头基准: {', '.join(BENCHMARKS.values())}")
    log(f"⏳ 预热期: 需收集{WARMUP_POINTS}个5秒数据 (约{WARMUP_POINTS * POLL_INTERVAL}秒)")
    log("="*50)

    while running:
        try:
            if is_trading_time(): scan_market()
            else: time.sleep(60); continue
            time.sleep(POLL_INTERVAL)
        except Exception as e:
            log(f"❌ 引擎异常: {e}")
            time.sleep(10)
    log("👋 对冲引擎已停止")

if __name__ == "__main__":
    main()
