import requests
import json
import datetime
import os
import re

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

# AI 大模型配置
LLM_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
LLM_API_URL = os.environ.get("LLM_API_URL", "https://api.deepseek.com/v1/chat/completions")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "daily_config.json")
PORTFOLIO_FILE = os.path.join(SCRIPT_DIR, "apex_portfolio.json")
STATS_FILE = os.path.join(SCRIPT_DIR, "trade_stats.json")

# 全市场股票池（供 AI 动态选择）
FULL_SYMBOL_POOL = {
    # 科技算力
    "sh601138": "工业富联", "sz000938": "紫光股份", "sz002371": "北方华创", "sh603019": "中科曙光",
    "sz002475": "立讯精密", "sh688981": "中芯国际", "sz300750": "宁德时代", "sz002415": "海康威视",
    # 新能源汽车
    "sh601127": "赛力斯", "sz002594": "比亚迪", "sz002456": "欧菲光", "sz002241": "歌尔股份",
    "sh600104": "上汽集团", "sz002920": "德赛西威",
    # 大金融
    "sh600030": "中信证券", "sh601519": "大智慧", "sh600999": "招商证券", "sh600036": "招商银行",
    "sh601166": "兴业银行", "sh601318": "中国平安",
    # 医药消费
    "sh600276": "恒瑞医药", "sh603259": "药明康德", "sz000538": "云南白药", "sz002714": "牧原股份",
    "sz000858": "五粮液", "sh600519": "贵州茅台",
    # 周期资源
    "sh601899": "紫金矿业", "sh600028": "中国石化", "sh601088": "中国神华",
    # ETF宽基
    "sz159819": "人工智能ETF", "sh512880": "证券ETF", "sh513180": "恒生科技ETF", "sh512010": "医药ETF",
    "sh510300": "沪深300ETF", "sz159915": "创业板ETF"
}

# 默认股票池（AI 失败时使用）
DEFAULT_SYMBOLS = {
    "sz159819": "人工智能ETF", "sh512880": "证券ETF", "sh513180": "恒生科技ETF",
    "sh600030": "中信证券", "sh601138": "工业富联", "sz002594": "比亚迪"
}
# ===============================================

# ===============================================
# 数据源升维：多维度数据采集
# ===============================================

def fetch_morning_news():
    """抓取新浪财经 A股 7x24小时滚动新闻"""
    print("📡 正在获取 A 股早盘核心资讯...")
    url = "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&k=&num=15&page=1"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    news_list = []
    
    try:
        res = requests.get(url, headers=headers, timeout=10)
        data = res.json()
        for item in data.get('result', {}).get('data', []):
            title = item.get('title', '')
            summary = item.get('summary', '')
            if title:
                news_list.append(f"【{title}】{summary}")
        return "\n".join(news_list)
    except Exception as e:
        print(f"新闻抓取失败: {e}")
        return "今日暂无重大宏观新闻。"

def fetch_us_market():
    """
    获取隔夜美股表现
    对 A 股开盘有重要影响
    """
    print("🇺🇸 正在获取隔夜美股表现...")
    signals = []
    
    try:
        # 纳斯达克指数
        url = "http://hq.sinajs.cn/list=gb_$ndx"
        headers = {'Referer': 'http://finance.sina.com.cn'}
        res = requests.get(url, headers=headers, timeout=5)
        res.encoding = 'gbk'
        if '="' in res.text:
            data = res.text.split('="')[1].split(';')[0].split(',')
            if len(data) > 2:
                name = "纳斯达克"
                current = float(data[1]) if data[1] else 0
                change_pct = float(data[2]) if data[2] else 0
                signals.append(f"{name}: {change_pct:+.2f}%")
    except:
        pass
    
    try:
        # 道琼斯指数
        url = "http://hq.sinajs.cn/list=gb_$dji"
        headers = {'Referer': 'http://finance.sina.com.cn'}
        res = requests.get(url, headers=headers, timeout=5)
        res.encoding = 'gbk'
        if '="' in res.text:
            data = res.text.split('="')[1].split(';')[0].split(',')
            if len(data) > 2:
                name = "道琼斯"
                change_pct = float(data[2]) if data[2] else 0
                signals.append(f"{name}: {change_pct:+.2f}%")
    except:
        pass
    
    try:
        # 标普500
        url = "http://hq.sinajs.cn/list=gb_$spx"
        headers = {'Referer': 'http://finance.sina.com.cn'}
        res = requests.get(url, headers=headers, timeout=5)
        res.encoding = 'gbk'
        if '="' in res.text:
            data = res.text.split('="')[1].split(';')[0].split(',')
            if len(data) > 2:
                name = "标普500"
                change_pct = float(data[2]) if data[2] else 0
                signals.append(f"{name}: {change_pct:+.2f}%")
    except:
        pass
    
    return "\n".join(signals) if signals else "美股数据暂无"

def fetch_a50_futures():
    """
    获取富时A50期指表现
    A股早盘的重要风向标
    """
    print("🇬🇧 正在获取富时A50期指...")
    
    try:
        url = "http://hq.sinajs.cn/list=nf_FTSE_A50"
        headers = {'Referer': 'http://finance.sina.com.cn'}
        res = requests.get(url, headers=headers, timeout=5)
        res.encoding = 'gbk'
        if '="' in res.text:
            data = res.text.split('="')[1].split(';')[0].split(',')
            if len(data) > 4:
                current = float(data[3]) if data[3] else 0
                prev_close = float(data[4]) if data[4] else 0
                change_pct = (current - prev_close) / prev_close * 100 if prev_close else 0
                return f"富时A50期指: {change_pct:+.2f}% (现价{current:.0f})"
        return "A50期指数据暂无"
    except Exception as e:
        print(f"A50期指获取失败: {e}")
        return "A50期指数据暂无"

def fetch_market_volume():
    """
    获取昨日两市成交额
    用于判断市场活跃度
    """
    print("📊 正在获取昨日成交额...")
    
    try:
        # 东方财富两市成交额接口
        url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get?lmt=5&klt=1&secid=1.000001&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=10)
        data = res.json()
        
        if data.get('data', {}).get('klines'):
            kline = data['data']['klines'][0]
            parts = kline.split(',')
            # 成交额（元）
            amount = float(parts[6]) if len(parts) > 6 else 0
            amount_yi = amount / 100000000  # 转换为亿
            
            # 判断放量/缩量
            if amount_yi < 7000:
                volume_status = "极度缩量（防守）"
            elif amount_yi < 9000:
                volume_status = "缩量"
            elif amount_yi < 12000:
                volume_status = "正常"
            elif amount_yi < 15000:
                volume_status = "放量"
            else:
                volume_status = "巨量（进攻）"
            
            return f"昨日成交额: {amount_yi:.0f}亿 ({volume_status})"
        
        return "成交额数据暂无"
    except Exception as e:
        print(f"成交额获取失败: {e}")
        return "成交额数据暂无"

def fetch_northbound_flow():
    """获取北向资金流向"""
    print("💰 正在获取北向资金流向...")
    
    try:
        url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get?lmt=1&klt=1&secid=1.000001&fields1=f1,f2,f3,f7&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=10)
        data = res.json()
        if data.get('data', {}).get('klines'):
            kline = data['data']['klines'][0]
            parts = kline.split(',')
            flow = float(parts[6]) if len(parts) > 6 else 0
            return f"北向资金成交额: {flow/100000000:.2f}亿元"
        return "北向资金数据暂无"
    except Exception as e:
        print(f"北向资金获取失败: {e}")
        return "北向资金数据暂无"

def fetch_margin_data():
    """获取融资融券数据"""
    print("📈 正在获取融资融券数据...")
    
    try:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_MARGIN_FINANCE&columns=TRADE_DATE,TOTAL_FINANCE&pageSize=1"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=10)
        data = res.json()
        if data.get('result', {}).get('data'):
            item = data['result']['data'][0]
            date = item.get('TRADE_DATE', '')
            amount = item.get('TOTAL_FINANCE', 0)
            return f"融资余额: {amount/100000000:.2f}亿元 (截止{date})"
        return "融资融券数据暂无"
    except Exception as e:
        print(f"融资融券获取失败: {e}")
        return "融资融券数据暂无"

# ===============================================
# 反馈闭环：读取昨日表现
# ===============================================

def fetch_yesterday_pnl():
    """
    读取昨日盈亏情况
    用于反馈闭环
    """
    print("📊 正在读取昨日交易表现...")
    
    try:
        if os.path.exists(PORTFOLIO_FILE):
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                portfolio = json.load(f)
            
            # 检查是否是今天的数据（说明今天还没交易）
            today = str(datetime.date.today())
            if portfolio.get("date") == today:
                # 今天的数据，说明还没开始交易
                return "今日尚未开盘"
            
            # 昨日数据
            cash = portfolio.get("cash", 1000000)
            initial = 1000000
            
            # 计算持仓市值（需要当前价格，这里简化）
            positions = portfolio.get("positions", {})
            total_assets = cash  # 简化版，不含持仓市值
            
            pnl = total_assets - initial
            pnl_pct = (pnl / initial) * 100
            
            # 读取交易统计
            stats = {}
            if os.path.exists(STATS_FILE):
                with open(STATS_FILE, "r", encoding="utf-8") as f:
                    stats = json.load(f)
            
            total_trades = stats.get("total_trades", 0)
            win_trades = stats.get("win_trades", 0)
            win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0
            
            return f"昨日盈亏: {pnl:+.2f}元 ({pnl_pct:+.2f}%) | 历史胜率: {win_rate:.1f}% ({win_trades}/{total_trades})"
        
        return "首次运行，暂无历史数据"
    except Exception as e:
        print(f"读取昨日表现失败: {e}")
        return "历史数据读取失败"

# ===============================================
# AI 大脑：思维链推理
# ===============================================

def analyze_with_ai(news_text, us_market, a50, volume, northbound, margin, yesterday_pnl):
    """
    呼叫 AI 大脑进行综合投研分析
    使用思维链 (Chain of Thought) 提示词
    """
    print("🧠 正在呼叫 AI 大脑进行多维度分析...")
    
    today = datetime.date.today()
    weekday = ["周一", "周二", "周三", "周四", "周五"][today.weekday()]
    
    prompt = f"""
你是一位顶尖的 A 股量化策略分析师。请根据提供的【混合市场数据】，严格按照以下思考路径进行分析。

═══════════════════════════════════════
【今日日期】: {today} ({weekday})

【隔夜外围市场】
{us_market}
{a50}

【资金面信号】
{volume}
{northbound}
{margin}

【早盘核心新闻】
{news_text[:2000]}

【昨日表现反馈】
{yesterday_pnl}
═══════════════════════════════════════

<thinking>
第一步 (宏观定调)：
分析隔夜外盘、A50期指、资金面数据，判断今日大盘系统性风险等级：
- 风险极高：美股大跌 + A50大跌 + 资金流出 → trade_ratio = 0.05
- 震荡：多空交织 → trade_ratio = 0.2
- 安全：美股大涨 + A50涨 + 资金流入 → trade_ratio = 0.4

第二步 (主线挖掘)：
从早盘新闻中提取今日最可能爆发的 1-2 个行业概念。
例如：降准利好金融、AI利好科技、新能源政策利好相关板块。

第三步 (参数映射)：
基于风险判断，推导高频引擎的参数：
- surge_threshold (追涨阈值): 激进0.015, 防守0.04
- stop_loss_pct (止损线): 激进-0.08, 防守-0.03
- trade_ratio (开火比例): 0.05~0.5

第四步 (反思调整)：
如果昨日亏损，今日应该降低 trade_ratio，提高 surge_threshold，更加谨慎。
如果昨日盈利，可以适当激进，但不要超过风险承受能力。

第五步 (动态选股)：
根据今日政策和热点，从标的池中选择 6-10 只最可能有表现的方向。
</thinking>

<output>
{{
    "market_sentiment": "看多/震荡/看空",
    "risk_level": "极高/中等/安全",
    "reasoning": "综合判断理由（一句话）",
    "surge_threshold": 0.02,
    "stop_loss_pct": -0.05,
    "trade_ratio": 0.3,
    "focus_sectors": ["科技", "金融"],
    "symbols": {{
        "sh600030": "中信证券",
        "sz159819": "人工智能ETF"
    }}
}}
</output>
"""
    
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": "你是一个专业的量化交易引擎。严格按照格式输出：先<thinking>分析，再<output>输出JSON。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3
    }
    
    try:
        res = requests.post(LLM_API_URL, headers=headers, json=payload, timeout=60)
        content = res.json()['choices'][0]['message']['content']
        
        # 提取 <output> 标签内的 JSON
        output_match = re.search(r'<output>(.*?)</output>', content, re.DOTALL)
        if output_match:
            json_str = output_match.group(1).strip()
        else:
            # 尝试直接提取 JSON
            json_str = content.replace('```json', '').replace('```', '').strip()
        
        config = json.loads(json_str)
        
        # 确保必要字段存在
        if 'symbols' not in config or not config['symbols']:
            config['symbols'] = DEFAULT_SYMBOLS
        
        # 保存思维链（用于调试）
        thinking_match = re.search(r'<thinking>(.*?)</thinking>', content, re.DOTALL)
        if thinking_match:
            config['thinking'] = thinking_match.group(1).strip()
        
        return config
        
    except Exception as e:
        print(f"AI 分析失败，启用备用防守配置: {e}")
        return {
            "market_sentiment": "数据异常 (防守模式)",
            "risk_level": "极高",
            "reasoning": "API异常，系统自动切入防守模式。",
            "surge_threshold": 0.04,
            "stop_loss_pct": -0.03,
            "trade_ratio": 0.1,
            "focus_sectors": ["ETF宽基"],
            "symbols": DEFAULT_SYMBOLS
        }

# ===============================================
# 配置保存与早报发送
# ===============================================

def save_daily_config(config):
    """保存每日作战参数"""
    config['date'] = str(datetime.date.today())
    
    # 添加交易成本配置
    config['slippage'] = 0.002
    config['stamp_duty'] = 0.001
    config['commission'] = 0.00025
    config['z_score_threshold'] = 2.0
    
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    print("💾 每日作战参数已更新！")

def send_morning_brief(config):
    """发送飞书早报"""
    
    color = "grey"
    if "多" in config['market_sentiment']: color = "red"
    elif "空" in config['market_sentiment']: color = "green"
    
    risk_emoji = {"极高": "🔴", "中等": "🟡", "安全": "🟢"}.get(config.get('risk_level', '中等'), "⚪")
    
    symbols_str = "\n".join([f"  - {code}: {name}" for code, name in list(config.get('symbols', {}).items())[:8]])
    if len(config.get('symbols', {})) > 8:
        symbols_str += f"\n  - ... 共{len(config['symbols'])}只"
    
    report = f"**🧠 AI 首席量化策略师晨会纪要 v2.0**\n\n"
    report += f"📅 **交易日**: {datetime.date.today()}\n"
    report += f"🌡️ **市场定调**: **{config['market_sentiment']}**\n"
    report += f"{risk_emoji} **风险等级**: {config.get('risk_level', '中等')}\n"
    report += f"💡 **逻辑推演**: {config['reasoning']}\n"
    report += f"🎯 **聚焦板块**: {', '.join(config.get('focus_sectors', ['未指定']))}\n\n"
    
    report += f"---\n**⚙️ 作战参数**\n"
    report += f"- 追涨阈值: `+{config['surge_threshold']*100:.1f}%`\n"
    report += f"- 止损线: `{config['stop_loss_pct']*100:.0f}%`\n"
    report += f"- 开火比例: `{config['trade_ratio']*100:.0f}%`\n\n"
    
    report += f"---\n**📊 今日监控池**\n{symbols_str}\n"
    
    # 如果有思维链，添加到报告
    if config.get('thinking'):
        thinking_preview = config['thinking'][:200] + "..." if len(config['thinking']) > 200 else config['thinking']
        report += f"\n---\n**🤔 AI 思考过程**\n> {thinking_preview}\n"

    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "☕ 盘前宏观与策略部署 v2.0"},
                "template": color
            },
            "elements": [{"tag": "markdown", "content": report}]
        }
    }
    try:
        requests.post(FEISHU_WEBHOOK, json=payload)
    except: pass

def main():
    print("="*50)
    print(f"[{datetime.datetime.now()}] 🧠 AI 大脑启动 (v2.0 深度优化版)")
    print("="*50)
    
    # 1. 多维度数据采集
    news = fetch_morning_news()
    us_market = fetch_us_market()
    a50 = fetch_a50_futures()
    volume = fetch_market_volume()
    northbound = fetch_northbound_flow()
    margin = fetch_margin_data()
    yesterday_pnl = fetch_yesterday_pnl()
    
    print(f"\n📊 数据采集完成:")
    print(f"   - 新闻: {len(news)} 字符")
    print(f"   - 美股: {us_market}")
    print(f"   - A50: {a50}")
    print(f"   - 成交额: {volume}")
    print(f"   - 北向: {northbound}")
    print(f"   - 融资: {margin}")
    print(f"   - 昨日表现: {yesterday_pnl}")
    
    # 2. AI 综合分析（思维链）
    config = analyze_with_ai(news, us_market, a50, volume, northbound, margin, yesterday_pnl)
    
    # 3. 存储决策
    save_daily_config(config)
    
    # 4. 发送早报
    send_morning_brief(config)
    
    print(f"\n✅ 盘前部署完毕！今日监控 {len(config.get('symbols', {}))} 只标的")
    print(f"   - 市场定调: {config['market_sentiment']}")
    print(f"   - 开火比例: {config['trade_ratio']*100:.0f}%")

if __name__ == "__main__":
    main()
