"""Robustness battery on the candidate parameters: Monte Carlo, cost stress, neighbourhood."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from stratlab.engine.registry import latest_research_run, save_research_run
from stratlab.engine.runner import active_params, compute_signals, prepare, run_window
from stratlab.research.charter import load_charter
from stratlab.research.sweep import param_grid
from stratlab.spec.models import StrategySpec


def candidate_params(spec: StrategySpec, overrides: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    """The parameter set under review, and where it came from.

    1. explicit `--params` overrides, else
    2. the best combo of the latest sweep of this exact spec (what the Backtester would ship), else
    3. the spec defaults.
    """
    if overrides:
        return active_params(spec, overrides), "explicit"
    sweep = latest_research_run("sweep", spec)
    if sweep and sweep.get("best_params"):
        return active_params(spec, sweep["best_params"]), f"sweep:{sweep['run_id']}"
    return active_params(spec), "defaults"


def run_monte_carlo_bootstrap(trades_df: pd.DataFrame, initial_capital: float = 10000.0,
                              n_simulations: int = 1000, seed: int = 42) -> dict[str, Any]:
    """Resample the per-trade returns with replacement and compound them (100% equity sizing)."""
    if len(trades_df) == 0:
        return {"n_simulations": n_simulations, "n_trades": 0, "pct_95th_max_drawdown": 0.0,
                "pct_5th_final_equity": initial_capital, "pct_50th_final_equity": initial_capital}
    if "return_pct" in trades_df:
        rets = trades_df["return_pct"].to_numpy(dtype=np.float64) / 100.0
    else:  # only currency P&L: turn it into returns on the running equity
        eq = initial_capital + np.concatenate([[0.0], np.cumsum(trades_df["pnl"].to_numpy(dtype=np.float64))[:-1]])
        rets = trades_df["pnl"].to_numpy(dtype=np.float64) / eq
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(rets), size=(n_simulations, len(rets)))
    growth = np.cumprod(1.0 + rets[idx], axis=1)
    curves = np.hstack([np.ones((n_simulations, 1)), growth]) * initial_capital
    peaks = np.maximum.accumulate(curves, axis=1)
    max_dd = ((peaks - curves) / peaks * 100.0).max(axis=1)
    finals = curves[:, -1]
    return {
        "n_simulations": n_simulations,
        "n_trades": int(len(rets)),
        "pct_95th_max_drawdown": round(float(np.percentile(max_dd, 95)), 2),
        "pct_5th_final_equity": round(float(np.percentile(finals, 5)), 2),
        "pct_50th_final_equity": round(float(np.percentile(finals, 50)), 2),
    }


def run_cost_stress_test(spec: StrategySpec, params: dict[str, Any], multiplier: float = 2.0, prep=None,
                         sig=None) -> dict[str, Any]:
    prep = prep or prepare(spec)
    sig = sig or compute_signals(spec, prep, params)
    _, _, m_is = run_window(spec, prep, sig, params, prep.start, prep.split, cost_mult=multiplier)
    _, _, m_oos = run_window(spec, prep, sig, params, prep.split, prep.end, cost_mult=multiplier)
    _, _, m_full = run_window(spec, prep, sig, params, prep.start, prep.end, cost_mult=multiplier)
    return {
        "multiplier": multiplier,
        "stressed_commission_pct": spec.costs.commission_pct * multiplier,
        "stressed_slippage_ticks": spec.costs.slippage_ticks * multiplier,
        "in_sample_pf": m_is["profit_factor"],
        "out_of_sample_pf": m_oos["profit_factor"],
        "full_period_pf": m_full["profit_factor"],
        "full_period_net_pct": m_full["net_profit_pct"],
    }


def run_parameter_neighbourhood_test(spec: StrategySpec, params: dict[str, Any], prep=None) -> dict[str, Any]:
    """Move each tunable param one grid step either way and compare in-sample profit factor."""
    prep = prep or prepare(spec)
    grid = param_grid(spec)
    sig = compute_signals(spec, prep, params)
    _, _, base = run_window(spec, prep, sig, params, prep.start, prep.split)
    best_pf = base["profit_factor"]
    if not grid:
        return {"tested_neighbours": 0, "neighbours": [], "best_pf": best_pf, "median_neighbour_pf": None,
                "stability_ratio": None, "note": "no tunable params, nothing to perturb"}
    neighbours = []
    for name, values in grid.items():
        cur = params[name]
        pos = int(np.argmin([abs(v - cur) for v in values]))
        for j in (pos - 1, pos + 1):
            if 0 <= j < len(values):
                p = dict(params)
                p[name] = values[j]
                s = compute_signals(spec, prep, p)
                _, _, m = run_window(spec, prep, s, p, prep.start, prep.split)
                neighbours.append({"param": name, "value": values[j], "pf": m["profit_factor"], "trades": m["trades"]})
    pfs = [n["pf"] for n in neighbours]
    median = float(np.median(pfs)) if pfs else best_pf
    return {
        "tested_neighbours": len(neighbours),
        "neighbours": neighbours,
        "best_pf": round(best_pf, 2),
        "median_neighbour_pf": round(median, 2),
        "stability_ratio": round(median / best_pf, 2) if best_pf > 0 else 0.0,
    }


def run_robustness_battery(spec: StrategySpec, param_overrides: dict[str, Any] | None = None,
                           save: bool = True, run_id: str | None = None) -> dict[str, Any]:
    charter = load_charter()
    params, source = candidate_params(spec, param_overrides)
    prep = prepare(spec)
    sig = compute_signals(spec, prep, params)
    trades, _, _ = run_window(spec, prep, sig, params, prep.start, prep.end)
    result = {
        "params": params,
        "params_source": source,
        "monte_carlo": run_monte_carlo_bootstrap(trades, spec.risk.initial_capital,
                                                 n_simulations=int(charter["g6_tail_risk"]["mc_runs"])),
        "cost_stress": run_cost_stress_test(spec, params, charter["g5_costs"]["cost_multiplier"], prep, sig),
        "neighbourhood": run_parameter_neighbourhood_test(spec, params, prep),
    }
    if save:
        rid, _ = save_research_run("robust", spec, result)
        result["run_id"] = rid
    return result
