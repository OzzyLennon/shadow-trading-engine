"""
核心模块单元测试
测试core模块中的函数
"""
import sys
import os
import math
from datetime import datetime, timedelta

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import functions


class TestCoreFunctions:
    """核心函数测试类"""

    def test_calculate_z_score_basic(self):
        """测试Z-Score基本计算"""
        # 测试正常价格序列
        prices = [100.0, 101.0, 99.0, 98.5, 97.0, 96.0, 95.5, 94.0, 93.5, 92.0]
        z_score = functions.calculate_z_score(prices)
        # Z-Score应为负值（价格下跌）
        assert z_score < 0
        # 验证计算合理性
        assert -10 < z_score < 10

    def test_calculate_z_score_edge_cases(self):
        """测试Z-Score边界情况"""
        # 数据点不足
        assert functions.calculate_z_score([100.0]) == 0.0
        assert functions.calculate_z_score([100.0, 101.0]) == 0.0

        # 价格不变
        constant_prices = [100.0, 100.0, 100.0, 100.0]
        z_score = functions.calculate_z_score(constant_prices)
        assert abs(z_score) < 0.0001

        # 大幅上涨（但收益率恒定，Z-Score应接近0）
        rising_prices = [100.0, 110.0, 121.0, 133.1]
        z_score = functions.calculate_z_score(rising_prices)
        # 由于收益率接近恒定，Z-Score应接近0
        assert abs(z_score) < 0.1

        # 大幅下跌（但收益率恒定，Z-Score应接近0）
        falling_prices = [100.0, 90.0, 81.0, 72.9]
        z_score = functions.calculate_z_score(falling_prices)
        # 由于收益率接近恒定，Z-Score应接近0
        assert abs(z_score) < 0.1

        # 测试加速上涨（收益率递增）
        accelerating_prices = [100.0, 105.0, 115.0, 130.0]  # 收益率: 5%, 9.5%, 13%
        z_score = functions.calculate_z_score(accelerating_prices)
        # 当前收益率高于历史均值，Z-Score应为正
        assert z_score > 0

        # 测试减速下跌（收益率递减）
        decelerating_prices = [100.0, 90.0, 83.0, 79.0]  # 收益率: -10%, -7.8%, -4.8%
        z_score = functions.calculate_z_score(decelerating_prices)
        # 当前亏损小于历史平均亏损，Z-Score应为正（负得少）
        # 实际上：收益率从-10%到-4.8%，在改善，所以Z-Score应为正
        assert z_score > 0

    def test_calculate_ema(self):
        """测试EMA计算"""
        # 首次计算
        ema1 = functions.calculate_ema(100.0, None, alpha=0.5)
        assert ema1 == 100.0

        # 第二次计算
        ema2 = functions.calculate_ema(110.0, ema1, alpha=0.5)
        assert abs(ema2 - 105.0) < 0.001  # 0.5*110 + 0.5*100 = 105

        # 第三次计算
        ema3 = functions.calculate_ema(105.0, ema2, alpha=0.5)
        assert abs(ema3 - 105.0) < 0.001  # 0.5*105 + 0.5*105 = 105

        # 测试不同alpha值
        ema_low_alpha = functions.calculate_ema(110.0, 100.0, alpha=0.1)
        assert abs(ema_low_alpha - 101.0) < 0.001  # 0.1*110 + 0.9*100 = 101

    def test_is_valid_price(self):
        """测试价格有效性检查"""
        # 有效价格
        valid, msg = functions.is_valid_price(100.0, None)
        assert valid
        assert msg is None

        # 价格过低
        valid, msg = functions.is_valid_price(0.5, None, min_valid_price=1.0)
        assert not valid
        assert "低于最小有效价格" in msg

        # 价格为0
        valid, msg = functions.is_valid_price(0.0, None)
        assert not valid
        assert "价格必须大于0" in msg

        # 负价格
        valid, msg = functions.is_valid_price(-10.0, None)
        assert not valid
        assert "价格必须大于0" in msg

        # 正常变化
        valid, msg = functions.is_valid_price(110.0, 100.0, price_change_limit=0.20)
        assert valid
        assert msg is None

        # 变化过大
        valid, msg = functions.is_valid_price(130.0, 100.0, price_change_limit=0.20)
        assert not valid
        assert "价格变化超过限制" in msg

        # 负向变化过大
        valid, msg = functions.is_valid_price(70.0, 100.0, price_change_limit=0.20)
        assert not valid
        assert "价格变化超过限制" in msg

        # 边界情况：刚好20%变化
        valid, msg = functions.is_valid_price(120.0, 100.0, price_change_limit=0.20)
        assert valid
        assert msg is None

    def test_is_trading_time(self):
        """测试交易时间检查"""
        # 周一上午10点（交易时间）
        monday_10am = datetime(2026, 3, 23, 10, 0)  # 2026-03-23是周一
        assert functions.is_trading_time(monday_10am)

        # 周一下午14点（交易时间）
        monday_2pm = datetime(2026, 3, 23, 14, 0)
        assert functions.is_trading_time(monday_2pm)

        # 周一上午9点（非交易时间）
        monday_9am = datetime(2026, 3, 23, 9, 0)
        assert not functions.is_trading_time(monday_9am)

        # 周一下午15点（非交易时间）
        monday_3pm = datetime(2026, 3, 23, 15, 0)
        assert not functions.is_trading_time(monday_3pm)

        # 周六上午10点（周末）
        saturday_10am = datetime(2026, 3, 21, 10, 0)  # 2026-03-21是周六
        assert not functions.is_trading_time(saturday_10am)

        # 自定义交易时间
        custom_time = datetime(2026, 3, 23, 10, 30)
        assert functions.is_trading_time(
            custom_time,
            morning_start=(9, 0),
            morning_end=(12, 0),
            afternoon_start=(13, 0),
            afternoon_end=(15, 0)
        )

    def test_is_in_cooldown(self):
        """测试冷却期检查"""
        last_trade_times = {}
        symbol = "test_symbol"

        # 不在冷却期（从未交易）
        assert not functions.is_in_cooldown(symbol, last_trade_times)

        # 刚刚交易（在冷却期内）
        trade_time = datetime.now() - timedelta(minutes=1)
        last_trade_times[symbol] = trade_time
        assert functions.is_in_cooldown(symbol, last_trade_times, cooldown_minutes=10)

        # 冷却期已过
        old_trade_time = datetime.now() - timedelta(minutes=15)
        last_trade_times["old_symbol"] = old_trade_time
        assert not functions.is_in_cooldown("old_symbol", last_trade_times, cooldown_minutes=10)

    def test_is_account_in_cooldown(self):
        """测试账户冷却期检查"""
        # 账户从未交易
        assert not functions.is_account_in_cooldown(None)

        # 账户刚刚交易（在冷却期内）
        recent_trade = datetime.now() - timedelta(minutes=1)
        assert functions.is_account_in_cooldown(recent_trade, account_cooldown_minutes=3)

        # 账户冷却期已过
        old_trade = datetime.now() - timedelta(minutes=5)
        assert not functions.is_account_in_cooldown(old_trade, account_cooldown_minutes=3)

    def test_calculate_trade_amount(self):
        """测试交易金额计算"""
        # 正常情况
        cash = 100000.0
        trade_amount = functions.calculate_trade_amount(cash, trade_ratio=0.3)
        assert abs(trade_amount - 30000.0) < 0.001

        # 达到最小交易金额
        cash = 20000.0
        trade_amount = functions.calculate_trade_amount(cash, trade_ratio=0.3, min_trade_amount=10000.0)
        assert trade_amount == 0.0  # 6000 < 10000，现金不足，不交易

        # 现金不足
        cash = 5000.0
        trade_amount = functions.calculate_trade_amount(cash, trade_ratio=0.3, min_trade_amount=10000.0)
        assert trade_amount == 0.0

        # 零现金
        trade_amount = functions.calculate_trade_amount(0.0, trade_ratio=0.3)
        assert trade_amount == 0.0

    def test_calculate_shares(self):
        """测试股数计算"""
        # 正常情况
        trade_amount = 10000.0
        price = 50.0
        shares = functions.calculate_shares(trade_amount, price, lot_size=100)
        # 10000 / 50 = 200股，刚好是整手
        assert shares == 200

        # 不是整手的情况（向下取整）
        trade_amount = 15000.0
        price = 50.0
        shares = functions.calculate_shares(trade_amount, price, lot_size=100)
        # 15000 / 50 = 300股，刚好是整手
        assert shares == 300

        # 价格过高，不够一手
        trade_amount = 5000.0
        price = 200.0
        shares = functions.calculate_shares(trade_amount, price, lot_size=100)
        # 5000 / 200 = 25股，不够一手，返回0
        assert shares == 0

        # 价格为0
        shares = functions.calculate_shares(10000.0, 0.0, lot_size=100)
        assert shares == 0

        # 负价格
        shares = functions.calculate_shares(10000.0, -10.0, lot_size=100)
        assert shares == 0

    def test_calculate_trade_costs(self):
        """测试交易成本计算"""
        amount = 10000.0

        # 买入成本
        total_cost, net_amount = functions.calculate_trade_costs(
            amount, is_buy=True,
            commission=0.00025,  # 0.025%
            stamp_duty=0.001,    # 0.1%
            slippage=0.002       # 0.2%
        )

        # 计算预期成本：
        # 滑点: 10000 * 0.002 = 20
        # 佣金: 10000 * 0.00025 = 2.5
        # 印花税: 0（买入无印花税）
        # 总成本: 22.5
        # 净金额: 10000 + 22.5 = 10022.5
        expected_cost = 22.5
        expected_net = 10022.5

        assert abs(total_cost - expected_cost) < 0.01
        assert abs(net_amount - expected_net) < 0.01

        # 卖出成本
        total_cost, net_amount = functions.calculate_trade_costs(
            amount, is_buy=False,
            commission=0.00025,
            stamp_duty=0.001,
            slippage=0.002
        )

        # 计算预期成本：
        # 滑点: 10000 * 0.002 = 20
        # 佣金: 10000 * 0.00025 = 2.5
        # 印花税: 10000 * 0.001 = 10
        # 总成本: 32.5
        # 净金额: 10000 - 32.5 = 9967.5
        expected_cost = 32.5
        expected_net = 9967.5

        assert abs(total_cost - expected_cost) < 0.01
        assert abs(net_amount - expected_net) < 0.01

        # 测试零金额
        total_cost, net_amount = functions.calculate_trade_costs(0.0, is_buy=True)
        assert total_cost == 0.0
        assert net_amount == 0.0

    def test_z_score_with_single_return(self):
        """测试只有一个收益率时的Z-Score计算"""
        # 只有两个价格点，只能计算一个收益率
        prices = [100.0, 101.0]
        z_score = functions.calculate_z_score(prices)
        # 当只有1个收益率时，方差为0，应返回0.0
        assert z_score == 0.0

    def test_z_score_with_zero_variance(self):
        """测试零方差时的Z-Score计算"""
        # 测试真正的零方差情况：所有价格相同
        prices = [100.0, 100.0, 100.0, 100.0, 100.0]
        z_score = functions.calculate_z_score(prices)
        # 所有价格相同时，Z-Score应为0.0
        assert abs(z_score) < 0.0001

        # 测试近似零方差情况：使用更严格的条件
        # 对于几乎恒定的收益率，Z-Score应该很小
        # 这里使用一个真正恒定的收益率序列（通过计算得到）
        # 创建价格序列，使每个收益率恰好为0.01
        base_price = 100.0
        prices = [base_price]
        for i in range(4):
            prices.append(prices[-1] * 1.01)  # 每次精确涨1%
        z_score = functions.calculate_z_score(prices)
        # 由于是精确的1%增长，方差应该为0（或非常接近0）
        assert abs(z_score) < 0.0001

    def test_ema_with_extreme_alpha(self):
        """测试极端alpha值的EMA计算"""
        # alpha = 0（完全使用历史值）
        ema = functions.calculate_ema(110.0, 100.0, alpha=0.0)
        assert ema == 100.0

        # alpha = 1（完全使用当前值）
        ema = functions.calculate_ema(110.0, 100.0, alpha=1.0)
        assert ema == 110.0

    def test_trade_costs_with_zero_rates(self):
        """测试零费率时的交易成本"""
        amount = 10000.0

        # 所有费率为0
        total_cost, net_amount = functions.calculate_trade_costs(
            amount, is_buy=True,
            commission=0.0,
            stamp_duty=0.0,
            slippage=0.0
        )

        assert total_cost == 0.0
        assert net_amount == amount  # 买入：金额不变

        # 卖出
        total_cost, net_amount = functions.calculate_trade_costs(
            amount, is_buy=False,
            commission=0.0,
            stamp_duty=0.0,
            slippage=0.0
        )

        assert total_cost == 0.0
        assert net_amount == amount  # 卖出：金额不变

if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])