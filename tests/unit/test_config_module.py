"""
配置模块单元测试
测试core.config模块
"""
import sys
import os
import json
import tempfile
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import (
    TradingConfig, StrategyConfig, RiskConfig,
    TransactionCosts, MarketHours, APIConfig, AlphaFactoryConfig,
    load_config, ConfigError
)


class TestStrategyConfig:
    """策略配置测试"""

    def test_default_values(self):
        """测试默认值"""
        config = StrategyConfig()
        assert config.z_score_threshold == -1.5
        assert config.z_score_exit == 0.0
        assert config.trade_ratio == 0.3
        assert config.momentum_window == 20  # 优化后: 10 -> 20
        assert config.ema_alpha == 0.15  # 优化后: 0.3 -> 0.15
        assert config.ema_period == 20
        assert config.stop_loss == 0.08  # 优化后: 0.10 -> 0.08
        assert config.trailing_stop == 0.05  # 新增
        assert config.use_ema_filter == False
        assert config.use_adaptive_threshold == True  # 新增
        assert config.min_signal_confirmations == 2  # 新增

    def test_custom_values(self):
        """测试自定义值"""
        config = StrategyConfig(
            z_score_threshold=-2.0,
            z_score_exit=0.5,
            trade_ratio=0.5,
            momentum_window=20,
            ema_alpha=0.2,
            ema_period=30,
            stop_loss=0.15,
            use_ema_filter=True
        )

        assert config.z_score_threshold == -2.0
        assert config.z_score_exit == 0.5
        assert config.trade_ratio == 0.5
        assert config.momentum_window == 20
        assert config.ema_alpha == 0.2
        assert config.ema_period == 30
        assert config.stop_loss == 0.15
        assert config.use_ema_filter == True


class TestRiskConfig:
    """风险配置测试"""

    def test_default_values(self):
        """测试默认值"""
        config = RiskConfig()

        assert config.cooldown_minutes == 10
        assert config.account_cooldown_minutes == 3
        assert config.max_position_per_stock == 0.3
        assert config.max_total_position == 0.9
        assert config.daily_loss_limit == 0.05
        assert config.min_valid_price == 1.0
        assert config.price_change_limit == 0.20


class TestTransactionCosts:
    """交易成本配置测试"""

    def test_default_values(self):
        """测试默认值"""
        costs = TransactionCosts()

        assert costs.commission == 0.00025  # 0.025%
        assert costs.stamp_duty == 0.001    # 0.1%
        assert costs.slippage == 0.002     # 0.2%

    def test_calculate_buy_costs(self):
        """测试买入成本计算"""
        costs = TransactionCosts()
        amount = 10000.0

        # 买入总成本：滑点 + 佣金
        expected_cost = amount * (costs.slippage + costs.commission)
        # 净支付：金额 + 成本
        expected_net = amount + expected_cost

        # 实际应用中需要调用相关函数计算
        # 这里只是验证配置值
        assert costs.commission == 0.00025
        assert costs.stamp_duty == 0.001
        assert costs.slippage == 0.002

class TestMarketHours:
    """交易时间配置测试"""

    def test_default_values(self):
        """测试默认值"""
        hours = MarketHours()

        assert hours.morning_start == (9, 30)
        assert hours.morning_end == (11, 30)
        assert hours.afternoon_start == (13, 0)
        assert hours.afternoon_end == (14, 57)

    def test_custom_values(self):
        """测试自定义值"""
        hours = MarketHours(
            morning_start=(9, 0),
            morning_end=(12, 0),
            afternoon_start=(13, 0),
            afternoon_end=(15, 0)
        )

        assert hours.morning_start == (9, 0)
        assert hours.morning_end == (12, 0)
        assert hours.afternoon_start == (13, 0)
        assert hours.afternoon_end == (15, 0)


class TestTradingConfig:
    """交易配置测试"""

    def test_default_values(self):
        """测试默认值"""
        config = TradingConfig()

        assert config.initial_capital == 1000000.0
        assert config.poll_interval == 5
        assert config.log_level == "INFO"
        assert config.red_engine_allow == True
        assert config.blue_engine_allow == True
        assert config.global_market_status == "NORMAL"

        # 子配置检查
        assert isinstance(config.strategy, StrategyConfig)
        assert isinstance(config.risk, RiskConfig)
        assert isinstance(config.costs, TransactionCosts)
        assert isinstance(config.market_hours, MarketHours)
        assert isinstance(config.api, APIConfig)

    def test_from_dict(self):
        """测试从字典创建配置"""
        config_dict = {
            "initial_capital": 2000000.0,
            "poll_interval": 10,
            "log_level": "DEBUG",
            "red_engine_allow": False,
            "blue_engine_allow": False,
            "global_market_status": "RISK_AVERSION",
            "strategy": {
                "z_score_threshold": -2.0,
                "trade_ratio": 0.4,
                "momentum_window": 15,
                "ema_alpha": 0.4,
                "ema_period": 25
            },
            "risk": {
                "cooldown_minutes": 15,
                "account_cooldown_minutes": 5,
                "max_position_per_stock": 0.4,
                "max_total_position": 0.8,
                "daily_loss_limit": 0.03
            }
        }

        config = TradingConfig.from_dict(config_dict)

        assert config.initial_capital == 2000000.0
        assert config.poll_interval == 10
        assert config.log_level == "DEBUG"
        assert config.red_engine_allow == False
        assert config.blue_engine_allow == False
        assert config.global_market_status == "RISK_AVERSION"

        # 检查子配置
        assert config.strategy.z_score_threshold == -2.0
        assert config.strategy.trade_ratio == 0.4
        assert config.strategy.momentum_window == 15
        assert config.risk.cooldown_minutes == 15
        assert config.risk.max_position_per_stock == 0.4

    def test_validate(self):
        """测试配置验证"""
        config = TradingConfig()

        # 正常情况下应该没有错误
        errors = config.validate()
        assert len(errors) == 0

        # 测试无效的Z-Score阈值
        invalid_config = TradingConfig(
            strategy=StrategyConfig(
                z_score_threshold=1.0  # 应该为负值
            )
        )

        errors = invalid_config.validate()
        assert "Z-Score阈值必须为负值" in errors

    def test_validate_ema_alpha(self):
        """测试EMA alpha验证"""
        # 测试无效的EMA alpha
        invalid_config = TradingConfig(
            strategy=StrategyConfig(
                ema_alpha=-0.5  # 应该在0到1之间

            )
        )

        errors = invalid_config.validate()
        assert "EMA alpha必须在0到1之间" in errors

    def test_validate_position_limits(self):
        """测试仓位限制验证"""
        # 测试无效的单股仓位限制
        invalid_config = TradingConfig(
            risk=RiskConfig(
                max_position_per_stock=1.5  # 应该在0到1之间

            )
        )

        errors = invalid_config.validate()
        assert "单股最大仓位必须在0到1之间" in errors

    def test_validate_market_hours(self):
        """测试交易时间验证"""
        # 测试无效的交易时间（开盘晚于收盘）
        invalid_config = TradingConfig(
            market_hours=MarketHours(
                morning_start=(12, 0),
                morning_end=(9, 0)

            )
        )

        errors = invalid_config.validate()
        assert "上午开盘时间必须早于收盘时间" in errors

    def test_to_dict(self):
        """测试转换为字典"""
        config = TradingConfig()
        config_dict = config.to_dict()

        assert isinstance(config_dict, dict)
        assert "initial_capital" in config_dict
        assert "strategy" in config_dict
        assert "risk" in config_dict
        assert "costs" in config_dict

        # 验证子配置存在
        strategy_dict = config_dict.get("strategy", {})
        assert "z_score_threshold" in strategy_dict
        assert "trade_ratio" in strategy_dict

        risk_dict = config_dict.get("risk", {})
        assert "cooldown_minutes" in risk_dict
        assert "max_position_per_stock" in risk_dict

    def test_from_dict_with_alpha_factory(self):
        """测试从字典加载Alpha Factory配置"""
        config_dict = {
            "alpha_factory": {
                "gray_weight": 0.15,
                "min_capital_per_trade": 15000.0,
                "max_positions": 12,
                "max_holding_days": 6,
                "commission_rate": 0.0004,
                "stamp_duty_rate": 0.0009
            }
        }
        config = TradingConfig.from_dict(config_dict)
        assert config.alpha_factory.gray_weight == 0.15
        assert config.alpha_factory.min_capital_per_trade == 15000.0
        assert config.alpha_factory.max_positions == 12
        assert config.alpha_factory.max_holding_days == 6
        assert config.alpha_factory.commission_rate == 0.0004
        assert config.alpha_factory.stamp_duty_rate == 0.0009

    def test_is_valid(self):
        """测试配置有效性检查"""
        config = TradingConfig()
        assert config.is_valid() == True


class TestLoadConfig:
    """测试配置加载"""

    def test_load_default(self):
        """测试加载默认配置"""
        config = load_config()
        assert isinstance(config, TradingConfig)

    def test_load_from_json_file(self, tmp_path):
        """测试从JSON文件加载配置"""
        # 创建JSON配置文件
        config_data = {
            "initial_capital": 1500000.0,
            "poll_interval": 8,
            "log_level": "WARNING",
            "symbols": {
                "sh601088": "中国神华",
                "sh600886": "国投电力"
            },
            "strategy": {
                "z_score_threshold": -1.8,
                "trade_ratio": 0.35
            }
        }

        config_file = tmp_path / "test_config.json"
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config_data, f)

        # 加载配置
        config = load_config(str(config_file))

        # 验证配置值
        assert config.initial_capital == 1500000.0
        assert config.poll_interval == 8
        assert config.log_level == "WARNING"
        assert config.symbols["sh601088"] == "中国神华"
        assert config.symbols["sh600886"] == "国投电力"
        assert config.strategy.z_score_threshold == -1.8
        assert config.strategy.trade_ratio == 0.35

    def test_load_from_yaml_file(self, tmp_path):
        """测试从YAML文件加载配置"""
        try:
            import yaml

            # 创建YAML配置文件
            config_data = {
                "initial_capital": 1800000.0,
                "poll_interval": 12,
                "log_level": "ERROR",
                "symbols": {
                    "sh601088": "中国神华",
                    "sh600886": "国投电力"
                },
                "strategy": {
                    "z_score_threshold": -1.6,
                    "trade_ratio": 0.25
                }
            }

            config_file = tmp_path / "test_config.yaml"
            with open(config_file, 'w', encoding='utf-8') as f:
                yaml.dump(config_data, f)

            # 加载配置
            config = load_config(str(config_file))

            # 验证配置值
            assert config.initial_capital == 1800000.0
            assert config.poll_interval == 12
            assert config.log_level == "ERROR"
        except ImportError:
            # 跳过测试，如果没有安装yaml
            pass

    def test_load_invalid_config_file(self, tmp_path):
        """测试加载无效配置文件"""
        # 创建无效的JSON文件
        config_file = tmp_path / "invalid.json"
        with open(config_file, 'w', encoding='utf-8') as f:
            f.write("{ invalid json }")

        try:
            load_config(str(config_file))
            assert False, "应该抛出异常"
        except ConfigError:
            # 期望的行为
            pass

    def test_env_override(self, monkeypatch):
        """测试环境变量覆盖配置"""
        # 设置环境变量
        monkeypatch.setenv("FEISHU_WEBHOOK", "https://test-webhook.com")
        monkeypatch.setenv("Z_SCORE_THRESHOLD", "-2.2")

        # 测试from_env方法
        config = TradingConfig.from_env()

        # 环境变量应该覆盖默认值
        assert config.api.feishu_webhook == "https://test-webhook.com"
        assert config.strategy.z_score_threshold == -2.2

        # 测试load_config函数（需要确保没有配置文件干扰）
        # 使用一个不存在的配置文件路径，确保只使用环境变量
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建一个空目录，确保没有配置文件
            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                config2 = load_config()
                # 在空目录中，load_config应该使用环境变量
                assert config2.api.feishu_webhook == "https://test-webhook.com"
                assert config2.strategy.z_score_threshold == -2.2
            finally:
                os.chdir(old_cwd)

class TestAlphaFactoryConfig:
    """Alpha Factory配置测试"""

    def test_default_values(self):
        """测试默认值"""
        config = AlphaFactoryConfig()
        assert config.gray_weight == 0.10
        assert config.min_capital_per_trade == 10000.0
        assert config.max_positions == 10
        assert config.max_holding_days == 5
        assert config.commission_rate == 0.0003
        assert config.stamp_duty_rate == 0.001

    def test_custom_values(self):
        """测试自定义值"""
        config = AlphaFactoryConfig(
            gray_weight=0.20,
            min_capital_per_trade=20000.0,
            max_positions=15,
            max_holding_days=7,
            commission_rate=0.0005,
            stamp_duty_rate=0.0008
        )
        assert config.gray_weight == 0.20
        assert config.min_capital_per_trade == 20000.0
        assert config.max_positions == 15
        assert config.max_holding_days == 7
        assert config.commission_rate == 0.0005
        assert config.stamp_duty_rate == 0.0008

    def test_in_trading_config(self):
        """测试在TradingConfig中的集成"""
        trading_config = TradingConfig()
        assert isinstance(trading_config.alpha_factory, AlphaFactoryConfig)
        assert trading_config.alpha_factory.gray_weight == 0.10


class TestConfigError:
    """配置错误测试"""

    def test_exception_message(self):
        """测试异常消息"""
        error_msg = "配置文件格式错误"
        error = ConfigError(error_msg)

        assert str(error) == error_msg

if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])