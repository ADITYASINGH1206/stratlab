"""Technical indicators calculated via NumPy with exact TradingView formula parity."""

import ast

import numpy as np
import pandas as pd
from numba import njit


@njit(cache=True)
def _seeded_recursive(source: np.ndarray, length: int, alpha: float) -> np.ndarray:
    """Pine's ta.ema / ta.rma recursion.

    The first value is the SMA of the first `length` consecutive valid values; after that
    out[i] = alpha * x[i] + (1 - alpha) * out[i-1]. Leading NaNs (e.g. an EMA of an RSI)
    are skipped instead of poisoning the whole series, which is what Pine does.
    """
    n = len(source)
    out = np.full(n, np.nan)
    if length <= 0:
        return out
    run = 0
    seed_idx = -1
    for i in range(n):
        if np.isnan(source[i]):
            run = 0
        else:
            run += 1
            if run == length:
                seed_idx = i
                break
    if seed_idx < 0:
        return out
    s = 0.0
    for j in range(seed_idx - length + 1, seed_idx + 1):
        s += source[j]
    out[seed_idx] = s / length
    for i in range(seed_idx + 1, n):
        x = source[i]
        if np.isnan(x):
            out[i] = out[i - 1]
        else:
            out[i] = alpha * x + (1.0 - alpha) * out[i - 1]
    return out


def rma(source: np.ndarray, length: int) -> np.ndarray:
    """TradingView's ta.rma (Wilder): alpha = 1/length, seeded with an SMA."""
    return _seeded_recursive(np.asarray(source, dtype=np.float64), int(length), 1.0 / length if length > 0 else 0.0)


def sma(source: np.ndarray, length: int) -> np.ndarray:
    """Simple Moving Average (ta.sma). A window containing NaN is NaN, like Pine."""
    src = np.asarray(source, dtype=np.float64)
    if length <= 0:
        return np.full(len(src), np.nan)
    return pd.Series(src).rolling(int(length), min_periods=int(length)).mean().to_numpy()


def ema(source: np.ndarray, length: int) -> np.ndarray:
    """TradingView's ta.ema: alpha = 2/(length+1), seeded with an SMA."""
    return _seeded_recursive(np.asarray(source, dtype=np.float64), int(length), 2.0 / (length + 1.0))


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
    """Relative Strength Index (ta.rsi): RMA of gains and losses.

    Pine: rsi = down == 0 ? 100 : up == 0 ? 0 : 100 - 100 / (1 + up / down).
    The first value appears on bar `length` (the first change is on bar 1).
    """
    src = np.asarray(source, dtype=np.float64)
    n = len(src)
    if n <= length or length <= 0:
        return np.full(n, np.nan)
    change = np.full(n, np.nan)
    change[1:] = np.diff(src)
    gains = np.where(np.isnan(change), np.nan, np.maximum(change, 0.0))
    losses = np.where(np.isnan(change), np.nan, np.maximum(-change, 0.0))
    up = rma(gains, length)
    down = rma(losses, length)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 100.0 - 100.0 / (1.0 + up / down)
    out = np.where(down == 0.0, 100.0, out)
    out = np.where((up == 0.0) & (down != 0.0), 0.0, out)
    return np.where(np.isnan(up) | np.isnan(down), np.nan, out)


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
    """Rolling highest over `length` bars including the current bar (ta.highest)."""
    src = np.asarray(source, dtype=np.float64)
    return pd.Series(src).rolling(int(length), min_periods=int(length)).max().to_numpy()


def lowest(source: np.ndarray, length: int) -> np.ndarray:
    """Rolling lowest over `length` bars including the current bar (ta.lowest)."""
    src = np.asarray(source, dtype=np.float64)
    return pd.Series(src).rolling(int(length), min_periods=int(length)).min().to_numpy()


def donchian(high: np.ndarray, low: np.ndarray, length: int) -> tuple[np.ndarray, np.ndarray]:
    """Donchian channel (highest high and lowest low). Returns (upper, lower)."""
    return highest(high, length), lowest(low, length)


_BIN_OPS = {
    ast.Add: np.add,
    ast.Sub: np.subtract,
    ast.Mult: np.multiply,
    ast.Div: np.divide,
}


def check_expression(expr: str, names: set[str]) -> list[str]:
    """Return a list of problems with an `expr` indicator (empty list means OK).

    Only numbers, known series names, + - * /, unary minus and parentheses are allowed.
    Specs can be written by anyone in the room, so nothing else ever reaches the evaluator.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        return [f"expression '{expr}' is not valid arithmetic: {e.msg}"]
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Expression, ast.Load, ast.UnaryOp, ast.USub, ast.UAdd, ast.BinOp, *_BIN_OPS)):
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            continue
        if isinstance(node, ast.Name):
            if node.id not in names:
                problems.append(f"expression '{expr}' uses unknown series '{node.id}'")
            continue
        problems.append(f"expression '{expr}' may only use numbers, series names, + - * / and parentheses")
        break
    return problems


def evaluate_expression(expr: str, context: dict[str, np.ndarray]) -> np.ndarray:
    """Evaluate arithmetic on series, e.g. 'atr / close * 100', without eval()."""
    problems = check_expression(expr, set(context))
    if problems:
        raise ValueError(problems[0])
    n = len(context["close"])

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            return np.asarray(context[node.id], dtype=np.float64)
        if isinstance(node, ast.UnaryOp):
            v = ev(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        return _BIN_OPS[type(node.op)](ev(node.left), ev(node.right))

    with np.errstate(divide="ignore", invalid="ignore"):
        out = ev(ast.parse(expr, mode="eval"))
    out = np.broadcast_to(np.asarray(out, dtype=np.float64), (n,)).copy()
    out[~np.isfinite(out)] = np.nan
    return out
