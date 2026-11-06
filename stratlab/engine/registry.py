"""SQLite registry of research runs (sweep, walk-forward, robust, gates) and run folders."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from stratlab.config import get_registry_db, get_runs_dir
from stratlab.spec.models import StrategySpec


def spec_hash(spec: StrategySpec) -> str:
    """Content hash of a spec, so results from an edited file are never reused."""
    blob = json.dumps(spec.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:10]


def new_run_id(kind: str, spec: StrategySpec) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    return f"{kind}_{spec.id}_v{spec.version}_{stamp}"


def _conn() -> sqlite3.Connection:
    db = get_registry_db()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS research_runs (
            run_id TEXT PRIMARY KEY, kind TEXT NOT NULL, spec_id TEXT NOT NULL,
            version INTEGER NOT NULL, spec_hash TEXT NOT NULL, path TEXT NOT NULL,
            summary_json TEXT, created_at TEXT NOT NULL)"""
    )
    return conn


def to_jsonable(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): to_jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [to_jsonable(v) for v in o]
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        v = float(o)
        return None if v != v else v
    if isinstance(o, float) and o != o:
        return None
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.isoformat()
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, Path):
        return str(o)
    return o


def save_research_run(kind: str, spec: StrategySpec, summary: dict[str, Any], files: dict[str, Any] | None = None,
                      run_id: str | None = None) -> tuple[str, Path]:
    """Write runs/<run_id>/<kind>.json (+ files) and register it."""
    run_id = run_id or new_run_id(kind, spec)
    path = get_runs_dir() / run_id
    path.mkdir(parents=True, exist_ok=True)
    summary = to_jsonable({"run_id": run_id, "kind": kind, "spec_id": spec.id, "version": spec.version,
                           "spec_hash": spec_hash(spec), **summary})
    (path / f"{kind}.json").write_text(json.dumps(summary, indent=2))
    for name, obj in (files or {}).items():
        if isinstance(obj, pd.DataFrame):
            obj.to_csv(path / name, index=False)
        else:
            (path / name).write_text(obj if isinstance(obj, str) else json.dumps(to_jsonable(obj), indent=2))
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO research_runs VALUES (?,?,?,?,?,?,?,?)",
            (run_id, kind, spec.id, spec.version, spec_hash(spec), str(path), json.dumps(summary),
             datetime.now(timezone.utc).isoformat()),
        )
    return run_id, path


def latest_research_run(kind: str, spec: StrategySpec) -> dict[str, Any] | None:
    """Newest run of `kind` for this exact spec content, or None."""
    with _conn() as c:
        row = c.execute(
            "SELECT summary_json FROM research_runs WHERE kind=? AND spec_id=? AND version=? AND spec_hash=? "
            "ORDER BY created_at DESC LIMIT 1",
            (kind, spec.id, spec.version, spec_hash(spec)),
        ).fetchone()
    return json.loads(row[0]) if row else None


def list_research_runs(kind: str | None = None) -> list[dict[str, Any]]:
    with _conn() as c:
        q = "SELECT summary_json FROM research_runs"
        rows = c.execute(q + (" WHERE kind=?" if kind else "") + " ORDER BY created_at ASC",
                         (kind,) if kind else ()).fetchall()
    return [json.loads(r[0]) for r in rows]


def latest_by_id(kind: str, spec_id: str, version: int | None = None) -> dict[str, Any] | None:
    """Newest run of `kind` for a spec id (and version), whatever its content hash."""
    with _conn() as c:
        if version is None:
            row = c.execute("SELECT summary_json FROM research_runs WHERE kind=? AND spec_id=? "
                            "ORDER BY created_at DESC LIMIT 1", (kind, spec_id)).fetchone()
        else:
            row = c.execute("SELECT summary_json FROM research_runs WHERE kind=? AND spec_id=? AND version=? "
                            "ORDER BY created_at DESC LIMIT 1", (kind, spec_id, version)).fetchone()
    return json.loads(row[0]) if row else None
