"""Performance metrics calculation for backtest trade logs and equity curves."""

from typing import Any

import numpy as np
import pandas as pd


def compute_metrics(
    trades_df: pd.DataFrame,
    equity_curve: np.ndarray,
    initial_capital: float = 10000.0,
    timeframe: str = "4h",
    total_bars: int = 1,
) -> dict[str, Any]:
    """Compute comprehensive trading strategy performance metrics."""
    n_trades = len(trades_df)
    final_equity = float(equity_curve[-1]) if len(equity_curve) > 0 else initial_capital
    net_profit = final_equity - initial_capital
    net_profit_pct = (net_profit / initial_capital) * 100.0

    if n_trades == 0:
        return {
            "trades": 0,
            "net_profit": 0.0,
            "net_profit_pct": 0.0,
            "cagr_pct": 0.0,
            "profit_factor": 0.0,
            "win_rate_pct": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "win_loss_ratio": 0.0,
            "expectancy": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "exposure_pct": 0.0,
        }

    pnls = trades_df["pnl"].to_numpy()
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]

    gross_profit = float(np.sum(wins)) if len(wins) > 0 else 0.0
    gross_loss = float(abs(np.sum(losses))) if len(losses) > 0 else 0.0

    win_rate = (len(wins) / n_trades) * 100.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

    avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
    avg_loss = float(abs(np.mean(losses))) if len(losses) > 0 else 0.0
    win_loss_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0
    expectancy = (win_rate / 100.0 * avg_win) - ((1.0 - win_rate / 100.0) * avg_loss)

    # Drawdown calculation
    peaks = np.maximum.accumulate(equity_curve)
    drawdowns = (peaks - equity_curve) / np.where(peaks > 0, peaks, 1.0) * 100.0
    max_drawdown_pct = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

    # Bars in trade / exposure
    bars_in_trade = 0
    if "entry_bar" in trades_df and "exit_bar" in trades_df:
        bars_in_trade = int(np.sum(trades_df["exit_bar"] - trades_df["entry_bar"]))
    exposure_pct = (bars_in_trade / total_bars * 100.0) if total_bars > 0 else 0.0

    # Annualization factor for Sharpe/Sortino
    bars_per_year_map = {
        "1m": 525600,
        "5m": 105120,
        "15m": 35040,
        "1h": 8760,
        "4h": 2190,
        "1d": 365,
    }
    bars_per_year = bars_per_year_map.get(timeframe, 2190)

    # Returns per bar
    eq_returns = np.diff(equity_curve) / equity_curve[:-1]
    mean_ret = np.mean(eq_returns)
    std_ret = np.std(eq_returns)

    if std_ret > 0:
        sharpe = float(mean_ret / std_ret * np.sqrt(bars_per_year))
    else:
        sharpe = 0.0

    downside_returns = eq_returns[eq_returns < 0]
    downside_std = np.std(downside_returns) if len(downside_returns) > 0 else 0.0
    if downside_std > 0:
        sortino = float(mean_ret / downside_std * np.sqrt(bars_per_year))
    else:
        sortino = 0.0

    # Approximate CAGR based on bar count
    years = total_bars / bars_per_year if bars_per_year > 0 else 1.0
    if years > 0 and final_equity > 0:
        cagr = float(((final_equity / initial_capital) ** (1.0 / years) - 1.0) * 100.0)
    else:
        cagr = 0.0

    return {
        "trades": n_trades,
        "net_profit": round(net_profit, 2),
        "net_profit_pct": round(net_profit_pct, 2),
        "cagr_pct": round(cagr, 2),
        "profit_factor": round(profit_factor, 2),
        "win_rate_pct": round(win_rate, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "win_loss_ratio": round(win_loss_ratio, 2),
        "expectancy": round(expectancy, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "exposure_pct": round(exposure_pct, 2),
    }
