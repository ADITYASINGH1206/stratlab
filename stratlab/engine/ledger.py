"""Strategy Ledger management in SQLite registry."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stratlab.config import get_registry_db, get_runs_dir
from stratlab.engine.registry import latest_by_id


def init_ledger_table() -> Path:
    """Ensure the ledger table exists in registry.sqlite."""
    db_path = get_registry_db()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spec_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                verdict TEXT NOT NULL,
                decided_by TEXT NOT NULL,
                note TEXT NOT NULL,
                oos_pf REAL,
                oos_max_dd REAL,
                failed_gates TEXT,
                run_id TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    return db_path


def add_ledger_entry(
    target: str,
    verdict: str,
    decided_by: str,
    note: str = "",
) -> dict[str, Any]:
    """Add a strategy decision entry (promote, kill, park) to the ledger."""
    verdict = verdict.strip().lower()
    if verdict not in ("promote", "kill", "park"):
        raise ValueError(f"verdict must be promote, kill or park, got '{verdict}'")
    db_path = init_ledger_table()
    if "@v" in target:
        spec_id, v_str = target.split("@v", 1)
        version = int(v_str)
    elif "_v" in target:
        spec_id, v_str = target.split("_v", 1)
        version = int(v_str)
    else:
        spec_id = target
        version = 1

    # Try to find latest OOS run metrics and gates audit
    oos_pf = None
    oos_max_dd = None
    failed_gates = "None"
    run_id = None

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT run_id, profit_factor, max_drawdown_pct
            FROM runs
            WHERE spec_id = ? AND version = ? AND split = 'OOS'
            ORDER BY created_at DESC LIMIT 1
            """,
            (spec_id, version),
        )
        row = cursor.fetchone()
        if row:
            run_id = row[0]
            oos_pf = row[1]
            oos_max_dd = row[2]

            # Check if gates report exists in the run folder
            base_run_id = run_id.replace("_oos", "")
            run_dir = get_runs_dir() / base_run_id
            gates_file = run_dir / "gates.json"
            if gates_file.exists():
                try:
                    gates_data = json.loads(gates_file.read_text())
                    fails = [g["name"] for g in gates_data.get("gates", []) if not g.get("passed", False)]
                    if fails:
                        failed_gates = ", ".join(fails)
                except Exception:
                    pass

        # Prefer the Skeptic's latest gate audit: it holds the candidate's OOS numbers.
        gates_run = latest_by_id("gates", spec_id, version)
        if gates_run:
            oos = gates_run.get("oos") or {}
            oos_pf = oos.get("profit_factor", oos_pf)
            oos_max_dd = oos.get("max_drawdown_pct", oos_max_dd)
            failed_gates = ", ".join(gates_run.get("failed") or []) or "None"
            run_id = gates_run.get("gates_run_id") or gates_run.get("run_id") or run_id

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        cursor.execute(
            """
            INSERT INTO ledger (spec_id, version, verdict, decided_by, note, oos_pf, oos_max_dd, failed_gates, run_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                spec_id,
                version,
                verdict.upper(),
                decided_by,
                note,
                oos_pf,
                oos_max_dd,
                failed_gates,
                run_id,
                now_str,
            ),
        )
        entry_id = cursor.lastrowid
        conn.commit()

    return {
        "id": entry_id,
        "spec_id": spec_id,
        "version": version,
        "verdict": verdict.upper(),
        "decided_by": decided_by,
        "note": note,
        "oos_pf": oos_pf,
        "oos_max_dd": oos_max_dd,
        "failed_gates": failed_gates,
        "run_id": run_id,
        "created_at": now_str,
    }


def query_ledger(spec_id: str | None = None) -> list[dict[str, Any]]:
    """Query entries from the strategy ledger."""
    db_path = init_ledger_table()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        if spec_id:
            cursor.execute("SELECT * FROM ledger WHERE spec_id = ? ORDER BY id ASC", (spec_id,))
        else:
            cursor.execute("SELECT * FROM ledger ORDER BY id ASC")
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


def render_ledger_markdown() -> str:
    """Render the full Strategy Ledger as GitHub Flavored Markdown table for Switch room document."""
    entries = query_ledger()
    if not entries:
        return (
            "# Strategy Ledger\n\n"
            "*No strategies have been recorded yet. The Strategy Ledger will automatically update as decisions are made.*\n"
        )

    lines = [
        "# Strategy Ledger",
        "",
        "| ID | Version | Verdict | Decided By | OOS PF | OOS Max DD | Failed Gates | Notes | Logged At |",
        "| :--- | :---: | :---: | :--- | :---: | :---: | :--- | :--- | :--- |",
    ]
    for e in entries:
        pf_str = f"{e['oos_pf']:.2f}" if e.get("oos_pf") is not None else "—"
        dd_str = f"{e['oos_max_dd']:.1f}%" if e.get("oos_max_dd") is not None else "—"
        verdict = e["verdict"]
        badge = f"**{verdict}**"
        if verdict == "PROMOTE":
            badge = "🟢 **PROMOTE**"
        elif verdict == "KILL":
            badge = "🔴 **KILL**"
        elif verdict == "PARK":
            badge = "🟡 **PARK**"

        lines.append(
            f"| `{e['spec_id']}` | v{e['version']} | {badge} | {e['decided_by']} | {pf_str} | {dd_str} | {e.get('failed_gates', 'None')} | {e.get('note', '')} | {e['created_at'][:10]} |"
        )

    lines.append("")
    lines.append("*Maintained automatically by `@scribe` via StratLab.*")
    return "\n".join(lines)


def ledger_digest() -> dict[str, Any]:
    """What was tried, promoted, killed and parked, and which gate fails most often."""
    entries = query_ledger()
    counts = {"PROMOTE": 0, "KILL": 0, "PARK": 0}
    gate_fails: dict[str, int] = {}
    for e in entries:
        counts[e["verdict"]] = counts.get(e["verdict"], 0) + 1
        for g in (e.get("failed_gates") or "").split(","):
            g = g.strip()
            if g and g != "None":
                gate_fails[g] = gate_fails.get(g, 0) + 1
    common = max(gate_fails, key=gate_fails.get) if gate_fails else None
    return {
        "decisions": len(entries),
        "specs": sorted({f"{e['spec_id']}@v{e['version']}" for e in entries}),
        "promoted": counts.get("PROMOTE", 0),
        "killed": counts.get("KILL", 0),
        "parked": counts.get("PARK", 0),
        "gate_failures": gate_fails,
        "most_common_failure": common,
    }


def render_digest(d: dict[str, Any]) -> str:
    if not d["decisions"]:
        return "Digest: nothing in the ledger yet."
    lines = [
        f"Digest: {d['decisions']} decisions on {len(d['specs'])} spec versions",
        f"  promoted {d['promoted']} | killed {d['killed']} | parked {d['parked']}",
    ]
    if d["most_common_failure"]:
        lines.append(f"  most common failure: {d['most_common_failure']} ({d['gate_failures'][d['most_common_failure']]}x)")
    return "\n".join(lines)
