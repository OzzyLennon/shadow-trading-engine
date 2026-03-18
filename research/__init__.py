# -*- coding: utf-8 -*-
"""
量化研究框架 (Research Framework)
================================

模块列表：
- data_downloader.py: 历史数据下载与清洗
- backtest_engine.py: Backtrader 回测引擎
- walk_forward.py: 前进式分析 (WFA)
- hedge_engine.py: Alpha对冲回测引擎 (新增)

快速开始：
    from research.data_downloader import download_stock_daily
    from research.backtest_engine import BacktestEngine
    from research.walk_forward import WalkForwardEngine
    from research.hedge_engine import AlphaHedgeEngine
"""

from .data_downloader import (
    download_stock_daily,
    download_index_daily,
    download_stock_minute,
    clean_data,
    add_technical_indicators,
    save_to_csv,
    load_from_csv,
    download_stock_pool
)

from .backtest_engine import (
    BacktestEngine,
    ZScoreStrategy,
    BollingerBandsStrategy
)

from .walk_forward import (
    WalkForwardEngine,
    ParameterOptimizer,
    WFWindow,
    WFResult
)

from .hedge_engine import (
    AlphaHedgeEngine,
    AlphaHedgeStrategy,
    run_hedge_backtest_comparison
)

__all__ = [
    # Data
    'download_stock_daily',
    'download_index_daily', 
    'download_stock_minute',
    'clean_data',
    'add_technical_indicators',
    'save_to_csv',
    'load_from_csv',
    'download_stock_pool',
    # Backtest
    'BacktestEngine',
    'ZScoreStrategy',
    'BollingerBandsStrategy',
    # Walk-Forward
    'WalkForwardEngine',
    'ParameterOptimizer',
    'WFWindow',
    'WFResult',
    # Hedge
    'AlphaHedgeEngine',
    'AlphaHedgeStrategy',
    'run_hedge_backtest_comparison'
]
