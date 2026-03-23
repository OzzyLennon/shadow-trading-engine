"""
日志配置模块
提供结构化日志配置
"""
import logging
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from logging.handlers import RotatingFileHandler


class StructuredFormatter(logging.Formatter):
    """结构化日志格式化器"""

    def __init__(self, fmt=None, datefmt=None, style='%'):
        super().__init__(fmt, datefmt, style)

    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 添加额外字段
        if hasattr(record, 'extra') and isinstance(record.extra, dict):
            log_entry.update(record.extra)

        # 添加异常信息
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # 添加线程/进程信息
        if record.threadName:
            log_entry["thread"] = record.threadName
        if record.processName:
            log_entry["process"] = record.processName

        return json.dumps(log_entry, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """控制台日志格式化器（人类可读）"""

    COLORS = {
        'DEBUG': '\033[36m',      # 青色
        'INFO': '\033[32m',       # 绿色
        'WARNING': '\033[33m',    # 黄色
        'ERROR': '\033[31m',      # 红色
        'CRITICAL': '\033[41m',   # 红色背景
    }
    RESET = '\033[0m'

    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录（带颜色）"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        level = record.levelname
        message = record.getMessage()

        # 添加颜色
        color = self.COLORS.get(level, '')
        level_colored = f"{color}{level:<8}{self.RESET}"

        # 基本格式
        log_line = f"{timestamp} {level_colored} {record.name} - {message}"

        # 添加上下文信息
        if hasattr(record, 'extra') and isinstance(record.extra, dict):
            context_str = " ".join(f"{k}={v}" for k, v in record.extra.items())
            if context_str:
                log_line += f" | {context_str}"

        # 添加异常信息
        if record.exc_info:
            log_line += f"\n{self.formatException(record.exc_info)}"

        return log_line


def setup_logger(
    name: str = "trading_system",
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    max_file_size: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    enable_console: bool = True,
    enable_json: bool = False
) -> logging.Logger:
    """
    设置日志记录器

    Args:
        name: 日志记录器名称
        log_level: 日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）
        log_file: 日志文件路径，如果为None则不记录到文件
        max_file_size: 单个日志文件最大大小（字节）
        backup_count: 备份文件数量
        enable_console: 是否启用控制台输出
        enable_json: 是否启用JSON格式输出（否则使用文本格式）

    Returns:
        配置好的日志记录器
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper()))

    # 移除现有处理器（避免重复）
    logger.handlers.clear()

    # 控制台处理器
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_formatter = ConsoleFormatter()
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    # 文件处理器
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_file_size,
            backupCount=backup_count,
            encoding='utf-8'
        )

        if enable_json:
            formatter = StructuredFormatter()
        else:
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )

        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str = "trading_system") -> logging.Logger:
    """
    获取日志记录器（如果未设置则使用默认设置）

    Args:
        name: 日志记录器名称

    Returns:
        日志记录器
    """
    logger = logging.getLogger(name)

    # 如果还没有处理器，设置默认配置
    if not logger.handlers:
        setup_logger(name)

    return logger


class TradingLogger:
    """交易系统专用日志记录器"""

    def __init__(self, name: str = "trading_system", config: Optional[Dict[str, Any]] = None):
        self.logger = get_logger(name)
        self.config = config or {}

    def log_trade(self, action: str, symbol: str, shares: int,
                  price: float, profit: Optional[float] = None,
                  cash_before: Optional[float] = None, cash_after: Optional[float] = None):
        """记录交易日志"""
        extra = {
            "type": "trade",
            "action": action,
            "symbol": symbol,
            "shares": shares,
            "price": price,
            "profit": profit,
            "cash_before": cash_before,
            "cash_after": cash_after,
        }

        # 移除None值
        extra = {k: v for k, v in extra.items() if v is not None}

        self.logger.info(f"交易: {action} {symbol} {shares}股 @ {price}", extra=extra)

    def log_signal(self, symbol: str, signal_type: str, value: float,
                   threshold: Optional[float] = None, confidence: Optional[float] = None):
        """记录信号日志"""
        extra = {
            "type": "signal",
            "symbol": symbol,
            "signal_type": signal_type,
            "value": value,
            "threshold": threshold,
            "confidence": confidence,
        }

        # 移除None值
        extra = {k: v for k, v in extra.items() if v is not None}

        message = f"信号: {symbol} {signal_type}={value:.3f}"
        if threshold is not None:
            message += f" (阈值={threshold})"

        self.logger.debug(message, extra=extra)

    def log_portfolio_update(self, cash: float, market_value: float,
                             total_assets: float, positions_count: int):
        """记录投资组合更新日志"""
        extra = {
            "type": "portfolio",
            "cash": cash,
            "market_value": market_value,
            "total_assets": total_assets,
            "positions_count": positions_count,
        }

        self.logger.info(
            f"投资组合更新: 现金={cash:.0f}, 市值={market_value:.0f}, "
            f"总资产={total_assets:.0f}, 持仓数={positions_count}",
            extra=extra
        )

    def log_risk_event(self, event_type: str, rule: str, symbol: Optional[str] = None,
                       details: Optional[Dict[str, Any]] = None):
        """记录风险事件日志"""
        extra = {
            "type": "risk",
            "event_type": event_type,
            "rule": rule,
            "symbol": symbol,
            "details": details or {},
        }

        message = f"风险事件: {event_type} - {rule}"
        if symbol:
            message += f" ({symbol})"

        self.logger.warning(message, extra=extra)

    def log_performance(self, metric: str, value: float, period: Optional[str] = None):
        """记录性能指标日志"""
        extra = {
            "type": "performance",
            "metric": metric,
            "value": value,
            "period": period,
        }

        # 移除None值
        extra = {k: v for k, v in extra.items() if v is not None}

        self.logger.info(f"性能: {metric}={value:.4f}", extra=extra)