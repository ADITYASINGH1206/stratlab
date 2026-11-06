"""Diff engine comparing two StrategySpec configurations."""

from pathlib import Path
from typing import Any

from stratlab.spec.validate import validate_spec_file


def diff_specs(spec_a_path: Path | str, spec_b_path: Path | str) -> dict[str, Any]:
    """Compare two spec files and produce a structured differences dictionary."""
    res_a = validate_spec_file(spec_a_path)
    res_b = validate_spec_file(spec_b_path)

    if not res_a.is_valid:
        raise ValueError(f"Spec A ({spec_a_path}) is invalid: {'; '.join(res_a.errors)}")
    if not res_b.is_valid:
        raise ValueError(f"Spec B ({spec_b_path}) is invalid: {'; '.join(res_b.errors)}")

    spec_a = res_a.spec
    spec_b = res_b.spec

    diff: dict[str, Any] = {
        "id": {"a": spec_a.id, "b": spec_b.id},
        "version": {"a": spec_a.version, "b": spec_b.version},
        "name": {"a": spec_a.name, "b": spec_b.name},
        "market": {},
        "params": {"added": {}, "removed": {}, "changed": {}},
        "indicators": {"added": {}, "removed": {}, "changed": {}},
        "entry": {},
        "exit": {},
        "costs": {},
    }

    # Market diff
    if spec_a.market.model_dump() != spec_b.market.model_dump():
        diff["market"] = {"a": spec_a.market.model_dump(), "b": spec_b.market.model_dump()}

    # Params diff
    a_params = {k: v.model_dump() for k, v in spec_a.params.items()}
    b_params = {k: v.model_dump() for k, v in spec_b.params.items()}

    for k in b_params:
        if k not in a_params:
            diff["params"]["added"][k] = b_params[k]
        elif a_params[k] != b_params[k]:
            diff["params"]["changed"][k] = {"from": a_params[k], "to": b_params[k]}

    for k in a_params:
        if k not in b_params:
            diff["params"]["removed"][k] = a_params[k]

    # Indicators diff
    a_inds = {k: v.model_dump(exclude_none=True) for k, v in spec_a.indicators.items()}
    b_inds = {k: v.model_dump(exclude_none=True) for k, v in spec_b.indicators.items()}

    for k in b_inds:
        if k not in a_inds:
            diff["indicators"]["added"][k] = b_inds[k]
        elif a_inds[k] != b_inds[k]:
            diff["indicators"]["changed"][k] = {"from": a_inds[k], "to": b_inds[k]}

    for k in a_inds:
        if k not in b_inds:
            diff["indicators"]["removed"][k] = a_inds[k]

    # Entry diff
    if spec_a.entry.model_dump() != spec_b.entry.model_dump():
        diff["entry"] = {"a": spec_a.entry.model_dump(), "b": spec_b.entry.model_dump()}

    # Exit diff
    if spec_a.exit.model_dump() != spec_b.exit.model_dump():
        diff["exit"] = {"a": spec_a.exit.model_dump(), "b": spec_b.exit.model_dump()}

    # Costs diff
    if spec_a.costs.model_dump() != spec_b.costs.model_dump():
        diff["costs"] = {"a": spec_a.costs.model_dump(), "b": spec_b.costs.model_dump()}

    return diff


def render_diff_text(diff: dict[str, Any]) -> str:
    """Format a diff dictionary into readable text for CLI and chat messages."""
    lines = [
        f"Diff: {diff['id']['a']}@v{diff['version']['a']} -> {diff['id']['b']}@v{diff['version']['b']}"
    ]

    # Params
    params = diff["params"]
    if params["added"] or params["removed"] or params["changed"]:
        lines.append("\nParameters:")
        for k, v in params["added"].items():
            lines.append(f"  + {k}: {v['default']} (range: {v.get('range')})")
        for k, v in params["removed"].items():
            lines.append(f"  - {k}: {v['default']}")
        for k, change in params["changed"].items():
            lines.append(f"  ~ {k}: {change['from']} -> {change['to']}")

    # Indicators
    inds = diff["indicators"]
    if inds["added"] or inds["removed"] or inds["changed"]:
        lines.append("\nIndicators:")
        for k, v in inds["added"].items():
            lines.append(f"  + {k}: {v}")
        for k, v in inds["removed"].items():
            lines.append(f"  - {k}: {v}")
        for k, change in inds["changed"].items():
            lines.append(f"  ~ {k}: {change['from']} -> {change['to']}")

    # Entry / Exit
    if diff["entry"]:
        lines.append("\nEntry Rules:")
        lines.append("  ~ Entry conditions modified")
    if diff["exit"]:
        lines.append("\nExit Rules:")
        lines.append("  ~ Exit conditions modified")

    return "\n".join(lines)
