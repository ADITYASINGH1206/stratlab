"""Rolling walk-forward: re-optimise on each in-sample window, trade the next window blind."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta

from stratlab.engine.registry import save_research_run
from stratlab.engine.runner import compute_signals, prepare, run_window
from stratlab.research.charter import load_charter
from stratlab.research.sweep import _generate_param_combinations
from stratlab.spec.models import StrategySpec


def _annualised(net_pct: float, months: float) -> float:
    growth = 1.0 + net_pct / 100.0
    if growth <= 0:
        return -100.0
    return (growth ** (12.0 / months) - 1.0) * 100.0


def run_walkforward(
    spec: StrategySpec,
    is_months: int | None = None,
    oos_months: int | None = None,
    step_months: int | None = None,
    sweep_budget: int | None = None,
    min_trades: int | None = None,
    save: bool = True,
) -> dict[str, Any]:
    """Walk-forward efficiency (WFE) = mean annualised OOS return / mean annualised IS return.

    This is the usual (Pardo) definition: 1.0 means the blind windows earned at the same rate
    as the optimised ones. If the optimised windows lose money, WFE is reported as 0.
    """
    wf_cfg = load_charter()["walk_forward"]
    is_months = is_months or wf_cfg["is_months"]
    oos_months = oos_months or wf_cfg["oos_months"]
    step_months = step_months or wf_cfg["step_months"]
    sweep_budget = sweep_budget or wf_cfg["budget"]
    min_trades = wf_cfg["min_trades"] if min_trades is None else min_trades

    prep = prepare(spec)
    ts = pd.to_datetime(prep.df["timestamp"])
    first, last = ts.iloc[prep.start], ts.iloc[prep.end - 1]

    combos = _generate_param_combinations(spec, budget=sweep_budget)
    signals = [compute_signals(spec, prep, c) for c in combos]
    defaults = {k: p.default for k, p in spec.params.items()}

    windows: list[dict[str, Any]] = []
    is_start = first
    while True:
        is_end = is_start + relativedelta(months=is_months)
        oos_end = is_end + relativedelta(months=oos_months)
        if oos_end > last + pd.Timedelta(days=1):
            break
        i0 = int(np.searchsorted(ts.values, np.datetime64(is_start)))
        i1 = int(np.searchsorted(ts.values, np.datetime64(is_end)))
        i2 = int(np.searchsorted(ts.values, np.datetime64(oos_end)))
        if i1 - i0 < 50 or i2 - i1 < 10:
            is_start += relativedelta(months=step_months)
            continue

        best_idx, best_key = None, None
        for idx, combo in enumerate(combos):
            _, _, m = run_window(spec, prep, signals[idx], combo, i0, i1)
            if m["trades"] < min_trades:
                continue
            key = (m["profit_factor"], m["net_profit_pct"])
            if best_key is None or key > best_key:
                best_idx, best_key = idx, key
        if best_idx is None:  # nothing traded enough: fall back to defaults, flagged
            combo, sig, picked = defaults, compute_signals(spec, prep, defaults), False
        else:
            combo, sig, picked = combos[best_idx], signals[best_idx], True

        _, _, m_is = run_window(spec, prep, sig, combo, i0, i1)
        _, _, m_oos = run_window(spec, prep, sig, combo, i1, i2)
        windows.append({
            "window": len(windows) + 1,
            "is_start": is_start.strftime("%Y-%m-%d"),
            "is_end": is_end.strftime("%Y-%m-%d"),
            "oos_start": is_end.strftime("%Y-%m-%d"),
            "oos_end": oos_end.strftime("%Y-%m-%d"),
            "best_params": combo,
            "optimised": picked,
            "is_trades": m_is["trades"],
            "is_pf": m_is["profit_factor"],
            "is_net_pct": m_is["net_profit_pct"],
            "oos_trades": m_oos["trades"],
            "oos_pf": m_oos["profit_factor"],
            "oos_net_pct": m_oos["net_profit_pct"],
            "is_annual_pct": round(_annualised(m_is["net_profit_pct"], is_months), 2),
            "oos_annual_pct": round(_annualised(m_oos["net_profit_pct"], oos_months), 2),
        })
        is_start += relativedelta(months=step_months)

    if not windows:
        result = {"windows": [], "walk_forward_efficiency": 0.0, "pct_profitable_windows": 0.0,
                  "total_windows": 0, "note": f"period too short for {is_months}+{oos_months} month windows"}
    else:
        mean_is = float(np.mean([w["is_annual_pct"] for w in windows]))
        mean_oos = float(np.mean([w["oos_annual_pct"] for w in windows]))
        wfe = round(mean_oos / mean_is, 2) if mean_is > 0 else 0.0
        result = {
            "windows": windows,
            "walk_forward_efficiency": wfe,
            "mean_is_annual_pct": round(mean_is, 2),
            "mean_oos_annual_pct": round(mean_oos, 2),
            "pct_profitable_windows": round(100.0 * sum(w["oos_net_pct"] > 0 for w in windows) / len(windows), 1),
            "total_windows": len(windows),
        }
    result.update({"is_months": is_months, "oos_months": oos_months, "step_months": step_months,
                   "budget": sweep_budget, "min_trades": min_trades})
    if save:
        run_id, _ = save_research_run("walkforward", spec, result)
        result["run_id"] = run_id
    return result
