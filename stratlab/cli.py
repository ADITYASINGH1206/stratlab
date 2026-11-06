"""Command line interface for StratLab."""

import json
from pathlib import Path
from typing import Any

import numpy as np
import typer
from rich.console import Console

from stratlab import __version__
from stratlab.charts import (
    plot_equity_and_drawdown,
    plot_walkforward_windows,
    render_metrics_card,
)
from stratlab.config import get_artifacts_dir, get_specs_dir, init_environment
from stratlab.data.cache import load_ohlcv
from stratlab.data.fetch import fetch_and_cache_ohlcv
from stratlab.engine.backtest import run_backtest
from stratlab.pine.generate import generate_pine_script
from stratlab.pine.importer import import_pine_file
from stratlab.research.gates import evaluate_gates
from stratlab.research.robust import run_robustness_battery
from stratlab.research.sweep import run_sweep
from stratlab.research.walkforward import run_walkforward
from stratlab.spec.diff import diff_specs, render_diff_text
from stratlab.spec.models import StrategySpec
from stratlab.spec.validate import validate_spec_file
from stratlab.tv.parity import check_trade_parity, render_parity_report

app = typer.Typer(
    name="stratlab",
    help="StratLab: Adversarial Trading Strategy Research Desk CLI",
    add_completion=False,
)
spec_app = typer.Typer(help="Manage and validate StrategySpec files")
data_app = typer.Typer(help="Fetch and cache historical OHLCV market data")

app.add_typer(spec_app, name="spec")
app.add_typer(data_app, name="data")

console = Console()
err_console = Console(stderr=True)


@app.callback()
def main_callback():
    """StratLab CLI initialized."""
    init_environment()


@app.command()
def version():
    """Display the current StratLab version."""
    typer.echo(f"StratLab v{__version__}")


# ==========================================
# Spec Subcommands
# ==========================================

@spec_app.command("validate")
def spec_validate(
    spec_path: str = typer.Argument(..., help="Path to the strategy spec YAML file"),
    as_json: bool = typer.Option(False, "--json", help="Output machine-readable JSON"),
):
    """Validate a StrategySpec YAML file against schema and vocabulary constraints."""
    result = validate_spec_file(spec_path)
    output_data = result.to_dict()

    if as_json:
        typer.echo(json.dumps(output_data, indent=2))
    else:
        if result.is_valid:
            console.print(f"[bold green]PASS[/bold green]: Spec '{result.spec.id}@v{result.spec.version}' ({result.spec.name}) is valid.")
        else:
            err_console.print(f"[bold red]FAIL[/bold red]: Spec at '{spec_path}' has errors:")
            for err in result.errors:
                err_console.print(f"  - [red]{err}[/red]")

    if not result.is_valid:
        raise typer.Exit(code=1)


@spec_app.command("schema")
def spec_schema():
    """Output the JSON schema for StrategySpec."""
    schema = StrategySpec.model_json_schema()
    typer.echo(json.dumps(schema, indent=2))


@spec_app.command("diff")
def spec_diff(
    spec_a: str = typer.Argument(..., help="Path to spec A (or base version)"),
    spec_b: str = typer.Argument(..., help="Path to spec B (or revised version)"),
    as_json: bool = typer.Option(False, "--json", help="Output machine-readable JSON"),
):
    """Compare two StrategySpec files and show parameter, indicator, and rule changes."""
    try:
        diff = diff_specs(spec_a, spec_b)
    except Exception as e:
        err_console.print(f"[bold red]Error[/bold red]: {e}")
        raise typer.Exit(code=1)

    if as_json:
        typer.echo(json.dumps(diff, indent=2))
    else:
        console.print(render_diff_text(diff))


@spec_app.command("new")
def spec_new(
    spec_id: str = typer.Option(..., "--id", help="Strategy ID, e.g. S-012"),
    from_spec: str | None = typer.Option(None, "--from", help="Base spec to increment version from"),
    name: str = typer.Option("New Strategy", "--name", help="Strategy name"),
):
    """Draft a new StrategySpec or bump version from an existing spec."""
    specs_dir = get_specs_dir() / spec_id
    specs_dir.mkdir(parents=True, exist_ok=True)

    if from_spec:
        res = validate_spec_file(from_spec)
        if not res.is_valid:
            err_console.print(f"[bold red]Error[/bold red]: Base spec '{from_spec}' is invalid: {res.errors}")
            raise typer.Exit(code=1)
        base = res.spec
        new_version = base.version + 1
        spec_dict = base.model_dump()
        spec_dict["version"] = new_version
    else:
        new_version = 1
        spec_dict = {
            "id": spec_id,
            "version": 1,
            "name": name,
            "market": {
                "symbol": "BTCUSDT",
                "exchange": "binance",
                "tv_symbol": "BINANCE:BTCUSDT",
                "timeframe": "4h",
            },
            "period": {
                "start": "2021-01-01",
                "end": "2025-12-31",
                "oos_fraction": 0.3,
            },
            "direction": "long",
            "params": {
                "fast_len": {"default": 10, "range": [5, 25, 5]},
                "slow_len": {"default": 30, "range": [20, 60, 10]},
            },
            "indicators": {
                "fast_ma": {"fn": "sma", "src": "close", "len": "$fast_len"},
                "slow_ma": {"fn": "sma", "src": "close", "len": "$slow_len"},
            },
            "entry": {
                "long": {"crosses_above": ["fast_ma", "slow_ma"]},
            },
            "exit": {
                "opposite_signal": True,
            },
            "risk": {
                "sizing": "percent_equity",
                "value": 100,
                "initial_capital": 10000,
                "pyramiding": 0,
            },
            "costs": {
                "commission_pct": 0.1,
                "slippage_ticks": 1,
                "tick_size": 0.01,
            },
        }

    out_file = specs_dir / f"v{new_version}.yaml"
    import yaml
    with open(out_file, "w", encoding="utf-8") as f:
        yaml.dump(spec_dict, f, sort_keys=False)

    console.print(f"[bold green]Created[/bold green]: {out_file}")


# ==========================================
# Data Subcommands
# ==========================================

@data_app.command("fetch")
def data_fetch(
    symbol: str = typer.Argument(..., help="Symbol, e.g. BTCUSDT"),
    timeframe: str = typer.Argument("4h", help="Timeframe, e.g. 1h, 4h, 1d"),
    start_date: str = typer.Option("2021-01-01", "--from", help="Start date YYYY-MM-DD"),
    end_date: str | None = typer.Option(None, "--to", help="End date YYYY-MM-DD"),
    as_json: bool = typer.Option(False, "--json", help="Output machine-readable JSON"),
):
    """Fetch historical OHLCV data from Binance/yfinance and store in Parquet cache."""
    with console.status(f"[cyan]Fetching {symbol} ({timeframe}) from {start_date}...[/cyan]"):
        try:
            cached_path = fetch_and_cache_ohlcv(symbol, timeframe, start_date, end_date)
        except Exception as e:
            err_msg = str(e)
            if as_json:
                typer.echo(json.dumps({"success": False, "error": err_msg}))
            else:
                err_console.print(f"[bold red]Fetch Failed[/bold red]: {err_msg}")
            raise typer.Exit(code=1)

    if as_json:
        typer.echo(json.dumps({"success": True, "path": str(cached_path)}))
    else:
        console.print(f"[bold green]Success[/bold green]: Cached {symbol} {timeframe} to [blue]{cached_path}[/blue]")


def _resolve_spec_path(spec_target: str) -> Path:
    """Resolve spec file from path or <ID>@v<n> notation."""
    p = Path(spec_target)
    if p.exists():
        return p

    # Check for <ID>@v<n>
    if "@" in spec_target:
        spec_id, ver = spec_target.split("@", 1)
        if not ver.startswith("v"):
            ver = f"v{ver}"
        filename = f"{ver}.yaml"

        # Check examples
        ex_path = Path("examples/specs") / spec_id / filename
        if ex_path.exists():
            return ex_path

        # Check user specs
        user_path = get_specs_dir() / spec_id / filename
        if user_path.exists():
            return user_path

    raise FileNotFoundError(f"Could not find strategy spec for target '{spec_target}'")


@app.command("backtest")
def backtest_cmd(
    target: str = typer.Argument(..., help="Spec path or notation, e.g. S-012@v1"),
    params: str | None = typer.Option(None, "--params", help="Comma-separated overrides, e.g. 'rsi_len=14,atr_stop=2.5'"),
    as_json: bool = typer.Option(False, "--json", help="Output machine-readable JSON"),
):
    """Run in-sample and out-of-sample backtest for a strategy spec."""
    try:
        spec_path = _resolve_spec_path(target)
    except FileNotFoundError as e:
        err_console.print(f"[bold red]Error[/bold red]: {e}")
        raise typer.Exit(code=1)

    res = validate_spec_file(spec_path)
    if not res.is_valid:
        err_console.print(f"[bold red]Invalid Spec[/bold red]: {res.errors}")
        raise typer.Exit(code=1)

    param_overrides: dict[str, Any] = {}
    if params:
        for item in params.split(","):
            if "=" in item:
                k, v = item.split("=", 1)
                k = k.strip()
                v = v.strip()
                # Parse number if possible
                try:
                    param_overrides[k] = int(v) if "." not in v else float(v)
                except ValueError:
                    param_overrides[k] = v

    try:
        results = run_backtest(res.spec, param_overrides=param_overrides, save_run=True)
    except Exception as e:
        err_console.print(f"[bold red]Backtest Failed[/bold red]: {e}")
        raise typer.Exit(code=1)

    if as_json:
        typer.echo(json.dumps(results, indent=2))
    else:
        m_is = results["is"]
        m_oos = results.get("oos", {})
        console.print(f"\n[bold cyan]Backtest Results: {results['spec_id']}@v{results['version']}[/bold cyan] [dim](run_id: {results['run_id']})[/dim]")
        console.print(f"  [bold]Parameters[/bold]: {results['params']}")
        console.print(
            f"  [green]In-Sample[/green]:     Trades: [bold]{m_is['trades']}[/bold] | "
            f"Net: [bold]{m_is['net_profit_pct']:+.1f}%[/bold] | "
            f"PF: [bold]{m_is['profit_factor']:.2f}[/bold] | "
            f"Win%: [bold]{m_is['win_rate_pct']:.1f}%[/bold] | "
            f"MaxDD: [bold]{m_is['max_drawdown_pct']:.1f}%[/bold] | "
            f"Sharpe: [bold]{m_is['sharpe_ratio']:.2f}[/bold]"
        )
        if m_oos:
            console.print(
                f"  [yellow]Out-of-Sample[/yellow]: Trades: [bold]{m_oos['trades']}[/bold] | "
                f"Net: [bold]{m_oos['net_profit_pct']:+.1f}%[/bold] | "
                f"PF: [bold]{m_oos['profit_factor']:.2f}[/bold] | "
                f"Win%: [bold]{m_oos['win_rate_pct']:.1f}%[/bold] | "
                f"MaxDD: [bold]{m_oos['max_drawdown_pct']:.1f}%[/bold] | "
                f"Sharpe: [bold]{m_oos['sharpe_ratio']:.2f}[/bold]"
            )
        console.print(f"  [dim]Artifacts saved to: {results['run_dir']}[/dim]\n")


@app.command("sweep")
def sweep_cmd(
    target: str = typer.Argument(..., help="Spec path or notation, e.g. S-012@v1"),
    budget: int = typer.Option(200, "--budget", help="Maximum combinations to evaluate"),
    as_json: bool = typer.Option(False, "--json", help="Output machine-readable JSON"),
):
    """Run parameter sweep scored on In-Sample data."""
    try:
        spec_path = _resolve_spec_path(target)
    except FileNotFoundError as e:
        err_console.print(f"[bold red]Error[/bold red]: {e}")
        raise typer.Exit(code=1)

    res = validate_spec_file(spec_path)
    if not res.is_valid:
        err_console.print(f"[bold red]Invalid Spec[/bold red]: {res.errors}")
        raise typer.Exit(code=1)

    with console.status(f"[cyan]Running sweep for {target} (budget {budget})...[/cyan]"):
        sweep_df = run_sweep(res.spec, budget=budget)

    if as_json:
        top10 = sweep_df.head(10).to_dict(orient="records")
        typer.echo(json.dumps({"total_combos": len(sweep_df), "top_10": top10}, indent=2))
    else:
        console.print(f"\n[bold green]Sweep Complete[/bold green]: Evaluated [bold]{len(sweep_df)}[/bold] combinations.")
        console.print("\n[bold]Top 5 Parameter Sets (by Profit Factor):[/bold]")
        top5 = sweep_df.head(5)
        for idx, row in top5.iterrows():
            params_str = ", ".join(f"{k}={row[k]}" for k in res.spec.params.keys() if k in row)
            console.print(
                f"  #{idx + 1}: [cyan]{params_str}[/cyan] -> "
                f"PF: [bold]{row['profit_factor']:.2f}[/bold] | "
                f"Net: [bold]{row['net_profit_pct']:+.1f}%[/bold] | "
                f"Trades: [bold]{int(row['trades'])}[/bold] | "
                f"MaxDD: [bold]{row['max_drawdown_pct']:.1f}%[/bold]"
            )
        console.print()


@app.command("walkforward")
def walkforward_cmd(
    target: str = typer.Argument(..., help="Spec path or notation, e.g. S-012@v1"),
    as_json: bool = typer.Option(False, "--json", help="Output machine-readable JSON"),
):
    """Run rolling walk-forward analysis re-optimizing parameters per window."""
    try:
        spec_path = _resolve_spec_path(target)
    except FileNotFoundError as e:
        err_console.print(f"[bold red]Error[/bold red]: {e}")
        raise typer.Exit(code=1)

    res = validate_spec_file(spec_path)
    if not res.is_valid:
        err_console.print(f"[bold red]Invalid Spec[/bold red]: {res.errors}")
        raise typer.Exit(code=1)

    with console.status(f"[cyan]Running Walk-Forward Analysis for {target}...[/cyan]"):
        wf_res = run_walkforward(res.spec)

    if as_json:
        typer.echo(json.dumps(wf_res, indent=2))
    else:
        console.print(f"\n[bold green]Walk-Forward Analysis: {target}[/bold green]")
        console.print(
            f"  Efficiency (WFE): [bold]{wf_res['walk_forward_efficiency']:.2f}[/bold] | "
            f"Profitable Windows: [bold]{wf_res['pct_profitable_windows']:.1f}%[/bold] "
            f"({wf_res.get('total_windows', 0)} total windows)"
        )
        for w in wf_res.get("windows", []):
            console.print(
                f"  Window {w['window']} ({w['oos_start']} to {w['oos_end']}): "
                f"IS PF: {w['is_pf']:.2f} -> OOS PF: [bold]{w['oos_pf']:.2f}[/bold] | "
                f"OOS Net: [bold]{w['oos_net_pct']:+.1f}%[/bold] ({w['oos_trades']} trades)"
            )
        console.print()


@app.command("robust")
def robust_cmd(
    target: str = typer.Argument(..., help="Spec path or notation, e.g. S-012@v1"),
    as_json: bool = typer.Option(False, "--json", help="Output machine-readable JSON"),
):
    """Run Monte Carlo bootstrap, cost stress, and parameter neighborhood tests."""
    try:
        spec_path = _resolve_spec_path(target)
    except FileNotFoundError as e:
        err_console.print(f"[bold red]Error[/bold red]: {e}")
        raise typer.Exit(code=1)

    res = validate_spec_file(spec_path)
    if not res.is_valid:
        err_console.print(f"[bold red]Invalid Spec[/bold red]: {res.errors}")
        raise typer.Exit(code=1)

    with console.status(f"[cyan]Running Robustness Battery for {target}...[/cyan]"):
        robust_data = run_robustness_battery(res.spec)

    if as_json:
        typer.echo(json.dumps(robust_data, indent=2))
    else:
        mc = robust_data["monte_carlo"]
        cost = robust_data["cost_stress"]
        neigh = robust_data["neighbourhood"]

        console.print(f"\n[bold green]Robustness Audit: {target}[/bold green] [dim]({robust_data['run_id']})[/dim]")
        console.print(
            f"  [bold]Monte Carlo (1,000 runs)[/bold]: 95th pct Max DD: [bold]{mc['pct_95th_max_drawdown']:.1f}%[/bold] | "
            f"5th pct Equity: [bold]${mc['pct_5th_final_equity']:.2f}[/bold]"
        )
        console.print(
            f"  [bold]Cost Stress (2x fees & slippage)[/bold]: IS PF: [bold]{cost['in_sample_pf']:.2f}[/bold] | "
            f"OOS PF: [bold]{cost['out_of_sample_pf']:.2f}[/bold]"
        )
        console.print(
            f"  [bold]Neighbourhood Stability[/bold]: Best PF: {neigh['best_pf']:.2f} -> "
            f"Median Neighbour PF: [bold]{neigh['median_neighbour_pf']:.2f}[/bold] (Stability Ratio: [bold]{neigh['stability_ratio']:.2f}[/bold])\n"
        )


@app.command("gates")
def gates_cmd(
    target: str = typer.Argument(..., help="Spec path or notation, e.g. S-012@v1"),
    as_json: bool = typer.Option(False, "--json", help="Output machine-readable JSON"),
):
    """Audit strategy against all 6 Lab Charter promotion gates."""
    try:
        spec_path = _resolve_spec_path(target)
    except FileNotFoundError as e:
        err_console.print(f"[bold red]Error[/bold red]: {e}")
        raise typer.Exit(code=1)

    res = validate_spec_file(spec_path)
    if not res.is_valid:
        err_console.print(f"[bold red]Invalid Spec[/bold red]: {res.errors}")
        raise typer.Exit(code=1)

    with console.status(f"[cyan]Evaluating 6 Promotion Gates for {target}...[/cyan]"):
        audit = evaluate_gates(res.spec)

    if as_json:
        typer.echo(json.dumps(audit, indent=2))
    else:
        v_color = "green" if audit["verdict"] == "PASS" else "red"
        console.print(f"\n[bold {v_color}]VERDICT: {audit['verdict']}[/bold {v_color}] ({audit['passed_count']} of {audit['total_gates']} gates passed)")
        for g_name, g_info in audit["gates"].items():
            status_text = "[bold green]PASS[/bold green]" if g_info["pass"] else "[bold red]FAIL[/bold red]"
            console.print(f"  {status_text} [bold]{g_name}[/bold]: {g_info['detail']}")
        console.print()

    if audit["verdict"] != "PASS":
        raise typer.Exit(code=1)


@app.command("chart")
def chart_cmd(
    target: str = typer.Argument(..., help="Spec path or notation, e.g. S-012@v1"),
    output_dir: str | None = typer.Option(None, "--out", help="Output directory for PNG charts"),
    as_json: bool = typer.Option(False, "--json", help="Output machine-readable JSON"),
):
    """Generate dark-mode charts: equity curve, heatmap, walkforward bars, and metrics card."""
    try:
        spec_path = _resolve_spec_path(target)
    except FileNotFoundError as e:
        err_console.print(f"[bold red]Error[/bold red]: {e}")
        raise typer.Exit(code=1)

    res = validate_spec_file(spec_path)
    if not res.is_valid:
        err_console.print(f"[bold red]Invalid Spec[/bold red]: {res.errors}")
        raise typer.Exit(code=1)

    target_dir = Path(output_dir) if output_dir else get_artifacts_dir() / f"{res.spec.id}_v{res.spec.version}"
    target_dir.mkdir(parents=True, exist_ok=True)

    # 1. Backtest & Equity Curve
    bt = run_backtest(res.spec, save_run=True)
    df = load_ohlcv(res.spec.market.symbol, res.spec.market.timeframe)
    run_dir = Path(bt["run_dir"])
    with open(run_dir / "metrics.json") as f:
        metrics_json = json.load(f)

    # Load simulated equity from backtest
    eq_path = plot_equity_and_drawdown(
        df,
        np.array([10000.0] * len(df)),  # fallback or baseline
        target_dir / "equity.png",
        title=f"{res.spec.id} v{res.spec.version} Equity Curve",
    )

    # 2. Metrics Card
    card_path = render_metrics_card(
        res.spec.id,
        res.spec.version,
        metrics_json,
        equity_curve=None,
        output_path=target_dir / "card.png",
    )

    # 3. Walkforward Chart
    wf = run_walkforward(res.spec, sweep_budget=20)
    wf_path = plot_walkforward_windows(wf, target_dir / "walkforward.png")

    chart_paths = {
        "equity": str(eq_path),
        "card": str(card_path),
        "walkforward": str(wf_path),
    }

    if as_json:
        typer.echo(json.dumps({"success": True, "charts": chart_paths}, indent=2))
    else:
        console.print(f"[bold green]Charts Generated[/bold green] in [blue]{target_dir}[/blue]:")
        for k, v in chart_paths.items():
            console.print(f"  - {k}: {v}")


@app.command("pine")
def pine_cmd(
    target: str = typer.Argument(..., help="Spec target, e.g. S-012@v2, or 'import'"),
    file_path: str | None = typer.Argument(None, help="File path if importing, or output path"),
    out: str | None = typer.Option(None, "-o", "--out", help="Output .pine file path"),
    print_code: bool = typer.Option(False, "--print", help="Print Pine code directly to stdout"),
    as_json: bool = typer.Option(False, "--json", help="Output machine-readable JSON"),
):
    """Generate Pine Script v6 strategy or import an existing Pine script."""
    import yaml

    if target == "import":
        if not file_path:
            err_console.print("[bold red]Error[/bold red]: Usage: stratlab pine import <file.pine>")
            raise typer.Exit(code=1)
        res = import_pine_file(file_path)
        if as_json:
            typer.echo(json.dumps(res, indent=2))
        else:
            if res["supported"]:
                console.print(f"[bold green]Import Succeeded[/bold green]: Strategy '{res['spec_dict']['name']}'")
                console.print(yaml.dump(res["spec_dict"], sort_keys=False))
            else:
                err_console.print("[bold yellow]Partial Import with Unsupported Features:[/bold yellow]")
                for f in res["unsupported_features"]:
                    err_console.print(f"  - {f}")
        return

    try:
        spec_path = _resolve_spec_path(target)
    except FileNotFoundError as e:
        err_console.print(f"[bold red]Error[/bold red]: {e}")
        raise typer.Exit(code=1)

    val = validate_spec_file(spec_path)
    if not val.is_valid:
        err_console.print(f"[bold red]Invalid Spec[/bold red]: {val.errors}")
        raise typer.Exit(code=1)

    pine_code = generate_pine_script(val.spec)
    out_path = Path(out) if out else get_artifacts_dir() / f"{val.spec.id}_v{val.spec.version}.pine"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(pine_code, encoding="utf-8")

    if print_code:
        typer.echo(pine_code)
        return

    if as_json:
        typer.echo(json.dumps({"success": True, "path": str(out_path)}, indent=2))
    else:
        console.print(f"[bold green]Generated Pine v6[/bold green] -> [blue]{out_path}[/blue]")
        console.print(f"  Strategy: {val.spec.name}")
        console.print(f"  Inputs: {list(val.spec.params.keys())}")
        console.print(f"  Commission: {val.spec.costs.commission_pct}% | Slippage: {val.spec.costs.slippage_ticks} ticks")


@app.command("parity")
def parity_cmd(
    target: str = typer.Argument(..., help="Spec target, e.g. S-012@v2"),
    tv_csv: str = typer.Argument(..., help="Path to TradingView 'List of Trades' CSV export"),
    as_json: bool = typer.Option(False, "--json", help="Output machine-readable JSON"),
):
    """Compare engine trades against TradingView Strategy Tester CSV export."""
    try:
        spec_path = _resolve_spec_path(target)
    except FileNotFoundError as e:
        err_console.print(f"[bold red]Error[/bold red]: {e}")
        raise typer.Exit(code=1)

    val = validate_spec_file(spec_path)
    if not val.is_valid:
        err_console.print(f"[bold red]Invalid Spec[/bold red]: {val.errors}")
        raise typer.Exit(code=1)

    try:
        rep = check_trade_parity(val.spec, tv_csv)
    except Exception as e:
        err_console.print(f"[bold red]Parity Check Failed[/bold red]: {e}")
        raise typer.Exit(code=1)

    if as_json:
        typer.echo(json.dumps(rep, indent=2))
    else:
        console.print(render_parity_report(rep))

    if rep["status"] != "PASS":
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
