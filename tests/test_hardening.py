"""Phase 6 hardening: failure paths give one clear line, agents share specs, docs match code."""

import os
import re
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from stratlab.cli import app
from stratlab.config import get_specs_dir
from stratlab.spec.validate import validate_spec_dict

runner = CliRunner()
ROOT = Path(__file__).resolve().parent.parent
BASE = yaml.safe_load((ROOT / "examples/specs/S-012/v1.yaml").read_text())


def _err(result) -> str:
    return (result.stderr if hasattr(result, "stderr") else "") + result.output


def test_spec_reference_resolves_from_any_directory(tmp_path):
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)  # an agent's own working directory, not the repo
        r = runner.invoke(app, ["spec", "validate", "S-012@v1"])
        assert r.exit_code == 0, r.output
        r = runner.invoke(app, ["spec", "path", "S-012"])  # no version: latest
        assert r.output.strip().endswith("v2.yaml")
    finally:
        os.chdir(cwd)


def test_spec_new_writes_to_the_shared_workspace():
    r = runner.invoke(app, ["spec", "new", "--name", "Test idea", "--json"])
    assert r.exit_code == 0, r.output
    path = Path(re.search(r'"path": "([^"]+)"', r.output).group(1))
    assert path.is_relative_to(get_specs_dir()) and path.exists()
    ref = re.search(r'"ref": "([^"]+)"', r.output).group(1)
    assert runner.invoke(app, ["spec", "validate", ref]).exit_code == 0  # the skeleton itself is valid
    r = runner.invoke(app, ["spec", "new", "--from", "S-012@v2"])
    assert "S-012@v3" in r.output
    assert (get_specs_dir() / "S-012" / "v3.yaml").exists()


@pytest.mark.parametrize("args,needle", [
    (["backtest", "S-999@v1"], "not found"),
    (["backtest", "S-012@v1", "--params", "nope=3"], "unknown param"),
    (["backtest", "S-012@v1", "--params", "rsi_len=abc"], "not a number"),
    (["sweep", "S-012@v1", "--budget", "0"], "budget"),
    (["parity", "S-012@v2", "missing.csv"], "not found"),
    (["ledger", "add", "S-012@v1", "--verdict", "maybe", "--by", "x"], "promote, kill or park"),
    (["gates", "S-012@v1", "--set", "g9.nothing=1"], "unknown charter setting"),
])
def test_failures_are_one_clear_line(args, needle):
    r = runner.invoke(app, args)
    assert r.exit_code == 1
    out = _err(r)
    assert out.strip().startswith("Error:") and needle in out
    assert "Traceback" not in out


def _spec(**changes):
    d = yaml.safe_load(yaml.safe_dump(BASE))
    for k, v in changes.items():
        cur = d
        *path, last = k.split(".")
        for p in path:
            cur = cur[p]
        if v is None:
            cur.pop(last, None)
        else:
            cur[last] = v
    return validate_spec_dict(d)


@pytest.mark.parametrize("changes,needle", [
    ({"indicators.macd": {"fn": "macd", "src": "close"}}, "not supported yet"),
    ({"indicators.bad": {"fn": "expr", "expr": "__import__('os')"}}, "may only use"),
    ({"direction": "short", "entry.short": {"lt": ["rsi", 70]}}, "long-only"),
    ({"exit.opposite_signal": True}, "needs an entry.short"),
    ({"exit.stop.atr_mult": "$missing"}, "Undefined parameter"),
    ({"exit.time.bars": "$atr_stop"}, "integer param"),
    ({"indicators.atr": None, "indicators.rsi.len": 14}, "fn: atr"),
    ({"exit.stopp": {"pct": 2}}, "Extra inputs"),
])
def test_validator_rejects_what_the_engine_cannot_run(changes, needle):
    res = _spec(**changes)
    assert not res.is_valid
    assert any(needle in e for e in res.errors), res.errors


def test_charter_doc_matches_the_gate_code():
    from stratlab.research.charter import load_charter
    from switch.build_template import build_template

    t = build_template()
    charter_doc = t["rooms"][0]["docs"][0]["content"]
    c = load_charter()
    for title in ("G1 Sample size", "G2 Out-of-sample", "G3 Walk-forward", "G4 Stability", "G5 Costs", "G6 Tail risk"):
        assert title in charter_doc
    dd = c["g6_tail_risk"]["max_drawdown_limit_pct"] * c["g6_tail_risk"]["mc_drawdown_multiple"]
    assert f"at most {dd:g}%" in charter_doc
    assert str(c["g2_out_of_sample"]["min_oos_pf"]) in charter_doc
    skeptic = next(a for a in t["agents"] if a["name"] == "stratlab-skeptic")["instructions"]
    assert "G2 Out-of-sample" in skeptic and "Parity" not in skeptic


def test_agent_prompts_use_commands_that_exist():
    from switch.build_template import build_template

    commands = {c.name for c in app.registered_commands} | {"spec", "data", "ledger"}
    for agent in build_template()["agents"]:
        text = agent["instructions"]
        assert "~/stratlab-home/bin/stratlab" in text
        for cmd in re.findall(r"`stratlab ([a-z]+)", text):
            assert cmd in commands, f"{agent['name']} uses unknown command {cmd}"
        assert "--best" not in text or "walkforward" not in text.split("--best")[0][-40:]


def test_loop_guard_and_human_gate_are_in_the_prompts():
    """The loop guard lives in the Strategist's instructions; this keeps it from being edited away."""
    from switch.build_template import build_template

    t = build_template()
    strat = next(a for a in t["agents"] if a["name"] == "stratlab-strategist")["instructions"]
    assert "After the third" in strat and "Waiting on a human." in strat
    assert "Only humans decide" in strat
    lab = t["rooms"][0]["instructions"]
    assert "up to 3 versions" in lab and "promote, kill or park" in lab


def test_offline_demo_and_desk(tmp_path):
    r = runner.invoke(app, ["demo", "--budget", "20"])
    assert r.exit_code == 0, r.output
    assert "VERDICT" in r.output and "Strategy Ledger" in r.output
    out = tmp_path / "desk.html"
    r = runner.invoke(app, ["ui", "--out", str(out)])
    assert r.exit_code == 0, r.output
    html = out.read_text()
    assert "StratLab Desk" in html and '"ref": "S-012@v1"' in html and "/*__STRATLAB_DATA__*/null" not in html
    r = runner.invoke(app, ["ledger", "digest"])
    assert "most common failure" in r.output
