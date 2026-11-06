"""Pine Script v6 code generation from StrategySpec."""

from typing import Any

from jinja2 import Template

from stratlab.spec.models import StrategySpec


def _param_ref_to_var(token: str) -> str:
    """Convert $param_name to param_name."""
    if isinstance(token, str) and token.startswith("$"):
        return token[1:]
    return str(token)


def _condition_to_pine(node: dict[str, Any]) -> str:
    """Recursively convert condition AST into a Pine Script boolean expression."""
    if not node:
        return "true"

    op = next(iter(node.keys()))
    val = node[op]

    if op == "all":
        parts = [_condition_to_pine(sub) for sub in val]
        return "(" + " and ".join(parts) + ")"

    if op == "any":
        parts = [_condition_to_pine(sub) for sub in val]
        return "(" + " or ".join(parts) + ")"

    if op == "not":
        sub = _condition_to_pine(val)
        return f"(not {sub})"

    left_str = _param_ref_to_var(val[0])
    right_str = _param_ref_to_var(val[1])

    if op == "crosses_above":
        return f"ta.crossover({left_str}, {right_str})"
    if op == "crosses_below":
        return f"ta.crossunder({left_str}, {right_str})"
    if op == "gt":
        return f"({left_str} > {right_str})"
    if op == "lt":
        return f"({left_str} < {right_str})"
    if op == "gte":
        return f"({left_str} >= {right_str})"
    if op == "lte":
        return f"({left_str} <= {right_str})"
    if op == "eq":
        return f"({left_str} == {right_str})"
    if op == "neq":
        return f"({left_str} != {right_str})"

    return f"/* unsupported op {op} */ true"


PINE_V6_TEMPLATE = """//@version=6
// StratLab Generated Strategy: {{ spec.id }} v{{ spec.version }}
// Name: {{ spec.name }}
// Market: {{ spec.market.tv_symbol }} ({{ spec.market.timeframe }})
// Generated automatically by StratLab. Do not hand-edit.
strategy(
    title = "{{ spec.id }} v{{ spec.version }}: {{ spec.name }}",
    shorttitle = "{{ spec.id }}@v{{ spec.version }}",
    overlay = true,
    initial_capital = {{ spec.risk.initial_capital }},
    default_qty_type = strategy.percent_of_equity,
    default_qty_value = {{ spec.risk.value }},
    commission_type = strategy.commission.percent,
    commission_value = {{ spec.costs.commission_pct }},
    slippage = {{ spec.costs.slippage_ticks }},
    pyramiding = {{ spec.risk.pyramiding }},
    process_orders_on_close = false
)

// === Date Range Filter ===
inDateRange = time >= timestamp("{{ spec.period.start }}T00:00:00Z") and time <= timestamp("{{ spec.period.end }}T23:59:59Z")

// === Inputs ===
{% for p_name, p_cfg in spec.params.items() %}
{% if p_cfg.range %}
{% if p_cfg.range[0] is integer and p_cfg.range[1] is integer and p_cfg.range[2] is integer %}
{{ p_name }} = input.int({{ p_cfg.default }}, title="{{ p_name }}", minval={{ p_cfg.range[0] }}, maxval={{ p_cfg.range[1] }}, step={{ p_cfg.range[2] }})
{% else %}
{{ p_name }} = input.float({{ p_cfg.default }}, title="{{ p_name }}", minval={{ p_cfg.range[0] }}, maxval={{ p_cfg.range[1] }}, step={{ p_cfg.range[2] }})
{% endif %}
{% else %}
{% if p_cfg.default is integer %}
{{ p_name }} = input.int({{ p_cfg.default }}, title="{{ p_name }}")
{% else %}
{{ p_name }} = input.float({{ p_cfg.default }}, title="{{ p_name }}")
{% endif %}
{% endif %}
{% endfor %}

// === Indicators ===
{% for ind_name, ind_cfg in spec.indicators.items() %}
{% set fn = ind_cfg.fn.lower() %}
{% if fn == "sma" %}
{{ ind_name }} = ta.sma({{ ind_cfg.src or "close" }}, {{ ind_cfg.len | replace("$", "") }})
{% elif fn == "ema" %}
{{ ind_name }} = ta.ema({{ ind_cfg.src or "close" }}, {{ ind_cfg.len | replace("$", "") }})
{% elif fn == "wma" %}
{{ ind_name }} = ta.wma({{ ind_cfg.src or "close" }}, {{ ind_cfg.len | replace("$", "") }})
{% elif fn == "rma" %}
{{ ind_name }} = ta.rma({{ ind_cfg.src or "close" }}, {{ ind_cfg.len | replace("$", "") }})
{% elif fn == "rsi" %}
{{ ind_name }} = ta.rsi({{ ind_cfg.src or "close" }}, {{ ind_cfg.len | replace("$", "") }})
{% elif fn == "atr" %}
{{ ind_name }} = ta.atr({{ ind_cfg.len | replace("$", "") }})
{% elif fn == "highest" %}
{{ ind_name }} = ta.highest({{ ind_cfg.src or "high" }}, {{ ind_cfg.len | replace("$", "") }})
{% elif fn == "lowest" %}
{{ ind_name }} = ta.lowest({{ ind_cfg.src or "low" }}, {{ ind_cfg.len | replace("$", "") }})
{% elif fn == "expr" %}
{{ ind_name }} = {{ ind_cfg.expr }}
{% endif %}
{% endfor %}

// === Execution State Variables ===
var float stopPx = na
var float tpPx = na
var int entryBarIndex = na

// === Conditions ===
{% if spec.entry.long %}
longSignal = inDateRange and {{ long_condition_code }}
{% else %}
longSignal = false
{% endif %}

// === Orders & Execution ===
if longSignal and strategy.position_size == 0
    strategy.entry("Long", strategy.long)
    entryBarIndex := bar_index
{% if spec.exit.stop and spec.exit.stop.atr_mult %}
    stopPx := close - ({{ spec.exit.stop.atr_mult | replace("$", "") }} * atr)
{% elif spec.exit.stop and spec.exit.stop.pct %}
    stopPx := close * (1.0 - ({{ spec.exit.stop.pct | replace("$", "") }} / 100.0))
{% else %}
    stopPx := na
{% endif %}
{% if spec.exit.target and spec.exit.target.atr_mult %}
    tpPx := close + ({{ spec.exit.target.atr_mult | replace("$", "") }} * atr)
{% elif spec.exit.target and spec.exit.target.pct %}
    tpPx := close * (1.0 + ({{ spec.exit.target.pct | replace("$", "") }} / 100.0))
{% else %}
    tpPx := na
{% endif %}

{% if spec.exit.time and spec.exit.time.bars %}
if strategy.position_size > 0 and (bar_index - entryBarIndex) >= {{ spec.exit.time.bars }}
    strategy.close("Long", comment="Time Exit")
{% endif %}

if strategy.position_size > 0
    strategy.exit("Exit Long", from_entry="Long", stop=stopPx, limit=tpPx)

if strategy.position_size == 0
    stopPx := na
    tpPx := na
    entryBarIndex := na
"""


def generate_pine_script(spec: StrategySpec) -> str:
    """Render StrategySpec into valid Pine Script v6 strategy code."""
    long_code = _condition_to_pine(spec.entry.long) if spec.entry.long else "false"
    template = Template(PINE_V6_TEMPLATE)
    return template.render(spec=spec, long_condition_code=long_code)
