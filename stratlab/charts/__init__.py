"""Charting and visual artifact generators for StratLab."""

from stratlab.charts.card import render_metrics_card
from stratlab.charts.equity import plot_equity_and_drawdown
from stratlab.charts.heatmap import plot_param_heatmap
from stratlab.charts.walkforward import plot_walkforward_windows

__all__ = [
    "plot_equity_and_drawdown",
    "plot_param_heatmap",
    "plot_walkforward_windows",
    "render_metrics_card",
]
