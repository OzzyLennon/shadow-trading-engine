"""
错误处理模块
定义量化交易系统的异常类和错误处理工具
"""
import logging
import traceback
from typing import Optional, Dict, Any, Type
from datetime import datetime


class TradingSystemError(Exception):
    """交易系统基础异常"""
    def __init__(self, message: str, error_code: Optional[str] = None,
                 details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        self.timestamp = datetime.now()
        self.traceback = traceback.format_exc()

    def __str__(self) -> str:
        if self.error_code:
            return f"[{self.error_code}] {self.message}"
        return self.message

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典，便于日志记录"""
        return {
            "error_type": self.__class__.__name__,
            "error_code": self.error_code,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
            "traceback": self.traceback
        }


class DataSourceError(TradingSystemError):
    """数据源异常"""
    def __init__(self, message: str, source: Optional[str] = None,
                 url: Optional[str] = None, **kwargs):
        details = kwargs.pop("details", {})
        if source:
            details["source"] = source
        if url:
            details["url"] = url
        details.update(kwargs)
        super().__init__(message, error_code="DATA_SOURCE_ERROR", details=details)


class StrategyError(TradingSystemError):
    """策略异常"""
    def __init__(self, message: str, strategy_name: Optional[str] = None,
                 symbol: Optional[str] = None, **kwargs):
        details = kwargs.pop("details", {})
        if strategy_name:
            details["strategy_name"] = strategy_name
        if symbol:
            details["symbol"] = symbol
        details.update(kwargs)
        super().__init__(message, error_code="STRATEGY_ERROR", details=details)


class ExecutionError(TradingSystemError):
    """交易执行异常"""
    def __init__(self, message: str, action: Optional[str] = None,
                 symbol: Optional[str] = None, quantity: Optional[int] = None,
                 price: Optional[float] = None, **kwargs):
        details = kwargs.pop("details", {})
        if action:
            details["action"] = action
        if symbol:
            details["symbol"] = symbol
        if quantity:
            details["quantity"] = quantity
        if price:
            details["price"] = price
        details.update(kwargs)
        super().__init__(message, error_code="EXECUTION_ERROR", details=details)


class RiskControlError(TradingSystemError):
    """风控异常"""
    def __init__(self, message: str, rule: Optional[str] = None,
                 violation_type: Optional[str] = None, **kwargs):
        details = kwargs.pop("details", {})
        if rule:
            details["rule"] = rule
        if violation_type:
            details["violation_type"] = violation_type
        details.update(kwargs)
        super().__init__(message, error_code="RISK_CONTROL_ERROR", details=details)


class ConfigurationError(TradingSystemError):
    """配置异常"""
    def __init__(self, message: str, config_file: Optional[str] = None,
                 config_key: Optional[str] = None, **kwargs):
        details = kwargs.pop("details", {})
        if config_file:
            details["config_file"] = config_file
        if config_key:
            details["config_key"] = config_key
        details.update(kwargs)
        super().__init__(message, error_code="CONFIGURATION_ERROR", details=details)


class RetryableError(TradingSystemError):
    """可重试异常（如网络超时）"""
    def __init__(self, message: str, max_retries: Optional[int] = None,
                 retry_count: Optional[int] = None, **kwargs):
        details = kwargs.pop("details", {})
        if max_retries:
            details["max_retries"] = max_retries
        if retry_count:
            details["retry_count"] = retry_count
        details.update(kwargs)
        super().__init__(message, error_code="RETRYABLE_ERROR", details=details)


def safe_execute(func, *args, error_class: Type[TradingSystemError] = TradingSystemError,
                 default_return=None, max_retries: int = 1, retry_delay: float = 1.0,
                 **kwargs):
    """
    安全执行函数，捕获异常并转换为系统异常

    Args:
        func: 要执行的函数
        *args: 函数参数
        error_class: 异常类，默认为TradingSystemError
        default_return: 异常时的默认返回值
        max_retries: 最大重试次数（仅对RetryableError有效）
        retry_delay: 重试延迟（秒）
        **kwargs: 函数关键字参数

    Returns:
        函数返回值或default_return
    """
    import time
    from functools import wraps

    @wraps(func)
    def wrapper():
        return func(*args, **kwargs)

    for attempt in range(max_retries):
        try:
            return wrapper()
        except RetryableError as e:
            if attempt == max_retries - 1:
                # 最后一次重试仍然失败
                raise error_class(
                    message=f"操作重试{max_retries}次后失败: {str(e)}",
                    details={
                        "original_error": str(e),
                        "max_retries": max_retries,
                        "retry_count": attempt + 1
                    }
                )
            time.sleep(retry_delay * (2 ** attempt))  # 指数退避
        except Exception as e:
            # 将通用异常转换为指定异常类型
            raise error_class(
                message=f"执行失败: {str(e)}",
                details={
                    "original_error": str(e),
                    "function": func.__name__,
                    "attempt": attempt + 1
                }
            ) from e

    return default_return


def log_error(logger: logging.Logger, error: Exception,
              level: int = logging.ERROR, context: Optional[Dict[str, Any]] = None):
    """
    记录错误日志

    Args:
        logger: 日志记录器
        error: 异常对象
        level: 日志级别
        context: 额外上下文信息
    """
    if isinstance(error, TradingSystemError):
        error_dict = error.to_dict()
        if context:
            error_dict["context"] = context

        log_message = f"{error_dict['error_type']}: {error_dict['message']}"
        if error_dict.get('error_code'):
            log_message = f"[{error_dict['error_code']}] {log_message}"

        logger.log(level, log_message, extra=error_dict)
    else:
        # 普通异常
        error_info = {
            "error_type": error.__class__.__name__,
            "message": str(error),
            "timestamp": datetime.now().isoformat(),
            "traceback": traceback.format_exc()
        }
        if context:
            error_info["context"] = context

        logger.log(level, f"{error.__class__.__name__}: {str(error)}", extra=error_info)


def create_error_handler(logger: logging.Logger, default_error_class: Type[TradingSystemError] = TradingSystemError):
    """
    创建错误处理装饰器

    Args:
        logger: 日志记录器
        default_error_class: 默认异常类

    Returns:
        错误处理装饰器
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                log_error(logger, e)
                if not isinstance(e, TradingSystemError):
                    # 转换为系统异常
                    raise default_error_class(
                        message=f"未处理的异常: {str(e)}",
                        details={
                            "function": func.__name__,
                            "original_error": str(e)
                        }
                    ) from e
                raise
        return wrapper
    return decorator