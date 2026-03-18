import pandas as pd
import numpy as np
import os
from scipy.stats import spearmanr
import glob

# ==========================================
# 因子挖掘实验室：IC (Information Coefficient) 分析仪
# ==========================================

def load_all_data(data_dir):
    """
    读取 data/ 目录下所有的 csv 文件，并拼接成一个庞大的面板数据 (Panel Data)
    """
    print(f"📂 正在加载 {data_dir} 目录下的所有股票数据...")
    all_files = glob.glob(os.path.join(data_dir, "*.csv"))

    if not all_files:
        print("❌ 未找到任何数据，请先使用 data_downloader.py 下载多只股票。")
        return None

    df_list = []
    for file in all_files:
        symbol = os.path.basename(file).split('.')[0]
        df = pd.read_csv(file, parse_dates=['date'])
        df['symbol'] = symbol
        df_list.append(df)

    # 合并所有数据
    panel_df = pd.concat(df_list, ignore_index=True)
    # 按日期和股票代码排序
    panel_df = panel_df.sort_values(by=['date', 'symbol'])
    panel_df.set_index(['date', 'symbol'], inplace=True)

    print(f"✅ 加载完成，共包含 {len(all_files)} 只股票，{len(panel_df)} 条日线数据。")
    return panel_df

def calculate_factors(panel_df):
    """
    在这里计算你的 Alpha 因子
    实验：短期反转因子 (过去 5 天收益率)
    """
    print("🧮 正在计算【短期反转因子】...")

    # 避免 SettingWithCopyWarning
    df = panel_df.copy()

    # 获取每日收盘价
    close_price = df['close'].unstack(level='symbol')

    # 1. 计算因子值：过去 5 个交易日的累计收益率 (Lookback)
    # factor = (today_close - past_5d_close) / past_5d_close
    factor_5d_return = close_price.pct_change(periods=5)

    # 2. 计算未来真实的收益率：未来 5 个交易日的累计收益率 (Forward Return)
    # 这是我们的"真实答案"，用来和因子做对比的。注意要用 shift(-5) 把未来的收益拉到现在来对齐
    forward_5d_return = close_price.pct_change(periods=5).shift(-5)

    return factor_5d_return, forward_5d_return

def analyze_ic(factor_df, forward_return_df):
    """
    计算截面 IC 序列 (Rank IC)
    """
    print("🔬 正在进行截面 IC 分析 (Spearman Rank Correlation)...")

    ic_list = []
    dates = factor_df.index

    for date in dates:
        # 截取当天的因子和未来收益
        f_val = factor_df.loc[date].dropna()
        r_val = forward_return_df.loc[date].dropna()

        # 找到两者的交集（今天既有因子，又有未来收益的股票）
        common_symbols = f_val.index.intersection(r_val.index)

        if len(common_symbols) < 5:
            # 截面股票太少，失去统计意义，跳过
            continue

        f_common = f_val[common_symbols]
        r_common = r_val[common_symbols]

        # 计算秩相关系数 (Spearman)
        ic, p_value = spearmanr(f_common, r_common)

        if not np.isnan(ic):
            ic_list.append({'date': date, 'IC': ic})

    ic_df = pd.DataFrame(ic_list).set_index('date')

    # === 计算统计指标 ===
    mean_ic = ic_df['IC'].mean()
    ir = mean_ic / ic_df['IC'].std() if ic_df['IC'].std() != 0 else 0
    win_rate = (ic_df['IC'] < 0).sum() / len(ic_df) # 对于反转因子，我们期望 IC 为负，所以统计负 IC 的比例

    print("\n" + "="*50)
    print(f"🏆 因子名称: 过去 5 日短期反转 (5-Day Reversal)")
    print("="*50)
    print(f"📊 IC 均值 (Mean IC)   : {mean_ic:.4f}  (绝对值 > 0.03 即为极佳)")
    print(f"⚖️ 信息比率 (IR)       : {ir:.4f}  (绝对值 > 0.5 即为稳定有效)")
    print(f"🎯 胜率 (负相关占比)    : {win_rate*100:.2f}% (越高说明反转效应越明显)")
    print("="*50)

    if mean_ic < -0.02:
        print("💡 结论: 这是一个强有效的反转因子！在 A 股，过去 5 天跌得越狠，未来 5 天涨得越好。")
    elif mean_ic > 0.02:
        print("💡 结论: 这是一个动量因子！强者恒强。")
    else:
        print("💡 结论: 因子有效性较弱，可能沦为随机噪音。")

    return ic_df

if __name__ == "__main__":
    # 假设你的历史数据存放在 research/data 目录下
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

    # 如果本地还没有大量的 csv，需要先提示下载
    if not os.path.exists(data_dir):
        print(f"错误：数据目录 {data_dir} 不存在。")
    else:
        panel_data = load_all_data(data_dir)
        if panel_data is not None:
            factor, forward_return = calculate_factors(panel_data)
            ic_series = analyze_ic(factor, forward_return)
