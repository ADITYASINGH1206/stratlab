"""Evaluation engine for StrategySpec entry and exit conditions."""

import re
from typing import Any

import numpy as np


def _resolve_series(operand: Any, context: dict[str, np.ndarray], n_bars: int) -> np.ndarray:
    """Resolve an operand (string, number, or offset series) into a 1D NumPy float array."""
    if isinstance(operand, (int, float)):
        return np.full(n_bars, float(operand), dtype=np.float64)

    if isinstance(operand, str):
        op_str = operand.strip()
        # Check if numeric string
        try:
            val = float(op_str)
            return np.full(n_bars, val, dtype=np.float64)
        except ValueError:
            pass

        # Check for offset notation: e.g. close[1] or rsi[2]
        match = re.match(r"^([a-zA-Z0-9_]+)\[(\d+)\]$", op_str)
        if match:
            base_name, offset_str = match.groups()
            offset = int(offset_str)
            if base_name not in context:
                raise KeyError(f"Series '{base_name}' not found in indicator context")
            base_series = context[base_name]
            shifted = np.full(n_bars, np.nan, dtype=np.float64)
            if offset < n_bars:
                shifted[offset:] = base_series[:-offset]
            return shifted

        if op_str not in context:
            raise KeyError(f"Series '{op_str}' not found in indicator context. Available: {list(context.keys())}")

        return context[op_str].astype(np.float64)

    raise TypeError(f"Cannot resolve operand of type {type(operand).__name__}: {operand}")


def evaluate_condition_tree(node: dict[str, Any], context: dict[str, np.ndarray], n_bars: int) -> np.ndarray:
    """Evaluate an entry condition tree into a boolean 1D array of length n_bars."""
    if not node:
        return np.zeros(n_bars, dtype=bool)

    # A node is expected to have one key: e.g. all, any, not, gt, lt, crosses_above, etc.
    op = next(iter(node.keys()))
    val = node[op]

    if op == "all":
        # Logical AND across sub-conditions
        res = np.ones(n_bars, dtype=bool)
        for sub_node in val:
            sub_res = evaluate_condition_tree(sub_node, context, n_bars)
            res = res & sub_res
        return res

    if op == "any":
        # Logical OR across sub-conditions
        res = np.zeros(n_bars, dtype=bool)
        for sub_node in val:
            sub_res = evaluate_condition_tree(sub_node, context, n_bars)
            res = res | sub_res
        return res

    if op == "not":
        # Logical NOT
        sub_res = evaluate_condition_tree(val, context, n_bars)
        return ~sub_res

    # Binary comparator: [left, right]
    left = _resolve_series(val[0], context, n_bars)
    right = _resolve_series(val[1], context, n_bars)

    if op == "gt":
        return (left > right) & ~np.isnan(left) & ~np.isnan(right)
    if op == "lt":
        return (left < right) & ~np.isnan(left) & ~np.isnan(right)
    if op == "gte":
        return (left >= right) & ~np.isnan(left) & ~np.isnan(right)
    if op == "lte":
        return (left <= right) & ~np.isnan(left) & ~np.isnan(right)
    if op == "eq":
        return np.isclose(left, right) & ~np.isnan(left) & ~np.isnan(right)
    if op == "neq":
        return ~np.isclose(left, right) & ~np.isnan(left) & ~np.isnan(right)

    if op == "crosses_above":
        # left[i] > right[i] and left[i-1] <= right[i-1]
        out = np.zeros(n_bars, dtype=bool)
        valid = ~np.isnan(left) & ~np.isnan(right)
        for i in range(1, n_bars):
            if valid[i] and valid[i - 1]:
                if left[i] > right[i] and left[i - 1] <= right[i - 1]:
                    out[i] = True
        return out

    if op == "crosses_below":
        # left[i] < right[i] and left[i-1] >= right[i-1]
        out = np.zeros(n_bars, dtype=bool)
        valid = ~np.isnan(left) & ~np.isnan(right)
        for i in range(1, n_bars):
            if valid[i] and valid[i - 1]:
                if left[i] < right[i] and left[i - 1] >= right[i - 1]:
                    out[i] = True
        return out

    raise ValueError(f"Unknown condition operator '{op}'")
