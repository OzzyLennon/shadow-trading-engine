import requests
import json
import datetime
import os
import math

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

INITIAL_CAPITAL = 1000000.0  # 模拟盘 100 万起始资金
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_FILE = os.path.join(SCRIPT_DIR, "apex_portfolio.json")
CONFIG_FILE = os.path.join(SCRIPT_DIR, "daily_config.json")
STATS_FILE = os.path.join(SCRIPT_DIR, "trade_stats.json")

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
MOMENTUM_WINDOW = 20        # 扩大窗口用于统计计算
Z_SCORE_THRESHOLD = 2.0     # Z-Score 阈值（95%置信度）
SURGE_THRESHOLD = 0.015     # 备用固定阈值
STOP_LOSS_PCT = -0.08       # 止损线
PROFIT_ACTIVATE = 0.05      # 止盈激活
TRAILING_DROP = 0.03        # 回撤止盈
TRADE_RATIO = 0.3           # 默认开火比例

# ================= 交易成本参数 =================
SLIPPAGE = 0.002
STAMP_DUTY = 0.001
COMMISSION = 0.00025

# ================= 凯利公式参数 =================
KELLY_FRACTION = 0.5        # 凯利系数折扣（使用半凯利，更保守）
# ===============================================

def calculate_statistics(prices):
    """计算收益率序列的统计量：均值、标准差、Z-Score"""
    if len(prices) < 2:
        return None, None, None
    
    # 计算收益率序列
    returns = []
    for i in range(1, len(prices)):
        r = (prices[i] - prices[i-1]) / prices[i-1]
        returns.append(r)
    
    if len(returns) < 2:
        return None, None, None
    
    # 计算均值和标准差
    n = len(returns)
    mean = sum(returns) / n
    
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0001
    
    # 计算最新收益率的 Z-Score
    latest_return = returns[-1]
    z_score = (latest_return - mean) / std if std > 0 else 0
    
    return mean, std, z_score

def calculate_bollinger_bands(prices, k=2.0):
    """计算布林带：中轨、上轨、下轨"""
    if len(prices) < 5:
        return None, None, None
    
    # 中轨 = 移动平均
    mid = sum(prices) / len(prices)
    
    # 标准差
    variance = sum((p - mid) ** 2 for p in prices) / len(prices)
    std = math.sqrt(variance)
    
    # 上下轨
    upper = mid + k * std
    lower = mid - k * std
    
    return mid, upper, lower

def calculate_kelly_ratio(win_rate, win_loss_ratio):
    """凯利公式：f* = (bp - q) / b
    - b = 赔率（盈亏比）
    - p = 胜率
    - q = 1 - p
    """
    if win_rate <= 0 or win_loss_ratio <= 0:
        return 0.1  # 默认保守值
    
    q = 1 - win_rate
    kelly = (win_loss_ratio * win_rate - q) / win_loss_ratio
    
    # 凯利公式可能给出负值或大于1的值，需要限制
    kelly = max(0, min(kelly, 0.5))
    
    # 使用半凯利（更保守）
    return kelly * KELLY_FRACTION

def load_trade_stats():
    """加载历史交易统计（用于凯利公式）"""
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
        "symbols": {}  # 每只股票的独立统计
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
    """根据历史数据计算某只股票的凯利比例"""
    if symbol not in stats["symbols"]:
        return TRADE_RATIO
    
    sym = stats["symbols"][symbol]
    trades = sym["trades"]
    
    if trades < 3:  # 样本太少，用默认值
        return TRADE_RATIO
    
    win_rate = sym["wins"] / trades
    
    # 计算平均盈亏比
    avg_win = sym["total_profit"] / sym["wins"] if sym["wins"] > 0 else 0
    avg_loss = sym["total_loss"] / (trades - sym["wins"]) if (trades - sym["wins"]) > 0 else 1
    
    if avg_loss == 0:
        avg_loss = 1
    
    win_loss_ratio = avg_win / avg_loss
    
    kelly = calculate_kelly_ratio(win_rate, win_loss_ratio)
    
    # 如果凯利值为0或负，使用最小保守值
    return max(kelly, 0.05)

def calculate_var(portfolio_value, prices_history, confidence=0.99):
    """计算 VaR (Value at Risk)
    简化版：使用历史模拟法
    """
    if len(prices_history) < 10:
        return 0
    
    # 计算历史收益率
    returns = []
    for i in range(1, len(prices_history)):
        r = (prices_history[i] - prices_history[i-1]) / prices_history[i-1]
        returns.append(r)
    
    returns.sort()
    
    # 取 (1 - confidence) 分位数
    var_index = int(len(returns) * (1 - confidence))
    var_return = returns[var_index]
    
    # VaR = 组合价值 × 最坏情况下的损失率
    var = portfolio_value * abs(var_return)
    
    return var

def load_ai_config():
    """读取AI大脑下发的每日作战参数"""
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
                        print(f"🎯 AI选股: 今日监控 {len(SYMBOLS)} 只标的")
                    
                    print(f"🧠 已加载AI参数: Z阈值={Z_SCORE_THRESHOLD}|追涨{SURGE_THRESHOLD*100}%|止损{STOP_LOSS_PCT*100}%|开火{TRADE_RATIO*100}%")
                    return
        print("⚠️ 未找到今日AI配置，使用默认参数")
    except Exception as e:
        print(f"⚠️ AI配置读取失败: {e}")

def load_portfolio():
    today_str = str(datetime.date.today())
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                p = json.load(f)
                if p.get("date") != today_str:
                    print("🌅 新的一天！系统正在为你解锁昨天买入的冻结筹码...")
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
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, indent=4)

def get_market_data(symbols):
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

def main():
    print(f"[{datetime.datetime.now()}] ⚡ APEX 统计学量化引擎 v3.0 启动...")
    
    # 加载配置
    load_ai_config()
    trade_stats = load_trade_stats()
    
    p = load_portfolio()
    data = get_market_data(list(SYMBOLS.keys()))
    if not data: return

    alerts = []
    
    # 计算组合总净值
    total_market_value = sum(pos["total_shares"] * data[s]["current"] for s, pos in p["positions"].items() if s in data)
    total_assets = p["cash"] + total_market_value
    
    # 计算 VaR（简化版：用所有价格序列）
    all_prices = []
    for sym in p["price_queue"]:
        all_prices.extend(p["price_queue"][sym])
    
    if all_prices:
        var = calculate_var(total_assets, all_prices)
        var_pct = (var / total_assets) * 100 if total_assets > 0 else 0
        
        # VaR 警报
        if var_pct > 3:  # VaR 超过 3%
            alerts.append(f"⚠️ **VaR 风险警报**: 今日潜在最大损失 `{var:.2f}元` ({var_pct:.2f}%)\n建议降低仓位或增加对冲。")
    
    for sym, info in data.items():
        price = info["current"]
        name = info["name"]
        if price <= 0: continue

        # 更新价格队列
        if sym not in p["price_queue"]:
            p["price_queue"][sym] = []
        p["price_queue"][sym].append(price)
        
        if len(p["price_queue"][sym]) > MOMENTUM_WINDOW:
            p["price_queue"][sym].pop(0)

        # ==========================================
        # 模块 2：卖出逻辑 (含凯利更新)
        # ==========================================
        if sym in p["positions"]:
            pos = p["positions"][sym]
            
            if price > pos["peak_price"]:
                pos["peak_price"] = price

            profit_pct = (price - pos["cost"]) / pos["cost"]
            drop_from_peak = (pos["peak_price"] - price) / pos["peak_price"]
            
            sell_reason = None
            
            # 追踪止盈
            if profit_pct >= PROFIT_ACTIVATE and drop_from_peak >= TRAILING_DROP:
                sell_reason = f"🏆 追踪止盈触发 (触顶回落{drop_from_peak*100:.1f}%)"
            
            # 铁血止损
            elif profit_pct <= STOP_LOSS_PCT:
                sell_reason = f"🩸 铁血止损触发 (亏损{profit_pct*100:.1f}%)"

            if sell_reason and pos["available_shares"] > 0:
                sell_shares = pos["available_shares"]
                
                actual_sell_price = price * (1 - SLIPPAGE)
                sell_amount = sell_shares * actual_sell_price
                stamp_duty_cost = sell_amount * STAMP_DUTY
                commission_cost = sell_amount * COMMISSION
                total_cost = stamp_duty_cost + commission_cost
                
                actual_revenue = sell_amount - total_cost
                profit_val = actual_revenue - (sell_shares * pos["cost"])
                
                # 更新交易统计（凯利公式用）
                update_trade_stats(trade_stats, sym, profit_val)
                
                p["cash"] += actual_revenue
                pos["total_shares"] -= sell_shares
                pos["available_shares"] = 0
                
                alerts.append(f"🔴 **{sell_reason}**\n卖出标的：{name}\n成交均价：`{actual_sell_price:.3f}` | 数量：`{sell_shares}股`\n本笔盈亏：`{profit_val:.2f}元`")
                
                if pos["total_shares"] == 0:
                    del p["positions"][sym]
                continue

        # ==========================================
        # 模块 3：统计学买入信号
        # ==========================================
        queue = p["price_queue"][sym]
        
        if len(queue) >= 5:
            # ===== 方法1: Z-Score 信号 =====
            mean, std, z_score = calculate_statistics(queue)
            
            # ===== 方法2: 布林带信号 =====
            mid, upper, lower = calculate_bollinger_bands(queue)
            
            # 综合信号判断
            buy_signal = False
            signal_reason = ""
            
            # Z-Score 突破（突破均值+N倍标准差）
            if z_score is not None and z_score >= Z_SCORE_THRESHOLD:
                buy_signal = True
                signal_reason = f"Z-Score={z_score:.2f}(>{Z_SCORE_THRESHOLD})"
            
            # 价格突破布林带上轨（动量信号）
            if upper is not None and price > upper:
                buy_signal = True
                signal_reason = f"突破布林上轨({upper:.2f})"
            
            # 备用：固定阈值
            velocity = (price - queue[0]) / queue[0] if queue[0] > 0 else 0
            if velocity >= SURGE_THRESHOLD:
                buy_signal = True
                signal_reason = f"涨速={velocity*100:.2f}%(>{SURGE_THRESHOLD*100}%)"
            
            if buy_signal and p["cash"] >= 10000 and sym not in p["positions"]:
                # 凯利公式计算最优仓位
                kelly_ratio = get_symbol_kelly_ratio(trade_stats, sym)
                
                # 取 AI 下发比例和凯利比例的最小值（更保守）
                actual_ratio = min(TRADE_RATIO, kelly_ratio)
                
                trade_amount = p["cash"] * actual_ratio
                actual_buy_price = price * (1 + SLIPPAGE)
                
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
                    
                    alerts.append(f"🚀 **统计学信号触发** ({signal_reason})\n买入标的：{name}\n成交均价：`{actual_buy_price:.3f}` | 数量：`{shares}股`\n仓位比例：`{actual_ratio*100:.1f}%` (凯利建议{kelly_ratio*100:.1f}%)\n⚠️ [T+1锁定] 明日解锁。")

    # === 生成战报 ===
    if alerts:
        total_market_value = sum(pos["total_shares"] * data[s]["current"] for s, pos in p["positions"].items() if s in data)
        total_assets = p["cash"] + total_market_value
        return_pct = (total_assets - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

        # 计算胜率
        win_rate = (trade_stats["win_trades"] / trade_stats["total_trades"] * 100) if trade_stats["total_trades"] > 0 else 0

        report = f"**🔥 APEX 统计学量化战报 v3.0**\n\n"
        for alert in alerts:
            report += f"{alert}\n\n"
        
        report += f"---\n**💼 账户总览 (初始100万)**\n"
        report += f"动态总资产: **{total_assets:.2f} 元** (收益: {return_pct:.2f}%)\n"
        report += f"持仓总市值: {total_market_value:.2f} 元\n"
        report += f"可用现金流: {p['cash']:.2f} 元\n"
        report += f"历史胜率: {win_rate:.1f}% ({trade_stats['win_trades']}/{trade_stats['total_trades']})\n"

        payload = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": "⚡ APEX 统计学引擎 v3.0"},
                    "template": "purple"
                },
                "elements": [{"tag": "markdown", "content": report}]
            }
        }
        try:
            requests.post(FEISHU_WEBHOOK, json=payload)
        except Exception as e: print("飞书推送异常")

    save_portfolio(p)
    print("✅ 扫描结束，账本已同步。")

if __name__ == "__main__":
    main()
