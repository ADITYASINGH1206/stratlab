# StratLab #lab

Post an idea and the desk specs it, codes it, tests it and attacks it. You decide if it lives.

## How it runs
1. Start: `@strategist idea: BTCUSDT 4h, long when RSI(14) crosses above 30 and close > EMA(200); stop 2 ATR, target 3 ATR`.
2. `@strategist` writes the spec and hands off to `@pine-coder` and `@backtester`.
3. `@backtester` runs the numbers and hands off to `@skeptic`.
4. `@skeptic` audits gates G1 to G6 from the Lab Charter. On FAIL, `@strategist` revises, up to 3 versions without a human message. On PASS, the desk waits for you.
5. Reply `promote`, `kill` or `park`. `@scribe` records it and posts a card in #ledger.

## Rules for agents
- One thread per strategy; the spec ID goes in the first line.
- End each message with exactly one hand-off line, or `Waiting on a human.`
- Every number cites its run id. Never estimate a metric.
- Only a human message containing promote, kill or park ends a thread.
- Use `@quant-on-call` for a quick "can someone run numbers on X".
- Hand off with @mentions and files. Do not use Switch task operations (`delegate_task` and the like): Switch marks them as not ready for use.
