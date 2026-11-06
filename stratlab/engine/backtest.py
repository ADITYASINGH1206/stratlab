"""Backtest orchestration engine compiling spec to simulation runs."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from stratlab.config import get_registry_db, get_runs_dir
from stratlab.engine.registry import new_run_id, spec_hash, to_jsonable
from stratlab.engine.runner import active_params, compute_context, evaluate, prepare
from stratlab.spec.models import StrategySpec

# Kept for callers of the Phase 2 API.
compute_indicator_context = compute_context


def init_registry_db() -> Path:
    """Initialize the SQLite registry database table if not exists."""
    db_path = get_registry_db()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                spec_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                split TEXT NOT NULL,
                trades INTEGER NOT NULL,
                net_profit_pct REAL NOT NULL,
                profit_factor REAL NOT NULL,
                max_drawdown_pct REAL NOT NULL,
                win_rate_pct REAL NOT NULL,
                sharpe_ratio REAL NOT NULL,
                params_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    return db_path


def _record_run_in_registry(
    run_id: str,
    spec_id: str,
    version: int,
    split: str,
    metrics: dict[str, Any],
    params: dict[str, Any],
) -> None:
    """Save run summary row to SQLite registry."""
    db_path = init_registry_db()
    now_iso = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO runs (
                run_id, spec_id, version, split, trades,
                net_profit_pct, profit_factor, max_drawdown_pct,
                win_rate_pct, sharpe_ratio, params_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                spec_id,
                version,
                split,
                metrics["trades"],
                metrics["net_profit_pct"],
                metrics["profit_factor"],
                metrics["max_drawdown_pct"],
                metrics["win_rate_pct"],
                metrics["sharpe_ratio"],
                json.dumps(params),
                now_iso,
            ),
        )
        conn.commit()


def _split_dates(prep) -> dict[str, str]:
    ts = pd.to_datetime(prep.df["timestamp"])
    return {
        "is_start": str(ts.iloc[prep.start]), "is_end": str(ts.iloc[prep.split - 1]),
        "oos_start": str(ts.iloc[prep.split]) if prep.split < prep.end else None,
        "oos_end": str(ts.iloc[prep.end - 1]),
    }


def run_backtest(
    spec: StrategySpec,
    param_overrides: dict[str, Any] | None = None,
    save_run: bool = True,
    params_source: str = "defaults",
    cost_mult: float = 1.0,
) -> dict[str, Any]:
    """In-sample, out-of-sample and full-period backtest for one parameter set.

    Every window starts flat. Indicators are computed on all history up to the period end, so
    the out-of-sample window keeps its warm-up (as on a TradingView chart).
    """
    params = active_params(spec, param_overrides)
    prep = prepare(spec)
    res = evaluate(spec, prep, params, cost_mult=cost_mult)
    m_is = res["is"]["metrics"]
    m_oos = res["oos"]["metrics"] if res["oos"] else {}
    m_full = res["full"]["metrics"]

    run_id = new_run_id("run", spec)
    run_dir = get_runs_dir() / run_id
    if save_run:
        run_dir.mkdir(parents=True, exist_ok=True)
        full_metrics = {
            "run_id": run_id,
            "spec_id": spec.id,
            "version": spec.version,
            "spec_hash": spec_hash(spec),
            "spec_name": spec.name,
            "market": spec.market.model_dump(),
            "params": params,
            "params_source": params_source,
            "cost_multiplier": cost_mult,
            "windows": _split_dates(prep),
            "in_sample": m_is,
            "out_of_sample": m_oos,
            "full_period": m_full,
        }
        (run_dir / "metrics.json").write_text(json.dumps(to_jsonable(full_metrics), indent=2))
        parts = [res["is"]["trades"].assign(split="IS")]
        if res["oos"]:
            parts.append(res["oos"]["trades"].assign(split="OOS"))
        parts.append(res["full"]["trades"].assign(split="FULL"))
        pd.concat([p for p in parts if len(p)] or [parts[0]], ignore_index=True).to_csv(run_dir / "trades.csv", index=False)
        ts = prep.df["timestamp"].iloc[prep.start:prep.end].reset_index(drop=True)
        pd.DataFrame({"timestamp": ts, "equity": res["full"]["equity"]}).to_csv(run_dir / "equity.csv", index=False)
        _record_run_in_registry(f"{run_id}_is", spec.id, spec.version, "IS", m_is, params)
        if m_oos:
            _record_run_in_registry(f"{run_id}_oos", spec.id, spec.version, "OOS", m_oos, params)
        _record_run_in_registry(f"{run_id}_full", spec.id, spec.version, "FULL", m_full, params)

    return {
        "run_id": run_id,
        "spec_id": spec.id,
        "version": spec.version,
        "params": params,
        "params_source": params_source,
        "is": m_is,
        "oos": m_oos,
        "full": m_full,
        "trades_is_count": int(m_is["trades"]),
        "trades_oos_count": int(m_oos.get("trades", 0)),
        "run_dir": str(run_dir) if save_run else None,
    }
