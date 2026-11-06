"""Research module: sweep, walk-forward, robustness, and promotion gates."""

from stratlab.research.gates import evaluate_gates
from stratlab.research.robust import run_robustness_battery
from stratlab.research.sweep import run_sweep
from stratlab.research.walkforward import run_walkforward

__all__ = [
    "run_sweep",
    "run_walkforward",
    "run_robustness_battery",
    "evaluate_gates",
]
