"""One place that turns (spec, params, window) into trades and an equity curve.

Backtest, sweep, walk-forward, robustness and parity all call `run_window`, so they share
the same exit resolution, ATR lookup and indicator warm-up. Indicators are computed once on
the whole history up to the period end and then sliced, the way TradingView computes them on
the full chart, so an out-of-sample or walk-forward window never loses bars to warm-up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from stratlab.data.cache import load_ohlcv
from stratlab.engine.conditions import evaluate_condition_tree
from stratlab.engine.indicators import (
    atr,
    ema,
    evaluate_expression,
    highest,
    lowest,
    rma,
    rsi,
    sma,
    wma,
)
from stratlab.engine.metrics import compute_metrics
from stratlab.engine.sim import simulate
from stratlab.spec.models import StrategySpec


@dataclass
class Prepared:
    """History up to the period end plus the bar indices of the research windows."""

    df: pd.DataFrame
    start: int  # first bar inside spec.period
    end: int  # one past the last bar inside spec.period
    split: int  # first out-of-sample bar


def prepare(spec: StrategySpec, df: pd.DataFrame | None = None) -> Prepared:
    if df is None:
        df = load_ohlcv(spec.market.symbol, spec.market.timeframe)
    df = df.sort_values("timestamp").reset_index(drop=True)
    ts = pd.to_datetime(df["timestamp"])
    start_ts = pd.Timestamp(spec.period.start)
    end_ts = pd.Timestamp(spec.period.end) + pd.Timedelta(days=1)
    df = df[ts < end_ts].reset_index(drop=True)
    start = int((pd.to_datetime(df["timestamp"]) < start_ts).sum())
    end = len(df)
    if end - start < 100:
        raise ValueError(
            f"only {end - start} bars of {spec.market.symbol} {spec.market.timeframe} inside "
            f"{spec.period.start}..{spec.period.end}; need at least 100"
        )
    n = end - start
    split = start + int(round(n * (1.0 - spec.period.oos_fraction))) if spec.period.oos_fraction > 0 else end
    return Prepared(df=df, start=start, end=end, split=split)


def resolve(value: Any, params: dict[str, Any]) -> Any:
    """Replace a `$param` reference with its active value."""
    if isinstance(value, str) and value.startswith("$"):
        name = value[1:]
        if name not in params:
            raise ValueError(f"unknown parameter reference {value}")
        return params[name]
    return value


def atr_indicator_name(spec: StrategySpec) -> str | None:
    """Name of the first indicator with fn: atr (stops use it whatever it is called)."""
    for name, ind in spec.indicators.items():
        if ind.fn.lower() == "atr":
            return name
    return None


def active_params(spec: StrategySpec, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    params = {k: v.default for k, v in spec.params.items()}
    for k, v in (overrides or {}).items():
        if k not in params:
            raise ValueError(f"unknown parameter '{k}'. Known: {', '.join(params) or 'none'}")
        is_int = isinstance(spec.params[k].default, int) and not isinstance(spec.params[k].default, bool)
        params[k] = int(round(float(v))) if is_int else float(v)
    return params


def compute_context(df: pd.DataFrame, spec: StrategySpec, params: dict[str, Any]) -> dict[str, np.ndarray]:
    ctx: dict[str, np.ndarray] = {c: df[c].to_numpy(dtype=np.float64) for c in ("open", "high", "low", "close", "volume")}
    for name, ind in spec.indicators.items():
        fn = ind.fn.lower()
        src = ctx[ind.src or "close"] if fn != "atr" else None
        if fn == "expr":
            ctx[name] = evaluate_expression(ind.expr or "", ctx)
            continue
        length = int(resolve(ind.len, params)) if ind.len is not None else 14
        if length < 1:
            raise ValueError(f"indicator '{name}' length must be >= 1, got {length}")
        if fn == "sma":
            ctx[name] = sma(src, length)
        elif fn == "ema":
            ctx[name] = ema(src, length)
        elif fn == "wma":
            ctx[name] = wma(src, length)
        elif fn == "rma":
            ctx[name] = rma(src, length)
        elif fn == "rsi":
            ctx[name] = rsi(src, length)
        elif fn == "atr":
            ctx[name] = atr(ctx["high"], ctx["low"], ctx["close"], length)
        elif fn == "highest":
            ctx[name] = highest(ctx[ind.src or "high"], length)
        elif fn == "lowest":
            ctx[name] = lowest(ctx[ind.src or "low"], length)
        else:
            raise ValueError(f"indicator function '{fn}' is not supported by the engine")
    return ctx


@dataclass
class Signals:
    long: np.ndarray
    short: np.ndarray
    atr: np.ndarray | None
    ctx: dict[str, np.ndarray]


def compute_signals(spec: StrategySpec, prep: Prepared, params: dict[str, Any]) -> Signals:
    ctx = compute_context(prep.df, spec, params)
    n = len(prep.df)
    long_sig = evaluate_condition_tree(spec.entry.long, ctx, n) if spec.entry.long else np.zeros(n, dtype=bool)
    short_sig = evaluate_condition_tree(spec.entry.short, ctx, n) if spec.entry.short else np.zeros(n, dtype=bool)
    name = atr_indicator_name(spec)
    return Signals(long=long_sig, short=short_sig, atr=ctx.get(name) if name else None, ctx=ctx)


def exit_settings(spec: StrategySpec, params: dict[str, Any]) -> dict[str, Any]:
    out = {"stop_atr_mult": 0.0, "stop_pct": 0.0, "target_atr_mult": 0.0, "target_pct": 0.0,
           "time_bars": 0, "opposite_exit": bool(spec.exit.opposite_signal)}
    if spec.exit.stop:
        if spec.exit.stop.atr_mult is not None:
            out["stop_atr_mult"] = float(resolve(spec.exit.stop.atr_mult, params))
        elif spec.exit.stop.pct is not None:
            out["stop_pct"] = float(resolve(spec.exit.stop.pct, params))
    if spec.exit.target:
        if spec.exit.target.atr_mult is not None:
            out["target_atr_mult"] = float(resolve(spec.exit.target.atr_mult, params))
        elif spec.exit.target.pct is not None:
            out["target_pct"] = float(resolve(spec.exit.target.pct, params))
    if spec.exit.time and spec.exit.time.bars is not None:
        out["time_bars"] = int(resolve(spec.exit.time.bars, params))
    return out


def run_window(
    spec: StrategySpec,
    prep: Prepared,
    sig: Signals,
    params: dict[str, Any],
    i0: int,
    i1: int,
    cost_mult: float = 1.0,
) -> tuple[pd.DataFrame, np.ndarray, dict[str, Any]]:
    """Simulate bars [i0, i1) starting flat. Returns (trades, equity, metrics)."""
    window = prep.df.iloc[i0:i1].reset_index(drop=True)
    exits = exit_settings(spec, params)
    trades, equity = simulate(
        window,
        long_signals=sig.long[i0:i1],
        short_signals=sig.short[i0:i1],
        atr_series=sig.atr[i0:i1] if sig.atr is not None else None,
        commission_pct=spec.costs.commission_pct * cost_mult / 100.0,
        slippage_ticks=spec.costs.slippage_ticks * cost_mult,
        tick_size=spec.costs.tick_size,
        initial_capital=spec.risk.initial_capital,
        **exits,
    )
    if len(trades):
        trades["entry_bar"] = trades["entry_bar"] + i0
        trades["exit_bar"] = trades["exit_bar"] + i0
    metrics = compute_metrics(
        trades, equity, initial_capital=spec.risk.initial_capital,
        timeframe=spec.market.timeframe, total_bars=i1 - i0,
    )
    return trades, equity, metrics


def evaluate(spec: StrategySpec, prep: Prepared, params: dict[str, Any], cost_mult: float = 1.0) -> dict[str, Any]:
    """IS, OOS and full-window results for one parameter set."""
    sig = compute_signals(spec, prep, params)
    out: dict[str, Any] = {"params": params}
    for label, (i0, i1) in {"is": (prep.start, prep.split), "oos": (prep.split, prep.end),
                            "full": (prep.start, prep.end)}.items():
        if i1 - i0 < 10:
            out[label] = None
            continue
        trades, equity, metrics = run_window(spec, prep, sig, params, i0, i1, cost_mult)
        out[label] = {"trades": trades, "equity": equity, "metrics": metrics, "i0": i0, "i1": i1}
    return out
