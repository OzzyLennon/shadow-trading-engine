"""
核心函数单元测试
测试量化交易系统的核心计算函数
"""
import sys
import os
import math
from datetime import datetime, timedelta

# 导入被测试模块中的函数
# 由于原代码是脚本形式，我们需要导入函数
# 这里我们复制核心函数到测试中，或者重构代码使其可测试
# 暂时先复制核心函数逻辑进行测试

def calculate_z_score(prices):
    """标准的 Z-Score 计算"""
    if len(prices) < 2:
        return 0.0
    returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
    if len(returns) < 2:
        return 0.0

    n = len(returns)
    mu = sum(returns) / n
    variance = sum((r - mu) ** 2 for r in returns) / (n - 1)
    sigma = math.sqrt(variance) if variance > 0 else 0.0001

    r_t = returns[-1]
    return (r_t - mu) / sigma if sigma > 0 else 0.0

def calculate_ema(symbol, price, ema_prices, ema_alpha=0.3):
    """计算EMA"""
    if symbol not in ema_prices:
        ema_prices[symbol] = price
        return price
    ema = ema_alpha * price + (1 - ema_alpha) * ema_prices[symbol]
    ema_prices[symbol] = ema
    return ema

def is_valid_price(symbol, price, prev_prices, min_valid_price=1.0, price_change_limit=0.20):
    """检查价格有效性"""
    if price <= 0 or price < min_valid_price:
        return False
    if symbol in prev_prices and prev_prices[symbol] > 0:
        change_pct = abs(price - prev_prices[symbol]) / prev_prices[symbol]
        if change_pct > price_change_limit:
            return False
    prev_prices[symbol] = price
    return True

def is_trading_time(now, morning_start=(9, 30), morning_end=(11, 30),
                    afternoon_start=(13, 0), afternoon_end=(14, 57)):
    """检查是否为交易时间"""
    if now.weekday() >= 5:
        return False
    current_time = (now.hour, now.minute)
    if morning_start <= current_time < morning_end:
        return True
    if afternoon_start <= current_time < afternoon_end:
        return True
    return False

def is_in_cooldown(symbol, last_trade_times, cooldown_minutes=10):
    """检查是否在冷却期"""
    if symbol not in last_trade_times:
        return False
    return datetime.now() - last_trade_times[symbol] < timedelta(minutes=cooldown_minutes)

def is_account_in_cooldown(last_account_trade, account_cooldown_minutes=3):
    """检查账户是否在冷却期"""
    if last_account_trade is None:
        return False
    return datetime.now() - last_account_trade < timedelta(minutes=account_cooldown_minutes)


class TestCoreFunctions:
    """核心函数测试类"""

    def test_calculate_z_score_basic(self):
        """测试Z-Score基本计算"""
        # 测试正常价格序列
        prices = [100.0, 101.0, 99.0, 98.5, 97.0, 96.0, 95.5, 94.0, 93.5, 92.0]
        z_score = calculate_z_score(prices)
        # Z-Score应为负值（价格下跌）
        assert z_score < 0
        # 验证计算合理性
        assert -10 < z_score < 10

    def test_calculate_z_score_insufficient_data(self):
        """测试数据不足时的Z-Score计算"""
        # 数据点不足
        prices = [100.0]
        assert calculate_z_score(prices) == 0.0

        # 只有两个数据点
        prices = [100.0, 101.0]
        # 应该返回0.0，因为需要至少2个收益率点
        assert calculate_z_score(prices) == 0.0

    def test_calculate_z_score_constant_price(self):
        """测试价格不变时的Z-Score计算"""
        prices = [100.0, 100.0, 100.0, 100.0, 100.0]
        z_score = calculate_z_score(prices)
        # 价格不变时，Z-Score应该为0
        assert abs(z_score) < 0.0001

    def test_calculate_ema_first_price(self):
        """测试EMA首次计算"""
        ema_prices = {}
        price = 100.0
        result = calculate_ema("test_symbol", price, ema_prices)
        assert result == price
        assert ema_prices["test_symbol"] == price

    def test_calculate_ema_smoothing(self):
        """测试EMA平滑效果"""
        ema_prices = {}
        prices = [100.0, 101.0, 99.0, 98.5]
        results = []

        for i, price in enumerate(prices):
            result = calculate_ema("test_symbol", price, ema_prices, ema_alpha=0.5)
            results.append(result)

        # EMA应该比原始价格更平滑
        # 第二个EMA: 0.5*101.0 + 0.5*100.0 = 100.5
        assert abs(results[1] - 100.5) < 0.001
        # 第三个EMA: 0.5*99.0 + 0.5*100.5 = 99.75
        assert abs(results[2] - 99.75) < 0.001

    def test_is_valid_price_basic(self):
        """测试价格有效性检查"""
        prev_prices = {}

        # 有效价格
        assert is_valid_price("test", 100.0, prev_prices, min_valid_price=1.0)
        assert prev_prices["test"] == 100.0

        # 价格过低
        assert not is_valid_price("test2", 0.5, prev_prices, min_valid_price=1.0)

        # 价格为0
        assert not is_valid_price("test3", 0.0, prev_prices, min_valid_price=1.0)

        # 负价格
        assert not is_valid_price("test4", -10.0, prev_prices, min_valid_price=1.0)

    def test_is_valid_price_change_limit(self):
        """测试价格变化限制"""
        # 测试1：正常变化（10%）
        prev_prices1 = {"test1": 100.0}
        assert is_valid_price("test1", 110.0, prev_prices1, price_change_limit=0.20)
        assert prev_prices1["test1"] == 110.0  # 应该更新为新价格

        # 测试2：变化过大（30%，超过20%限制）
        prev_prices2 = {"test2": 100.0}
        assert not is_valid_price("test2", 130.0, prev_prices2, price_change_limit=0.20)
        assert prev_prices2["test2"] == 100.0  # 不应该更新，保持原价

        # 测试3：变化过大负向（-30%，超过20%限制）
        prev_prices3 = {"test3": 100.0}
        assert not is_valid_price("test3", 70.0, prev_prices3, price_change_limit=0.20)
        assert prev_prices3["test3"] == 100.0  # 不应该更新，保持原价

        # 测试4：边界情况（刚好20%变化）
        prev_prices4 = {"test4": 100.0}
        assert is_valid_price("test4", 120.0, prev_prices4, price_change_limit=0.20)
        assert prev_prices4["test4"] == 120.0  # 应该更新

    def test_is_trading_time_weekday(self):
        """测试工作日交易时间"""
        # 周一上午10点
        monday_10am = datetime(2026, 3, 23, 10, 0)  # 2026-03-23是周一
        assert is_trading_time(monday_10am)

        # 周一下午14点
        monday_2pm = datetime(2026, 3, 23, 14, 0)
        assert is_trading_time(monday_2pm)

        # 周一上午9点（交易时间前）
        monday_9am = datetime(2026, 3, 23, 9, 0)
        assert not is_trading_time(monday_9am)

        # 周一下午15点（交易时间后）
        monday_3pm = datetime(2026, 3, 23, 15, 0)
        assert not is_trading_time(monday_3pm)

    def test_is_trading_time_weekend(self):
        """测试周末交易时间"""
        # 周六上午10点
        saturday_10am = datetime(2026, 3, 21, 10, 0)  # 2026-03-21是周六
        assert not is_trading_time(saturday_10am)

        # 周日上午10点
        sunday_10am = datetime(2026, 3, 22, 10, 0)  # 2026-03-22是周日
        assert not is_trading_time(sunday_10am)

    def test_is_in_cooldown(self):
        """测试冷却期检查"""
        last_trade_times = {}

        # 不在冷却期（从未交易）
        assert not is_in_cooldown("test", last_trade_times)

        # 刚刚交易
        trade_time = datetime.now() - timedelta(minutes=1)
        last_trade_times["test"] = trade_time
        assert is_in_cooldown("test", last_trade_times, cooldown_minutes=10)

        # 冷却期已过
        old_trade_time = datetime.now() - timedelta(minutes=15)
        last_trade_times["test2"] = old_trade_time
        assert not is_in_cooldown("test2", last_trade_times, cooldown_minutes=10)

    def test_is_account_in_cooldown(self):
        """测试账户冷却期检查"""
        # 账户从未交易
        assert not is_account_in_cooldown(None)

        # 账户刚刚交易
        recent_trade = datetime.now() - timedelta(minutes=1)
        assert is_account_in_cooldown(recent_trade, account_cooldown_minutes=3)

        # 账户冷却期已过
        old_trade = datetime.now() - timedelta(minutes=5)
        assert not is_account_in_cooldown(old_trade, account_cooldown_minutes=3)

    def test_z_score_extreme_values(self):
        """测试极端价格序列的Z-Score计算"""
        # 大幅上涨序列
        rising_prices = [100.0, 110.0, 121.0, 133.1, 146.41]
        z_score_rising = calculate_z_score(rising_prices)
        # 持续上涨，Z-Score应为正
        assert z_score_rising > 0

        # 大幅下跌序列
        falling_prices = [100.0, 90.0, 81.0, 72.9, 65.61]
        z_score_falling = calculate_z_score(falling_prices)
        # 持续下跌，Z-Score应为负
        assert z_score_falling < 0

        # 波动序列
        volatile_prices = [100.0, 110.0, 90.0, 105.0, 95.0]
        z_score_volatile = calculate_z_score(volatile_prices)
        # 绝对值应较小
        assert abs(z_score_volatile) < 2.0

    def test_ema_alpha_effect(self):
        """测试EMA alpha参数的影响"""
        ema_prices1 = {}
        ema_prices2 = {}
        prices = [100.0, 110.0, 105.0, 115.0, 110.0]

        # 高alpha（0.8） - 对最新价格更敏感
        results_high_alpha = []
        for price in prices:
            result = calculate_ema("test1", price, ema_prices1, ema_alpha=0.8)
            results_high_alpha.append(result)

        # 低alpha（0.2） - 更平滑
        results_low_alpha = []
        for price in prices:
            result = calculate_ema("test2", price, ema_prices2, ema_alpha=0.2)
            results_low_alpha.append(result)

        # 高alpha的结果应该更接近最新价格
        assert abs(results_high_alpha[-1] - prices[-1]) < abs(results_low_alpha[-1] - prices[-1])

if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])