"""Tests for Pine Script v6 generator, importer, and TradingView parity checker."""

import tempfile
from pathlib import Path

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


def test_tv_csv_parser():
    """Verify parser correctly reads 71 closed trades (142 rows) from TV CSV."""
    csv_path = Path("fixtures/tv_trades_S-012_v2.csv")
    df = parse_tv_trades_csv(csv_path)
    assert len(df) == 71
    assert "entry_time" in df.columns
    assert "exit_time" in df.columns
    assert "profit" in df.columns


def test_parity_evaluation():
    """Verify parity comparison between engine backtest and TV trades CSV."""
    spec_path = SPEC_DIR / "S-012" / "v2.yaml"
    val = validate_spec_file(spec_path)
    assert val.is_valid
    csv_path = Path("fixtures/tv_trades_S-012_v2.csv")

    report = check_trade_parity(val.spec, csv_path)
    assert report["status"] == "PASS"
    assert report["engine_trades"] == 71
    assert report["tv_trades"] == 71
    assert report["matched_entries_pct"] >= 95.0
    assert report["net_profit_diff_pct"] <= 5.0

    rendered = render_parity_report(report)
    assert "Parity Match Report: [PASS]" in rendered


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


def test_cli_parity():
    result = runner.invoke(
        app,
        [
            "parity",
            "S-012@v2",
            "fixtures/tv_trades_S-012_v2.csv",
        ],
    )
    assert result.exit_code == 0
    assert "Parity Match Report" in result.stdout
    assert "Matched Entries: 71/71" in result.stdout
