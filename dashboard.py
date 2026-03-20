import streamlit as st
import json
import pandas as pd
import os
import time

# ==========================================
# APEX 影子基金 - 云端可视化监控台 (Streamlit)
# 运行命令: streamlit run dashboard.py --server.port 8501
# ==========================================

# 页面配置
st.set_page_config(page_title="APEX Shadow Fund", page_icon="📈", layout="wide")

# 常量定义
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RED_PORTFOLIO = os.path.join(SCRIPT_DIR, "apex_portfolio.json")
BLUE_PORTFOLIO = os.path.join(SCRIPT_DIR, "apex_tech_portfolio.json")

def load_json(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            st.error(f"读取文件失败: {filepath} \n报错: {e}")
    return None

# ================= UI 侧边栏 =================
st.sidebar.title("⚙️ APEX 控制中心")
st.sidebar.markdown("实时监控双引擎账本状态")
if st.sidebar.button("🔄 手动刷新数据"):
    pass # Streamlit 按钮点击会自动 rerun
st.sidebar.markdown("---")
st.sidebar.info("💡 提示: 开启右上角的 'Run on save' 可实现代码更新时自动刷新。")

# ================= 主界面 =================
st.title("🚀 APEX 影子量化对冲基金 - 监控大屏")
st.markdown(f"**最后更新时间**: `{time.strftime('%Y-%m-%d %H:%M:%S')}`")

# 读取双轨账本
red_data = load_json(RED_PORTFOLIO)
blue_data = load_json(BLUE_PORTFOLIO)

if not red_data or not blue_data:
    st.warning("⚠️ 暂未找到完整的双轨账本 (apex_portfolio.json / apex_tech_portfolio.json)，请确认引擎已启动并生成账本。")
    st.stop()

# ================= 核心数据区 =================
st.header("1. 资产总览 (Asset Overview)")

col1, col2, col3 = st.columns(3)

# 简化的净值估算 (此处仅显示现金流状态，实际净值需接入实时行情)
red_cash = red_data.get('cash', 0)
blue_cash = blue_data.get('cash', 0)
total_cash = red_cash + blue_cash

with col1:
    st.metric(label="💰 基金总现金流", value=f"¥ {total_cash:,.2f}")
with col2:
    st.metric(label="🔴 Red Engine (防守) 现金", value=f"¥ {red_cash:,.2f}")
with col3:
    st.metric(label="🔵 Blue Engine (进攻) 现金", value=f"¥ {blue_cash:,.2f}")

st.markdown("---")

# ================= 持仓状态区 =================
st.header("2. 实时战斗序列 (Live Positions)")

col_red, col_blue = st.columns(2)

with col_red:
    st.subheader("🔴 红利抄底军团 (Red Engine)")
    red_pos = red_data.get('positions', {})
    if red_pos:
        df_red = pd.DataFrame.from_dict(red_pos, orient='index')
        # 整理显示的列名
        if not df_red.empty:
            df_red = df_red.reset_index().rename(columns={'index': '股票代码', 'total_shares': '总股数', 'cost': '持仓成本'})
            st.dataframe(df_red[['股票代码', '总股数', '持仓成本']], use_container_width=True)
    else:
        st.info("当前空仓，等待 Z < -1.5 极度恐慌出现...")

with col_blue:
    st.subheader("🔵 科技动量对冲军团 (Blue Engine)")
    blue_pos = blue_data.get('positions', {})
    if blue_pos:
        df_blue = pd.DataFrame.from_dict(blue_pos, orient='index')
        if not df_blue.empty:
            df_blue = df_blue.reset_index().rename(columns={
                'index': '多头标的', 
                'stock_shares': '做多股数', 
                'bench_sym': '空头基准', 
                'bench_shares': '做空股数',
                'beta_applied': '执行Beta'
            })
            st.dataframe(df_blue[['多头标的', '做多股数', '空头基准', '做空股数', '执行Beta']], use_container_width=True)
    else:
        st.info("当前空仓，等待多因子共振 (低波+动量突破) 出现...")

# ================= 状态机与队列检查 =================
st.markdown("---")
st.header("3. 引擎微观队列监控 (Engine Queues)")
with st.expander("查看价格缓冲队列 (Price Queues)"):
    st.json({
        "Red Engine 队列池大小": len(red_data.get('price_queue', {})),
        "Blue Engine 队列池大小": len(blue_data.get('queues', {}))
    })
