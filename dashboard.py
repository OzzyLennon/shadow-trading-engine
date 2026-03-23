import streamlit as st
import json
import pandas as pd
import os
import time
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import requests
from typing import Dict, Any, Optional

from core.config import load_config_with_fallback

# APEX 量化中控台 V2.0
# 运行命令: streamlit run dashboard.py --server.port 8501

# 加载配置
config = load_config_with_fallback()

# 页面全局配置
st.set_page_config(page_title="APEX Quant Command Center", page_icon="👁️‍🗨️", layout="wide", initial_sidebar_state="expanded")

# 数据加载层
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ALPHA_PORTFOLIO = os.path.join(SCRIPT_DIR, "alpha_factory_portfolio.json")
PERFORMANCE_FILE = os.path.join(SCRIPT_DIR, "strategy_performance.json")
PROMOTED_FILE = os.path.join(SCRIPT_DIR, "promoted_strategies.json")
RED_PORTFOLIO = os.path.join(SCRIPT_DIR, "apex_portfolio.json")
BLUE_PORTFOLIO = os.path.join(SCRIPT_DIR, "apex_tech_portfolio.json")

@st.cache_data(ttl=10)
def load_json(filepath: str) -> Dict[str, Any]:
    """加载JSON文件"""
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

# 实时价格获取
@st.cache_data(ttl=5)
def get_realtime_prices(symbols: list) -> Dict[str, Dict[str, Any]]:
    """批量获取实时价格"""
    if not symbols:
        return {}
    
    codes = []
    for s in symbols:
        if s.startswith('sh'):
            codes.append(f"sh{s[2:]}")
        elif s.startswith('sz'):
            codes.append(f"sz{s[2:]}")
    
    prices = {}
    url = f"http://hq.sinajs.cn/list={','.join(codes)}"
    headers = {'Referer': 'http://finance.sina.com.cn'}
    
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.encoding = 'gbk'
        
        for line in res.text.split('\n'):
            if 'hq_str_' not in line or '=' not in line:
                continue
            
            code_part = line.split('=')[0].split('_')[-1]
            data_part = line.split('"')[1] if '"' in line else ''
            
            if not data_part:
                continue
            
            fields = data_part.split(',')
            if len(fields) < 31:
                continue
            
            try:
                price = float(fields[3])  # 当前价
                if price <= 0:
                    price = float(fields[2])  # 昨收
                
                # 恢复代码格式
                if code_part.startswith('sh'):
                    symbol = f"sh{code_part[2:]}"
                elif code_part.startswith('sz'):
                    symbol = f"sz{code_part[2:]}"
                else:
                    symbol = code_part
                
                prices[symbol] = {
                    'current': price,
                    'open': float(fields[1]) if fields[1] else price,
                    'high': float(fields[4]) if fields[4] else price,
                    'low': float(fields[5]) if fields[5] else price,
                    'volume': int(fields[8]) if fields[8] else 0,
                    'change_pct': (price - float(fields[2])) / float(fields[2]) * 100 if float(fields[2]) > 0 else 0
                }
            except:
                continue
    except Exception as e:
        st.warning(f"获取实时行情失败: {e}")
    
    return prices

# 加载核心数据
alpha_data = load_json(ALPHA_PORTFOLIO)
perf_data = load_json(PERFORMANCE_FILE)
promo_data = load_json(PROMOTED_FILE)
red_data = load_json(RED_PORTFOLIO)
blue_data = load_json(BLUE_PORTFOLIO)  # Blue Engine (科技对冲)

# 获取所有持仓的实时价格
all_symbols = set(red_data.get('positions', {}).keys())
all_symbols.update(alpha_data.get('positions', {}).keys())
all_symbols.update(blue_data.get('positions', {}).keys())  # Blue Engine 持仓
realtime_prices = get_realtime_prices(list(all_symbols)) if all_symbols else {}

# ================= 侧边栏: 哨兵与宏观控制 =================
with st.sidebar:
    st.image("https://img.icons8.com/color/96/000000/artificial-intelligence.png", width=60)
    st.title("APEX 核心引擎")
    st.markdown("`状态: 运行中 🟢`")

    st.markdown("---")
    st.subheader("🚨 Sentinel 宏观风控")
    # 模拟 Sentinel 状态 (后续可接入你的 ai_sentinel 真实日志)
    macro_status = "Safe" 
    if macro_status == "Safe":
        st.success("✅ 宏观环境安全 (允许开仓)")
        st.metric("大盘 Beta 偏离度", "+0.45", "正常")
    else:
        st.error("🛑 黑天鹅警报 (强制平仓中)")

    st.markdown("---")
    st.markdown(f"⏱️ **最后快照**: {datetime.now().strftime('%H:%M:%S')}")
    if st.button("🔄 强制同步核心数据", use_container_width=True):
        st.cache_data.clear()

# ================= 顶部 KPI 展板 =================
st.title("👁️‍🗨️ APEX Alpha Factory 驾驶舱")

# 计算核心指标
cash_alpha = alpha_data.get('cash', 0)
cash_red = red_data.get('cash', 0)
cash_blue = blue_data.get('cash', 0)  # Blue Engine
total_cash = cash_alpha + cash_red + cash_blue

# 计算持仓市值和盈亏
position_value = 0
position_cost = 0

# Red Engine 持仓 (煤电红利)
for symbol, pos in red_data.get('positions', {}).items():
    shares = pos.get('total_shares', 0)
    cost = pos.get('cost', 0)
    current_price = realtime_prices.get(symbol, {}).get('current', cost)
    position_value += shares * current_price
    position_cost += shares * cost

# Alpha Factory 持仓
for symbol, pos in alpha_data.get('positions', {}).items():
    shares = pos.get('shares', 0)
    cost = pos.get('cost_price', 0)
    current_price = realtime_prices.get(symbol, {}).get('current', cost)
    position_value += shares * current_price
    position_cost += shares * cost

# Blue Engine 持仓 (科技对冲)
for symbol, pos in blue_data.get('positions', {}).items():
    shares = pos.get('stock_shares', 0)
    cost = pos.get('stock_cost', 0)
    current_price = realtime_prices.get(symbol, {}).get('current', cost)
    position_value += shares * current_price
    position_cost += shares * cost
    # 注意：Blue Engine 还有空头头寸，这里简化处理只算多头

total_aum = total_cash + position_value
total_profit = position_value - position_cost
total_profit_pct = (total_profit / position_cost * 100) if position_cost > 0 else 0

# 总收益率计算 (与收盘汇报一致)
# 使用配置中的初始资金 × 2（双引擎）
INITIAL_CAPITAL = config.initial_capital * 2
total_return = (total_aum - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

active_strats = len(promo_data.get('strategies', []))
total_trades_alpha = len(alpha_data.get('trades', []))
total_trades_red = len(red_data.get('trades', []))
total_trades = total_trades_alpha + total_trades_red

# 渲染顶部指标卡
kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
kpi1.metric(label="💰 总资产净值 (AUM)", value=f"¥ {total_aum:,.0f}", delta=f"现金 {total_cash:,.0f}")
kpi2.metric(label="📊 持仓市值", value=f"¥ {position_value:,.0f}", delta=f"成本 {position_cost:,.0f}")
kpi3.metric(label="📈 总收益率", value=f"{total_return:+.2f}%", delta=f"持仓盈亏 ¥{total_profit:,.0f}")
kpi4.metric(label="🧠 存活 Alpha 策略", value=f"{active_strats} 个")
kpi5.metric(label="⚡ 累计调仓", value=f"{total_trades} 笔")

# 计算整体胜率
total_wins = sum([s.get('wins', 0) for s in perf_data.get('strategies', {}).values()])
total_perf_trades = sum([s.get('trades', 0) for s in perf_data.get('strategies', {}).values()])
global_win_rate = (total_wins / total_perf_trades * 100) if total_perf_trades > 0 else 0
kpi4.metric(label="🎯 Alpha 全局实盘胜率", value=f"{global_win_rate:.1f}%", delta=f"{total_wins}胜 / {total_perf_trades-total_wins}负")

st.markdown("---")

# ================= 核心视窗 (Tabs) =================
tab1, tab2, tab3, tab4 = st.tabs(["⚔️ Alpha 存活与衰减", "📦 实时持仓透视", "💸 TCA 交易成本分析", "📜 交易流水审计"])

# ----------------- Tab 1: 策略性能表现 -----------------
with tab1:
    st.subheader("因子表现排行榜 (末位淘汰监控区)")
    strats = perf_data.get('strategies', {})

    if strats:
        df_perf = pd.DataFrame.from_dict(strats, orient='index').reset_index()
        df_perf.columns = ['策略因子', '累计收益', '交易笔数', '盈利笔数', '亏损笔数']
        df_perf['实盘胜率'] = (df_perf['盈利笔数'] / df_perf['交易笔数'] * 100).fillna(0).round(1)

        col_chart1, col_chart2 = st.columns([2, 1])

        with col_chart1:
            # 绘制：策略累计收益条形图
            fig_return = px.bar(
                df_perf.sort_values('累计收益', ascending=False), 
                x='策略因子', y='累计收益', 
                color='累计收益', color_continuous_scale=px.colors.diverging.RdYlGn,
                title="实盘累计收益提取量 (盈亏绝对值)"
            )
            st.plotly_chart(fig_return, use_container_width=True)

        with col_chart2:
            # 绘制：胜率气泡图 (防范高频低胜率陷阱)
            fig_scatter = px.scatter(
                df_perf, x='交易笔数', y='实盘胜率', 
                size='盈利笔数', color='实盘胜率', hover_name='策略因子',
                color_continuous_scale='Bluered_r',
                title="Alpha 衰减雷达 (胜率 vs 频率)"
            )
            fig_scatter.add_hline(y=40, line_dash="dash", line_color="red", annotation_text="淘汰红线 (40%)")
            st.plotly_chart(fig_scatter, use_container_width=True)

        st.dataframe(df_perf.style.highlight_max(subset=['累计收益', '实盘胜率'], color='lightgreen').highlight_min(subset=['累计收益'], color='lightcoral'), use_container_width=True)
    else:
        st.info("🕒 等待 Alpha Factory 产生实盘交易数据...")

# ----------------- Tab 2: 实时敞口透视 -----------------
with tab2:
    st.subheader("资金分布与多头敞口 (Position Exposure)")
    
    # 合并 Alpha Factory 和 APEX 的持仓
    positions = alpha_data.get('positions', {})
    red_positions = red_data.get('positions', {})
    
    # APEX持仓转换为统一格式
    all_positions = {}
    total_value = 0
    total_cost = 0
    
    # Alpha Factory 持仓
    for symbol, pos in positions.items():
        shares = pos.get('shares', 0)
        cost_price = pos.get('cost_price', 0)
        total_cost_pos = pos.get('total_cost', 0)
        
        current_price = realtime_prices.get(symbol, {}).get('current', cost_price)
        current_value = shares * current_price
        profit = current_value - total_cost_pos
        profit_pct = (profit / total_cost_pos * 100) if total_cost_pos > 0 else 0
        
        all_positions[symbol] = {
            '持股数量': shares,
            '持仓均价': cost_price,
            '当前价格': current_price,
            '当前市值': current_value,
            '占用资金': total_cost_pos,
            '盈亏金额': profit,
            '盈亏比例': profit_pct,
            '买入时间': pos.get('buy_time', ''),
            '信号来源': 'Alpha Factory',
            '引擎': 'Alpha Factory'
        }
        total_value += current_value
        total_cost += total_cost_pos
    
    # Red Engine 持仓 (煤电红利)
    for symbol, pos in red_positions.items():
        shares = pos.get('total_shares', 0)
        cost_price = pos.get('cost', 0)
        total_cost_pos = shares * cost_price
        
        current_price = realtime_prices.get(symbol, {}).get('current', cost_price)
        current_value = shares * current_price
        profit = current_value - total_cost_pos
        profit_pct = (profit / total_cost_pos * 100) if total_cost_pos > 0 else 0
        
        all_positions[symbol] = {
            '持股数量': shares,
            '持仓均价': cost_price,
            '当前价格': current_price,
            '当前市值': current_value,
            '占用资金': total_cost_pos,
            '盈亏金额': profit,
            '盈亏比例': profit_pct,
            '买入时间': '历史持仓',
            '信号来源': 'Red Engine (煤电红利)',
            '引擎': 'Red Engine'
        }
        total_value += current_value
        total_cost += total_cost_pos
    
    # Blue Engine 持仓 (科技对冲)
    blue_positions = blue_data.get('positions', {})
    for symbol, pos in blue_positions.items():
        shares = pos.get('stock_shares', 0)
        cost_price = pos.get('stock_cost', 0)
        total_cost_pos = shares * cost_price
        
        current_price = realtime_prices.get(symbol, {}).get('current', cost_price)
        current_value = shares * current_price
        profit = current_value - total_cost_pos
        profit_pct = (profit / total_cost_pos * 100) if total_cost_pos > 0 else 0
        
        bench_sym = pos.get('bench_sym', '')
        bench_name = '中证1000ETF' if bench_sym == 'sh512100' else '沪深300ETF' if bench_sym == 'sh510300' else bench_sym
        
        all_positions[symbol] = {
            '持股数量': shares,
            '持仓均价': cost_price,
            '当前价格': current_price,
            '当前市值': current_value,
            '占用资金': total_cost_pos,
            '盈亏金额': profit,
            '盈亏比例': profit_pct,
            '买入时间': '历史持仓',
            '信号来源': f'Blue Engine (对冲: {bench_name})',
            '引擎': 'Blue Engine'
        }
        total_value += current_value
        total_cost += total_cost_pos

    if all_positions:
        df_pos = pd.DataFrame.from_dict(all_positions, orient='index').reset_index()
        df_pos.columns = ['股票代码', '持股数量', '持仓均价', '当前价格', '当前市值', '占用资金', '盈亏金额', '盈亏比例', '买入时间', '信号来源', '引擎']
        
        # 汇总行
        total_profit = df_pos['盈亏金额'].sum()
        total_profit_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0
        
        st.markdown(f"**📊 持仓汇总**: 总市值 `¥{total_value:,.2f}` | 总成本 `¥{total_cost:,.2f}` | 总盈亏 `{'🟢' if total_profit >= 0 else '🔴'} ¥{total_profit:,.2f}` ({total_profit_pct:+.2f}%)")

        col_tm, col_pie = st.columns([2, 1])

        with col_tm:
            # 绘制树状图
            fig_treemap = px.treemap(
                df_pos, path=['引擎', '股票代码'], values='当前市值',
                title="多头仓位资金热力图 (Treemap)",
                color='当前市值', color_continuous_scale='Blues'
            )
            st.plotly_chart(fig_treemap, use_container_width=True)

        with col_pie:
            # 引擎资金占用饼图
            fig_pie = px.pie(df_pos, names='引擎', values='当前市值', hole=0.4, title="引擎资金权重占比")
            st.plotly_chart(fig_pie, use_container_width=True)

        # 持仓明细表格（带颜色）
        def color_profit(val):
            if isinstance(val, (int, float)):
                color = 'lightgreen' if val >= 0 else 'lightcoral'
                return f'background-color: {color}'
            return ''
        
        st.dataframe(
            df_pos.style.applymap(color_profit, subset=['盈亏金额', '盈亏比例'])
            .format({'持仓均价': '¥{:.3f}', '当前价格': '¥{:.3f}', '当前市值': '¥{:,.2f}', '占用资金': '¥{:,.2f}', '盈亏金额': '¥{:+,.2f}', '盈亏比例': '{:+.2f}%'}),
            use_container_width=True
        )
    else:
        st.success("🟢 当前无多头持仓，现金为王。")

# ----------------- Tab 3: TCA 与滑点分析 -----------------
with tab3:
    st.subheader("交易摩擦成本审计 (TCA)")
    st.markdown("监控你的实盘执行是否被 **滑点** 和 **印花税** 吞噬了超额收益。")

    trades = alpha_data.get('trades', [])
    if trades:
        df_trades = pd.DataFrame(trades)
        if 'profit' in df_trades.columns:
            sells = df_trades[df_trades['type'] == 'sell'].copy()
            if not sells.empty:
                sells['time'] = pd.to_datetime(sells['time'])

                # 滑点与盈亏时序图
                fig_tca = px.bar(
                    sells, x='time', y='profit', color='profit',
                    color_continuous_scale=px.colors.diverging.RdYlGn,
                    hover_data=['symbol', 'reason'],
                    title="逐笔平仓盈亏瀑布图 (扣除千分之二摩擦成本后)"
                )
                st.plotly_chart(fig_tca, use_container_width=True)

                st.markdown(f"**累计实盘扣费后净利润:** `¥ {sells['profit'].sum():.2f}`")
            else:
                st.info("尚无平仓记录。")
    else:
         st.info("尚无交易流水。")

# ----------------- Tab 4: 底层系统数据 -----------------
with tab4:
    st.subheader("📜 原始系统 JSON 日志")
    col_j1, col_j2 = st.columns(2)
    with col_j1:
        st.markdown("**alpha_factory_portfolio.json**")
        st.json(alpha_data, expanded=False)
    with col_j2:
        st.markdown("**strategy_performance.json**")
        st.json(perf_data, expanded=False)
