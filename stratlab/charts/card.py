"""Discord 1200x675 summary card generator with dark styling."""

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def render_metrics_card(
    spec_id: str,
    version: int,
    metrics: dict[str, Any],
    equity_curve: np.ndarray | None,
    output_path: Path | str,
) -> Path:
    """Render a 1200x675 PNG metrics card optimized for Discord embeds."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # 1200 x 675 at 100 dpi is 12 x 6.75 inches
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(12, 6.75), dpi=100)

    # Background card styling
    fig.patch.set_facecolor("#0f172a")

    # Header
    plt.text(
        0.05, 0.88,
        f"STRATLAB // {spec_id} v{version}",
        fontsize=24, fontweight="bold", color="#38bdf8",
    )
    plt.text(
        0.05, 0.82,
        "Quantitative Research Verification & Risk Audit",
        fontsize=12, color="#94a3b8",
    )

    # Metrics Grid
    m_is = metrics.get("in_sample", metrics)
    m_oos = metrics.get("out_of_sample", {})

    stats = [
        ("Net Return", f"{m_is.get('net_profit_pct', 0.0):+.1f}%", f"{m_oos.get('net_profit_pct', 0.0):+.1f}%" if m_oos else "N/A"),
        ("Profit Factor", f"{m_is.get('profit_factor', 0.0):.2f}", f"{m_oos.get('profit_factor', 0.0):.2f}" if m_oos else "N/A"),
        ("Win Rate", f"{m_is.get('win_rate_pct', 0.0):.1f}%", f"{m_oos.get('win_rate_pct', 0.0):.1f}%" if m_oos else "N/A"),
        ("Max Drawdown", f"{m_is.get('max_drawdown_pct', 0.0):.1f}%", f"{m_oos.get('max_drawdown_pct', 0.0):.1f}%" if m_oos else "N/A"),
        ("Sharpe Ratio", f"{m_is.get('sharpe_ratio', 0.0):.2f}", f"{m_oos.get('sharpe_ratio', 0.0):.2f}" if m_oos else "N/A"),
        ("Trades Count", f"{m_is.get('trades', 0)}", f"{m_oos.get('trades', 0)}" if m_oos else "N/A"),
    ]

    col_x = [0.05, 0.35, 0.65]
    row_y = [0.68, 0.52]

    idx = 0
    for r, y in enumerate(row_y):
        for c, x in enumerate(col_x):
            if idx < len(stats):
                label, is_val, oos_val = stats[idx]
                plt.text(x, y + 0.06, label.upper(), fontsize=10, fontweight="bold", color="#64748b")
                plt.text(x, y, is_val, fontsize=18, fontweight="bold", color="#f8fafc")
                plt.text(x, y - 0.04, f"OOS: {oos_val}", fontsize=10, color="#a855f7")
                idx += 1

    # Bottom sparkline
    if equity_curve is not None and len(equity_curve) > 1:
        ax = fig.add_axes([0.05, 0.10, 0.90, 0.25])
        ax.set_facecolor("#1e293b")
        ax.plot(equity_curve, color="#38bdf8", linewidth=1.5)
        ax.axis("off")

    plt.savefig(out, facecolor=fig.get_facecolor(), dpi=100)
    plt.close(fig)
    return out
