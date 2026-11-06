"""Robustness testing: Monte Carlo trade bootstrap, cost stress, and parameter neighbourhood."""

import json
from typing import Any

import numpy as np
import pandas as pd

from stratlab.config import get_runs_dir
from stratlab.engine.backtest import run_backtest
from stratlab.spec.models import StrategySpec


def run_monte_carlo_bootstrap(
    trades_df: pd.DataFrame,
    initial_capital: float = 10000.0,
    n_simulations: int = 1000,
    seed: int = 42,
) -> dict[str, Any]:
    """Resample trades with replacement 1,000 times to estimate tail risk."""
    if len(trades_df) == 0:
        return {
            "n_simulations": n_simulations,
            "pct_5th_final_equity": initial_capital,
            "pct_50th_final_equity": initial_capital,
            "pct_95th_max_drawdown": 0.0,
        }

    np.random.seed(seed)
    pnls = trades_df["pnl"].to_numpy()
    n_trades = len(pnls)

    final_equities = np.empty(n_simulations, dtype=np.float64)
    max_drawdowns = np.empty(n_simulations, dtype=np.float64)

    for i in range(n_simulations):
        # Sample trade indices with replacement
        sampled_indices = np.random.choice(n_trades, size=n_trades, replace=True)
        sampled_pnls = pnls[sampled_indices]

        # Reconstruct equity curve
        eq = np.empty(n_trades + 1, dtype=np.float64)
        eq[0] = initial_capital
        curr = initial_capital
        for t in range(n_trades):
            curr += sampled_pnls[t]
            eq[t + 1] = max(curr, 0.0)

        final_equities[i] = eq[-1]

        # Max drawdown of sampled curve
        peaks = np.maximum.accumulate(eq)
        dds = (peaks - eq) / np.where(peaks > 0, peaks, 1.0) * 100.0
        max_drawdowns[i] = np.max(dds)

    pct_95th_max_dd = float(np.percentile(max_drawdowns, 95))
    pct_5th_final_equity = float(np.percentile(final_equities, 5))
    pct_50th_final_equity = float(np.percentile(final_equities, 50))

    return {
        "n_simulations": n_simulations,
        "pct_95th_max_drawdown": round(pct_95th_max_dd, 2),
        "pct_5th_final_equity": round(pct_5th_final_equity, 2),
        "pct_50th_final_equity": round(pct_50th_final_equity, 2),
    }


def run_cost_stress_test(
    spec: StrategySpec,
    active_params: dict[str, Any],
) -> dict[str, Any]:
    """Test strategy resilience with 2x commission and 2x slippage."""
    stressed_spec = spec.model_copy(deep=True)
    stressed_spec.costs.commission_pct *= 2.0
    stressed_spec.costs.slippage_ticks *= 2

    res = run_backtest(stressed_spec, param_overrides=active_params, save_run=False)
    m_is = res["is"]
    m_oos = res.get("oos", {})

    return {
        "stressed_commission_pct": stressed_spec.costs.commission_pct,
        "stressed_slippage_ticks": stressed_spec.costs.slippage_ticks,
        "in_sample_pf": m_is.get("profit_factor", 0.0),
        "in_sample_net_pct": m_is.get("net_profit_pct", 0.0),
        "out_of_sample_pf": m_oos.get("profit_factor", 0.0),
        "out_of_sample_net_pct": m_oos.get("net_profit_pct", 0.0),
    }


def run_parameter_neighbourhood_test(
    spec: StrategySpec,
    best_params: dict[str, Any],
) -> dict[str, Any]:
    """Perturb tunable parameters by +/- 1 step along each axis to verify plateau stability."""
    tunable_params = {k: v for k, v in spec.params.items() if not v.fixed and v.range is not None}
    if not tunable_params:
        return {
            "tested_neighbours": 0,
            "median_neighbour_pf": best_params.get("profit_factor", 1.5),
            "stability_ratio": 1.0,
        }

    # Evaluate baseline best params
    baseline_res = run_backtest(spec, param_overrides=best_params, save_run=False)
    best_pf = baseline_res["is"]["profit_factor"]

    neighbour_pfs = []

    for param_name, cfg in tunable_params.items():
        min_v, max_v, step = cfg.range
        curr_val = best_params.get(param_name, cfg.default)

        # Step up
        val_up = curr_val + step
        if val_up <= max_v:
            p_copy = dict(best_params)
            p_copy[param_name] = int(val_up) if isinstance(step, int) else round(val_up, 4)
            res_up = run_backtest(spec, param_overrides=p_copy, save_run=False)
            neighbour_pfs.append(res_up["is"]["profit_factor"])

        # Step down
        val_down = curr_val - step
        if val_down >= min_v:
            p_copy = dict(best_params)
            p_copy[param_name] = int(val_down) if isinstance(step, int) else round(val_down, 4)
            res_down = run_backtest(spec, param_overrides=p_copy, save_run=False)
            neighbour_pfs.append(res_down["is"]["profit_factor"])

    if not neighbour_pfs:
        neighbour_pfs = [best_pf]

    median_neighbour_pf = float(np.median(neighbour_pfs))
    stability_ratio = round(median_neighbour_pf / best_pf, 2) if best_pf > 0 else 0.0

    return {
        "tested_neighbours": len(neighbour_pfs),
        "neighbour_pfs": neighbour_pfs,
        "median_neighbour_pf": round(median_neighbour_pf, 2),
        "best_pf": round(best_pf, 2),
        "stability_ratio": stability_ratio,
    }


def run_robustness_battery(
    spec: StrategySpec,
    run_id: str | None = None,
    save: bool = True,
) -> dict[str, Any]:
    """Execute full robustness suite: Monte Carlo, cost stress, and parameter neighborhood."""
    # Run backtest to obtain baseline trades
    res = run_backtest(spec, save_run=True)
    actual_run_id = run_id or res["run_id"]
    active_params = res["params"]

    # Load trades from run
    run_dir = get_runs_dir() / actual_run_id
    trades_path = run_dir / "trades.csv"
    if trades_path.exists():
        trades_df = pd.read_csv(trades_path)
    else:
        trades_df = pd.DataFrame()

    # 1. Monte Carlo
    mc_results = run_monte_carlo_bootstrap(trades_df, initial_capital=spec.risk.initial_capital)

    # 2. Cost Stress
    cost_results = run_cost_stress_test(spec, active_params)

    # 3. Parameter Neighborhood
    neigh_results = run_parameter_neighbourhood_test(spec, active_params)

    robust_data = {
        "run_id": actual_run_id,
        "spec_id": spec.id,
        "version": spec.version,
        "monte_carlo": mc_results,
        "cost_stress": cost_results,
        "neighbourhood": neigh_results,
    }

    if save and run_dir.exists():
        with open(run_dir / "robust.json", "w", encoding="utf-8") as f:
            json.dump(robust_data, f, indent=2)

    return robust_data
