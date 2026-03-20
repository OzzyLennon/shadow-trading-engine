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
MOMENTUM_WINDOW = 20      # Z-Score 计算窗口
VOLATILITY_WINDOW = 60    # 波动率计算窗口 (参数高原优化结果)
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
HISTORY_DATA_DIR = os.path.join(SCRIPT_DIR, "research", "data")

running = True
prev_prices = {}
last_alert_time = {}       # 上次报警时间

# ================= 加载历史数据预热 =================
def load_history_prices(symbol, days=60):
    """
    从CSV加载历史收盘价用于波动率计算
    """
    csv_path = os.path.join(HISTORY_DATA_DIR, f"{symbol}_daily.csv")
    if not os.path.exists(csv_path):
        # CSV不存在，尝试自动下载
        download_history_data(symbol)
        if not os.path.exists(csv_path):
            return []
    
    return load_csv_prices(csv_path, days)

def download_history_data(symbol):
    """
    自动下载历史数据（60天）
    """
    import requests
    import time
    
    csv_path = os.path.join(HISTORY_DATA_DIR, f"{symbol}_daily.csv")
    if os.path.exists(csv_path):
        return True
    
    # 尝试新浪API
    url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=0&datalen=1024"
    
    try:
        log(f"📥 自动下载 {symbol} 历史数据...")
        res = requests.get(url, timeout=15)
        res.encoding = 'utf-8'
        
        import json
        data = json.loads(res.text)
        
        if not data or not isinstance(data, list):
            log(f"⚠️ {symbol} 无历史数据")
            return False
        
        # 写入CSV
        with open(csv_path, 'w') as f:
            f.write("date,code,open,high,low,close,preclose,volume,amount,turn,tradestatus,pctChg\n")
            
            preclose = None
            for day in reversed(data):
                close_price = float(day['close'])
                
                if preclose is None:
                    preclose = close_price
                
                pct = (close_price - preclose) / preclose * 100 if preclose > 0 else 0
                
                f.write(f"{day['day']},{symbol},{day['open']},{day['high']},{day['low']},{close_price},{preclose},{day['volume']},0,0,1,{pct:.4f}\n")
                preclose = close_price
        
        log(f"✅ {symbol} 历史数据下载完成 ({len(data)} 条)")
        time.sleep(0.3)  # 避免请求过快
        return True
        
    except Exception as e:
        log(f"❌ {symbol} 下载失败: {e}")
        return False

def load_csv_prices(csv_path, days=60):
    """
    从CSV文件读取最近N天收盘价
    """
    try:
        with open(csv_path, 'r') as f:
            lines = f.readlines()
        
        prices = []
        for line in reversed(lines[1:]):  # 从最新往前读
            parts = line.strip().split(',')
            if len(parts) >= 5:
                try:
                    close = float(parts[5])  # close列
                    prices.append(close)
                    if len(prices) >= days:
                        break
                except:
                    continue
        
        return list(reversed(prices))  # 恢复时间顺序（旧->新）
    except Exception as e:
        log(f"⚠️ 读取CSV失败 {csv_path}: {e}")
        return []

def preload_history_to_queue(p):
    """
    启动时预热队列，填充历史收盘价
    自动检测并下载缺失数据
    """
    all_syms = list(TECH_SYMBOLS.keys()) + list(BENCHMARKS.keys())
    loaded = 0
    
    for sym in all_syms:
        # 尝试加载CSV，不存在则自动下载
        history = load_history_prices(sym, days=VOLATILITY_WINDOW + 10)
        
        if history:
            # 历史数据用于波动率计算（需要60天日收益率）
            if "history_prices" not in p:
                p["history_prices"] = {}
            p["history_prices"][sym] = history
            
            # 实时队列只需要最新价格
            if sym not in p["queues"]:
                p["queues"][sym] = []
            # 用最近的一个历史价格初始化实时队列
            if history:
                p["queues"][sym] = [history[-1]]
            
            loaded += 1
            log(f"📊 {sym} 预加载 {len(history)} 天历史数据用于波动率")
        else:
            log(f"⚠️ {sym} 无历史数据，将使用实时数据")
    
    if loaded > 0:
        save_portfolio(p)
        log(f"✅ 历史数据预热完成，{loaded}/{len(all_syms)} 只标的")
    
    return p

def get_volatility_data(p, symbol):
    """
    获取用于波动率计算的价格序列
    优先使用历史日线数据，不足时用实时队列补齐
    """
    history = p.get("history_prices", {}).get(symbol, [])
    
    # 如果有完整的历史日线数据（>=60天），直接返回
    if len(history) >= VOLATILITY_WINDOW:
        return history
    
    # 历史数据不足，用实时队列补充
    realtime = p.get("queues", {}).get(symbol, [])
    
    # 合并：历史日线 + 实时数据
    combined = history + realtime
    
    # 确保有足够的数据点
    if len(combined) < VOLATILITY_WINDOW:
        return None  # 数据不足
    
    return combined[-VOLATILITY_WINDOW:]

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

    # 1. 更新实时价格队列（仅用于动量Z-score计算，5秒粒度）
    for sym, info in data.items():
        if sym not in p["queues"]: p["queues"][sym] = []
        p["queues"][sym].append(info["price"])
        if len(p["queues"][sym]) > MOMENTUM_WINDOW: p["queues"][sym].pop(0)
    
    # 2. 更新历史日线数据（仅用于波动率计算，不自动追加实时数据）
    # 历史数据在启动时预热，之后只更新已有历史，不混入实时数据

    # 2. 遍历科技股，执行对冲策略
    for sym, name in TECH_SYMBOLS.items():
        if sym not in data: continue
        bench_sym = HEDGE_MAPPING[sym]
        if bench_sym not in data: continue

        stock_q = p["queues"][sym]
        bench_q = p["queues"][bench_sym]
        if len(stock_q) < 5 or len(bench_q) < 5: continue

        stock_price = data[sym]["price"]
        bench_price = data[bench_sym]["price"]
        bench_name = BENCHMARKS[bench_sym]

        current_z = calculate_z_score(stock_q)

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
            # 获取用于波动率计算的历史日线数据
            vol_prices = get_volatility_data(p, sym)
            
            # 多因子共振条件检查
            momentum_trigger = current_z > Z_BUY_THRESHOLD
            
            # 使用历史日线数据计算波动率，而不是实时队列
            if vol_prices and len(vol_prices) >= VOLATILITY_WINDOW:
                is_low_vol, recent_vol = is_low_volatility(vol_prices)
            else:
                is_low_vol, recent_vol = False, float('inf')  # 数据不足时阻止买入
            
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
                                  f"📊 近期{VOLATILITY_WINDOW}日波动率: `{recent_vol*100:.2f}%` (< 3% 低波门槛)\n"
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
                                  f"🚫 近期{VOLATILITY_WINDOW}日波动率: `{recent_vol*100:.2f}%` > 3%\n"
                                  f"📝 {name} 近期已炒作，等待回调蓄势")

    if alerts: send_alert(alerts, p, data)
    save_portfolio(p)

def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    log("="*50)
    log("⚔️ APEX 科技动量对冲引擎 (Blue Engine) 启动")
    log(f"🎯 策略: 低波蓄势(60日<3%) + 动量突破 Z>{Z_BUY_THRESHOLD} | 动态 Beta 风险中性")
    log(f"🛡️ 空头基准: {', '.join(BENCHMARKS.values())}")
    log("="*50)

    # 预热：从CSV加载历史数据填充队列
    p = load_portfolio()
    p = preload_history_to_queue(p)
    save_portfolio(p)

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
