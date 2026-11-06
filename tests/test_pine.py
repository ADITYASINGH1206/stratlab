"""Tests for Pine Script v6 generator, importer, and TradingView parity checker."""

import tempfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from stratlab.cli import app
from stratlab.pine.generate import generate_pine_script
from stratlab.pine.importer import import_pine_to_spec
from stratlab.spec.validate import validate_spec_file
from stratlab.tv.parity import check_trade_parity, render_parity_report
from stratlab.tv.trades_csv import parse_tv_trades_csv

runner = CliRunner()
SPEC_DIR = Path(__file__).resolve().parent.parent / "examples" / "specs"


def test_pine_generation_golden():
    """Verify that generated Pine Script matches golden file for S-012_v2."""
    spec_path = SPEC_DIR / "S-012" / "v2.yaml"
    val = validate_spec_file(spec_path)
    assert val.is_valid
    generated = generate_pine_script(val.spec)

    golden_path = Path("fixtures/golden/S-012_v2.pine")
    assert golden_path.exists()
    golden_content = golden_path.read_text()
    assert generated.strip() == golden_content.strip()


def test_pine_generation_all_examples():
    """Generate Pine script for all example specs and verify valid output."""
    specs = [
        SPEC_DIR / "S-001" / "v1.yaml",
        SPEC_DIR / "S-012" / "v1.yaml",
        SPEC_DIR / "S-012" / "v2.yaml",
        SPEC_DIR / "S-020" / "v1.yaml",
    ]
    for spec_path in specs:
        val = validate_spec_file(spec_path)
        assert val.is_valid
        code = generate_pine_script(val.spec)
        assert "//@version=6" in code
        assert val.spec.name in code
        assert "strategy.entry" in code
        assert "ta." in code


def test_pine_import():
    """Verify reverse-mapping simple Pine code into StrategySpec."""
    pine_code = """//@version=6
strategy('EMA Cross Demo', overlay=true)

fast = ta.ema(close, 9)
slow = ta.ema(close, 21)

long_condition = ta.crossover(fast, slow)
short_condition = ta.crossunder(fast, slow)

if long_condition
    strategy.entry("Long", strategy.long)
if short_condition
    strategy.close("Long")
"""
    res = import_pine_to_spec(pine_code)
    assert res["supported"] is True
    spec_dict = res["spec_dict"]
    assert spec_dict["name"] == "EMA Cross Demo"
    assert "fast" in spec_dict["indicators"]
    assert "slow" in spec_dict["indicators"]


def test_tv_csv_parser_current_headers():
    """Net P&L / Position size headers, exit-row-first order, and an open trade that is skipped."""
    df = parse_tv_trades_csv(Path("fixtures/tv_format_sample.csv"))
    assert list(df["trade_num"]) == [1, 2]
    assert df.iloc[0]["profit"] == 380.40 and df.iloc[1]["profit"] == -210.40
    assert df.iloc[0]["entry_price"] == 44400.0 and df.iloc[0]["qty"] == 0.22


def test_tv_csv_parser_unknown_headers(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("a,b,c\n1,2,3\n")
    with pytest.raises(ValueError, match="Headers seen"):
        parse_tv_trades_csv(bad)


def _engine_trades_as_tv_csv(spec, path):
    from stratlab.engine.runner import active_params, compute_signals, prepare, run_window
    from stratlab.tv.trades_csv import write_tv_style_csv

    params = active_params(spec)
    prep = prepare(spec)
    trades, _, _ = run_window(spec, prep, compute_signals(spec, prep, params), params, prep.start, prep.end)
    return write_tv_style_csv(trades, path), len(trades)


def test_parity_matcher_self_check(tmp_path):
    """Matcher self-test: the engine's own trades written in TradingView's layout must match 100%.

    This checks the matcher and the parser, not TradingView. Real parity needs a real export.
    """
    spec = validate_spec_file(SPEC_DIR / "S-012" / "v2.yaml").spec
    csv, n = _engine_trades_as_tv_csv(spec, tmp_path / "self.csv")
    report = check_trade_parity(spec, csv)
    assert report["status"] == "PASS"
    assert report["tv_trades"] == n and report["matched_entries_pct"] == 100.0
    assert report["net_profit_diff_pct"] < 0.1
    assert "Parity Match Report: [PASS]" in render_parity_report(report)


def test_parity_reports_drift(tmp_path):
    spec = validate_spec_file(SPEC_DIR / "S-012" / "v2.yaml").spec
    report = check_trade_parity(spec, Path("fixtures/tv_format_sample.csv"))
    assert report["status"] == "FAIL"
    assert report["first_mismatch"]
    assert "Known drift causes" in render_parity_report(report)


def test_cli_pine_generate():
    result = runner.invoke(app, ["pine", "S-012@v2", "--print"])
    assert result.exit_code == 0
    assert "//@version=6" in result.stdout
    assert "S-012 v2: RSI reclaim above EMA with ATR target" in result.stdout


def test_cli_pine_save():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_file = Path(tmpdir) / "test.pine"
        result = runner.invoke(app, ["pine", "S-012@v2", "-o", str(out_file)])
        assert result.exit_code == 0
        assert out_file.exists()
        assert "//@version=6" in out_file.read_text()


def test_cli_pine_import():
    golden_path = "fixtures/golden/S-012_v2.pine"
    result = runner.invoke(app, ["pine", "import", golden_path])
    assert result.exit_code == 0
    assert "Import Succeeded: Strategy" in result.stdout


def test_cli_parity(tmp_path):
    spec = validate_spec_file(SPEC_DIR / "S-012" / "v2.yaml").spec
    csv, n = _engine_trades_as_tv_csv(spec, tmp_path / "self.csv")
    result = runner.invoke(app, ["parity", "S-012@v2", str(csv)])
    assert result.exit_code == 0
    assert f"Matched Entries: {n}/{n}" in result.stdout
