"""Command line interface for StratLab."""

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from stratlab import __version__
from stratlab.config import get_specs_dir, init_environment
from stratlab.data.fetch import fetch_and_cache_ohlcv
from stratlab.engine.backtest import run_backtest
from stratlab.spec.diff import diff_specs, render_diff_text
from stratlab.spec.models import StrategySpec
from stratlab.spec.validate import validate_spec_file

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


if __name__ == "__main__":
    app()
