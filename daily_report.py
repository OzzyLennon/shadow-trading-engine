#!/usr/bin/env python3
"""
APEX 双引擎收盘汇报系统
每日 15:00 自动发送收益汇总到飞书
"""

import json
import requests
import datetime
import os

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

# ================= 配置 =================
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RED_PORTFOLIO = os.path.join(SCRIPT_DIR, "apex_portfolio.json")
BLUE_PORTFOLIO = os.path.join(SCRIPT_DIR, "apex_tech_portfolio.json")

RED_SYMBOLS = {
    "sh600886": "国投电力",
    "sh601088": "中国神华",
    "sh601991": "大唐发电"
}

BLUE_SYMBOLS = {
    "sz300308": "中际旭创",
    "sh601138": "工业富联",
    "sz002371": "北方华创",
    "sh688256": "寒武纪"
}

BENCHMARKS = {
    "sh512100": "中证1000ETF",
    "sh510300": "沪深300ETF"
}

# ================= 获取实时价格 =================
def get_all_prices():
    all_syms = list(RED_SYMBOLS.keys()) + list(BLUE_SYMBOLS.keys()) + list(BENCHMARKS.keys())
    url = f"http://hq.sinajs.cn/list={','.join(all_syms)}"
    headers = {'Referer': 'http://finance.sina.com.cn'}
    
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.encoding = 'gbk'
        prices = {}
        for line in res.text.strip().split('\n'):
            if '="' in line:
                sym = line.split('=')[0].split('_')[-1]
                parts = line.split('="')[1].split(';')[0].split(',')
                if len(parts) > 3:
                    prices[sym] = float(parts[3])
        return prices
    except Exception as e:
        print(f"获取价格失败: {e}")
        return {}

# ================= 计算Red Engine资产 =================
def calc_red_assets(prices):
    try:
        with open(RED_PORTFOLIO, 'r') as f:
            p = json.load(f)
        
        cash = p.get('cash', 0)
        market_val = 0
        positions_detail = []
        
        for sym, pos in p.get('positions', {}).items():
            shares = pos.get('total_shares', 0)
            if sym in prices and shares > 0:
                price = prices[sym]
                val = shares * price
                cost = pos.get('cost', 0)
                profit = (price - cost) * shares
                profit_pct = (price - cost) / cost * 100 if cost > 0 else 0
                
                market_val += val
                positions_detail.append({
                    'symbol': sym,
                    'name': RED_SYMBOLS.get(sym, sym),
                    'shares': shares,
                    'price': price,
                    'cost': cost,
                    'value': val,
                    'profit': profit,
                    'profit_pct': profit_pct
                })
        
        total = cash + market_val
        ret = (total - 1000000) / 1000000 * 100
        
        return {
            'cash': cash,
            'market_val': market_val,
            'total': total,
            'return_pct': ret,
            'positions': positions_detail
        }
    except Exception as e:
        return {'error': str(e)}

# ================= 计算Blue Engine资产 =================
def calc_blue_assets(prices):
    try:
        with open(BLUE_PORTFOLIO, 'r') as f:
            p = json.load(f)
        
        cash = p.get('cash', 0)
        market_val = 0
        short_debt = 0
        positions_detail = []
        
        for sym, pos in p.get('positions', {}).items():
            shares = pos.get('stock_shares', 0)
            bench_sym = pos.get('bench_sym', '')
            bench_shares = pos.get('bench_shares', 0)
            
            if sym in prices and shares > 0:
                price = prices[sym]
                val = shares * price
                cost = pos.get('stock_cost', 0)
                profit = (price - cost) * shares
                profit_pct = (price - cost) / cost * 100 if cost > 0 else 0
                
                market_val += val
                
                # 计算空头负债
                if bench_sym in prices and bench_shares > 0:
                    bench_price = prices[bench_sym]
                    short_debt += bench_shares * bench_price
                    bench_name = BENCHMARKS.get(bench_sym, bench_sym)
                
                positions_detail.append({
                    'symbol': sym,
                    'name': BLUE_SYMBOLS.get(sym, sym),
                    'shares': shares,
                    'price': price,
                    'cost': cost,
                    'value': val,
                    'profit': profit,
                    'profit_pct': profit_pct,
                    'bench_name': bench_name,
                    'bench_shares': bench_shares
                })
        
        total = cash + market_val - short_debt
        ret = (total - 1000000) / 1000000 * 100
        
        return {
            'cash': cash,
            'market_val': market_val,
            'short_debt': short_debt,
            'total': total,
            'return_pct': ret,
            'positions': positions_detail
        }
    except Exception as e:
        return {'error': str(e)}

# ================= 发送飞书报告 =================
def send_daily_report():
    prices = get_all_prices()
    if not prices:
        print("无法获取价格数据，跳过汇报")
        return
    
    red = calc_red_assets(prices)
    blue = calc_blue_assets(prices)
    
    today = datetime.date.today().strftime("%Y-%m-%d")
    now = datetime.datetime.now().strftime("%H:%M")
    
    # 构建报告
    report = f"📊 **APEX 双引擎收盘汇报**\n"
    report += f"📅 {today} {now}\n"
    report += f"{'─'*40}\n\n"
    
    # Red Engine
    if 'error' not in red:
        report += f"🔴 **Red Engine (均值回归)**\n"
        report += f"总资产: **{red['total']:,.0f}** 元\n"
        report += f"收益率: **{red['return_pct']:+.2f}%**\n"
        report += f"现金: {red['cash']:,.0f} | 持仓: {red['market_val']:,.0f}\n"
        
        if red['positions']:
            report += "持仓:\n"
            for pos in red['positions']:
                report += f"  • {pos['name']}: {pos['shares']}股 × {pos['price']:.2f} = {pos['value']:,.0f}元 ({pos['profit_pct']:+.1f}%)\n"
        report += "\n"
    else:
        report += f"🔴 Red Engine: 计算失败 {red['error']}\n\n"
    
    # Blue Engine
    if 'error' not in blue:
        report += f"🔵 **Blue Engine (科技对冲)**\n"
        report += f"总资产: **{blue['total']:,.0f}** 元\n"
        report += f"收益率: **{blue['return_pct']:+.2f}%**\n"
        report += f"现金: {blue['cash']:,.0f} | 多头: {blue['market_val']:,.0f} | 空头负债: {blue['short_debt']:,.0f}\n"
        
        if blue['positions']:
            report += "持仓:\n"
            for pos in blue['positions']:
                report += f"  • {pos['name']}: {pos['shares']}股 × {pos['price']:.2f} = {pos['value']:,.0f}元 ({pos['profit_pct']:+.1f}%) | 对冲: {pos['bench_name']} {pos['bench_shares']}股\n"
        report += "\n"
    else:
        report += f"🔵 Blue Engine: 计算失败 {blue['error']}\n\n"
    
    # 总览
    if 'error' not in red and 'error' not in blue:
        total_assets = red['total'] + blue['total']
        total_return = (total_assets - 2000000) / 2000000 * 100
        report += f"{'─'*40}\n"
        report += f"💰 **双引擎总资产: {total_assets:,.0f} 元**\n"
        report += f"📈 **总收益率: {total_return:+.2f}%**\n"
    
    # 发送飞书
    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "📊 APEX 收盘汇报"},
                "template": "blue"
            },
            "elements": [{"tag": "markdown", "content": report}]
        }
    }
    
    try:
        res = requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)
        print(f"✅ 收盘汇报已发送 ({now})")
    except Exception as e:
        print(f"❌ 发送失败: {e}")

if __name__ == "__main__":
    send_daily_report()
