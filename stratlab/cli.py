"""Command line interface for StratLab.

Agents run these commands in their shells and paste the output into the room, so every
command prints short human text, `--json` prints machine-readable JSON, and any failure is
one line on stderr with a non-zero exit code.
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console
from rich.table import Table

from stratlab import __version__
from stratlab.config import (
    PROJECT_ROOT,
    get_artifacts_dir,
    get_runs_dir,
    get_specs_dir,
    init_environment,
)
from stratlab.engine.registry import to_jsonable
from stratlab.spec.models import StrategySpec
from stratlab.spec.validate import validate_spec_file

app = typer.Typer(name="stratlab", help="StratLab: adversarial trading-strategy research desk", add_completion=False)
spec_app = typer.Typer(help="Create, find, validate and compare StrategySpec files")
data_app = typer.Typer(help="Fetch and cache OHLCV market data")
ledger_app = typer.Typer(help="The Strategy Ledger: verdicts and history")
app.add_typer(spec_app, name="spec")
app.add_typer(data_app, name="data")
app.add_typer(ledger_app, name="ledger")

console = Console(soft_wrap=True)
err_console = Console(stderr=True, soft_wrap=True)
EXAMPLES_DIR = PROJECT_ROOT / "examples" / "specs"
_REF = re.compile(r"^(S-\d+)(?:@v?(\d+))?$")


class CommandError(Exception):
    """A user-facing error: printed as one line, exit code 1."""


def handled(fn):
    """Turn any exception into a one-line error the agents can post in chat."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except typer.Exit:
            raise
        except FileNotFoundError as e:
            err_console.print(f"Error: {e}", markup=False)
        except (CommandError, ValueError, KeyError) as e:
            msg = e.args[0] if isinstance(e, KeyError) and e.args else e
            err_console.print(f"Error: {msg}", markup=False)
        except Exception as e:  # noqa: BLE001 - last resort, still one line
            err_console.print(f"Error: {type(e).__name__}: {e}", markup=False)
        raise typer.Exit(code=1)

    return wrapper


def emit_json(obj: Any) -> None:
    typer.echo(json.dumps(to_jsonable(obj), indent=2, default=str))


@app.callback()
def main_callback():
    """Workspace: $STRATLAB_HOME (default ~/stratlab-home)."""
    init_environment()


@app.command()
def version():
    """Show the StratLab version."""
    typer.echo(f"StratLab v{__version__}")


# ---------------------------------------------------------------- spec resolution
def _versions(folder: Path) -> list[int]:
    return sorted(int(m.group(1)) for f in folder.glob("v*.yaml") if (m := re.fullmatch(r"v(\d+)\.yaml", f.name)))


def resolve_spec_path(target: str) -> Path:
    """A file path, `S-012@v2`, `S-012@2` or `S-012` (latest version).

    Looks in $STRATLAB_HOME/specs first (shared by every agent), then the repo examples, so it
    works from any agent's working directory.
    """
    p = Path(target).expanduser()
    if p.suffix in (".yaml", ".yml") or p.exists():
        if not p.exists():
            raise CommandError(f"spec file not found: {target}")
        return p
    m = _REF.match(target.strip())
    if not m:
        raise CommandError(f"'{target}' is not a spec path or reference like S-012@v2")
    spec_id, ver = m.group(1), m.group(2)
    roots = [get_specs_dir(), EXAMPLES_DIR]
    for root in roots:
        folder = root / spec_id
        if not folder.exists():
            continue
        if ver:
            f = folder / f"v{int(ver)}.yaml"
            if f.exists():
                return f
        elif _versions(folder):
            return folder / f"v{_versions(folder)[-1]}.yaml"
    raise CommandError(f"spec {target} not found in {get_specs_dir()} or {EXAMPLES_DIR}")


def load_spec(target: str) -> StrategySpec:
    path = resolve_spec_path(target)
    res = validate_spec_file(path)
    if not res.is_valid:
        raise CommandError(f"{path.name} is invalid: " + " | ".join(res.errors))
    return res.spec


def parse_params(spec: StrategySpec, params: str | None) -> dict[str, Any] | None:
    if not params:
        return None
    out: dict[str, Any] = {}
    for item in re.split(r"[,\s]+", params.strip()):
        if not item:
            continue
        if "=" not in item:
            raise CommandError(f"bad --params item '{item}': use name=value,name=value")
        k, v = item.split("=", 1)
        if k not in spec.params:
            raise CommandError(f"unknown param '{k}'. Params of {spec.id}@v{spec.version}: {', '.join(spec.params)}")
        try:
            out[k] = float(v)
        except ValueError:
            raise CommandError(f"param {k}: '{v}' is not a number") from None
    return out


def next_spec_id() -> str:
    ids = [0]
    for root in (get_specs_dir(), EXAMPLES_DIR):
        if root.exists():
            ids += [int(m.group(1)) for d in root.iterdir() if (m := re.fullmatch(r"S-(\d+)", d.name))]
    return f"S-{max(ids) + 1:03d}"


# ---------------------------------------------------------------- spec
@spec_app.command("validate")
@handled
def spec_validate(target: str = typer.Argument(..., help="Spec path or reference, e.g. S-012@v1"),
                  as_json: bool = typer.Option(False, "--json")):
    """Validate a spec against the schema and the supported vocabulary."""
    path = resolve_spec_path(target)
    result = validate_spec_file(path)
    if as_json:
        emit_json({**result.to_dict(), "path": str(path)})
    elif result.is_valid:
        console.print(f"[bold green]PASS[/bold green]: Spec '{result.spec.id}@v{result.spec.version}' ({result.spec.name}) is valid.")
    else:
        err_console.print(f"FAIL: {path} has errors:", markup=False)
        for err in result.errors:
            err_console.print(f"  - {err}", markup=False)
    if not result.is_valid:
        raise typer.Exit(code=1)


@spec_app.command("schema")
def spec_schema():
    """Print the StrategySpec JSON schema."""
    typer.echo(json.dumps(StrategySpec.model_json_schema(), indent=2))


@spec_app.command("path")
@handled
def spec_path(target: str = typer.Argument(..., help="Reference, e.g. S-012@v2")):
    """Print the file a reference resolves to (useful before editing it)."""
    typer.echo(str(resolve_spec_path(target)))


@spec_app.command("list")
@handled
def spec_list(as_json: bool = typer.Option(False, "--json")):
    """List every spec version in the shared workspace and the examples."""
    rows = []
    for root, origin in ((get_specs_dir(), "workspace"), (EXAMPLES_DIR, "example")):
        if root.exists():
            for folder in sorted(root.glob("S-*")):
                for v in _versions(folder):
                    rows.append({"ref": f"{folder.name}@v{v}", "origin": origin, "path": str(folder / f"v{v}.yaml")})
    if as_json:
        emit_json(rows)
        return
    for r in rows:
        console.print(f"{r['ref']:<12} {r['origin']:<10} {r['path']}", markup=False)


@spec_app.command("diff")
@handled
def spec_diff(spec_a: str, spec_b: str, as_json: bool = typer.Option(False, "--json")):
    """Compare two specs (paths or references)."""
    from stratlab.spec.diff import diff_specs, render_diff_text

    diff = diff_specs(resolve_spec_path(spec_a), resolve_spec_path(spec_b))
    emit_json(diff) if as_json else console.print(render_diff_text(diff), markup=False)


SKELETON = {
    "direction": "long",
    "market": {"symbol": "BTCUSDT", "exchange": "binance", "tv_symbol": "BINANCE:BTCUSDT", "timeframe": "4h"},
    "period": {"start": "2021-01-01", "end": "2025-12-31", "oos_fraction": 0.3},
    "params": {"fast_len": {"default": 20, "range": [10, 50, 10]}, "slow_len": {"default": 100, "range": [60, 200, 20]},
               "atr_len": {"default": 14, "fixed": True}, "atr_stop": {"default": 2.0, "range": [1.0, 3.0, 0.5]}},
    "indicators": {"fast_ma": {"fn": "ema", "src": "close", "len": "$fast_len"},
                   "slow_ma": {"fn": "ema", "src": "close", "len": "$slow_len"},
                   "atr": {"fn": "atr", "len": "$atr_len"}},
    "entry": {"long": {"crosses_above": ["fast_ma", "slow_ma"]}, "short": {"crosses_below": ["fast_ma", "slow_ma"]}},
    "exit": {"stop": {"atr_mult": "$atr_stop"}, "opposite_signal": True},
    "risk": {"sizing": "percent_equity", "value": 100, "initial_capital": 10000, "pyramiding": 0},
    "costs": {"commission_pct": 0.1, "slippage_ticks": 1, "tick_size": 0.01},
}


@spec_app.command("new")
@handled
def spec_new(
    spec_id: str | None = typer.Option(None, "--id", help="Strategy ID; default: next free S-nnn"),
    from_spec: str | None = typer.Option(None, "--from", help="Copy this spec (e.g. S-012@v1) as the next version"),
    name: str = typer.Option("New Strategy", "--name"),
    as_json: bool = typer.Option(False, "--json"),
):
    """Create specs in the SHARED workspace ($STRATLAB_HOME/specs) so every agent can see them."""
    if from_spec:
        src = resolve_spec_path(from_spec)
        raw = yaml.safe_load(src.read_text())
        spec_id = raw["id"]
        folder = get_specs_dir() / spec_id
        known = _versions(folder) + _versions(EXAMPLES_DIR / spec_id) + [int(raw["version"])]
        new_version = max(known) + 1
        text = re.sub(r"(?m)^version:\s*\d+", f"version: {new_version}", src.read_text(), count=1)
    else:
        spec_id = spec_id or next_spec_id()
        if not re.fullmatch(r"S-\d+", spec_id):
            raise CommandError("--id must look like S-030")
        folder = get_specs_dir() / spec_id
        new_version = 1
        text = yaml.safe_dump({"id": spec_id, "version": 1, "name": name, **SKELETON}, sort_keys=False)
    out = folder / f"v{new_version}.yaml"
    if out.exists():
        raise CommandError(f"{out} already exists")
    folder.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    ref = f"{spec_id}@v{new_version}"
    emit_json({"ref": ref, "path": str(out)}) if as_json else console.print(f"Created {ref}: {out}", markup=False)


# ---------------------------------------------------------------- data
@data_app.command("fetch")
@handled
def data_fetch(symbol: str, timeframe: str = typer.Argument("4h"),
               start_date: str = typer.Option("2021-01-01", "--from"), end_date: str | None = typer.Option(None, "--to"),
               as_json: bool = typer.Option(False, "--json")):
    """Fetch OHLCV from Binance (ccxt, no key) with a yfinance fallback, into the cache."""
    from stratlab.data.fetch import fetch_and_cache_ohlcv

    path = fetch_and_cache_ohlcv(symbol, timeframe, start_date, end_date)
    emit_json({"success": True, "path": str(path)}) if as_json else console.print(f"Cached {symbol} {timeframe} -> {path}", markup=False)


# ---------------------------------------------------------------- research
def _metrics_line(label: str, m: dict) -> str:
    return (f"{label:<4} trades {m['trades']:>3} | net {m['net_profit_pct']:+7.1f}% | PF {m['profit_factor']:5.2f} | "
            f"win {m['win_rate_pct']:5.1f}% | maxDD {m['max_drawdown_pct']:5.1f}% | Sharpe {m['sharpe_ratio']:5.2f}")


@app.command("backtest")
@handled
def backtest_cmd(target: str, params: str | None = typer.Option(None, "--params", help="e.g. 'rsi_len=14,atr_stop=2.5'"),
                 as_json: bool = typer.Option(False, "--json")):
    """In-sample / out-of-sample backtest (spec defaults unless --params)."""
    from stratlab.engine.backtest import run_backtest

    spec = load_spec(target)
    res = run_backtest(spec, param_overrides=parse_params(spec, params), params_source="explicit" if params else "defaults")
    if as_json:
        emit_json(res)
        return
    typer.echo(f"{spec.id}@v{spec.version} backtest  run_id {res['run_id']}")
    typer.echo(f"params {res['params']}")
    typer.echo(_metrics_line("IS", res["is"]))
    if res["oos"]:
        typer.echo(_metrics_line("OOS", res["oos"]))
    typer.echo(f"files {res['run_dir']}")


@app.command("sweep")
@handled
def sweep_cmd(target: str, budget: int = typer.Option(200, "--budget"),
              min_trades: int | None = typer.Option(None, "--min-trades", help="Default: Lab Charter sweep.min_trades"),
              as_json: bool = typer.Option(False, "--json")):
    """Parameter sweep scored on in-sample only. The best eligible combo becomes the candidate."""
    from stratlab.research.sweep import run_sweep

    spec = load_spec(target)
    df = run_sweep(spec, budget=budget, min_trades=min_trades)
    s = df.attrs["summary"]
    if as_json:
        emit_json({**s, "run_id": df.attrs.get("run_id"), "top_10": df.head(10).to_dict(orient="records")})
        return
    typer.echo(f"{spec.id}@v{spec.version} sweep  run_id {df.attrs.get('run_id')}")
    typer.echo(f"evaluated {s['evaluated']} of {s['grid_size']} combos on IS; {s['eligible']} with >= {s['min_trades']} trades")
    for i, row in df.head(5).iterrows():
        p = ", ".join(f"{k}={row[k]}" for k in s["tunable"]) or "defaults"
        flag = "" if row["eligible"] else "  (too few trades)"
        typer.echo(f"#{i + 1} {p} -> PF {row['profit_factor']:.2f} | net {row['net_profit_pct']:+.1f}% | trades {int(row['trades'])}{flag}")
    if not s["best_is_eligible"]:
        typer.echo("warning: no combo reached the minimum trade count; the candidate is unreliable")


@app.command("walkforward")
@handled
def walkforward_cmd(target: str,
                    best: bool = typer.Option(True, "--best/--no-best", help="Re-pick the best params in every window (always on)"),
                    as_json: bool = typer.Option(False, "--json")):
    """Rolling walk-forward (24-month IS / 6-month OOS by default, from the Lab Charter)."""
    from stratlab.research.walkforward import run_walkforward

    spec = load_spec(target)
    wf = run_walkforward(spec)
    if as_json:
        emit_json(wf)
        return
    typer.echo(f"{spec.id}@v{spec.version} walk-forward  run_id {wf.get('run_id')}")
    typer.echo(f"WFE {wf['walk_forward_efficiency']:.2f} | profitable windows {wf['pct_profitable_windows']:.0f}% of {wf['total_windows']}")
    for w in wf["windows"]:
        typer.echo(f"W{w['window']} {w['oos_start']}..{w['oos_end']}: IS PF {w['is_pf']:.2f} -> OOS PF {w['oos_pf']:.2f}, "
                   f"OOS net {w['oos_net_pct']:+.1f}% ({w['oos_trades']} trades)")


@app.command("robust")
@handled
def robust_cmd(target: str, params: str | None = typer.Option(None, "--params"), as_json: bool = typer.Option(False, "--json")):
    """Monte Carlo, 2x cost stress and parameter neighbourhood on the candidate params."""
    from stratlab.research.robust import run_robustness_battery

    spec = load_spec(target)
    r = run_robustness_battery(spec, param_overrides=parse_params(spec, params))
    if as_json:
        emit_json(r)
        return
    mc, cost, nb = r["monte_carlo"], r["cost_stress"], r["neighbourhood"]
    typer.echo(f"{spec.id}@v{spec.version} robustness  run_id {r.get('run_id')}")
    typer.echo(f"candidate {r['params']} (from {r['params_source']})")
    typer.echo(f"Monte Carlo ({mc['n_simulations']} runs, {mc['n_trades']} trades): 95th pct max DD {mc['pct_95th_max_drawdown']:.1f}%, "
               f"5th pct final equity ${mc['pct_5th_final_equity']:,.0f}")
    typer.echo(f"{cost['multiplier']:g}x costs: PF IS {cost['in_sample_pf']:.2f} | OOS {cost['out_of_sample_pf']:.2f} | full {cost['full_period_pf']:.2f}")
    if nb["stability_ratio"] is None:
        typer.echo("neighbourhood: n/a (no tunable params)")
    else:
        typer.echo(f"neighbourhood: candidate IS PF {nb['best_pf']:.2f}, median of {nb['tested_neighbours']} neighbours "
                   f"{nb['median_neighbour_pf']:.2f}, ratio {nb['stability_ratio']:.2f}")


@app.command("gates")
@handled
def gates_cmd(
    target: str,
    params: str | None = typer.Option(None, "--params", help="Audit these params instead of the latest sweep best"),
    set_: list[str] = typer.Option([], "--set", help="Charter override, e.g. --set g2_out_of_sample.min_oos_pf=1.3"),
    strict: bool = typer.Option(False, "--strict", help="Exit 1 when the verdict is FAIL (for CI)"),
    as_json: bool = typer.Option(False, "--json"),
):
    """Audit the candidate against the six Lab Charter gates."""
    from stratlab.research.gates import GATE_TITLES, evaluate_gates

    spec = load_spec(target)
    overrides = {}
    for item in set_:
        if "=" not in item:
            raise CommandError(f"bad --set '{item}', use section.key=value")
        k, v = item.split("=", 1)
        overrides[k] = v
    audit = evaluate_gates(spec, param_overrides=parse_params(spec, params), charter_overrides=overrides)
    if as_json:
        emit_json(audit)
    else:
        typer.echo(f"{spec.id}@v{spec.version} VERDICT: {audit['verdict']} ({audit['passed_count']} of {audit['total_gates']} gates)")
        typer.echo(f"candidate {audit['params']} (from {audit['params_source']})  gates run {audit.get('gates_run_id')}")
        for key, g in audit["gates"].items():
            typer.echo(f"  {'PASS' if g['pass'] else 'FAIL'} {GATE_TITLES[key]}: {g['detail']}")
    if strict and audit["verdict"] != "PASS":
        raise typer.Exit(code=1)


@app.command("chart")
@handled
def chart_cmd(target: str, output_dir: str | None = typer.Option(None, "--out"), as_json: bool = typer.Option(False, "--json")):
    """Equity + drawdown, sweep heatmap, walk-forward bars and a metrics card (PNG, dark theme)."""
    import pandas as pd

    from stratlab.charts import (
        plot_equity_and_drawdown,
        plot_param_heatmap,
        plot_walkforward_windows,
        render_metrics_card,
    )
    from stratlab.engine.backtest import run_backtest
    from stratlab.engine.registry import latest_research_run
    from stratlab.research.robust import candidate_params
    from stratlab.research.walkforward import run_walkforward

    spec = load_spec(target)
    out = Path(output_dir) if output_dir else get_artifacts_dir() / f"{spec.id}_v{spec.version}"
    out.mkdir(parents=True, exist_ok=True)
    params, source = candidate_params(spec)
    bt = run_backtest(spec, param_overrides=params, params_source=source)
    eq = pd.read_csv(Path(bt["run_dir"]) / "equity.csv")
    eq["timestamp"] = pd.to_datetime(eq["timestamp"])
    charts = {"equity": str(plot_equity_and_drawdown(eq, eq["equity"].to_numpy(), out / "equity.png",
                                                     title=f"{spec.id} v{spec.version} equity ({source.split(':')[0]} params)"))}
    metrics = json.loads((Path(bt["run_dir"]) / "metrics.json").read_text())
    charts["card"] = str(render_metrics_card(spec.id, spec.version, metrics, equity_curve=eq["equity"].to_numpy(),
                                             output_path=out / "card.png"))
    sweep = latest_research_run("sweep", spec)
    if sweep and len(sweep.get("tunable", [])) >= 2:
        df = pd.read_csv(get_runs_dir() / sweep["run_id"] / "sweep.csv")
        axes = sorted(sweep["tunable"], key=lambda k: -df[k].nunique())[:2]
        charts["heatmap"] = str(plot_param_heatmap(df, axes[0], axes[1], "profit_factor", out / "heatmap.png",
                                                   title=f"{spec.id} v{spec.version} IS profit factor"))
    wf = latest_research_run("walkforward", spec) or run_walkforward(spec)
    if wf.get("windows"):
        charts["walkforward"] = str(plot_walkforward_windows(wf, out / "walkforward.png"))
    emit_json({"success": True, "charts": charts}) if as_json else [typer.echo(f"{k}: {v}") for k, v in charts.items()]


# ---------------------------------------------------------------- Pine / TradingView
@app.command("pine")
@handled
def pine_cmd(
    target: str = typer.Argument(..., help="Spec reference, or 'import'"),
    file_path: str | None = typer.Argument(None, help="Pine file to import"),
    out: str | None = typer.Option(None, "-o", "--out"),
    print_code: bool = typer.Option(False, "--print"),
    as_json: bool = typer.Option(False, "--json"),
):
    """Generate Pine Script v6 from a spec, or `pine import file.pine` into a spec draft."""
    from stratlab.pine.generate import generate_pine_script
    from stratlab.pine.importer import import_pine_file

    if target == "import":
        if not file_path:
            raise CommandError("usage: stratlab pine import <file.pine>")
        res = import_pine_file(file_path)
        if as_json:
            emit_json(res)
        elif res["supported"]:
            typer.echo(f"Import Succeeded: Strategy '{res['spec_dict']['name']}'")
            typer.echo(yaml.safe_dump(res["spec_dict"], sort_keys=False))
        else:
            typer.echo("Partial import. Unsupported constructs:")
            for f in res["unsupported_features"]:
                typer.echo(f"  - {f}")
        return
    spec = load_spec(target)
    code = generate_pine_script(spec)
    path = Path(out) if out else get_artifacts_dir() / f"{spec.id}_v{spec.version}.pine"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code, encoding="utf-8")
    if print_code:
        typer.echo(code)
    elif as_json:
        emit_json({"success": True, "path": str(path)})
    else:
        typer.echo(f"Generated Pine v6 -> {path}")
        typer.echo(f"inputs {', '.join(spec.params)} | commission {spec.costs.commission_pct}% | slippage {spec.costs.slippage_ticks} tick(s)")


@app.command("parity")
@handled
def parity_cmd(target: str, tv_csv: str = typer.Argument(..., help="TradingView List of Trades CSV"),
               params: str | None = typer.Option(None, "--params", help="Inputs used in TradingView, if not the defaults"),
               as_json: bool = typer.Option(False, "--json")):
    """Compare the engine with a TradingView export of the generated Pine."""
    from stratlab.tv.parity import check_trade_parity, render_parity_report

    spec = load_spec(target)
    rep = check_trade_parity(spec, tv_csv, param_overrides=parse_params(spec, params))
    emit_json(rep) if as_json else typer.echo(render_parity_report(rep))


# ---------------------------------------------------------------- ledger
@ledger_app.command("add")
@handled
def ledger_add_cmd(target: str, verdict: str = typer.Option(..., "--verdict", help="promote, kill or park"),
                   by: str = typer.Option(..., "--by"), note: str = typer.Option("", "--note"),
                   as_json: bool = typer.Option(False, "--json")):
    """Record a human verdict."""
    from stratlab.engine.ledger import add_ledger_entry

    m = _REF.match(target)
    if not m or not m.group(2):
        raise CommandError("use a versioned reference, e.g. S-012@v2")
    res = add_ledger_entry(f"{m.group(1)}@v{int(m.group(2))}", verdict, by, note)
    if as_json:
        emit_json(res)
        return
    typer.echo(f"Ledger Updated: {res['spec_id']}@v{res['version']} -> {res['verdict']} by {res['decided_by']}")
    if res.get("oos_pf") is not None:
        typer.echo(f"OOS PF {res['oos_pf']:.2f} | OOS max DD {res['oos_max_dd']:.1f}% | failed gates: {res['failed_gates']}")


@ledger_app.command("render")
def ledger_render_cmd():
    """Markdown for the Strategy Ledger room document."""
    from stratlab.engine.ledger import render_ledger_markdown

    typer.echo(render_ledger_markdown())


@ledger_app.command("query")
@handled
def ledger_query_cmd(spec: str | None = typer.Option(None, "--spec"), as_json: bool = typer.Option(False, "--json")):
    """Ledger entries, optionally for one spec ID."""
    from stratlab.engine.ledger import query_ledger

    entries = query_ledger(spec)
    if as_json:
        emit_json(entries)
        return
    if not entries:
        typer.echo("No ledger entries found.")
        return
    table = Table(title="Strategy Ledger", header_style="bold magenta")
    for col in ("ID", "Ver", "Verdict", "By", "OOS PF", "OOS DD%", "Failed Gates", "Date"):
        table.add_column(col)
    for e in entries:
        table.add_row(e["spec_id"], f"v{e['version']}", e["verdict"], e["decided_by"],
                      f"{e['oos_pf']:.2f}" if e.get("oos_pf") is not None else "-",
                      f"{e['oos_max_dd']:.1f}" if e.get("oos_max_dd") is not None else "-",
                      e.get("failed_gates") or "None", e["created_at"][:10])
    console.print(table)


@ledger_app.command("digest")
@handled
def ledger_digest_cmd(as_json: bool = typer.Option(False, "--json")):
    """What was tried, promoted, killed and parked, and the most common failing gate."""
    from stratlab.engine.ledger import ledger_digest, render_digest

    d = ledger_digest()
    emit_json(d) if as_json else typer.echo(render_digest(d))


# ---------------------------------------------------------------- desk UI and demo
@app.command("ui")
@handled
def ui_cmd(out: str | None = typer.Option(None, "--out", help="Default: $STRATLAB_HOME/artifacts/stratlab-desk.html"),
           serve: bool = typer.Option(False, "--serve", help="Also serve it on http://127.0.0.1:PORT"),
           port: int = typer.Option(8765, "--port")):
    """Build the StratLab Desk: one offline HTML page with every spec, gate audit, chart and verdict."""
    from stratlab.ui.build import build_desk

    path = build_desk(Path(out) if out else None)
    typer.echo(f"StratLab Desk -> {path}")
    if serve:
        import functools as ft
        import http.server

        handler = ft.partial(http.server.SimpleHTTPRequestHandler, directory=str(path.parent))
        typer.echo(f"serving http://127.0.0.1:{port}/{path.name}  (Ctrl+C to stop)")
        http.server.ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()


@app.command("demo")
@handled
def demo_cmd(budget: int = typer.Option(120, "--budget")):
    """Offline replay of the room: what each agent would post for S-012 v1 and v2. No Switch, no network."""
    from stratlab.demo import run_demo

    run_demo(budget=budget)


if __name__ == "__main__":
    app()
