import requests
import json
import datetime
import os
import math
import time
import signal
from core import functions
from core.config import load_env, load_config_with_fallback
from core.errors import create_error_handler, log_error, TradingSystemError
from core.logging_config import get_logger

# 加载环境变量和配置
load_env()
config = load_config_with_fallback()

# 初始化日志系统
logger = get_logger("apex_tech_hedge")
error_handler = create_error_handler(logger)

# ================= 核心配置区域 =================
FEISHU_WEBHOOK = config.api.feishu_webhook or ""
INITIAL_CAPITAL = config.initial_capital
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

# ================= 策略参数 (优化版) =================
POLL_INTERVAL = config.poll_interval
MOMENTUM_WINDOW = config.strategy.momentum_window      # Z-Score 计算窗口 (优化: 20)
VOLATILITY_WINDOW = config.strategy.volatility_window  # 波动率计算窗口 (优化: 120 = 10分钟)
VOLATILITY_THRESHOLD = config.strategy.volatility_threshold  # 低波动过滤阈值 3%
Z_BUY_THRESHOLD = config.strategy.z_buy_threshold     # 动量爆发买入 (Z > 1.5)
Z_SELL_THRESHOLD = config.strategy.z_sell_threshold    # 动量衰竭卖出 (Z < 0)
TRADE_RATIO = config.strategy.trade_ratio         # 每次动用总资金的 30%

# Beta计算参数 (新增)
BETA_MIN_POINTS = config.strategy.beta_min_points      # 最小数据点
BETA_WINDOW = config.strategy.beta_window              # Beta计算窗口

# 摩擦成本
SLIPPAGE = config.costs.slippage
COMMISSION = config.costs.commission
STAMP_DUTY = config.costs.stamp_duty        # 印花税（仅卖出）
SHORT_INTEREST = config.strategy.short_interest   # 模拟做空的额外融券/期指升水成本

# 静默期配置 (防止刷屏)
ALERT_COOLDOWN = config.strategy.alert_cooldown      # 同一股票同一状态，5分钟内不重复报警

running = True
prev_prices = {}
last_alert_time = {}       # 上次报警时间

# ================= 预热期配置 =================
# 每天首次启动需要5分钟预热 (60个点 * 5秒 = 300秒)
WARMUP_POINTS = VOLATILITY_WINDOW  # 60个点
warmup_complete = False  # 预热完成标志（全局变量）

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
    """检查是否为A股交易时间"""
    return functions.is_trading_time(
        morning_start=config.market_hours.morning_start,
        morning_end=config.market_hours.morning_end,
        afternoon_start=config.market_hours.afternoon_start,
        afternoon_end=config.market_hours.afternoon_end
    )

# ================= 统计与动态 Beta 计算 =================
def calc_returns(prices):
    return [(prices[i] - prices[i-1])/prices[i-1] for i in range(1, len(prices))]

def calculate_z_score(prices):
    """计算价格序列的Z-Score (使用改进版本)"""
    # 优先使用改进的价格偏离度Z-Score
    if len(prices) >= MOMENTUM_WINDOW:
        return functions.calculate_z_score_improved(prices, window=MOMENTUM_WINDOW)
    return functions.calculate_z_score(prices)

def calculate_dynamic_beta(stock_prices, bench_prices):
    """实时计算股票与基准的动态 Beta (使用改进版本)"""
    # 使用改进的稳健Beta计算
    return functions.calculate_dynamic_beta_improved(
        stock_prices, bench_prices, window=BETA_WINDOW
    )

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
@error_handler
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

@error_handler
def save_portfolio(p):
    with open(PORTFOLIO_FILE, "w") as f: json.dump(p, f, indent=4)

@error_handler
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
@error_handler
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
@error_handler
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
    global warmup_complete
    warmup_ready = True
    min_queue_len = float('inf')
    
    for sym, info in data.items():
        if sym not in p["queues"]: p["queues"][sym] = []
        p["queues"][sym].append(info["price"])
        if len(p["queues"][sym]) > VOLATILITY_WINDOW: p["queues"][sym].pop(0)
        min_queue_len = min(min_queue_len, len(p["queues"][sym]))
    
    # 预热期检查
    if min_queue_len < WARMUP_POINTS:
        if not warmup_complete:
            log(f"⏳ 引擎预热中... 需收集 {WARMUP_POINTS} 个数据点 (约{WARMUP_POINTS * POLL_INTERVAL}秒)")
            warmup_complete = True  # 标记预热已开始
        return  # 预热期不交易
    else:
        if warmup_complete != "DONE":
            log(f"🔥 引擎预热完成！开始交易")
            warmup_complete = "DONE"

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

        # 波动率用全部数据点计算
        is_low_vol, recent_vol = is_low_volatility(stock_q_full)

        # 计算RSI用于信号确认 (新增)
        rsi = functions.calculate_rsi(stock_q_full) if len(stock_q_full) >= 14 else None

        # ====== 卖出逻辑 (平仓对冲) ======
        if sym in p["positions"]:
            pos = p["positions"][sym]

            # 更新持仓峰值价格 (用于移动止损)
            if "peak_price" not in pos:
                pos["peak_price"] = pos["stock_cost"]
            if stock_price > pos["peak_price"]:
                pos["peak_price"] = stock_price

            sell_signal = False
            sell_reason = ""

            # 止损检查 (新增)
            stop_triggered, stop_reason = functions.check_stop_loss(
                {"cost": pos["stock_cost"], "peak_price": pos.get("peak_price", pos["stock_cost"])},
                stock_price, max_loss=0.10, trailing_stop=0.05
            )
            if stop_triggered:
                sell_signal = True
                sell_reason = stop_reason

            # 动量衰竭 (Z < 0) 触发双边平仓
            elif current_z < Z_SELL_THRESHOLD:
                sell_signal = True
                sell_reason = f"动量衰竭 (Z={current_z:.2f})"

            if sell_signal and pos["stock_available"] > 0:
                s_shares = pos["stock_available"]
                b_shares = pos["bench_shares"]

                # 结算多头
                sell_amount = s_shares * stock_price
                total_cost, s_revenue = functions.calculate_trade_costs(
                    sell_amount, is_buy=False,
                    commission=COMMISSION,
                    stamp_duty=STAMP_DUTY,
                    slippage=SLIPPAGE
                )
                s_profit = s_revenue - (s_shares * pos["stock_cost"])

                # 结算空头 (买回 ETF 还券)
                buy_amount = b_shares * bench_price
                total_cost, net_amount = functions.calculate_trade_costs(
                    buy_amount, is_buy=True,
                    commission=COMMISSION,
                    stamp_duty=0,  # 买回ETF无印花税
                    slippage=SLIPPAGE
                )
                # 加上做空利息成本
                short_interest_cost = buy_amount * SHORT_INTEREST
                b_cost = net_amount + short_interest_cost
                b_profit = (b_shares * pos["bench_short_price"]) - b_cost

                net_profit = s_profit + b_profit

                # 更新账本
                p["cash"] += (s_revenue - b_cost)
                del p["positions"][sym]

                alerts.append(f"🔴 **{sell_reason}**\n"
                              f"卖出多头: {name} | 平仓空头: {bench_name}\n"
                              f"多头盈亏: `{s_profit:.2f}` | 空头盈亏: `{b_profit:.2f}`\n"
                              f"**纯 Alpha 净赚: `{net_profit:.2f} 元`**")

        # ====== 买入逻辑 (低波蓄势 + 动量突破 + 多因子确认) ======
        else:
            # 多因子共振条件检查
            momentum_trigger = current_z > Z_BUY_THRESHOLD

            # 三因子共振：动量突破 + 低波动蓄势 + RSI确认
            if momentum_trigger and is_low_vol and p["cash"] > 20000:
                # 信号确认 (新增)
                confirmed, confirmations = functions.confirm_buy_signal(
                    z_score=current_z,
                    volume_ratio=1.0,
                    price_vs_ema=0,  # 动量策略不需要EMA偏离
                    rsi=rsi,
                    min_confirmations=1  # 降低确认要求，动量策略更宽松
                )

                if not confirmed:
                    continue

                dyn_beta = calculate_dynamic_beta(stock_q_full, bench_q_full)

                # 计算多头金额
                long_amount = functions.calculate_trade_amount(p["cash"], config.strategy.trade_ratio, min_trade_amount=20000)
                stock_shares = functions.calculate_shares(long_amount, stock_price, lot_size=100)

                # 计算空头金额 (Beta 中性配平)
                short_amount = long_amount * dyn_beta
                bench_shares = functions.calculate_shares(short_amount, bench_price, lot_size=100)

                if stock_shares > 0 and bench_shares > 0:
                    # 扣除多头成本
                    buy_amount = stock_shares * stock_price
                    total_cost, net_amount = functions.calculate_trade_costs(
                        buy_amount, is_buy=True,
                        commission=COMMISSION,
                        stamp_duty=STAMP_DUTY,
                        slippage=SLIPPAGE
                    )
                    p["cash"] -= net_amount

                    # 做空ETF获得现金收入
                    short_amount = bench_shares * bench_price
                    total_cost, net_amount = functions.calculate_trade_costs(
                        short_amount, is_buy=False,
                        commission=COMMISSION,
                        stamp_duty=STAMP_DUTY,
                        slippage=SLIPPAGE
                    )
                    p["cash"] += net_amount

                    p["positions"][sym] = {
                        "stock_shares": stock_shares,
                        "stock_available": 0, # T+1
                        "stock_cost": stock_price,
                        "peak_price": stock_price,  # 新增峰值价格
                        "bench_sym": bench_sym,
                        "bench_shares": bench_shares,
                        "bench_short_price": bench_price,
                        "beta_applied": dyn_beta
                    }

                    # 构建确认因子描述
                    confirm_desc = [k for k, v in confirmations.items() if v]
                    alerts.append(f"🚀 **低波蓄势 + 动量突破共振** (Z={current_z:.2f})\n"
                                  f"📊 近{VOLATILITY_WINDOW}个5秒波动率: `{recent_vol*100:.2f}%` (< 3% 低波门槛)\n"
                                  f"🟢 做多: {name} `{stock_shares}股`\n"
                                  f"🔴 做空: {bench_name} `{bench_shares}股`\n"
                                  f"📐 动态 Beta 配平: `β = {dyn_beta:.2f}`\n"
                                  f"✅ 确认因子: {', '.join(confirm_desc)}")
            
            # 动量触发但波动率过高 - 静默，不发送报警
            # elif momentum_trigger and not is_low_vol and p["cash"] > 20000:
            #     pass  # 不报警，避免刷屏

    if alerts: send_alert(alerts, p, data)
    save_portfolio(p)

def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    log("="*50)
    log("⚔️ APEX 科技动量对冲引擎 V5.1 (优化版)")
    log(f"🎯 策略: 低波蓄势({VOLATILITY_WINDOW}点<3%) + 动量突破 Z>{Z_BUY_THRESHOLD}")
    log(f"📊 窗口参数: MOMENTUM={MOMENTUM_WINDOW}, VOLATILITY={VOLATILITY_WINDOW}")
    log(f"📐 Beta计算: 窗口{BETA_WINDOW}, 最小{BETA_MIN_POINTS}点")
    log(f"🛡️ 空头基准: {', '.join(BENCHMARKS.values())}")
    log(f"⏳ 预热期: 需收集{WARMUP_POINTS}个数据点 (约{WARMUP_POINTS * POLL_INTERVAL}秒)")
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
