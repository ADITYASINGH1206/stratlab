"""Market data fetching via public CCXT (Binance) and yfinance fallback."""

import time
from datetime import datetime, timezone
from pathlib import Path

import ccxt
import pandas as pd
import yfinance as yf

from stratlab.data.cache import save_ohlcv


def _parse_date_to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def fetch_binance_ohlcv(
    symbol: str,
    timeframe: str = "4h",
    start_date: str = "2021-01-01",
    end_date: str | None = None,
    limit_per_call: int = 1000,
) -> pd.DataFrame:
    """Fetch historical OHLCV from Binance public API using CCXT."""
    # Standardize symbol, e.g. BTCUSDT -> BTC/USDT
    ccxt_symbol = symbol
    if "/" not in ccxt_symbol and ccxt_symbol.endswith("USDT"):
        base = ccxt_symbol[:-4]
        ccxt_symbol = f"{base}/USDT"

    exchange = ccxt.binance({"enableRateLimit": True})
    since = _parse_date_to_ms(start_date)
    end_ms = _parse_date_to_ms(end_date) if end_date else int(time.time() * 1000)

    all_ohlcv: list[list[float]] = []

    while since < end_ms:
        try:
            records = exchange.fetch_ohlcv(ccxt_symbol, timeframe=timeframe, since=since, limit=limit_per_call)
        except Exception as e:
            # If Binance is blocked or fails, raise so fallback can be attempted
            raise RuntimeError(f"CCXT Binance fetch failed: {e}") from e

        if not records:
            break

        all_ohlcv.extend(records)
        last_timestamp = records[-1][0]

        if last_timestamp <= since:
            break

        since = last_timestamp + 1
        time.sleep(0.05)  # Respect rate limit

    if not all_ohlcv:
        raise ValueError(f"No OHLCV records returned from Binance for {symbol} ({timeframe})")

    df = pd.DataFrame(all_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    if end_date:
        end_ts = pd.to_datetime(end_date)
        df = df[df["timestamp"] <= end_ts]

    return df.reset_index(drop=True)


def fetch_yfinance_ohlcv(symbol: str, timeframe: str = "4h", start_date: str = "2021-01-01", end_date: str | None = None) -> pd.DataFrame:
    """Fallback fetcher using yfinance for crypto or equity symbols."""
    # Convert crypto symbol, e.g. BTCUSDT -> BTC-USD
    clean_sym = symbol.replace("/", "").upper()
    if clean_sym.endswith("USDT"):
        yf_sym = clean_sym.replace("USDT", "-USD")
    else:
        yf_sym = clean_sym

    # yfinance timeframes: 1h, 1d (4h is not natively supported in yfinance, so resample from 1h if needed)
    yf_interval = "1h" if timeframe in ("1h", "4h") else "1d"

    ticker = yf.Ticker(yf_sym)
    hist = ticker.history(start=start_date, end=end_date, interval=yf_interval)
    if hist.empty:
        raise ValueError(f"yfinance returned no data for {yf_sym}")

    hist = hist.reset_index()
    hist.rename(
        columns={
            "Datetime": "timestamp",
            "Date": "timestamp",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        },
        inplace=True,
    )
    hist["timestamp"] = pd.to_datetime(hist["timestamp"]).dt.tz_localize(None)

    if timeframe == "4h":
        hist = hist.set_index("timestamp").resample("4h").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna().reset_index()

    return hist[["timestamp", "open", "high", "low", "close", "volume"]]


def fetch_and_cache_ohlcv(
    symbol: str,
    timeframe: str = "4h",
    start_date: str = "2021-01-01",
    end_date: str | None = None,
    destination_dir: Path | None = None,
) -> Path:
    """Fetch OHLCV data using CCXT (Binance) with yfinance fallback, and write Parquet cache."""
    try:
        df = fetch_binance_ohlcv(symbol, timeframe, start_date, end_date)
    except Exception as e:
        # Fallback to yfinance
        try:
            df = fetch_yfinance_ohlcv(symbol, timeframe, start_date, end_date)
        except Exception as yf_err:
            raise RuntimeError(f"Failed to fetch data for {symbol} via CCXT ({e}) and yfinance ({yf_err})")

    file_path = save_ohlcv(df, symbol, timeframe, destination_dir=destination_dir)
    return file_path
