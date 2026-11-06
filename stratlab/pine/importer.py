"""Reverse-mapping parser converting simple Pine Script strategies into StrategySpec."""

import re
from pathlib import Path
from typing import Any


def import_pine_to_spec(pine_code: str) -> dict[str, Any]:
    """Parse a Pine Script v5/v6 code string into a draft StrategySpec dictionary or unsupported report."""
    unsupported: list[str] = []

    # Check for unsupported constructs
    unsupported_patterns = [
        (r"request\.security", "Multi-timeframe data (request.security)"),
        (r"for\s+[a-zA-Z0-9_]+\s*=", "Custom loops (for/while)"),
        (r"array\.", "Arrays (array.*)"),
        (r"matrix\.", "Matrices (matrix.*)"),
        (r"strategy\.order", "Custom orders (strategy.order)"),
    ]
    for pat, desc in unsupported_patterns:
        if re.search(pat, pine_code):
            unsupported.append(desc)

    # Strategy settings
    title_match = re.search(r'strategy\s*\(\s*(?:title\s*=\s*)?["\']([^"\']+)["\']', pine_code)
    strategy_name = title_match.group(1) if title_match else "Imported Pine Strategy"

    comm_match = re.search(r'commission_value\s*=\s*([0-9.]+)', pine_code)
    commission_pct = float(comm_match.group(1)) if comm_match else 0.1

    slip_match = re.search(r'slippage\s*=\s*([0-9]+)', pine_code)
    slippage_ticks = int(slip_match.group(1)) if slip_match else 1

    # Extract inputs
    params: dict[str, Any] = {}
    input_matches = re.finditer(
        r'([a-zA-Z0-9_]+)\s*=\s*input\.(int|float)\s*\(\s*([0-9.]+)(?:.*?minval\s*=\s*([0-9.]+))?(?:.*?maxval\s*=\s*([0-9.]+))?(?:.*?step\s*=\s*([0-9.]+))?',
        pine_code,
    )
    for m in input_matches:
        p_name = m.group(1)
        p_type = m.group(2)
        default_v = float(m.group(3)) if p_type == "float" or "." in m.group(3) else int(m.group(3))
        min_v = m.group(4)
        max_v = m.group(5)
        step_v = m.group(6)

        if min_v is not None and max_v is not None and step_v is not None:
            conv = float if p_type == "float" else int
            params[p_name] = {
                "default": default_v,
                "range": [conv(min_v), conv(max_v), conv(step_v)],
                "fixed": False,
            }
        else:
            params[p_name] = {"default": default_v, "fixed": True}

    # Extract standard indicators
    indicators: dict[str, Any] = {}
    # SMA / EMA / RSI / ATR
    ind_matches = re.finditer(
        r'([a-zA-Z0-9_]+)\s*=\s*ta\.(sma|ema|wma|rma|rsi|atr)\s*\(\s*([a-zA-Z0-9_]+)?\s*,?\s*([a-zA-Z0-9_]+)?\s*\)',
        pine_code,
    )
    for m in ind_matches:
        ind_name = m.group(1)
        fn_name = m.group(2)
        arg1 = m.group(3)
        arg2 = m.group(4)

        if fn_name == "atr":
            len_val = f"${arg1}" if arg1 in params else (int(arg1) if arg1 and arg1.isdigit() else 14)
            indicators[ind_name] = {"fn": "atr", "len": len_val}
        else:
            src_val = arg1 if arg1 in ("open", "high", "low", "close", "volume") else "close"
            len_arg = arg2 if arg2 else arg1
            len_val = f"${len_arg}" if len_arg in params else (int(len_arg) if len_arg and len_arg.isdigit() else 14)
            indicators[ind_name] = {"fn": fn_name, "src": src_val, "len": len_val}

    # Draft Spec
    spec_dict = {
        "id": "IMPORTED-01",
        "version": 1,
        "name": strategy_name,
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
        "params": params,
        "indicators": indicators,
        "entry": {
            "long": {"crosses_above": ["close", "sma"]} if "sma" in indicators else {"gt": ["close", "open"]},
        },
        "exit": {
            "stop": {"atr_mult": "$atr_stop"} if "atr_stop" in params else None,
            "target": {"atr_mult": "$atr_tp"} if "atr_tp" in params else None,
        },
        "risk": {
            "sizing": "percent_equity",
            "value": 100,
            "initial_capital": 10000,
            "pyramiding": 0,
        },
        "costs": {
            "commission_pct": commission_pct,
            "slippage_ticks": slippage_ticks,
            "tick_size": 0.01,
        },
    }

    return {
        "supported": len(unsupported) == 0,
        "unsupported_features": unsupported,
        "spec_dict": spec_dict,
    }


def import_pine_file(path: Path | str) -> dict[str, Any]:
    """Read a .pine file and import into StrategySpec draft."""
    with open(path, "r", encoding="utf-8") as f:
        code = f.read()
    return import_pine_to_spec(code)
