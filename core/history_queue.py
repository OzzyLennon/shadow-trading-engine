"""
历史队列管理模块
用于预热和持久化价格队列数据，支持跨日 Z-Score 和 EMA 计算
"""
import os
import json
import datetime
from typing import Dict, List, Optional, Tuple
from enum import Enum
from core.logging_config import get_logger

logger = get_logger("history_queue")

# 历史队列存储目录
HISTORY_DIR = os.path.join(os.path.dirname(__file__), "..", "research", "data", "queues")


class PreheatMode(Enum):
    """预热模式枚举"""
    AKSHARE = "akshare"              # 从 AkShare 获取历史数据
    LOCAL_CACHE = "local_cache"      # 从本地缓存加载
    REALTIME_FALLBACK = "realtime"   # 降级到实时收集模式


class PreheatResult:
    """预热结果"""
    def __init__(self, price_queue: List[float], long_ema_queue: List[float],
                 mode: PreheatMode, fallback: bool = False):
        self.price_queue = price_queue
        self.long_ema_queue = long_ema_queue
        self.mode = mode
        self.fallback = fallback  # 是否需要降级到实时收集


def ensure_history_dir():
    """确保历史目录存在"""
    os.makedirs(HISTORY_DIR, exist_ok=True)


def get_history_file(symbol: str) -> str:
    """获取股票历史队列文件路径"""
    ensure_history_dir()
    return os.path.join(HISTORY_DIR, f"{symbol}_queue.json")


def save_queue_history(symbol: str,
                       price_queue: List[float],
                       long_ema_queue: List[float]) -> None:
    """
    保存队列历史到文件

    Args:
        symbol: 股票代码
        price_queue: 短期价格队列
        long_ema_queue: 长期EMA队列
    """
    filepath = get_history_file(symbol)
    data = {
        "symbol": symbol,
        "last_update": datetime.datetime.now().isoformat(),
        "price_queue": price_queue,
        "long_ema_queue": long_ema_queue
    }
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        logger.debug(f"队列历史已保存: {symbol}")
    except Exception as e:
        logger.warning(f"保存队列历史失败: {symbol}, {e}")


def load_queue_history(symbol: str,
                       max_len: int = 60) -> Tuple[List[float], List[float], bool]:
    """
    从文件加载队列历史

    Args:
        symbol: 股票代码
        max_len: 最大保留长度

    Returns:
        (price_queue, long_ema_queue, is_fresh)
        is_fresh: 数据是否为今天的数据
    """
    filepath = get_history_file(symbol)

    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            price_queue = data.get("price_queue", [])[-max_len:]
            long_ema_queue = data.get("long_ema_queue", [])[-max_len:]
            last_update = data.get("last_update", "")

            # 检查数据新鲜度（如果是今天的数据则视为新鲜）
            today = datetime.date.today().isoformat()
            is_fresh = last_update.startswith(today)

            logger.info(f"加载历史队列: {symbol}, price_queue={len(price_queue)}, "
                        f"long_ema_queue={len(long_ema_queue)}, fresh={is_fresh}")

            return price_queue, long_ema_queue, is_fresh

        except Exception as e:
            logger.warning(f"加载队列历史失败: {symbol}, {e}")

    return [], [], False


def fetch_preheat_data_from_akshare(symbol: str,
                                     minutes: int = 60,
                                     ema_alpha: float = 0.15,
                                     timeout: int = 10) -> Tuple[List[float], List[float], bool]:
    """
    从 AkShare 获取预热数据

    Args:
        symbol: 股票代码 (如 "sh600886")
        minutes: 需要的分钟数
        ema_alpha: EMA 平滑系数
        timeout: 请求超时时间（秒）

    Returns:
        (price_queue, long_ema_queue, fallback_mode)
        fallback_mode: True 表示需要降级到实时收集模式
    """
    try:
        import akshare as ak

        # 转换股票代码格式 (sh600886 -> 600886)
        if symbol.startswith("sh") or symbol.startswith("sz"):
            code = symbol[2:]
        else:
            code = symbol

        # 计算日期范围
        end_date = datetime.datetime.now()
        start_date = end_date - datetime.timedelta(days=2)  # 多获取一些数据

        logger.info(f"📊 {symbol} 正在从 AkShare 预热数据...")

        # 获取1分钟K线
        df = ak.stock_zh_a_hist_min_em(
            symbol=code,
            period="1",
            start_date=start_date.strftime("%Y-%m-%d %H:%M:%S"),
            end_date=end_date.strftime("%Y-%m-%d %H:%M:%S"),
            adjust=""
        )

        if df is None or df.empty:
            logger.warning(f"AkShare 未获取到数据: {symbol}，降级到实时收集模式")
            return [], [], True

        # 取最近的 minutes 条数据
        df = df.tail(minutes)

        # 提取收盘价并应用 EMA 平滑
        prices = df['收盘'].tolist()
        smoothed_prices = []
        ema = None

        for price in prices:
            if ema is None:
                ema = price
            else:
                ema = ema_alpha * price + (1 - ema_alpha) * ema
            smoothed_prices.append(ema)

        logger.info(f"✅ AkShare 预热成功: {symbol}, 获取 {len(smoothed_prices)} 条数据")

        # price_queue 和 long_ema_queue 使用相同的数据
        return smoothed_prices, smoothed_prices.copy(), False

    except ImportError:
        logger.warning("⚠️ AkShare 未安装，降级到实时收集模式")
        return [], [], True
    except Exception as e:
        logger.error(f"⚠️ AkShare 数据获取失败: {symbol}, {e}，降级到实时收集模式")
        return [], [], True


def get_preheat_mode(symbol: str,
                     min_points: int = 20) -> Tuple[PreheatMode, str]:
    """
    获取推荐的预热模式

    Args:
        symbol: 股票代码
        min_points: 最小数据点数

    Returns:
        (mode, description)
    """
    # 检查本地缓存
    price_q, long_q, is_fresh = load_queue_history(symbol, max_len=60)

    if is_fresh and len(price_q) >= min_points:
        return PreheatMode.LOCAL_CACHE, f"本地缓存 ({len(price_q)} 条)"

    if len(price_q) >= min_points:
        return PreheatMode.LOCAL_CACHE, f"本地缓存 (非今日数据, {len(price_q)} 条)"

    # 需要从 AkShare 获取或降级
    return PreheatMode.AKSHARE, "需要从 AkShare 获取"


def preload_all_queues(symbols: Dict[str, str],
                       ema_alpha: float = 0.15,
                       min_points: int = 20) -> Dict[str, Dict[str, List[float]]]:
    """
    预加载所有股票的队列数据

    Args:
        symbols: 股票代码字典 {code: name}
        ema_alpha: EMA 平滑系数
        min_points: 最小数据点数

    Returns:
        {symbol: {"price_queue": [...], "long_ema_queue": [...], "fallback": bool}}
    """
    result = {}
    fallback_count = 0

    for sym in symbols.keys():
        # 优先尝试加载本地历史
        price_q, long_q, is_fresh = load_queue_history(sym, max_len=60)

        if is_fresh and len(price_q) >= min_points:
            # 本地数据新鲜且足够
            result[sym] = {
                "price_queue": price_q,
                "long_ema_queue": long_q,
                "fallback": False
            }
            continue

        # 本地数据不新鲜或不足，从 AkShare 获取
        price_q, long_q, fallback = fetch_preheat_data_from_akshare(
            sym, minutes=60, ema_alpha=ema_alpha
        )

        if fallback:
            fallback_count += 1
            logger.warning(f"⚠️ {sym} 将使用实时收集模式填充队列")

        result[sym] = {
            "price_queue": price_q,
            "long_ema_queue": long_q,
            "fallback": fallback
        }

    # 汇总日志
    if fallback_count > 0:
        logger.warning(f"⚠️ 共 {fallback_count} 只股票降级到实时收集模式，"
                       f"需要通过预热锁收集 {min_points} 个数据点")

    return result
