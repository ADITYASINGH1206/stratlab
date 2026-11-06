# StratLab Lab Charter

StratLab turns trading ideas into specs, Pine Script and backtests, then tries to break them before a human decides. It is a research tool, not financial advice, and it never places orders.

## Protocol
1. A human posts an idea in #lab, mentioning `@strategist`.
2. `@strategist` writes and validates a StrategySpec, then hands off to `@pine-coder` and `@backtester`.
3. `@pine-coder` generates Pine Script v6 for TradingView. `@backtester` runs the baseline, a parameter sweep and a walk-forward.
4. `@skeptic` audits the candidate, which is the sweep's best in-sample combo, against the six gates below.
5. On FAIL, `@strategist` makes the smallest revision. After three versions with no human message, the desk stops and waits.
6. Only a human ends a thread, by replying `promote`, `kill` or `park`. `@scribe` records it in the Strategy Ledger.

## Promotion gates
{{GATES_TABLE}}

These are reasonable starting values, not industry standards. The numbers live in `~/stratlab-home/charter.yaml`; edit them there, or ask the Skeptic to use a different value for one review with `--set`.

## Cost and execution assumptions
- Commission 0.1% per side and 1 tick of slippage, unless the spec says otherwise.
- 100% of equity per trade, long only, one position at a time.
- Signals on bar close, market orders at the next open, intrabar stops and targets by TradingView's broker-emulator rule.
