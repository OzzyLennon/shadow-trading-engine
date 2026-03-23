"""
测试优化后的核心函数
"""
import pytest
import math
from core.functions import (
    calculate_z_score_improved,
    calculate_volatility,
    adaptive_z_threshold,
    check_stop_loss,
    confirm_buy_signal,
    confirm_sell_signal,
    calculate_beta_robust,
    calculate_dynamic_beta_improved,
    calculate_rsi,
)


class TestImprovedZScore:
    """改进的Z-Score计算测试"""

    def test_basic_calculation(self):
        """基本计算测试"""
        # 创建一个稳定上涨的价格序列
        prices = [100 + i * 0.5 for i in range(20)]
        z = calculate_z_score_improved(prices, window=20)
        # 最后价格高于均值，Z应为正
        assert z > 0

    def test_negative_z_score(self):
        """负Z-Score测试（价格低于均值）"""
        # 创建一个下跌序列
        prices = [100 - i * 0.5 for i in range(20)]
        z = calculate_z_score_improved(prices, window=20)
        # 最后价格低于均值，Z应为负
        assert z < 0

    def test_insufficient_data(self):
        """数据不足时返回0"""
        prices = [100, 101]
        z = calculate_z_score_improved(prices, window=20)
        assert z == 0.0

    def test_constant_prices(self):
        """价格不变时返回0"""
        prices = [100] * 20
        z = calculate_z_score_improved(prices, window=20)
        assert z == 0.0


class TestVolatility:
    """波动率计算测试"""

    def test_basic_volatility(self):
        """基本波动率计算"""
        prices = [100, 101, 102, 101, 100, 99, 100, 101]
        vol = calculate_volatility(prices)
        assert vol > 0
        assert vol < 1  # 日波动率应该小于1

    def test_zero_volatility(self):
        """零波动率"""
        prices = [100, 100, 100, 100]
        vol = calculate_volatility(prices)
        assert vol == 0.0

    def test_insufficient_data(self):
        """数据不足"""
        prices = [100]
        vol = calculate_volatility(prices)
        assert vol == 0.0


class TestAdaptiveThreshold:
    """自适应阈值测试"""

    def test_high_volatility_tightens_threshold(self):
        """高波动时收紧阈值（需要更大偏离才触发）"""
        # 创建高波动序列（大幅震荡）- 每天波动约10%
        prices = []
        base = 100
        for i in range(30):
            # 交替涨跌5%
            if i % 2 == 0:
                prices.append(base * 1.05)
            else:
                prices.append(base * 0.95)

        # 先验证这是高波动
        vol = calculate_volatility(prices[-20:])
        assert vol > 0.02, f"Expected high volatility > 0.02, got {vol}"

        adaptive = adaptive_z_threshold(prices, base_threshold=-1.5, lookback=20)
        # 高波动时，阈值应该更严格（更远离0，即更小的值）
        # 例如 -1.8 < -1.5（需要更大下跌才触发）
        assert adaptive < -1.5, f"High vol {vol:.3f} should tighten threshold, got {adaptive}"

    def test_low_volatility_relaxes_threshold(self):
        """低波动时放宽阈值（更敏感，小偏离就触发）"""
        # 创建低波动序列（几乎不变）
        prices = [100 + i * 0.0001 for i in range(30)]

        # 先验证这是低波动
        vol = calculate_volatility(prices[-20:])
        assert vol < 0.01, f"Expected low volatility < 0.01, got {vol}"

        adaptive = adaptive_z_threshold(prices, base_threshold=-1.5, lookback=20)
        # 低波动时，阈值应该更宽松（更接近0，即更大的值）
        # 例如 -1.2 > -1.5（更敏感，小波动就触发）
        assert adaptive > -1.5, f"Low vol {vol:.3f} should relax threshold, got {adaptive}"

    def test_insufficient_data_returns_base(self):
        """数据不足时返回基础阈值"""
        prices = [100, 101]
        adaptive = adaptive_z_threshold(prices, base_threshold=-1.5, lookback=20)
        assert adaptive == -1.5

    def test_medium_volatility_interpolates(self):
        """中等波动时线性插值"""
        # 创建中等波动序列 - 约1.5%日波动
        # 使用更小的波动幅度
        prices = [100 * (1 + 0.008 * ((-1) ** i)) for i in range(30)]

        vol = calculate_volatility(prices[-20:])
        # 应该在1%-2%之间
        assert 0.01 <= vol <= 0.02, f"Expected medium volatility, got {vol}"

        adaptive = adaptive_z_threshold(prices, base_threshold=-1.5, lookback=20)
        # 应该在基础值附近（插值结果）
        assert -1.6 <= adaptive <= -1.4


class TestStopLoss:
    """止损检查测试"""

    def test_fixed_stop_loss(self):
        """固定止损触发"""
        position = {"cost": 100, "peak_price": 100}
        current_price = 90  # 下跌10%

        triggered, reason = check_stop_loss(position, current_price, max_loss=0.08)
        assert triggered is True
        assert "固定止损" in reason

    def test_trailing_stop(self):
        """移动止损触发"""
        position = {"cost": 100, "peak_price": 120}  # 曾涨到120
        current_price = 112  # 从峰值回撤超过5%

        triggered, reason = check_stop_loss(position, current_price, max_loss=0.10, trailing_stop=0.05)
        assert triggered is True
        assert "移动止损" in reason

    def test_no_stop_loss(self):
        """未触发止损"""
        position = {"cost": 100, "peak_price": 105}
        current_price = 102  # 盈利中，未触发止损

        triggered, reason = check_stop_loss(position, current_price, max_loss=0.08, trailing_stop=0.05)
        assert triggered is False

    def test_small_loss_no_stop(self):
        """小幅亏损不触发止损"""
        position = {"cost": 100, "peak_price": 100}
        current_price = 95  # 下跌5%，小于8%止损线

        triggered, reason = check_stop_loss(position, current_price, max_loss=0.08, trailing_stop=0.05)
        assert triggered is False


class TestConfirmBuySignal:
    """买入信号确认测试"""

    def test_single_factor_not_confirmed(self):
        """单一因子不确认"""
        confirmed, details = confirm_buy_signal(
            z_score=-2.0,
            volume_ratio=1.0,  # 未放量
            price_vs_ema=0.0,  # 未低于均线
            rsi=50,  # 未超卖
            min_confirmations=2
        )
        assert confirmed is False
        assert details["z_score"] is True
        assert details["volume"] is False

    def test_two_factors_confirmed(self):
        """两个因子确认"""
        confirmed, details = confirm_buy_signal(
            z_score=-2.0,
            volume_ratio=1.5,  # 放量
            price_vs_ema=-0.03,  # 低于均线3%
            rsi=50,
            min_confirmations=2
        )
        assert confirmed is True
        assert details["z_score"] is True
        assert details["volume"] is True
        assert details["price_below_ema"] is True

    def test_all_factors_confirmed(self):
        """所有因子确认"""
        confirmed, details = confirm_buy_signal(
            z_score=-2.0,
            volume_ratio=1.5,
            price_vs_ema=-0.03,
            rsi=25,  # 超卖
            min_confirmations=2
        )
        assert confirmed is True
        assert all(details.values())


class TestConfirmSellSignal:
    """卖出信号确认测试"""

    def test_profit_target_confirmed(self):
        """盈利目标确认"""
        confirmed, details = confirm_sell_signal(
            z_score=0.5,
            profit_ratio=0.08,
            min_confirmations=1
        )
        assert confirmed is True
        assert details["profit_target"] is True

    def test_momentum_exhausted(self):
        """动量衰竭"""
        confirmed, details = confirm_sell_signal(
            z_score=-0.5,
            momentum_exhausted=True,
            min_confirmations=1
        )
        assert confirmed is True


class TestBetaCalculation:
    """Beta计算测试"""

    def test_robust_beta_calculation(self):
        """稳健Beta计算"""
        # 创建相关但不完全同步的收益率序列
        stock_returns = [0.01 + i * 0.001 for i in range(40)]
        bench_returns = [0.008 + i * 0.001 for i in range(40)]

        beta = calculate_beta_robust(stock_returns, bench_returns, min_points=30)
        # Beta应该接近1（因为两个序列走势相似）
        assert 0.5 < beta < 2.0

    def test_insufficient_data_returns_neutral(self):
        """数据不足返回中性值"""
        stock_returns = [0.01, 0.02]
        bench_returns = [0.01, 0.02]

        beta = calculate_beta_robust(stock_returns, bench_returns, min_points=30)
        assert beta == 1.0

    def test_dynamic_beta_improved(self):
        """改进的动态Beta"""
        stock_prices = [100 + i * 0.5 for i in range(70)]
        bench_prices = [100 + i * 0.4 for i in range(70)]

        beta = calculate_dynamic_beta_improved(stock_prices, bench_prices, window=60)
        # Beta应该接近1
        assert 0.3 <= beta <= 2.5


class TestRSI:
    """RSI计算测试"""

    def test_overbought_condition(self):
        """超买区域"""
        # 持续上涨
        prices = [100 + i for i in range(20)]
        rsi = calculate_rsi(prices, period=14)
        assert rsi > 70  # 超买

    def test_oversold_condition(self):
        """超卖区域"""
        # 持续下跌
        prices = [100 - i for i in range(20)]
        rsi = calculate_rsi(prices, period=14)
        assert rsi < 30  # 超卖

    def test_neutral_rsi(self):
        """中性RSI"""
        # 横盘震荡
        prices = [100, 101, 100, 101, 100, 101] * 3
        rsi = calculate_rsi(prices, period=14)
        # 横盘时RSI应该在中性区域
        assert 40 < rsi < 60

    def test_insufficient_data(self):
        """数据不足"""
        prices = [100, 101]
        rsi = calculate_rsi(prices, period=14)
        assert rsi == 50.0  # 中性值
