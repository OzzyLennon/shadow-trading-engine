# -*- coding: utf-8 -*-
"""
AI Sentinel V3.0 - 全局多战区风控司令
=====================================
角色：双引擎定向熔断系统

核心职责：
1. 同时监控 Red Engine (红利) 和 Blue Engine (科技)
2. 输出 red_engine_allow / blue_engine_allow 双通道权限矩阵
3. 定向熔断：煤炭政策打击 → Red熔断 Blue继续；芯片禁令 → Blue熔断 Red继续

版本: 3.0.0
日期: 2026-03-18
"""

import requests
import json
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

# ================= 核心配置 =================
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")
LLM_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
LLM_API_URL = os.environ.get("LLM_API_URL", "https://api.deepseek.com/v1/chat/completions")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "daily_config.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "logs", "ai_sentinel.log")

# ================= 工具函数 =================
def log(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {message}"
    print(log_line)
    try:
        log_dir = os.path.dirname(LOG_FILE)
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_line + "\n")
    except: pass

def fetch_morning_news():
    """抓取新浪财经 A股 7x24小时滚动新闻"""
    log("📡 正在获取 A 股早盘核心资讯...")
    url = "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&k=&num=20&page=1"
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
        return "\n".join(news_list[:20])
    except Exception as e:
        log(f"⚠️ 新闻抓取失败: {e}")
        return "今日暂无重大宏观新闻。"

def call_llm_risk_assessment(news_content):
    """
    调用大模型进行双引擎风险研判
    
    输出格式：
    {
        "red_engine_allow": true/false,
        "red_reasoning": "红利板块风控判断理由",
        "blue_engine_allow": true/false,
        "blue_reasoning": "科技板块风控判断理由",
        "global_market_status": "NORMAL / BLACK_SWAN"
    }
    """
    if not LLM_API_KEY:
        log("⚠️ 未配置LLM API密钥，默认允许双引擎交易")
        return {
            "red_engine_allow": True,
            "red_reasoning": "LLM未配置，采用默认允许",
            "blue_engine_allow": True,
            "blue_reasoning": "LLM未配置，采用默认允许",
            "global_market_status": "NORMAL"
        }
    
    system_prompt = """你是一位顶尖的 A 股量化基金宏观风控官。我们的基金目前部署了两个完全独立的交易引擎：

1. 【Red Engine】(红利防守军团)：持仓中国神华、国投电力等煤电一体化股票。核心风险：国家出台严厉政策限制煤价/电价利润、针对国企分红比例的负面政策调整。
2. 【Blue Engine】(科技进攻军团)：持仓中际旭创，寒武纪、工业富联等 AI 与半导体龙头。核心风险：美国出台极其严厉的芯片/算力制裁禁令、国家级针对 AI 行业的重大打压政策。

请阅读以下今日早盘的宏观与行业新闻，并分别判断两个战区是否存在【摧毁其底层逻辑的黑天鹅事件】。
如果只是普通的市场涨跌，请保持交易通道开启。

请严格输出以下 JSON 格式：
{
    "red_engine_allow": true 或 false,
    "red_reasoning": "红利板块风控判断理由",
    "blue_engine_allow": true 或 false,
    "blue_reasoning": "科技板块风控判断理由",
    "global_market_status": "NORMAL / BLACK_SWAN"
}"""

    user_prompt = f"""今日早盘新闻：

{news_content}

请严格按照 JSON 格式输出上述字段。"""

    try:
        headers = {
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.3,
            "response_format": {"type": "json_object"}
        }
        
        res = requests.post(LLM_API_URL, headers=headers, json=payload, timeout=30)
        result = res.json()
        
        content = result["choices"][0]["message"]["content"]
        risk_assessment = json.loads(content)
        
        return risk_assessment
        
    except Exception as e:
        log(f"❌ LLM调用失败: {e}")
        return {
            "red_engine_allow": True,
            "red_reasoning": f"LLM调用异常: {str(e)}，默认允许",
            "blue_engine_allow": True,
            "blue_reasoning": f"LLM调用异常: {str(e)}，默认允许",
            "global_market_status": "NORMAL"
        }

def save_risk_config(risk_assessment):
    """保存双引擎风控配置到 daily_config.json"""
    try:
        config = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
        
        # 更新双引擎风控字段
        config["red_engine_allow"] = risk_assessment.get("red_engine_allow", True)
        config["red_reasoning"] = risk_assessment.get("red_reasoning", "")
        config["blue_engine_allow"] = risk_assessment.get("blue_engine_allow", True)
        config["blue_reasoning"] = risk_assessment.get("blue_reasoning", "")
        config["global_market_status"] = risk_assessment.get("global_market_status", "NORMAL")
        
        # 兼容旧字段（如果AI Brain还在用）
        config["allow_trading"] = risk_assessment.get("red_engine_allow", True)
        config["market_regime"] = risk_assessment.get("global_market_status", "NORMAL")
        
        config["risk_updated_at"] = datetime.datetime.now().isoformat()
        
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        
        log(f"💾 风控配置已保存: red={config['red_engine_allow']}, blue={config['blue_engine_allow']}")
        
    except Exception as e:
        log(f"❌ 保存配置失败: {e}")

def send_risk_alert(risk_assessment):
    """发送双引擎风控警报到飞书"""
    if not FEISHU_WEBHOOK:
        return
    
    red_allow = risk_assessment.get("red_engine_allow", True)
    blue_allow = risk_assessment.get("blue_engine_allow", True)
    global_status = risk_assessment.get("global_market_status", "NORMAL")
    red_reason = risk_assessment.get("red_reasoning", "")
    blue_reason = risk_assessment.get("blue_reasoning", "")
    
    # 确定状态
    if not red_allow and not blue_allow:
        template = "red"
        status = "🚫 双引擎熔断"
    elif not red_allow:
        template = "orange"
        status = "🟠 Red Engine 熔断"
    elif not blue_allow:
        template = "blue"
        status = "🔵 Blue Engine 熔断"
    else:
        template = "green"
        status = "✅ 双引擎通行"
    
    report = f"**🛡️ AI Sentinel V3.0 - 全局风控司令**\n\n"
    report += f"**全局状态**: {global_status}\n"
    report += f"**交易权限**: {status}\n\n"
    report += f"---\n"
    report += f"**🔴 Red Engine (红利)**\n"
    report += f"状态: {'✅ 允许' if red_allow else '🚫 熔断'}\n"
    report += f"理由: {red_reason[:150]}...\n\n"
    report += f"**🔵 Blue Engine (科技)**\n"
    report += f"状态: {'✅ 允许' if blue_allow else '🚫 熔断'}\n"
    report += f"理由: {blue_reason[:150]}...\n"
    report += f"\n---\n*更新时间: {datetime.datetime.now().strftime('%H:%M')}*"
    
    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "🛡️ 双引擎风控矩阵"},
                "template": template
            },
            "elements": [{"tag": "markdown", "content": report}]
        }
    }
    
    try:
        requests.post(FEISHU_WEBHOOK, json=payload, timeout=5)
    except Exception as e:
        log(f"⚠️ 飞书推送失败: {e}")

def main():
    log("="*60)
    log("🧠 AI Sentinel V3.0 - 全局多战区风控司令启动")
    log("="*60)
    
    # 1. 获取新闻
    news = fetch_morning_news()
    log(f"📰 获取到 {len(news)} 字符新闻内容")
    
    # 2. LLM双引擎风险研判
    log("🤖 正在调用大模型进行双引擎风险研判...")
    risk_assessment = call_llm_risk_assessment(news)
    
    # 3. 输出结果
    log(f"\n📊 风控研判结果:")
    log(f"   全局状态: {risk_assessment.get('global_market_status', 'UNKNOWN')}")
    log(f"   🔴 Red Engine: {'允许' if risk_assessment.get('red_engine_allow') else '熔断'}")
    log(f"   🔵 Blue Engine: {'允许' if risk_assessment.get('blue_engine_allow') else '熔断'}")
    
    # 4. 保存配置
    save_risk_config(risk_assessment)
    
    # 5. 发送警报
    send_risk_alert(risk_assessment)
    
    log("="*60)
    log("✅ 风控哨兵任务完成")
    log("="*60)

if __name__ == "__main__":
    main()
