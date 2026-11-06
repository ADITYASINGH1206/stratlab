"""Promotion Gates evaluator enforcing Lab Charter quantitative standards."""

from typing import Any

from stratlab.engine.backtest import run_backtest
from stratlab.research.robust import run_robustness_battery
from stratlab.research.walkforward import run_walkforward
from stratlab.spec.models import StrategySpec


def evaluate_gates(
    spec: StrategySpec,
    run_id: str | None = None,
    charter_min_is_trades: int = 30,
    charter_min_oos_trades: int = 15,
    charter_min_oos_pf: float = 1.2,
    charter_min_pf_ratio: float = 0.6,
    charter_min_wfe: float = 0.5,
    charter_min_profitable_windows: float = 60.0,
    charter_min_stability_ratio: float = 0.8,
    charter_min_stressed_pf: float = 1.05,
    charter_max_mc_dd: float = 45.0,
) -> dict[str, Any]:
    """Audit a strategy against all 6 Lab Charter promotion gates."""
    # 1. Run baseline backtest
    bt_res = run_backtest(spec, save_run=True)
    m_is = bt_res["is"]
    m_oos = bt_res.get("oos", {})

    # 2. Run robustness battery (Monte Carlo, cost stress, neighbourhood)
    robust_res = run_robustness_battery(spec, run_id=bt_res["run_id"], save=True)

    # 3. Run walk-forward analysis
    wf_res = run_walkforward(spec, sweep_budget=20)

    # Check G1: Sample size
    is_trades = m_is.get("trades", 0)
    oos_trades = m_oos.get("trades", 0)
    g1_pass = (is_trades >= charter_min_is_trades) and (oos_trades >= charter_min_oos_trades)
    g1_detail = f"IS trades: {is_trades} (min {charter_min_is_trades}), OOS trades: {oos_trades} (min {charter_min_oos_trades})"

    # Check G2: Out-of-sample performance
    is_pf = m_is.get("profit_factor", 0.0)
    oos_pf = m_oos.get("profit_factor", 0.0)
    pf_ratio = (oos_pf / is_pf) if is_pf > 0 else 0.0
    g2_pass = (oos_pf >= charter_min_oos_pf) and (pf_ratio >= charter_min_pf_ratio)
    g2_detail = f"OOS PF: {oos_pf:.2f} (min {charter_min_oos_pf:.2f}), OOS/IS PF ratio: {pf_ratio:.2f} (min {charter_min_pf_ratio:.2f})"

    # Check G3: Walk-Forward efficiency & consistency
    wfe = wf_res.get("walk_forward_efficiency", 0.0)
    pct_prof = wf_res.get("pct_profitable_windows", 0.0)
    g3_pass = (wfe >= charter_min_wfe) and (pct_prof >= charter_min_profitable_windows)
    g3_detail = f"WFE: {wfe:.2f} (min {charter_min_wfe:.2f}), Profitable windows: {pct_prof:.1f}% (min {charter_min_profitable_windows:.1f}%)"

    # Check G4: Parameter stability / neighbourhood
    neigh = robust_res["neighbourhood"]
    stab_ratio = neigh.get("stability_ratio", 0.0)
    g4_pass = stab_ratio >= charter_min_stability_ratio
    g4_detail = f"Median neighbour PF: {neigh.get('median_neighbour_pf', 0.0):.2f} vs Best: {neigh.get('best_pf', 0.0):.2f} (ratio: {stab_ratio:.2f}, min {charter_min_stability_ratio:.2f})"

    # Check G5: Cost stress resilience (2x fees & slippage)
    cost = robust_res["cost_stress"]
    stressed_pf = cost.get("in_sample_pf", 0.0)
    g5_pass = stressed_pf >= charter_min_stressed_pf
    g5_detail = f"2x costs PF: {stressed_pf:.2f} (min {charter_min_stressed_pf:.2f})"

    # Check G6: Tail risk (Monte Carlo bootstrap)
    mc = robust_res["monte_carlo"]
    mc_dd = mc.get("pct_95th_max_drawdown", 100.0)
    mc_eq = mc.get("pct_5th_final_equity", 0.0)
    init_cap = spec.risk.initial_capital
    g6_pass = (mc_dd <= charter_max_mc_dd) and (mc_eq > init_cap)
    g6_detail = f"MC 95th pct Max DD: {mc_dd:.1f}% (max {charter_max_mc_dd:.1f}%), 5th pct Final Eq: ${mc_eq:.2f} (min ${init_cap:.2f})"

    gates = {
        "G1_sample_size": {"pass": g1_pass, "detail": g1_detail},
        "G2_out_of_sample": {"pass": g2_pass, "detail": g2_detail},
        "G3_walk_forward": {"pass": g3_pass, "detail": g3_detail},
        "G4_stability": {"pass": g4_pass, "detail": g4_detail},
        "G5_costs": {"pass": g5_pass, "detail": g5_detail},
        "G6_tail_risk": {"pass": g6_pass, "detail": g6_detail},
    }

    passed_count = sum(1 for g in gates.values() if g["pass"])
    total_gates = len(gates)
    all_passed = (passed_count == total_gates)

    return {
        "verdict": "PASS" if all_passed else "FAIL",
        "passed_count": passed_count,
        "total_gates": total_gates,
        "gates": gates,
        "run_id": bt_res["run_id"],
        "spec_id": spec.id,
        "version": spec.version,
    }
