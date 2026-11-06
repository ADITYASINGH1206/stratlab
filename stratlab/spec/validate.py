"""Validation engine for StrategySpec enforcing supported vocabulary and parameter references."""

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from stratlab.engine.indicators import check_expression
from stratlab.spec.models import StrategySpec

# Only what BOTH the Python engine and the Pine generator implement. Anything else is
# rejected up front with a readable message instead of failing halfway through a run.
SUPPORTED_INDICATORS = {"sma", "ema", "wma", "rma", "rsi", "atr", "highest", "lowest", "expr"}
NOT_YET_SUPPORTED = {"macd", "bb", "donchian", "stoch", "adx", "vwap"}
INT_FIELDS = ("len",)

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


def _is_int_param(p) -> bool:
    vals = [p.default] + list(p.range or [])
    return all(float(v).is_integer() for v in vals)


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

    defined_params = set(spec.params.keys())

    # 2. Every $param anywhere in the spec must be declared
    for ref in sorted(set(_extract_param_references(data))):
        if ref not in defined_params:
            errors.append(f"Undefined parameter reference '${ref}'. Declared params: {sorted(defined_params) or 'none'}")

    # 3. Indicators: supported, defined in order, integer lengths, safe expressions
    known_series = set(BUILTIN_SERIES)
    for ind_name, ind_cfg in spec.indicators.items():
        fn = ind_cfg.fn.lower()
        if ind_name in BUILTIN_SERIES:
            errors.append(f"Indicator name '{ind_name}' shadows a price series; pick another name")
        if fn in NOT_YET_SUPPORTED:
            errors.append(
                f"Indicator '{ind_name}' uses '{fn}', which is not supported yet in both the engine and the "
                f"Pine generator. Supported: {', '.join(sorted(SUPPORTED_INDICATORS))}. "
                f"Tip: build it from these, e.g. a Donchian upper band is highest(high, n)."
            )
        elif fn not in SUPPORTED_INDICATORS:
            errors.append(
                f"Unsupported indicator function '{ind_cfg.fn}' in '{ind_name}'. Supported: {', '.join(sorted(SUPPORTED_INDICATORS))}"
            )
        if fn == "expr":
            if not ind_cfg.expr:
                errors.append(f"Indicator '{ind_name}' (fn: expr) needs an `expr`")
            else:
                errors.extend(f"Indicator '{ind_name}': {m}" for m in check_expression(ind_cfg.expr, known_series))
        else:
            if fn != "atr" and ind_cfg.src and ind_cfg.src not in known_series:
                errors.append(
                    f"Indicator '{ind_name}' source '{ind_cfg.src}' must be an OHLCV series or an indicator defined above it"
                )
            if ind_cfg.len is None:
                errors.append(f"Indicator '{ind_name}' (fn: {fn}) needs `len`")
            elif isinstance(ind_cfg.len, str):
                pname = ind_cfg.len[1:] if ind_cfg.len.startswith("$") else None
                if pname in spec.params and not _is_int_param(spec.params[pname]):
                    errors.append(f"Indicator '{ind_name}' length uses ${pname}, which must be an integer param")
        known_series.add(ind_name)

    # 4. Exits the engine can simulate
    has_atr = any(i.fn.lower() == "atr" for i in spec.indicators.values())
    for label, lvl in (("stop", spec.exit.stop), ("target", spec.exit.target)):
        if lvl is None:
            continue
        if getattr(lvl, "price", None) is not None:
            errors.append(f"exit.{label}.price is not supported yet; use atr_mult or pct")
        if lvl.atr_mult is not None and lvl.pct is not None:
            errors.append(f"exit.{label}: give atr_mult or pct, not both")
        if lvl.atr_mult is None and lvl.pct is None and getattr(lvl, "price", None) is None:
            errors.append(f"exit.{label}: give atr_mult or pct")
        if lvl.atr_mult is not None and not has_atr:
            errors.append(f"exit.{label}.atr_mult needs an indicator with fn: atr")
    if spec.exit.time and isinstance(spec.exit.time.bars, str):
        pname = spec.exit.time.bars.lstrip("$")
        if pname in spec.params and not _is_int_param(spec.params[pname]):
            errors.append(f"exit.time.bars uses ${pname}, which must be an integer param")
    if spec.exit.opposite_signal and not spec.entry.short:
        errors.append(
            "exit.opposite_signal needs an entry.short condition: it is the bearish signal that closes the long"
        )
    if not (spec.exit.stop or spec.exit.target or spec.exit.time or spec.exit.opposite_signal):
        errors.append("Define at least one exit: stop, target, time or opposite_signal (otherwise a trade never closes)")

    # 5. What the v1 engine simulates
    if spec.direction != "long":
        errors.append(
            f"direction '{spec.direction}' is not supported yet: the engine is long-only. Use direction: long; "
            f"entry.short with exit.opposite_signal closes the long on a bearish signal."
        )
    if spec.risk.sizing != "percent_equity" or spec.risk.value != 100:
        errors.append("risk: only sizing percent_equity with value 100 is supported (matches the Pine strategy() defaults)")
    if spec.risk.pyramiding != 0:
        errors.append("risk.pyramiding must be 0 (one position at a time)")
    if spec.period.oos_fraction < 0.1 or spec.period.oos_fraction > 0.5:
        errors.append("period.oos_fraction must be between 0.1 and 0.5")

    # 6. Conditions
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
