"""Numba-accelerated backtest simulation engine matching TradingView's broker emulator.

Execution model (TradingView defaults, `process_orders_on_close=false`):

* Signals are evaluated on bar close. Market orders (entries, time exits, signal exits)
  fill at the NEXT bar's open, plus slippage against the trader.
* An entry order is only placed if the strategy was flat at the close that produced the
  signal. A position closed intrabar can therefore never be re-entered at that same bar's open.
* Stop and target levels are computed from the entry fill price and the ATR of the signal
  bar. They become active on the bar after the entry fill (TradingView places the exit order
  at the close of the entry bar).
* Intrabar path: if the open is nearer the high the path is O-H-L-C, otherwise O-L-H-C.
  A gap through a level fills at the open.
* Slippage applies to market and stop fills. Limit (target) fills get no slippage, like
  TradingView.
* Commission is a percentage of traded value on each side. Long-only, one position at a time.
"""

import numpy as np
import pandas as pd
from numba import njit

REASON_MAP = {1: "STOP", 2: "TARGET", 3: "TIME", 4: "OPPOSITE", 5: "END"}


@njit(cache=True)
def run_simulation_numba(
    open_p, high_p, low_p, close_p, long_signals, short_signals, atr_series,
    stop_atr_mult, target_atr_mult, stop_pct, target_pct, time_bars, opposite_exit,
    commission_pct, slippage_cost, initial_capital,
):
    n_bars = len(close_p)
    t_entry_bar = np.empty(n_bars, dtype=np.int64)
    t_exit_bar = np.empty(n_bars, dtype=np.int64)
    t_entry_price = np.empty(n_bars, dtype=np.float64)
    t_exit_price = np.empty(n_bars, dtype=np.float64)
    t_direction = np.empty(n_bars, dtype=np.int64)
    t_qty = np.empty(n_bars, dtype=np.float64)
    t_pnl = np.empty(n_bars, dtype=np.float64)
    t_return_pct = np.empty(n_bars, dtype=np.float64)
    t_reason = np.empty(n_bars, dtype=np.int64)
    equity_curve = np.empty(n_bars, dtype=np.float64)

    trade_count = 0
    in_pos = 0
    entry_bar = 0
    entry_price = 0.0
    entry_capital = initial_capital
    qty = 0.0
    stop_price = -1.0
    target_price = 1e18
    capital = initial_capital
    if n_bars > 0:
        equity_curve[0] = initial_capital

    for i in range(1, n_bars):
        flat_at_prev_close = in_pos == 0

        # 1) exits
        if in_pos == 1:
            exited = False
            exit_px = 0.0
            reason = 0
            op = open_p[i]
            hi = high_p[i]
            lo = low_p[i]
            if opposite_exit and short_signals[i - 1]:
                exit_px = op - slippage_cost
                reason = 4
                exited = True
            elif time_bars > 0 and (i - entry_bar) >= time_bars:
                exit_px = op - slippage_cost
                reason = 3
                exited = True
            elif i > entry_bar:
                if op <= stop_price:
                    exit_px = op - slippage_cost
                    reason = 1
                    exited = True
                elif op >= target_price:
                    exit_px = op
                    reason = 2
                    exited = True
                else:
                    open_nearer_high = (hi - op) < (op - lo)
                    if open_nearer_high:
                        if hi >= target_price:
                            exit_px = target_price
                            reason = 2
                            exited = True
                        elif lo <= stop_price:
                            exit_px = stop_price - slippage_cost
                            reason = 1
                            exited = True
                    else:
                        if lo <= stop_price:
                            exit_px = stop_price - slippage_cost
                            reason = 1
                            exited = True
                        elif hi >= target_price:
                            exit_px = target_price
                            reason = 2
                            exited = True
            if exited:
                proceeds = qty * exit_px
                capital = proceeds - proceeds * commission_pct
                pnl = capital - entry_capital
                t_entry_bar[trade_count] = entry_bar
                t_exit_bar[trade_count] = i
                t_entry_price[trade_count] = entry_price
                t_exit_price[trade_count] = exit_px
                t_direction[trade_count] = 1
                t_qty[trade_count] = qty
                t_pnl[trade_count] = pnl
                t_return_pct[trade_count] = pnl / entry_capital * 100.0
                t_reason[trade_count] = reason
                trade_count += 1
                in_pos = 0

        # 2) entries: only if flat when the signal bar closed
        if in_pos == 0 and flat_at_prev_close and long_signals[i - 1]:
            entry_px = open_p[i] + slippage_cost
            entry_capital = capital
            qty = capital * (1.0 - commission_pct) / entry_px
            capital = 0.0
            in_pos = 1
            entry_bar = i
            entry_price = entry_px
            atr_val = atr_series[i - 1]
            if stop_atr_mult > 0.0 and not np.isnan(atr_val):
                stop_price = entry_price - stop_atr_mult * atr_val
            elif stop_pct > 0.0:
                stop_price = entry_price * (1.0 - stop_pct / 100.0)
            else:
                stop_price = -1.0
            if target_atr_mult > 0.0 and not np.isnan(atr_val):
                target_price = entry_price + target_atr_mult * atr_val
            elif target_pct > 0.0:
                target_price = entry_price * (1.0 + target_pct / 100.0)
            else:
                target_price = 1e18

        # 3) mark to market
        if in_pos == 1:
            equity_curve[i] = qty * close_p[i]
        else:
            equity_curve[i] = capital

    return (
        t_entry_bar[:trade_count], t_exit_bar[:trade_count], t_entry_price[:trade_count],
        t_exit_price[:trade_count], t_direction[:trade_count], t_qty[:trade_count],
        t_pnl[:trade_count], t_return_pct[:trade_count], t_reason[:trade_count], equity_curve,
    )


TRADE_COLUMNS = [
    "trade_num", "direction", "entry_time", "entry_bar", "entry_price", "exit_time",
    "exit_bar", "exit_price", "qty", "pnl", "return_pct", "reason",
]


def simulate(
    df: pd.DataFrame,
    long_signals: np.ndarray,
    short_signals: np.ndarray | None = None,
    atr_series: np.ndarray | None = None,
    stop_atr_mult: float = 0.0,
    target_atr_mult: float = 0.0,
    stop_pct: float = 0.0,
    target_pct: float = 0.0,
    time_bars: int = 0,
    opposite_exit: bool = False,
    commission_pct: float = 0.001,
    slippage_ticks: float = 1,
    tick_size: float = 0.01,
    initial_capital: float = 10000.0,
) -> tuple[pd.DataFrame, np.ndarray]:
    """Run the bar loop over `df` (already sliced to the window) and return (trades, equity)."""
    n = len(df)
    long_signals = np.asarray(long_signals, dtype=np.bool_)
    short_signals = np.zeros(n, dtype=np.bool_) if short_signals is None else np.asarray(short_signals, dtype=np.bool_)
    atr_series = np.full(n, np.nan) if atr_series is None else np.asarray(atr_series, dtype=np.float64)
    if (stop_atr_mult > 0 or target_atr_mult > 0) and np.all(np.isnan(atr_series)):
        raise ValueError("ATR stop/target requested but no ATR series is available (add an indicator with fn: atr)")

    out = run_simulation_numba(
        df["open"].to_numpy(dtype=np.float64), df["high"].to_numpy(dtype=np.float64),
        df["low"].to_numpy(dtype=np.float64), df["close"].to_numpy(dtype=np.float64),
        long_signals, short_signals, atr_series,
        float(stop_atr_mult), float(target_atr_mult), float(stop_pct), float(target_pct),
        int(time_bars), bool(opposite_exit), float(commission_pct),
        float(slippage_ticks) * float(tick_size), float(initial_capital),
    )
    entry_bars, exit_bars, entry_px, exit_px, dirs, qtys, pnls, rets, reasons, equity = out

    if len(entry_bars) == 0:
        return pd.DataFrame(columns=TRADE_COLUMNS), equity

    ts = df["timestamp"].to_numpy()
    trades = pd.DataFrame({
        "trade_num": np.arange(1, len(entry_bars) + 1),
        "direction": ["long"] * len(entry_bars),
        "entry_time": ts[entry_bars],
        "entry_bar": entry_bars,
        "entry_price": np.round(entry_px, 4),
        "exit_time": ts[exit_bars],
        "exit_bar": exit_bars,
        "exit_price": np.round(exit_px, 4),
        "qty": np.round(qtys, 8),
        "pnl": np.round(pnls, 2),
        "return_pct": np.round(rets, 4),
        "reason": [REASON_MAP.get(int(r), "OTHER") for r in reasons],
    })
    return trades, equity
