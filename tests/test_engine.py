"""Tests for engine core: indicators, condition tree, Numba simulator, and metrics."""

import time
from pathlib import Path

import numpy as np
import pandas as pd

from stratlab.engine.backtest import run_backtest
from stratlab.engine.conditions import evaluate_condition_tree
from stratlab.engine.indicators import atr, ema, rma, rsi, sma, tr
from stratlab.engine.sim import simulate
from stratlab.spec.validate import validate_spec_file


def test_tradingview_indicator_formulas_20bars():
    """Verify indicators against 20 bars with exact mathematical expectations."""
    # Constant series test
    arr = np.array([10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0,
                    20.0, 21.0, 22.0, 23.0, 24.0, 25.0, 26.0, 27.0, 28.0, 29.0])

    # 1. SMA length 5
    sma5 = sma(arr, 5)
    assert np.isnan(sma5[3])
    assert np.isclose(sma5[4], 12.0)  # (10+11+12+13+14)/5 = 12.0
    assert np.isclose(sma5[5], 13.0)  # (11+12+13+14+15)/5 = 13.0

    # 2. EMA length 5 seeded with SMA of first 5 bars
    ema5 = ema(arr, 5)
    assert np.isnan(ema5[3])
    assert np.isclose(ema5[4], 12.0)  # Seed is SMA(first 5) = 12.0
    # Next bar: alpha = 2/(5+1) = 1/3; ema = 1/3 * 15 + 2/3 * 12 = 5 + 8 = 13.0
    assert np.isclose(ema5[5], 13.0)
    # Next bar: ema = 1/3 * 16 + 2/3 * 13 = 5.3333 + 8.6666 = 14.0
    assert np.isclose(ema5[6], 14.0)

    # 3. RMA length 5 (alpha = 1/5 = 0.2, seed is SMA of first 5 bars)
    rma5 = rma(arr, 5)
    assert np.isnan(rma5[3])
    assert np.isclose(rma5[4], 12.0)  # Seed is SMA(first 5) = 12.0
    # Next bar: 0.2 * 15 + 0.8 * 12 = 3.0 + 9.6 = 12.6
    assert np.isclose(rma5[5], 12.6)

    # 4. ATR on linear bars
    high = arr + 1.0
    low = arr - 1.0
    close = arr
    true_range = tr(high, low, close)
    # Every bar high - low = 2.0; close[i-1] is arr[i-1], high - close[i-1] = arr[i]+1 - arr[i-1] = 2.0
    assert np.allclose(true_range, 2.0)
    atr5 = atr(high, low, close, 5)
    assert np.isclose(atr5[4], 2.0)
    assert np.isclose(atr5[10], 2.0)

    # 5. RSI monotonic upward series must be 100
    rsi5 = rsi(arr, 5)
    assert np.isclose(rsi5[6], 100.0)


def test_condition_evaluator():
    n = 6
    close = np.array([10.0, 12.0, 15.0, 11.0, 9.0, 14.0])
    ema_line = np.array([11.0, 11.0, 11.0, 11.0, 11.0, 11.0])
    context = {"close": close, "ema": ema_line}

    # gt
    gt_res = evaluate_condition_tree({"gt": ["close", "ema"]}, context, n)
    assert np.array_equal(gt_res, [False, True, True, False, False, True])

    # crosses_above
    cross_res = evaluate_condition_tree({"crosses_above": ["close", "ema"]}, context, n)
    # close was 10 (<=11) then 12 (>11) -> cross at idx 1
    # close was 9 (<=11) then 14 (>11) -> cross at idx 5
    assert bool(cross_res[1]) is True
    assert bool(cross_res[5]) is True
    assert bool(cross_res[2]) is False


def test_hand_checked_toy_simulation():
    """Verify exact fills, intrabar path, commission, and slippage on a 3-trade series."""
    # 10 bars
    # Bar 0: prep
    # Bar 1: Long signal generated on close -> enter bar 2 at open
    # Bar 2: Enter Long at Open 100 + slippage (0.10) = 100.10
    #        Target = 110.11, Stop = 95.095.
    # Bar 3: High reaches 112 -> Take profit fills at target 110.11 - slippage (0.10) = 110.01
    #
    # Bar 4: Long signal generated on close -> enter bar 5 at open
    # Bar 5: Enter Long at Open 100 + slippage = 100.10
    #        Target = 110.11, Stop = 95.095.
    # Bar 6: Low reaches 93 -> Stop loss fills at stop 95.095 - slippage = 94.995
    #
    # Bar 7: Long signal generated on close -> enter bar 8 at open
    # Bar 8: Enter Long at Open 100 + slippage = 100.10
    # Bar 9: Neither stop nor target hit
    # Bar 10 (idx 10): Time exit after 2 bars -> exit at bar 10 Open 102 - slippage = 101.90

    timestamps = pd.date_range("2024-01-01", periods=11, freq="4h")
    df = pd.DataFrame({
        "timestamp": timestamps,
        "open":  [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 102.0],
        "high":  [101.0, 101.0, 105.0, 112.0, 101.0, 102.0,  99.0, 101.0, 103.0, 103.0, 104.0],
        "low":   [ 99.0,  99.0,  98.0,  99.0,  99.0,  98.0,  93.0,  99.0,  98.0,  98.0, 101.0],
        "close": [100.0, 100.0, 104.0, 108.0, 100.0,  99.0,  94.0, 100.0, 102.0, 102.0, 103.0],
        "volume": [1000.0] * 11,
    })

    long_signals = np.zeros(11, dtype=bool)
    long_signals[1] = True  # Enters bar 2
    long_signals[4] = True  # Enters bar 5
    long_signals[7] = True  # Enters bar 8

    slippage_ticks = 10
    tick_size = 0.01  # slippage cost = 0.10
    initial_cap = 10000.0

    trades_df, equity = simulate(
        df,
        long_signals=long_signals,
        stop_pct=5.0,        # 5% stop
        target_pct=10.0,     # 10% target
        time_bars=2,         # 2 bar time exit
        commission_pct=0.001,  # 0.1%
        slippage_ticks=slippage_ticks,
        tick_size=tick_size,
        initial_capital=initial_cap,
    )

    assert len(trades_df) == 3

    # Trade 1: Target exit
    t1 = trades_df.iloc[0]
    assert t1["entry_bar"] == 2
    assert t1["exit_bar"] == 3
    assert np.isclose(t1["entry_price"], 100.10)
    assert np.isclose(t1["exit_price"], 100.10 * 1.10 - 0.10)
    assert t1["reason"] == "TARGET"

    # Trade 2: Stop exit
    t2 = trades_df.iloc[1]
    assert t2["entry_bar"] == 5
    assert t2["exit_bar"] == 6
    assert np.isclose(t2["entry_price"], 100.10)
    assert np.isclose(t2["exit_price"], 100.10 * 0.95 - 0.10)
    assert t2["reason"] == "STOP"

    # Trade 3: Time exit
    t3 = trades_df.iloc[2]
    assert t3["entry_bar"] == 8
    assert t3["exit_bar"] == 10
    assert np.isclose(t3["entry_price"], 100.10)
    assert np.isclose(t3["exit_price"], 102.0 - 0.10)
    assert t3["reason"] == "TIME"


def test_backtest_s012_v1_under_2_seconds():
    """Verify S-012 v1 backtest runs in under 2 seconds on sample data with valid trades."""
    spec_res = validate_spec_file("examples/specs/S-012/v1.yaml")
    assert spec_res.is_valid

    start_time = time.perf_counter()
    result = run_backtest(spec_res.spec, save_run=True)
    duration = time.perf_counter() - start_time

    assert duration < 2.0, f"Backtest took {duration:.2f}s, expected < 2.0s"
    assert result["trades_is_count"] > 0
    assert "in_sample" in Path(result["run_dir"]).joinpath("metrics.json").read_text()
