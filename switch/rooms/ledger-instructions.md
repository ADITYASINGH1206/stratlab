# StratLab Ledger Room Instructions

This room (`#ledger`) is the clean, read-only broadcast and audit feed for finalized strategy decisions.

## Room Policies
- **Read-Only Feed**: Only `@scribe` and `@strategist` post top-level strategy cards to keep this channel unpolluted.
- **Card Format**: Each promoted, killed, or parked strategy receives a standardized card containing:
  - Strategy ID and Version
  - Verdict Badge (`🟢 PROMOTE`, `🔴 KILL`, `🟡 PARK`)
  - Author and Deciding Trader
  - Out-of-sample metrics (PF, Max Drawdown, Win Rate)
  - Core thesis or primary failure reason
- **Inquiries**: Anyone may ask `@scribe` questions about strategy track records, past versions, or failure statistics. `@scribe` will answer strictly using `stratlab ledger query` and the Strategy Ledger document.
