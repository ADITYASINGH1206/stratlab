"""Parameter sweep and optimization engine using joblib process pools."""

import itertools
import random
from typing import Any

import joblib
import numpy as np
import pandas as pd

from stratlab.data.cache import load_ohlcv
from stratlab.engine.backtest import compute_indicator_context
from stratlab.engine.conditions import evaluate_condition_tree
from stratlab.engine.metrics import compute_metrics
from stratlab.engine.sim import simulate
from stratlab.spec.models import StrategySpec


def _generate_param_combinations(
    spec: StrategySpec,
    budget: int = 200,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Generate combinations for all parameters that have a range defined."""
    tunable = {}
    fixed = {}

    for k, p in spec.params.items():
        if p.fixed or p.range is None:
            fixed[k] = p.default
        else:
            min_v, max_v, step = p.range
            # Determine int vs float
            if isinstance(min_v, int) and isinstance(max_v, int) and isinstance(step, int):
                vals = list(range(min_v, max_v + 1, step))
            else:
                n_steps = int(round((max_v - min_v) / step)) + 1
                vals = [round(min_v + i * step, 4) for i in range(n_steps)]
            tunable[k] = vals

    if not tunable:
        return [fixed]

    keys = list(tunable.keys())
    value_lists = [tunable[k] for k in keys]
    total_grid = list(itertools.product(*value_lists))

    if len(total_grid) > budget:
        random.seed(seed)
        sampled_tuples = random.sample(total_grid, budget)
    else:
        sampled_tuples = total_grid

    combos = []
    for t in sampled_tuples:
        c = dict(fixed)
        for k, v in zip(keys, t):
            c[k] = v
        combos.append(c)

    return combos


def _evaluate_single_combo(
    spec: StrategySpec,
    df_is: pd.DataFrame,
    combo_params: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate one parameter combination on in-sample data slice."""
    try:
        ctx = compute_indicator_context(df_is, spec, combo_params)
        long_sig = evaluate_condition_tree(spec.entry.long, ctx, len(df_is)) if spec.entry.long else np.zeros(len(df_is), dtype=bool)
        short_sig = evaluate_condition_tree(spec.entry.short, ctx, len(df_is)) if spec.entry.short else np.zeros(len(df_is), dtype=bool)
        atr_series = ctx.get("atr")

        # Resolve exits
        stop_atr_mult = 0.0
        stop_pct = 0.0
        if spec.exit.stop:
            if spec.exit.stop.atr_mult:
                raw = spec.exit.stop.atr_mult
                stop_atr_mult = float(combo_params.get(raw[1:], raw) if isinstance(raw, str) and raw.startswith("$") else raw)
            elif spec.exit.stop.pct:
                raw = spec.exit.stop.pct
                stop_pct = float(combo_params.get(raw[1:], raw) if isinstance(raw, str) and raw.startswith("$") else raw)

        target_atr_mult = 0.0
        target_pct = 0.0
        if spec.exit.target:
            if spec.exit.target.atr_mult:
                raw = spec.exit.target.atr_mult
                target_atr_mult = float(combo_params.get(raw[1:], raw) if isinstance(raw, str) and raw.startswith("$") else raw)
            elif spec.exit.target.pct:
                raw = spec.exit.target.pct
                target_pct = float(combo_params.get(raw[1:], raw) if isinstance(raw, str) and raw.startswith("$") else raw)

        time_bars = int(spec.exit.time.bars) if spec.exit.time and spec.exit.time.bars else 0
        opposite_exit = bool(spec.exit.opposite_signal)
        comm_pct = spec.costs.commission_pct / 100.0

        trades, eq = simulate(
            df_is,
            long_signals=long_sig,
            short_signals=short_sig,
            atr_series=atr_series,
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

        metrics = compute_metrics(
            trades,
            eq,
            initial_capital=spec.risk.initial_capital,
            timeframe=spec.market.timeframe,
            total_bars=len(df_is),
        )

        res = dict(combo_params)
        res.update({
            "trades": metrics["trades"],
            "net_profit_pct": metrics["net_profit_pct"],
            "profit_factor": metrics["profit_factor"],
            "win_rate_pct": metrics["win_rate_pct"],
            "max_drawdown_pct": metrics["max_drawdown_pct"],
            "sharpe_ratio": metrics["sharpe_ratio"],
        })
        return res
    except Exception as e:
        res = dict(combo_params)
        res.update({
            "trades": 0,
            "net_profit_pct": -99.9,
            "profit_factor": 0.0,
            "win_rate_pct": 0.0,
            "max_drawdown_pct": 100.0,
            "sharpe_ratio": -9.9,
            "error": str(e),
        })
        return res


def run_sweep(
    spec: StrategySpec,
    budget: int = 200,
    n_jobs: int = -1,
) -> pd.DataFrame:
    """Execute grid or random parameter sweep scored on the In-Sample slice."""
    df = load_ohlcv(
        spec.market.symbol,
        spec.market.timeframe,
        start_date=str(spec.period.start),
        end_date=str(spec.period.end),
    )

    oos_fraction = spec.period.oos_fraction
    split_idx = int(len(df) * (1.0 - oos_fraction)) if oos_fraction > 0 else len(df)
    df_is = df.iloc[:split_idx].reset_index(drop=True)

    combos = _generate_param_combinations(spec, budget=budget)

    # Run in parallel
    results = joblib.Parallel(n_jobs=n_jobs)(
        joblib.delayed(_evaluate_single_combo)(spec, df_is, c) for c in combos
    )

    results_df = pd.DataFrame(results)
    # Sort by profit_factor descending, with tie break on net_profit_pct
    results_df = results_df.sort_values(
        by=["profit_factor", "net_profit_pct"], ascending=[False, False]
    ).reset_index(drop=True)

    return results_df
