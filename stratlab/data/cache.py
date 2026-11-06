"""Local Parquet caching for historical OHLCV market data."""

from pathlib import Path

import pandas as pd

from stratlab.config import get_data_dir

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SAMPLE_DATA_DIR = PROJECT_ROOT / "sample_data"


def get_cache_filename(symbol: str, timeframe: str) -> str:
    """Format standardized filename, e.g. BTCUSDT_4h.parquet."""
    clean_sym = symbol.replace("/", "").replace(":", "_").upper()
    return f"{clean_sym}_{timeframe}.parquet"


def resolve_data_file(symbol: str, timeframe: str) -> Path | None:
    """Look for cached data file in user STRATLAB_HOME or repo sample_data."""
    filename = get_cache_filename(symbol, timeframe)

    # Check STRATLAB_HOME/data
    home_path = get_data_dir() / filename
    if home_path.exists():
        return home_path

    # Check project sample_data
    sample_path = SAMPLE_DATA_DIR / filename
    if sample_path.exists():
        return sample_path

    # Check for wildcards like BTCUSDT_4h_2021_2025.parquet in sample_data
    clean_sym = symbol.replace("/", "").replace(":", "_").upper()
    prefix = f"{clean_sym}_{timeframe}"
    if SAMPLE_DATA_DIR.exists():
        for f in SAMPLE_DATA_DIR.glob(f"{prefix}*.parquet"):
            return f

    return None


def save_ohlcv(df: pd.DataFrame, symbol: str, timeframe: str, destination_dir: Path | None = None) -> Path:
    """Save an OHLCV dataframe to Parquet cache."""
    target_dir = destination_dir or get_data_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / get_cache_filename(symbol, timeframe)

    # Ensure correct columns and sorted by timestamp
    required_cols = ["timestamp", "open", "high", "low", "close", "volume"]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Missing required OHLCV column: {col}")

    clean_df = df[required_cols].copy()
    clean_df["timestamp"] = pd.to_datetime(clean_df["timestamp"])
    clean_df = clean_df.sort_values("timestamp").reset_index(drop=True)
    clean_df.to_parquet(file_path, engine="pyarrow", index=False)
    return file_path


def load_ohlcv(symbol: str, timeframe: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
    """Load cached OHLCV dataframe, filtered by date range if provided."""
    file_path = resolve_data_file(symbol, timeframe)
    if not file_path or not file_path.exists():
        raise FileNotFoundError(
            f"No cached data found for {symbol} ({timeframe}). Run `stratlab data fetch {symbol} {timeframe}` first."
        )

    df = pd.read_parquet(file_path, engine="pyarrow")
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    if start_date:
        start_ts = pd.to_datetime(start_date)
        df = df[df["timestamp"] >= start_ts]

    if end_date:
        end_ts = pd.to_datetime(end_date)
        df = df[df["timestamp"] <= end_ts]

    return df.reset_index(drop=True)
