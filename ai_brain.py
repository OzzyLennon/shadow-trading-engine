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

# AI 大模型配置
LLM_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
LLM_API_URL = os.environ.get("LLM_API_URL", "https://api.deepseek.com/v1/chat/completions")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "daily_config.json")

# 默认股票池（当AI无法生成时使用）
DEFAULT_SYMBOLS = {
    "sh601138": "工业富联", "sz000938": "紫光股份", "sz002371": "北方华创", "sh603019": "中科曙光",
    "sh601127": "赛力斯", "sz002594": "比亚迪", "sz002456": "欧菲光", "sz002241": "歌尔股份",
    "sh600030": "中信证券", "sh601519": "大智慧", "sh600999": "招商证券", "sh600036": "招商银行",
    "sh600276": "恒瑞医药", "sh603259": "药明康德", "sz000538": "云南白药", "sz002714": "牧原股份",
    "sz159819": "人工智能ETF", "sh512880": "证券ETF", "sh513180": "恒生科技ETF", "sh512010": "医药ETF"
}
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

def fetch_northbound_flow():
    """获取北向资金流向（模拟数据源）"""
    print("💰 正在获取北向资金流向...")
    try:
        # 东方财富北向资金接口
        url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get?lmt=1&klt=1&secid=1.000001&fields1=f1,f2,f3,f7&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=10)
        data = res.json()
        if data.get('data', {}).get('klines'):
            kline = data['data']['klines'][0]
            parts = kline.split(',')
            # 解析：日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
            flow = float(parts[6]) if len(parts) > 6 else 0  # 成交额
            return f"昨日北向资金成交额: {flow/100000000:.2f}亿元"
        return "北向资金数据暂无"
    except Exception as e:
        print(f"北向资金获取失败: {e}")
        return "北向资金数据暂无"

def fetch_margin_data():
    """获取融资融券数据（模拟）"""
    print("📊 正在获取融资融券数据...")
    try:
        # 简化版：从东方财富获取两市融资余额
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

def fetch_overseas_signals():
    """获取外围市场信号"""
    print("🌍 正在获取外围市场信号...")
    signals = []
    
    try:
        # 富时A50期指（新浪）
        url = "http://hq.sinajs.cn/list=nf_FTSE_A50"
        headers = {'Referer': 'http://finance.sina.com.cn'}
        res = requests.get(url, headers=headers, timeout=5)
        res.encoding = 'gbk'
        if '="' in res.text:
            data = res.text.split('="')[1].split(';')[0].split(',')
            if len(data) > 3:
                current = float(data[3]) if data[3] else 0
                prev_close = float(data[4]) if data[4] else 0
                change_pct = (current - prev_close) / prev_close * 100 if prev_close else 0
                signals.append(f"富时A50期指: {change_pct:+.2f}%")
    except:
        pass
    
    try:
        # 美元指数
        url = "http://hq.sinajs.cn/list=gb_$dxy"
        headers = {'Referer': 'http://finance.sina.com.cn'}
        res = requests.get(url, headers=headers, timeout=5)
        res.encoding = 'gbk'
        if '="' in res.text:
            data = res.text.split('="')[1].split(';')[0].split(',')
            if len(data) > 2:
                signals.append(f"美元指数: {data[1]}")
    except:
        pass
    
    return "\n".join(signals) if signals else "外围市场数据暂无"

def analyze_with_ai(news_text, northbound, margin, overseas):
    """呼叫 AI 大脑进行综合投研分析"""
    print("🧠 正在呼叫 AI 大脑进行多维度分析...")
    
    prompt = f"""
    你现在是一位中国 A 股市场的顶尖量化策略分析师。
    请综合以下多维度信息，评估今天的市场情绪并生成作战参数。
    
    ═══════════════════════════════════════
    【今日早盘新闻】
    {news_text[:2000]}
    
    ═══════════════════════════════════════
    【资金面信号】
    {northbound}
    {margin}
    
    ═══════════════════════════════════════
    【外围市场】
    {overseas}
    ═══════════════════════════════════════
    
    【任务一：市场定调】
    综合新闻、资金面、外围市场，判断今日市场情绪：
    - 看多：多重利好共振，北向持续流入，外围配合
    - 震荡：多空交织，无明显方向
    - 看空：利空主导，资金流出，外围拖累
    
    【任务二：策略参数】
    1. surge_threshold: 追涨阈值 (激进0.015, 防守0.04)
    2. stop_loss_pct: 止损线 (激进-0.08, 防守-0.03)
    3. trade_ratio: 开火比例 (激进0.5, 防守0.1)
    
    【任务三：动态选股】
    根据今日政策和热点，从以下标的池中选择6-10只最可能有表现的方向：
    标的池选项：
    - 科技算力: 工业富联(sh601138), 紫光股份(sz000938), 北方华创(sz002371), 中科曙光(sh603019)
    - 新能源汽车: 赛力斯(sh601127), 比亚迪(sz002594), 欧菲光(sz002456), 歌尔股份(sz002241)
    - 大金融: 中信证券(sh600030), 大智慧(sh601519), 招商证券(sh600999), 招商银行(sh600036)
    - 医药消费: 恒瑞医药(sh600276), 药明康德(sh603259), 云南白药(sz000538), 牧原股份(sz002714)
    - ETF宽基: 人工智能ETF(sz159819), 证券ETF(sh512880), 恒生科技ETF(sh513180), 医药ETF(sh512010)
    
    选择逻辑：
    - 政策利好 → 选择对应板块
    - 资金流入 → 选择主力关注方向
    - 避险情绪 → 选择ETF宽基
    
    请输出合法 JSON 格式：
    {{
        "market_sentiment": "看多/震荡/看空",
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
    """
    
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": "你是一个专业的量化交易引擎，只输出合法JSON。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2
    }
    
    try:
        res = requests.post(LLM_API_URL, headers=headers, json=payload, timeout=45)
        content = res.json()['choices'][0]['message']['content']
        content = content.replace('```json', '').replace('```', '').strip()
        config = json.loads(content)
        
        # 确保symbols字段存在
        if 'symbols' not in config or not config['symbols']:
            config['symbols'] = DEFAULT_SYMBOLS
        
        return config
    except Exception as e:
        print(f"AI 分析失败，启用备用防守配置: {e}")
        return {
            "market_sentiment": "数据异常 (防守模式)",
            "reasoning": "API异常，系统自动切入防守模式。",
            "surge_threshold": 0.04,
            "stop_loss_pct": -0.03,
            "trade_ratio": 0.1,
            "focus_sectors": ["ETF宽基"],
            "symbols": {
                "sz159819": "人工智能ETF",
                "sh512880": "证券ETF",
                "sh513180": "恒生科技ETF"
            }
        }

def save_daily_config(config):
    """保存每日作战参数"""
    config['date'] = str(datetime.date.today())
    
    # 添加交易成本配置
    config['slippage'] = 0.002  # 0.2% 滑点
    config['stamp_duty'] = 0.001  # 0.1% 印花税（仅卖出）
    config['commission'] = 0.00025  # 0.025% 佣金
    
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    print("💾 每日作战参数已更新！")

def send_morning_brief(config):
    """发送飞书早报"""
    
    color = "grey"
    if "多" in config['market_sentiment']: color = "red"
    elif "空" in config['market_sentiment']: color = "green"
    
    symbols_str = "\n".join([f"  - {code}: {name}" for code, name in list(config.get('symbols', {}).items())[:6]])
    if len(config.get('symbols', {})) > 6:
        symbols_str += f"\n  - ... 共{len(config['symbols'])}只"
    
    report = f"**🧠 AI 首席量化策略师晨会纪要**\n\n"
    report += f"📅 **交易日**: {datetime.date.today()}\n"
    report += f"🌡️ **市场定调**: **{config['market_sentiment']}**\n"
    report += f"💡 **逻辑推演**: {config['reasoning']}\n"
    report += f"🎯 **聚焦板块**: {', '.join(config.get('focus_sectors', ['未指定']))}\n\n"
    
    report += f"---\n**⚙️ 作战参数**\n"
    report += f"- 追涨阈值: `+{config['surge_threshold']*100}%`\n"
    report += f"- 止损线: `{config['stop_loss_pct']*100}%`\n"
    report += f"- 开火比例: `{config['trade_ratio']*100}%`\n"
    report += f"- 滑点/印花税: `{config.get('slippage',0.002)*100}%` / `{config.get('stamp_duty',0.001)*100}%`\n\n"
    
    report += f"---\n**📊 今日监控池**\n{symbols_str}\n"

    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "☕ 盘前宏观与策略部署"},
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
    print(f"[{datetime.datetime.now()}] 🧠 AI 大脑启动 (增强版)")
    
    # 1. 多维度数据采集
    news = fetch_morning_news()
    northbound = fetch_northbound_flow()
    margin = fetch_margin_data()
    overseas = fetch_overseas_signals()
    
    print(f"\n📊 数据采集完成:")
    print(f"   - 新闻: {len(news)} 字符")
    print(f"   - 北向: {northbound}")
    print(f"   - 融资: {margin}")
    print(f"   - 外围: {overseas}")
    
    # 2. AI 综合分析
    config = analyze_with_ai(news, northbound, margin, overseas)
    
    # 3. 存储决策
    save_daily_config(config)
    
    # 4. 发送早报
    send_morning_brief(config)
    
    print(f"\n✅ 盘前部署完毕！今日监控 {len(config.get('symbols', {}))} 只标的")

if __name__ == "__main__":
    main()
