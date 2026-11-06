"""Parity checker comparing Python backtest trades with TradingView CSV exports."""

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from stratlab.engine.backtest import run_backtest
from stratlab.spec.models import StrategySpec
from stratlab.tv.trades_csv import parse_tv_trades_csv


def check_trade_parity(
    spec: StrategySpec,
    tv_csv_path: Path | str,
    time_tolerance_hours: float = 4.5,
) -> dict[str, Any]:
    """Compare Python engine simulation trades against TradingView export."""
    # 1. Parse TradingView trades
    tv_df = parse_tv_trades_csv(tv_csv_path)

    # 2. Run simulation
    bt_res = run_backtest(spec, save_run=True)
    run_dir = Path(bt_res["run_dir"])
    engine_df = pd.read_csv(run_dir / "trades.csv")

    engine_count = len(engine_df)
    tv_count = len(tv_df)

    if tv_count == 0:
        return {
            "engine_trades": engine_count,
            "tv_trades": 0,
            "matched_entries_pct": 0.0,
            "net_profit_diff_pct": 0.0,
            "status": "FAIL",
            "first_mismatch": "TradingView CSV contains 0 trades",
        }

    # Match entries within tolerance
    engine_times = pd.to_datetime(engine_df["entry_time"]).to_numpy()
    tv_times = pd.to_datetime(tv_df["entry_time"]).to_numpy()

    matched_count = 0
    first_mismatch = None

    for idx, tv_t in enumerate(tv_times):
        # Time difference in hours
        diffs_hours = np.abs((engine_times - tv_t) / np.timedelta64(1, "h"))
        min_idx = np.argmin(diffs_hours) if len(diffs_hours) > 0 else None

        if min_idx is not None and diffs_hours[min_idx] <= time_tolerance_hours:
            matched_count += 1
        else:
            if first_mismatch is None:
                first_mismatch = {
                    "trade_num": idx + 1,
                    "tv_entry_time": str(tv_t),
                    "tv_entry_price": float(tv_df["entry_price"].iloc[idx]),
                    "closest_engine_time": str(engine_times[min_idx]) if min_idx is not None else "None",
                    "closest_engine_price": float(engine_df["entry_price"].iloc[min_idx]) if min_idx is not None else 0.0,
                    "hour_diff": round(float(diffs_hours[min_idx]), 2) if min_idx is not None else 999.0,
                }

    matched_pct = round((matched_count / tv_count) * 100.0, 1)

    engine_profit = float(engine_df["pnl"].sum()) if not engine_df.empty else 0.0
    tv_profit = float(tv_df["profit"].sum()) if "profit" in tv_df else 0.0

    profit_diff = abs(engine_profit - tv_profit)
    profit_diff_pct = round((profit_diff / abs(tv_profit) * 100.0), 2) if abs(tv_profit) > 0 else 0.0

    # Target: >= 95% entries matched and net profit within 5%
    passes_parity = (matched_pct >= 95.0) and (profit_diff_pct <= 5.0)

    return {
        "status": "PASS" if passes_parity else "FAIL",
        "engine_trades": engine_count,
        "tv_trades": tv_count,
        "trade_count_diff": abs(engine_count - tv_count),
        "matched_entries_count": matched_count,
        "matched_entries_pct": matched_pct,
        "engine_net_profit": round(engine_profit, 2),
        "tv_net_profit": round(tv_profit, 2),
        "net_profit_diff_pct": profit_diff_pct,
        "first_mismatch": first_mismatch,
    }


def render_parity_report(report: dict[str, Any]) -> str:
    """Format parity comparison into clean human text for chat/CLI."""
    status_str = "PASS" if report["status"] == "PASS" else "FAIL"
    lines = [
        f"Parity Match Report: [{status_str}]",
        f"  Trade Counts: Engine {report['engine_trades']} vs TradingView {report['tv_trades']} (diff: {report['trade_count_diff']})",
        f"  Matched Entries: {report['matched_entries_count']}/{report['tv_trades']} ({report['matched_entries_pct']}%) [Target: >= 95%]",
        f"  Net Profit: Engine ${report['engine_net_profit']:.2f} vs TV ${report['tv_net_profit']:.2f} (drift: {report['net_profit_diff_pct']}%) [Target: <= 5%]",
    ]

    if report.get("first_mismatch"):
        fm = report["first_mismatch"]
        if isinstance(fm, dict):
            lines.append("  First Mismatch:")
            lines.append(f"    TV Trade #{fm['trade_num']} at {fm['tv_entry_time']} (${fm['tv_entry_price']})")
            lines.append(f"    Nearest Engine entry: {fm['closest_engine_time']} (${fm['closest_engine_price']}, diff {fm['hour_diff']}h)")
        else:
            lines.append(f"  Note: {fm}")

    return "\n".join(lines)
