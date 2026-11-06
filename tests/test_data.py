"""Tests for market data caching and loading."""

import pandas as pd

from stratlab.data.cache import load_ohlcv, resolve_data_file, save_ohlcv


def test_resolve_sample_data():
    sample_file = resolve_data_file("BTCUSDT", "4h")
    assert sample_file is not None
    assert sample_file.exists()
    assert "BTCUSDT_4h" in sample_file.name


def test_load_sample_data():
    df = load_ohlcv("BTCUSDT", "4h")
    assert not df.empty
    assert len(df) > 1000
    for col in ["timestamp", "open", "high", "low", "close", "volume"]:
        assert col in df.columns


def test_load_sample_data_filtered():
    df = load_ohlcv("BTCUSDT", "4h", start_date="2022-01-01", end_date="2022-12-31")
    assert not df.empty
    assert df["timestamp"].min() >= pd.to_datetime("2022-01-01")
    assert df["timestamp"].max() <= pd.to_datetime("2022-12-31 23:59:59")


def test_save_and_load_roundtrip(tmp_path):
    dates = pd.date_range("2024-01-01", periods=10, freq="4h")
    data = {
        "timestamp": dates,
        "open": [100.0 + i for i in range(10)],
        "high": [105.0 + i for i in range(10)],
        "low": [95.0 + i for i in range(10)],
        "close": [102.0 + i for i in range(10)],
        "volume": [1000.0 for _ in range(10)],
    }
    dummy_df = pd.DataFrame(data)

    saved_path = save_ohlcv(dummy_df, "ETHUSDT", "4h", destination_dir=tmp_path)
    assert saved_path.exists()
    assert saved_path.name == "ETHUSDT_4h.parquet"

    loaded_df = pd.read_parquet(saved_path)
    assert len(loaded_df) == 10
    assert loaded_df["close"].iloc[0] == 102.0
