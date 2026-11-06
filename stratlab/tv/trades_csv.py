"""Parser for TradingView Strategy Tester "List of Trades" CSV exports.

TradingView has changed these headers over time ("Profit USD" vs "Net P&L USDT", "Contracts"
vs "Position size (qty)", "Date/Time" vs "Date and time"), so columns are found by name, and
an export we cannot read fails with the headers we saw. Trades still open at the end of the
export (exit signal "Open") are skipped, since the engine does not count them either.

Set the chart timezone to UTC before exporting: the engine's timestamps are UTC.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED = ("trade number", "type", "date/time", "price")


def _pick(columns: list[str], include: tuple[str, ...], exclude: tuple[str, ...] = ()) -> str | None:
    for col in columns:
        low = col.lower().strip()
        if any(k in low for k in include) and not any(x in low for x in exclude):
            return col
    return None


def detect_columns(columns: list[str]) -> dict[str, str | None]:
    return {
        "trade": _pick(columns, ("trade #", "trade number", "trade no")) or next((c for c in columns if c.strip().lower() in ("trade", "#")), None),
        "type": _pick(columns, ("type",)),
        "signal": _pick(columns, ("signal",)),
        "datetime": _pick(columns, ("date/time", "date and time", "datetime", "date", "time")),
        "price": _pick(columns, ("price",)),
        "qty": _pick(columns, ("position size (qty)", "contracts", "quantity", "qty", "shares"), ("value",)),
        "profit": _pick(columns, ("net p&l", "p&l", "profit"), ("%", "cum", "run-up", "drawdown")),
    }


def _num(val) -> float:
    if pd.isna(val):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace("−", "-").replace("$", "").replace(",", "").replace("%", "").strip()
    for unit in ("USDT", "USDC", "USD", "BTC"):
        s = s.replace(unit, "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_tv_trades_csv(csv_path: Path | str) -> pd.DataFrame:
    """Return one row per closed trade: trade_num, direction, entry/exit time and price, qty, profit."""
    p = Path(csv_path)
    if not p.exists():
        raise FileNotFoundError(f"TradingView trades CSV not found: {p}")
    raw = pd.read_csv(p, encoding="utf-8-sig")
    cols = [str(c) for c in raw.columns]
    found = detect_columns(cols)
    missing = [name for name, key in zip(REQUIRED, ("trade", "type", "datetime", "price")) if not found[key]]
    if missing:
        raise ValueError(
            f"Not a TradingView 'List of Trades' export: missing {', '.join(missing)} column(s). "
            f"Headers seen: {cols}. Export it from Strategy Tester > List of Trades > Export."
        )

    raw[found["datetime"]] = pd.to_datetime(raw[found["datetime"]])
    types = raw[found["type"]].astype(str).str.lower()
    trades = []
    for t_id, group in raw.groupby(found["trade"], sort=False):
        g_types = types.loc[group.index]
        entry = group[g_types.str.contains("entry")]
        exit_ = group[g_types.str.contains("exit")]
        if entry.empty or exit_.empty:
            continue
        e, x = entry.iloc[0], exit_.iloc[0]
        if found["signal"] and str(x[found["signal"]]).strip().lower() == "open":
            continue
        qty = _num(e[found["qty"]]) if found["qty"] else 0.0
        e_px, x_px = _num(e[found["price"]]), _num(x[found["price"]])
        trades.append({
            "trade_num": int(_num(t_id)),
            "direction": "short" if "short" in str(e[found["type"]]).lower() else "long",
            "entry_time": e[found["datetime"]],
            "entry_price": e_px,
            "exit_time": x[found["datetime"]],
            "exit_price": x_px,
            "exit_signal": str(x[found["signal"]]) if found["signal"] else "",
            "qty": qty,
            "profit": _num(x[found["profit"]]) if found["profit"] else (x_px - e_px) * qty,
        })
    if not trades:
        return pd.DataFrame(columns=["trade_num", "direction", "entry_time", "entry_price", "exit_time",
                                     "exit_price", "exit_signal", "qty", "profit"])
    return pd.DataFrame(trades).sort_values("entry_time").reset_index(drop=True)


def write_tv_style_csv(trades: pd.DataFrame, path: Path | str, currency: str = "USDT") -> Path:
    """Write engine trades in TradingView's export layout (used by the matcher self-test)."""
    rows = []
    for _, t in trades.iterrows():
        n = int(t["trade_num"])
        rows.append({"Trade #": n, "Type": "Exit long", "Date/Time": t["exit_time"], "Signal": t.get("reason", ""),
                     f"Price {currency}": t["exit_price"], "Position size (qty)": t["qty"],
                     f"Net P&L {currency}": t["pnl"], "Net P&L %": t.get("return_pct", 0.0)})
        rows.append({"Trade #": n, "Type": "Entry long", "Date/Time": t["entry_time"], "Signal": "Long",
                     f"Price {currency}": t["entry_price"], "Position size (qty)": t["qty"],
                     f"Net P&L {currency}": "", "Net P&L %": ""})
    out = Path(path)
    pd.DataFrame(rows).to_csv(out, index=False)
    return out
