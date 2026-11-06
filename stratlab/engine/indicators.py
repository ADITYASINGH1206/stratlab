"""Technical indicators calculated via NumPy with exact TradingView formula parity."""

import numpy as np


def rma(source: np.ndarray, length: int) -> np.ndarray:
    """TradingView's ta.rma (Wilder's Moving Average).

    alpha = 1 / length
    Seeded with the simple moving average (SMA) of the first `length` valid values.
    """
    n = len(source)
    out = np.full(n, np.nan, dtype=np.float64)
    if n < length or length <= 0:
        return out

    # First value is SMA of first length elements
    sma_first = np.mean(source[:length])
    out[length - 1] = sma_first
    alpha = 1.0 / length

    for i in range(length, n):
        out[i] = alpha * source[i] + (1.0 - alpha) * out[i - 1]

    return out


def sma(source: np.ndarray, length: int) -> np.ndarray:
    """Simple Moving Average (ta.sma)."""
    n = len(source)
    out = np.full(n, np.nan, dtype=np.float64)
    if n < length or length <= 0:
        return out

    # Cumulative sum approach for O(N) performance
    cumsum = np.cumsum(source)
    out[length - 1] = cumsum[length - 1] / length
    out[length:] = (cumsum[length:] - cumsum[:-length]) / length
    return out


def ema(source: np.ndarray, length: int) -> np.ndarray:
    """TradingView's ta.ema.

    alpha = 2 / (length + 1)
    Seeded with SMA of first `length` values, matching Pine Script.
    """
    n = len(source)
    out = np.full(n, np.nan, dtype=np.float64)
    if n < length or length <= 0:
        return out

    # Pine seeds EMA with the SMA of the first length values
    out[length - 1] = np.mean(source[:length])
    alpha = 2.0 / (length + 1.0)

    for i in range(length, n):
        out[i] = alpha * source[i] + (1.0 - alpha) * out[i - 1]

    return out


def wma(source: np.ndarray, length: int) -> np.ndarray:
    """Weighted Moving Average (ta.wma)."""
    n = len(source)
    out = np.full(n, np.nan, dtype=np.float64)
    if n < length or length <= 0:
        return out

    weights = np.arange(1, length + 1, dtype=np.float64)
    weight_sum = weights.sum()

    for i in range(length - 1, n):
        window = source[i - length + 1 : i + 1]
        out[i] = np.dot(window, weights) / weight_sum

    return out


def tr(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    """True Range (ta.tr).

    tr = max(high - low, abs(high - close[1]), abs(low - close[1]))
    First bar tr is high[0] - low[0].
    """
    n = len(high)
    out = np.empty(n, dtype=np.float64)
    if n == 0:
        return out

    out[0] = high[0] - low[0]
    for i in range(1, n):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        out[i] = max(hl, hc, lc)

    return out


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int) -> np.ndarray:
    """Average True Range (ta.atr) using Wilder's RMA."""
    true_range = tr(high, low, close)
    return rma(true_range, length)


def rsi(source: np.ndarray, length: int) -> np.ndarray:
    """Relative Strength Index (ta.rsi) using Wilder's RMA smoothing."""
    n = len(source)
    out = np.full(n, np.nan, dtype=np.float64)
    if n <= length or length <= 0:
        return out

    diff = np.diff(source)
    gains = np.where(diff > 0, diff, 0.0)
    losses = np.where(diff < 0, -diff, 0.0)

    # RMA of gains and losses over length
    avg_gain = rma(gains, length)
    avg_loss = rma(losses, length)

    for i in range(length - 1, len(diff)):
        ag = avg_gain[i]
        al = avg_loss[i]
        bar_idx = i + 1  # diff is length n - 1
        if np.isnan(ag) or np.isnan(al):
            continue
        if al == 0.0:
            out[bar_idx] = 100.0 if ag > 0 else 50.0
        else:
            rs = ag / al
            out[bar_idx] = 100.0 - (100.0 / (1.0 + rs))

    return out


def macd(source: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Moving Average Convergence Divergence (ta.macd).

    Returns (macd_line, signal_line, hist).
    """
    fast_ma = ema(source, fast)
    slow_ma = ema(source, slow)
    macd_line = fast_ma - slow_ma

    # Calculate signal line over valid macd values
    valid_idx = np.where(~np.isnan(macd_line))[0]
    signal_line = np.full_like(macd_line, np.nan)
    if len(valid_idx) >= signal:
        first_valid = valid_idx[0]
        sub_signal = ema(macd_line[first_valid:], signal)
        signal_line[first_valid:] = sub_signal

    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def bb(source: np.ndarray, length: int = 20, mult: float = 2.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bollinger Bands (ta.bb).

    Returns (upper, basis, lower).
    """
    basis = sma(source, length)
    n = len(source)
    dev = np.full(n, np.nan, dtype=np.float64)

    for i in range(length - 1, n):
        window = source[i - length + 1 : i + 1]
        # TradingView uses population std dev (ddof=0)
        dev[i] = mult * np.std(window, ddof=0)

    upper = basis + dev
    lower = basis - dev
    return upper, basis, lower


def highest(source: np.ndarray, length: int) -> np.ndarray:
    """Rolling highest over length bars (ta.highest)."""
    n = len(source)
    out = np.full(n, np.nan, dtype=np.float64)
    for i in range(length - 1, n):
        out[i] = np.max(source[i - length + 1 : i + 1])
    return out


def lowest(source: np.ndarray, length: int) -> np.ndarray:
    """Rolling lowest over length bars (ta.lowest)."""
    n = len(source)
    out = np.full(n, np.nan, dtype=np.float64)
    for i in range(length - 1, n):
        out[i] = np.min(source[i - length + 1 : i + 1])
    return out


def donchian(high: np.ndarray, low: np.ndarray, length: int) -> tuple[np.ndarray, np.ndarray]:
    """Donchian channel (highest high and lowest low). Returns (upper, lower)."""
    return highest(high, length), lowest(low, length)


def evaluate_expression(expr: str, context: dict[str, np.ndarray]) -> np.ndarray:
    """Safely evaluate arithmetic series expressions, e.g. 'atr / close * 100'."""
    safe_dict = {k: v for k, v in context.items() if isinstance(v, (np.ndarray, float, int))}
    safe_dict["np"] = np
    # Evaluate within restricted globals
    return eval(expr, {"__builtins__": {}}, safe_dict)
