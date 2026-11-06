"""The six promotion gates of the Lab Charter, applied to the candidate parameter set."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stratlab.engine.backtest import run_backtest
from stratlab.engine.registry import latest_research_run, save_research_run
from stratlab.research.charter import load_charter
from stratlab.research.robust import candidate_params, run_robustness_battery
from stratlab.research.walkforward import run_walkforward
from stratlab.spec.models import StrategySpec

GATE_TITLES = {
    "G1_sample_size": "G1 Sample size",
    "G2_out_of_sample": "G2 Out-of-sample",
    "G3_walk_forward": "G3 Walk-forward",
    "G4_stability": "G4 Stability",
    "G5_costs": "G5 Costs",
    "G6_tail_risk": "G6 Tail risk",
}


def evaluate_gates(
    spec: StrategySpec,
    param_overrides: dict[str, Any] | None = None,
    charter_overrides: dict[str, Any] | None = None,
    reuse_walkforward: bool = True,
    save: bool = True,
) -> dict[str, Any]:
    """Audit the candidate (explicit params, else latest sweep best, else defaults)."""
    c = load_charter(overrides=charter_overrides)
    params, source = candidate_params(spec, param_overrides)
    bt = run_backtest(spec, param_overrides=params, save_run=True, params_source=source)
    robust = run_robustness_battery(spec, param_overrides=params, save=save)
    robust["params_source"] = source
    wf = latest_research_run("walkforward", spec) if reuse_walkforward else None
    if wf is None:
        wf = run_walkforward(spec, save=save)

    m_is, m_oos = bt["is"], bt["oos"] or {}
    gates: dict[str, dict[str, Any]] = {}

    t = c["g1_sample_size"]
    gates["G1_sample_size"] = {
        "pass": m_is["trades"] >= t["min_is_trades"] and m_oos.get("trades", 0) >= t["min_oos_trades"],
        "values": {"is_trades": m_is["trades"], "oos_trades": m_oos.get("trades", 0)},
        "detail": f"IS trades {m_is['trades']} (min {t['min_is_trades']}), OOS trades {m_oos.get('trades', 0)} (min {t['min_oos_trades']})",
    }

    t = c["g2_out_of_sample"]
    is_pf, oos_pf = m_is["profit_factor"], m_oos.get("profit_factor", 0.0)
    ratio = round(oos_pf / is_pf, 2) if is_pf > 0 else 0.0
    gates["G2_out_of_sample"] = {
        "pass": oos_pf >= t["min_oos_pf"] and ratio >= t["min_oos_is_pf_ratio"],
        "values": {"oos_pf": oos_pf, "is_pf": is_pf, "ratio": ratio},
        "detail": f"OOS PF {oos_pf:.2f} (min {t['min_oos_pf']}), OOS/IS PF {ratio:.2f} (min {t['min_oos_is_pf_ratio']})",
    }

    t = c["g3_walk_forward"]
    wfe, prof = wf.get("walk_forward_efficiency", 0.0), wf.get("pct_profitable_windows", 0.0)
    gates["G3_walk_forward"] = {
        "pass": wf.get("total_windows", 0) > 0 and wfe >= t["min_wfe"] and prof >= t["min_pct_profitable_windows"],
        "values": {"wfe": wfe, "pct_profitable_windows": prof, "windows": wf.get("total_windows", 0)},
        "detail": f"WFE {wfe:.2f} (min {t['min_wfe']}), profitable windows {prof:.0f}% (min {t['min_pct_profitable_windows']}%) over {wf.get('total_windows', 0)} windows",
    }

    t = c["g4_stability"]
    nb = robust["neighbourhood"]
    if nb["stability_ratio"] is None:
        gates["G4_stability"] = {"pass": True, "values": {"stability_ratio": None},
                                 "detail": "n/a: no tunable params, nothing to overfit"}
    else:
        gates["G4_stability"] = {
            "pass": nb["stability_ratio"] >= t["min_neighbour_pf_ratio"],
            "values": {"stability_ratio": nb["stability_ratio"], "best_pf": nb["best_pf"], "median_neighbour_pf": nb["median_neighbour_pf"]},
            "detail": f"median neighbour PF {nb['median_neighbour_pf']:.2f} vs candidate {nb['best_pf']:.2f}, ratio {nb['stability_ratio']:.2f} (min {t['min_neighbour_pf_ratio']}) over {nb['tested_neighbours']} neighbours",
        }

    t = c["g5_costs"]
    stressed = robust["cost_stress"]["full_period_pf"]
    gates["G5_costs"] = {
        "pass": stressed >= t["min_stressed_pf"],
        "values": {"stressed_pf": stressed},
        "detail": f"PF at {t['cost_multiplier']:g}x fees and slippage {stressed:.2f} (min {t['min_stressed_pf']})",
    }

    t = c["g6_tail_risk"]
    mc = robust["monte_carlo"]
    dd_cap = t["max_drawdown_limit_pct"] * t["mc_drawdown_multiple"]
    init = spec.risk.initial_capital
    gates["G6_tail_risk"] = {
        "pass": mc["n_trades"] > 0 and mc["pct_95th_max_drawdown"] <= dd_cap and mc["pct_5th_final_equity"] > init,
        "values": {"p95_max_dd": mc["pct_95th_max_drawdown"], "p5_final_equity": mc["pct_5th_final_equity"]},
        "detail": f"MC 95th pct max DD {mc['pct_95th_max_drawdown']:.1f}% (max {dd_cap:g}%), 5th pct final equity ${mc['pct_5th_final_equity']:,.0f} (must beat ${init:,.0f})",
    }

    passed = sum(g["pass"] for g in gates.values())
    failed = [k for k, g in gates.items() if not g["pass"]]
    audit = {
        "verdict": "PASS" if not failed else "FAIL",
        "passed_count": passed,
        "total_gates": len(gates),
        "failed": failed,
        "gates": gates,
        "params": params,
        "params_source": source,
        "charter": c,
        "run_id": bt["run_id"],
        "backtest_run_id": bt["run_id"],
        "robust_run_id": robust.get("run_id"),
        "walkforward_run_id": wf.get("run_id"),
        "spec_id": spec.id,
        "version": spec.version,
        "spec_name": spec.name,
        "is": m_is,
        "oos": m_oos,
    }
    if save:
        rid, _ = save_research_run("gates", spec, audit)
        audit["gates_run_id"] = rid
        # Also drop a copy next to the backtest run, where the ledger looks for it.
        Path(bt["run_dir"], "gates.json").write_text(json.dumps(
            {"gates": [{"name": k, "passed": bool(g["pass"])} for k, g in gates.items()], **{
                "verdict": audit["verdict"], "gates_run_id": rid}}, indent=2))
    return audit
