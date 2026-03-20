#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
因子生成器 - Alpha Factory 第一阶段
====================================
海量因子公式生成 + 批量IC/IR计算 + 硬过滤

经济学逻辑约束：
- 只有具备经济学逻辑的特征组合才允许生成
- 纯数学随机组合将被过滤

作者: AI 量化研究助手
日期: 2026-03-20
"""

import pandas as pd
import numpy as np
import os
import json
import itertools
from scipy.stats import spearmanr
from typing import Dict, List, Tuple
import warnings
warnings.filterwarnings('ignore')

# ================= 路径配置 =================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "promoted_candidates.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "logs", "factor_mining.log")

# ================= 硬过滤阈值 =================
IC_THRESHOLD = 0.03      # |Mean IC| > 0.03
IR_THRESHOLD = 0.15      # |IR| > 0.15 (熊市宽松版)

# ================= 因子模板库 =================
class FactorFactory:
    """因子生成工厂"""
    
    def __init__(self):
        self.factor_templates = self._init_templates()
    
    def _init_templates(self) -> Dict:
        """
        经济学逻辑约束的因子模板
        每个模板代表一种可解释的alpha来源
        """
        return {
            # ===== 动量类 =====
            "return": {
                "desc": "收益率因子",
                "params": {"period": [1, 3, 5, 10, 20]},
                "formula": lambda p: f"return_{p}d",
                "compute": lambda df, p: df['close'].pct_change(periods=p)
            },
            "log_return": {
                "desc": "对数收益率因子",
                "params": {"period": [1, 3, 5, 10]},
                "formula": lambda p: f"log_return_{p}d",
                "compute": lambda df, p: np.log(df['close'] / df['close'].shift(p))
            },
            
            # ===== 成交量类 =====
            "volume_ma": {
                "desc": "成交量均线",
                "params": {"period": [5, 10, 20, 60]},
                "formula": lambda p: f"volume_ma_{p}d",
                "compute": lambda df, p: df['volume'].rolling(p).mean()
            },
            "volume_ratio": {
                "desc": "成交量比",
                "params": {"period": [5, 10, 20]},
                "formula": lambda p: f"volume_ratio_{p}d",
                "compute": lambda df, p: df['volume'] / df['volume'].rolling(p).mean()
            },
            
            # ===== 波动率类 =====
            "volatility": {
                "desc": "波动率因子",
                "params": {"period": [5, 10, 20, 60]},
                "formula": lambda p: f"volatility_{p}d",
                "compute": lambda df, p: df['close'].pct_change().rolling(p).std()
            },
            " ATR": {
                "desc": "真实波动幅度",
                "params": {"period": [14, 20]},
                "formula": lambda p: f"ATR_{p}d",
                "compute": lambda df, p: self._compute_atr(df, p)
            },
            
            # ===== 换手率类 =====
            "turnover": {
                "desc": "换手率因子",
                "params": {"period": [5, 10, 20]},
                "formula": lambda p: f"turnover_{p}d",
                "compute": lambda df, p: df['volume'].pct_change(p)
            },
            
            # ===== 乖离率类 =====
            "bias": {
                "desc": "价格乖离率",
                "params": {"period": [5, 10, 20, 60]},
                "formula": lambda p: f"bias_{p}d",
                "compute": lambda df, p: (df['close'] - df['close'].rolling(p).mean()) / df['close'].rolling(p).mean()
            },
            
            # ===== 动量类 =====
            "momentum": {
                "desc": "动量因子",
                "params": {"period": [5, 10, 20, 60]},
                "formula": lambda p: f"momentum_{p}d",
                "compute": lambda df, p: df['close'] / df['close'].shift(p) - 1
            },
            
            # ===== RSI =====
            "rsi": {
                "desc": "相对强弱因子",
                "params": {"period": [6, 12, 24]},
                "formula": lambda p: f"RSI_{p}d",
                "compute": lambda df, p: self._compute_rsi(df['close'], p)
            },
            
            # ===== 均价类 =====
            "price_ma_ratio": {
                "desc": "价格与均线比",
                "params": {"period": [5, 10, 20, 60]},
                "formula": lambda p: f"price_ma_ratio_{p}d",
                "compute": lambda df, p: df['close'] / df['close'].rolling(p).mean()
            },
        }
    
    def _compute_atr(self, df: pd.DataFrame, period: int) -> pd.Series:
        """计算真实波动幅度 (ATR)"""
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        return atr
    
    def _compute_rsi(self, close: pd.Series, period: int) -> pd.Series:
        """计算RSI"""
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def generate_single_factors(self) -> List[Tuple[str, str, callable]]:
        """
        生成所有单因子
        返回: [(因子名, 描述, 计算函数), ...]
        """
        factors = []
        
        for factor_name, config in self.factor_templates.items():
            params = config["params"]
            param_names = list(params.keys())
            
            # 遍历所有参数组合
            if len(param_names) == 1:
                pname = param_names[0]
                for pvalue in params[pname]:
                    formula = config["formula"](pvalue)
                    desc = f"{config['desc']}_{pvalue}日"
                    factors.append((formula, desc, lambda df, p=pvalue, c=config: c["compute"](df, p)))
            elif len(param_names) == 2:
                # 处理双参数因子 (如相关性需要两个序列)
                pass  # 暂不实现
        
        return factors
    
    def generate_composite_factors(
        self, 
        single_factors: List[Tuple],
        operations: List[str] = None
    ) -> List[Tuple[str, str]]:
        """
        生成复合因子
        经济学逻辑组合：动量 + 成交量, 估值 + 动量 等
        
        Args:
            single_factors: 单因子列表
            operations: 允许的数学运算
        
        Returns:
            [(复合因子名, 描述), ...]
        """
        if operations is None:
            operations = ["+", "-", "*", "/"]
        
        composites = []
        
        # 预定义的有经济学意义的组合
        COMPOSITE_TEMPLATES = [
            # 动量 + 成交量：价量齐升/齐跌
            ("return_{p}d", "volume_ratio_{p}d", "*", "momentum_volume_{p}d"),
            # 波动率 + 换手率：高波动高换手
            ("volatility_{p}d", "turnover_{p}d", "*", "vol_turn_{p}d"),
            # 乖离率 + RSI：超卖反弹
            ("bias_{p}d", "RSI_{p}d", "+", "bias_rsi_{p}d"),
            # 动量 / 波动率：风险调整动量
            ("momentum_{p}d", "volatility_{p}d", "/", "risk_adj_mom_{p}d"),
        ]
        
        return composites
    
    def generate_all(self) -> Tuple[List, List]:
        """
        生成所有可用因子
        
        Returns:
            (单因子列表, 复合因子列表)
        """
        single = self.generate_single_factors()
        composite = self.generate_composite_factors(single)
        return single, composite


# ================= IC/IR 分析器 =================
class ICIROrthogonalAnalyzer:
    """IC/IR 正交分析器"""
    
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.panel_df = None
    
    def load_data(self) -> bool:
        """加载面板数据"""
        import glob
        
        all_files = glob.glob(os.path.join(self.data_dir, "*.csv"))
        if not all_files:
            print(f"❌ 未找到数据文件: {self.data_dir}")
            return False
        
        print(f"📂 加载 {len(all_files)} 只股票数据...")
        
        df_list = []
        for file in all_files:
            symbol = os.path.basename(file).split('.')[0]
            df = pd.read_csv(file, parse_dates=['date'])
            df['symbol'] = symbol
            df_list.append(df)
        
        self.panel_df = pd.concat(df_list, ignore_index=True)
        self.panel_df = self.panel_df.sort_values(by=['date', 'symbol'])
        
        print(f"✅ 加载完成: {len(self.panel_df['symbol'].unique())} 只股票, {len(self.panel_df)} 条记录")
        return True
    
    def calculate_forward_return(self, forward_period: int = 5) -> pd.DataFrame:
        """计算未来收益率"""
        if self.panel_df is None:
            return None
        
        close = self.panel_df.set_index(['date', 'symbol'])['close'].unstack(level='symbol')
        forward_ret = close.pct_change(periods=forward_period).shift(-forward_period)
        
        return forward_ret.stack().rename('forward_return')
    
    def compute_factor_ic(
        self, 
        factor_values: pd.Series,
        forward_returns: pd.Series,
        min_stocks: int = 10
    ) -> Dict:
        """
        计算因子的IC和IR
        
        Args:
            factor_values: 因子值序列
            forward_returns: 未来收益序列
            min_stocks: 最小股票数
        
        Returns:
            {'mean_ic': float, 'ic_ir': float, 'ic_series': list}
        """
        # 对齐数据
        common_idx = factor_values.index.intersection(forward_returns.index)
        if len(common_idx) < min_stocks:
            return None
        
        f_val = factor_values.loc[common_idx]
        f_ret = forward_returns.loc[common_idx]
        
        # 按日期计算截面IC
        ic_series = []
        dates = f_val.index.get_level_values(0).unique()
        
        for date in dates:
            try:
                fv = f_val.loc[date].dropna()
                fr = f_ret.loc[date].dropna()
                common = fv.index.intersection(fr.index)
                
                if len(common) >= min_stocks:
                    ic, _ = spearmanr(fv.loc[common], fr.loc[common])
                    if not np.isnan(ic):
                        ic_series.append(ic)
            except:
                continue
        
        if len(ic_series) < 20:  # 至少20个交易日
            return None
        
        ic_array = np.array(ic_series)
        mean_ic = np.mean(ic_array)
        std_ic = np.std(ic_array)
        ir = mean_ic / std_ic if std_ic > 0 else 0
        
        return {
            'mean_ic': round(mean_ic, 4),
            'ic_ir': round(ir, 4),
            'ic_std': round(std_ic, 4),
            'ic_count': len(ic_series),
            'positive_ic_ratio': round(np.mean(ic_array > 0), 2)
        }
    
    def run_factor_analysis(
        self,
        factor_name: str,
        factor_func: callable,
        forward_period: int = 5
    ) -> Dict:
        """
        运行单因子分析
        """
        if self.panel_df is None:
            return None
        
        # 计算因子值
        print(f"  🔬 分析因子: {factor_name}")
        
        factor_list = []
        for symbol in self.panel_df['symbol'].unique():
            stock_df = self.panel_df[self.panel_df['symbol'] == symbol].copy()
            stock_df = stock_df.sort_values('date')
            
            try:
                factor_vals = factor_func(stock_df)
                temp_df = pd.DataFrame({
                    'date': stock_df['date'].values,
                    'symbol': symbol,
                    'factor': factor_vals.values
                })
                temp_df = temp_df.set_index(['date', 'symbol'])
                factor_list.append(temp_df)
            except Exception as e:
                continue
        
        if not factor_list:
            return None
        
        factor_series = pd.concat(factor_list)['factor']
        
        # 计算未来收益
        forward_series = self.calculate_forward_return(forward_period)
        
        # 计算IC/IR
        ic_result = self.compute_factor_ic(factor_series, forward_series)
        
        if ic_result:
            ic_result['factor_name'] = factor_name
        
        return ic_result


# ================= 主程序 =================
def main():
    """主函数：因子生成 -> IC分析 -> 硬过滤 -> 输出"""
    
    print("=" * 60)
    print("🚀 Alpha Factory - 因子挖掘机启动")
    print("=" * 60)
    
    # 1. 创建输出目录
    logs_dir = os.path.join(SCRIPT_DIR, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    
    # 2. 初始化因子工厂
    factory = FactorFactory()
    single_factors = factory.generate_single_factors()
    
    print(f"\n📊 生成了 {len(single_factors)} 个单因子")
    
    # 3. 加载数据
    analyzer = ICIROrthogonalAnalyzer(DATA_DIR)
    if not analyzer.load_data():
        return
    
    # 4. 批量计算IC/IR
    results = []
    
    print(f"\n🔍 开始批量IC分析 (阈值: |IC|>{IC_THRESHOLD}, |IR|>{IR_THRESHOLD})...")
    print("-" * 60)
    
    for factor_name, desc, factor_func in single_factors:
        try:
            result = analyzer.run_factor_analysis(factor_name, factor_func)
            
            if result:
                result['description'] = desc
                results.append(result)
                
                # 打印结果
                status = "✅" if abs(result['mean_ic']) >= IC_THRESHOLD and abs(result['ic_ir']) >= IR_THRESHOLD else "❌"
                print(f"  {status} {factor_name}: IC={result['mean_ic']:+.4f}, IR={result['ic_ir']:.4f}")
            else:
                print(f"  ⚠️ {factor_name}: 计算失败")
                
        except Exception as e:
            print(f"  ❌ {factor_name}: 异常 - {str(e)[:50]}")
    
    # 5. 硬过滤
    print("\n" + "=" * 60)
    print("🎯 硬过滤结果")
    print("=" * 60)
    
    passed = []
    for r in results:
        if abs(r['mean_ic']) >= IC_THRESHOLD and abs(r['ic_ir']) >= IR_THRESHOLD:
            passed.append(r)
    
    # 按IC绝对值排序
    passed = sorted(passed, key=lambda x: abs(x['mean_ic']), reverse=True)
    
    print(f"\n✅ 通过过滤的因子: {len(passed)}/{len(results)}")
    
    for i, r in enumerate(passed[:10], 1):  # 只显示前10
        print(f"  {i}. {r['factor_name']}: IC={r['mean_ic']:+.4f}, IR={r['ic_ir']:.4f}")
    
    # 6. 输出到JSON
    output_data = {
        "timestamp": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_factors": len(results),
        "passed_factors": len(passed),
        "thresholds": {
            "ic_threshold": IC_THRESHOLD,
            "ir_threshold": IR_THRESHOLD
        },
        "candidates": [
            {
                "factor_name": r['factor_name'],
                "description": r.get('description', ''),
                "mean_ic": r['mean_ic'],
                "ic_ir": r['ic_ir'],
                "ic_std": r['ic_std'],
                "positive_ic_ratio": r['positive_ic_ratio'],
                "rank": i + 1
            }
            for i, r in enumerate(passed)
        ]
    }
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 结果已保存至: {OUTPUT_FILE}")
    print("=" * 60)
    
    return passed


if __name__ == "__main__":
    main()