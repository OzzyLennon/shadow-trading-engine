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

# AI 大模型配置 (这里以 DeepSeek 为例，兼容 OpenAI 格式。注册即送免费额度，非常便宜)
# 获取 API Key: https://platform.deepseek.com/
LLM_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
LLM_API_URL = os.environ.get("LLM_API_URL", "https://api.deepseek.com/v1/chat/completions")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "daily_config.json")
# ===============================================

def fetch_morning_news():
    """抓取新浪财经 A股 7x24小时滚动新闻（极速接口）"""
    print("📡 正在获取 A 股早盘核心资讯...")
    # 新浪财经滚动新闻 API (分类: A股)
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
        return "今日暂无重大宏观新闻，大盘按技术面自然震荡。"

def analyze_with_ai(news_text):
    """呼叫 AI 大脑进行投研分析"""
    print("🧠 正在呼叫 AI 大脑进行情绪分析与参数生成...")
    
    prompt = f"""
    你现在是一位中国 A 股市场的顶尖量化策略分析师。
    请阅读以下今天早晨的最新 A 股财经新闻，并评估今天的市场情绪。
    
    【今日早盘新闻】
    {news_text}
    
    【任务要求】
    请根据新闻内容，决定今天量化高频交易系统的作战参数。
    
    【参数说明】
    1. surge_threshold (追涨阈值): 激进写0.015(涨1.5%就追)，防守写0.035(涨3.5%才敢追)。
    2. stop_loss_pct (止损线): 激进写-0.08，防守写-0.03。
    3. trade_ratio (动态开火比例): 这是一个 0.1 到 0.5 之间的小数。
    - 激进情绪：写 0.4 或 0.5 (发现目标，直接倾泻账户 50% 的可用现金！两枪满仓！)
    - 震荡情绪：写 0.2 (每次动用 20% 现金)
    - 防守情绪：写 0.1 (每次只敢用 10% 现金试错)
    
    请务必只输出一个合法的 JSON 格式，格式要求如下：
    {{
        "market_sentiment": "看多 / 看空 / 震荡",
        "reasoning": "简短的一句话说明为什么这么判断",
        "surge_threshold": 0.02,
        "stop_loss_pct": -0.05,
        "trade_ratio": 0.3
    }}
    """
    
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": "你是一个只输出合法 JSON 格式的量化交易引擎。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2 # 降低随机性，保证理性输出
    }
    
    try:
        res = requests.post(LLM_API_URL, headers=headers, json=payload, timeout=30)
        content = res.json()['choices'][0]['message']['content']
        # 清理可能带有的 markdown 代码块标记
        content = content.replace('```json', '').replace('```', '').strip()
        config = json.loads(content)
        return config
    except Exception as e:
        print(f"AI 分析失败，启用备用防守配置: {e}")
        # 如果 AI 接口挂了，强制启用"怂包防守模式"保命
        return {
            "market_sentiment": "数据异常 (启用防守模式)",
            "reasoning": "由于 API 超时或报错，系统自动切入最低风险的防守模式。",
            "surge_threshold": 0.04,  # 极难触发买入
            "stop_loss_pct": -0.03,   # 极易触发止损
            "trade_ratio": 0.1        # 只敢用10%仓位试错
        }

def save_daily_config(config):
    """保存今天的作战参数，供高频脊髓读取"""
    config['date'] = str(datetime.date.today())
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    print("💾 每日作战参数 daily_config.json 已更新！")

def send_morning_brief(config):
    """发送飞书早报"""
    
    color = "grey"
    if "多" in config['market_sentiment']: color = "red" # A股红涨
    elif "空" in config['market_sentiment']: color = "green" # A股绿跌
    
    report = f"**🧠 AI 首席量化策略师晨会纪要**\n\n"
    report += f"📅 **交易日**: {datetime.date.today()}\n"
    report += f"🌡️ **今日市场定调**: **{config['market_sentiment']}**\n"
    report += f"💡 **逻辑推演**: {config['reasoning']}\n\n"
    
    report += f"---\n**⚙️ 高频执行系统 (APEX) 今日下发参数**\n"
    report += f"- 追涨点火阈值: `+{config['surge_threshold']*100}%`\n"
    report += f"- 铁血止损线: `{config['stop_loss_pct']*100}%`\n"
    report += f"- 动态开火比例: `{config.get('trade_ratio', 0.2)*100}%`\n\n"
    report += f"*(下发完毕，APEX 脊髓引擎已就绪，将在 9:30 自动接管战场)*"

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
    print("="*40)
    print(f"[{datetime.datetime.now()}] AI 慢速大脑启动")
    
    # 1. 抓取真实世界的新闻
    news = fetch_morning_news()
    
    # 2. 喂给大模型进行思考
    config = analyze_with_ai(news)
    
    # 3. 存储决策，发给高频代码去执行
    save_daily_config(config)
    
    # 4. 给老板（你）发个早报
    send_morning_brief(config)
    print("✅ 盘前部署完毕。")

if __name__ == "__main__":
    main()
