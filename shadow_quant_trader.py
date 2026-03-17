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

# ================= 核心配置区域 =================
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")

# 虚拟账户初始资金：50万人民币
INITIAL_CAPITAL = 500000.0 

# 模拟账本文件路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_FILE = os.path.join(SCRIPT_DIR, "portfolio.json")

# 监控标的 (支持ETF)
SYMBOLS = {
    "sz159819": "AI ETF",
    "sh000688": "科创50 ETF",
    "sh000300": "沪深300 ETF"
}

# 策略阈值参数 (例如：跌破均线、回撤买入等，这里以暴跌抄底为例)
# 真实场景中，这里可以接入 AI 的判断分数
BUY_DRAWDOWN = 0.10  # 回撤 10% 虚拟买入
SELL_PROFIT  = 0.15  # 盈利 15% 虚拟止盈
# ===============================================

def load_portfolio():
    """读取虚拟账本"""
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"读取账本失败，重建账本: {e}")
            
    # 如果没有账本，初始化一个全新的 50 万虚拟账户
    return {
        "cash": INITIAL_CAPITAL,
        "positions": {}, # 格式: {"sz159819": {"shares": 10000, "cost_price": 1.2}}
        "high_water_marks": {"sz159819": 1.573, "sh000688": 1424.52, "sh000300": 4050.00},
        "history": [] # 交易流水
    }

def save_portfolio(portfolio):
    """保存虚拟账本"""
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, indent=4)

def get_market_data(symbols):
    """获取真实的新浪实时行情"""
    url = f"http://hq.sinajs.cn/list={','.join(symbols)}"
    headers = {'Referer': 'http://finance.sina.com.cn'} 
    market_data = {}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.encoding = 'gbk'
        for line in response.text.strip().split('\n'):
            if '="' in line:
                symbol = line.split('=')[0].split('_')[-1]
                data = line.split('="')[1].split(';')[0].split(',')
                if len(data) > 3:
                    market_data[symbol] = {
                        "name": SYMBOLS.get(symbol, data[0]),
                        "current": float(data[3])
                    }
        return market_data
    except Exception as e:
        print(f"获取行情失败: {e}")
        return {}

def execute_trade(portfolio, symbol, name, action, price, amount_ratio=0.2):
    """
    虚拟交易执行器
    action: 'BUY' 或 'SELL'
    amount_ratio: 每次动用总仓位的比例 (默认20%，即10万元)
    """
    trade_msg = ""
    
    if action == "BUY":
        # 计算打算用多少钱买 (例如账户总资产的 20%)
        trade_amount = INITIAL_CAPITAL * amount_ratio
        if portfolio["cash"] < trade_amount:
            trade_amount = portfolio["cash"] # 如果现金不够，全仓买入剩余现金
            
        if trade_amount <= 100: # 没钱了
            return None
            
        # 算出能买多少股 (A股必须是100的整数倍)
        shares = int(trade_amount / price / 100) * 100
        actual_cost = shares * price
        
        # 扣除现金，增加持仓
        portfolio["cash"] -= actual_cost
        
        if symbol not in portfolio["positions"]:
            portfolio["positions"][symbol] = {"shares": shares, "cost_price": price}
        else:
            # 计算摊薄后的成本价
            old_shares = portfolio["positions"][symbol]["shares"]
            old_cost = portfolio["positions"][symbol]["cost_price"]
            new_shares = old_shares + shares
            new_cost_price = ((old_shares * old_cost) + actual_cost) / new_shares
            
            portfolio["positions"][symbol]["shares"] = new_shares
            portfolio["positions"][symbol]["cost_price"] = round(new_cost_price, 4)
            
        trade_msg = f"🟢 **虚拟买入**：{name} \n成交价: `{price}` | 数量: `{shares}股` | 耗资: `{actual_cost:.2f}元`"
        
    elif action == "SELL":
        if symbol not in portfolio["positions"]:
            return None
            
        shares_to_sell = portfolio["positions"][symbol]["shares"]
        cost_price = portfolio["positions"][symbol]["cost_price"]
        revenue = shares_to_sell * price
        profit = revenue - (shares_to_sell * cost_price)
        profit_pct = profit / (shares_to_sell * cost_price) * 100
        
        # 增加现金，清空持仓
        portfolio["cash"] += revenue
        del portfolio["positions"][symbol]
        
        trade_msg = f"🔴 **虚拟止盈**：{name} \n成交价: `{price}` | 获利: `{profit:.2f}元` ({profit_pct:.2f}%)"

    if trade_msg:
        # 记录交易流水
        portfolio["history"].append(f"[{datetime.date.today()}] {trade_msg.replace('**', '').replace('`', '')}")
        
    return trade_msg

def main():
    print(f"[{datetime.datetime.now()}] 启动影子交易模拟盘...")
    portfolio = load_portfolio()
    data = get_market_data(list(SYMBOLS.keys()))
    
    if not data:
        return

    trade_alerts = []
    
    # === 策略引擎核心逻辑 ===
    for sym, info in data.items():
        current_price = info["current"]
        name = info["name"]
        
        # 1. 更新最高点记忆
        if sym in portfolio["high_water_marks"]:
            if current_price > portfolio["high_water_marks"][sym]:
                portfolio["high_water_marks"][sym] = current_price
                
        # 2. 判断买入逻辑 (回撤抄底策略)
        high_price = portfolio["high_water_marks"].get(sym, current_price)
        drawdown = (high_price - current_price) / high_price
        
        if drawdown >= BUY_DRAWDOWN and sym not in portfolio["positions"]:
            # 触发买入！
            msg = execute_trade(portfolio, sym, name, "BUY", current_price)
            if msg: trade_alerts.append(msg)
            
        # 3. 判断卖出逻辑 (盈利止盈策略)
        if sym in portfolio["positions"]:
            cost_price = portfolio["positions"][sym]["cost_price"]
            profit_pct = (current_price - cost_price) / cost_price
            
            if profit_pct >= SELL_PROFIT:
                # 触发止盈！
                msg = execute_trade(portfolio, sym, name, "SELL", current_price)
                if msg: trade_alerts.append(msg)

    # === 计算虚拟账户总净值 ===
    total_market_value = 0.0
    holdings_str = ""
    for sym, pos in portfolio["positions"].items():
        if sym in data:
            curr_price = data[sym]["current"]
            market_val = pos["shares"] * curr_price
            total_market_value += market_val
            
            profit_pct = (curr_price - pos["cost_price"]) / pos["cost_price"] * 100
            holdings_str += f"- {data[sym]['name']}: {pos['shares']}股 | 浮盈: {profit_pct:.2f}%\n"
            
    total_assets = portfolio["cash"] + total_market_value
    total_return = (total_assets - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    # === 生成飞书汇报卡片 ===
    card_color = "green" if total_return >= 0 else "red"
    report = f"**💰 虚拟基金净值报告 (模拟盘)**\n\n"
    report += f"总资产: **{total_assets:.2f} 元**\n"
    report += f"累计收益: **{total_return:.2f}%**\n"
    report += f"可用现金: {portfolio['cash']:.2f} 元\n\n"
    
    if holdings_str:
        report += f"**📊 当前持仓**\n{holdings_str}\n"
    else:
        report += f"**📊 当前持仓**: 空仓防御中\n\n"
        
    if trade_alerts:
        report += f"**⚡ 今日交易动作**\n"
        for alert in trade_alerts:
            report += f"{alert}\n\n"
    else:
        report += f"*今日无交易信号触发，继续盯盘。*"

    # 发送飞书
    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "🤖 AI影子基金日终结算"},
                "template": card_color
            },
            "elements": [{"tag": "markdown", "content": report}]
        }
    }
    
    try:
        requests.post(FEISHU_WEBHOOK, json=payload)
        print("✅ 模拟盘状态已推送至飞书！")
    except Exception as e:
        print(f"飞书推送失败: {e}")

    # 保存账本
    save_portfolio(portfolio)

if __name__ == "__main__":
    main()