"""
动态滑点和冲击成本模块
用于更严格地校验对冲交易的可行性和成本估计
"""
import math
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from core.logging_config import get_logger

logger = get_logger("dynamic_slippage")


@dataclass
class SlippageEstimate:
    """滑点估计结果"""
    base_slippage: float       # 基础滑点
    spread_cost: float         # 买卖价差成本
    impact_cost: float         # 冲击成本
    liquidity_risk: float      # 流动性风险溢价
    total_slippage: float      # 总滑点估计
    confidence: str            # 置信度: HIGH/MEDIUM/LOW


def estimate_dynamic_slippage(
    symbol: str,
    trade_amount: float,
    current_price: float,
    avg_daily_volume: Optional[float] = None,
    bid_ask_spread: Optional[float] = None,
    price_volatility: Optional[float] = None,
    is_etf: bool = False,
    is_limit_up: bool = False,
    is_limit_down: bool = False,
    base_slippage: float = 0.002
) -> SlippageEstimate:
    """
    估计动态滑点和冲击成本

    Args:
        symbol: 股票代码
        trade_amount: 交易金额
        current_price: 当前价格
        avg_daily_volume: 平均日成交额（可选）
        bid_ask_spread: 买卖价差比例（可选）
        price_volatility: 价格波动率（可选）
        is_etf: 是否为 ETF
        is_limit_up: 是否涨停
        is_limit_down: 是否跌停
        base_slippage: 基础滑点

    Returns:
        SlippageEstimate 对象
    """
    # 1. 基础滑点
    base = base_slippage

    # 2. 买卖价差成本 (默认估计)
    spread = bid_ask_spread if bid_ask_spread else 0.001  # 默认 0.1%

    # 3. 冲击成本 (基于交易量占日均成交额的比例)
    impact = 0.0
    if avg_daily_volume and avg_daily_volume > 0:
        participation_rate = trade_amount / avg_daily_volume
        # 使用平方根法则估计冲击成本
        # impact = σ * sqrt(participation_rate) * 调整因子
        vol = price_volatility if price_volatility else 0.02
        impact = vol * math.sqrt(participation_rate) * 0.5
        impact = min(impact, 0.02)  # 上限 2%

    # 4. 流动性风险溢价
    liquidity_risk = 0.0
    confidence = "HIGH"

    if is_limit_up:
        # 涨停时买入风险极高
        liquidity_risk = 0.05  # 5% 额外风险溢价
        confidence = "LOW"
        logger.warning(f"⚠️ {symbol} 涨停，买入滑点风险极高")

    if is_limit_down:
        # 跌停时卖出风险极高
        liquidity_risk = 0.05  # 5% 额外风险溢价
        confidence = "LOW"
        logger.warning(f"⚠️ {symbol} 跌停，卖出滑点风险极高")

    if is_etf:
        # ETF 流动性通常较好
        spread *= 0.5
        impact *= 0.5
        confidence = "HIGH"

    # 5. 总滑点
    total = base + spread + impact + liquidity_risk

    # 6. 置信度评估
    if avg_daily_volume is None or bid_ask_spread is None:
        confidence = "MEDIUM"

    return SlippageEstimate(
        base_slippage=base,
        spread_cost=spread,
        impact_cost=impact,
        liquidity_risk=liquidity_risk,
        total_slippage=total,
        confidence=confidence
    )


def check_trade_feasibility(
    stock_symbol: str,
    stock_price: float,
    stock_amount: float,
    etf_symbol: str,
    etf_price: float,
    etf_amount: float,
    stock_is_limit_up: bool = False,
    stock_is_limit_down: bool = False,
    etf_is_limit_up: bool = False,
    etf_is_limit_down: bool = False,
    max_acceptable_slippage: float = 0.01
) -> Tuple[bool, str, Dict]:
    """
    检查对冲交易的可行性

    Args:
        stock_symbol: 正股代码
        stock_price: 正股价格
        stock_amount: 正股交易金额
        etf_symbol: ETF代码
        etf_price: ETF价格
        etf_amount: ETF交易金额
        stock_is_limit_up: 正股是否涨停
        stock_is_limit_down: 正股是否跌停
        etf_is_limit_up: ETF是否涨停
        etf_is_limit_down: ETF是否跌停
        max_acceptable_slippage: 最大可接受滑点

    Returns:
        (是否可行, 原因, 详细信息)
    """
    details = {}

    # 1. 检查涨停限制
    if stock_is_limit_up:
        # 正股涨停：可以卖出（如有持仓），但买入困难
        details["stock_status"] = "LIMIT_UP"
        return False, f"正股 {stock_symbol} 涨停，无法买入", details

    if etf_is_limit_up:
        # ETF涨停：做空对冲失败风险
        details["etf_status"] = "LIMIT_UP"
        details["warning"] = "ETF涨停，做空对冲可能失败"
        # 继续评估，但标记风险

    # 2. 检查跌停限制
    if stock_is_limit_down:
        details["stock_status"] = "LIMIT_DOWN"
        details["warning"] = "正股跌停，卖出困难"

    if etf_is_limit_down:
        details["etf_status"] = "LIMIT_DOWN"
        details["warning"] = "ETF跌停，买入对冲困难"

    # 3. 估计滑点
    stock_slip = estimate_dynamic_slippage(
        stock_symbol, stock_amount, stock_price,
        is_etf=False, is_limit_up=stock_is_limit_up, is_limit_down=stock_is_limit_down
    )

    etf_slip = estimate_dynamic_slippage(
        etf_symbol, etf_amount, etf_price,
        is_etf=True, is_limit_up=etf_is_limit_up, is_limit_down=etf_is_limit_down
    )

    details["stock_slippage"] = stock_slip.total_slippage
    details["etf_slippage"] = etf_slip.total_slippage
    details["total_slippage"] = stock_slip.total_slippage + etf_slip.total_slippage
    details["stock_confidence"] = stock_slip.confidence
    details["etf_confidence"] = etf_slip.confidence

    # 4. 判断可行性
    if details["total_slippage"] > max_acceptable_slippage:
        return False, f"总滑点 {details['total_slippage']:.2%} 超过阈值 {max_acceptable_slippage:.2%}", details

    # 5. Legging Risk 警告
    if etf_is_limit_up or etf_is_limit_down or etf_slip.liquidity_risk > 0.02:
        details["legging_risk"] = "HIGH"
        logger.warning(f"⚠️ Legging Risk 高: {stock_symbol}/{etf_symbol}")

    return True, "OK", details


def check_limit_status(current_price: float, prev_close: float,
                        limit_pct: float = 0.1) -> Tuple[bool, bool]:
    """
    检查涨跌停状态

    Args:
        current_price: 当前价格
        prev_close: 昨收价
        limit_pct: 涨跌停幅度 (默认10%)

    Returns:
        (is_limit_up, is_limit_down)
    """
    if prev_close <= 0:
        return False, False

    change_pct = (current_price - prev_close) / prev_close

    is_limit_up = change_pct >= limit_pct - 0.001  # 容忍小误差
    is_limit_down = change_pct <= -limit_pct + 0.001

    return is_limit_up, is_limit_down
