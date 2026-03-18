# -*- coding: utf-8 -*-
"""
前进式分析模块 (Walk-Forward Analysis)
=======================================
实现滚动窗口交叉验证，防止策略过拟合

核心逻辑：
1. 用训练窗口优化参数
2. 用测试窗口验证性能
3. 滚动窗口重复以上步骤
4. 汇总所有样本外测试结果

这是 IMA 报告强调的核心防过拟合机制！

作者: AI 量化研究助手
日期: 2026-03-18
"""

import os
import sys
import pandas as pd
import numpy as np
import json
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import logging
from dataclasses import dataclass
import warnings
warnings.filterwarnings('ignore')

# 导入回测引擎
from .backtest_engine import BacktestEngine, ZScoreStrategy

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("WalkForward")


# ================= 数据类定义 =================

@dataclass
class WFWindow:
    """前进式窗口定义"""
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    
    def __str__(self):
        return f"训练: {self.train_start} ~ {self.train_end}, 测试: {self.test_start} ~ {self.test_end}"


@dataclass
class WFResult:
    """单次前进式测试结果"""
    window: WFWindow
    best_params: Dict
    train_performance: Dict
    test_performance: Dict
    test_return: float


# ================= 参数优化器 =================

class ParameterOptimizer:
    """
    参数网格搜索优化器
    
    在训练集上寻找最优参数组合
    """
    
    def __init__(self, param_grid: Dict):
        """
        Args:
            param_grid: 参数网格，如 {'zscore_threshold': [1.5, 2.0, 2.5]}
        """
        self.param_grid = param_grid
        self.best_params = None
        self.best_score = -np.inf
        self.all_results = []
    
    def optimize(
        self,
        data_path: str,
        symbol: str,
        train_start: str,
        train_end: str,
        metric: str = 'sharpe_ratio'
    ) -> Dict:
        """
        在训练集上优化参数
        
        Args:
            data_path: 数据路径
            symbol: 股票代码
            train_start: 训练开始日期
            train_end: 训练结束日期
            metric: 优化目标指标
        
        Returns:
            最优参数字典
        """
        logger.info(f"🔍 参数优化: {train_start} ~ {train_end}")
        
        # 生成参数组合
        from itertools import product
        param_names = list(self.param_grid.keys())
        param_values = list(self.param_grid.values())
        combinations = list(product(*param_values))
        
        logger.info(f"📊 共 {len(combinations)} 种参数组合")
        
        for combo in combinations:
            params = dict(zip(param_names, combo))
            
            try:
                # 运行回测
                engine = BacktestEngine(initial_cash=1000000)
                engine.load_data(symbol, train_start, train_end)
                engine.add_strategy(ZScoreStrategy, **params, printlog=False)
                perf = engine.run()
                
                score = perf.get(metric, 0)
                
                self.all_results.append({
                    'params': params,
                    'score': score,
                    'performance': perf
                })
                
                if score > self.best_score:
                    self.best_score = score
                    self.best_params = params
                    
            except Exception as e:
                logger.warning(f"⚠️ 参数 {params} 回测失败: {e}")
        
        logger.info(f"✅ 最优参数: {self.best_params}, {metric}={self.best_score:.3f}")
        return self.best_params


# ================= 前进式分析引擎 =================

class WalkForwardEngine:
    """
    前进式分析引擎
    
    实现 IMA 报告要求的滚动窗口交叉验证
    """
    
    def __init__(
        self,
        data_path: str,
        symbol: str,
        train_window: int = 252,  # 训练窗口（交易日），默认1年
        test_window: int = 126,   # 测试窗口（交易日），默认半年
        step_size: int = 63,      # 滚动步长（交易日），默认3个月
        anchor: bool = False      # 是否使用扩展窗口
    ):
        """
        Args:
            data_path: 数据路径
            symbol: 股票代码
            train_window: 训练窗口大小（交易日）
            test_window: 测试窗口大小（交易日）
            step_size: 滚动步长（交易日）
            anchor: True=扩展窗口, False=滚动窗口
        """
        self.data_path = data_path
        self.symbol = symbol
        self.train_window = train_window
        self.test_window = test_window
        self.step_size = step_size
        self.anchor = anchor
        
        self.windows: List[WFWindow] = []
        self.results: List[WFResult] = []
        self.returns_series: List[float] = []
        
        logger.info(f"📊 前进式分析配置:")
        logger.info(f"   训练窗口: {train_window} 天")
        logger.info(f"   测试窗口: {test_window} 天")
        logger.info(f"   滚动步长: {step_size} 天")
        logger.info(f"   模式: {'扩展窗口' if anchor else '滚动窗口'}")
    
    def generate_windows(self, start_date: str, end_date: str) -> List[WFWindow]:
        """
        生成前进式窗口
        
        Args:
            start_date: 数据开始日期
            end_date: 数据结束日期
        
        Returns:
            窗口列表
        """
        # 加载数据获取交易日历
        data_file = os.path.join(self.data_path, f"{self.symbol}_daily.csv")
        df = pd.read_csv(data_file)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        
        # 生成交易日列表
        trading_days = df['date'].tolist()
        
        windows = []
        i = 0
        
        while i + self.train_window + self.test_window <= len(trading_days):
            # 训练窗口
            train_start = trading_days[i].strftime('%Y-%m-%d')
            
            if self.anchor:
                # 扩展窗口：训练起点固定
                train_end_idx = i + self.train_window
            else:
                # 滚动窗口：训练窗口固定大小
                train_end_idx = i + self.train_window
            
            train_end = trading_days[train_end_idx - 1].strftime('%Y-%m-%d')
            
            # 测试窗口
            test_start = trading_days[train_end_idx].strftime('%Y-%m-%d')
            test_end_idx = train_end_idx + self.test_window
            
            if test_end_idx > len(trading_days):
                break
            
            test_end = trading_days[test_end_idx - 1].strftime('%Y-%m-%d')
            
            window = WFWindow(
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end
            )
            windows.append(window)
            
            # 滚动
            i += self.step_size
        
        self.windows = windows
        logger.info(f"📅 生成 {len(windows)} 个前进式窗口")
        
        return windows
    
    def run(
        self,
        param_grid: Dict,
        start_date: str = None,
        end_date: str = None
    ) -> Dict:
        """
        运行前进式分析
        
        Args:
            param_grid: 参数网格
            start_date: 数据开始日期
            end_date: 数据结束日期
        
        Returns:
            汇总结果
        """
        logger.info("=" * 60)
        logger.info("🚀 开始前进式分析 (Walk-Forward Analysis)")
        logger.info("=" * 60)
        
        # 生成窗口
        windows = self.generate_windows(start_date, end_date)
        
        if not windows:
            logger.error("❌ 无法生成前进式窗口")
            return {}
        
        # 遍历每个窗口
        for i, window in enumerate(windows):
            logger.info(f"\n{'='*60}")
            logger.info(f"📊 窗口 {i+1}/{len(windows)}: {window}")
            logger.info(f"{'='*60}")
            
            # 1. 在训练集上优化参数
            optimizer = ParameterOptimizer(param_grid)
            best_params = optimizer.optimize(
                self.data_path,
                self.symbol,
                window.train_start,
                window.train_end
            )
            
            # 2. 在训练集上评估（样本内）
            engine_train = BacktestEngine(initial_cash=1000000)
            engine_train.load_data(self.symbol, window.train_start, window.train_end)
            engine_train.add_strategy(ZScoreStrategy, **best_params, printlog=False)
            train_perf = engine_train.run()
            
            # 3. 在测试集上评估（样本外）
            engine_test = BacktestEngine(initial_cash=1000000)
            engine_test.load_data(self.symbol, window.test_start, window.test_end)
            engine_test.add_strategy(ZScoreStrategy, **best_params, printlog=False)
            test_perf = engine_test.run()
            
            # 4. 记录结果
            result = WFResult(
                window=window,
                best_params=best_params,
                train_performance=train_perf,
                test_performance=test_perf,
                test_return=test_perf.get('total_return', 0)
            )
            self.results.append(result)
            self.returns_series.append(result.test_return)
            
            logger.info(f"📈 训练集收益: {train_perf.get('total_return', 0):.2f}%")
            logger.info(f"📉 测试集收益: {test_perf.get('total_return', 0):.2f}%")
        
        # 汇总结果
        return self.summarize()
    
    def summarize(self) -> Dict:
        """
        汇总所有前进式测试结果
        """
        if not self.results:
            return {}
        
        # 提取测试集收益序列
        test_returns = [r.test_return for r in self.results]
        train_returns = [r.train_performance.get('total_return', 0) for r in self.results]
        
        # 计算汇总指标
        avg_test_return = np.mean(test_returns)
        std_test_return = np.std(test_returns)
        
        # 样本外夏普比率
        if std_test_return > 0:
            oos_sharpe = avg_test_return / std_test_return * np.sqrt(2)  # 年化因子
        else:
            oos_sharpe = 0
        
        # 胜率（测试集收益为正的比例）
        win_rate = sum(1 for r in test_returns if r > 0) / len(test_returns) * 100
        
        # 累计收益（复合）
        cumulative_return = 1
        for r in test_returns:
            cumulative_return *= (1 + r/100)
        cumulative_return = (cumulative_return - 1) * 100
        
        # 过拟合概率 (PBO)
        # PBO = 训练集优于测试集的比例
        pbo = sum(1 for tr, te in zip(train_returns, test_returns) if tr > te) / len(self.results)
        
        summary = {
            'total_windows': len(self.results),
            'avg_test_return': avg_test_return,
            'std_test_return': std_test_return,
            'oos_sharpe_ratio': oos_sharpe,
            'win_rate': win_rate,
            'cumulative_return': cumulative_return,
            'pbo': pbo,  # 过拟合概率
            'test_returns': test_returns,
            'train_returns': train_returns
        }
        
        # 打印汇总
        print("\n" + "=" * 60)
        print("📊 前进式分析汇总报告")
        print("=" * 60)
        print(f"📅 总窗口数: {summary['total_windows']}")
        print(f"📈 平均测试收益: {summary['avg_test_return']:.2f}%")
        print(f"📉 收益标准差: {summary['std_test_return']:.2f}%")
        print(f"⚡ 样本外夏普比率: {summary['oos_sharpe_ratio']:.2f}")
        print(f"🎯 测试胜率: {summary['win_rate']:.1f}%")
        print(f"💰 累计收益: {summary['cumulative_return']:.2f}%")
        print(f"⚠️ 过拟合概率 (PBO): {summary['pbo']*100:.1f}%")
        print("=" * 60)
        
        # PBO 解读
        if summary['pbo'] > 0.7:
            print("⚠️ 警告: 过拟合概率很高！策略可能在历史数据上表现良好但实盘失效。")
        elif summary['pbo'] > 0.5:
            print("⚠️ 注意: 存在一定过拟合风险，建议进一步验证。")
        else:
            print("✅ 策略泛化能力良好，过拟合风险较低。")
        
        return summary
    
    def save_results(self, filepath: str):
        """
        保存结果到 JSON
        """
        output = {
            'summary': {
                'total_windows': len(self.results),
                'avg_test_return': float(np.mean([r.test_return for r in self.results])),
                'win_rate': float(sum(1 for r in self.results if r.test_return > 0) / len(self.results) * 100)
            },
            'windows': [
                {
                    'train_start': r.window.train_start,
                    'train_end': r.window.train_end,
                    'test_start': r.window.test_start,
                    'test_end': r.window.test_end,
                    'best_params': r.best_params,
                    'test_return': r.test_return
                }
                for r in self.results
            ]
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        
        logger.info(f"💾 结果已保存: {filepath}")


# ================= 主程序 =================

if __name__ == "__main__":
    # 参数网格 (均值回归策略)
    param_grid = {
        'z_threshold': [-2.0, -1.5, -1.0],
        'window': [5, 10, 15],
        'trade_ratio': [0.2, 0.3, 0.4]
    }
    
    # 创建前进式分析引擎
    data_path = os.path.join(os.path.dirname(__file__), 'data')
    symbol = "sh600000"
    
    wf_engine = WalkForwardEngine(
        data_path=data_path,
        symbol=symbol,
        train_window=252,  # 1年
        test_window=126,   # 半年
        step_size=63       # 3个月滚动
    )
    
    # 运行前进式分析
    summary = wf_engine.run(
        param_grid=param_grid,
        start_date="20220101",
        end_date="20241231"
    )
    
    # 保存结果
    wf_engine.save_results(os.path.join(data_path, "walk_forward_results.json"))
