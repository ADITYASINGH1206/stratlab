# StratLab Architectural Decisions Log (ADR)

This document records architectural decisions made during development when choices are taken or the plan is silent.

---

## ADR-001: Initial Repository & CI/CD Structure
- **Date**: 2026-11-06
- **Context**: Project initialization for Track 2 Flip the Switch Hackathon.
- **Decision**: Public repository `ADITYASINGH1206/stratlab` created with `main` branch protection. All development proceeds strictly through phased feature branches and Pull Requests.
- **Consequences**: Direct pushes to `main` are prevented, establishing clean auditability and code review discipline.

---

## ADR-002: StrategySpec Schema & Vocabulary Validation (Phase 1)
- **Date**: 2026-11-06
- **Context**: Need a single source of truth that compiles to both TradingView Pine Script v6 and Python simulation.
- **Decision**: Implemented `StrategySpec` in Pydantic v2. Parameter values can be referenced dynamically using `$param_name` in indicator lengths, multipliers, stop ATR multiples, etc. The spec validator enforces that every `$param` is declared in `spec.params` and every series referenced in entry/exit rules is either in OHLCV or defined in `spec.indicators`.
- **Consequences**: Invalid specs fail fast at validation time before any code generation or backtesting begins.

---

## ADR-003: Market Data Fetch & Parquet Caching
- **Date**: 2026-11-06
- **Context**: Zero-API-key requirement for hackathon reproducibility and offline judge runs.
- **Decision**: Use `ccxt` connected to Binance public market endpoints to fetch OHLCV, with automatic fallback to `yfinance`. Cache fetched data into PyArrow Parquet files in `$STRATLAB_HOME/data/` or bundled `sample_data/`.
- **Consequences**: `sample_data/BTCUSDT_4h_2021_2025.parquet` is committed to the repository (498 KB), allowing the entire system to run offline with zero network or API credentials.

---

## ADR-004: TradingView Broker Emulator Parity & Simulation Loop (Phase 2)
- **Date**: 2026-11-06
- **Context**: Discrepancies between backtest engines and TradingView's Strategy Tester lead to invalid research results and parity failures.
- **Decision**: Implemented Numba `@njit` simulation loop matching TradingView's exact broker emulator:
  1. Orders generated on bar close fill at the *next bar's open*.
  2. Intrabar price path follows `Open -> High -> Low -> Close` when open is nearer high, and `Open -> Low -> High -> Close` otherwise.
  3. Stops and targets trigger along this path; price gaps fill at the bar open.
  4. Indicators match Pine Script formulas: RSI/ATR use Wilder's RMA (alpha = 1/len, seeded with SMA); EMA uses alpha = 2/(len+1) seeded with SMA.
- **Consequences**: Deterministic execution matching Pine Script v6 defaults, running >10,000 bars in under 1 second.
