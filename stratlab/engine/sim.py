"""Numba-accelerated backtest simulation engine matching TradingView broker emulator."""

import numpy as np
import pandas as pd
from numba import njit


@njit
def run_simulation_numba(
    open_p: np.ndarray,
    high_p: np.ndarray,
    low_p: np.ndarray,
    close_p: np.ndarray,
    long_signals: np.ndarray,
    short_signals: np.ndarray,
    atr_series: np.ndarray,
    stop_atr_mult: float,
    target_atr_mult: float,
    stop_pct: float,
    target_pct: float,
    time_bars: int,
    opposite_exit: bool,
    commission_pct: float,
    slippage_cost: float,
    initial_capital: float,
):
    """Core simulation loop compiled with Numba njit."""
    n_bars = len(close_p)
    max_trades = n_bars

    # Pre-allocate output arrays for trade logs
    t_entry_bar = np.empty(max_trades, dtype=np.int64)
    t_exit_bar = np.empty(max_trades, dtype=np.int64)
    t_entry_price = np.empty(max_trades, dtype=np.float64)
    t_exit_price = np.empty(max_trades, dtype=np.float64)
    t_direction = np.empty(max_trades, dtype=np.int64)  # 1 for long, -1 for short
    t_qty = np.empty(max_trades, dtype=np.float64)
    t_pnl = np.empty(max_trades, dtype=np.float64)
    t_return_pct = np.empty(max_trades, dtype=np.float64)
    t_reason = np.empty(max_trades, dtype=np.int64)  # 1=STOP, 2=TARGET, 3=TIME, 4=OPPOSITE, 5=END

    trade_count = 0
    in_pos = 0  # 0=flat, 1=long
    entry_bar = 0
    entry_price = 0.0
    qty = 0.0
    stop_price = 0.0
    target_price = 1e12
    capital = initial_capital

    equity_curve = np.empty(n_bars, dtype=np.float64)

    for i in range(1, n_bars):
        # 1. Process open position exits on bar i
        if in_pos == 1:
            exited = False
            exit_px = 0.0
            reason_code = 0

            # Opposite signal exit at bar open?
            if opposite_exit and short_signals[i - 1]:
                exit_px = open_p[i] - slippage_cost
                reason_code = 4  # OPPOSITE
                exited = True

            # Time exit at bar open?
            elif time_bars > 0 and (i - entry_bar) >= time_bars:
                exit_px = open_p[i] - slippage_cost
                reason_code = 3  # TIME
                exited = True

            # Intrabar Stop / Limit evaluation via TradingView Broker Emulator path
            if not exited:
                op = open_p[i]
                hi = high_p[i]
                lo = low_p[i]

                # TV Intrabar rule: if open is closer to high, path is Open -> High -> Low -> Close
                # Otherwise, Open -> Low -> High -> Close
                open_nearer_high = (hi - op) < (op - lo)

                if open_nearer_high:
                    # Check Target (Take Profit) first
                    if hi >= target_price:
                        # Filled at limit or gap open
                        raw_fill = op if op > target_price else target_price
                        exit_px = raw_fill - slippage_cost
                        reason_code = 2  # TARGET
                        exited = True
                    elif lo <= stop_price:
                        # Filled at stop or gap open
                        raw_fill = op if op < stop_price else stop_price
                        exit_px = raw_fill - slippage_cost
                        reason_code = 1  # STOP
                        exited = True
                else:
                    # Check Stop Loss first
                    if lo <= stop_price:
                        raw_fill = op if op < stop_price else stop_price
                        exit_px = raw_fill - slippage_cost
                        reason_code = 1  # STOP
                        exited = True
                    elif hi >= target_price:
                        raw_fill = op if op > target_price else target_price
                        exit_px = raw_fill - slippage_cost
                        reason_code = 2  # TARGET
                        exited = True

            if exited:
                gross_proceeds = qty * exit_px
                exit_comm = gross_proceeds * commission_pct
                capital = gross_proceeds - exit_comm

                pnl = capital - (qty * entry_price)
                return_pct = (exit_px - entry_price) / entry_price * 100.0

                t_entry_bar[trade_count] = entry_bar
                t_exit_bar[trade_count] = i
                t_entry_price[trade_count] = entry_price
                t_exit_price[trade_count] = exit_px
                t_direction[trade_count] = 1
                t_qty[trade_count] = qty
                t_pnl[trade_count] = pnl
                t_return_pct[trade_count] = return_pct
                t_reason[trade_count] = reason_code
                trade_count += 1

                in_pos = 0

        # 2. Check entries for next bar if flat
        if in_pos == 0 and long_signals[i - 1]:
            # Fill long at bar i open
            entry_px = open_p[i] + slippage_cost
            entry_comm = capital * commission_pct
            capital_after_comm = capital - entry_comm
            qty = capital_after_comm / entry_px
            in_pos = 1
            entry_bar = i
            entry_price = entry_px

            # Compute stop & target price
            atr_val = atr_series[i - 1]
            if stop_atr_mult > 0.0 and not np.isnan(atr_val):
                stop_price = entry_price - (stop_atr_mult * atr_val)
            elif stop_pct > 0.0:
                stop_price = entry_price * (1.0 - stop_pct / 100.0)
            else:
                stop_price = 0.0

            if target_atr_mult > 0.0 and not np.isnan(atr_val):
                target_price = entry_price + (target_atr_mult * atr_val)
            elif target_pct > 0.0:
                target_price = entry_price * (1.0 + target_pct / 100.0)
            else:
                target_price = 1e12

        # Record equity
        if in_pos == 1:
            equity_curve[i] = qty * close_p[i]
        else:
            equity_curve[i] = capital

    equity_curve[0] = initial_capital

    return (
        t_entry_bar[:trade_count],
        t_exit_bar[:trade_count],
        t_entry_price[:trade_count],
        t_exit_price[:trade_count],
        t_direction[:trade_count],
        t_qty[:trade_count],
        t_pnl[:trade_count],
        t_return_pct[:trade_count],
        t_reason[:trade_count],
        equity_curve,
    )


REASON_MAP = {
    1: "STOP",
    2: "TARGET",
    3: "TIME",
    4: "OPPOSITE",
    5: "END",
}


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
    slippage_ticks: int = 1,
    tick_size: float = 0.01,
    initial_capital: float = 10000.0,
) -> tuple[pd.DataFrame, np.ndarray]:
    """Execute high-performance backtest simulation returning trades DataFrame and equity series."""
    n = len(df)
    open_p = df["open"].to_numpy(dtype=np.float64)
    high_p = df["high"].to_numpy(dtype=np.float64)
    low_p = df["low"].to_numpy(dtype=np.float64)
    close_p = df["close"].to_numpy(dtype=np.float64)

    if short_signals is None:
        short_signals = np.zeros(n, dtype=bool)
    if atr_series is None:
        atr_series = np.full(n, np.nan, dtype=np.float64)

    slippage_cost = slippage_ticks * tick_size

    (
        entry_bars,
        exit_bars,
        entry_prices,
        exit_prices,
        directions,
        qtys,
        pnls,
        return_pcts,
        reasons,
        equity_curve,
    ) = run_simulation_numba(
        open_p,
        high_p,
        low_p,
        close_p,
        long_signals,
        short_signals,
        atr_series,
        float(stop_atr_mult),
        float(target_atr_mult),
        float(stop_pct),
        float(target_pct),
        int(time_bars),
        bool(opposite_exit),
        float(commission_pct),
        float(slippage_cost),
        float(initial_capital),
    )

    if len(entry_bars) == 0:
        trades_df = pd.DataFrame(
            columns=[
                "trade_num",
                "direction",
                "entry_time",
                "entry_bar",
                "entry_price",
                "exit_time",
                "exit_bar",
                "exit_price",
                "qty",
                "pnl",
                "return_pct",
                "reason",
            ]
        )
    else:
        timestamps = df["timestamp"].to_numpy()
        trades_df = pd.DataFrame(
            {
                "trade_num": np.arange(1, len(entry_bars) + 1),
                "direction": ["long" if d == 1 else "short" for d in directions],
                "entry_time": timestamps[entry_bars],
                "entry_bar": entry_bars,
                "entry_price": np.round(entry_prices, 4),
                "exit_time": timestamps[exit_bars],
                "exit_bar": exit_bars,
                "exit_price": np.round(exit_prices, 4),
                "qty": np.round(qtys, 6),
                "pnl": np.round(pnls, 2),
                "return_pct": np.round(return_pcts, 2),
                "reason": [REASON_MAP.get(r, "OTHER") for r in reasons],
            }
        )

    return trades_df, equity_curve
