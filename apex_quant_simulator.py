import requests
import json
import datetime
import os

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

# 默认股票池（会被AI大脑动态覆盖）
DEFAULT_SYMBOLS = {
    "sh601138": "工业富联", "sz000938": "紫光股份", "sz002371": "北方华创", "sh603019": "中科曙光",
    "sh601127": "赛力斯", "sz002594": "比亚迪", "sz002456": "欧菲光", "sz002241": "歌尔股份",
    "sh600030": "中信证券", "sh601519": "大智慧", "sh600999": "招商证券", "sh600036": "招商银行",
    "sh600276": "恒瑞医药", "sh603259": "药明康德", "sz000538": "云南白药", "sz002714": "牧原股份",
    "sz159819": "人工智能ETF", "sh512880": "证券ETF", "sh513180": "恒生科技ETF", "sh512010": "医药ETF"
}

# 当前使用的股票池
SYMBOLS = DEFAULT_SYMBOLS.copy()

# ================= 顶级机构策略参数（默认值，会被AI大脑覆盖）==================
MOMENTUM_WINDOW = 5
SURGE_THRESHOLD = 0.015
PROFIT_ACTIVATE = 0.05
TRAILING_DROP = 0.03
STOP_LOSS_PCT = -0.08
TRADE_RATIO = 0.3

# ================= 交易成本参数 =================
SLIPPAGE = 0.002      # 滑点 0.2%
STAMP_DUTY = 0.001    # 印花税 0.1%（仅卖出）
COMMISSION = 0.00025  # 佣金 0.025%
# ===============================================

def load_ai_config():
    """读取AI大脑下发的每日作战参数（增强版）"""
    global SURGE_THRESHOLD, STOP_LOSS_PCT, TRADE_RATIO, SYMBOLS, SLIPPAGE, STAMP_DUTY, COMMISSION
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                # 只有当天的配置才生效
                if config.get("date") == str(datetime.date.today()):
                    # 加载策略参数
                    SURGE_THRESHOLD = config.get("surge_threshold", SURGE_THRESHOLD)
                    STOP_LOSS_PCT = config.get("stop_loss_pct", STOP_LOSS_PCT)
                    TRADE_RATIO = config.get("trade_ratio", TRADE_RATIO)
                    
                    # 加载交易成本
                    SLIPPAGE = config.get("slippage", SLIPPAGE)
                    STAMP_DUTY = config.get("stamp_duty", STAMP_DUTY)
                    COMMISSION = config.get("commission", COMMISSION)
                    
                    # 加载动态股票池
                    if "symbols" in config and config["symbols"]:
                        SYMBOLS = config["symbols"]
                        print(f"🎯 AI选股: 今日监控 {len(SYMBOLS)} 只标的")
                    
                    print(f"🧠 已加载AI参数: 追涨{SURGE_THRESHOLD*100}%|止损{STOP_LOSS_PCT*100}%|开火{TRADE_RATIO*100}%|滑点{SLIPPAGE*100}%")
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
                # ==========================================
                # 核心机制：A 股 T+1 跨日筹码解锁逻辑
                # ==========================================
                if p.get("date") != today_str:
                    print("🌅 新的一天！系统正在为你解锁昨天买入的冻结筹码...")
                    for sym, pos in p["positions"].items():
                        # 把所有筹码变成"可卖筹码"
                        pos["available_shares"] = pos["total_shares"]
                    p["date"] = today_str
                    # 清空昨天的价格队列，重新计算日内动量
                    p["price_queue"] = {} 
                return p
        except Exception: pass
            
    return {
        "date": today_str,
        "cash": INITIAL_CAPITAL,
        "positions": {}, # {"sh601138": {"total_shares": 1000, "available_shares": 0, "cost": 15.0, "peak_price": 15.0}}
        "price_queue": {}, # {"sh601138": [14.8, 14.9, 15.1]}
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
    print(f"[{datetime.datetime.now()}] ⚡ APEX 高频量化引擎扫描中...")
    
    # 加载AI大脑参数
    load_ai_config()
    
    p = load_portfolio()
    data = get_market_data(list(SYMBOLS.keys()))
    if not data: return

    alerts = []
    
    for sym, info in data.items():
        price = info["current"]
        name = info["name"]
        if price <= 0: continue

        # ==========================================
        # 模块 1：更新日内价格滑动窗口 (记录最近N次的价格)
        # ==========================================
        if sym not in p["price_queue"]:
            p["price_queue"][sym] = []
        p["price_queue"][sym].append(price)
        
        # 保持窗口长度不变（比如只留最近5次的快照）
        if len(p["price_queue"][sym]) > MOMENTUM_WINDOW:
            p["price_queue"][sym].pop(0)

        # ==========================================
        # 模块 2：卖出逻辑 (含滑点和交易成本)
        # ==========================================
        if sym in p["positions"]:
            pos = p["positions"][sym]
            
            # 更新该持仓的历史最高价 (为了追踪止盈)
            if price > pos["peak_price"]:
                pos["peak_price"] = price

            profit_pct = (price - pos["cost"]) / pos["cost"]
            drop_from_peak = (pos["peak_price"] - price) / pos["peak_price"]
            
            sell_reason = None
            
            # 策略 A: 追踪止盈 (利润超过5%后，只要从最高点回落3%立刻卖出)
            if profit_pct >= PROFIT_ACTIVATE and drop_from_peak >= TRAILING_DROP:
                sell_reason = f"🏆 追踪止盈触发 (触顶回落{drop_from_peak*100:.1f}%)"
            
            # 策略 B: 铁血止损 (亏损达到止损线立刻清仓)
            elif profit_pct <= STOP_LOSS_PCT:
                sell_reason = f"🩸 铁血止损触发 (亏损{profit_pct*100:.1f}%)"

            # 执行卖出
            if sell_reason and pos["available_shares"] > 0:
                sell_shares = pos["available_shares"]
                
                # ===== 计算真实成交价（含滑点）=====
                actual_sell_price = price * (1 - SLIPPAGE)  # 卖出滑点
                
                # ===== 计算交易成本 =====
                sell_amount = sell_shares * actual_sell_price
                stamp_duty_cost = sell_amount * STAMP_DUTY  # 印花税
                commission_cost = sell_amount * COMMISSION  # 佣金
                total_cost = stamp_duty_cost + commission_cost
                
                # 实际收入
                actual_revenue = sell_amount - total_cost
                profit_val = actual_revenue - (sell_shares * pos["cost"])
                
                p["cash"] += actual_revenue
                # 扣除股份
                pos["total_shares"] -= sell_shares
                pos["available_shares"] = 0 # 卖光了
                
                alerts.append(f"🔴 **{sell_reason}**\n卖出标的：{name}\n成交均价：`{actual_sell_price:.3f}` (滑点后) | 卖出数量：`{sell_shares}股`\n交易成本：`{total_cost:.2f}元` | 本笔盈亏：`{profit_val:.2f}元`")
                
                # 如果一股都没了，彻底删掉持仓记录
                if pos["total_shares"] == 0:
                    del p["positions"][sym]
                continue # 卖完就不考虑买了，看下一个股票

        # ==========================================
        # 模块 3：买入逻辑 (日内异动点火) - 狂暴版
        # ==========================================
        queue = p["price_queue"][sym]
        if len(queue) == MOMENTUM_WINDOW:
            # 计算滑动窗口内的涨速 (当前价 / N分钟前的价)
            velocity = (price - queue[0]) / queue[0]
            
            # 【核心修改点】：不再判断现金是否大于固定值，而是直接算比例！
            # 只要现金还大于 10000 元（最低买入底线），并且触发了阈值，且未持仓
            if velocity >= SURGE_THRESHOLD and p["cash"] >= 10000 and sym not in p["positions"]:
                # 动态计算本次应该打出多少子弹！
                trade_amount = p["cash"] * TRADE_RATIO
                
                # ===== 计算真实买入价（含滑点）=====
                actual_buy_price = price * (1 + SLIPPAGE)  # 买入滑点
                
                shares = int(trade_amount / actual_buy_price / 100) * 100
                if shares > 0:
                    # 计算实际成本
                    buy_amount = shares * actual_buy_price
                    commission_cost = buy_amount * COMMISSION  # 佣金
                    total_cost = buy_amount + commission_cost
                    
                    p["cash"] -= total_cost
                    
                    # 写入新持仓，成本价为滑点后价格
                    p["positions"][sym] = {
                        "total_shares": shares,
                        "available_shares": 0, 
                        "cost": actual_buy_price,  # 真实成本价
                        "peak_price": actual_buy_price
                    }
                    alerts.append(f"🚀 **满级火力追涨** (瞬时涨速: +{velocity*100:.2f}%)\n买入标的：{name}\n成交均价：`{actual_buy_price:.3f}` (滑点后) | 买入数量：`{shares}股`\n总成本：`{total_cost:.2f}元` (含佣金{commission_cost:.2f})\n⚠️ [系统锁定] 此筹码明日解锁。")

    # === 生成战报 ===
    if alerts:
        # 计算当前总净值
        total_market_value = sum(pos["total_shares"] * data[s]["current"] for s, pos in p["positions"].items() if s in data)
        total_assets = p["cash"] + total_market_value
        return_pct = (total_assets - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

        report = f"**🔥 APEX 巅峰高频量化战报**\n\n"
        for alert in alerts:
            report += f"{alert}\n\n"
        
        report += f"---\n**💼 账户总览 (初始100万)**\n"
        report += f"动态总资产: **{total_assets:.2f} 元** (收益: {return_pct:.2f}%)\n"
        report += f"持仓总市值: {total_market_value:.2f} 元\n"
        report += f"可用现金流: {p['cash']:.2f} 元\n"

        payload = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": "⚡ APEX 引擎极速交易警报"},
                    "template": "purple"  # 用高贵的紫色代表高频量化
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
