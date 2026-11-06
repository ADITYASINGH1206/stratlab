# StratLab Lab Room Instructions

This room (`#lab`) is the active collaboration floor where human traders and autonomous AI quant agents interact.

## Operating Protocol
1. **Starting an Idea**:
   - Any member can post an idea: `@strategist idea: buy BTC 4h when RSI(14) crosses above 30 while close > EMA(100); stop at 1.5 ATR, target at 3.5 ATR`.
2. **Autonomous Workflow**:
   - `@strategist` creates and validates the specification, then tags `@pine-coder` and `@backtester`.
   - `@pine-coder` outputs the Pine v6 strategy and configuration summary.
   - `@backtester` runs backtest, sweep, walkforward, and charts, then tags `@skeptic`.
   - `@skeptic` performs stress tests and audits G1-G6 against the Lab Charter.
3. **Escalation & Decision**:
   - If `@skeptic` reports FAIL: `@strategist` proposes a revision (up to 3 revisions max).
   - If `@skeptic` reports PASS: Desk pauses and asks for a human verdict (`promote`, `kill`, or `park`).
4. **Execution of Verdict**:
   - Once a human replies, `@scribe` updates the Strategy Ledger and notifies `#ledger`.

## Roles & Mentions
- Use `@quant-on-call` to ask for fast numerical evaluations, backtest checks, or data inquiries.
- Never use Switch task operations (`delegate_task`); hand-offs must be conducted via explicit `@mention` tags and file links.
