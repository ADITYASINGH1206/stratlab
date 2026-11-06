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

---

## ADR-005: Research Battery, Robustness Audit & Promotion Gates (Phase 3)
- **Date**: 2026-11-06
- **Context**: Overfitting and curve-fitting are the #1 pitfall in strategy design. Retail quants need automated adversarial stress-testing.
- **Decision**: Implemented the complete research suite:
  1. `stratlab sweep`: Parallel parameter exploration with `joblib` on the in-sample slice.
  2. `stratlab walkforward`: Rolling window optimization (24-mo IS / 6-mo OOS) evaluating Walk-Forward Efficiency (WFE) and consistency.
  3. `stratlab robust`: 1,000-run Monte Carlo trade order bootstrap, 2x cost stress (fees + slippage), and parameter neighbourhood plateau stability (+-1 step).
  4. `stratlab gates`: Audit against Lab Charter standards (G1 sample size, G2 OOS performance, G3 walk-forward, G4 stability, G5 cost stress, G6 tail risk).
  5. `stratlab chart`: Visual artifact generation for Discord and reports (dark-themed equity & drawdown, heatmap, walkforward bars, and 1200x675 metrics card).
- **Consequences**: Rigorous, reproducible adversarial validation that separates fragile curve-fit strategies (`S-012 v1` fails 4 of 6 gates) from robust strategies (`S-012 v2` passes all 6 gates).

---

## ADR-006: The Skeptic audits the optimised candidate, not the defaults (Phase 6)
- **Date**: 2026-11-06
- **Context**: `gates` and `robust` ran on the spec defaults, and sweep results were never saved. The overfitting test therefore never looked at the parameters the sweep picked, which is exactly where overfitting lives.
- **Decision**: `sweep` saves its ranking and best combo (`runs/sweep_*/sweep.csv`, registry kind `sweep`). `robust` and `gates` audit the *candidate*: explicit `--params`, else the best combo of the latest sweep of the same spec content (matched by content hash), else the defaults. The source is printed with every audit. Combos with fewer than `sweep.min_trades` in-sample trades are ranked last, so a two-trade "profit factor 99" can never be the candidate.
- **Consequences**: On the bundled data, S-012 v1 fails 4 gates and S-012 v2 fails 3. The earlier claim that "v2 passes all 6" does not hold once the optimised parameters are audited. 24 further RSI-reclaim variants were tried while checking this; none passed, and mining more variants until one does would itself be overfitting, so the demo now ends with v1 killed and v2 parked.

## ADR-007: One runner, indicators on full history
- **Date**: 2026-11-06
- **Decision**: `stratlab.engine.runner` is the only path from (spec, params, window) to trades. Backtest, sweep, walk-forward, robustness and parity all use it. Indicators are computed once on all history up to the period end and then sliced, as on a TradingView chart, so out-of-sample and walk-forward windows keep their warm-up (previously each OOS slice lost about 200 bars to EMA(200)). ATR stops use the first indicator with `fn: atr`, whatever it is named.

## ADR-008: Fill-model fixes for TradingView parity
- **Date**: 2026-11-06
- **Decision**: (1) An entry needs a flat position at the signal bar's close; previously a stop hit intrabar on bar k could be "refilled" at bar k's open, an impossible fill. (2) Limit (target) fills get no slippage, as in TradingView. (3) Trade P&L includes both commissions. (4) The Pine generator sets stop and target from `strategy.position_avg_price` and `atr[1]` on the bar the entry fills, which is what the engine does; previously Pine used the signal bar's close. Comparisons are hoisted to global variables because Pine v6 evaluates `and`/`or` lazily.

## ADR-009: The validator only accepts what both engine and Pine implement
- **Date**: 2026-11-06
- **Decision**: `macd`, `bb`, `donchian`, `stoch`, `adx` and `vwap` are rejected with a hint (the engine had some, Pine had none, and some were in neither). `direction: short|both` is rejected (the sim is long-only). `opposite_signal` requires `entry.short`. All `$param` references are checked, lengths must be integer params, unknown keys are errors, and `expr` is parsed with an AST whitelist instead of `eval()`, because specs can be written by anyone in the room. S-001 (never exited) and S-020 (could never enter: `close` cannot exceed a channel that includes the current high) are fixed.

## ADR-010: No fabricated TradingView export
- **Date**: 2026-11-06
- **Context**: `fixtures/tv_trades_S-012_v2.csv` was generated from the engine (Run-up and Drawdown all zero, Python float artefacts in the cumulative column), so the "71/71 parity PASS" test compared the engine with itself.
- **Decision**: It is removed. The parser is tested on `fixtures/tv_format_sample.csv`, a hand-written file in TradingView's current header layout, labelled as a format sample. The matcher is tested by writing the engine's trades in TradingView's layout and requiring 100%, which the test names as a self-check. Real parity will be reported only from a real export.

## ADR-011: Agents share one workspace and one CLI path
- **Date**: 2026-11-06
- **Decision**: Specs are created with `stratlab spec new` in `~/stratlab-home/specs`, and references like `S-012@v2` resolve there first, then in the repo examples, from any working directory. Before, the Strategist wrote specs inside its own clone, where the other agents could not see them. `make setup` creates `~/stratlab-home/bin/stratlab`, and every agent calls that path, so nothing depends on a session's PATH. A shared preamble (`switch/agents/_common.md`) is appended to every agent's instructions, and the Lab Charter's gate table is generated from `charter_default.yaml`.

## ADR-012: The StratLab Desk is a static page
- **Date**: 2026-11-06
- **Decision**: `stratlab ui` writes one self-contained HTML file with the data embedded as JSON and every chart drawn as inline SVG. There is no server, framework or CDN, so it opens offline, can be attached in the room by the Scribe, and is reproducible for judges. The chat stays the live interface; the desk is the case file.
