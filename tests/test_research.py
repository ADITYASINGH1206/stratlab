"""Tests for research tools: sweep, walk-forward, robustness, promotion gates, and charts."""

from pathlib import Path

import numpy as np
import pandas as pd

from stratlab.charts import (
    plot_equity_and_drawdown,
    plot_param_heatmap,
    render_metrics_card,
)
from stratlab.research.gates import evaluate_gates
from stratlab.research.robust import run_monte_carlo_bootstrap
from stratlab.research.sweep import run_sweep
from stratlab.research.walkforward import run_walkforward
from stratlab.spec.validate import validate_spec_file

SPEC_DIR = Path(__file__).resolve().parent.parent / "examples" / "specs"


def test_param_sweep():
    spec_res = validate_spec_file(SPEC_DIR / "S-012" / "v1.yaml")
    assert spec_res.is_valid
    sweep_df = run_sweep(spec_res.spec, budget=15, n_jobs=2)

    assert len(sweep_df) == 15
    for col in ["profit_factor", "net_profit_pct", "trades", "max_drawdown_pct"]:
        assert col in sweep_df.columns
    # Results should be sorted by profit_factor descending
    assert sweep_df["profit_factor"].iloc[0] >= sweep_df["profit_factor"].iloc[-1]


def test_walkforward():
    spec_res = validate_spec_file(SPEC_DIR / "S-012" / "v2.yaml")
    assert spec_res.is_valid
    wf_res = run_walkforward(spec_res.spec, sweep_budget=10)

    assert "walk_forward_efficiency" in wf_res
    assert "pct_profitable_windows" in wf_res
    assert len(wf_res["windows"]) > 0
    w1 = wf_res["windows"][0]
    assert "is_pf" in w1
    assert "oos_pf" in w1


def test_robustness_monte_carlo():
    dates = pd.date_range("2024-01-01", periods=20, freq="1D")
    trades_df = pd.DataFrame({
        "timestamp": dates,
        "pnl": [100.0, -50.0, 200.0, -100.0, 150.0] * 4,
    })
    mc = run_monte_carlo_bootstrap(trades_df, initial_capital=10000.0, n_simulations=500)

    assert mc["n_simulations"] == 500
    assert mc["pct_95th_max_drawdown"] >= 0.0
    assert mc["pct_5th_final_equity"] > 0.0


def test_sweep_never_picks_a_low_trade_fluke():
    spec = validate_spec_file(SPEC_DIR / "S-012" / "v1.yaml").spec
    df = run_sweep(spec, budget=60, min_trades=20)
    s = df.attrs["summary"]
    assert df.iloc[0]["eligible"]
    assert s["best_is"]["trades"] >= 20
    assert df.attrs["run_id"].startswith("sweep_S-012_v1")


def test_gates_audit_the_sweep_candidate_and_read_the_charter():
    """The Skeptic audits the sweep's best combo, with thresholds from charter.yaml."""
    spec = validate_spec_file(SPEC_DIR / "S-012" / "v1.yaml").spec
    df = run_sweep(spec, budget=60)
    audit = evaluate_gates(spec, reuse_walkforward=False)
    assert audit["params_source"].startswith("sweep:")
    best = {k: df.iloc[0][k] for k in df.attrs["summary"]["tunable"]}
    assert all(float(audit["params"][k]) == float(v) for k, v in best.items())
    assert set(audit["gates"]) == {"G1_sample_size", "G2_out_of_sample", "G3_walk_forward",
                                   "G4_stability", "G5_costs", "G6_tail_risk"}
    # S-012 v1 is the demo's overfit baseline: it must not pass on the bundled data.
    assert audit["verdict"] == "FAIL"

    strict = evaluate_gates(spec, charter_overrides={"g1_sample_size.min_is_trades": 1,
                                                     "g1_sample_size.min_oos_trades": 1})
    assert strict["gates"]["G1_sample_size"]["pass"]


def test_gates_without_a_sweep_fall_back_to_defaults():
    spec = validate_spec_file(SPEC_DIR / "S-020" / "v1.yaml").spec
    audit = evaluate_gates(spec)
    assert audit["params_source"] in ("defaults",) or audit["params_source"].startswith("sweep:")
    assert audit["total_gates"] == 6


def test_chart_renderers(tmp_path):
    # 1. Equity
    dates = pd.date_range("2024-01-01", periods=10, freq="4h")
    df = pd.DataFrame({"timestamp": dates})
    eq = np.array([10000.0 + i * 50.0 for i in range(10)])
    eq_file = plot_equity_and_drawdown(df, eq, tmp_path / "eq.png")
    assert eq_file.exists()
    assert eq_file.stat().st_size > 1000

    # 2. Heatmap
    sweep_df = pd.DataFrame({
        "rsi_len": [7, 7, 14, 14],
        "atr_stop": [1.0, 2.0, 1.0, 2.0],
        "profit_factor": [1.2, 1.5, 1.4, 1.8],
    })
    hm_file = plot_param_heatmap(sweep_df, "rsi_len", "atr_stop", "profit_factor", tmp_path / "hm.png")
    assert hm_file.exists()
    assert hm_file.stat().st_size > 1000

    # 3. Card
    card_file = render_metrics_card("S-012", 2, {"in_sample": {"profit_factor": 1.5}}, eq, tmp_path / "card.png")
    assert card_file.exists()
    assert card_file.stat().st_size > 1000
