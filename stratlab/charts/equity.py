"""Dark-themed equity and drawdown chart generator using matplotlib."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def plot_equity_and_drawdown(
    df: pd.DataFrame,
    equity_curve: np.ndarray,
    output_path: Path | str,
    title: str = "Strategy Equity & Drawdown",
) -> Path:
    """Render high-resolution dark-themed equity and underwater drawdown chart."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    n_bars = len(equity_curve)
    timestamps = df["timestamp"].iloc[:n_bars]

    peaks = np.maximum.accumulate(equity_curve)
    drawdown_pct = (peaks - equity_curve) / np.where(peaks > 0, peaks, 1.0) * 100.0

    plt.style.use("dark_background")
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(10, 6), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )

    # 1. Equity curve
    ax1.plot(timestamps, equity_curve, color="#38bdf8", linewidth=1.5, label="Portfolio Equity")
    ax1.plot(timestamps, peaks, color="#94a3b8", linestyle="--", linewidth=1.0, alpha=0.6, label="Peak Equity")
    ax1.set_title(title, fontsize=13, fontweight="bold", pad=10, color="#f8fafc")
    ax1.set_ylabel("Equity ($)", fontsize=10, color="#cbd5e1")
    ax1.grid(True, linestyle=":", alpha=0.3)
    ax1.legend(loc="upper left", framealpha=0.3)

    # 2. Underwater drawdown
    ax2.fill_between(timestamps, -drawdown_pct, 0, color="#f43f5e", alpha=0.4, label="Drawdown %")
    ax2.plot(timestamps, -drawdown_pct, color="#f43f5e", linewidth=1.0)
    ax2.set_ylabel("Drawdown %", fontsize=10, color="#cbd5e1")
    ax2.set_xlabel("Date", fontsize=10, color="#cbd5e1")
    ax2.grid(True, linestyle=":", alpha=0.3)

    plt.tight_layout()
    plt.savefig(out, dpi=150)
    plt.close(fig)
    return out
