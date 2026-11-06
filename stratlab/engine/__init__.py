"""StratLab core quantitative engine: indicators, conditions, sim, metrics, backtest."""

from stratlab.engine.backtest import run_backtest
from stratlab.engine.conditions import evaluate_condition_tree
from stratlab.engine.indicators import (
    atr,
    bb,
    donchian,
    ema,
    evaluate_expression,
    highest,
    lowest,
    macd,
    rma,
    rsi,
    sma,
    wma,
)
from stratlab.engine.metrics import compute_metrics
from stratlab.engine.sim import simulate

__all__ = [
    "run_backtest",
    "simulate",
    "compute_metrics",
    "evaluate_condition_tree",
    "sma",
    "ema",
    "wma",
    "rma",
    "rsi",
    "atr",
    "bb",
    "donchian",
    "highest",
    "lowest",
    "macd",
    "evaluate_expression",
]
