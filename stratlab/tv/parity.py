"""Compare the engine's trades with a TradingView "List of Trades" export of the same spec."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from stratlab.config import TF_SECONDS
from stratlab.engine.registry import save_research_run
from stratlab.engine.runner import active_params, compute_signals, prepare, run_window
from stratlab.spec.models import StrategySpec
from stratlab.tv.trades_csv import parse_tv_trades_csv

DRIFT_CAUSES = [
    "data feed: TradingView's BINANCE:BTCUSDT candles vs the cached Binance candles",
    "position size: TradingView sizes 100% of equity from the signal bar's close, the engine from the fill price",
    "intrabar path assumption (keep Bar Magnifier OFF for parity runs)",
    "chart timezone: export with the chart set to UTC",
    "rounding to the symbol's tick size",
]


def check_trade_parity(spec: StrategySpec, tv_csv_path: Path | str, param_overrides: dict[str, Any] | None = None,
                       min_match_pct: float = 95.0, max_profit_drift_pct: float = 5.0, save: bool = True) -> dict[str, Any]:
    """Match TradingView entries to engine entries within one bar, and compare net profit.

    The engine side is one simulation over the whole spec period with the same inputs as
    the generated Pine (spec defaults unless `param_overrides`), which is what TradingView runs.
    """
    tv = parse_tv_trades_csv(tv_csv_path)
    params = active_params(spec, param_overrides)
    prep = prepare(spec)
    sig = compute_signals(spec, prep, params)
    eng, _, m_full = run_window(spec, prep, sig, params, prep.start, prep.end)
    bar = np.timedelta64(TF_SECONDS.get(spec.market.timeframe, 14400), "s")

    report: dict[str, Any] = {"spec_id": spec.id, "version": spec.version, "params": params,
                              "engine_trades": len(eng), "tv_trades": len(tv),
                              "trade_count_diff": abs(len(eng) - len(tv)), "drift_causes": DRIFT_CAUSES}
    if len(tv) == 0:
        report.update({"status": "FAIL", "matched_entries_count": 0, "matched_entries_pct": 0.0,
                       "matched_exits_pct": 0.0, "engine_net_profit": m_full["net_profit"], "tv_net_profit": 0.0,
                       "net_profit_diff_pct": 100.0, "first_mismatch": "the TradingView CSV has no closed trades"})
        return report

    e_times = pd.to_datetime(eng["entry_time"]).to_numpy() if len(eng) else np.array([], dtype="datetime64[ns]")
    used: set[int] = set()
    matched = exits_matched = 0
    first = None
    for k, row in tv.iterrows():
        t = np.datetime64(pd.Timestamp(row["entry_time"]).to_datetime64())
        j = None
        if len(e_times):
            diffs = np.abs(e_times - t)
            order = np.argsort(diffs)
            j = next((int(i) for i in order if int(i) not in used), None)
        if j is not None and np.abs(e_times[j] - t) <= bar:
            used.add(j)
            matched += 1
            if abs(pd.Timestamp(eng["exit_time"].iloc[j]) - pd.Timestamp(row["exit_time"])) <= pd.Timedelta(bar):
                exits_matched += 1
        elif first is None:
            near = int(np.argmin(np.abs(e_times - t))) if len(e_times) else None
            first = {
                "tv_trade": int(row["trade_num"]),
                "tv_entry": f"{pd.Timestamp(row['entry_time'])} @ {row['entry_price']:.2f}",
                "tv_exit": f"{pd.Timestamp(row['exit_time'])} @ {row['exit_price']:.2f}",
                "engine_nearest_entry": (f"{pd.Timestamp(eng['entry_time'].iloc[near])} @ {eng['entry_price'].iloc[near]:.2f}"
                                         if near is not None else "none"),
                "engine_nearest_exit": (f"{pd.Timestamp(eng['exit_time'].iloc[near])} @ {eng['exit_price'].iloc[near]:.2f}"
                                        if near is not None else "none"),
            }

    cap = spec.risk.initial_capital
    eng_profit = float(eng["pnl"].sum()) if len(eng) else 0.0
    tv_profit = float(tv["profit"].sum())
    drift = abs(eng_profit - tv_profit) / max(abs(tv_profit), 0.01 * cap) * 100.0
    matched_pct = round(100.0 * matched / len(tv), 1)
    report.update({
        "matched_entries_count": matched,
        "matched_entries_pct": matched_pct,
        "matched_exits_pct": round(100.0 * exits_matched / len(tv), 1),
        "engine_net_profit": round(eng_profit, 2),
        "tv_net_profit": round(tv_profit, 2),
        "net_profit_diff_pct": round(drift, 2),
        "targets": {"min_matched_entries_pct": min_match_pct, "max_net_profit_drift_pct": max_profit_drift_pct},
        "first_mismatch": first,
        "status": "PASS" if matched_pct >= min_match_pct and drift <= max_profit_drift_pct else "FAIL",
    })
    if save:
        rid, _ = save_research_run("parity", spec, report)
        report["run_id"] = rid
    return report


def render_parity_report(report: dict[str, Any]) -> str:
    lines = [
        f"Parity Match Report: [{report['status']}]",
        f"  Trade Counts: Engine {report['engine_trades']} vs TradingView {report['tv_trades']} (diff: {report['trade_count_diff']})",
        f"  Matched Entries: {report['matched_entries_count']}/{report['tv_trades']} ({report['matched_entries_pct']}%) [Target: >= 95%]",
        f"  Matched Exits (same bar): {report.get('matched_exits_pct', 0.0)}%",
        f"  Net Profit: Engine ${report['engine_net_profit']:,.2f} vs TV ${report['tv_net_profit']:,.2f} "
        f"(drift: {report['net_profit_diff_pct']}%) [Target: <= 5%]",
    ]
    fm = report.get("first_mismatch")
    if isinstance(fm, dict):
        lines += ["  First Mismatch:",
                  f"    TV #{fm['tv_trade']}: entry {fm['tv_entry']}, exit {fm['tv_exit']}",
                  f"    Engine nearest: entry {fm['engine_nearest_entry']}, exit {fm['engine_nearest_exit']}"]
    elif fm:
        lines.append(f"  Note: {fm}")
    if report["status"] != "PASS":
        lines.append("  Known drift causes: " + "; ".join(report.get("drift_causes", [])))
    return "\n".join(lines)
