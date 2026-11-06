"""Walk-forward consistency bar chart."""

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def plot_walkforward_windows(
    wf_data: dict[str, Any],
    output_path: Path | str,
    title: str = "Walk-Forward Windows: In-Sample vs Out-of-Sample PF",
) -> Path:
    """Render comparison bar chart showing IS vs OOS profit factors across rolling windows."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    windows = wf_data.get("windows", [])
    if not windows:
        return out

    labels = [f"W{w['window']}\n{w['oos_start']}" for w in windows]
    is_pfs = [w["is_pf"] for w in windows]
    oos_pfs = [w["oos_pf"] for w in windows]

    x = np.arange(len(labels))
    width = 0.35

    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(9, 5))

    ax.bar(x - width / 2, is_pfs, width, label="In-Sample PF", color="#60a5fa")
    ax.bar(x + width / 2, oos_pfs, width, label="Out-of-Sample PF", color="#34d399")

    ax.axhline(1.0, color="#f43f5e", linestyle="--", alpha=0.7, label="Breakeven (1.0)")
    ax.set_ylabel("Profit Factor", fontsize=11, color="#cbd5e1")
    ax.set_title(title, fontsize=13, fontweight="bold", pad=12, color="#f8fafc")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9, color="#cbd5e1")
    ax.legend(framealpha=0.3)
    ax.grid(True, linestyle=":", alpha=0.3)

    plt.tight_layout()
    plt.savefig(out, dpi=150)
    plt.close(fig)
    return out
