# StratLab Demo Video Script (3 Minutes)

**Event**: Flip the Switch Hackathon (WeMakeDevs & DevTools Academy, Nov 2026)  
**Track**: Track 2 — Best Personal or Creative Workflow ($2,000)  
**Target Runtime**: 3:00  

---

## High-Concept Hook (0:00 – 0:25)

**Visual**: Switch Console open with Discord / Mattermost side-by-side with TradingView and terminal.  
**Voiceover**:
> "Every retail trader knows the pain: you have an idea, you code it up in TradingView, curve-fit the parameters until the equity curve looks like a hockey stick, and lose money the moment you turn it on. Solo traders skip the quantitative discipline because it takes hours.
> 
> Meet **StratLab**: an adversarial, 5-agent quantitative research desk living inside a single Switch room. You propose the idea. The desk specs it, generates Pine Script v6, backtests it, optimizes it, and then ruthlessly tries to break it. You decide whether it lives."

---

## Act 1: The Raw Idea & The Skeptic Rejection (0:25 – 1:15)

**Visual**: Discord `#lab` channel. Trader `@Aditya` types:
`@strategist idea: BTCUSDT 4h, long when RSI(9) crosses above 30 and close > EMA(200). Stop 2x ATR, target 3x ATR.`

**Action Flow**:
1. **`@strategist`** validates the idea, drafts `specs/S-012/v1.yaml` in the shared workspace, and hands off:
   `@pine-coder @backtester S-012@v1 ready.`
2. **`@pine-coder`** generates `artifacts/S-012_v1.pine` matching the exact StrategySpec.
3. **`@backtester`** runs baseline backtest, 120-combination parameter sweep, and walk-forward analysis.
   - Posts metrics: IS PF 1.71, but OOS PF collapses to 0.68.
   - Hands off: `@skeptic review S-012@v1`.
4. **`@skeptic`** (The Hero Moment):
   - Audits the 6 Lab Charter promotion gates.
   - **Verdict**: `REJECTED (FAIL 2/6)`.
   - Explains *why*: high turnover in chop, negative walk-forward efficiency (-0.20), and fails 2x cost stress test.
   - Tells `@strategist`: *"Failed G1, G2, G3, G6. Add a regime filter and dynamic exits."*

---

## Act 2: Iteration & TradingView Parity (1:15 – 2:05)

**Visual**: `@strategist` creates `S-012@v2`.

**Action Flow**:
1. **`@strategist`** posts spec diff:
   - Fixed trend entry (EMA 12/100 cross with RSI > 40)
   - Dynamic ATR trailing stops ($1.5 \times ATR$) and targets ($3.5 \times ATR$)
2. **`@pine-coder`** generates Pine Script v6 strategy.
3. **TradingView Parity Verification**:
   - Backtester runs `stratlab parity S-012@v2 fixtures/tv_format_sample.csv`.
   - Demonstrates trade-by-trade broker emulator matching (fills at next bar open, intrabar path emulation).
4. **`@skeptic`** re-audits the candidate:
   - WFE improves, cost stress test passes, stability passes.
   - Hands off to human: *"Waiting on a human: promote, kill or park?"*

---

## Act 3: The Human Gate, Strategy Ledger & The Desk (2:05 – 3:00)

**Visual**: Human replies `park` (or `promote`).

**Action Flow**:
1. **Human Decision**: `@Aditya` replies `park` in chat.
2. **`@scribe`**:
   - Records the verdict in SQLite registry (`stratlab ledger add`).
   - Updates the pinned **Strategy Ledger** document in Switch.
   - Posts strategy card to `#ledger`.
3. **The StratLab Desk UI**:
   - Scribe runs `stratlab ui` and shares `stratlab-desk.html`.
   - We open `stratlab-desk.html` in the browser: an interactive, dark-themed offline case file displaying:
     - All 6 quantitative gates with radar/bar indicators
     - Interactive SVG equity curves and drawdowns
     - Walk-forward rolling windows & parameter heatmaps
     - Copyable Pine Script v6 code block
4. **Closing Summary**:
   > "Without Switch, this would be a generic chatbot. With Switch's shared room, role hierarchy, room documents, and persistent memory, StratLab gives retail quants an entire hedge fund research desk right in their chat."

---

## Key Assets Shown in Video
- Switch Console running 5 Claude Code agents
- Discord / Mattermost UI with colored webhooks
- TradingView Pine Editor with generated v6 script
- Interactive StratLab Desk (`docs/stratlab-desk-demo.html` / `artifacts/stratlab-desk.html`)
- SQLite Strategy Ledger document

