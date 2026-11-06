"""Tests for StrategySpec models, validation, diffing, and schema generation."""

from pathlib import Path

from stratlab.spec.diff import diff_specs, render_diff_text
from stratlab.spec.models import StrategySpec
from stratlab.spec.validate import validate_spec_dict, validate_spec_file

SPEC_DIR = Path(__file__).resolve().parent.parent / "examples" / "specs"


def test_validate_all_example_specs():
    specs = [
        SPEC_DIR / "S-001" / "v1.yaml",
        SPEC_DIR / "S-012" / "v1.yaml",
        SPEC_DIR / "S-012" / "v2.yaml",
        SPEC_DIR / "S-020" / "v1.yaml",
    ]
    for spec_path in specs:
        assert spec_path.exists(), f"Spec file missing: {spec_path}"
        result = validate_spec_file(spec_path)
        assert result.is_valid, f"Spec {spec_path} failed validation: {result.errors}"
        assert result.spec is not None
        assert result.spec.id in ("S-001", "S-012", "S-020")


def test_schema_generation():
    schema = StrategySpec.model_json_schema()
    assert isinstance(schema, dict)
    assert schema["title"] == "StrategySpec"
    assert "properties" in schema
    assert "market" in schema["properties"]
    assert "params" in schema["properties"]
    assert "indicators" in schema["properties"]
    assert "entry" in schema["properties"]


def test_invalid_indicator_function():
    invalid_data = {
        "id": "S-999",
        "version": 1,
        "name": "Invalid Indicator Spec",
        "market": {"symbol": "BTCUSDT", "exchange": "binance", "tv_symbol": "BINANCE:BTCUSDT", "timeframe": "4h"},
        "period": {"start": "2021-01-01", "end": "2025-12-31"},
        "direction": "long",
        "params": {},
        "indicators": {
            "my_ind": {"fn": "magic_quantum_oscillator", "src": "close"},
        },
        "entry": {"long": {"gt": ["close", "my_ind"]}},
    }
    res = validate_spec_dict(invalid_data)
    assert not res.is_valid
    assert any("Unsupported indicator function 'magic_quantum_oscillator'" in err for err in res.errors)


def test_undefined_param_reference():
    invalid_data = {
        "id": "S-998",
        "version": 1,
        "name": "Undefined Param",
        "market": {"symbol": "BTCUSDT", "exchange": "binance", "tv_symbol": "BINANCE:BTCUSDT", "timeframe": "4h"},
        "period": {"start": "2021-01-01", "end": "2025-12-31"},
        "direction": "long",
        "params": {
            "rsi_len": {"default": 14},
        },
        "indicators": {
            "rsi": {"fn": "rsi", "src": "close", "len": "$unknown_param"},
        },
        "entry": {"long": {"gt": ["rsi", 30]}},
    }
    res = validate_spec_dict(invalid_data)
    assert not res.is_valid
    assert any("Undefined parameter reference '$unknown_param'" in err for err in res.errors)


def test_missing_direction_entry():
    invalid_data = {
        "id": "S-997",
        "version": 1,
        "name": "Missing Entry",
        "market": {"symbol": "BTCUSDT", "exchange": "binance", "tv_symbol": "BINANCE:BTCUSDT", "timeframe": "4h"},
        "period": {"start": "2021-01-01", "end": "2025-12-31"},
        "direction": "long",
        "params": {},
        "indicators": {},
        "entry": {},  # Missing long entry
    }
    res = validate_spec_dict(invalid_data)
    assert not res.is_valid
    assert any("direction 'long' requires entry.long condition" in err for err in res.errors)


def test_spec_diff():
    spec_v1 = SPEC_DIR / "S-012" / "v1.yaml"
    spec_v2 = SPEC_DIR / "S-012" / "v2.yaml"
    diff = diff_specs(spec_v1, spec_v2)

    assert diff["id"]["a"] == "S-012"
    assert diff["version"]["a"] == 1
    assert diff["version"]["b"] == 2
    assert "atrp" in diff["indicators"]["added"]
    assert "rsi_len" in diff["params"]["changed"]

    diff_text = render_diff_text(diff)
    assert "S-012@v1 -> S-012@v2" in diff_text
    assert "atrp" in diff_text
