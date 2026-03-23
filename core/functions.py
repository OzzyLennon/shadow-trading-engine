"""
核心计算函数
提供量化交易系统的核心计算功能
"""
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple


def calculate_z_score(prices: List[float]) -> float:
    """
    计算价格序列的Z-Score

    Z-Score衡量当前收益率相对于历史收益率的偏离程度
    公式: Z = (r_t - μ) / σ

    Args:
        prices: 价格序列，至少需要2个数据点

    Returns:
        Z-Score值，数据不足时返回0.0
    """
    if len(prices) < 2:
        return 0.0

    # 计算收益率序列
    returns = [(prices[i] - prices[i-1]) / prices[i-1]
               for i in range(1, len(prices))]

    if len(returns) < 2:
        return 0.0

    n = len(returns)
    mu = sum(returns) / n
    variance = sum((r - mu) ** 2 for r in returns) / (n - 1)

    # 如果方差非常小（接近0），返回0.0
    if variance < 1e-10:
        return 0.0

    sigma = math.sqrt(variance)
    r_t = returns[-1]
    return (r_t - mu) / sigma


def calculate_ema(price: float, previous_ema: Optional[float],
                  alpha: float = 0.3) -> float:
    """
    计算指数移动平均（EMA）

    EMA公式: EMA_t = α * Price_t + (1 - α) * EMA_{t-1}

    Args:
        price: 当前价格
        previous_ema: 上一个EMA值，如果为None则使用当前价格
        alpha: 平滑系数，范围(0, 1]，默认0.3

    Returns:
        当前EMA值
    """
    if previous_ema is None:
        return price
    return alpha * price + (1 - alpha) * previous_ema


def is_valid_price(current_price: float, previous_price: Optional[float],
                   min_valid_price: float = 1.0,
                   price_change_limit: float = 0.20) -> Tuple[bool, Optional[str]]:
    """
    检查价格有效性

    Args:
        current_price: 当前价格
        previous_price: 上一个有效价格，如果为None则只检查最小值
        min_valid_price: 最小有效价格，默认1.0
        price_change_limit: 价格变化限制（百分比），默认0.20（20%）

    Returns:
        (是否有效, 错误信息)
    """
    if current_price <= 0:
        return False, "价格必须大于0"

    if current_price < min_valid_price:
        return False, f"价格低于最小有效价格 {min_valid_price}"

    if previous_price is not None and previous_price > 0:
        change_pct = abs(current_price - previous_price) / previous_price
        if change_pct > price_change_limit:
            return False, f"价格变化超过限制: {change_pct:.1%} > {price_change_limit:.1%}"

    return True, None


def is_trading_time(check_time: Optional[datetime] = None,
                    morning_start: Tuple[int, int] = (9, 30),
                    morning_end: Tuple[int, int] = (11, 30),
                    afternoon_start: Tuple[int, int] = (13, 0),
                    afternoon_end: Tuple[int, int] = (14, 57)) -> bool:
    """
    检查是否为A股交易时间

    Args:
        check_time: 检查时间，默认为当前时间
        morning_start: 上午开盘时间
        morning_end: 上午收盘时间
        afternoon_start: 下午开盘时间
        afternoon_end: 下午收盘时间

    Returns:
        是否为交易时间
    """
    if check_time is None:
        check_time = datetime.now()

    # 周末非交易时间
    if check_time.weekday() >= 5:
        return False

    current_time = (check_time.hour, check_time.minute)

    # 上午交易时段
    if morning_start <= current_time < morning_end:
        return True

    # 下午交易时段
    if afternoon_start <= current_time < afternoon_end:
        return True

    return False


def is_in_cooldown(symbol: str, last_trade_times: Dict[str, datetime],
                   cooldown_minutes: int = 10) -> bool:
    """
    检查股票是否在冷却期内

    Args:
        symbol: 股票代码
        last_trade_times: 上次交易时间字典
        cooldown_minutes: 冷却时间（分钟）

    Returns:
        是否在冷却期内
    """
    if symbol not in last_trade_times:
        return False

    time_since_last_trade = datetime.now() - last_trade_times[symbol]
    return time_since_last_trade < timedelta(minutes=cooldown_minutes)


def is_account_in_cooldown(last_account_trade: Optional[datetime],
                           account_cooldown_minutes: int = 3) -> bool:
    """
    检查账户是否在冷却期内

    Args:
        last_account_trade: 账户上次交易时间
        account_cooldown_minutes: 账户冷却时间（分钟）

    Returns:
        账户是否在冷却期内
    """
    if last_account_trade is None:
        return False

    time_since_last_trade = datetime.now() - last_account_trade
    return time_since_last_trade < timedelta(minutes=account_cooldown_minutes)


def calculate_trade_amount(cash: float, trade_ratio: float = 0.3,
                          min_trade_amount: float = 10000.0) -> float:
    """
    计算交易金额

    Args:
        cash: 可用现金
        trade_ratio: 交易比例，默认0.3（30%）
        min_trade_amount: 最小交易金额，默认10000元

    Returns:
        交易金额，如果现金不足最小交易金额则返回0.0
    """
    if cash <= 0:
        return 0.0

    trade_amount = cash * trade_ratio

    # 如果计算出的交易金额小于最小交易金额，则返回0
    if trade_amount < min_trade_amount:
        return 0.0

    return trade_amount


def calculate_shares(trade_amount: float, price: float,
                    lot_size: int = 100) -> int:
    """
    计算可交易股数（整手）

    Args:
        trade_amount: 交易金额
        price: 股票价格
        lot_size: 手大小（A股为100股）

    Returns:
        可交易股数（整手）
    """
    if price <= 0:
        return 0

    raw_shares = trade_amount / price
    # 向下取整到最近的整手
    shares = int(raw_shares // lot_size) * lot_size
    return shares


def calculate_trade_costs(amount: float, is_buy: bool,
                         commission: float = 0.00025,
                         stamp_duty: float = 0.001,
                         slippage: float = 0.002) -> Tuple[float, float]:
    """
    计算交易成本

    Args:
        amount: 交易金额
        is_buy: 是否为买入交易
        commission: 佣金比例，默认0.025%
        stamp_duty: 印花税比例（仅卖出），默认0.1%
        slippage: 滑点成本比例，默认0.2%

    Returns:
        (总成本, 净金额)
    """
    # 滑点成本
    slippage_cost = amount * slippage

    # 佣金
    commission_cost = amount * commission

    # 印花税（仅卖出）
    stamp_duty_cost = 0.0
    if not is_buy:
        stamp_duty_cost = amount * stamp_duty

    total_cost = slippage_cost + commission_cost + stamp_duty_cost

    if is_buy:
        # 买入：支付金额 + 成本
        net_amount = amount + total_cost
    else:
        # 卖出：收到金额 - 成本
        net_amount = amount - total_cost

    return total_cost, net_amount


# ==================== 优化后的计算函数 ====================

def calculate_z_score_improved(prices: List[float], window: int = 20) -> float:
    """
    改进的Z-Score计算 - 基于价格偏离度

    相比基于收益率的Z-Score，这种方法：
    1. 减少收益率计算的噪声放大
    2. 更直观地反映价格偏离程度
    3. 短期数据更稳定

    Args:
        prices: 价格序列
        window: 计算窗口，默认20

    Returns:
        Z-Score值，数据不足时返回0.0
    """
    if len(prices) < window:
        return 0.0

    recent_prices = prices[-window:]
    mean_price = sum(recent_prices) / len(recent_prices)

    # 计算标准差
    variance = sum((p - mean_price) ** 2 for p in recent_prices) / len(recent_prices)
    if variance < 1e-10:
        return 0.0

    std_price = math.sqrt(variance)

    # 当前价格偏离均值的标准化程度
    return (prices[-1] - mean_price) / std_price


def calculate_volatility(prices: List[float], annualize: bool = False) -> float:
    """
    计算价格序列的波动率

    Args:
        prices: 价格序列
        annualize: 是否年化，默认False

    Returns:
        波动率（收益率标准差）
    """
    if len(prices) < 2:
        return 0.0

    # 计算收益率
    returns = [(prices[i] - prices[i-1]) / prices[i-1]
               for i in range(1, len(prices))]

    if len(returns) < 2:
        return 0.0

    # 计算标准差
    mean_ret = sum(returns) / len(returns)
    variance = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
    volatility = math.sqrt(variance) if variance > 0 else 0.0

    # 年化（假设为日数据，252个交易日）
    if annualize:
        volatility *= math.sqrt(252)

    return volatility


def adaptive_z_threshold(prices: List[float], base_threshold: float = -1.5,
                         lookback: int = 20) -> float:
    """
    根据市场波动率自适应调整Z-Score阈值

    高波动时收紧阈值（更保守，需要更大偏离才触发）
    低波动时放宽阈值（更积极，捕捉小幅偏离机会）

    注意：base_threshold应为负值（如-1.5）

    Args:
        prices: 价格序列
        base_threshold: 基础阈值（负值）
        lookback: 波动率计算回看期

    Returns:
        调整后的阈值
    """
    if len(prices) < lookback:
        return base_threshold

    # 计算历史波动率
    volatility = calculate_volatility(prices[-lookback:])

    # 对于负阈值（如-1.5）：
    # 高波动时收紧（绝对值变大）：-1.5 -> -1.8（需要更大偏离）
    # 低波动时放宽（绝对值变小）：-1.5 -> -1.2（更敏感）
    if volatility > 0.02:
        return base_threshold * 1.2  # -1.5 * 1.2 = -1.8（更严格）
    elif volatility < 0.01:
        return base_threshold * 0.8  # -1.5 * 0.8 = -1.2（更宽松）
    else:
        # 线性插值
        ratio = 0.8 + 0.4 * (volatility - 0.01) / 0.01
        return base_threshold * ratio


def check_stop_loss(position: Dict[str, any], current_price: float,
                    max_loss: float = 0.08, trailing_stop: float = 0.05) -> Tuple[bool, Optional[str]]:
    """
    检查止损条件

    Args:
        position: 持仓信息字典，包含 cost, peak_price 等
        current_price: 当前价格
        max_loss: 最大亏损比例，默认8%
        trailing_stop: 移动止损回撤比例，默认5%

    Returns:
        (是否触发止损, 止损原因)
    """
    cost = position.get("cost", current_price)
    peak = position.get("peak_price", cost)

    # 固定止损：亏损超过阈值
    loss_pct = (current_price - cost) / cost
    if loss_pct < -max_loss:
        return True, f"固定止损: 亏损{abs(loss_pct)*100:.1f}% > {max_loss*100:.0f}%"

    # 移动止损：从峰值回撤超过阈值（仅在盈利时生效）
    if peak > cost:
        drawdown = (peak - current_price) / peak
        if drawdown > trailing_stop:
            return True, f"移动止损: 回撤{drawdown*100:.1f}% > {trailing_stop*100:.0f}%"

    return False, None


def confirm_buy_signal(z_score: float, volume_ratio: float = 1.0,
                       price_vs_ema: float = 0.0,
                       rsi: Optional[float] = None,
                       min_confirmations: int = 2) -> Tuple[bool, Dict[str, bool]]:
    """
    多因子买入信号确认

    通过多个因子交叉验证，减少假信号触发

    Args:
        z_score: Z-Score值
        volume_ratio: 成交量比率（当前/平均），>1.2表示放量
        price_vs_ema: 价格相对EMA偏离度，<-0.02表示低于均线2%
        rsi: RSI指标（可选），<30表示超卖
        min_confirmations: 最少需要的确认因子数

    Returns:
        (是否确认, 各因子确认状态)
    """
    confirmations = {
        "z_score": z_score < -1.5,
        "volume": volume_ratio > 1.2,
        "price_below_ema": price_vs_ema < -0.02,
        "rsi_oversold": rsi is not None and rsi < 30
    }

    # 统计确认因子数量
    confirmed_count = sum(1 for v in confirmations.values() if v)

    return confirmed_count >= min_confirmations, confirmations


def confirm_sell_signal(z_score: float, momentum_exhausted: bool = False,
                        price_above_ema: bool = False,
                        profit_ratio: float = 0.0,
                        min_confirmations: int = 1) -> Tuple[bool, Dict[str, bool]]:
    """
    多因子卖出信号确认

    Args:
        z_score: Z-Score值
        momentum_exhausted: 动量是否衰竭（Z从正转负）
        price_above_ema: 价格是否站上均线
        profit_ratio: 当前盈亏比例
        min_confirmations: 最少需要的确认因子数

    Returns:
        (是否确认, 各因子确认状态)
    """
    confirmations = {
        "z_score_normal": z_score > 0,
        "momentum_exhausted": momentum_exhausted,
        "price_above_ema": price_above_ema,
        "profit_target": profit_ratio > 0.05  # 盈利超过5%
    }

    confirmed_count = sum(1 for v in confirmations.values() if v)

    return confirmed_count >= min_confirmations, confirmations


def calculate_beta_robust(stock_returns: List[float], bench_returns: List[float],
                          min_points: int = 30) -> float:
    """
    稳健Beta计算

    使用滚动窗口计算多个Beta值，返回中位数以减少极端值影响

    Args:
        stock_returns: 股票收益率序列
        bench_returns: 基准收益率序列
        min_points: 最小数据点数

    Returns:
        稳健Beta值
    """
    min_len = min(len(stock_returns), len(bench_returns))
    if min_len < min_points:
        return 1.0

    # 使用最近的数据
    window_size = min(60, min_len)
    betas = []

    for i in range(window_size, min_len):
        s = stock_returns[i-window_size:i]
        b = bench_returns[i-window_size:i]

        mean_s = sum(s) / len(s)
        mean_b = sum(b) / len(b)

        # 协方差
        cov = sum((s[j] - mean_s) * (b[j] - mean_b) for j in range(len(s))) / (len(s) - 1)
        # 基准方差
        var_b = sum((x - mean_b) ** 2 for x in b) / (len(b) - 1)

        if var_b > 1e-10:
            beta = cov / var_b
            # 限制极端值
            beta = max(-1.0, min(beta, 3.0))
            betas.append(beta)

    if not betas:
        return 1.0

    # 返回中位数Beta
    betas.sort()
    return betas[len(betas) // 2]


def calculate_dynamic_beta_improved(stock_prices: List[float], bench_prices: List[float],
                                    window: int = 60) -> float:
    """
    改进的动态Beta计算

    相比原版：
    1. 增加最小数据点要求
    2. 使用稳健估计方法
    3. 限制范围更合理

    Args:
        stock_prices: 股票价格序列
        bench_prices: 基准价格序列
        window: 计算窗口

    Returns:
        动态Beta值
    """
    min_len = min(len(stock_prices), len(bench_prices))
    if min_len < window:
        return 1.0

    # 计算收益率
    stock_returns = [(stock_prices[i] - stock_prices[i-1]) / stock_prices[i-1]
                     for i in range(min_len - window, min_len)]
    bench_returns = [(bench_prices[i] - bench_prices[i-1]) / bench_prices[i-1]
                     for i in range(min_len - window, min_len)]

    # 使用稳健计算
    beta = calculate_beta_robust(stock_returns, bench_returns, min_points=window // 2)

    # 限制范围（更合理的限制）
    return max(0.3, min(beta, 2.5))


def calculate_rsi(prices: List[float], period: int = 14) -> float:
    """
    计算RSI指标

    Args:
        prices: 价格序列
        period: RSI周期，默认14

    Returns:
        RSI值（0-100）
    """
    if len(prices) < period + 1:
        return 50.0  # 数据不足返回中性值

    # 计算价格变化
    changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]

    # 分离上涨和下跌
    gains = [max(0, c) for c in changes[-period:]]
    losses = [abs(min(0, c)) for c in changes[-period:]]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss < 1e-10:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi


def calculate_atr(prices: List[Tuple[float, float, float]], period: int = 14) -> float:
    """
    计算ATR（平均真实波幅）

    Args:
        prices: 价格序列，每个元素为
        period: ATR周期，默认14

    Returns:
        ATR值
    """
    if len(prices) < period + 1:
        return 0.0

    true_ranges = []
    for i in range(1, len(prices)):
        high, low, close = prices[i]
        prev_close = prices[i-1][2]

        # 真实波幅
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        true_ranges.append(tr)

    # 计算平均值
    if len(true_ranges) < period:
        return sum(true_ranges) / len(true_ranges) if true_ranges else 0.0

    return sum(true_ranges[-period:]) / period