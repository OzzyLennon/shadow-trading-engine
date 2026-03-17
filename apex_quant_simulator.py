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

INITIAL_CAPITAL = 1000000.0  # 胆子大一点，模拟盘直接给你 100 万起始资金
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_FILE = os.path.join(SCRIPT_DIR, "apex_portfolio.json")
CONFIG_FILE = os.path.join(SCRIPT_DIR, "daily_config.json")

# 极限扩张池：精选 A 股两市最具爆发力、最容易被游资盯上的 20 只猛兽
SYMBOLS = {
    # 科技与算力核心
    "sh601138": "工业富联", "sz000938": "紫光股份", "sz002371": "北方华创", "sh603019": "中科曙光",
    # 消费电子与汽车
    "sh601127": "赛力斯",   "sz002594": "比亚迪",   "sz002456": "欧菲光",   "sz002241": "歌尔股份",
    # 大金融与牛市旗手
    "sh600030": "中信证券", "sh601519": "大智慧",   "sh600999": "招商证券", "sh600036": "招商银行",
    # 妖股与高弹性医药/概念
    "sh600276": "恒瑞医药", "sh603259": "药明康德", "sz000538": "云南白药", "sz002714": "牧原股份",
    # 核心宽基 (留着防身)
    "sz159819": "人工智能ETF", "sh512880": "证券ETF", "sh513180": "恒生科技ETF", "sh512010": "医药ETF"
}

# ================= 顶级机构策略参数（默认值，会被AI大脑覆盖）==================
# 1. 游资点火策略 (Momentum Ignition)
MOMENTUM_WINDOW = 5      # 记录过去 5 次的价格 (如果是每分钟跑一次，就是过去5分钟)
SURGE_THRESHOLD = 0.015  # 窗口期内突然爆拉 1.5% -> 无脑买入追涨！

# 2. 动态追踪止盈 (Trailing Stop)
PROFIT_ACTIVATE = 0.05   # 盈利超过 5% 后，激活追踪止盈
TRAILING_DROP = 0.03     # 从最高点回撤 3% -> 瞬间砸盘卖出保住利润！

# 3. 铁血止损 (Hard Stop-Loss)
STOP_LOSS_PCT = -0.08    # 绝不补仓，亏损达到 8% 直接割肉斩仓！

# 4. 动态仓位比例 (每次动用现金的百分比)
TRADE_RATIO = 0.3   # 默认每次动用剩余现金的 30%
# ===============================================

def load_ai_config():
    """读取AI大脑下发的每日作战参数"""
    global SURGE_THRESHOLD, STOP_LOSS_PCT, TRADE_UNIT
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                # 只有当天的配置才生效
                if config.get("date") == str(datetime.date.today()):
                    SURGE_THRESHOLD = config.get("surge_threshold", SURGE_THRESHOLD)
                    STOP_LOSS_PCT = config.get("stop_loss_pct", STOP_LOSS_PCT)
                    TRADE_UNIT = config.get("trade_unit", TRADE_UNIT)
                    print(f"🧠 已加载AI大脑今日参数: 追涨{SURGE_THRESHOLD*100}%|止损{STOP_LOSS_PCT*100}%|子弹{TRADE_UNIT}元")
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
    
    # ===== 新增：读取大脑早上的决策 =====
    try:
        config_path = os.path.join(SCRIPT_DIR, "daily_config.json")
        with open(config_path, "r") as f:
            daily_cfg = json.load(f)
            # 动态覆盖原本写死的参数！
            global SURGE_THRESHOLD, STOP_LOSS_PCT, TRADE_RATIO
            SURGE_THRESHOLD = daily_cfg["surge_threshold"]
            STOP_LOSS_PCT = daily_cfg["stop_loss_pct"]
            TRADE_RATIO = daily_cfg["trade_ratio"]
            print(f"🧠 已加载AI大脑今日参数: 追涨{SURGE_THRESHOLD*100}%|止损{STOP_LOSS_PCT*100}%|开火比例{TRADE_RATIO*100}%")
    except Exception:
        print("未找到 AI 配置，使用默认写死的参数。")
    # ====================================

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
        # 模块 2：卖出逻辑 (必须拥有可卖筹码 available_shares > 0)
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
            
            # 策略 B: 铁血止损 (亏损达到 8% 立刻清仓)
            elif profit_pct <= STOP_LOSS_PCT:
                sell_reason = f"🩸 铁血止损触发 (亏损{profit_pct*100:.1f}%)"

            # 执行卖出
            if sell_reason and pos["available_shares"] > 0:
                sell_shares = pos["available_shares"]
                revenue = sell_shares * price
                profit_val = revenue - (sell_shares * pos["cost"])
                
                p["cash"] += revenue
                # 扣除股份
                pos["total_shares"] -= sell_shares
                pos["available_shares"] = 0 # 卖光了
                
                alerts.append(f"🔴 **{sell_reason}**\n卖出标的：{name}\n成交均价：`{price}` | 卖出数量：`{sell_shares}股`\n本笔盈亏：`{profit_val:.2f}元`")
                
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
                shares = int(trade_amount / price / 100) * 100
                if shares > 0:
                    cost = shares * price
                    p["cash"] -= cost
                    
                    # 写入新持仓，注意 available_shares 是 0！今天买的今天不能卖 (T+1)
                    p["positions"][sym] = {
                        "total_shares": shares,
                        "available_shares": 0, 
                        "cost": price,
                        "peak_price": price # 初始最高价就是买入价
                    }
                    alerts.append(f"🚀 **满级火力追涨** (瞬时涨速: +{velocity*100:.2f}%)\n买入标的：{name}\n成交均价：`{price}` | 买入数量：`{shares}股` (-{cost:.2f}元)\n⚠️ [系统锁定] 此筹码明日解锁。")

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
