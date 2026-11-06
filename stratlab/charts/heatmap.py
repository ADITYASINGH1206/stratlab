"""2D parameter optimization heatmap chart."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def plot_param_heatmap(
    sweep_df: pd.DataFrame,
    param_x: str,
    param_y: str,
    metric: str,
    output_path: Path | str,
    title: str = "Parameter Optimization Heatmap",
) -> Path:
    """Render 2D heatmap for sweep results across two tunable parameters."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    pivot_table = sweep_df.pivot_table(index=param_y, columns=param_x, values=metric, aggfunc="mean")

    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(8, 6))

    cax = ax.imshow(
        pivot_table.values,
        cmap="viridis",
        aspect="auto",
        origin="lower",
    )

    ax.set_xticks(range(len(pivot_table.columns)))
    ax.set_xticklabels([str(c) for c in pivot_table.columns], rotation=45, color="#cbd5e1")
    ax.set_yticks(range(len(pivot_table.index)))
    ax.set_yticklabels([str(r) for r in pivot_table.index], color="#cbd5e1")

    ax.set_xlabel(param_x, fontsize=11, color="#f8fafc")
    ax.set_ylabel(param_y, fontsize=11, color="#f8fafc")
    ax.set_title(title, fontsize=13, fontweight="bold", pad=12, color="#f8fafc")

    cbar = fig.colorbar(cax, ax=ax)
    cbar.set_label(metric.replace("_", " ").title(), color="#cbd5e1")

    plt.tight_layout()
    plt.savefig(out, dpi=150)
    plt.close(fig)
    return out
