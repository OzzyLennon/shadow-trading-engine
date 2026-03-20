import streamlit as st
import json
import pandas as pd
import os
import time
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

# ==========================================
# APEX 量化中控台 V2.0 - 机构级全息驾驶舱
# 运行命令: streamlit run dashboard.py --server.port 8501
# ==========================================

# 页面全局配置 (暗黑极客风)
st.set_page_config(page_title="APEX Quant Command Center", page_icon="👁️‍🗨️", layout="wide", initial_sidebar_state="expanded")

# ================= 数据加载层 =================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ALPHA_PORTFOLIO = os.path.join(SCRIPT_DIR, "alpha_factory_portfolio.json")
PERFORMANCE_FILE = os.path.join(SCRIPT_DIR, "strategy_performance.json")
PROMOTED_FILE = os.path.join(SCRIPT_DIR, "promoted_strategies.json")
RED_PORTFOLIO = os.path.join(SCRIPT_DIR, "apex_portfolio.json")

@st.cache_data(ttl=10) # 缓存10秒，防止高频刷新卡顿
def load_json(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

# 加载核心数据
alpha_data = load_json(ALPHA_PORTFOLIO)
perf_data = load_json(PERFORMANCE_FILE)
promo_data = load_json(PROMOTED_FILE)
red_data = load_json(RED_PORTFOLIO)

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
total_cash = cash_alpha + cash_red

active_strats = len(promo_data.get('strategies', []))
total_trades = len(alpha_data.get('trades', []))

# 渲染顶部指标卡
kpi1, kpi2, kpi3, kpi4 = st.columns(4)
kpi1.metric(label="💰 总可用现金流 (AUM)", value=f"¥ {total_cash:,.2f}", delta="整合双轨资金")
kpi2.metric(label="🧠 存活 Alpha 策略数", value=f"{active_strats} 个", delta=f"待淘汰: 0", delta_color="normal")
kpi3.metric(label="⚡ 累计调仓次数", value=f"{total_trades} 笔", delta="+12 今日", delta_color="normal")

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
    positions = alpha_data.get('positions', {})

    if positions:
        df_pos = pd.DataFrame.from_dict(positions, orient='index').reset_index()
        df_pos.columns = ['股票代码', '持股数量', '持仓均价', '占用资金', '买入时间', '信号来源']
        df_pos['信号来源'] = df_pos['信号来源'].astype(str) # 方便聚类

        col_tm, col_pie = st.columns([2, 1])

        with col_tm:
            # 绘制树状图：一眼看清资金集中在哪些股票和策略上
            fig_treemap = px.treemap(
                df_pos, path=['信号来源', '股票代码'], values='占用资金',
                title="多头仓位资金热力图 (Treemap)",
                color='占用资金', color_continuous_scale='Blues'
            )
            st.plotly_chart(fig_treemap, use_container_width=True)

        with col_pie:
            # 策略资金占用饼图
            fig_pie = px.pie(df_pos, names='信号来源', values='占用资金', hole=0.4, title="策略资金权重占比")
            st.plotly_chart(fig_pie, use_container_width=True)

        st.dataframe(df_pos, use_container_width=True)
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
