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
