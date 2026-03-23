import pytest
import sys
import os
from unittest.mock import Mock, patch
import json
from datetime import datetime, timedelta

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

@pytest.fixture
def mock_requests():
    """模拟requests模块"""
    with patch('requests.get') as mock_get:
        yield mock_get

@pytest.fixture
def sample_market_data():
    """示例市场数据"""
    return {
        "sh601088": {"name": "中国神华", "current": 50.0},
        "sh600886": {"name": "国投电力", "current": 15.0},
        "sh601991": {"name": "大唐发电", "current": 4.5}
    }

@pytest.fixture
def sample_portfolio():
    """示例持仓数据"""
    return {
        "date": "2026-03-22",
        "cash": 500000.0,
        "positions": {
            "sh601088": {
                "total_shares": 1000,
                "available_shares": 1000,
                "cost": 48.0,
                "peak_price": 48.0
            }
        },
        "price_queue": {},
        "long_ema_queue": {}
    }

@pytest.fixture
def sample_price_series():
    """示例价格序列"""
    return [100.0, 101.0, 99.0, 98.5, 97.0, 96.0, 95.5, 94.0, 93.5, 92.0]

@pytest.fixture
def sample_returns_series():
    """示例收益率序列"""
    return [0.01, -0.0198, -0.0051, -0.0152, -0.0103, -0.0052, -0.0157, -0.0053, -0.0160]

@pytest.fixture
def trading_config():
    """交易配置"""
    from dataclasses import dataclass
    from typing import Optional

    @dataclass
    class TradingConfig:
        z_score_threshold: float = -1.5
        trade_ratio: float = 0.3
        poll_interval: int = 5
        cooldown_minutes: int = 10
        account_cooldown_minutes: int = 3
        feishu_webhook: Optional[str] = None
        data_source_url: str = "http://hq.sinajs.cn"
        slippage: float = 0.002
        stamp_duty: float = 0.001
        commission: float = 0.00025
        ema_alpha: float = 0.3
        ema_period: int = 20
        momentum_window: int = 10
        min_valid_price: float = 1.0
        price_change_limit: float = 0.20

    return TradingConfig()

@pytest.fixture
def mock_logger():
    """模拟日志记录器"""
    logger = Mock()
    logger.info = Mock()
    logger.debug = Mock()
    logger.warning = Mock()
    logger.error = Mock()
    return logger