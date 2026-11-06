"""Validation engine for StrategySpec enforcing supported vocabulary and parameter references."""

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from stratlab.spec.models import StrategySpec

SUPPORTED_INDICATORS = {
    "sma", "ema", "wma", "rsi", "atr", "macd", "bb",
    "donchian", "stoch", "adx", "vwap", "highest", "lowest", "expr"
}

SUPPORTED_CONDITIONS = {
    "gt", "lt", "gte", "lte", "eq", "neq",
    "crosses_above", "crosses_below", "all", "any", "not"
}

BUILTIN_SERIES = {"open", "high", "low", "close", "volume"}


class ValidationResult:
    def __init__(self, is_valid: bool, spec: StrategySpec | None = None, errors: list[str] | None = None, warnings: list[str] | None = None):
        self.is_valid = is_valid
        self.spec = spec
        self.errors = errors or []
        self.warnings = warnings or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "spec_id": self.spec.id if self.spec else None,
            "version": self.spec.version if self.spec else None,
        }


def _extract_param_references(value: Any) -> list[str]:
    """Find all $param_name tokens in a string or nested structure."""
    refs = []
    if isinstance(value, str):
        for token in re.findall(r"\$([a-zA-Z0-9_]+)", value):
            refs.append(token)
    elif isinstance(value, dict):
        for v in value.values():
            refs.extend(_extract_param_references(v))
    elif isinstance(value, list):
        for item in value:
            refs.extend(_extract_param_references(item))
    return refs


def _validate_condition_node(
    node: Any,
    defined_indicators: set[str],
    defined_params: set[str],
    errors: list[str],
) -> None:
    if not isinstance(node, dict):
        errors.append(f"Condition node must be a dict, got {type(node).__name__}: {node}")
        return

    for op, val in node.items():
        if op not in SUPPORTED_CONDITIONS:
            errors.append(f"Unsupported condition operator '{op}'. Supported: {', '.join(sorted(SUPPORTED_CONDITIONS))}")
            continue

        if op in ("all", "any"):
            if not isinstance(val, list):
                errors.append(f"Condition '{op}' expects a list of conditions, got {type(val).__name__}")
            else:
                for sub_node in val:
                    _validate_condition_node(sub_node, defined_indicators, defined_params, errors)
        elif op == "not":
            _validate_condition_node(val, defined_indicators, defined_params, errors)
        else:
            # Binary or n-ary comparator: e.g. gt: [close, ema], crosses_above: [rsi, 30]
            if not isinstance(val, list) or len(val) != 2:
                errors.append(f"Comparator '{op}' expects a 2-element list [left, right], got: {val}")
                continue

            for operand in val:
                if isinstance(operand, str):
                    # Check if operand is $param
                    if operand.startswith("$"):
                        param_name = operand[1:]
                        if param_name not in defined_params:
                            errors.append(f"Undefined parameter reference '{operand}' in condition '{op}'")
                        continue

                    # Extract base series if offset present, e.g. close[1]
                    clean_op = re.sub(r"\[\d+\]$", "", operand.strip())
                    if clean_op not in BUILTIN_SERIES and clean_op not in defined_indicators:
                        # Check if it's a numeric string
                        try:
                            float(clean_op)
                        except ValueError:
                            errors.append(
                                f"Unknown series '{operand}' in condition '{op}'. Must be OHLCV or defined indicator in {sorted(defined_indicators)}"
                            )


def validate_spec_dict(data: dict[str, Any]) -> ValidationResult:
    """Validate a parsed dictionary against StrategySpec and vocabulary constraints."""
    errors: list[str] = []
    warnings: list[str] = []

    try:
        spec = StrategySpec.model_validate(data)
    except ValidationError as e:
        for err in e.errors():
            loc = " -> ".join(str(x) for x in err["loc"])
            errors.append(f"Schema error at '{loc}': {err['msg']}")
        return ValidationResult(is_valid=False, errors=errors, warnings=warnings)

    # 1. Date format check
    for field_name, dt_str in [("start", spec.period.start), ("end", spec.period.end)]:
        try:
            datetime.strptime(dt_str, "%Y-%m-%d")
        except ValueError:
            errors.append(f"Invalid date format for period.{field_name}: '{dt_str}'. Expected YYYY-MM-DD")

    # 2. Check parameter references across indicators, entry, exit
    defined_params = set(spec.params.keys())

    # Check indicators
    for ind_name, ind_cfg in spec.indicators.items():
        if ind_cfg.fn not in SUPPORTED_INDICATORS:
            errors.append(
                f"Unsupported indicator function '{ind_cfg.fn}' in '{ind_name}'. Supported: {', '.join(sorted(SUPPORTED_INDICATORS))}"
            )
        # Check source
        if ind_cfg.src and ind_cfg.src not in BUILTIN_SERIES and ind_cfg.src not in spec.indicators:
            errors.append(
                f"Indicator '{ind_name}' source '{ind_cfg.src}' is not a valid OHLCV series or defined indicator"
            )

        # Check param references in fields
        for field in [ind_cfg.len, ind_cfg.fast, ind_cfg.slow, ind_cfg.signal, ind_cfg.mult]:
            if isinstance(field, str) and field.startswith("$"):
                p = field[1:]
                if p not in defined_params:
                    errors.append(f"Undefined parameter reference '{field}' in indicator '{ind_name}'")

    # 3. Check param references in exit configs
    if spec.exit.stop and spec.exit.stop.atr_mult:
        if isinstance(spec.exit.stop.atr_mult, str) and spec.exit.stop.atr_mult.startswith("$"):
            p = spec.exit.stop.atr_mult[1:]
            if p not in defined_params:
                errors.append(f"Undefined parameter reference '{spec.exit.stop.atr_mult}' in exit.stop.atr_mult")

    if spec.exit.target and spec.exit.target.atr_mult:
        if isinstance(spec.exit.target.atr_mult, str) and spec.exit.target.atr_mult.startswith("$"):
            p = spec.exit.target.atr_mult[1:]
            if p not in defined_params:
                errors.append(f"Undefined parameter reference '{spec.exit.target.atr_mult}' in exit.target.atr_mult")

    # 4. Check entry conditions
    defined_indicators = set(spec.indicators.keys())
    if spec.entry.long:
        _validate_condition_node(spec.entry.long, defined_indicators, defined_params, errors)
    if spec.entry.short:
        _validate_condition_node(spec.entry.short, defined_indicators, defined_params, errors)

    return ValidationResult(
        is_valid=len(errors) == 0,
        spec=spec,
        errors=errors,
        warnings=warnings,
    )


def validate_spec_file(path: Path | str) -> ValidationResult:
    """Load and validate a YAML spec file from disk."""
    p = Path(path)
    if not p.exists():
        return ValidationResult(is_valid=False, errors=[f"File not found: {p}"])

    try:
        with open(p, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f)
    except Exception as e:
        return ValidationResult(is_valid=False, errors=[f"YAML parsing error: {e}"])

    if not isinstance(raw_data, dict):
        return ValidationResult(is_valid=False, errors=["Spec file must be a YAML dictionary"])

    return validate_spec_dict(raw_data)
