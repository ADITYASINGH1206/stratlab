"""`stratlab demo`: replay the #lab room offline, with real numbers from the engine.

Every number below is computed on the bundled data by the same functions the agents call.
Only the human lines (the idea and the final verdict) are scripted.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel

from stratlab.config import PROJECT_ROOT, get_artifacts_dir
from stratlab.engine.backtest import run_backtest
from stratlab.engine.ledger import add_ledger_entry
from stratlab.pine.generate import generate_pine_script
from stratlab.research.gates import GATE_TITLES, evaluate_gates
from stratlab.research.sweep import run_sweep
from stratlab.research.walkforward import run_walkforward
from stratlab.spec.diff import diff_specs, render_diff_text
from stratlab.spec.validate import validate_spec_file

COLORS = {"Aditya": "white", "Strategist": "cyan", "Pine Coder": "magenta", "Backtester": "green",
          "Skeptic": "red", "Scribe": "yellow"}
console = Console()


def say(who: str, text: str) -> None:
    console.print(Panel(text, title=f"[bold {COLORS[who]}]{who}[/]", title_align="left", border_style=COLORS[who]))


def _m(m: dict) -> str:
    return f"{m['trades']} trades, net {m['net_profit_pct']:+.1f}%, PF {m['profit_factor']:.2f}, max DD {m['max_drawdown_pct']:.1f}%"


def _round(spec, budget: int) -> dict:
    pine_path = get_artifacts_dir() / f"{spec.id}_v{spec.version}.pine"
    pine_path.write_text(generate_pine_script(spec))
    say("Pine Coder", f"{spec.id}@v{spec.version} Pine v6 -> {pine_path.name}\n"
        f"inputs: {', '.join(spec.params)} | commission {spec.costs.commission_pct}% | slippage {spec.costs.slippage_ticks} tick\n"
        "Generated from the spec; not hand-edited.")
    base = run_backtest(spec)
    sweep = run_sweep(spec, budget=budget)
    s = sweep.attrs["summary"]
    wf = run_walkforward(spec)
    say("Backtester",
        f"running baseline, a {s['evaluated']}-combo sweep and walk-forward...\n"
        f"```text\nbaseline IS : {_m(base['is'])}\nbaseline OOS: {_m(base['oos'])}\n"
        f"sweep best  : {s['best_params']}\n              IS PF {s['best_is']['profit_factor']:.2f} on {int(s['best_is']['trades'])} trades\n"
        f"walk-forward: WFE {wf['walk_forward_efficiency']:.2f}, {wf['pct_profitable_windows']:.0f}% of {wf['total_windows']} windows profitable\n```\n"
        f"runs {base['run_id']}, {sweep.attrs.get('run_id')}\n@skeptic review {spec.id}@v{spec.version}")
    audit = evaluate_gates(spec)
    lines = [f"{'PASS' if g['pass'] else 'FAIL'} {GATE_TITLES[k]}: {g['detail']}" for k, g in audit["gates"].items()]
    tail = (f"@strategist {spec.id}@v{spec.version} failed: {', '.join(GATE_TITLES[k] for k in audit['failed'])}."
            if audit["verdict"] == "FAIL" else "Waiting on a human: promote, kill or park?")
    say("Skeptic", f"Reviewing the sweep's candidate {audit['params']}.\n```text\n" + "\n".join(lines) +
        f"\n```\nVERDICT {audit['verdict']} ({audit['passed_count']}/6).  gates run {audit.get('gates_run_id')}\n{tail}")
    return audit


def run_demo(budget: int = 120) -> None:
    v1 = validate_spec_file(PROJECT_ROOT / "examples/specs/S-012/v1.yaml").spec
    v2 = validate_spec_file(PROJECT_ROOT / "examples/specs/S-012/v2.yaml").spec
    console.rule("[bold]StratLab offline replay: #lab[/] (numbers are real; human lines are scripted)")
    say("Aditya", "@strategist idea: BTCUSDT 4h, long when RSI(9) crosses above 30 and close > EMA(200). "
        "Stop 2x ATR(14), target 3x ATR, 60-bar time exit.")
    say("Strategist", f"Spec {v1.id} v1 drafted: long-only {v1.market.symbol} {v1.market.timeframe}, "
        f"{v1.period.start}..{v1.period.end}, fees {v1.costs.commission_pct}%, slippage {v1.costs.slippage_ticks} tick, "
        f"{int(v1.period.oos_fraction * 100)}% held out.\n@pine-coder @backtester {v1.id}@v1 ready.")
    a1 = _round(v1, budget)
    diff = render_diff_text(diff_specs(PROJECT_ROOT / "examples/specs/S-012/v1.yaml", PROJECT_ROOT / "examples/specs/S-012/v2.yaml"))
    say("Strategist", f"v2: trend entry (EMA 12/100 cross with RSI > 40), every lookback fixed, only the exits tunable.\n"
        f"```text\n{diff}\n```\n@pine-coder @backtester {v2.id}@v2 ready.")
    a2 = _round(v2, budget)
    if a2["verdict"] == "PASS":
        verdict, note = "promote", "all six gates passed"
    else:
        verdict = "park"
        note = f"better than v1 ({a2['passed_count']}/6 vs {a1['passed_count']}/6) but still fails " + ", ".join(a2["failed"])
    say("Aditya", f"{verdict}")
    entry = add_ledger_entry(f"{v2.id}@v2", verdict, "Aditya", note)
    add_ledger_entry(f"{v1.id}@v1", "kill", "Aditya", f"overfit: failed {', '.join(a1['failed'])}")
    say("Scribe", f"{v2.id}@v2 {entry['verdict']} logged to the Strategy Ledger (and {v1.id}@v1 KILL).\n"
        f"OOS PF {entry['oos_pf']} | failed gates: {entry['failed_gates']}\n"
        "Open the desk with: stratlab ui")
    console.rule("[dim]end of replay. Not financial advice.[/]")
