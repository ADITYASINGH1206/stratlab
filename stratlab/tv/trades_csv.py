"""Parser for TradingView Strategy Tester 'List of Trades' CSV exports."""

from pathlib import Path

import pandas as pd


def _find_column(columns: list[str], keywords: list[str]) -> str | None:
    """Find a column that matches any keyword in keywords (case-insensitive)."""
    for col in columns:
        low = col.lower().strip()
        for kw in keywords:
            if kw.lower() in low:
                return col
    return None


def parse_tv_trades_csv(csv_path: Path | str) -> pd.DataFrame:
    """Parse TradingView List of Trades CSV export into normalized DataFrame."""
    p = Path(csv_path)
    if not p.exists():
        raise FileNotFoundError(f"TradingView trades CSV not found: {p}")

    df_raw = pd.read_csv(p)
    cols = list(df_raw.columns)

    trade_num_col = _find_column(cols, ["trade #", "trade number", "trade", "#"])
    type_col = _find_column(cols, ["type", "action", "signal"])
    datetime_col = _find_column(cols, ["date/time", "date and time", "date", "time"])
    price_col = _find_column(cols, ["price", "price usd", "fill price"])
    contracts_col = _find_column(cols, ["contracts", "shares", "size", "qty", "amount"])
    profit_col = _find_column(cols, ["profit usd", "profit", "net profit", "pnl"])

    if not trade_num_col or not datetime_col or not price_col:
        raise ValueError(
            f"Unable to detect required TradingView trade headers in {cols}. "
            f"Found: trade_num={trade_num_col}, datetime={datetime_col}, price={price_col}"
        )

    # Clean numeric columns
    def clean_num(val):
        if pd.isna(val):
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).replace("$", "").replace(",", "").replace("%", "").strip()
        try:
            return float(s)
        except ValueError:
            return 0.0

    df_raw[price_col] = df_raw[price_col].apply(clean_num)
    df_raw[datetime_col] = pd.to_datetime(df_raw[datetime_col])

    # Check if single-row or two-rows per trade
    # If type_col has 'Entry' and 'Exit', group by trade_num
    trades = []
    if type_col and any("entry" in str(x).lower() for x in df_raw[type_col]):
        # Two rows per trade
        grouped = df_raw.groupby(trade_num_col)
        for t_id, group in grouped:
            entry_rows = group[group[type_col].str.lower().str.contains("entry")]
            exit_rows = group[group[type_col].str.lower().str.contains("exit")]

            if not entry_rows.empty and not exit_rows.empty:
                entry_row = entry_rows.iloc[0]
                exit_row = exit_rows.iloc[0]

                direction = "long" if "long" in str(entry_row[type_col]).lower() else "short"
                entry_t = entry_row[datetime_col]
                entry_px = entry_row[price_col]
                exit_t = exit_row[datetime_col]
                exit_px = exit_row[price_col]
                qty = clean_num(entry_row[contracts_col]) if contracts_col else 1.0
                profit = clean_num(exit_row[profit_col]) if profit_col else (exit_px - entry_px) * qty

                trades.append({
                    "trade_num": int(t_id),
                    "direction": direction,
                    "entry_time": entry_t,
                    "entry_price": entry_px,
                    "exit_time": exit_t,
                    "exit_price": exit_px,
                    "qty": qty,
                    "profit": profit,
                })
    else:
        # One row per trade or chronological trades
        for idx, row in df_raw.iterrows():
            t_id = row[trade_num_col] if trade_num_col else idx + 1
            direction = "long"
            if type_col and "short" in str(row[type_col]).lower():
                direction = "short"

            trades.append({
                "trade_num": int(clean_num(t_id)),
                "direction": direction,
                "entry_time": row[datetime_col],
                "entry_price": row[price_col],
                "exit_time": row[datetime_col],
                "exit_price": row[price_col],
                "qty": clean_num(row[contracts_col]) if contracts_col else 1.0,
                "profit": clean_num(row[profit_col]) if profit_col else 0.0,
            })

    result_df = pd.DataFrame(trades).sort_values("entry_time").reset_index(drop=True)
    return result_df
