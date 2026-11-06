"""Parameter sweep scored on the in-sample window only."""

from __future__ import annotations

import itertools
import random
from typing import Any

import pandas as pd

from stratlab.engine.registry import save_research_run
from stratlab.engine.runner import Prepared, compute_signals, prepare, run_window
from stratlab.research.charter import load_charter
from stratlab.spec.models import StrategySpec

METRIC_COLS = ["trades", "net_profit_pct", "profit_factor", "win_rate_pct", "max_drawdown_pct", "sharpe_ratio"]


def param_grid(spec: StrategySpec) -> dict[str, list[Any]]:
    """Values for every tunable param (has a range and is not fixed)."""
    grid: dict[str, list[Any]] = {}
    for k, p in spec.params.items():
        if p.fixed or p.range is None:
            continue
        lo, hi, step = p.range
        n = int(round((hi - lo) / step))
        is_int = all(float(v).is_integer() for v in (lo, hi, step, p.default))
        vals = [lo + i * step for i in range(n + 1) if lo + i * step <= hi + 1e-9]
        grid[k] = [int(round(v)) for v in vals] if is_int else [round(float(v), 6) for v in vals]
    return grid


def _generate_param_combinations(spec: StrategySpec, budget: int = 200, seed: int = 42) -> list[dict[str, Any]]:
    """Full grid, or a seeded random sample of it when larger than `budget` (defaults always included)."""
    defaults = {k: p.default for k, p in spec.params.items()}
    grid = param_grid(spec)
    if not grid:
        return [defaults]
    keys = list(grid)
    combos = [dict(defaults, **dict(zip(keys, t))) for t in itertools.product(*grid.values())]
    if len(combos) > budget:
        rng = random.Random(seed)
        combos = rng.sample(combos, budget)
        if defaults not in combos:
            combos[-1] = defaults
    return combos


def evaluate_combo(spec: StrategySpec, prep: Prepared, combo: dict[str, Any], i0: int, i1: int,
                   signals=None) -> dict[str, Any]:
    row = dict(combo)
    try:
        sig = signals or compute_signals(spec, prep, combo)
        _, _, m = run_window(spec, prep, sig, combo, i0, i1)
        row.update({k: m[k] for k in METRIC_COLS})
    except Exception as e:  # a bad combo (e.g. length 0) is reported, not fatal
        row.update({"trades": 0, "net_profit_pct": 0.0, "profit_factor": 0.0, "win_rate_pct": 0.0,
                    "max_drawdown_pct": 0.0, "sharpe_ratio": 0.0, "error": str(e)})
    return row


def rank(df: pd.DataFrame, min_trades: int) -> pd.DataFrame:
    """Combos with enough trades first, by profit factor then net profit."""
    df = df.copy()
    df["eligible"] = df["trades"] >= min_trades
    return df.sort_values(["eligible", "profit_factor", "net_profit_pct"], ascending=[False, False, False]).reset_index(drop=True)


def run_sweep(spec: StrategySpec, budget: int = 200, n_jobs: int = 1, min_trades: int | None = None,
              save: bool = True) -> pd.DataFrame:
    """Evaluate up to `budget` combos on the in-sample window and save the ranking.

    Profit factor alone rewards a 2-trade fluke, so combos below `min_trades` (Lab Charter
    `sweep.min_trades`) are ranked last and never picked as best.
    """
    if budget < 1:
        raise ValueError("--budget must be at least 1")
    charter = load_charter()
    min_trades = int(min_trades if min_trades is not None else charter["sweep"]["min_trades"])
    prep = prepare(spec)
    combos = _generate_param_combinations(spec, budget=budget)
    rows = [evaluate_combo(spec, prep, c, prep.start, prep.split) for c in combos]
    df = rank(pd.DataFrame(rows), min_trades)

    grid = param_grid(spec)
    best = df.iloc[0]
    def py(v):
        return v.item() if hasattr(v, "item") else v

    best_params = {k: py(best[k]) for k in spec.params}
    summary = {
        "budget": budget,
        "evaluated": len(df),
        "grid_size": int(pd.Series([len(v) for v in grid.values()]).prod()) if grid else 1,
        "tunable": list(grid),
        "min_trades": min_trades,
        "eligible": int(df["eligible"].sum()),
        "best_params": best_params,
        "best_is": {k: py(best[k]) for k in METRIC_COLS},
        "best_is_eligible": bool(best["eligible"]),
    }
    if save:
        run_id, _ = save_research_run("sweep", spec, summary, files={"sweep.csv": df})
        df.attrs["run_id"] = run_id
    df.attrs["summary"] = summary
    return df
