# -*- coding: utf-8 -*-
"""
AI Sentinel V5.0 - 宏观风控哨兵
================================
角色：从"参数微调器"升维为"黑天鹅熔断器"

核心职责：
1. 监控逻辑破坏型暴跌（Regime Shift）
2. 输出 allow_trading 风控开关
3. 绝不篡改经WFA验证的底层数理参数

作者: AI量化风控官
版本: 5.0.0
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
    """记录日志"""
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
        return "\n".join(news_list[:15])  # 取前15条
    except Exception as e:
        log(f"⚠️ 新闻抓取失败: {e}")
        return "今日暂无重大宏观新闻。"

def fetch_policy_news():
    """获取政策相关新闻（重点关注煤炭/电力/分红政策）"""
    log("🏛️ 正在获取政策面资讯...")
    
    keywords = ["煤炭", "电力", "电价", "煤价", "分红", "国企", "能源", "发改委"]
    policy_news = []
    
    try:
        # 新浪财经搜索
        url = "https://search.sina.com.cn/?q=煤炭+电力+政策&c=news&from=channel&ie=utf-8"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        res = requests.get(url, headers=headers, timeout=10)
        # 这里简化处理，实际可以解析HTML
    except Exception as e:
        log(f"⚠️ 政策新闻获取失败: {e}")
    
    return policy_news

def call_llm_risk_assessment(news_content):
    """
    调用大模型进行风险研判
    
    输出格式：
    {
        "market_regime": "NORMAL / BLACK_SWAN",
        "reasoning": "判断理由",
        "allow_trading": true/false
    }
    """
    if not LLM_API_KEY:
        log("⚠️ 未配置LLM API密钥，默认允许交易")
        return {
            "market_regime": "NORMAL",
            "reasoning": "LLM未配置，采用默认允许",
            "allow_trading": True
        }
    
    system_prompt = """你是一位顶尖的 A 股宏观风控官。我们的量化引擎目前全仓聚焦于【煤电一体化与红利低波】板块（中国神华、国投电力、大唐发电）。

该策略的核心逻辑是：依靠公用事业的稳定盈利和高股息进行超跌抄底。

请阅读以下今日早盘新闻，并判断是否存在会【摧毁该板块底层逻辑】的系统性黑天鹅事件。

致命的黑天鹅包括但不限于：
1. 国家出台严厉政策限制煤价或电价利润（如限制煤炭企业暴利、电价市场化改革冲击）。
2. 针对国企分红比例的负面政策调整（如强制降低分红率、征收红利税）。
3. 极端的系统性股灾或流动性枯竭危机（如2015年式千股跌停）。
4. 重大地缘政治冲突导致能源供应链断裂。

如果不包含上述致命危机，即使大盘普通下跌，也请保持交易通道开启。"""

    user_prompt = f"""今日早盘新闻：

{news_content}

请输出 JSON 格式：
{{
    "market_regime": "NORMAL (正常震荡) / BLACK_SWAN (黑天鹅预警)",
    "reasoning": "详细的风控判断理由，说明是否检测到逻辑破坏型事件",
    "allow_trading": true 或 false
}}"""

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
            "temperature": 0.3,  # 低温度，更确定性输出
            "response_format": {"type": "json_object"}
        }
        
        res = requests.post(LLM_API_URL, headers=headers, json=payload, timeout=30)
        result = res.json()
        
        content = result["choices"][0]["message"]["content"]
        risk_assessment = json.loads(content)
        
        return risk_assessment
        
    except Exception as e:
        log(f"❌ LLM调用失败: {e}")
        # 失败时默认允许交易（保守策略）
        return {
            "market_regime": "NORMAL",
            "reasoning": f"LLM调用异常: {str(e)}，默认允许交易",
            "allow_trading": True
        }

def save_risk_config(risk_assessment):
    """保存风控配置到 daily_config.json"""
    try:
        config = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
        
        # 更新风控字段
        config["allow_trading"] = risk_assessment.get("allow_trading", True)
        config["market_regime"] = risk_assessment.get("market_regime", "NORMAL")
        config["risk_reasoning"] = risk_assessment.get("reasoning", "")
        config["risk_updated_at"] = datetime.datetime.now().isoformat()
        
        # 保留策略参数（绝不篡改）
        config["strategy_params"] = config.get("strategy_params", {
            "z_threshold": -1.5,
            "window": 10,
            "trade_ratio": 0.3,
            "stop_loss": 0.10
        })
        
        config["portfolio"] = config.get("portfolio", {
            "symbols": {
                "sh600886": {"name": "国投电力", "sector": "水电龙头"},
                "sh601088": {"name": "中国神华", "sector": "煤电一体化"},
                "sh601991": {"name": "大唐发电", "sector": "火电转型"}
            }
        })
        
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        
        log(f"💾 风控配置已保存: allow_trading={config['allow_trading']}")
        
    except Exception as e:
        log(f"❌ 保存配置失败: {e}")

def send_risk_alert(risk_assessment):
    """发送风控警报到飞书"""
    if not FEISHU_WEBHOOK:
        return
    
    regime = risk_assessment.get("market_regime", "NORMAL")
    allow = risk_assessment.get("allow_trading", True)
    reasoning = risk_assessment.get("reasoning", "")
    
    # 根据风险等级选择颜色
    template = "green" if allow else "red"
    status_emoji = "✅" if allow else "🚫"
    status_text = "交易通道开启" if allow else "交易通道关闭"
    
    report = f"**{status_emoji} AI风控哨兵 V5.0 晨报**\n\n"
    report += f"**市场状态**: {regime}\n"
    report += f"**交易权限**: {status_text}\n\n"
    report += f"**研判理由**:\n{reasoning}\n\n"
    report += f"---\n*更新时间: {datetime.datetime.now().strftime('%H:%M')}*"
    
    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "🛡️ 宏观风控警报"},
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
    """主函数：每日早盘执行一次"""
    log("="*60)
    log("🧠 AI Sentinel V5.0 - 宏观风控哨兵启动")
    log("="*60)
    
    # 1. 获取新闻
    news = fetch_morning_news()
    log(f"📰 获取到 {len(news)} 字符新闻内容")
    
    # 2. LLM风险研判
    log("🤖 正在调用大模型进行风险研判...")
    risk_assessment = call_llm_risk_assessment(news)
    
    # 3. 输出结果
    log(f"\n📊 风控研判结果:")
    log(f"   市场状态: {risk_assessment.get('market_regime', 'UNKNOWN')}")
    log(f"   交易权限: {'允许' if risk_assessment.get('allow_trading') else '禁止'}")
    log(f"   研判理由: {risk_assessment.get('reasoning', 'N/A')[:100]}...")
    
    # 4. 保存配置
    save_risk_config(risk_assessment)
    
    # 5. 发送警报
    send_risk_alert(risk_assessment)
    
    log("="*60)
    log("✅ 风控哨兵任务完成")
    log("="*60)

if __name__ == "__main__":
    main()
