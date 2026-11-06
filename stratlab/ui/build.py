"""Collect everything StratLab has computed into one self-contained HTML page.

No server, no CDN, no network: the data is embedded as JSON and drawn with inline SVG, so
the file can be attached in the room, opened from disk, or shown to a judge offline.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from stratlab import __version__
from stratlab.config import PROJECT_ROOT, get_artifacts_dir, get_runs_dir, get_specs_dir
from stratlab.engine.ledger import ledger_digest, query_ledger
from stratlab.engine.registry import latest_by_id, to_jsonable
from stratlab.research.charter import load_charter

TEMPLATE = Path(__file__).with_name("desk.html")


def _spec_files() -> list[tuple[str, Path, str]]:
    seen: dict[str, tuple[str, Path, str]] = {}
    for root, origin in ((PROJECT_ROOT / "examples" / "specs", "example"), (get_specs_dir(), "workspace")):
        if not root.exists():
            continue
        for f in sorted(root.glob("S-*/v*.yaml")):
            m = re.fullmatch(r"v(\d+)\.yaml", f.name)
            if m:
                ref = f"{f.parent.name}@v{int(m.group(1))}"
                seen[ref] = (ref, f, origin)  # workspace copies win over examples
    return sorted(seen.values(), key=lambda t: (t[0].split("@")[0], int(t[0].split("@v")[1])))


def _equity(run_id: str | None, max_points: int = 700) -> dict[str, Any] | None:
    if not run_id:
        return None
    p = get_runs_dir() / run_id / "equity.csv"
    m = get_runs_dir() / run_id / "metrics.json"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    step = max(1, len(df) // max_points)
    df = df.iloc[::step]
    meta = json.loads(m.read_text()) if m.exists() else {}
    return {"t": df["timestamp"].astype(str).str[:10].tolist(), "v": df["equity"].round(2).tolist(),
            "oos_start": (meta.get("windows") or {}).get("oos_start", "")[:10]}


def _heatmap(sweep: dict | None) -> dict[str, Any] | None:
    if not sweep or len(sweep.get("tunable", [])) < 2:
        return None
    p = get_runs_dir() / sweep["run_id"] / "sweep.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    x, y = sorted(sweep["tunable"], key=lambda k: -df[k].nunique())[:2]
    # Show the best-scoring combo per cell, the one the sweep would actually pick.
    if "eligible" not in df:
        df["eligible"] = df["trades"] >= sweep.get("min_trades", 0)
    df = df.sort_values(["eligible", "profit_factor"], ascending=False)
    first = df.groupby([y, x], as_index=False).first()
    piv = first.pivot(index=y, columns=x, values="profit_factor")
    ntr = first.pivot(index=y, columns=x, values="trades").reindex(index=piv.index, columns=piv.columns)
    best = sweep.get("best_params", {})
    return {"x": x, "y": y, "xs": [float(v) for v in piv.columns], "ys": [float(v) for v in piv.index],
            "z": [[None if pd.isna(v) else round(float(v), 2) for v in row] for row in piv.values],
            "n": [[None if pd.isna(v) else int(v) for v in row] for row in ntr.values],
            "min_trades": sweep.get("min_trades", 0),
            "best": [best.get(x), best.get(y)], "evaluated": sweep.get("evaluated"), "grid": sweep.get("grid_size")}


def collect() -> dict[str, Any]:
    cases = []
    for ref, path, origin in _spec_files():
        raw = yaml.safe_load(path.read_text()) or {}
        sid, ver = ref.split("@v")
        gates = latest_by_id("gates", sid, int(ver))
        sweep = latest_by_id("sweep", sid, int(ver))
        wf = latest_by_id("walkforward", sid, int(ver))
        robust = latest_by_id("robust", sid, int(ver))
        parity = latest_by_id("parity", sid, int(ver))
        pine = get_artifacts_dir() / f"{sid}_v{ver}.pine"
        cases.append({
            "ref": ref, "id": sid, "version": int(ver), "origin": origin, "name": raw.get("name", ref),
            "market": raw.get("market", {}), "period": raw.get("period", {}), "spec_yaml": path.read_text(),
            "gates": gates, "walkforward": wf, "robust": robust, "parity": parity,
            "equity": _equity(gates.get("backtest_run_id") if gates else None),
            "heatmap": _heatmap(sweep),
            "pine": pine.read_text() if pine.exists() else None,
        })
    return to_jsonable({
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "version": __version__,
        "charter": load_charter(),
        "cases": cases,
        "ledger": query_ledger(),
        "digest": ledger_digest(),
    })


def build_desk(out: Path | None = None) -> Path:
    data = json.dumps(collect(), default=str).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__STRATLAB_DATA__*/null", data)
    out = out or get_artifacts_dir() / "stratlab-desk.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
