"""Configuration and workspace paths for StratLab."""

import os
from pathlib import Path

# Default workspace directory in user home
DEFAULT_HOME = Path.home() / "stratlab-home"


def get_stratlab_home() -> Path:
    """Return the base STRATLAB_HOME path from environment or default."""
    env_home = os.environ.get("STRATLAB_HOME")
    if env_home:
        return Path(env_home).expanduser().resolve()
    return DEFAULT_HOME


def get_specs_dir() -> Path:
    """Directory where strategy specs live."""
    return get_stratlab_home() / "specs"


def get_runs_dir() -> Path:
    """Directory where backtest runs and artifacts live."""
    return get_stratlab_home() / "runs"


def get_data_dir() -> Path:
    """Directory where downloaded and cached OHLCV Parquet files live."""
    return get_stratlab_home() / "data"


def get_artifacts_dir() -> Path:
    """Directory where rendered charts, heatmaps, and summaries live."""
    return get_stratlab_home() / "artifacts"


def get_registry_db() -> Path:
    """Path to the SQLite registry file."""
    return get_stratlab_home() / "registry.sqlite"


def init_environment() -> None:
    """Ensure all required workspace directories exist."""
    for directory in [
        get_stratlab_home(),
        get_specs_dir(),
        get_runs_dir(),
        get_data_dir(),
        get_artifacts_dir(),
    ]:
        directory.mkdir(parents=True, exist_ok=True)
