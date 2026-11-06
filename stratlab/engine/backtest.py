"""Backtest orchestration engine compiling spec to simulation runs."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from stratlab.config import get_registry_db, get_runs_dir
from stratlab.data.cache import load_ohlcv
from stratlab.engine.conditions import evaluate_condition_tree
from stratlab.engine.indicators import (
    atr,
    bb,
    donchian,
    ema,
    evaluate_expression,
    highest,
    lowest,
    macd,
    rma,
    rsi,
    sma,
    wma,
)
from stratlab.engine.metrics import compute_metrics
from stratlab.engine.sim import simulate
from stratlab.spec.models import StrategySpec


def init_registry_db() -> Path:
    """Initialize the SQLite registry database table if not exists."""
    db_path = get_registry_db()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                spec_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                split TEXT NOT NULL,
                trades INTEGER NOT NULL,
                net_profit_pct REAL NOT NULL,
                profit_factor REAL NOT NULL,
                max_drawdown_pct REAL NOT NULL,
                win_rate_pct REAL NOT NULL,
                sharpe_ratio REAL NOT NULL,
                params_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    return db_path


def _record_run_in_registry(
    run_id: str,
    spec_id: str,
    version: int,
    split: str,
    metrics: dict[str, Any],
    params: dict[str, Any],
) -> None:
    """Save run summary row to SQLite registry."""
    db_path = init_registry_db()
    now_iso = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO runs (
                run_id, spec_id, version, split, trades,
                net_profit_pct, profit_factor, max_drawdown_pct,
                win_rate_pct, sharpe_ratio, params_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                spec_id,
                version,
                split,
                metrics["trades"],
                metrics["net_profit_pct"],
                metrics["profit_factor"],
                metrics["max_drawdown_pct"],
                metrics["win_rate_pct"],
                metrics["sharpe_ratio"],
                json.dumps(params),
                now_iso,
            ),
        )
        conn.commit()


def _resolve_param_val(val: Any, active_params: dict[str, Any]) -> Any:
    """Replace $param references with active parameter values."""
    if isinstance(val, str) and val.startswith("$"):
        param_name = val[1:]
        if param_name in active_params:
            return active_params[param_name]
    return val


def compute_indicator_context(
    df: pd.DataFrame,
    spec: StrategySpec,
    active_params: dict[str, Any],
) -> dict[str, np.ndarray]:
    """Compute all indicator series declared in the StrategySpec."""
    context: dict[str, np.ndarray] = {
        "open": df["open"].to_numpy(dtype=np.float64),
        "high": df["high"].to_numpy(dtype=np.float64),
        "low": df["low"].to_numpy(dtype=np.float64),
        "close": df["close"].to_numpy(dtype=np.float64),
        "volume": df["volume"].to_numpy(dtype=np.float64),
    }

    for name, ind in spec.indicators.items():
        src_name = ind.src or "close"
        src_series = context.get(src_name, context["close"])
        fn = ind.fn.lower()

        # Resolve length/periods
        raw_len = _resolve_param_val(ind.len, active_params)
        length = int(raw_len) if raw_len is not None else 14

        if fn == "sma":
            context[name] = sma(src_series, length)
        elif fn == "ema":
            context[name] = ema(src_series, length)
        elif fn == "wma":
            context[name] = wma(src_series, length)
        elif fn == "rma":
            context[name] = rma(src_series, length)
        elif fn == "rsi":
            context[name] = rsi(src_series, length)
        elif fn == "atr":
            context[name] = atr(context["high"], context["low"], context["close"], length)
        elif fn == "highest":
            context[name] = highest(src_series, length)
        elif fn == "lowest":
            context[name] = lowest(src_series, length)
        elif fn == "bb":
            raw_mult = _resolve_param_val(ind.mult, active_params)
            mult = float(raw_mult) if raw_mult is not None else 2.0
            upper, basis, lower = bb(src_series, length, mult)
            context[f"{name}_upper"] = upper
            context[f"{name}_basis"] = basis
            context[f"{name}_lower"] = lower
            context[name] = basis
        elif fn == "donchian":
            upper, lower = donchian(context["high"], context["low"], length)
            context[f"{name}_upper"] = upper
            context[f"{name}_lower"] = lower
            context[name] = upper
        elif fn == "macd":
            fast = int(_resolve_param_val(ind.fast, active_params) or 12)
            slow = int(_resolve_param_val(ind.slow, active_params) or 26)
            sig = int(_resolve_param_val(ind.signal, active_params) or 9)
            m_line, s_line, hist = macd(src_series, fast, slow, sig)
            context[f"{name}_line"] = m_line
            context[f"{name}_signal"] = s_line
            context[f"{name}_hist"] = hist
            context[name] = m_line
        elif fn == "expr":
            if ind.expr:
                context[name] = evaluate_expression(ind.expr, context)
            else:
                context[name] = src_series
        else:
            raise ValueError(f"Indicator function '{fn}' not implemented")

    return context


def run_backtest(
    spec: StrategySpec,
    param_overrides: dict[str, Any] | None = None,
    save_run: bool = True,
) -> dict[str, Any]:
    """Execute complete in-sample and out-of-sample backtest for a StrategySpec."""
    # 1. Resolve active parameters
    active_params: dict[str, Any] = {k: v.default for k, v in spec.params.items()}
    if param_overrides:
        active_params.update(param_overrides)

    # 2. Load historical OHLCV data
    df = load_ohlcv(
        spec.market.symbol,
        spec.market.timeframe,
        start_date=str(spec.period.start),
        end_date=str(spec.period.end),
    )

    n_total = len(df)
    if n_total < 30:
        raise ValueError(f"Insufficient bars for backtest: {n_total} bars found")

    # 3. Calculate In-Sample / Out-of-Sample split
    oos_fraction = spec.period.oos_fraction
    split_idx = int(n_total * (1.0 - oos_fraction)) if oos_fraction > 0 else n_total

    df_is = df.iloc[:split_idx].reset_index(drop=True)
    df_oos = df.iloc[split_idx:].reset_index(drop=True) if oos_fraction > 0 else pd.DataFrame()

    # 4. Resolve stop and target multiples
    stop_atr_mult = 0.0
    stop_pct = 0.0
    if spec.exit.stop:
        if spec.exit.stop.atr_mult:
            stop_atr_mult = float(_resolve_param_val(spec.exit.stop.atr_mult, active_params))
        elif spec.exit.stop.pct:
            stop_pct = float(_resolve_param_val(spec.exit.stop.pct, active_params))

    target_atr_mult = 0.0
    target_pct = 0.0
    if spec.exit.target:
        if spec.exit.target.atr_mult:
            target_atr_mult = float(_resolve_param_val(spec.exit.target.atr_mult, active_params))
        elif spec.exit.target.pct:
            target_pct = float(_resolve_param_val(spec.exit.target.pct, active_params))

    time_bars = int(spec.exit.time.bars) if spec.exit.time and spec.exit.time.bars else 0
    opposite_exit = bool(spec.exit.opposite_signal)
    comm_pct = spec.costs.commission_pct / 100.0  # e.g. 0.1% -> 0.001

    # 5. Run In-Sample
    ctx_is = compute_indicator_context(df_is, spec, active_params)
    long_sig_is = evaluate_condition_tree(spec.entry.long, ctx_is, len(df_is)) if spec.entry.long else np.zeros(len(df_is), dtype=bool)
    short_sig_is = evaluate_condition_tree(spec.entry.short, ctx_is, len(df_is)) if spec.entry.short else np.zeros(len(df_is), dtype=bool)
    atr_series_is = ctx_is.get("atr")

    trades_is, eq_is = simulate(
        df_is,
        long_signals=long_sig_is,
        short_signals=short_sig_is,
        atr_series=atr_series_is,
        stop_atr_mult=stop_atr_mult,
        target_atr_mult=target_atr_mult,
        stop_pct=stop_pct,
        target_pct=target_pct,
        time_bars=time_bars,
        opposite_exit=opposite_exit,
        commission_pct=comm_pct,
        slippage_ticks=spec.costs.slippage_ticks,
        tick_size=spec.costs.tick_size,
        initial_capital=spec.risk.initial_capital,
    )
    metrics_is = compute_metrics(
        trades_is,
        eq_is,
        initial_capital=spec.risk.initial_capital,
        timeframe=spec.market.timeframe,
        total_bars=len(df_is),
    )

    # 6. Run Out-of-Sample if split exists
    metrics_oos: dict[str, Any] = {}
    trades_oos = pd.DataFrame()
    eq_oos = np.array([])
    if not df_oos.empty and len(df_oos) > 10:
        ctx_oos = compute_indicator_context(df_oos, spec, active_params)
        long_sig_oos = evaluate_condition_tree(spec.entry.long, ctx_oos, len(df_oos)) if spec.entry.long else np.zeros(len(df_oos), dtype=bool)
        short_sig_oos = evaluate_condition_tree(spec.entry.short, ctx_oos, len(df_oos)) if spec.entry.short else np.zeros(len(df_oos), dtype=bool)
        atr_series_oos = ctx_oos.get("atr")

        trades_oos, eq_oos = simulate(
            df_oos,
            long_signals=long_sig_oos,
            short_signals=short_sig_oos,
            atr_series=atr_series_oos,
            stop_atr_mult=stop_atr_mult,
            target_atr_mult=target_atr_mult,
            stop_pct=stop_pct,
            target_pct=target_pct,
            time_bars=time_bars,
            opposite_exit=opposite_exit,
            commission_pct=comm_pct,
            slippage_ticks=spec.costs.slippage_ticks,
            tick_size=spec.costs.tick_size,
            initial_capital=spec.risk.initial_capital,
        )
        metrics_oos = compute_metrics(
            trades_oos,
            eq_oos,
            initial_capital=spec.risk.initial_capital,
            timeframe=spec.market.timeframe,
            total_bars=len(df_oos),
        )

    # 7. Persist run results
    timestamp_tag = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_id = f"run_{spec.id}_v{spec.version}_{timestamp_tag}"

    if save_run:
        run_dir = get_runs_dir() / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # Save metrics.json
        full_metrics = {
            "run_id": run_id,
            "spec_id": spec.id,
            "version": spec.version,
            "market": spec.market.model_dump(),
            "params": active_params,
            "in_sample": metrics_is,
            "out_of_sample": metrics_oos,
        }
        with open(run_dir / "metrics.json", "w", encoding="utf-8") as f:
            json.dump(full_metrics, f, indent=2)

        # Save trades.csv
        combined_trades = pd.concat([
            trades_is.assign(split="IS"),
            trades_oos.assign(split="OOS"),
        ], ignore_index=True)
        combined_trades.to_csv(run_dir / "trades.csv", index=False)

        # Record in SQLite registry
        _record_run_in_registry(f"{run_id}_is", spec.id, spec.version, "IS", metrics_is, active_params)
        if metrics_oos:
            _record_run_in_registry(f"{run_id}_oos", spec.id, spec.version, "OOS", metrics_oos, active_params)

    return {
        "run_id": run_id,
        "spec_id": spec.id,
        "version": spec.version,
        "params": active_params,
        "is": metrics_is,
        "oos": metrics_oos,
        "trades_is_count": len(trades_is),
        "trades_oos_count": len(trades_oos),
        "run_dir": str(get_runs_dir() / run_id) if save_run else None,
    }
