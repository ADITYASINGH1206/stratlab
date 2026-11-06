"""Rolling Walk-Forward Analysis re-optimizing parameters per window."""

from typing import Any

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta

from stratlab.data.cache import load_ohlcv
from stratlab.engine.backtest import compute_indicator_context
from stratlab.engine.conditions import evaluate_condition_tree
from stratlab.engine.metrics import compute_metrics
from stratlab.engine.sim import simulate
from stratlab.research.sweep import _evaluate_single_combo, _generate_param_combinations
from stratlab.spec.models import StrategySpec


def run_walkforward(
    spec: StrategySpec,
    is_months: int = 24,
    oos_months: int = 6,
    step_months: int = 6,
    sweep_budget: int = 50,
) -> dict[str, Any]:
    """Execute rolling walk-forward test re-picking best params per window."""
    df = load_ohlcv(
        spec.market.symbol,
        spec.market.timeframe,
        start_date=str(spec.period.start),
        end_date=str(spec.period.end),
    )

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    start_dt = df["timestamp"].min()
    end_dt = df["timestamp"].max()

    curr_is_start = start_dt
    windows = []
    window_idx = 1

    param_combos = _generate_param_combinations(spec, budget=sweep_budget)

    while True:
        curr_is_end = curr_is_start + relativedelta(months=is_months)
        curr_oos_end = curr_is_end + relativedelta(months=oos_months)

        if curr_oos_end > end_dt:
            break

        # Slice data
        df_win_is = df[(df["timestamp"] >= curr_is_start) & (df["timestamp"] < curr_is_end)].reset_index(drop=True)
        df_win_oos = df[(df["timestamp"] >= curr_is_end) & (df["timestamp"] < curr_oos_end)].reset_index(drop=True)

        if len(df_win_is) < 30 or len(df_win_oos) < 10:
            curr_is_start += relativedelta(months=step_months)
            continue

        # 1. Optimize on In-Sample window
        best_combo = None
        best_score = -9999.0

        for combo in param_combos:
            res = _evaluate_single_combo(spec, df_win_is, combo)
            # Score: profit factor prioritized if trades >= 10
            pf = res.get("profit_factor", 0.0)
            score = pf * min(res.get("trades", 0), 20) / 20.0
            if score > best_score:
                best_score = score
                best_combo = combo

        if not best_combo:
            best_combo = {k: v.default for k, v in spec.params.items()}

        # 2. Test best combo on Out-of-Sample window
        ctx_oos = compute_indicator_context(df_win_oos, spec, best_combo)
        long_sig = evaluate_condition_tree(spec.entry.long, ctx_oos, len(df_win_oos)) if spec.entry.long else np.zeros(len(df_win_oos), dtype=bool)
        short_sig = evaluate_condition_tree(spec.entry.short, ctx_oos, len(df_win_oos)) if spec.entry.short else np.zeros(len(df_win_oos), dtype=bool)

        stop_atr_mult = 0.0
        if spec.exit.stop and spec.exit.stop.atr_mult:
            raw = spec.exit.stop.atr_mult
            stop_atr_mult = float(best_combo.get(raw[1:], raw) if isinstance(raw, str) and raw.startswith("$") else raw)

        target_atr_mult = 0.0
        if spec.exit.target and spec.exit.target.atr_mult:
            raw = spec.exit.target.atr_mult
            target_atr_mult = float(best_combo.get(raw[1:], raw) if isinstance(raw, str) and raw.startswith("$") else raw)

        trades_oos, eq_oos = simulate(
            df_win_oos,
            long_signals=long_sig,
            short_signals=short_sig,
            atr_series=ctx_oos.get("atr"),
            stop_atr_mult=stop_atr_mult,
            target_atr_mult=target_atr_mult,
            time_bars=int(spec.exit.time.bars) if spec.exit.time and spec.exit.time.bars else 0,
            opposite_exit=bool(spec.exit.opposite_signal),
            commission_pct=spec.costs.commission_pct / 100.0,
            slippage_ticks=spec.costs.slippage_ticks,
            tick_size=spec.costs.tick_size,
            initial_capital=spec.risk.initial_capital,
        )

        m_oos = compute_metrics(
            trades_oos,
            eq_oos,
            initial_capital=spec.risk.initial_capital,
            timeframe=spec.market.timeframe,
            total_bars=len(df_win_oos),
        )

        # IS metrics for best combo
        m_is = _evaluate_single_combo(spec, df_win_is, best_combo)

        windows.append({
            "window": window_idx,
            "is_start": curr_is_start.strftime("%Y-%m-%d"),
            "is_end": curr_is_end.strftime("%Y-%m-%d"),
            "oos_start": curr_is_end.strftime("%Y-%m-%d"),
            "oos_end": curr_oos_end.strftime("%Y-%m-%d"),
            "best_params": best_combo,
            "is_pf": m_is.get("profit_factor", 0.0),
            "is_net_pct": m_is.get("net_profit_pct", 0.0),
            "oos_trades": m_oos["trades"],
            "oos_pf": m_oos["profit_factor"],
            "oos_net_pct": m_oos["net_profit_pct"],
        })

        window_idx += 1
        curr_is_start += relativedelta(months=step_months)

    if not windows:
        return {
            "windows": [],
            "walk_forward_efficiency": 0.0,
            "pct_profitable_windows": 0.0,
        }

    # Aggregate Walk-Forward Efficiency (WFE)
    is_pfs = [w["is_pf"] for w in windows if w["is_pf"] > 0]
    oos_pfs = [w["oos_pf"] for w in windows]
    avg_is_pf = float(np.mean(is_pfs)) if is_pfs else 1.0
    avg_oos_pf = float(np.mean(oos_pfs)) if oos_pfs else 0.0

    wfe = round(avg_oos_pf / avg_is_pf, 2) if avg_is_pf > 0 else 0.0
    profitable_count = sum(1 for w in windows if w["oos_net_pct"] > 0)
    pct_profitable = round((profitable_count / len(windows)) * 100.0, 1)

    return {
        "windows": windows,
        "walk_forward_efficiency": wfe,
        "pct_profitable_windows": pct_profitable,
        "total_windows": len(windows),
    }
