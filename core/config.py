"""
配置管理模块
支持从环境变量、配置文件和默认值加载配置
"""
import os
import json
import yaml
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from pathlib import Path


class ConfigError(Exception):
    """配置错误异常"""
    pass


def load_env(env_file: str = ".env") -> None:
    """从.env文件加载环境变量"""
    env_path = Path(env_file)
    if not env_path.is_absolute():
        env_path = Path(__file__).parent.parent / env_file

    if env_path.exists():
        with open(env_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


@dataclass
class StrategyConfig:
    """策略配置"""
    # 通用策略参数
    z_score_threshold: float = -1.5
    z_score_exit: float = 0.0         # 卖出阈值：情绪回归均值
    trade_ratio: float = 0.3
    momentum_window: int = 20         # 优化: 10 -> 20，增加统计显著性
    ema_alpha: float = 0.15           # 优化: 0.3 -> 0.15，更平滑
    ema_period: int = 20
    stop_loss: float = 0.08           # 优化: 添加固定止损8%
    trailing_stop: float = 0.05       # 新增: 移动止损5%
    use_ema_filter: bool = False
    use_adaptive_threshold: bool = True  # 新增: 启用自适应阈值
    min_signal_confirmations: int = 2    # 新增: 信号确认最小因子数

    # Blue Engine 特有参数
    z_buy_threshold: float = 1.5      # Blue Engine 买入阈值（动量突破）
    z_sell_threshold: float = 0.0     # Blue Engine 卖出阈值（动量衰竭）
    volatility_window: int = 120      # 优化: 60 -> 120，更稳定的波动率估计
    volatility_threshold: float = 0.03 # 低波动过滤阈值（3%）
    short_interest: float = 0.0005    # 做空额外成本（融券/期指升水）
    alert_cooldown: int = 300         # 报警冷却时间（秒）
    beta_min_points: int = 30         # 新增: Beta计算最小数据点
    beta_window: int = 60             # 新增: Beta计算窗口


@dataclass
class RiskConfig:
    """风险配置"""
    cooldown_minutes: int = 10
    account_cooldown_minutes: int = 3
    max_position_per_stock: float = 0.3
    max_total_position: float = 0.9
    daily_loss_limit: float = 0.05
    min_valid_price: float = 1.0
    price_change_limit: float = 0.20


@dataclass
class TransactionCosts:
    """交易成本配置"""
    commission: float = 0.00025  # 0.025%
    stamp_duty: float = 0.001    # 0.1% (仅卖出)
    slippage: float = 0.002      # 0.2%


@dataclass
class MarketHours:
    """交易时间配置"""
    morning_start: tuple = (9, 30)
    morning_end: tuple = (11, 30)
    afternoon_start: tuple = (13, 0)
    afternoon_end: tuple = (14, 57)


@dataclass
class APIConfig:
    """API配置"""
    feishu_webhook: Optional[str] = None
    data_source_url: str = "http://hq.sinajs.cn"
    llm_api_url: str = "https://api.deepseek.com/v1/chat/completions"
    llm_model: str = "deepseek-chat"


@dataclass
class AlphaFactoryConfig:
    """Alpha Factory配置"""
    gray_weight: float = 0.10          # 新策略只给10%仓位
    min_capital_per_trade: float = 10000  # 单笔最小金额
    max_positions: int = 10            # 单策略最多持有10只股票
    max_holding_days: int = 5          # 最大持仓天数（调仓周期）
    commission_rate: float = 0.0003    # 佣金费率（0.03%）
    stamp_duty_rate: float = 0.001     # 印花税税率（0.1%）


@dataclass
class TradingConfig:
    """交易系统完整配置"""
    # 基础配置
    initial_capital: float = 1000000.0
    poll_interval: int = 5  # 秒
    log_level: str = "INFO"

    # 子配置
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    costs: TransactionCosts = field(default_factory=TransactionCosts)
    market_hours: MarketHours = field(default_factory=MarketHours)
    api: APIConfig = field(default_factory=APIConfig)
    alpha_factory: AlphaFactoryConfig = field(default_factory=AlphaFactoryConfig)

    # 动态配置
    symbols: Dict[str, str] = field(default_factory=dict)
    red_engine_allow: bool = True
    blue_engine_allow: bool = True
    global_market_status: str = "NORMAL"

    @classmethod
    def from_env(cls) -> "TradingConfig":
        """从环境变量加载配置"""
        config = cls()

        # 从环境变量覆盖配置
        if feishu_webhook := os.getenv("FEISHU_WEBHOOK"):
            config.api.feishu_webhook = feishu_webhook

        if llm_api_key := os.getenv("DEEPSEEK_API_KEY"):
            # 这里可以存储API密钥，但实际使用时需要安全处理
            pass

        if llm_api_url := os.getenv("LLM_API_URL"):
            config.api.llm_api_url = llm_api_url

        if llm_model := os.getenv("LLM_MODEL"):
            config.api.llm_model = llm_model

        # 策略参数
        if z_threshold := os.getenv("Z_SCORE_THRESHOLD"):
            config.strategy.z_score_threshold = float(z_threshold)

        if trade_ratio := os.getenv("TRADE_RATIO"):
            config.strategy.trade_ratio = float(trade_ratio)

        if poll_interval := os.getenv("POLL_INTERVAL"):
            config.poll_interval = int(poll_interval)

        return config

    @classmethod
    def from_file(cls, filepath: str) -> "TradingConfig":
        """从配置文件加载"""
        filepath = Path(filepath)

        if not filepath.exists():
            raise ConfigError(f"配置文件不存在: {filepath}")

        with open(filepath, 'r', encoding='utf-8') as f:
            if filepath.suffix in ['.yaml', '.yml']:
                config_dict = yaml.safe_load(f)
            else:
                # 默认使用JSON
                config_dict = json.load(f)

        return cls.from_dict(config_dict)

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "TradingConfig":
        """从字典加载配置"""
        # 创建基础配置
        config = cls()

        # 更新基础字段
        for key, value in config_dict.items():
            if hasattr(config, key):
                # 如果是子配置字段，需要特殊处理
                if key in ['strategy', 'risk', 'costs', 'market_hours', 'api', 'alpha_factory']:
                    continue
                setattr(config, key, value)

        # 更新子配置
        if 'strategy' in config_dict:
            for key, value in config_dict['strategy'].items():
                if hasattr(config.strategy, key):
                    setattr(config.strategy, key, value)

        if 'risk' in config_dict:
            for key, value in config_dict['risk'].items():
                if hasattr(config.risk, key):
                    setattr(config.risk, key, value)

        if 'costs' in config_dict:
            for key, value in config_dict['costs'].items():
                if hasattr(config.costs, key):
                    setattr(config.costs, key, value)

        if 'market_hours' in config_dict:
            market_hours = config_dict['market_hours']
            if 'morning_start' in market_hours:
                config.market_hours.morning_start = tuple(market_hours['morning_start'])
            if 'morning_end' in market_hours:
                config.market_hours.morning_end = tuple(market_hours['morning_end'])
            if 'afternoon_start' in market_hours:
                config.market_hours.afternoon_start = tuple(market_hours['afternoon_start'])
            if 'afternoon_end' in market_hours:
                config.market_hours.afternoon_end = tuple(market_hours['afternoon_end'])

        if 'api' in config_dict:
            for key, value in config_dict['api'].items():
                if hasattr(config.api, key):
                    setattr(config.api, key, value)

        if 'alpha_factory' in config_dict:
            for key, value in config_dict['alpha_factory'].items():
                if hasattr(config.alpha_factory, key):
                    setattr(config.alpha_factory, key, value)

        return config

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    def save(self, filepath: str):
        """保存配置到文件"""
        filepath = Path(filepath)

        # 确保目录存在
        filepath.parent.mkdir(parents=True, exist_ok=True)

        config_dict = self.to_dict()

        with open(filepath, 'w', encoding='utf-8') as f:
            if filepath.suffix in ['.yaml', '.yml']:
                yaml.dump(config_dict, f, default_flow_style=False, allow_unicode=True)
            else:
                # 默认使用JSON
                json.dump(config_dict, f, indent=4, ensure_ascii=False)

    def validate(self) -> List[str]:
        """验证配置，返回错误列表"""
        errors = []

        # 验证策略参数
        if self.strategy.z_score_threshold >= 0:
            errors.append("Z-Score阈值必须为负值")

        if not 0 < self.strategy.trade_ratio <= 1:
            errors.append("交易比例必须在0到1之间")

        if self.strategy.momentum_window < 2:
            errors.append("动量窗口必须至少为2")

        if not 0 < self.strategy.ema_alpha <= 1:
            errors.append("EMA alpha必须在0到1之间")

        # 验证风险参数
        if self.risk.cooldown_minutes <= 0:
            errors.append("冷却时间必须大于0")

        if not 0 <= self.risk.max_position_per_stock <= 1:
            errors.append("单股最大仓位必须在0到1之间")

        if not 0 <= self.risk.daily_loss_limit <= 1:
            errors.append("日亏损限制必须在0到1之间")

        # 验证交易成本
        if any(cost < 0 for cost in [self.costs.commission, self.costs.stamp_duty, self.costs.slippage]):
            errors.append("交易成本不能为负")

        # 验证交易时间
        if not (0 <= self.market_hours.morning_start[0] < 24 and
                0 <= self.market_hours.morning_start[1] < 60):
            errors.append("上午开盘时间格式错误")

        if not (0 <= self.market_hours.morning_end[0] < 24 and
                0 <= self.market_hours.morning_end[1] < 60):
            errors.append("上午收盘时间格式错误")

        if self.market_hours.morning_start >= self.market_hours.morning_end:
            errors.append("上午开盘时间必须早于收盘时间")

        return errors

    def is_valid(self) -> bool:
        """检查配置是否有效"""
        return len(self.validate()) == 0


def load_config(config_file: Optional[str] = None) -> TradingConfig:
    """
    加载配置（优先级：环境变量 > 配置文件 > 默认值）

    Args:
        config_file: 配置文件路径，如果为None则尝试默认位置

    Returns:
        配置对象
    """
    # 从环境变量加载基础配置
    config = TradingConfig.from_env()

    # 尝试加载配置文件
    config_files = []

    if config_file:
        config_files.append(config_file)

    # 默认配置文件位置
    config_files.extend([
        "config.yaml",
        "config.yml",
        "config.json",
        "daily_config.json"
    ])

    for filepath in config_files:
        try:
            file_config = TradingConfig.from_file(filepath)
            config = file_config
            break
        except FileNotFoundError:
            continue
        except (json.JSONDecodeError, yaml.YAMLError) as e:
            raise ConfigError(f"配置文件解析失败 {filepath}: {e}")
        except Exception as e:
            continue

    # 验证配置
    if errors := config.validate():
        raise ConfigError(f"配置验证失败: {', '.join(errors)}")

    return config


def load_config_with_fallback(config_file: Optional[str] = None) -> "TradingConfig":
    """
    加载配置，失败时返回默认值

    Args:
        config_file: 配置文件路径，如果为None则尝试默认位置

    Returns:
        配置对象（保证返回有效配置，不抛出异常）
    """
    try:
        return load_config(config_file)
    except ConfigError as e:
        print(f"⚠️ 配置加载失败，使用默认值: {e}")
        return TradingConfig()